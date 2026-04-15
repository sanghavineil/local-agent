#!/usr/bin/env python3
"""Manage the LiteLLM proxy that routes Claude Code traffic to local models.

The proxy is launched as a detached subprocess; its PID is recorded in a pidfile
under the user's state directory so that subsequent invocations can stop or query
it. The config file rendered by `local-agent sync` lives at
~/.config/litellm/config.yaml.
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

import sync_agent_parity


def home_dir(home_override: str | None = None) -> Path:
    return Path(home_override).expanduser() if home_override else Path.home()


def litellm_config_path(home_override: str | None = None) -> Path:
    return home_dir(home_override) / ".config" / "litellm" / "config.yaml"


def state_dir(home_override: str | None = None) -> Path:
    return home_dir(home_override) / ".local" / "state" / "local-agent"


def pidfile_path(home_override: str | None = None) -> Path:
    return state_dir(home_override) / "gateway.pid"


def logfile_path(home_override: str | None = None) -> Path:
    return state_dir(home_override) / "gateway.log"


def gateway_port(root: Path | None = None) -> int:
    root = root or sync_agent_parity.repo_root()
    manifest = sync_agent_parity.load_json(root / "manifests" / "model_providers.json")
    return manifest.get("gateway", {}).get("port", 4000)


GATEWAY_PROCESS_MARKER = "litellm"


def is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError as exc:
        return exc.errno == errno.EPERM
    return True


def process_command(pid: int) -> str | None:
    """Return the full command line for `pid` via `ps`, or None if it doesn't exist."""
    if pid <= 0:
        return None
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            timeout=2.0,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    output = result.stdout.strip()
    return output or None


def is_our_gateway(pid: int) -> bool:
    """Return True only if `pid` exists AND looks like our spawned LiteLLM proxy.

    Defends against PID reuse: after a reboot or PID rollover, the PID recorded
    in our pidfile may belong to an unrelated process. Sending SIGTERM to that
    process would be incorrect, so we require a string match against the command
    line before treating the PID as ours.
    """
    if not is_pid_alive(pid):
        return False
    cmd = process_command(pid)
    if cmd is None:
        return False
    return GATEWAY_PROCESS_MARKER in cmd


def read_pidfile(home_override: str | None = None) -> int | None:
    path = pidfile_path(home_override)
    if not path.exists():
        return None
    try:
        return int(path.read_text().strip())
    except (ValueError, OSError):
        return None


def clear_pidfile(home_override: str | None = None) -> None:
    try:
        pidfile_path(home_override).unlink()
    except FileNotFoundError:
        pass


def status(home_override: str | None = None) -> dict:
    pid = read_pidfile(home_override)
    if pid is None:
        return {"running": False, "port": gateway_port()}
    if is_our_gateway(pid):
        return {"running": True, "pid": pid, "port": gateway_port()}
    if is_pid_alive(pid):
        # PID exists but does not look like our proxy — almost certainly PID
        # reuse after a crash/reboot. Treat as not-running and refuse to signal it.
        return {
            "running": False,
            "wrong_pid_owner": pid,
            "owner_command": process_command(pid),
            "port": gateway_port(),
        }
    return {"running": False, "stale_pid": pid, "port": gateway_port()}


def start(
    home_override: str | None = None,
    launcher: list[str] | None = None,
    startup_timeout_seconds: float = 0.5,
) -> dict:
    """Start the proxy. Returns a dict describing the new state.

    `launcher` is overridable for tests; in production we shell out to the
    `litellm` CLI installed via `pip install 'litellm[proxy]'`.

    `startup_timeout_seconds` is how long we wait after spawning to confirm the
    process is still alive. If it dies within this window we raise RuntimeError
    with a tail of the log instead of writing a misleading pidfile.
    """
    state = status(home_override)
    if state["running"]:
        return {"already_running": True, **state}

    # Stale or wrong-owner pidfile — clean it up before spawning a fresh proxy.
    if "stale_pid" in state or "wrong_pid_owner" in state:
        clear_pidfile(home_override)

    config_path = litellm_config_path(home_override)
    if not config_path.exists():
        raise FileNotFoundError(
            f"{config_path} not found. Run 'local-agent sync --apply' first."
        )

    if launcher is None:
        litellm_bin = shutil.which("litellm")
        if litellm_bin is None:
            raise FileNotFoundError(
                "`litellm` not found on PATH. Install with: pip install 'litellm[proxy]'"
            )
        port = gateway_port()
        launcher = [litellm_bin, "--config", str(config_path), "--port", str(port)]

    state_dir(home_override).mkdir(parents=True, exist_ok=True)
    log_path = logfile_path(home_override)
    # Open in a `with` so the parent's fd closes immediately after spawn — the
    # child gets its own dup of fd 1/2, so closing here does not affect logging.
    with open(log_path, "ab") as log_handle:
        process = subprocess.Popen(
            launcher,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )

    # Confirm the proxy actually came up before declaring success. LiteLLM may
    # exit immediately on a port collision, malformed config, or missing runtime
    # dependency. Use `process.poll()` rather than `os.kill(pid, 0)` because the
    # latter sees zombie children as alive — `poll()` actively reaps zombies so
    # we can distinguish "still running" from "exited within the window".
    deadline = time.monotonic() + startup_timeout_seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            log_tail = _tail_file(log_path, lines=8)
            raise RuntimeError(
                f"gateway exited with code {process.returncode} within "
                f"{startup_timeout_seconds}s of launch. Log tail ({log_path}):\n"
                f"{log_tail}"
            )
        time.sleep(0.05)

    # Past the startup window — the proxy is up. Detach Python's subprocess
    # tracking so Popen.__del__ does not emit a ResourceWarning at GC. The
    # actual process keeps running under init/launchd until `stop()` signals it.
    process.returncode = 0
    pidfile_path(home_override).write_text(f"{process.pid}\n")
    return {"started": True, "pid": process.pid, "port": gateway_port(), "log": str(log_path)}


