import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from longterm_pool_alert_audit import apply_alert_cooldown, build_report, filter_elite_alerts, summarize_alerts


class LongtermPoolAlertAuditTest(unittest.TestCase):
    def make_events(self):
        return pd.DataFrame(
            [
                {
                    "first_select_date": "20250102",
                    "ts_code": "a.SZ",
                    "name": "A",
                    "compression_score": 85,
                    "industry_rs": 9,
                    "drawdown_from_high": 10,
                    "ret_80d": 10,
                    "outperform_80d": True,
                },
                {
                    "first_select_date": "20250120",
                    "ts_code": "a.SZ",
                    "name": "A",
                    "compression_score": 90,
                    "industry_rs": 12,
                    "drawdown_from_high": 9,
                    "ret_80d": -5,
                    "outperform_80d": False,
                },
                {
                    "first_select_date": "20250415",
                    "ts_code": "a.SZ",
                    "name": "A",
                    "compression_score": 92,
                    "industry_rs": 11,
                    "drawdown_from_high": 8,
                    "ret_80d": 20,
                    "outperform_80d": True,
                },
                {
                    "first_select_date": "20250110",
                    "ts_code": "b.SZ",
                    "name": "B",
                    "compression_score": 70,
                    "industry_rs": 9,
                    "drawdown_from_high": 10,
                    "ret_80d": 8,
                    "outperform_80d": True,
                },
            ]
        )

    def test_apply_alert_cooldown_skips_repeated_stock_inside_window(self):
        alerts = apply_alert_cooldown(self.make_events(), cooldown_days=80)

        self.assertEqual(alerts["ts_code"].tolist(), ["a.SZ", "b.SZ", "a.SZ"])
        self.assertEqual(alerts.iloc[0]["alert_type"], "new_alert")
        self.assertEqual(alerts.iloc[2]["alert_type"], "re_alert")

    def test_summarize_alerts_reports_forward_quality(self):
        alerts = apply_alert_cooldown(self.make_events(), cooldown_days=80)
        summary = summarize_alerts(alerts, horizons=[80])

        row = summary.iloc[0]
        self.assertEqual(row["count"], 3)
        self.assertAlmostEqual(row["avg_ret"], 12.67)
        self.assertAlmostEqual(row["win_rate"], 100.0)

    def test_filter_elite_alerts_keeps_only_strong_rs_and_mid_pullback(self):
        alerts = apply_alert_cooldown(self.make_events(), cooldown_days=80)
        elite = filter_elite_alerts(alerts, min_score=80, min_industry_rs=8, min_drawdown=7, max_drawdown=15)

        self.assertEqual(elite["ts_code"].tolist(), ["a.SZ", "a.SZ"])
        self.assertTrue((elite["elite_alert"] == True).all())

    def test_build_report_contains_sections(self):
        alerts = apply_alert_cooldown(self.make_events(), cooldown_days=80)
        report = build_report(alerts, original_events=self.make_events(), title="alert test")

        self.assertIn("# alert test", report)
        self.assertIn("先看结论", report)
        self.assertIn("提醒表现", report)
        self.assertIn("提醒明细", report)


if __name__ == "__main__":
    unittest.main()
