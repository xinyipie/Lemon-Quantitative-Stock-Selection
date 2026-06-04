import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from supplement_longterm_data import merge_daily_basic_cache, merge_static_cache, quarter_periods


class SupplementLongtermDataTest(unittest.TestCase):
    def test_quarter_periods_returns_all_quarters(self):
        self.assertEqual(
            quarter_periods(2024, 2025),
            [
                "20240331",
                "20240630",
                "20240930",
                "20241231",
                "20250331",
                "20250630",
                "20250930",
                "20251231",
            ],
        )

    def test_merge_static_cache_deduplicates_by_report_key(self):
        old = pd.DataFrame(
            [{"ts_code": "000001.SZ", "end_date": "20241231", "ann_date": "20250330", "roe": 10}]
        )
        new = pd.DataFrame(
            [{"ts_code": "000001.SZ", "end_date": "20241231", "ann_date": "20250330", "roe": 12}]
        )

        merged = merge_static_cache(old, new, keys=["ts_code", "end_date", "ann_date"])

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged.iloc[0]["ts_code"], "000001.SZ")
        self.assertEqual(float(merged.iloc[0]["roe"]), 12.0)

    def test_merge_daily_basic_cache_preserves_old_and_adds_valuation(self):
        old = pd.DataFrame(
            [{"ts_code": "000001.SZ", "turnover_rate": 2.5, "volume_ratio": 1.2}]
        )
        new = pd.DataFrame(
            [{"ts_code": "000001.SZ", "turnover_rate": 2.8, "pe": 8.5, "pb": 0.9}]
        )

        merged = merge_daily_basic_cache(old, new)

        row = merged.iloc[0]
        self.assertEqual(float(row["turnover_rate"]), 2.8)
        self.assertEqual(float(row["volume_ratio"]), 1.2)
        self.assertEqual(float(row["pe"]), 8.5)
        self.assertEqual(float(row["pb"]), 0.9)


if __name__ == "__main__":
    unittest.main()