def _tail_file(path: Path, lines: int = 8) -> str:
    if not path.exists():
        return "(no log file)"
    try:
        text = path.read_text(errors="replace")
    except OSError as exc:
        return f"(could not read log: {exc})"
    return "\n".join(text.splitlines()[-lines:]) or "(empty)"


def stop(home_override: str | None = None, wait_seconds: float = 5.0) -> dict:
    pid = read_pidfile(home_override)
    if pid is None:
        return {"already_stopped": True}
    if not is_pid_alive(pid):
        clear_pidfile(home_override)
        return {"already_stopped": True, "stale_pid": pid}
    if not is_our_gateway(pid):
        # PID exists but is not our litellm proxy — almost certainly PID reuse.
        # Refuse to signal it; clear the pidfile so the user can retry from
        # a clean state. The caller surfaces this distinctly from a normal stop.
        owner = process_command(pid)
        clear_pidfile(home_override)
        return {"refused": True, "pid": pid, "owner_command": owner}

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        clear_pidfile(home_override)
        return {"already_stopped": True, "stale_pid": pid}

    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if not is_pid_alive(pid):
            break
        time.sleep(0.1)
    else:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    # If the process is our direct child (test scenarios, or whenever `start`
    # was called from the same long-lived python process), reap it so it does
    # not linger as a zombie. In normal CLI use the gateway is orphaned to
    # init/launchd, in which case waitpid raises ECHILD and we simply ignore.
    try:
        os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        pass

    clear_pidfile(home_override)
    return {"stopped": True, "pid": pid}


def format_status(state: dict) -> list[str]:
    if state.get("running"):
        return [f"gateway: running  pid={state['pid']}  port={state['port']}"]
    if "stale_pid" in state:
        return [f"gateway: not running (stale pidfile referenced pid={state['stale_pid']})"]
    if "wrong_pid_owner" in state:
        owner = state.get("owner_command") or "<unknown>"
        return [
            f"gateway: not running (pidfile points at pid={state['wrong_pid_owner']}, "
            f"which is not litellm: {owner})",
            "Run `local-agent gateway start` to clear the stale pidfile and relaunch.",
        ]
    return [f"gateway: not running  port={state['port']}"]


def format_start(state: dict) -> list[str]:
    if state.get("already_running"):
        return [f"gateway: already running  pid={state['pid']}  port={state['port']}"]
    return [
        f"gateway: started  pid={state['pid']}  port={state['port']}",
        f"log: {state['log']}",
    ]


def format_stop(state: dict) -> list[str]:
    if state.get("stopped"):
        return [f"gateway: stopped  (was pid={state['pid']})"]
    if state.get("refused"):
        owner = state.get("owner_command") or "<unknown>"
        return [
            f"gateway: refused to signal pid={state['pid']} — not our litellm proxy: {owner}",
            "Cleared the stale pidfile. Re-run `local-agent gateway start` to relaunch.",
        ]
    if state.get("already_stopped"):
        if "stale_pid" in state:
            return [f"gateway: not running  (cleared stale pidfile pid={state['stale_pid']})"]
        return ["gateway: not running"]
    return [json.dumps(state)]


def run(action: str, home_override: str | None = None, launcher: list[str] | None = None) -> list[str]:
    if action == "status":
        return format_status(status(home_override))
    if action == "start":
        return format_start(start(home_override, launcher=launcher))
    if action == "stop":
        return format_stop(stop(home_override))
    raise AssertionError(f"Unhandled gateway action: {action}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage the LiteLLM proxy used by Claude Code.")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("start", help="Start the proxy in the background.")
    sub.add_parser("stop", help="Stop the running proxy if any.")
    sub.add_parser("status", help="Report the proxy's current state.")
    parser.add_argument("--home", default=None, help="Override home directory for testing.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        for line in run(args.action, home_override=args.home):
            print(line)
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"error: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
