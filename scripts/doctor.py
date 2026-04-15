#!/usr/bin/env python3
"""Check whether machine and project setup match the tracked local-agent repo state."""

from __future__ import annotations

import argparse
import socket
from dataclasses import dataclass
from pathlib import Path

import gateway
import init_project
import sync_agent_parity


@dataclass
class ProjectIssue:
    kind: str
    path: Path
    detail: str


def check_home(home_override: str | None = None) -> tuple[list[sync_agent_parity.Action], list[sync_agent_parity.WarningItem]]:
    actions, warnings = sync_agent_parity.run_sync(
        apply=False, home_override=home_override, adopt_existing_skills=False
    )
    warnings.extend(probe_gateway_port(home_override))
    return actions, warnings


def probe_gateway_port(home_override: str | None = None) -> list[sync_agent_parity.WarningItem]:
    """Warn if the active profile uses a proxy provider but the configured port is bound by something other than our own gateway.

    Skips entirely when the active profile uses anthropic-direct (no proxy
    needed) or when machine.local.json is missing/legacy. The check is best-
    effort: if the bind probe fails for unexpected reasons, no warning is
    emitted.
    """
    root = sync_agent_parity.repo_root()
    machine_state = sync_agent_parity.load_machine_state(root)
    if not machine_state.get("profiles"):
        return []
    try:
        providers_manifest = sync_agent_parity.load_json(
            root / "manifests" / "model_providers.json"
        )
    except FileNotFoundError:
        return []
    profile, _ = sync_agent_parity.load_active_profile(machine_state)
    provider, _ = sync_agent_parity.resolve_model_provider(profile, providers_manifest)
    if not sync_agent_parity.is_proxy_provider(provider):
        return []

    port = providers_manifest.get("gateway", {}).get("port", 4000)
    if not _port_is_bound(port):
        return []

    # Port is bound. If our gateway already owns it, that is the expected state.
    pid = gateway.read_pidfile(home_override)
    if pid is not None and gateway.is_our_gateway(pid):
        return []

    return [
        sync_agent_parity.WarningItem(
            "port-in-use",
            f"port {port} is bound by another process; "
            f"`local-agent gateway start` will fail until it's freed",
        )
    ]


def _port_is_bound(port: int) -> bool:
    """Return True if something is already listening on localhost:port."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", port))
    except OSError:
        return True
    finally:
        sock.close()
    return False


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
