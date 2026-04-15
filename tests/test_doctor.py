from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import doctor  # noqa: E402
import init_project  # noqa: E402
import sync_agent_parity  # noqa: E402


def dummy_machine_state() -> dict:
    return {
        "mcp_env": {
            "FIGMA_API_KEY": "figma-test",
            "JIRA_HOST": "https://example.atlassian.net",
            "JIRA_EMAIL": "neil@example.com",
            "JIRA_API_TOKEN": "jira-test",
        }
    }


class DoctorTests(unittest.TestCase):
    def test_check_home_is_clean_after_sync(self) -> None:
        with tempfile.TemporaryDirectory() as temp_home:
            with patch.object(sync_agent_parity, "load_machine_state", return_value=dummy_machine_state()):
                sync_agent_parity.run_sync(apply=True, home_override=temp_home)
                actions, warnings = doctor.check_home(home_override=temp_home)

            self.assertFalse(actions)
            self.assertFalse(warnings)

    def test_check_project_reports_missing_files(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            issues = doctor.check_project(Path(tempdir))

        self.assertTrue(any(issue.kind == "missing" and issue.path.name == "AGENTS.md" for issue in issues))
        self.assertTrue(any(issue.kind == "missing" and issue.path.name == "CLAUDE.md" for issue in issues))

    def test_check_project_detects_baseline_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            project_root = Path(tempdir)
            init_project.run_init_project(
                project_root=project_root,
                apply=True,
                force=False,
                with_impeccable_template=False,
            )

            agents_path = project_root / "AGENTS.md"
            drifted = agents_path.read_text().replace("Operate in caveman mode", "Operate in old mode")
            agents_path.write_text(drifted)

            issues = doctor.check_project(project_root)

        self.assertTrue(any(issue.kind == "drift" and issue.path.name == "AGENTS.md" for issue in issues))


if __name__ == "__main__":
    unittest.main()
