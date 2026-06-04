import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from winner_loser_factor_diagnostics import (
    build_markdown_report,
    compare_factors_by_label,
    loss_group_summary,
    normalize_trade_frames,
)


class WinnerLoserFactorDiagnosticsTest(unittest.TestCase):
    def make_frames(self):
        v6 = pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "name": "Alpha",
                    "profit_after_fee": 8.0,
                    "factor_pattern": 80,
                    "factor_inflow": 90,
                    "factor_sector": 45,
                    "volume_ratio": 2.0,
                    "market_style": "weak_momentum",
                    "macro_mode": "active",
                    "industry": "软件服务",
                },
                {
                    "ts_code": "000002.SZ",
                    "name": "Beta",
                    "profit_after_fee": -4.0,
                    "factor_pattern": 35,
                    "factor_inflow": 30,
                    "factor_sector": 20,
                    "volume_ratio": 3.4,
                    "market_style": "weak_momentum",
                    "macro_mode": "active",
                    "industry": "软件服务",
                },
            ]
        )
        v9 = pd.DataFrame(
            [
                {
                    "ts_code": "000003.SZ",
                    "name": "Gamma",
                    "profit_after_fee": 5.0,
                    "factor_pattern": 70,
                    "factor_inflow": 75,
                    "factor_sector": 65,
                    "volume_ratio": 2.2,
                    "market_style": "sideways",
                    "macro_mode": "active",
                    "industry": "专用机械",
                },
                {
                    "ts_code": "000004.SZ",
                    "name": "Delta",
                    "profit_after_fee": -6.0,
                    "factor_pattern": 25,
                    "factor_inflow": 20,
                    "factor_sector": 25,
                    "volume_ratio": 3.5,
                    "market_style": "weak_momentum",
                    "macro_mode": "cautious",
                    "industry": "铜",
                },
            ]
        )
        return [("v6", v6), ("v9", v9)]

    def test_normalize_trade_frames_adds_label_and_return_flags(self):
        result = normalize_trade_frames(self.make_frames())

        self.assertEqual(set(result["source_label"]), {"v6", "v9"})
        self.assertIn("_return_pct", result.columns)
        self.assertTrue(result.loc[result["ts_code"] == "000001.SZ", "_is_win"].iloc[0])

    def test_compare_factors_by_label_reports_winner_loser_gaps(self):
        data = normalize_trade_frames(self.make_frames())

        result = compare_factors_by_label(data, ["factor_pattern", "factor_inflow"])
        v6_pattern = result[(result["source_label"] == "v6") & (result["factor"] == "factor_pattern")].iloc[0]

        self.assertEqual(v6_pattern["meaning"], "形态质量")
        self.assertEqual(v6_pattern["winner_avg"], 80.0)
        self.assertEqual(v6_pattern["loser_avg"], 35.0)
        self.assertEqual(v6_pattern["winner_minus_loser"], 45.0)

    def test_loss_group_summary_counts_loss_clusters(self):
        data = normalize_trade_frames(self.make_frames())

        result = loss_group_summary(data, "market_style")
        weak = result[result["market_style"] == "weak_momentum"].iloc[0]

        self.assertEqual(weak["loss_count"], 2)
        self.assertEqual(weak["loss_return_sum"], -10.0)

    def test_build_markdown_report_contains_decision_sections(self):
        data = normalize_trade_frames(self.make_frames())

        report = build_markdown_report(data, source="sample")

        self.assertIn("# Winner Loser Factor Diagnostics", report)
        self.assertIn("## 先看结论", report)
        self.assertIn("## 赚钱票 vs 亏钱票因子差异", report)
        self.assertIn("## 亏损集中度", report)
        self.assertIn("形态质量", report)


if __name__ == "__main__":
    unittest.main()
