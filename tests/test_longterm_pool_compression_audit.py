import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from longterm_pool_compression_audit import (
    add_compression_features,
    build_report,
    compress_pool,
    compress_snapshot_pool,
    summarize_compressed_pool,
)


class LongtermPoolCompressionAuditTest(unittest.TestCase):
    def make_frame(self):
        rows = []
        specs = [
            ("20250102", "a.SZ", "A", "电气", 88, 9, 8, 8, 20),
            ("20250102", "b.SZ", "B", "电气", 95, 4, 15, 5, -5),
            ("20250102", "c.SZ", "C", "元器件", 84, 11, 10, 4, 30),
            ("20250103", "a.SZ", "A", "电气", 90, 10, 9, 7, 18),
            ("20250103", "d.SZ", "D", "化工", 82, 7, 12, 3, 12),
            ("20250103", "e.SZ", "E", "元器件", 81, 6, 9, 2, -8),
            ("20250106", "f.SZ", "F", "汽车", 89, 12, 7, 4, 22),
            ("20250106", "g.SZ", "G", "汽车", 87, 13, 8, 5, 16),
        ]
        for select_date, code, name, industry, score, rs, pma, turnover, ret80 in specs:
            rows.append(
                {
                    "select_date": select_date,
                    "ts_code": code,
                    "name": name,
                    "industry": industry,
                    "pool_rank_score": score,
                    "quality_rank_score": score,
                    "industry_rs": rs,
                    "price_vs_ma60": pma,
                    "drawdown_from_high": 10,
                    "turnover": turnover,
                    "pb": 2.5,
                    "ret_10d": ret80 / 8,
                    "ret_40d": ret80 / 2,
                    "ret_80d": ret80,
                    "outperform_80d": ret80 > 0,
                }
            )
        return pd.DataFrame(rows)

    def test_add_compression_features_rewards_repeat_and_reasonable_setup(self):
        featured = add_compression_features(self.make_frame(), lookback_days=5)
        day2_a = featured[(featured["select_date"] == "20250103") & (featured["ts_code"] == "a.SZ")].iloc[0]
        day1_b = featured[(featured["select_date"] == "20250102") & (featured["ts_code"] == "b.SZ")].iloc[0]

        self.assertEqual(day2_a["recent_appearances"], 2)
        self.assertGreater(day2_a["compression_score"], day1_b["compression_score"])

    def test_compress_pool_limits_daily_active_and_industry(self):
        compressed = compress_pool(
            self.make_frame(),
            max_active=3,
            max_new_per_day=2,
            max_industry_active=1,
            hold_days=80,
        )

        self.assertLessEqual(compressed.groupby("select_date").size().max(), 2)
        self.assertLessEqual(len(compressed), 3)
        self.assertLessEqual(compressed["industry"].value_counts().max(), 1)
        self.assertFalse(compressed["ts_code"].duplicated().any())

    def test_compress_snapshot_pool_rebuilds_each_day_without_locking_old_names(self):
        compressed = compress_snapshot_pool(
            self.make_frame(),
            max_active=2,
            max_industry_active=1,
        )

        by_date = compressed.groupby("select_date")
        self.assertLessEqual(by_date.size().max(), 2)
        self.assertTrue({"f.SZ", "g.SZ"} & set(compressed["ts_code"]))
        self.assertGreater(len(compressed), 3)
        for _, group in compressed.groupby("select_date"):
            self.assertLessEqual(group["industry"].value_counts().max(), 1)

    def test_summarize_compressed_pool_reports_forward_quality(self):
        compressed = compress_pool(self.make_frame(), max_active=3, max_new_per_day=2, max_industry_active=1)
        summary = summarize_compressed_pool(compressed, horizons=[10, 40, 80])

        row = summary[summary["horizon"] == "80d"].iloc[0]
        self.assertEqual(row["count"], len(compressed))
        self.assertIn("avg_ret", summary.columns)
        self.assertIn("win_rate", summary.columns)

    def test_build_report_contains_core_sections(self):
        compressed = compress_pool(self.make_frame(), max_active=3, max_new_per_day=2, max_industry_active=1)
        report = build_report(compressed, self.make_frame(), title="compression test")

        self.assertIn("# compression test", report)
        self.assertIn("先看结论", report)
        self.assertIn("压缩后表现", report)
        self.assertIn("推荐明细", report)


if __name__ == "__main__":
    unittest.main()
