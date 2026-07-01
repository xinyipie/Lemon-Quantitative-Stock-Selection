import json
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime
from pathlib import Path

from web_app.services.update_service import (
    _merge_status,
    _running_message,
    build_update_command,
    build_update_worker_command,
    decorate_update_status_with_freshness,
    read_update_status,
    run_update_job,
    start_web_update,
)
from web_app.services.update_worker import main as update_worker_main


class UpdateServiceTest(unittest.TestCase):
    def test_build_update_command_defaults_to_daily_mode(self):
        command = build_update_command(end="20260616")

        self.assertIn("daily_web_update.py", command)
        self.assertIn("--end", command)
        self.assertIn("20260616", command)
        self.assertIn("--mode", command)
        self.assertIn("daily", command)
        self.assertIn("--fast", command)
        self.assertNotIn("--full-history", command)

    def test_build_update_command_can_request_full_mode(self):
        command = build_update_command(end="20260616", mode="full", full_history=True)

        self.assertIn("--mode", command)
        self.assertIn("full", command)
        self.assertIn("--full-history", command)
        self.assertNotIn("--fast", command)

    def test_build_update_command_can_request_dragon_mode(self):
        command = build_update_command(end="20260616", mode="dragon")

        self.assertIn("--mode", command)
        self.assertIn("dragon", command)
        self.assertIn("--end", command)
        self.assertIn("20260616", command)
        self.assertNotIn("--fast", command)
        self.assertNotIn("--full-history", command)

    def test_build_update_command_can_request_radar_mode(self):
        command = build_update_command(end="20260616", mode="radar")

        self.assertIn("--mode", command)
        self.assertIn("radar", command)
        self.assertIn("--end", command)
        self.assertIn("20260616", command)
        self.assertNotIn("--fast", command)
        self.assertNotIn("--full-history", command)

    def test_topic_running_messages_explain_core_history_refresh(self):
        dragon = _running_message(["python", "daily_web_update.py", "--mode", "dragon"])
        radar = _running_message(["python", "daily_web_update.py", "--mode", "radar"])

        self.assertIn("先更新核心行情", dragon)
        self.assertIn("刷新涨停池和龙头观察池", dragon)
        self.assertIn("先更新核心行情", radar)
        self.assertIn("刷新市场上下文和雷达快照", radar)

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

    def test_start_web_update_fails_fast_when_process_never_starts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            status_path = Path(tmpdir) / "status.json"
            status = start_web_update(
                mode="dragon",
                status_path=status_path,
                launcher=lambda command: None,
                startup_timeout_seconds=0.01,
            )

        self.assertEqual(status["state"], "failed")
        self.assertFalse(status["running"])
        self.assertIn("未能启动", status["message"])

    def test_build_update_worker_command_wraps_update_job(self):
        command = ["python", "daily_web_update.py", "--mode", "dragon"]
        worker_command = build_update_worker_command(command, Path("data/status.json"))

        self.assertIn("-m", worker_command)
        self.assertIn("web_app.services.update_worker", worker_command)
        self.assertIn("daily_web_update.py", worker_command[3])
        self.assertEqual(worker_command[-1], str(Path("data/status.json")))

    def test_update_worker_entrypoint_runs_command_and_writes_status(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            status_path = Path(tmpdir) / "status.json"
            command = [sys.executable, "-c", "print('worker ok')"]

            returncode = update_worker_main([json.dumps(command), str(status_path)])
            status = read_update_status(status_path=status_path)

        self.assertEqual(returncode, 0)
        self.assertEqual(status["state"], "finished")
        self.assertIn("worker ok", status.get("stdout_tail", ""))

    def test_read_update_status_handles_missing_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            status = read_update_status(status_path=Path(tmpdir) / "missing.json")

        self.assertEqual(status["state"], "idle")
        self.assertFalse(status["running"])

    def test_read_update_status_expires_stale_running_lock(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            status_path = Path(tmpdir) / "status.json"
            status_path.write_text(
                json.dumps(
                    {
                        "state": "running",
                        "running": True,
                        "started_at": "2026-06-24 09:00:00",
                        "message": "running",
                    }
                ),
                encoding="utf-8",
            )

            status = read_update_status(
                status_path=status_path,
                stale_after_seconds=60,
                now=datetime(2026, 6, 24, 9, 2, 1),
            )

        self.assertEqual(status["state"], "failed")
        self.assertFalse(status["running"])
        self.assertIn("超时", status["message"])

    def test_read_update_status_uses_shorter_default_timeout_for_daily_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            status_path = Path(tmpdir) / "status.json"
            status_path.write_text(
                json.dumps(
                    {
                        "state": "running",
                        "running": True,
                        "mode": "daily",
                        "started_at": "2026-06-24 09:00:00",
                        "message": "running",
                    }
                ),
                encoding="utf-8",
            )

            status = read_update_status(
                status_path=status_path,
                now=datetime(2026, 6, 24, 9, 25, 1),
            )

        self.assertEqual(status["state"], "failed")
        self.assertFalse(status["running"])

    def test_read_update_status_expires_unstarted_running_job_quickly(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            status_path = Path(tmpdir) / "status.json"
            status_path.write_text(
                json.dumps(
                    {
                        "state": "running",
                        "running": True,
                        "mode": "dragon",
                        "started_at": "2026-07-01 09:57:21",
                        "updated_at": "2026-07-01 09:57:21",
                        "message": "热门龙头更新已开始，完成前请不要重复点击。",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            status = read_update_status(
                status_path=status_path,
                now=datetime(2026, 7, 1, 9, 57, 32),
            )

        self.assertEqual(status["state"], "failed")
        self.assertFalse(status["running"])
        self.assertIn("超时", status["message"])

    def test_run_update_job_streams_progress_before_process_finishes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            script_path = tmp_path / "slow_update.py"
            status_path = tmp_path / "status.json"
            script_path.write_text(
                "import time\n"
                "print('step one', flush=True)\n"
                "time.sleep(0.6)\n"
                "print('step two', flush=True)\n",
                encoding="utf-8",
            )

            worker = threading.Thread(
                target=run_update_job,
                args=([sys.executable, str(script_path)],),
                kwargs={"status_path": status_path},
            )
            worker.start()
            time.sleep(0.25)
            mid_status = read_update_status(status_path=status_path)
            worker.join(timeout=3)
            final_status = read_update_status(status_path=status_path)

        self.assertIn("step one", mid_status.get("stdout_tail", ""))
        self.assertTrue(mid_status["running"])
        self.assertEqual(final_status["state"], "finished")
        self.assertIn("step two", final_status.get("stdout_tail", ""))

    def test_merge_status_keeps_json_valid_under_concurrent_writes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            status_path = Path(tmpdir) / "status.json"

            def writer(index):
                for step in range(50):
                    _merge_status(status_path, {f"worker_{index}": step})

            workers = [threading.Thread(target=writer, args=(index,)) for index in range(8)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=3)

            status = json.loads(status_path.read_text(encoding="utf-8"))

        for index in range(8):
            self.assertEqual(status[f"worker_{index}"], 49)

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
