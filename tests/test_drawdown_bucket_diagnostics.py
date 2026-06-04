import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from drawdown_bucket_diagnostics import (
    build_markdown_report,
    bucketize_drawdown,
    bucketize_factor_drawdown,
    normalize_trades,
    summarize_bucket,
)


class DrawdownBucketDiagnosticsTest(unittest.TestCase):
    def make_frame(self):
        return pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "profit_after_fee": 5.0,
                    "drawdown_from_high": 2.0,
                    "factor_drawdown": 55,
                    "mfe_pct": 8,
                    "mae_pct": -2,
                    "window_end_pct": 3,
                    "market_style": "weak_momentum",
                },
                {
                    "ts_code": "000002.SZ",
                    "profit_after_fee": -3.0,
                    "drawdown_from_high": 7.0,
                    "factor_drawdown": 82,
                    "mfe_pct": 4,
                    "mae_pct": -6,
                    "window_end_pct": -2,
                    "market_style": "weak_momentum",
                },
                {
                    "ts_code": "000003.SZ",
                    "profit_after_fee": -6.0,
                    "drawdown_from_high": 11.0,
                    "factor_drawdown": 95,
                    "mfe_pct": 2,
                    "mae_pct": -9,
                    "window_end_pct": -5,
                    "market_style": "sideways",
                },
                {
                    "ts_code": "000004.SZ",
                    "profit_after_fee": 4.0,
                    "drawdown_from_high": 4.0,
                    "factor_drawdown": 70,
                    "mfe_pct": 7,
                    "mae_pct": -3,
                    "window_end_pct": 2,
                    "market_style": "sideways",
                },
            ]
        )

    def test_bucketize_drawdown_uses_expected_ranges(self):
        self.assertEqual(bucketize_drawdown(2.5), "0-3%")
        self.assertEqual(bucketize_drawdown(5.0), "3-6%")
        self.assertEqual(bucketize_drawdown(8.0), "6-9%")
        self.assertEqual(bucketize_drawdown(11.0), "9-12%")
        self.assertEqual(bucketize_drawdown(13.0), "12%+")

    def test_bucketize_factor_drawdown_uses_expected_ranges(self):
        self.assertEqual(bucketize_factor_drawdown(55), "<60")
        self.assertEqual(bucketize_factor_drawdown(70), "60-75")
        self.assertEqual(bucketize_factor_drawdown(82), "75-90")
        self.assertEqual(bucketize_factor_drawdown(95), "90+")

    def test_normalize_trades_adds_buckets_and_return_flags(self):
        result = normalize_trades(self.make_frame())

        self.assertIn("drawdown_bucket", result.columns)
        self.assertIn("factor_drawdown_bucket", result.columns)
        self.assertTrue(result.loc[0, "_is_win"])

    def test_summarize_bucket_returns_trade_quality_metrics(self):
        data = normalize_trades(self.make_frame())

        result = summarize_bucket(data, "drawdown_bucket")
        deep = result[result["bucket"] == "9-12%"].iloc[0]

        self.assertEqual(deep["trades"], 1)
        self.assertEqual(deep["win_rate_pct"], 0.0)
        self.assertEqual(deep["avg_return_pct"], -6.0)
        self.assertEqual(deep["avg_mae_pct"], -9.0)

    def test_build_markdown_report_contains_drawdown_sections(self):
        report = build_markdown_report(self.make_frame(), source="sample.csv")

        self.assertIn("# Drawdown Bucket Diagnostics", report)
        self.assertIn("## drawdown_from_high 分桶", report)
        self.assertIn("## factor_drawdown 分桶", report)
        self.assertIn("## 按 market_style 拆分", report)


if __name__ == "__main__":
    unittest.main()
