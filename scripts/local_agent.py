#!/usr/bin/env python3
"""Unified CLI for local-agent machine and project setup."""

from __future__ import annotations

import argparse
from pathlib import Path

import bootstrap_machine
import doctor
import gateway
import init_project
import profile as profile_cmd
import sync_agent_parity


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Operate the local-agent setup repo.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    sync_parser = subparsers.add_parser("sync", help="Sync home-level shared agent setup from repo state.")
    sync_parser.add_argument("--apply", action="store_true", help="Apply changes. Defaults to dry-run.")
    sync_parser.add_argument("--home", default=None, help="Override home directory for testing.")
    sync_parser.add_argument(
        "--adopt-existing-skills",
        action="store_true",
        help="Move existing non-symlink skill directories aside and replace them with repo symlinks.",
    )

    bootstrap_parser = subparsers.add_parser("bootstrap", help="Initialize machine-local config and sync home state.")
    bootstrap_parser.add_argument("--apply", action="store_true", help="Apply changes. Defaults to dry-run.")
    bootstrap_parser.add_argument("--home", default=None, help="Override home directory for testing.")
    bootstrap_parser.add_argument(
        "--adopt-existing-skills",
        action="store_true",
        help="Move existing non-symlink skill directories aside and replace them with repo symlinks.",
    )
    bootstrap_parser.add_argument(
        "--init-machine-local",
        action="store_true",
        help="Create config/machine.local.json from config/machine.example.json if it is missing.",
    )

    init_parser = subparsers.add_parser("init-project", help="Create or refresh project-level shared agent instruction files.")
    init_parser.add_argument("path", nargs="?", default=".", help="Project directory. Defaults to the current directory.")
    init_parser.add_argument("--apply", action="store_true", help="Apply changes. Defaults to dry-run.")
    init_parser.add_argument("--force", action="store_true", help="Overwrite managed files.")
    init_parser.add_argument(
        "--with-impeccable-template",
        action="store_true",
        help="Also create .impeccable.md if it does not exist.",
    )

    doctor_parser = subparsers.add_parser("doctor", help="Check for drift in home and project setup.")
    doctor_parser.add_argument("--home", default=None, help="Override home directory for testing.")
    doctor_parser.add_argument("--project", default=None, help="Optional project directory to check.")
    doctor_parser.add_argument(
        "--expect-impeccable",
        action="store_true",
        help="Require .impeccable.md when checking a project.",
    )

    profile_parser = subparsers.add_parser("profile", help="Manage the active profile in machine.local.json.")
    profile_sub = profile_parser.add_subparsers(dest="profile_action", required=True)
    profile_sub.add_parser("list", help="List all profiles; active is marked with '*'.")
    show_parser = profile_sub.add_parser("show", help="Show details for a profile (defaults to active).")
    show_parser.add_argument("name", nargs="?", default=None)
    use_parser = profile_sub.add_parser("use", help="Switch the active profile.")
    use_parser.add_argument("name")
    use_parser.add_argument("--apply", action="store_true", help="Persist the change. Defaults to dry-run.")

    gateway_parser = subparsers.add_parser("gateway", help="Manage the LiteLLM proxy used by Claude Code.")
    gateway_sub = gateway_parser.add_subparsers(dest="gateway_action", required=True)
    gateway_sub.add_parser("start", help="Start the proxy in the background.")
    gateway_sub.add_parser("stop", help="Stop the running proxy if any.")
    gateway_sub.add_parser("status", help="Report the proxy's current state.")
    gateway_parser.add_argument("--home", default=None, help="Override home directory for testing.")

    return parser


def main() -> int:
    args = build_parser().parse_args()

    if args.command == "sync":
        actions, warnings = sync_agent_parity.run_sync(
            apply=args.apply,
            home_override=args.home,
            adopt_existing_skills=args.adopt_existing_skills,
        )
        for line in bootstrap_machine.format_actions(actions):
            print(line)
        for line in bootstrap_machine.format_warnings(warnings):
            print(line)
        return 0

    if args.command == "bootstrap":
        lines, warnings = bootstrap_machine.run_bootstrap(
            apply=args.apply,
            home_override=args.home,
            adopt_existing_skills=args.adopt_existing_skills,
            init_machine_local=args.init_machine_local,
        )
        for line in lines:
            print(line)
        for line in bootstrap_machine.format_warnings(warnings):
            print(line)
        return 0

    if args.command == "init-project":
        project_root = Path(args.path).expanduser().resolve()
        for line in init_project.run_init_project(
            project_root=project_root,
            apply=args.apply,
            force=args.force,
            with_impeccable_template=args.with_impeccable_template,
        ):
            print(line)
        return 0

    if args.command == "doctor":
        home_actions, home_warnings = doctor.check_home(home_override=args.home)
        if home_actions:
            print("Home drift:")
            for action in home_actions:
                print(f"- {action.kind}: {action.target}  {action.detail}")
        else:
            print("Home drift: clean")

        if home_warnings:
            print("")
            print("Home warnings:")
            for item in home_warnings:
                if item.kind == "missing-secret":
                    print(f"- missing secret: {item.detail}")
                elif item.kind == "missing-skill":
                    print(f"- missing vendored skill: {item.detail}")
                else:
                    print(f"- {item.kind}: {item.detail}")

        project_issues = []
        if args.project:
            project_root = Path(args.project).expanduser().resolve()
            project_issues = doctor.check_project(project_root, expect_impeccable=args.expect_impeccable)
            print("")
            print(f"Project check: {project_root}")
            if project_issues:
                for issue in project_issues:
                    print(f"- {issue.kind}: {issue.path}  {issue.detail}")
            else:
                print("- clean")

        return 1 if home_actions or home_warnings or project_issues else 0

    if args.command == "profile":
        try:
            lines = profile_cmd.run(
                action=args.profile_action,
                name=getattr(args, "name", None),
                apply=getattr(args, "apply", False),
            )
        except (FileNotFoundError, ValueError) as exc:
            print(f"error: {exc}")
            return 1
        for line in lines:
            print(line)
        return 0

    if args.command == "gateway":
        try:
            lines = gateway.run(
                action=args.gateway_action,
                home_override=getattr(args, "home", None),
            )
        except FileNotFoundError as exc:
            print(f"error: {exc}")
            return 1
        for line in lines:
            print(line)
        return 0

    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
