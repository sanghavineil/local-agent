#!/usr/bin/env python3
"""Initialize a new project with Claude + Codex parity files."""

from __future__ import annotations

import argparse
from pathlib import Path

LOCAL_AGENT_MARKER_START = "<!-- BEGIN local-agent shared baseline -->"
LOCAL_AGENT_MARKER_END = "<!-- END local-agent shared baseline -->"


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def normalize_newline(text: str) -> str:
    return text if text.endswith("\n") else text + "\n"


def render_project_agents(root: Path) -> str:
    template = (root / "templates" / "project" / "AGENTS.md").read_text()
    baseline = (root / "templates" / "home" / "AGENTS.md").read_text().strip()
    managed_baseline = f"{LOCAL_AGENT_MARKER_START}\n{baseline}\n{LOCAL_AGENT_MARKER_END}"
    return normalize_newline(template.replace("{{SHARED_BASELINE}}", managed_baseline))


def render_project_claude(root: Path) -> str:
    return normalize_newline((root / "templates" / "project" / "CLAUDE.md").read_text())


def render_impeccable_template(root: Path) -> str:
    return normalize_newline((root / "templates" / "project" / ".impeccable.md").read_text())


def update_existing_agents(existing: str, root: Path) -> str | None:
    if LOCAL_AGENT_MARKER_START not in existing or LOCAL_AGENT_MARKER_END not in existing:
        return None
    baseline = (root / "templates" / "home" / "AGENTS.md").read_text().strip()
    replacement = f"{LOCAL_AGENT_MARKER_START}\n{baseline}\n{LOCAL_AGENT_MARKER_END}"
    start = existing.index(LOCAL_AGENT_MARKER_START)
    end = existing.index(LOCAL_AGENT_MARKER_END) + len(LOCAL_AGENT_MARKER_END)
    updated = existing[:start] + replacement + existing[end:]
    return normalize_newline(updated)


def write_if_needed(path: Path, content: str, apply: bool, force: bool = False) -> str:
    if path.exists() and not force:
        existing = path.read_text()
        if existing == content:
            return f"unchanged     {path}"
        return f"skip          {path}  exists"
    if apply:
        path.write_text(content)
    return f"write         {path}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Initialize a project with local-agent parity files.")
    parser.add_argument("path", nargs="?", default=".", help="Project directory. Defaults to the current directory.")
    parser.add_argument("--apply", action="store_true", help="Apply changes. Defaults to dry-run.")
    parser.add_argument("--force", action="store_true", help="Overwrite managed files.")
    parser.add_argument(
        "--with-impeccable-template",
        action="store_true",
        help="Also create .impeccable.md if it does not exist.",
    )
    return parser


def run_init_project(
    project_root: Path,
    apply: bool,
    force: bool,
    with_impeccable_template: bool,
) -> list[str]:
    root = repo_root()

    agents_path = project_root / "AGENTS.md"
    claude_path = project_root / "CLAUDE.md"
    impeccable_path = project_root / ".impeccable.md"

    lines: list[str] = []
    project_root.mkdir(parents=True, exist_ok=True)

    rendered_agents = render_project_agents(root)
    if agents_path.exists() and not force:
        updated_agents = update_existing_agents(agents_path.read_text(), root)
        if updated_agents is not None:
            current = normalize_newline(agents_path.read_text())
            if current == updated_agents:
                lines.append(f"unchanged     {agents_path}")
            else:
                if apply:
                    agents_path.write_text(updated_agents)
                lines.append(f"update        {agents_path}  refreshed managed shared baseline")
        else:
            lines.append(f"skip          {agents_path}  exists without local-agent markers")
    else:
        lines.append(write_if_needed(agents_path, rendered_agents, apply, force=force))

    lines.append(write_if_needed(claude_path, render_project_claude(root), apply, force=force))

    if with_impeccable_template:
        lines.append(write_if_needed(impeccable_path, render_impeccable_template(root), apply, force=False))

    return lines


def main() -> int:
    args = build_parser().parse_args()
    project_root = Path(args.path).expanduser().resolve()
    for line in run_init_project(
        project_root=project_root,
        apply=args.apply,
        force=args.force,
        with_impeccable_template=args.with_impeccable_template,
    ):
        print(line)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
