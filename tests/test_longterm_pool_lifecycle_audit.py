import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from longterm_pool_lifecycle_audit import (
    active_pool_timeline,
    first_entry_table,
    lifecycle_entry_table,
    summarize_first_entries,
)


class LongtermPoolLifecycleAuditTest(unittest.TestCase):
    def make_quality(self):
        return pd.DataFrame(
            [
                {
                    "select_date": "20250102",
                    "ts_code": "good.SZ",
                    "name": "good",
                    "industry": "AI",
                    "longterm_score": 70,
                    "ret_10d": 5.0,
                    "ret_40d": 20.0,
                    "ret_80d": 40.0,
                    "outperform_80d": True,
                },
                {
                    "select_date": "20250106",
                    "ts_code": "good.SZ",
                    "name": "good",
                    "industry": "AI",
                    "longterm_score": 72,
                    "ret_10d": 4.0,
                    "ret_40d": 18.0,
                    "ret_80d": 35.0,
                    "outperform_80d": True,
                },
                {
                    "select_date": "20250103",
                    "ts_code": "weak.SZ",
                    "name": "weak",
                    "industry": "医药",
                    "longterm_score": 65,
                    "ret_10d": -3.0,
                    "ret_40d": -8.0,
                    "ret_80d": -10.0,
                    "outperform_80d": False,
                },
                {
                    "select_date": "20250110",
                    "ts_code": "late.SZ",
                    "name": "late",
                    "industry": "电气",
                    "longterm_score": 68,
                    "ret_10d": 2.0,
                    "ret_40d": 6.0,
                    "ret_80d": 12.0,
                    "outperform_80d": True,
                },
            ]
        )

    def test_first_entry_table_keeps_only_first_recommendation_per_stock(self):
        first = first_entry_table(self.make_quality())

        self.assertEqual(first["ts_code"].tolist(), ["good.SZ", "weak.SZ", "late.SZ"])
        self.assertEqual(first.loc[first["ts_code"] == "good.SZ", "appearances"].iloc[0], 2)
        self.assertEqual(first.loc[first["ts_code"] == "good.SZ", "first_select_date"].iloc[0], "20250102")

    def test_first_entry_table_prefers_quality_rank_score_for_same_day_records(self):
        data = pd.DataFrame(
            [
                {
                    "select_date": "20250102",
                    "ts_code": "same.SZ",
                    "name": "same",
                    "industry": "AI",
                    "longterm_score": 90,
                    "quality_rank_score": 40,
                    "risk_flags": "位置偏高",
                    "ret_80d": -5.0,
                },
                {
                    "select_date": "20250102",
                    "ts_code": "same.SZ",
                    "name": "same",
                    "industry": "AI",
                    "longterm_score": 70,
                    "quality_rank_score": 85,
                    "risk_flags": "无",
                    "ret_80d": 15.0,
                },
            ]
        )

        first = first_entry_table(data)

        self.assertEqual(first.iloc[0]["quality_rank_score"], 85)
        self.assertEqual(first.iloc[0]["risk_flags"], "无")

    def test_summarize_first_entries_uses_first_recommendation_quality(self):
        first = first_entry_table(self.make_quality())
        summary = summarize_first_entries(first, [10, 40, 80])

        ret80 = summary[summary["horizon"] == "80d"].iloc[0]

        self.assertEqual(ret80["new_stocks"], 3)
        self.assertAlmostEqual(ret80["avg_ret"], 14.0)
        self.assertAlmostEqual(ret80["win_rate"], 66.67)
        self.assertAlmostEqual(ret80["outperform_rate"], 66.67)

    def test_active_pool_timeline_counts_recent_recommendations(self):
        first = first_entry_table(self.make_quality())
        timeline = active_pool_timeline(first, hold_days=7)

        by_date = timeline.set_index("date")

        self.assertEqual(by_date.loc["20250102", "active_count"], 1)
        self.assertEqual(by_date.loc["20250103", "active_count"], 2)
        self.assertEqual(by_date.loc["20250110", "active_count"], 2)
        self.assertEqual(by_date["new_count"].sum(), 3)

    def test_lifecycle_entry_table_counts_reentry_after_stock_leaves_pool(self):
        data = pd.DataFrame(
            [
                {
                    "select_date": "20250102",
                    "ts_code": "reentry.SZ",
                    "name": "reentry",
                    "industry": "AI",
                    "pool_rank_score": 80,
                    "ret_80d": 10.0,
                },
                {
                    "select_date": "20250103",
                    "ts_code": "reentry.SZ",
                    "name": "reentry",
                    "industry": "AI",
                    "pool_rank_score": 82,
                    "ret_80d": 8.0,
                },
                {
                    "select_date": "20250106",
                    "ts_code": "other.SZ",
                    "name": "other",
                    "industry": "电气",
                    "pool_rank_score": 75,
                    "ret_80d": 5.0,
                },
                {
                    "select_date": "20250107",
                    "ts_code": "reentry.SZ",
                    "name": "reentry",
                    "industry": "AI",
                    "pool_rank_score": 90,
                    "ret_80d": 30.0,
                },
            ]
        )

        entries = lifecycle_entry_table(data)

        reentries = entries[entries["ts_code"] == "reentry.SZ"].sort_values("first_select_date")
        self.assertEqual(len(reentries), 2)
        self.assertEqual(reentries.iloc[0]["appearances"], 2)
        self.assertEqual(reentries.iloc[0]["first_select_date"], "20250102")
        self.assertEqual(reentries.iloc[0]["last_select_date"], "20250103")
        self.assertEqual(reentries.iloc[1]["appearances"], 1)
        self.assertEqual(reentries.iloc[1]["first_select_date"], "20250107")


if __name__ == "__main__":
    unittest.main()
