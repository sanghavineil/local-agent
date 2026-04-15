#!/usr/bin/env python3
"""Synchronize shared coding-agent setup from this repository's tracked sources."""

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
PROVIDERS_BLOCK_START = "# BEGIN local-agent providers managed block"
PROVIDERS_BLOCK_END = "# END local-agent providers managed block"


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


def desired_symlink(
    target: Path,
    link_path: Path,
    apply: bool,
    adopt_existing: bool = False,
    replace_matching_content: str | None = None,
) -> List[Action]:
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
        # Precedence: `replace_matching_content` is checked before `adopt_existing`
        # because converting an unchanged managed file into a symlink is strictly
        # less destructive than backing it up. If both are set and content matches,
        # we replace silently; if content has diverged, we surface a `skip-divergent`
        # action so the user knows their hand-edits are blocking the symlink.
        if replace_matching_content is not None and link_path.is_file():
            existing = link_path.read_text()
            if existing == replace_matching_content:
                actions.append(Action("replace-file", link_path, f"managed file -> symlink to {target}"))
                if apply:
                    link_path.unlink()
                    link_path.symlink_to(target)
                return actions
            actions.append(
                Action(
                    "skip-divergent",
                    link_path,
                    f"hand-edited content differs from managed source ({target}); resolve manually",
                )
            )
            return actions
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


def remove_managed_block(
    existing: str,
    start_marker: str = CONFIG_BLOCK_START,
    end_marker: str = CONFIG_BLOCK_END,
) -> str:
    if start_marker not in existing or end_marker not in existing:
        return existing

    start = existing.index(start_marker)
    end = existing.index(end_marker) + len(end_marker)
    prefix = existing[:start].rstrip()
    suffix = existing[end:].lstrip("\n")
    merged = prefix
    if prefix and suffix:
        merged += "\n\n"
    merged += suffix
    return merged.rstrip() + "\n" if merged.strip() else ""


def upsert_managed_block(
    existing: str,
    block: str,
    start_marker: str = CONFIG_BLOCK_START,
    end_marker: str = CONFIG_BLOCK_END,
) -> str:
    if start_marker in existing and end_marker in existing:
        existing = remove_managed_block(existing, start_marker, end_marker)
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


def load_active_profile(machine_state: dict) -> tuple[dict, List[WarningItem]]:
    """Return the active profile (mcp_env, mcp_servers, model_profile) and any warnings.

    Supports two schemas:
    - Profile-keyed: {"active_profile": "<name>", "profiles": {"<name>": {...}, ...}}
    - Legacy flat:   {"mcp_env": {...}}  (treated as a single synthetic profile that
      enables every MCP server in the manifest)

    `mcp_servers: None` in the returned dict means "no allowlist — render every server
    in the MCP manifest". A list narrows the render set to those names.
    """
    warnings: List[WarningItem] = []

    if "profiles" not in machine_state:
        return (
            {
                "name": None,
                "mcp_env": machine_state.get("mcp_env", {}),
                "mcp_servers": None,
                "model_profile": None,
            },
            warnings,
        )

    profiles = machine_state["profiles"]
    if not isinstance(profiles, dict) or not profiles:
        raise ValueError("machine.local.json 'profiles' must be a non-empty object")

    name = machine_state.get("active_profile")
    if name is None:
        raise ValueError("machine.local.json has 'profiles' but no 'active_profile'")
    if name not in profiles:
        raise ValueError(
            f"active_profile '{name}' not found in profiles {sorted(profiles)}"
        )

    profile = profiles[name]
    return (
        {
            "name": name,
            "mcp_env": profile.get("mcp_env", {}),
            "mcp_servers": profile.get("mcp_servers"),
            "model_profile": profile.get("model_profile"),
        },
        warnings,
    )


def filter_mcp_manifest(mcp_manifest: dict, allowed: list[str] | None) -> tuple[dict, List[WarningItem]]:
    """Return a copy of the MCP manifest filtered by an optional allowlist of names."""
    warnings: List[WarningItem] = []
    if allowed is None:
        return mcp_manifest, warnings

    available = mcp_manifest.get("servers", {})
    filtered: dict = {}
    for name in allowed:
        if name in available:
            filtered[name] = available[name]
        else:
            warnings.append(WarningItem("unknown-mcp-server", name))
    return {"servers": filtered}, warnings


