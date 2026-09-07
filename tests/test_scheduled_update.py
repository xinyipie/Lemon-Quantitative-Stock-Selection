import unittest
from pathlib import Path


class ScheduledUpdateTest(unittest.TestCase):
    def test_daily_full_update_uses_dashboard_status_worker(self):
        script = Path("deploy/stock-daily-full-update").read_text(encoding="utf-8")

        self.assertIn("web_app.services.update_worker", script)
        self.assertIn("data/web_update_status.json", script)
        self.assertIn("logs/daily_full_update.log", script)
        self.assertIn('daily_web_update.py", "--mode", "full"', script)
        self.assertIn('"--skip-daily-report"', script)

    def test_market_radar_update_persists_worker_output(self):
        script = Path("deploy/stock-market-radar-update").read_text(encoding="utf-8")
        self.assertIn("web_app.services.update_worker", script)
        self.assertIn("logs/market_radar_update.log", script)
        self.assertIn('"--skip-daily-report"', script)

    def test_full_retry_only_runs_when_today_full_update_is_not_finished(self):
        script = Path("deploy/stock-daily-full-retry").read_text(encoding="utf-8")
        self.assertIn('needs_full_update_retry()', script)
        self.assertIn("/usr/local/sbin/stock-daily-full-update", script)

    def test_daily_report_has_independent_status_and_log(self):
        script = Path("deploy/stock-daily-report").read_text(encoding="utf-8")
        self.assertIn("daily_research_report.py", script)
        self.assertIn('"--slot", "morning"', script)
        self.assertIn('"--retry-if-missing"', script)
        self.assertIn("data/daily_report_status.json", script)
        self.assertIn("logs/daily_report_update.log", script)


if __name__ == "__main__":
    unittest.main()
