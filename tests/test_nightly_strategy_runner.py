import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from research.nightly_strategy_runner import (
    REQUIRED_CAPABILITIES,
    build_default_tasks,
    build_cycle_tasks,
    build_weekend_tasks,
    coverage_by_capability,
    parse_until,
    run_once,
    write_final_summary,
)


class NightlyStrategyRunnerTest(unittest.TestCase):
    def test_parse_until_accepts_absolute_beijing_datetime(self):
        value = parse_until("2026-06-28T20:00:00+08:00")

        self.assertEqual(value.isoformat(), "2026-06-28T20:00:00+08:00")

    def test_parse_until_accepts_wall_clock_today_in_beijing(self):
        now = datetime(2026, 6, 26, 16, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

        value = parse_until("20:00", now=now)

        self.assertEqual(value.isoformat(), "2026-06-26T20:00:00+08:00")

    def test_default_tasks_write_into_daily_research_directory(self):
        output_dir = Path("reports") / "research" / "nightly" / "20260626"

        tasks = build_default_tasks(output_dir)

        task_names = [task.name for task in tasks]
        self.assertIn("strategy_research_overview", task_names)
        self.assertIn("strategy_layer_quality", task_names)
        self.assertIn("strategy_factor_stability", task_names)
        self.assertIn("strategy_candidate_simulation", task_names)
        self.assertIn("official_strategy_health_check", task_names)
        for task in tasks:
            self.assertIn(str(output_dir), " ".join(task.command))

    def test_weekend_tasks_cover_all_research_capabilities(self):
        output_dir = Path("reports") / "research" / "nightly" / "20260626"

        tasks = build_weekend_tasks(output_dir, allow_data_download=True)
        coverage = coverage_by_capability(tasks)

        self.assertEqual(set(REQUIRED_CAPABILITIES), set(coverage))
        for capability, names in coverage.items():
            self.assertTrue(names, capability)

        commands = [" ".join(task.command) for task in tasks]
        self.assertTrue(any("data_downloader.py" in command and "--core-only" in command and "--only-new" not in command for command in commands))
        self.assertTrue(any("data_downloader.py" in command and "--core-only" not in command and "--only-new" not in command for command in commands))
        self.assertTrue(any("batch_backtest.py" in command and "--mode" in command for command in commands))
        self.assertTrue(any("market_context_snapshot.py" in command for command in commands))
        self.assertTrue(any("backfill_signal_explanations.py" in command and "--limit" in command for command in commands))
        self.assertTrue(any("longterm_pool_quality_audit.py" in command for command in commands))

    def test_cycle_tasks_run_full_first_then_light_until_interval(self):
        output_dir = Path("reports") / "research" / "nightly" / "20260626"

        first = build_cycle_tasks(output_dir, cycle_index=0, full_cycle_interval=4)
        second = build_cycle_tasks(output_dir, cycle_index=1, full_cycle_interval=4)
        fourth = build_cycle_tasks(output_dir, cycle_index=4, full_cycle_interval=4)

        self.assertTrue(any(task.name == "data_core_missing" for task in first))
        self.assertFalse(any(task.name == "data_core_missing" for task in second))
        self.assertTrue(any(task.name == "data_core_missing" for task in fourth))
        self.assertLess(len(second), len(first))

    def test_run_once_continues_after_task_failure_and_writes_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "reports" / "research" / "nightly" / "20260626"
            calls = []

            def fake_runner(command, **kwargs):
                calls.append(command)
                class Result:
                    returncode = 1 if "bad.py" in command else 0
                    stdout = "stdout"
                    stderr = "stderr" if returncode else ""

                return Result()

            results = run_once(
                tasks=[
                    ("ok", ["python", "ok.py"]),
                    ("bad", ["python", "bad.py"]),
                    ("later", ["python", "later.py"]),
                ],
                root=root,
                output_dir=output_dir,
                runner=fake_runner,
            )

            self.assertEqual([result.name for result in results], ["ok", "bad", "later"])
            self.assertEqual([result.returncode for result in results], [0, 1, 0])
            self.assertEqual(len(calls), 3)
            self.assertTrue((output_dir / "runner_state.json").exists())
            self.assertTrue((output_dir / "runner.log").exists())

    def test_write_final_summary_marks_failed_tasks_without_trading_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "reports" / "research" / "nightly" / "20260626"
            output_dir.mkdir(parents=True)

            summary = write_final_summary(
                output_dir=output_dir,
                started_at=datetime(2026, 6, 26, 20, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
                until=datetime(2026, 6, 28, 20, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
                cycles=[],
                skipped_reasons=["network disabled"],
            )

            text = summary.read_text(encoding="utf-8")
            self.assertIn("周末策略研究总结", text)
            self.assertIn("不包含自动交易", text)
            self.assertIn("network disabled", text)
            self.assertIn("能力覆盖", text)


if __name__ == "__main__":
    unittest.main()
