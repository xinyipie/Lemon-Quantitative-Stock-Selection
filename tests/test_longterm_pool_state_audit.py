import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from longterm_pool_state_audit import build_report, build_state_events, summarize_state_events


class LongtermPoolStateAuditTest(unittest.TestCase):
    def make_candidate_pool(self):
        return pd.DataFrame(
            [
                {"select_date": "20250102", "ts_code": "a.SZ", "name": "A", "industry": "电气"},
                {"select_date": "20250102", "ts_code": "b.SZ", "name": "B", "industry": "元器件"},
                {"select_date": "20250103", "ts_code": "a.SZ", "name": "A", "industry": "电气"},
                {"select_date": "20250103", "ts_code": "b.SZ", "name": "B", "industry": "元器件"},
                {"select_date": "20250103", "ts_code": "c.SZ", "name": "C", "industry": "化工"},
                {"select_date": "20250106", "ts_code": "b.SZ", "name": "B", "industry": "元器件"},
                {"select_date": "20250106", "ts_code": "d.SZ", "name": "D", "industry": "汽车"},
            ]
        )

    def make_snapshot_pool(self):
        return pd.DataFrame(
            [
                {
                    "select_date": "20250102",
                    "ts_code": "a.SZ",
                    "name": "A",
                    "industry": "电气",
                    "compression_score": 90,
                    "ret_80d": 20,
                },
                {
                    "select_date": "20250102",
                    "ts_code": "b.SZ",
                    "name": "B",
                    "industry": "元器件",
                    "compression_score": 80,
                    "ret_80d": 10,
                },
                {
                    "select_date": "20250103",
                    "ts_code": "a.SZ",
                    "name": "A",
                    "industry": "电气",
                    "compression_score": 91,
                    "ret_80d": 18,
                },
                {
                    "select_date": "20250103",
                    "ts_code": "c.SZ",
                    "name": "C",
                    "industry": "化工",
                    "compression_score": 88,
                    "ret_80d": 12,
                },
                {
                    "select_date": "20250106",
                    "ts_code": "d.SZ",
                    "name": "D",
                    "industry": "汽车",
                    "compression_score": 85,
                    "ret_80d": -5,
                },
            ]
        )

    def test_build_state_events_marks_new_continue_downgrade_and_removed(self):
        events = build_state_events(self.make_snapshot_pool(), self.make_candidate_pool())
        states = {(row.select_date, row.ts_code, row.state) for row in events.itertuples()}

        self.assertIn(("20250102", "a.SZ", "new"), states)
        self.assertIn(("20250103", "a.SZ", "continue"), states)
        self.assertIn(("20250103", "b.SZ", "downgraded_watch"), states)
        self.assertIn(("20250106", "a.SZ", "removed"), states)
        self.assertIn(("20250106", "d.SZ", "new"), states)

    def test_summarize_state_events_counts_daily_changes(self):
        events = build_state_events(self.make_snapshot_pool(), self.make_candidate_pool())
        summary = summarize_state_events(events)

        by_date = summary.set_index("select_date")
        self.assertEqual(by_date.loc["20250103", "continue"], 1)
        self.assertEqual(by_date.loc["20250103", "downgraded_watch"], 1)
        self.assertEqual(by_date.loc["20250106", "removed"], 2)

    def test_build_report_contains_user_facing_sections(self):
        events = build_state_events(self.make_snapshot_pool(), self.make_candidate_pool())
        report = build_report(events, title="state test")

        self.assertIn("# state test", report)
        self.assertIn("先看结论", report)
        self.assertIn("每日状态变化", report)
        self.assertIn("当前池状态", report)


if __name__ == "__main__":
    unittest.main()
