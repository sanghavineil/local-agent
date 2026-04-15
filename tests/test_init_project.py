from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import init_project  # noqa: E402


class InitProjectTests(unittest.TestCase):
    def test_render_project_agents_includes_managed_markers(self) -> None:
        rendered = init_project.render_project_agents(ROOT)
        self.assertIn(init_project.LOCAL_AGENT_MARKER_START, rendered)
        self.assertIn(init_project.LOCAL_AGENT_MARKER_END, rendered)
        self.assertIn("Shared Agent Defaults", rendered)

    def test_update_existing_agents_refreshes_baseline_only(self) -> None:
        existing = init_project.render_project_agents(ROOT)
        existing = existing.replace("Operate in caveman mode", "Operate in old mode")
        existing = existing.replace("Add product/domain context here.", "Custom project context stays here.")

        updated = init_project.update_existing_agents(existing, ROOT)

        self.assertIsNotNone(updated)
        self.assertIn("Operate in caveman mode", updated)
        self.assertIn("Custom project context stays here.", updated)
        self.assertNotIn("Operate in old mode", updated)

    def test_run_init_project_writes_expected_files(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            project_root = Path(tempdir)

            lines = init_project.run_init_project(
                project_root=project_root,
                apply=True,
                force=False,
                with_impeccable_template=True,
            )

            self.assertTrue(any("AGENTS.md" in line for line in lines))
            self.assertTrue((project_root / "AGENTS.md").exists())
            self.assertTrue((project_root / "CLAUDE.md").exists())
            self.assertTrue((project_root / ".impeccable.md").exists())
            self.assertIn("@AGENTS.md", (project_root / "CLAUDE.md").read_text())


if __name__ == "__main__":
    unittest.main()
