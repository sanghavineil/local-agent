from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import gateway  # noqa: E402


def stage_litellm_config(home: Path) -> None:
    """Pretend `local-agent sync --apply` already wrote the proxy config."""
    config_path = gateway.litellm_config_path(str(home))
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("model_list: []\n")


class GatewayLifecycleTests(unittest.TestCase):
    def test_status_when_not_running(self) -> None:
        with tempfile.TemporaryDirectory() as fake_home:
            state = gateway.status(home_override=fake_home)
            self.assertFalse(state["running"])
            self.assertEqual(state["port"], 4000)

    def test_start_without_config_raises(self) -> None:
        with tempfile.TemporaryDirectory() as fake_home:
            with self.assertRaises(FileNotFoundError):
                gateway.start(
                    home_override=fake_home,
                    launcher=["/bin/sh", "-c", "sleep 60"],
                )

    def test_start_writes_pidfile_and_status_reports_running(self) -> None:
        with tempfile.TemporaryDirectory() as fake_home:
            stage_litellm_config(Path(fake_home))
            launcher = ["/bin/sh", "-c", "sleep 30"]
            try:
                state = gateway.start(home_override=fake_home, launcher=launcher)
                self.assertTrue(state.get("started"))
                pid = state["pid"]

                pidfile = gateway.pidfile_path(fake_home)
                self.assertTrue(pidfile.exists())
                self.assertEqual(int(pidfile.read_text().strip()), pid)

                status = gateway.status(home_override=fake_home)
                self.assertTrue(status["running"])
                self.assertEqual(status["pid"], pid)
            finally:
                gateway.stop(home_override=fake_home)

    def test_start_when_already_running_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as fake_home:
            stage_litellm_config(Path(fake_home))
            launcher = ["/bin/sh", "-c", "sleep 30"]
            try:
                gateway.start(home_override=fake_home, launcher=launcher)
                second = gateway.start(home_override=fake_home, launcher=launcher)
                self.assertTrue(second.get("already_running"))
            finally:
                gateway.stop(home_override=fake_home)

    def test_stop_when_not_running_is_noop(self) -> None:
        with tempfile.TemporaryDirectory() as fake_home:
            state = gateway.stop(home_override=fake_home)
            self.assertTrue(state.get("already_stopped"))

    def test_stop_terminates_process_and_clears_pidfile(self) -> None:
        with tempfile.TemporaryDirectory() as fake_home:
            stage_litellm_config(Path(fake_home))
            launcher = ["/bin/sh", "-c", "sleep 30"]
            started = gateway.start(home_override=fake_home, launcher=launcher)
            pid = started["pid"]

            stopped = gateway.stop(home_override=fake_home)
            self.assertTrue(stopped.get("stopped"))
            self.assertFalse(gateway.pidfile_path(fake_home).exists())
            self.assertFalse(gateway.is_pid_alive(pid))

    def test_stale_pidfile_is_cleaned_up_on_status(self) -> None:
        with tempfile.TemporaryDirectory() as fake_home:
            stage_litellm_config(Path(fake_home))
            pidfile = gateway.pidfile_path(fake_home)
            pidfile.parent.mkdir(parents=True, exist_ok=True)
            # PID 999999 is overwhelmingly unlikely to be alive.
            pidfile.write_text("999999\n")

            state = gateway.status(home_override=fake_home)
            self.assertFalse(state["running"])
            self.assertEqual(state["stale_pid"], 999999)

    def test_start_clears_stale_pidfile_before_launching(self) -> None:
        with tempfile.TemporaryDirectory() as fake_home:
            stage_litellm_config(Path(fake_home))
            pidfile = gateway.pidfile_path(fake_home)
            pidfile.parent.mkdir(parents=True, exist_ok=True)
            pidfile.write_text("999999\n")

            launcher = ["/bin/sh", "-c", "sleep 30"]
            try:
                state = gateway.start(home_override=fake_home, launcher=launcher)
                self.assertTrue(state.get("started"))
                self.assertNotEqual(state["pid"], 999999)
            finally:
                gateway.stop(home_override=fake_home)


if __name__ == "__main__":
    unittest.main()
