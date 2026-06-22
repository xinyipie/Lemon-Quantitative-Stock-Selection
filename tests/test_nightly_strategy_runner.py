import subprocess
import tempfile
import unittest
from pathlib import Path

from research.nightly_strategy_runner import run_nightly_research


class NightlyStrategyRunnerTest(unittest.TestCase):
    def test_refuses_to_run_outside_research_branch_by_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            result = run_nightly_research(
                root=root,
                until="23:59",
                runner=_FakeRunner(branch="main"),
                now_text="2026-06-22 20:00:00",
            )

        self.assertFalse(result["ok"])
        self.assertIn("codex/strategy-research", result["message"])
        self.assertEqual(result["tasks"], [])

    def test_runs_research_tasks_and_writes_nightly_report(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake = _FakeRunner(branch="codex/strategy-research")
            result = run_nightly_research(
                root=root,
                until="23:59",
                runner=fake,
                now_text="2026-06-22 20:00:00",
            )

            report = Path(result["report"])
            self.assertTrue(result["ok"])
            self.assertEqual(len(result["tasks"]), 5)
            self.assertTrue(report.exists())
            text = report.read_text(encoding="utf-8")

        self.assertIn("夜间策略研究运行报告", text)
        self.assertIn("strategy_research_overview.py", " ".join(fake.command_texts))
        self.assertIn("official_strategy_health_check.py", " ".join(fake.command_texts))


class _FakeRunner:
    def __init__(self, branch: str):
        self.branch = branch
        self.command_texts = []

    def __call__(self, command, cwd=None, text=True, capture_output=True, timeout=None, check=False):
        self.command_texts.append(" ".join(map(str, command)))
        if command[:3] == ["git", "branch", "--show-current"]:
            return subprocess.CompletedProcess(command, 0, stdout=self.branch + "\n", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="ok\n", stderr="")


if __name__ == "__main__":
    unittest.main()
