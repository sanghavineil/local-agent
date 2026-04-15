from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import sync_agent_parity  # noqa: E402


def base_providers_manifest() -> dict:
    return {
        "providers": {
            "anthropic-cloud": {
                "kind": "anthropic-direct",
                "display_name": "Anthropic Cloud",
                "default_model": "claude-opus-4-6",
            },
            "ollama-qwen": {
                "kind": "openai-compatible",
                "display_name": "Ollama",
                "base_url": "http://localhost:11434/v1",
                "default_model": "qwen2.5-coder:32b",
                "litellm_model": "ollama/qwen2.5-coder:32b",
                "auth": "none",
            },
            "lmstudio": {
                "kind": "openai-compatible",
                "display_name": "LM Studio",
                "base_url": "http://localhost:1234/v1",
                "default_model": "qwen2.5-coder-32b-instruct",
                "litellm_model": "openai/qwen2.5-coder-32b-instruct",
                "auth": "api-key",
            },
        },
        "gateway": {"port": 4000, "default_master_key": "local-agent-dev"},
    }


def state_with_profiles(active: str = "work") -> dict:
    return {
        "active_profile": active,
        "profiles": {
            "work": {
                "mcp_env": {
                    "FIGMA_API_KEY": "k",
                    "JIRA_HOST": "h",
                    "JIRA_EMAIL": "e",
                    "JIRA_API_TOKEN": "t",
                },
                "model_profile": "anthropic-cloud",
                "mcp_servers": ["figma", "atlassian-jira", "playwright"],
            },
            "personal": {
                "mcp_env": {"FIGMA_API_KEY": "k"},
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


class ResolveModelProviderTests(unittest.TestCase):
    def test_returns_provider_for_known_name(self) -> None:
        provider, warnings = sync_agent_parity.resolve_model_provider(
            {"model_profile": "ollama-qwen"}, base_providers_manifest()
        )
        self.assertIsNotNone(provider)
        self.assertEqual(provider["_name"], "ollama-qwen")
        self.assertEqual(provider["kind"], "openai-compatible")
        self.assertEqual(warnings, [])

    def test_returns_none_when_profile_has_no_model_profile(self) -> None:
        provider, warnings = sync_agent_parity.resolve_model_provider(
            {}, base_providers_manifest()
        )
        self.assertIsNone(provider)
        self.assertEqual(warnings, [])

    def test_unknown_provider_warns_and_returns_none(self) -> None:
        provider, warnings = sync_agent_parity.resolve_model_provider(
            {"model_profile": "ghost"}, base_providers_manifest()
        )
        self.assertIsNone(provider)
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].kind, "unknown-model-provider")

    def test_provider_with_missing_kind_warns_and_returns_none(self) -> None:
        manifest = {"providers": {"borked": {"display_name": "x", "base_url": "y"}}}
        provider, warnings = sync_agent_parity.resolve_model_provider(
            {"model_profile": "borked"}, manifest
        )
        self.assertIsNone(provider)
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].kind, "unknown-provider-kind")

    def test_provider_with_unrecognized_kind_warns_and_returns_none(self) -> None:
        manifest = {
            "providers": {
                "borked": {"kind": "magic-kind", "base_url": "y", "display_name": "x"}
            }
        }
        provider, warnings = sync_agent_parity.resolve_model_provider(
            {"model_profile": "borked"}, manifest
        )
        self.assertIsNone(provider)
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].kind, "unknown-provider-kind")

    def test_is_proxy_provider_classification(self) -> None:
        manifest = base_providers_manifest()
        self.assertFalse(sync_agent_parity.is_proxy_provider(None))
        self.assertFalse(
            sync_agent_parity.is_proxy_provider(manifest["providers"]["anthropic-cloud"])
        )
        self.assertTrue(
            sync_agent_parity.is_proxy_provider(manifest["providers"]["ollama-qwen"])
        )


