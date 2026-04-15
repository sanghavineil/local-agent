#!/usr/bin/env python3
"""Bootstrap a machine from the tracked local-agent configuration."""

from __future__ import annotations

import argparse
from pathlib import Path

import sync_agent_parity


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bootstrap Claude + Codex setup on this machine.")
    parser.add_argument("--apply", action="store_true", help="Apply changes. Defaults to dry-run.")
    parser.add_argument("--home", default=None, help="Override home directory for testing.")
    parser.add_argument(
        "--adopt-existing-skills",
        action="store_true",
        help="Move existing non-symlink skill directories aside and replace them with repo symlinks.",
    )
    parser.add_argument(
        "--init-machine-local",
        action="store_true",
        help="Create config/machine.local.json from config/machine.example.json if it is missing.",
    )
    return parser


def maybe_init_machine_local(root: Path, apply: bool) -> list[str]:
    messages: list[str] = []
    example = root / "config" / "machine.example.json"
    local = root / "config" / "machine.local.json"
    if local.exists():
        return messages
    if apply:
        local.write_text(example.read_text())
        messages.append(f"create-file  {local}  copied from machine.example.json")
    else:
        messages.append(f"create-file  {local}  would copy from machine.example.json")
    return messages


def format_actions(actions: list[sync_agent_parity.Action]) -> list[str]:
    if not actions:
        return ["No changes needed."]
    return [f"{action.kind:12} {action.target}  {action.detail}" for action in actions]


def format_warnings(warnings: list[sync_agent_parity.WarningItem]) -> list[str]:
    if not warnings:
        return []

    lines = ["", "Warnings:"]
    for item in warnings:
        if item.kind == "missing-secret":
            lines.append(f"- missing secret: {item.detail}")
        elif item.kind == "missing-skill":
            lines.append(f"- missing vendored skill: {item.detail}")
        else:
            lines.append(f"- {item.kind}: {item.detail}")
    return lines


def run_bootstrap(
    apply: bool,
    home_override: str | None = None,
    adopt_existing_skills: bool = False,
    init_machine_local: bool = False,
) -> tuple[list[str], list[sync_agent_parity.WarningItem]]:
    lines: list[str] = []
    root = sync_agent_parity.repo_root()

    if init_machine_local:
        lines.extend(maybe_init_machine_local(root, apply))

    actions, warnings = sync_agent_parity.run_sync(
        apply=apply,
        home_override=home_override,
        adopt_existing_skills=adopt_existing_skills,
    )
    lines.extend(format_actions(actions))
    return lines, warnings


def main() -> int:
    args = build_parser().parse_args()
    lines, warnings = run_bootstrap(
        apply=args.apply,
        home_override=args.home,
        adopt_existing_skills=args.adopt_existing_skills,
        init_machine_local=args.init_machine_local,
    )

    for line in lines:
        print(line)
    for line in format_warnings(warnings):
        print(line)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
