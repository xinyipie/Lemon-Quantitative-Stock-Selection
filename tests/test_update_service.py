import json
import tempfile
import unittest
from pathlib import Path

from web_app.services.update_service import (
    build_update_command,
    decorate_update_status_with_freshness,
    read_update_status,
    run_update_job,
)


class UpdateServiceTest(unittest.TestCase):
    def test_build_update_command_defaults_to_daily_mode(self):
        command = build_update_command(end="20260616")

        self.assertIn("daily_web_update.py", command)
        self.assertIn("--end", command)
        self.assertIn("20260616", command)
        self.assertIn("--mode", command)
        self.assertIn("daily", command)
        self.assertNotIn("--full-history", command)

    def test_build_update_command_can_request_full_mode(self):
        command = build_update_command(end="20260616", mode="full", full_history=True)

        self.assertIn("--mode", command)
        self.assertIn("full", command)
        self.assertIn("--full-history", command)

    def test_run_update_job_records_finished_status(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            status_path = Path(tmpdir) / "status.json"
            calls = []

            def fake_runner(command, **kwargs):
                calls.append(command)

                class Result:
                    returncode = 0
                    stdout = "ok"
                    stderr = ""

                return Result()

            run_update_job(["python", "daily_web_update.py"], status_path=status_path, runner=fake_runner)
            status = read_update_status(status_path=status_path)

        self.assertEqual(calls, [["python", "daily_web_update.py"]])
        self.assertEqual(status["state"], "finished")
        self.assertEqual(status["returncode"], 0)
        self.assertEqual(status["stdout_tail"], "ok")

    def test_read_update_status_handles_missing_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            status = read_update_status(status_path=Path(tmpdir) / "missing.json")

        self.assertEqual(status["state"], "idle")
        self.assertFalse(status["running"])

    def test_finished_update_status_warns_when_freshness_is_not_aligned(self):
        status = {
            "state": "finished",
            "running": False,
            "message": "同步完成。",
            "finished_at": "2026-06-22 10:00:00",
        }
        freshness = {
            "status_label": "行情滞后",
            "warnings": ["历史行情库最新到 20260617，落后最近实盘信号 1 个交易日。"],
        }

        decorated = decorate_update_status_with_freshness(status, freshness)

        self.assertFalse(decorated["aligned"])
        self.assertEqual(decorated["alignment_state"], "warn")
        self.assertIn("数据未对齐", decorated["display_message"])
        self.assertIn("行情滞后", decorated["display_message"])

    def test_finished_update_status_reports_aligned_when_no_freshness_warning(self):
        status = {"state": "finished", "running": False, "message": "同步完成。"}
        freshness = {"status_label": "数据正常", "warnings": []}

        decorated = decorate_update_status_with_freshness(status, freshness)

        self.assertTrue(decorated["aligned"])
        self.assertEqual(decorated["alignment_state"], "ok")
        self.assertEqual(decorated["display_message"], "同步完成，数据已对齐。")


if __name__ == "__main__":
    unittest.main()