class ResolveSettingsEnvKeysTests(unittest.TestCase):
    def test_no_conditional_keys_returns_unconditional_only(self) -> None:
        manifest = {"env_keys": ["A_KEY"]}
        active = {"servers": {}}
        self.assertEqual(
            sync_agent_parity.resolve_settings_env_keys(manifest, active), ["A_KEY"]
        )

    def test_conditional_key_included_when_server_active(self) -> None:
        manifest = {"env_keys": [], "conditional_env_keys": {"figma": ["FIGMA_API_KEY"]}}
        active = {"servers": {"figma": {}, "playwright": {}}}
        self.assertEqual(
            sync_agent_parity.resolve_settings_env_keys(manifest, active),
            ["FIGMA_API_KEY"],
        )

    def test_conditional_key_excluded_when_server_inactive(self) -> None:
        manifest = {"env_keys": [], "conditional_env_keys": {"figma": ["FIGMA_API_KEY"]}}
        active = {"servers": {"playwright": {}}}
        self.assertEqual(
            sync_agent_parity.resolve_settings_env_keys(manifest, active), []
        )

    def test_unconditional_and_conditional_dedup(self) -> None:
        manifest = {
            "env_keys": ["FIGMA_API_KEY"],
            "conditional_env_keys": {"figma": ["FIGMA_API_KEY"]},
        }
        active = {"servers": {"figma": {}}}
        self.assertEqual(
            sync_agent_parity.resolve_settings_env_keys(manifest, active),
            ["FIGMA_API_KEY"],
        )


class MasterKeyYamlSafetyTests(unittest.TestCase):
    def test_master_key_with_colon_renders_quoted(self) -> None:
        manifest = base_providers_manifest()
        config = sync_agent_parity.render_litellm_config(manifest, "user:has:colons")
        self.assertIn("master_key: 'user:has:colons'", config)

    def test_master_key_with_single_quote_is_doubled(self) -> None:
        manifest = base_providers_manifest()
        config = sync_agent_parity.render_litellm_config(manifest, "it's-mine")
        self.assertIn("master_key: 'it''s-mine'", config)


class GatewayEnvTests(unittest.TestCase):
    def test_anthropic_direct_returns_empty(self) -> None:
        manifest = base_providers_manifest()
        env = sync_agent_parity.gateway_env_for_profile(
            manifest["providers"]["anthropic-cloud"],
            state_with_profiles("work"),
            manifest,
        )
        self.assertEqual(env, {})

    def test_proxy_provider_emits_base_url_and_token(self) -> None:
        manifest = base_providers_manifest()
        env = sync_agent_parity.gateway_env_for_profile(
            manifest["providers"]["ollama-qwen"],
            state_with_profiles("local"),
            manifest,
        )
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "http://localhost:4000")
        self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "local-agent-dev")

    def test_per_profile_master_key_overrides_default(self) -> None:
        manifest = base_providers_manifest()
        state = state_with_profiles("local")
        state["profiles"]["local"]["gateway"] = {"master_key": "super-secret-xyz"}
        env = sync_agent_parity.gateway_env_for_profile(
            manifest["providers"]["ollama-qwen"], state, manifest
        )
        self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "super-secret-xyz")


class RenderCodexProvidersBlockTests(unittest.TestCase):
    def test_renders_provider_section_only_for_referenced_proxies(self) -> None:
        manifest = base_providers_manifest()
        state = state_with_profiles("work")
        block = sync_agent_parity.render_codex_providers_block(manifest, state)
        # ollama-qwen is referenced by the `local` profile so it must appear.
        self.assertIn("[model_providers.ollama-qwen]", block)
        # lmstudio is defined in the manifest but not referenced by any profile.
        self.assertNotIn("[model_providers.lmstudio]", block)

    def test_renders_profile_block_for_each_machine_profile(self) -> None:
        manifest = base_providers_manifest()
        state = state_with_profiles("work")
        block = sync_agent_parity.render_codex_providers_block(manifest, state)
        for name in ("work", "personal", "local"):
            self.assertIn(f"[profiles.{name}]", block)

    def test_anthropic_direct_profile_omits_model_provider_line(self) -> None:
        manifest = base_providers_manifest()
        state = state_with_profiles("work")
        block = sync_agent_parity.render_codex_providers_block(manifest, state)
        # Crude but effective slice: text between `[profiles.work]` and the next blank line.
        marker = "[profiles.work]"
        chunk = block.split(marker, 1)[1].split("\n\n", 1)[0]
        self.assertIn('model = "claude-opus-4-6"', chunk)
        self.assertNotIn("model_provider", chunk)

    def test_proxy_profile_includes_model_provider_line(self) -> None:
        manifest = base_providers_manifest()
        state = state_with_profiles("local")
        block = sync_agent_parity.render_codex_providers_block(manifest, state)
        chunk = block.split("[profiles.local]", 1)[1].split("\n\n", 1)[0]
        self.assertIn('model_provider = "ollama-qwen"', chunk)
        self.assertIn('model = "qwen2.5-coder:32b"', chunk)


