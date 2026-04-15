from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import profile as profile_cmd  # noqa: E402
import sync_agent_parity  # noqa: E402


def profiled_machine_state(active: str = "work") -> dict:
    return {
        "active_profile": active,
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
            },
            "personal": {
                "mcp_env": {"FIGMA_API_KEY": "figma-personal"},
                "model_profile": "anthropic-cloud",
                "mcp_servers": ["figma", "playwright"],
            },
            "local": {
                "mcp_env": {},
                "model_profile": "ollama-qwen",
                "mcp_servers": ["playwright"],
            },
        },
    }


def legacy_machine_state() -> dict:
    return {
        "mcp_env": {
            "FIGMA_API_KEY": "figma-test",
            "JIRA_HOST": "https://example.atlassian.net",
            "JIRA_EMAIL": "neil@example.com",
            "JIRA_API_TOKEN": "jira-test",
        }
    }


class LoadActiveProfileTests(unittest.TestCase):
    def test_legacy_flat_schema_returns_no_allowlist(self) -> None:
        profile, warnings = sync_agent_parity.load_active_profile(legacy_machine_state())
        self.assertEqual(profile["name"], None)
        self.assertEqual(profile["mcp_env"]["FIGMA_API_KEY"], "figma-test")
        self.assertIsNone(profile["mcp_servers"])
        self.assertIsNone(profile["model_profile"])
        self.assertEqual(warnings, [])

    def test_profiled_schema_returns_active_profile(self) -> None:
        profile, warnings = sync_agent_parity.load_active_profile(profiled_machine_state("personal"))
        self.assertEqual(profile["name"], "personal")
        self.assertEqual(profile["mcp_env"], {"FIGMA_API_KEY": "figma-personal"})
        self.assertEqual(profile["mcp_servers"], ["figma", "playwright"])
        self.assertEqual(profile["model_profile"], "anthropic-cloud")
        self.assertEqual(warnings, [])

    def test_missing_active_profile_field_raises(self) -> None:
        state = profiled_machine_state()
        del state["active_profile"]
        with self.assertRaises(ValueError):
            sync_agent_parity.load_active_profile(state)

    def test_unknown_active_profile_raises(self) -> None:
        state = profiled_machine_state()
        state["active_profile"] = "ghost"
        with self.assertRaises(ValueError):
            sync_agent_parity.load_active_profile(state)

    def test_empty_profiles_dict_raises(self) -> None:
        state = {"active_profile": "work", "profiles": {}}
        with self.assertRaises(ValueError):
            sync_agent_parity.load_active_profile(state)


class FilterMcpManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = sync_agent_parity.load_json(ROOT / "manifests" / "mcp_servers.json")

    def test_none_allowlist_returns_full_manifest(self) -> None:
        filtered, warnings = sync_agent_parity.filter_mcp_manifest(self.manifest, None)
        self.assertEqual(filtered, self.manifest)
        self.assertEqual(warnings, [])

    def test_allowlist_narrows_servers(self) -> None:
        filtered, warnings = sync_agent_parity.filter_mcp_manifest(self.manifest, ["figma", "playwright"])
        self.assertEqual(set(filtered["servers"]), {"figma", "playwright"})
        self.assertEqual(warnings, [])

    def test_unknown_server_in_allowlist_emits_warning(self) -> None:
        filtered, warnings = sync_agent_parity.filter_mcp_manifest(
            self.manifest, ["figma", "ghost-server"]
        )
        self.assertEqual(set(filtered["servers"]), {"figma"})
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].kind, "unknown-mcp-server")
        self.assertEqual(warnings[0].detail, "ghost-server")


