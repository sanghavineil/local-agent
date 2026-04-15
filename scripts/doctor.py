#!/usr/bin/env python3
"""Check whether machine and project setup match the tracked local-agent repo state."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import init_project
import sync_agent_parity


@dataclass
class ProjectIssue:
    kind: str
    path: Path
    detail: str


def check_home(home_override: str | None = None) -> tuple[list[sync_agent_parity.Action], list[sync_agent_parity.WarningItem]]:
    return sync_agent_parity.run_sync(apply=False, home_override=home_override, adopt_existing_skills=False)


def check_project(project_root: Path, expect_impeccable: bool = False) -> list[ProjectIssue]:
    root = sync_agent_parity.repo_root()
    issues: list[ProjectIssue] = []

    agents_path = project_root / "AGENTS.md"
    claude_path = project_root / "CLAUDE.md"
    impeccable_path = project_root / ".impeccable.md"

    if not agents_path.exists():
        issues.append(ProjectIssue("missing", agents_path, "missing AGENTS.md"))
    else:
        existing_agents = init_project.normalize_newline(agents_path.read_text())
        updated_agents = init_project.update_existing_agents(existing_agents, root)
        if updated_agents is None:
            issues.append(ProjectIssue("unmanaged", agents_path, "exists without local-agent markers"))
        elif updated_agents != existing_agents:
            issues.append(ProjectIssue("drift", agents_path, "managed shared baseline differs from repo template"))

    if not claude_path.exists():
        issues.append(ProjectIssue("missing", claude_path, "missing CLAUDE.md"))
    else:
        claude_text = claude_path.read_text()
        if "@AGENTS.md" not in claude_text:
            issues.append(ProjectIssue("drift", claude_path, "should import @AGENTS.md"))

    if expect_impeccable and not impeccable_path.exists():
        issues.append(ProjectIssue("missing", impeccable_path, "expected .impeccable.md"))

    return issues


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check local-agent machine/project drift.")
    parser.add_argument("--home", default=None, help="Override home directory for testing.")
    parser.add_argument(
        "--project",
        default=None,
        help="Optional project directory to check for generated AGENTS.md/CLAUDE.md parity.",
    )
    parser.add_argument(
        "--expect-impeccable",
        action="store_true",
        help="Require .impeccable.md when checking a project.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    actions, warnings = check_home(home_override=args.home)

    if actions:
        print("Home drift:")
        for action in actions:
            print(f"- {action.kind}: {action.target}  {action.detail}")
    else:
        print("Home drift: clean")

    if warnings:
        print("\nHome warnings:")
        for item in warnings:
            if item.kind == "missing-secret":
                print(f"- missing secret: {item.detail}")
            elif item.kind == "missing-skill":
                print(f"- missing vendored skill: {item.detail}")
            else:
                print(f"- {item.kind}: {item.detail}")

    issues: list[ProjectIssue] = []
    if args.project:
        project_root = Path(args.project).expanduser().resolve()
        issues = check_project(project_root, expect_impeccable=args.expect_impeccable)
        print(f"\nProject check: {project_root}")
        if issues:
            for issue in issues:
                print(f"- {issue.kind}: {issue.path}  {issue.detail}")
        else:
            print("- clean")

    return 1 if actions or warnings or issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
