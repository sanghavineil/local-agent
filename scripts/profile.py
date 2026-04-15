#!/usr/bin/env python3
"""Manage which profile in config/machine.local.json is active."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

import sync_agent_parity


def machine_local_path() -> Path:
    return sync_agent_parity.repo_root() / "config" / "machine.local.json"


def load_machine_local() -> dict:
    path = machine_local_path()
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Run 'local-agent bootstrap --init-machine-local' first."
        )
    return json.loads(path.read_text())


def write_machine_local(state: dict) -> None:
    machine_local_path().write_text(json.dumps(state, indent=2) + "\n")


def require_profiled_state(state: dict) -> dict:
    if "profiles" not in state:
        raise ValueError(
            "machine.local.json uses the legacy flat schema. "
            "Migrate to the profile-keyed shape (see config/machine.example.json) "
            "before using `local-agent profile`."
        )
    return state["profiles"]


def cmd_list(state: dict) -> list[str]:
    profiles = require_profiled_state(state)
    active = state.get("active_profile")
    lines: list[str] = []
    for name in sorted(profiles):
        marker = "* " if name == active else "  "
        lines.append(f"{marker}{name}")
    return lines


def cmd_show(state: dict, name: str | None) -> list[str]:
    profiles = require_profiled_state(state)
    target = name or state.get("active_profile")
    if target is None:
        raise ValueError("No profile specified and no active_profile is set.")
    if target not in profiles:
        raise ValueError(f"Profile '{target}' not found in {sorted(profiles)}")

    profile = profiles[target]
    lines = [f"profile: {target}"]
    if target == state.get("active_profile"):
        lines[-1] += "  (active)"
    lines.append(f"model_profile: {profile.get('model_profile', '<unset>')}")
    mcp_servers = profile.get("mcp_servers")
    lines.append(
        f"mcp_servers:   {'<all>' if mcp_servers is None else ', '.join(mcp_servers) or '<none>'}"
    )
    env_keys = sorted(profile.get("mcp_env", {}).keys())
    lines.append(f"mcp_env keys:  {', '.join(env_keys) if env_keys else '<none>'}")
    return lines


def cmd_use(state: dict, name: str, apply: bool) -> list[str]:
    profiles = require_profiled_state(state)
    if name not in profiles:
        raise ValueError(f"Profile '{name}' not found in {sorted(profiles)}")

    current = state.get("active_profile")
    if current == name:
        return [f"Profile already active: {name}"]

    if not apply:
        return [
            f"Would switch active_profile: {current} -> {name}",
            "Re-run with --apply to persist the change.",
        ]

    state["active_profile"] = name
    write_machine_local(state)
    return [
        f"Active profile: {current} -> {name}",
        "Run 'local-agent sync --apply' to render the new profile into ~/.claude and ~/.codex.",
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage active profile in machine.local.json.")
    sub = parser.add_subparsers(dest="action", required=True)

    sub.add_parser("list", help="List all profiles; active is marked with '*'.")

    show = sub.add_parser("show", help="Show details for a profile (defaults to the active one).")
    show.add_argument("name", nargs="?", default=None)

    use = sub.add_parser("use", help="Switch the active profile.")
    use.add_argument("name")
    use.add_argument("--apply", action="store_true", help="Persist the change. Defaults to dry-run.")

    return parser


def run(action: str, name: str | None = None, apply: bool = False) -> Iterable[str]:
    state = load_machine_local()
    if action == "list":
        return cmd_list(state)
    if action == "show":
        return cmd_show(state, name)
    if action == "use":
        if not name:
            raise ValueError("`profile use` requires a profile name")
        return cmd_use(state, name, apply)
    raise AssertionError(f"Unhandled action: {action}")


def main() -> int:
    args = build_parser().parse_args()
    try:
        lines = run(
            action=args.action,
            name=getattr(args, "name", None),
            apply=getattr(args, "apply", False),
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}")
        return 1

    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
