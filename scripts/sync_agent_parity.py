#!/usr/bin/env python3
"""Synchronize Claude + Codex local setup from this repository's tracked sources."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

CONFIG_BLOCK_START = "# BEGIN local-agent parity managed block"
CONFIG_BLOCK_END = "# END local-agent parity managed block"


@dataclass
class Action:
    kind: str
    target: Path
    detail: str


@dataclass
class WarningItem:
    kind: str
    detail: str


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def expand_home_path(path_text: str, home: Path) -> Path:
    if path_text == "~":
        return home
    if path_text.startswith("~/"):
        return home / path_text[2:]
    return Path(os.path.expanduser(path_text))


def quote_toml(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def array_toml(values: Iterable[str]) -> str:
    return "[" + ", ".join(quote_toml(v) for v in values) + "]"


def ensure_parent(path: Path, apply: bool) -> List[Action]:
    actions: List[Action] = []
    if not path.parent.exists():
        actions.append(Action("mkdir", path.parent, "create parent directory"))
        if apply:
            path.parent.mkdir(parents=True, exist_ok=True)
    return actions


def backup_name(path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    return path.with_name(f"{path.name}.bak-local-agent-{stamp}")


def desired_symlink(target: Path, link_path: Path, apply: bool, adopt_existing: bool = False) -> List[Action]:
    actions: List[Action] = ensure_parent(link_path, apply)

    if link_path.is_symlink():
        current = Path(os.readlink(link_path))
        if current == target:
            return actions
        actions.append(Action("replace-link", link_path, f"{current} -> {target}"))
        if apply:
            link_path.unlink()
            link_path.symlink_to(target)
        return actions

    if link_path.exists():
        if adopt_existing:
            backup_path = backup_name(link_path)
            actions.append(Action("backup", link_path, f"move to {backup_path}"))
            actions.append(Action("link", link_path, f"-> {target}"))
            if apply:
                link_path.rename(backup_path)
                link_path.symlink_to(target)
            return actions
        actions.append(Action("skip", link_path, "exists and is not a symlink"))
        return actions

    actions.append(Action("link", link_path, f"-> {target}"))
    if apply:
        link_path.symlink_to(target)
    return actions


def write_file_if_changed(path: Path, content: str, apply: bool) -> List[Action]:
    actions: List[Action] = ensure_parent(path, apply)
    existing = path.read_text() if path.exists() else None
    if existing == content:
        return actions
    kind = "update-file" if existing is not None else "create-file"
    actions.append(Action(kind, path, "write managed content"))
    if apply:
        path.write_text(content)
    return actions


def write_json_if_changed(path: Path, data: dict, apply: bool) -> List[Action]:
    content = json.dumps(data, indent=2) + "\n"
    return write_file_if_changed(path, content, apply)


def remove_managed_block(existing: str) -> str:
    if CONFIG_BLOCK_START not in existing or CONFIG_BLOCK_END not in existing:
        return existing

    start = existing.index(CONFIG_BLOCK_START)
    end = existing.index(CONFIG_BLOCK_END) + len(CONFIG_BLOCK_END)
    prefix = existing[:start].rstrip()
    suffix = existing[end:].lstrip("\n")
    merged = prefix
    if prefix and suffix:
        merged += "\n\n"
    merged += suffix
    return merged.rstrip() + "\n" if merged.strip() else ""


def upsert_managed_block(existing: str, block: str) -> str:
    if CONFIG_BLOCK_START in existing and CONFIG_BLOCK_END in existing:
        existing = remove_managed_block(existing)
    if existing.strip():
        return existing.rstrip() + "\n\n" + block
    return block


def strip_managed_server_sections(config_text: str, managed_names: Iterable[str]) -> str:
    names = set(managed_names)
    header_re = re.compile(r"^\[(?P<section>[^\]]+)\]\s*$")
    managed_sections = {f"mcp_servers.{name}" for name in names}
    managed_sections |= {f"mcp_servers.{name}.env" for name in names}

    kept: List[str] = []
    skip_section = False
    for line in config_text.splitlines():
        match = header_re.match(line.strip())
        if match:
            section = match.group("section")
            skip_section = section in managed_sections
            if skip_section:
                continue
            kept.append(line)
            continue
        if skip_section:
            continue
        kept.append(line)

    cleaned = "\n".join(kept).strip()
    return cleaned + "\n" if cleaned else ""


def load_machine_state(root: Path) -> dict:
    local_path = root / "config" / "machine.local.json"
    if local_path.exists():
        return load_json(local_path)
    return {}


def resolve_env_values(keys: Iterable[str], machine_state: dict) -> tuple[dict, List[WarningItem]]:
    resolved = {}
    warnings: List[WarningItem] = []
    machine_env = machine_state.get("mcp_env", {})
    for key in keys:
        value = machine_env.get(key) or os.environ.get(key)
        if value:
            resolved[key] = value
        else:
            warnings.append(WarningItem("missing-secret", key))
    return resolved, warnings


def render_claude_settings(settings_manifest: dict, env_values: dict) -> dict:
    data = {
        "permissions": settings_manifest["permissions"],
        "effortLevel": settings_manifest["effortLevel"],
    }
    env_payload = {}
    for key in settings_manifest.get("env_keys", []):
        if key in env_values:
            env_payload[key] = env_values[key]
    if env_payload:
        data["env"] = env_payload
    return data


def render_claude_mcp(mcp_manifest: dict, env_values: dict) -> dict:
    servers = {}
    for name, server in mcp_manifest["servers"].items():
        payload = {}
        for field in ("command", "args", "url"):
            if field in server:
                payload[field] = server[field]
        env_payload = {}
        for key in server.get("env_keys", []):
            if key in env_values:
                env_payload[key] = env_values[key]
        if env_payload:
            payload["env"] = env_payload
        servers[name] = payload
    return {"mcpServers": servers}


def render_codex_mcp_block(mcp_manifest: dict, env_values: dict) -> str:
    lines: List[str] = [CONFIG_BLOCK_START]
    for name in sorted(mcp_manifest["servers"]):
        server = mcp_manifest["servers"][name]
        lines.append(f"[mcp_servers.{name}]")
        if "command" in server:
            lines.append(f'command = {quote_toml(server["command"])}')
        if "args" in server:
            lines.append(f"args = {array_toml(server['args'])}")
        if "url" in server:
            lines.append(f'url = {quote_toml(server["url"])}')

        env_lines = []
        for key in server.get("env_keys", []):
            if key in env_values:
                env_lines.append(f"{key} = {quote_toml(str(env_values[key]))}")
        if env_lines:
            lines.append("")
            lines.append(f"[mcp_servers.{name}.env]")
            lines.extend(env_lines)
        lines.append("")

    if lines[-1] == "":
        lines.pop()
    lines.append(CONFIG_BLOCK_END)
    return "\n".join(lines) + "\n"


def collect_portable_skills(root: Path, skills_manifest: dict) -> tuple[dict, List[WarningItem]]:
    portable_root = root / "skills" / "portable"
    skills = {}
    warnings: List[WarningItem] = []
    for name in skills_manifest["portable_skills"]:
        path = portable_root / name
        if path.exists():
            skills[name] = path
        else:
            warnings.append(WarningItem("missing-skill", name))
    return skills, warnings


def run_sync(
    apply: bool,
    home_override: str | None = None,
    adopt_existing_skills: bool = False,
) -> tuple[List[Action], List[WarningItem]]:
    root = repo_root()
    home = Path(home_override).expanduser() if home_override else Path.home()

    skills_manifest = load_json(root / "manifests" / "skills.json")
    mcp_manifest = load_json(root / "manifests" / "mcp_servers.json")
    settings_manifest = load_json(root / "manifests" / "claude_settings.json")
    machine_state = load_machine_state(root)

    codex_agents_target = home / ".codex" / "AGENTS.md"
    claude_agents_link = home / ".claude" / "AGENTS.md"
    claude_wrapper_target = home / ".claude" / "CLAUDE.md"
    claude_settings_target = home / ".claude" / "settings.json"
    claude_mcp_target = home / ".claude" / ".mcp.json"
    codex_config_target = home / ".codex" / "config.toml"

    home_agents_template = (root / "templates" / "home" / "AGENTS.md").read_text()
    home_claude_template = (root / "templates" / "home" / "CLAUDE.md").read_text()

    portable_skills, skill_warnings = collect_portable_skills(root, skills_manifest)
    all_env_keys = set(settings_manifest.get("env_keys", []))
    for server in mcp_manifest["servers"].values():
        all_env_keys.update(server.get("env_keys", []))
    env_values, env_warnings = resolve_env_values(sorted(all_env_keys), machine_state)

    warnings = skill_warnings + env_warnings
    actions: List[Action] = []

    actions.extend(write_file_if_changed(codex_agents_target, home_agents_template, apply))
    actions.extend(desired_symlink(codex_agents_target, claude_agents_link, apply))
    actions.extend(write_file_if_changed(claude_wrapper_target, home_claude_template, apply))
    actions.extend(write_json_if_changed(claude_settings_target, render_claude_settings(settings_manifest, env_values), apply))
    actions.extend(write_json_if_changed(claude_mcp_target, render_claude_mcp(mcp_manifest, env_values), apply))

    for target_text in skills_manifest["install_targets"]:
        target_root = expand_home_path(target_text, home)
        for name, source in portable_skills.items():
            actions.extend(
                desired_symlink(
                    source,
                    target_root / name,
                    apply,
                    adopt_existing=adopt_existing_skills,
                )
            )

    existing_config = codex_config_target.read_text() if codex_config_target.exists() else ""
    base_config = remove_managed_block(existing_config)
    base_config = strip_managed_server_sections(base_config, mcp_manifest["servers"].keys())
    managed_block = render_codex_mcp_block(mcp_manifest, env_values)
    merged_config = upsert_managed_block(base_config, managed_block)
    actions.extend(write_file_if_changed(codex_config_target, merged_config, apply))

    return actions, warnings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Synchronize Claude + Codex local setup from repo-managed files.")
    parser.add_argument("--apply", action="store_true", help="Apply changes. Defaults to dry-run.")
    parser.add_argument("--home", default=None, help="Override home directory for testing.")
    parser.add_argument(
        "--adopt-existing-skills",
        action="store_true",
        help="Move existing non-symlink skill directories aside and replace them with repo symlinks.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    actions, warnings = run_sync(
        apply=args.apply,
        home_override=args.home,
        adopt_existing_skills=args.adopt_existing_skills,
    )

    if actions:
        for action in actions:
            print(f"{action.kind:12} {action.target}  {action.detail}")
    else:
        print("No changes needed.")

    if warnings:
        print("\nWarnings:")
        for item in warnings:
            if item.kind == "missing-secret":
                print(f"- missing secret: {item.detail}")
            elif item.kind == "missing-skill":
                print(f"- missing vendored skill: {item.detail}")
            else:
                print(f"- {item.kind}: {item.detail}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
