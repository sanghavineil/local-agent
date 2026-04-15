from __future__ import annotations

import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import doctor  # noqa: E402
import init_project  # noqa: E402
import sync_agent_parity  # noqa: E402


def dummy_machine_state() -> dict:
    return {
        "active_profile": "work",
        "profiles": {
            "work": {
                "mcp_env": {
                    "FIGMA_API_KEY": "figma-test",
                    "JIRA_HOST": "https://example.atlassian.net",
                    "JIRA_EMAIL": "neil@example.com",
                    "JIRA_API_TOKEN": "jira-test",
                },
                "model_profile": "anthropic-cloud",
                "mcp_servers": ["figma", "atlassian-jira", "playwright"],
            }
        },
    }


def local_profile_machine_state() -> dict:
    return {
        "active_profile": "local",
        "profiles": {
            "local": {
                "mcp_env": {},
                "model_profile": "ollama-qwen",
                "mcp_servers": [],
            }
        },
    }


class DoctorTests(unittest.TestCase):
    def test_check_home_is_clean_after_sync(self) -> None:
        with tempfile.TemporaryDirectory() as temp_home:
            with patch.object(sync_agent_parity, "load_machine_state", return_value=dummy_machine_state()):
                sync_agent_parity.run_sync(apply=True, home_override=temp_home)
                actions, warnings = doctor.check_home(home_override=temp_home)

            self.assertFalse(actions)
            self.assertFalse(warnings)

    def test_check_project_reports_missing_files(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            issues = doctor.check_project(Path(tempdir))

        self.assertTrue(any(issue.kind == "missing" and issue.path.name == "AGENTS.md" for issue in issues))
        self.assertTrue(any(issue.kind == "missing" and issue.path.name == "CLAUDE.md" for issue in issues))

    def test_check_project_detects_baseline_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            project_root = Path(tempdir)
            init_project.run_init_project(
                project_root=project_root,
                apply=True,
                force=False,
                with_impeccable_template=False,
            )

            agents_path = project_root / "AGENTS.md"
            drifted = agents_path.read_text().replace("Operate in caveman mode", "Operate in old mode")
            agents_path.write_text(drifted)

            issues = doctor.check_project(project_root)

        self.assertTrue(any(issue.kind == "drift" and issue.path.name == "AGENTS.md" for issue in issues))


class GatewayPortProbeTests(unittest.TestCase):
    def test_no_warning_when_active_profile_is_anthropic_direct(self) -> None:
        with tempfile.TemporaryDirectory() as temp_home:
            with patch.object(
                sync_agent_parity, "load_machine_state", return_value=dummy_machine_state()
            ):
                # Even if the port is bound by something, doctor must stay silent
                # because the work profile uses anthropic-direct (no proxy needed).
                blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                blocker.bind(("127.0.0.1", 0))
                blocker.listen(1)
                blocker_port = blocker.getsockname()[1]
                try:
                    with patch.object(
                        doctor.gateway, "gateway_port", return_value=blocker_port
                    ):
                        warnings = doctor.probe_gateway_port(temp_home)
                finally:
                    blocker.close()
            self.assertEqual(warnings, [])

    def test_warns_when_proxy_profile_active_and_port_bound_by_other(self) -> None:
        with tempfile.TemporaryDirectory() as temp_home:
            blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            blocker.bind(("127.0.0.1", 0))
            blocker.listen(1)
            blocker_port = blocker.getsockname()[1]
            try:
                # Patch the providers manifest via load_json to swap port,
                # and patch machine_state to use the local proxy profile.
                real_load_json = sync_agent_parity.load_json

                def patched_load_json(path):
                    data = real_load_json(path)
                    if path.name == "model_providers.json":
                        data = dict(data)
                        data["gateway"] = {**data.get("gateway", {}), "port": blocker_port}
                    return data

                with patch.object(
                    sync_agent_parity, "load_machine_state", return_value=local_profile_machine_state()
                ), patch.object(sync_agent_parity, "load_json", side_effect=patched_load_json):
                    warnings = doctor.probe_gateway_port(temp_home)
            finally:
                blocker.close()

            kinds = [w.kind for w in warnings]
            self.assertIn("port-in-use", kinds)

    def test_no_warning_when_port_free(self) -> None:
        with tempfile.TemporaryDirectory() as temp_home:
            # Pick a port, bind+release to ensure it's likely free, then probe.
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.bind(("127.0.0.1", 0))
            free_port = sock.getsockname()[1]
            sock.close()

            real_load_json = sync_agent_parity.load_json

            def patched_load_json(path):
                data = real_load_json(path)
                if path.name == "model_providers.json":
                    data = dict(data)
                    data["gateway"] = {**data.get("gateway", {}), "port": free_port}
                return data

            with patch.object(
                sync_agent_parity, "load_machine_state", return_value=local_profile_machine_state()
            ), patch.object(sync_agent_parity, "load_json", side_effect=patched_load_json):
                warnings = doctor.probe_gateway_port(temp_home)

            kinds = [w.kind for w in warnings]
            self.assertNotIn("port-in-use", kinds)


if __name__ == "__main__":
    unittest.main()
