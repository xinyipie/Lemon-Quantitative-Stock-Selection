import unittest
from pathlib import Path


class ScheduledUpdateTest(unittest.TestCase):
    def test_daily_full_update_uses_dashboard_status_worker(self):
        script = Path("deploy/stock-daily-full-update").read_text(encoding="utf-8")

        self.assertIn("web_app.services.update_worker", script)
        self.assertIn("data/web_update_status.json", script)
        self.assertIn('daily_web_update.py", "--mode", "full"', script)


if __name__ == "__main__":
    unittest.main()
