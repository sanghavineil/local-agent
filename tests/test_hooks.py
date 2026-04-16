from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import sync_agent_parity  # noqa: E402


def profiled_state() -> dict:
    return {
        "active_profile": "work",
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
            }
        },
    }


class CollectHookScriptsTests(unittest.TestCase):
    def test_collects_referenced_scripts_from_repo(self) -> None:
        manifest = sync_agent_parity.load_json(ROOT / "manifests" / "claude_settings.json")
        scripts, warnings = sync_agent_parity.collect_hook_scripts(ROOT, manifest)
        self.assertIn("notify-done.sh", scripts)
        self.assertEqual(warnings, [])

    def test_missing_script_emits_warning(self) -> None:
        manifest = {"hooks": {"Stop": [{"script": "ghost.sh"}]}}
        scripts, warnings = sync_agent_parity.collect_hook_scripts(ROOT, manifest)
        self.assertEqual(scripts, {})
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].kind, "missing-hook-script")
        self.assertEqual(warnings[0].detail, "ghost.sh")

    def test_non_executable_script_emits_warning(self) -> None:
        with tempfile.TemporaryDirectory() as fake_repo:
            fake_root = Path(fake_repo)
            hooks_dir = fake_root / "templates" / "home" / "claude" / "hooks"
            hooks_dir.mkdir(parents=True)
            script_path = hooks_dir / "noexec.sh"
            script_path.write_text("#!/bin/sh\nexit 0\n")
            # explicitly strip exec bit
            script_path.chmod(stat.S_IRUSR | stat.S_IWUSR)

            manifest = {"hooks": {"Stop": [{"script": "noexec.sh"}]}}
            scripts, warnings = sync_agent_parity.collect_hook_scripts(fake_root, manifest)

            self.assertIn("noexec.sh", scripts)
            self.assertTrue(any(w.kind == "non-executable-hook" for w in warnings))


class RenderHooksTests(unittest.TestCase):
    def test_script_field_resolves_to_absolute_command_path(self) -> None:
        manifest_hooks = {"Stop": [{"script": "notify-done.sh"}]}
        paths = {"notify-done.sh": Path("/Users/x/.claude/hooks/notify-done.sh")}
        rendered = sync_agent_parity.render_hooks(manifest_hooks, paths)
        self.assertEqual(
            rendered,
            {
                "Stop": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": "/Users/x/.claude/hooks/notify-done.sh",
                            }
                        ]
                    }
                ]
            },
        )

    def test_matcher_field_passes_through(self) -> None:
        manifest_hooks = {
            "PreToolUse": [{"matcher": "Bash(*)", "script": "notify-done.sh"}]
        }
        paths = {"notify-done.sh": Path("/Users/x/.claude/hooks/notify-done.sh")}
        rendered = sync_agent_parity.render_hooks(manifest_hooks, paths)
        self.assertEqual(
            rendered,
            {
                "PreToolUse": [
                    {
                        "matcher": "Bash(*)",
                        "hooks": [
                            {
                                "type": "command",
                                "command": "/Users/x/.claude/hooks/notify-done.sh",
                            }
                        ],
                    }
                ]
            },
        )

    def test_raw_command_passes_through(self) -> None:
        manifest_hooks = {"Stop": [{"command": "echo done"}]}
        rendered = sync_agent_parity.render_hooks(manifest_hooks, {})
        self.assertEqual(
            rendered,
            {"Stop": [{"hooks": [{"type": "command", "command": "echo done"}]}]},
        )

    def test_unresolved_script_is_dropped(self) -> None:
        manifest_hooks = {"Stop": [{"script": "missing.sh"}]}
        rendered = sync_agent_parity.render_hooks(manifest_hooks, {})
        self.assertEqual(rendered, {})


class RunSyncWithHooksTests(unittest.TestCase):
    def test_hook_script_symlinked_and_referenced_by_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_home:
            with patch.object(
                sync_agent_parity, "load_machine_state", return_value=profiled_state()
            ):
                actions, warnings = sync_agent_parity.run_sync(apply=True, home_override=temp_home)

            self.assertFalse(warnings)

            home = Path(temp_home)
            hook_link = home / ".claude" / "hooks" / "notify-done.sh"
            self.assertTrue(hook_link.is_symlink())
            self.assertEqual(
                Path(os.readlink(hook_link)),
                ROOT / "templates" / "home" / "claude" / "hooks" / "notify-done.sh",
            )

            settings = json.loads((home / ".claude" / "settings.json").read_text())
            self.assertIn("hooks", settings)
            stop_hooks = settings["hooks"]["Stop"]
            self.assertEqual(len(stop_hooks), 1)
            self.assertEqual(
                stop_hooks[0]["hooks"],
                [{"type": "command", "command": str(hook_link)}],
            )

            self.assertTrue(
                any(action.kind == "link" and action.target == hook_link for action in actions)
            )


if __name__ == "__main__":
    unittest.main()
