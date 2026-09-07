import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import daily_research_report


class DailyResearchReportCliTest(unittest.TestCase):
    def test_failed_generation_returns_nonzero_exit_code(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            signal_db = Path(tmpdir) / "signals.db"
            with patch.object(
                daily_research_report,
                "generate_daily_report",
                return_value={"status": "failed", "report_date": "20260806", "reason": "validation failed"},
            ):
                exit_code = daily_research_report.main(
                    [
                        "--report-date", "20260806",
                        "--market-date", "20260805",
                        "--signal-db", str(signal_db),
                        "--history-db", str(Path(tmpdir) / "history.db"),
                    ]
                )

        self.assertEqual(exit_code, 1)

    def test_published_generation_returns_success(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            signal_db = Path(tmpdir) / "signals.db"
            with patch.object(
                daily_research_report,
                "generate_daily_report",
                return_value={"status": "published", "report_date": "20260806", "version_id": 1},
            ):
                exit_code = daily_research_report.main(
                    [
                        "--report-date", "20260806",
                        "--market-date", "20260805",
                        "--signal-db", str(signal_db),
                        "--history-db", str(Path(tmpdir) / "history.db"),
                    ]
                )

        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
