import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from longterm_live_pipeline import build_live_watchlists


class LongtermLivePipelineTest(unittest.TestCase):
    def make_pool(self):
        return pd.DataFrame(
            [
                {
                    "code": "000001",
                    "name": "A",
                    "industry": "AI",
                    "longterm_score": 92,
                    "industry_rs": 9,
                    "price_vs_ma60": 8,
                    "drawdown_from_high": 10,
                    "turnover": 3,
                    "pb": 2.5,
                    "close": 10,
                },
                {
                    "code": "000002",
                    "name": "B",
                    "industry": "AI",
                    "longterm_score": 95,
                    "industry_rs": 10,
                    "price_vs_ma60": 9,
                    "drawdown_from_high": 11,
                    "turnover": 3,
                    "pb": 2.5,
                    "close": 11,
                },
                {
                    "code": "000003",
                    "name": "C",
                    "industry": "医药",
                    "longterm_score": 90,
                    "industry_rs": 11,
                    "price_vs_ma60": 7,
                    "drawdown_from_high": 9,
                    "turnover": 2,
                    "pb": 2.0,
                    "close": 12,
                },
                {
                    "code": "000004",
                    "name": "D",
                    "industry": "消费",
                    "longterm_score": 88,
                    "industry_rs": 3,
                    "price_vs_ma60": 20,
                    "drawdown_from_high": 2,
                    "turnover": 9,
                    "pb": 8,
                    "close": 13,
                },
            ]
        )

    def test_build_live_watchlists_limits_snapshot_and_marks_elite(self):
        result = build_live_watchlists(
            self.make_pool(),
            trade_date="20260612",
            max_watch=3,
            max_industry=1,
            elite_min_score=80,
            elite_min_industry_rs=8,
            elite_min_drawdown=7,
            elite_max_drawdown=15,
        )

        watch = result.watchlist
        elite = result.elite

        self.assertLessEqual(len(watch), 3)
        self.assertLessEqual(watch["industry"].value_counts().max(), 1)
        self.assertTrue((watch["pool_type"] == "longterm_watch").all())
        self.assertTrue((elite["pool_type"] == "longterm_elite").all())
        self.assertTrue(set(elite["ts_code"]).issubset(set(watch["ts_code"])))
        elite_codes = set(elite["ts_code"])
        marked_codes = set(watch[watch["elite_alert"] == True]["ts_code"])
        self.assertEqual(marked_codes, elite_codes)
        self.assertNotIn("000004.SZ", elite["ts_code"].tolist())


if __name__ == "__main__":
    unittest.main()
