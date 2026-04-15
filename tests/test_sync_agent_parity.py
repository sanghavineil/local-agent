from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import sync_agent_parity  # noqa: E402


def dummy_machine_state() -> dict:
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


class SyncAgentParityTests(unittest.TestCase):
    def test_run_sync_writes_managed_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_home:
            with patch.object(sync_agent_parity, "load_machine_state", return_value=dummy_machine_state()):
                actions, warnings = sync_agent_parity.run_sync(apply=True, home_override=temp_home)

            self.assertFalse(warnings)
            self.assertTrue(actions)

            home = Path(temp_home)
            shared_agents = home / ".agents" / "AGENTS.md"
            codex_agents = home / ".codex" / "AGENTS.md"
            claude_agents = home / ".claude" / "AGENTS.md"
            claude_wrapper = home / ".claude" / "CLAUDE.md"
            codex_config = home / ".codex" / "config.toml"
            caveman_link = home / ".agents" / "skills" / "caveman"

            self.assertTrue(shared_agents.exists())
            self.assertTrue(codex_agents.is_symlink())
            self.assertTrue(claude_agents.is_symlink())
            self.assertEqual(Path(os.readlink(codex_agents)), shared_agents)
            self.assertEqual(Path(os.readlink(claude_agents)), shared_agents)
            self.assertIn("caveman mode", shared_agents.read_text())
            self.assertIn("@AGENTS.md", claude_wrapper.read_text())
            self.assertIn("BEGIN local-agent parity managed block", codex_config.read_text())
            self.assertTrue(caveman_link.is_symlink())

    def test_run_sync_relinks_existing_managed_codex_agents_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_home:
            home = Path(temp_home)
            managed_text = (ROOT / "templates" / "home" / "AGENTS.md").read_text()
            codex_agents = home / ".codex" / "AGENTS.md"
            codex_agents.parent.mkdir(parents=True, exist_ok=True)
            codex_agents.write_text(managed_text)

            with patch.object(sync_agent_parity, "load_machine_state", return_value=dummy_machine_state()):
                actions, warnings = sync_agent_parity.run_sync(apply=True, home_override=temp_home)

            self.assertFalse(warnings)
            self.assertTrue(codex_agents.is_symlink())
            self.assertEqual(Path(os.readlink(codex_agents)), home / ".agents" / "AGENTS.md")
            self.assertTrue(
                any(action.kind == "replace-file" and action.target == codex_agents for action in actions)
            )

    def test_run_sync_flags_divergent_hand_edited_codex_agents_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_home:
            home = Path(temp_home)
            codex_agents = home / ".codex" / "AGENTS.md"
            codex_agents.parent.mkdir(parents=True, exist_ok=True)
            codex_agents.write_text("# my hand-edited overrides\nkeep me\n")

            with patch.object(sync_agent_parity, "load_machine_state", return_value=dummy_machine_state()):
                actions, warnings = sync_agent_parity.run_sync(apply=True, home_override=temp_home)

            self.assertFalse(warnings)
            self.assertFalse(codex_agents.is_symlink())
            self.assertEqual(codex_agents.read_text(), "# my hand-edited overrides\nkeep me\n")
            self.assertTrue(
                any(
                    action.kind == "skip-divergent" and action.target == codex_agents
                    for action in actions
                ),
                f"expected skip-divergent action for {codex_agents}, got {[(a.kind, a.target) for a in actions]}",
            )

    def test_run_sync_skips_existing_skill_directory_without_adoption(self) -> None:
        with tempfile.TemporaryDirectory() as temp_home:
            home = Path(temp_home)
            existing_skill = home / ".agents" / "skills" / "adapt"
            existing_skill.mkdir(parents=True, exist_ok=True)
            (existing_skill / "local-only.txt").write_text("keep me\n")

            with patch.object(sync_agent_parity, "load_machine_state", return_value=dummy_machine_state()):
                actions, warnings = sync_agent_parity.run_sync(
                    apply=True,
                    home_override=temp_home,
                    adopt_existing_skills=False,
                )

            self.assertFalse(warnings)
            self.assertTrue(existing_skill.is_dir())
            self.assertFalse(existing_skill.is_symlink())
            self.assertEqual((existing_skill / "local-only.txt").read_text(), "keep me\n")
            self.assertTrue(any(action.kind == "skip" and action.target == existing_skill for action in actions))

    def test_run_sync_adopts_existing_skill_directory_with_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_home:
            home = Path(temp_home)
            existing_skill = home / ".agents" / "skills" / "adapt"
            existing_skill.mkdir(parents=True, exist_ok=True)
            (existing_skill / "local-only.txt").write_text("move me\n")

            with patch.object(sync_agent_parity, "load_machine_state", return_value=dummy_machine_state()):
                actions, warnings = sync_agent_parity.run_sync(
                    apply=True,
                    home_override=temp_home,
                    adopt_existing_skills=True,
                )

            self.assertFalse(warnings)
            self.assertTrue(existing_skill.is_symlink())
            backups = list((home / ".agents" / "skills").glob("adapt.bak-local-agent-*"))
            self.assertEqual(len(backups), 1)
            self.assertTrue((backups[0] / "local-only.txt").exists())
            self.assertTrue(any(action.kind == "backup" and action.target == existing_skill for action in actions))


if __name__ == "__main__":
    unittest.main()
