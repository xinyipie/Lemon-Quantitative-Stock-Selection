import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from longterm_pool_watchlist_audit import (
    build_watchlist_report,
    promote_watchlist,
)


class LongtermPoolWatchlistAuditTest(unittest.TestCase):
    def make_frame(self):
        rows = [
            {
                "source_label": "sample",
                "stage": "sample",
                "select_date": "20250102",
                "ts_code": "repeat.SZ",
                "name": "repeat",
                "ret_40d": 3.0,
                "mfe_40d": 18.0,
                "mae_40d": -6.0,
                "longterm_score": 61.0,
            },
            {
                "source_label": "sample",
                "stage": "sample",
                "select_date": "20250103",
                "ts_code": "single.SZ",
                "name": "single",
                "ret_40d": -5.0,
                "mfe_40d": 7.0,
                "mae_40d": -13.0,
                "longterm_score": 62.0,
            },
            {
                "source_label": "sample",
                "stage": "sample",
                "select_date": "20250106",
                "ts_code": "repeat.SZ",
                "name": "repeat",
                "ret_40d": 9.0,
                "mfe_40d": 22.0,
                "mae_40d": -5.0,
                "longterm_score": 64.0,
            },
            {
                "source_label": "sample",
                "stage": "sample",
                "select_date": "20250120",
                "ts_code": "late.SZ",
                "name": "late",
                "ret_40d": 11.0,
                "mfe_40d": 21.0,
                "mae_40d": -4.0,
                "longterm_score": 63.0,
            },
            {
                "source_label": "sample",
                "stage": "sample",
                "select_date": "20250121",
                "ts_code": "fill1.SZ",
                "name": "fill1",
                "ret_40d": 1.0,
                "mfe_40d": 5.0,
                "mae_40d": -3.0,
                "longterm_score": 60.0,
            },
            {
                "source_label": "sample",
                "stage": "sample",
                "select_date": "20250122",
                "ts_code": "fill2.SZ",
                "name": "fill2",
                "ret_40d": 1.0,
                "mfe_40d": 5.0,
                "mae_40d": -3.0,
                "longterm_score": 60.0,
            },
            {
                "source_label": "sample",
                "stage": "sample",
                "select_date": "20250123",
                "ts_code": "fill3.SZ",
                "name": "fill3",
                "ret_40d": 1.0,
                "mfe_40d": 5.0,
                "mae_40d": -3.0,
                "longterm_score": 60.0,
            },
            {
                "source_label": "sample",
                "stage": "sample",
                "select_date": "20250220",
                "ts_code": "late.SZ",
                "name": "late",
                "ret_40d": 12.0,
                "mfe_40d": 22.0,
                "mae_40d": -4.0,
                "longterm_score": 65.0,
            },
        ]
        return pd.DataFrame(rows)

    def test_promote_watchlist_requires_repeated_recent_appearance(self):
        promoted = promote_watchlist(self.make_frame(), lookback_scans=3, min_appearances=2)

        self.assertEqual(list(promoted["ts_code"]), ["repeat.SZ"])
        row = promoted.iloc[0]
        self.assertEqual(int(row["watch_appearances"]), 2)
        self.assertEqual(row["first_seen_date"], "20250102")
        self.assertEqual(row["promote_date"], "20250106")

    def test_promote_watchlist_can_use_looser_scan_window(self):
        promoted = promote_watchlist(self.make_frame(), lookback_scans=10, min_appearances=2)

        self.assertEqual(set(promoted["ts_code"]), {"repeat.SZ", "late.SZ"})

    def test_build_watchlist_report_compares_raw_and_promoted_pool(self):
        raw = self.make_frame()
        promoted = promote_watchlist(raw, lookback_scans=3, min_appearances=2)
        report = build_watchlist_report(raw, promoted, horizon=40, title="watch test")

        self.assertIn("# watch test", report)
        self.assertIn("观察池升级审计", report)
        self.assertIn("原始入池样本", report)
        self.assertIn("升级样本", report)
        self.assertIn("repeat.SZ", report)


if __name__ == "__main__":
    unittest.main()