class RunSyncWithProfilesTests(unittest.TestCase):
    def test_profile_filters_rendered_mcp_servers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_home:
            with patch.object(
                sync_agent_parity, "load_machine_state", return_value=profiled_machine_state("local")
            ):
                actions, warnings = sync_agent_parity.run_sync(apply=True, home_override=temp_home)

            self.assertFalse(warnings)
            home = Path(temp_home)

            claude_mcp = json.loads((home / ".claude" / ".mcp.json").read_text())
            self.assertEqual(set(claude_mcp["mcpServers"]), {"playwright"})

            codex_config = (home / ".codex" / "config.toml").read_text()
            self.assertIn("[mcp_servers.playwright]", codex_config)
            self.assertNotIn("[mcp_servers.figma]", codex_config)
            self.assertNotIn("[mcp_servers.atlassian-jira]", codex_config)

            self.assertTrue(actions)

    def test_switching_profile_strips_disabled_servers_from_codex_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_home:
            # Render with the work profile first (figma + jira + playwright).
            with patch.object(
                sync_agent_parity, "load_machine_state", return_value=profiled_machine_state("work")
            ):
                sync_agent_parity.run_sync(apply=True, home_override=temp_home)

            codex_config = (Path(temp_home) / ".codex" / "config.toml").read_text()
            self.assertIn("[mcp_servers.atlassian-jira]", codex_config)

            # Switch to personal (drops jira) and re-render.
            with patch.object(
                sync_agent_parity, "load_machine_state", return_value=profiled_machine_state("personal")
            ):
                sync_agent_parity.run_sync(apply=True, home_override=temp_home)

            codex_config_after = (Path(temp_home) / ".codex" / "config.toml").read_text()
            self.assertIn("[mcp_servers.figma]", codex_config_after)
            self.assertNotIn("[mcp_servers.atlassian-jira]", codex_config_after)

    def test_legacy_flat_schema_emits_migration_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temp_home:
            with patch.object(
                sync_agent_parity, "load_machine_state", return_value=legacy_machine_state()
            ):
                _, warnings = sync_agent_parity.run_sync(apply=True, home_override=temp_home)

            kinds = [w.kind for w in warnings]
            self.assertIn("legacy-machine-schema", kinds)


class ProfileCommandTests(unittest.TestCase):
    def _patched_paths(self, temp_root: Path):
        machine_local = temp_root / "config" / "machine.local.json"
        machine_local.parent.mkdir(parents=True, exist_ok=True)
        machine_local.write_text(json.dumps(profiled_machine_state("work"), indent=2) + "\n")
        return patch.object(profile_cmd, "machine_local_path", return_value=machine_local)

    def test_list_marks_active_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            with self._patched_paths(Path(temp_root)):
                lines = profile_cmd.run("list")
        joined = "\n".join(lines)
        self.assertIn("* work", joined)
        self.assertIn("  personal", joined)
        self.assertIn("  local", joined)

    def test_show_defaults_to_active(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            with self._patched_paths(Path(temp_root)):
                lines = profile_cmd.run("show")
        joined = "\n".join(lines)
        self.assertIn("profile: work", joined)
        self.assertIn("(active)", joined)
        self.assertIn("figma, atlassian-jira, playwright", joined)

    def test_show_specific_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            with self._patched_paths(Path(temp_root)):
                lines = profile_cmd.run("show", name="local")
        joined = "\n".join(lines)
        self.assertIn("profile: local", joined)
        self.assertNotIn("(active)", joined)
        self.assertIn("ollama-qwen", joined)

    def test_use_dry_run_does_not_persist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            with self._patched_paths(Path(temp_root)):
                lines = profile_cmd.run("use", name="personal", apply=False)
                state = profile_cmd.load_machine_local()
        self.assertIn("Would switch", "\n".join(lines))
        self.assertEqual(state["active_profile"], "work")

    def test_use_apply_persists_change(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            with self._patched_paths(Path(temp_root)):
                lines = profile_cmd.run("use", name="personal", apply=True)
                state = profile_cmd.load_machine_local()
        self.assertIn("Active profile: work -> personal", "\n".join(lines))
        self.assertEqual(state["active_profile"], "personal")

    def test_use_unknown_profile_raises(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            with self._patched_paths(Path(temp_root)):
                with self.assertRaises(ValueError):
                    profile_cmd.run("use", name="ghost", apply=True)

    def test_use_already_active_is_noop(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            with self._patched_paths(Path(temp_root)):
                lines = profile_cmd.run("use", name="work", apply=True)
        self.assertIn("already active", "\n".join(lines))

    def test_legacy_schema_rejects_profile_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            machine_local = Path(temp_root) / "config" / "machine.local.json"
            machine_local.parent.mkdir(parents=True, exist_ok=True)
            machine_local.write_text(json.dumps(legacy_machine_state(), indent=2) + "\n")
            with patch.object(profile_cmd, "machine_local_path", return_value=machine_local):
                with self.assertRaises(ValueError):
                    profile_cmd.run("list")


if __name__ == "__main__":
    unittest.main()