def resolve_env_values(keys: Iterable[str], mcp_env: dict) -> tuple[dict, List[WarningItem]]:
    resolved = {}
    warnings: List[WarningItem] = []
    for key in keys:
        value = mcp_env.get(key) or os.environ.get(key)
        if value:
            resolved[key] = value
        else:
            warnings.append(WarningItem("missing-secret", key))
    return resolved, warnings


def resolve_settings_env_keys(settings_manifest: dict, active_mcp_manifest: dict) -> List[str]:
    keys = set(settings_manifest.get("env_keys", []))
    active_servers = set(active_mcp_manifest.get("servers", {}))
    for server_name, server_keys in (settings_manifest.get("conditional_env_keys") or {}).items():
        if server_name in active_servers:
            keys.update(server_keys)
    return sorted(keys)


def resolve_model_provider(
    profile: dict, providers_manifest: dict
) -> tuple[dict | None, List[WarningItem]]:
    """Look up the active profile's `model_profile` in the providers manifest.

    Returns (provider_dict, warnings). Provider dict is None if the profile does
    not specify a `model_profile`. Emits a warning if the referenced provider is
    unknown.
    """
    warnings: List[WarningItem] = []
    name = profile.get("model_profile")
    if not name:
        return None, warnings
    providers = providers_manifest.get("providers", {})
    if name not in providers:
        warnings.append(WarningItem("unknown-model-provider", name))
        return None, warnings
    provider = dict(providers[name])
    provider["_name"] = name
    return provider, warnings


def is_proxy_provider(provider: dict | None) -> bool:
    return bool(provider) and provider.get("kind") != "anthropic-direct"


def render_codex_providers_block(
    providers_manifest: dict,
    machine_state: dict,
) -> str:
    """Render Codex `[model_providers.X]` and `[profiles.Y]` sections.

    All non-`anthropic-direct` providers referenced by any profile in
    machine.local.json are rendered. A `[profiles.X]` block is rendered for each
    profile in machine.local.json, regardless of which is active, so the user can
    do `codex --profile X` without a re-sync.
    """
    providers = providers_manifest.get("providers", {})
    profiles = machine_state.get("profiles", {})

    referenced_providers: set[str] = set()
    for profile in profiles.values():
        ref = profile.get("model_profile")
        if ref and ref in providers and providers[ref].get("kind") != "anthropic-direct":
            referenced_providers.add(ref)

    lines: List[str] = [PROVIDERS_BLOCK_START]

    for name in sorted(referenced_providers):
        provider = providers[name]
        lines.append(f"[model_providers.{name}]")
        lines.append(f"name = {quote_toml(provider.get('display_name', name))}")
        lines.append(f"base_url = {quote_toml(provider['base_url'])}")
        lines.append("")

    for profile_name in sorted(profiles):
        profile = profiles[profile_name]
        ref = profile.get("model_profile")
        if not ref or ref not in providers:
            continue
        provider = providers[ref]
        lines.append(f"[profiles.{profile_name}]")
        if provider.get("kind") != "anthropic-direct":
            lines.append(f"model_provider = {quote_toml(ref)}")
        lines.append(f"model = {quote_toml(provider['default_model'])}")
        lines.append("")

    if lines[-1] == "":
        lines.pop()
    lines.append(PROVIDERS_BLOCK_END)
    return "\n".join(lines) + "\n"


def render_litellm_config(providers_manifest: dict, master_key: str) -> str:
    """Render a LiteLLM proxy config including all openai-compatible providers."""
    providers = providers_manifest.get("providers", {})
    lines: List[str] = ["model_list:"]

    proxy_providers = sorted(
        (name, p)
        for name, p in providers.items()
        if p.get("kind") == "openai-compatible"
    )

    if not proxy_providers:
        lines.append("  []")
    else:
        for name, provider in proxy_providers:
            lines.append(f"  - model_name: {name}")
            lines.append("    litellm_params:")
            lines.append(f"      model: {provider['litellm_model']}")
            lines.append(f"      api_base: {provider['base_url']}")
            if provider.get("auth") == "api-key":
                lines.append("      api_key: not-needed")

    lines.append("")
    lines.append("litellm_settings:")
    lines.append(f"  master_key: {master_key}")
    lines.append("")
    return "\n".join(lines)


