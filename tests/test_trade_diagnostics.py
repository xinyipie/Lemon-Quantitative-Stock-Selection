import unittest
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trade_diagnostics import (
    build_markdown_report,
    compare_winners_losers,
    group_summary,
    load_trades_frame,
    summarize_overall,
    top_high_score_losers,
)


class TradeDiagnosticsTest(unittest.TestCase):
    def make_frame(self):
        return pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "name": "Alpha",
                    "profit_after_fee": 6.0,
                    "original_score": 82,
                    "factor_pattern": 70,
                    "factor_inflow": 66,
                    "exit_reason": "take_profit",
                    "market_style": "bull",
                    "macro_mode": "normal",
                    "hold_days": 4,
                },
                {
                    "ts_code": "000002.SZ",
                    "name": "Beta",
                    "profit_after_fee": -3.0,
                    "original_score": 91,
                    "factor_pattern": 45,
                    "factor_inflow": 20,
                    "exit_reason": "stop_loss",
                    "market_style": "weak",
                    "macro_mode": "normal",
                    "hold_days": 2,
                },
                {
                    "ts_code": "000003.SZ",
                    "name": "Gamma",
                    "profit_after_fee": 2.0,
                    "original_score": 55,
                    "factor_pattern": 65,
                    "factor_inflow": 38,
                    "exit_reason": "time_exit",
                    "market_style": "weak",
                    "macro_mode": "risk_off",
                    "hold_days": 7,
                },
                {
                    "ts_code": "000004.SZ",
                    "name": "Delta",
                    "profit_after_fee": -1.0,
                    "original_score": 74,
                    "factor_pattern": 40,
                    "factor_inflow": 30,
                    "exit_reason": "stop_loss",
                    "market_style": "weak",
                    "macro_mode": "risk_off",
                    "hold_days": 5,
                },
            ]
        )

    def test_summarize_overall_uses_fee_adjusted_return(self):
        summary = summarize_overall(self.make_frame())

        self.assertEqual(summary["trade_count"], 4)
        self.assertEqual(summary["win_count"], 2)
        self.assertAlmostEqual(summary["win_rate_pct"], 50.0)
        self.assertAlmostEqual(summary["total_return_pct"], 4.0)
        self.assertAlmostEqual(summary["avg_win_pct"], 4.0)
        self.assertAlmostEqual(summary["avg_loss_pct"], -2.0)
        self.assertAlmostEqual(summary["payoff_ratio"], 2.0)

    def test_compare_winners_losers_highlights_factor_gap(self):
        result = compare_winners_losers(self.make_frame(), ["factor_pattern", "factor_inflow"])

        pattern = result[result["field"] == "factor_pattern"].iloc[0]
        self.assertAlmostEqual(pattern["winner_avg"], 67.5)
        self.assertAlmostEqual(pattern["loser_avg"], 42.5)
        self.assertAlmostEqual(pattern["diff"], 25.0)

    def test_group_summary_counts_and_win_rate(self):
        result = group_summary(self.make_frame(), "market_style")

        weak = result[result["group"] == "weak"].iloc[0]
        self.assertEqual(weak["trades"], 3)
        self.assertAlmostEqual(weak["win_rate_pct"], 33.33)
        self.assertAlmostEqual(weak["avg_return_pct"], -0.67)

    def test_top_high_score_losers_returns_bad_high_score_cases(self):
        result = top_high_score_losers(self.make_frame(), top_n=1)

        self.assertEqual(result.iloc[0]["ts_code"], "000002.SZ")
        self.assertEqual(result.iloc[0]["original_score"], 91)

    def test_load_trades_frame_adds_buckets(self):
        result = load_trades_frame(self.make_frame())

        self.assertIn("score_bucket", result.columns)
        self.assertIn("hold_bucket", result.columns)
        self.assertEqual(result.loc[0, "hold_bucket"], "4-5d")

    def test_build_markdown_report_contains_main_sections(self):
        report = build_markdown_report(self.make_frame(), source="sample.csv", top_n=2)

        self.assertIn("# Trade Diagnostics", report)
        self.assertIn("## Overall", report)
        self.assertIn("## Winners vs Losers", report)
        self.assertIn("## High Score Losers", report)
        self.assertIn("sample.csv", report)


if __name__ == "__main__":
    unittest.main()