class RenderLitellmConfigTests(unittest.TestCase):
    def test_includes_only_openai_compatible_providers(self) -> None:
        manifest = base_providers_manifest()
        config = sync_agent_parity.render_litellm_config(manifest, "test-key")
        self.assertIn("model_name: ollama-qwen", config)
        self.assertIn("model_name: lmstudio", config)
        self.assertNotIn("anthropic-cloud", config)

    def test_master_key_passed_through(self) -> None:
        manifest = base_providers_manifest()
        config = sync_agent_parity.render_litellm_config(manifest, "secret-99")
        self.assertIn("master_key: 'secret-99'", config)

    def test_api_key_emitted_for_api_key_auth(self) -> None:
        manifest = base_providers_manifest()
        config = sync_agent_parity.render_litellm_config(manifest, "x")
        # lmstudio uses auth=api-key, ollama-qwen uses auth=none
        self.assertIn("api_key: not-needed", config)


class RunSyncWithModelProvidersTests(unittest.TestCase):
    def test_local_profile_writes_proxy_env_and_litellm_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_home:
            with patch.object(
                sync_agent_parity, "load_machine_state", return_value=state_with_profiles("local")
            ):
                actions, warnings = sync_agent_parity.run_sync(apply=True, home_override=temp_home)

            self.assertFalse(warnings)
            home = Path(temp_home)

            settings = json.loads((home / ".claude" / "settings.json").read_text())
            self.assertIn("env", settings)
            self.assertEqual(settings["env"]["ANTHROPIC_BASE_URL"], "http://localhost:4000")
            self.assertEqual(settings["env"]["ANTHROPIC_AUTH_TOKEN"], "local-agent-dev")
            # Local profile excludes the figma MCP server, so the conditional env
            # key must not leak into Claude's settings.
            self.assertNotIn("FIGMA_API_KEY", settings["env"])

            litellm_config = (home / ".config" / "litellm" / "config.yaml").read_text()
            self.assertIn("model_name: ollama-qwen", litellm_config)
            self.assertIn("master_key: 'local-agent-dev'", litellm_config)

            codex_config = (home / ".codex" / "config.toml").read_text()
            self.assertIn("BEGIN local-agent providers managed block", codex_config)
            self.assertIn("[model_providers.ollama-qwen]", codex_config)
            self.assertIn("[profiles.local]", codex_config)
            self.assertTrue(actions)

    def test_work_profile_omits_proxy_env(self) -> None:
        with tempfile.TemporaryDirectory() as temp_home:
            with patch.object(
                sync_agent_parity, "load_machine_state", return_value=state_with_profiles("work")
            ):
                _, warnings = sync_agent_parity.run_sync(apply=True, home_override=temp_home)

            self.assertFalse(warnings)
            home = Path(temp_home)
            settings = json.loads((home / ".claude" / "settings.json").read_text())
            env = settings.get("env", {})
            self.assertNotIn("ANTHROPIC_BASE_URL", env)
            self.assertNotIn("ANTHROPIC_AUTH_TOKEN", env)
            self.assertEqual(env.get("FIGMA_API_KEY"), "k")

    def test_switching_profile_flips_codex_provider_blocks_and_claude_env(self) -> None:
        with tempfile.TemporaryDirectory() as temp_home:
            with patch.object(
                sync_agent_parity, "load_machine_state", return_value=state_with_profiles("work")
            ):
                sync_agent_parity.run_sync(apply=True, home_override=temp_home)

            home = Path(temp_home)
            settings_before = json.loads((home / ".claude" / "settings.json").read_text())
            self.assertNotIn("ANTHROPIC_BASE_URL", settings_before.get("env", {}))

            with patch.object(
                sync_agent_parity, "load_machine_state", return_value=state_with_profiles("local")
            ):
                sync_agent_parity.run_sync(apply=True, home_override=temp_home)

            settings_after = json.loads((home / ".claude" / "settings.json").read_text())
            self.assertEqual(
                settings_after["env"]["ANTHROPIC_BASE_URL"], "http://localhost:4000"
            )

            codex_after = (home / ".codex" / "config.toml").read_text()
            self.assertIn("[model_providers.ollama-qwen]", codex_after)
            # Both block sentinels present and only once each.
            self.assertEqual(codex_after.count("BEGIN local-agent parity managed block"), 1)
            self.assertEqual(codex_after.count("BEGIN local-agent providers managed block"), 1)


if __name__ == "__main__":
    unittest.main()