def resolve_gateway_master_key(machine_state: dict, providers_manifest: dict) -> str:
    """Return the master key for the LiteLLM proxy — per-profile override wins."""
    default_key = providers_manifest.get("gateway", {}).get(
        "default_master_key", "local-agent-dev"
    )
    active_profile_name = machine_state.get("active_profile")
    profile = (machine_state.get("profiles") or {}).get(active_profile_name, {}) or {}
    return (profile.get("gateway") or {}).get("master_key", default_key)


def gateway_env_for_profile(
    provider: dict | None,
    machine_state: dict,
    providers_manifest: dict,
) -> dict[str, str]:
    """Build the env vars that point Claude Code at the local LiteLLM proxy.

    Returns an empty dict when the active profile uses anthropic-direct; the caller
    should NOT inject any gateway env in that case so Claude talks to Anthropic
    natively.
    """
    if not is_proxy_provider(provider):
        return {}
    port = providers_manifest.get("gateway", {}).get("port", 4000)
    return {
        "ANTHROPIC_BASE_URL": f"http://localhost:{port}",
        "ANTHROPIC_AUTH_TOKEN": resolve_gateway_master_key(machine_state, providers_manifest),
    }


def render_claude_settings(
    settings_manifest: dict,
    env_values: dict,
    settings_env_keys: Iterable[str] | None = None,
    hook_command_paths: dict[str, Path] | None = None,
    gateway_env: dict[str, str] | None = None,
) -> dict:
    data = {
        "permissions": settings_manifest["permissions"],
        "effortLevel": settings_manifest["effortLevel"],
    }
    env_payload = {}
    keys_to_render = settings_env_keys if settings_env_keys is not None else settings_manifest.get("env_keys", [])
    for key in keys_to_render:
        if key in env_values:
            env_payload[key] = env_values[key]
    # Gateway env (ANTHROPIC_BASE_URL/AUTH_TOKEN) bypasses the env_keys filter on
    # purpose: when the active profile uses a proxy provider the env vars MUST be
    # present for Claude Code to reach the proxy. They are also intentionally last
    # so they cannot be overridden by a manifest entry of the same name.
    if gateway_env:
        env_payload.update(gateway_env)
    if env_payload:
        data["env"] = env_payload

    hooks_manifest = settings_manifest.get("hooks") or {}
    rendered_hooks = render_hooks(hooks_manifest, hook_command_paths or {})
    if rendered_hooks:
        data["hooks"] = rendered_hooks
    return data


def render_hooks(hooks_manifest: dict, hook_command_paths: dict[str, Path]) -> dict:
    """Resolve manifest hook entries into Claude Code's settings.json shape.

    Manifest entries reference scripts by name (`script` field). We rewrite each
    one as a `command` field whose value is the absolute path of the script's
    symlink under ~/.claude/hooks/. Entries that already provide a raw `command`
    pass through unchanged.
    """
    rendered: dict = {}
    for event, entries in hooks_manifest.items():
        rendered_entries = []
        for entry in entries:
            new_entry = dict(entry)
            script = new_entry.pop("script", None)
            if script is not None:
                target = hook_command_paths.get(script)
                if target is None:
                    # Script is referenced in manifest but missing from the tracked
                    # hooks directory. Skip rendering this entry; collect_hook_scripts
                    # will have already emitted a warning.
                    continue
                new_entry["command"] = str(target)
            rendered_entries.append(new_entry)
        if rendered_entries:
            rendered[event] = rendered_entries
    return rendered


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


def collect_hook_scripts(root: Path, settings_manifest: dict) -> tuple[dict, List[WarningItem]]:
    """Discover hook scripts referenced by the manifest under templates/home/claude/hooks/.

    Returns a dict mapping script name -> absolute source path in the repo, plus any
    warnings about referenced-but-missing scripts or scripts that are not executable.
    """
    hooks_root = root / "templates" / "home" / "claude" / "hooks"
    referenced: set[str] = set()
    for entries in (settings_manifest.get("hooks") or {}).values():
        for entry in entries:
            script = entry.get("script")
            if script:
                referenced.add(script)

    scripts: dict = {}
    warnings: List[WarningItem] = []
    for name in sorted(referenced):
        source = hooks_root / name
        if not source.exists():
            warnings.append(WarningItem("missing-hook-script", name))
            continue
        if not os.access(source, os.X_OK):
            warnings.append(WarningItem("non-executable-hook", name))
        scripts[name] = source
    return scripts, warnings


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
    providers_manifest = load_json(root / "manifests" / "model_providers.json")
    machine_state = load_machine_state(root)

    profile, profile_warnings = load_active_profile(machine_state)
    active_mcp_manifest, mcp_filter_warnings = filter_mcp_manifest(
        mcp_manifest, profile["mcp_servers"]
    )
    active_provider, provider_warnings = resolve_model_provider(profile, providers_manifest)
    gateway_env = gateway_env_for_profile(active_provider, machine_state, providers_manifest)
    if "profiles" not in machine_state and machine_state:
        profile_warnings.append(
            WarningItem(
                "legacy-machine-schema",
                "machine.local.json uses the flat schema; migrate to 'profiles' (see config/machine.example.json)",
            )
        )

    shared_agents_target = home / ".agents" / "AGENTS.md"
    codex_agents_target = home / ".codex" / "AGENTS.md"
    claude_agents_link = home / ".claude" / "AGENTS.md"
    claude_wrapper_target = home / ".claude" / "CLAUDE.md"
    claude_settings_target = home / ".claude" / "settings.json"
    claude_mcp_target = home / ".claude" / ".mcp.json"
    codex_config_target = home / ".codex" / "config.toml"
    litellm_config_target = home / ".config" / "litellm" / "config.yaml"

    home_agents_template = (root / "templates" / "home" / "AGENTS.md").read_text()
    home_claude_template = (root / "templates" / "home" / "CLAUDE.md").read_text()

    portable_skills, skill_warnings = collect_portable_skills(root, skills_manifest)
    hook_scripts, hook_warnings = collect_hook_scripts(root, settings_manifest)
    settings_env_keys = resolve_settings_env_keys(settings_manifest, active_mcp_manifest)
    all_env_keys = set(settings_env_keys)
    for server in active_mcp_manifest["servers"].values():
        all_env_keys.update(server.get("env_keys", []))
    env_values, env_warnings = resolve_env_values(sorted(all_env_keys), profile["mcp_env"])

    warnings = (
        profile_warnings
        + mcp_filter_warnings
        + provider_warnings
        + skill_warnings
        + hook_warnings
        + env_warnings
    )
    actions: List[Action] = []

    claude_hooks_dir = home / ".claude" / "hooks"
    hook_command_paths = {name: claude_hooks_dir / name for name in hook_scripts}

    actions.extend(write_file_if_changed(shared_agents_target, home_agents_template, apply))
    actions.extend(
        desired_symlink(
            shared_agents_target,
            codex_agents_target,
            apply,
            replace_matching_content=home_agents_template,
        )
    )
    actions.extend(
        desired_symlink(
            shared_agents_target,
            claude_agents_link,
            apply,
            replace_matching_content=home_agents_template,
        )
    )
    actions.extend(write_file_if_changed(claude_wrapper_target, home_claude_template, apply))
    actions.extend(
        write_json_if_changed(
            claude_settings_target,
            render_claude_settings(
                settings_manifest,
                env_values,
                settings_env_keys,
                hook_command_paths,
                gateway_env,
            ),
            apply,
        )
    )
    actions.extend(write_json_if_changed(claude_mcp_target, render_claude_mcp(active_mcp_manifest, env_values), apply))

    master_key = resolve_gateway_master_key(machine_state, providers_manifest)
    actions.extend(
        write_file_if_changed(
            litellm_config_target,
            render_litellm_config(providers_manifest, master_key),
            apply,
        )
    )

    for name, source in hook_scripts.items():
        actions.extend(desired_symlink(source, claude_hooks_dir / name, apply))

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
    base_config = remove_managed_block(base_config, PROVIDERS_BLOCK_START, PROVIDERS_BLOCK_END)
    # Strip *all* manifest server sections (not just the active profile's allowlist)
    # so that disabling a server in a profile also removes its managed section from
    # the existing user config.toml.
    base_config = strip_managed_server_sections(base_config, mcp_manifest["servers"].keys())
    mcp_block = render_codex_mcp_block(active_mcp_manifest, env_values)
    providers_block = render_codex_providers_block(providers_manifest, machine_state)
    merged_config = upsert_managed_block(base_config, mcp_block)
    merged_config = upsert_managed_block(
        merged_config, providers_block, PROVIDERS_BLOCK_START, PROVIDERS_BLOCK_END
    )
    actions.extend(write_file_if_changed(codex_config_target, merged_config, apply))

    return actions, warnings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Synchronize shared coding-agent setup from repo-managed files.")
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
