import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from risk_combo_diagnostics import (
    build_markdown_report,
    normalize_trades,
    summarize_combo_rules,
)


class RiskComboDiagnosticsTest(unittest.TestCase):
    def make_frame(self):
        return pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "profit_after_fee": -5.0,
                    "factor_sector": 22,
                    "volume_ratio": 3.4,
                    "drawdown_from_high": 10.5,
                    "factor_inflow": 40,
                    "market_style": "weak_momentum",
                    "name": "低板块高量中深回撤",
                },
                {
                    "ts_code": "000002.SZ",
                    "profit_after_fee": 4.0,
                    "factor_sector": 65,
                    "volume_ratio": 2.0,
                    "drawdown_from_high": 4.5,
                    "factor_inflow": 60,
                    "market_style": "weak_momentum",
                    "name": "强板块正常回撤",
                },
                {
                    "ts_code": "000003.SZ",
                    "profit_after_fee": -2.0,
                    "factor_sector": 20,
                    "volume_ratio": 1.6,
                    "drawdown_from_high": 11.0,
                    "factor_inflow": 35,
                    "market_style": "sideways",
                    "name": "低板块中深回撤",
                },
                {
                    "ts_code": "000004.SZ",
                    "profit_after_fee": 3.0,
                    "factor_sector": 28,
                    "volume_ratio": 3.2,
                    "drawdown_from_high": 2.0,
                    "factor_inflow": 55,
                    "market_style": "sideways",
                    "name": "低板块高量浅回撤",
                },
            ]
        )

    def test_normalize_trades_adds_combo_flags(self):
        result = normalize_trades(self.make_frame())

        self.assertTrue(result.loc[0, "low_sector"])
        self.assertTrue(result.loc[0, "high_volume"])
        self.assertTrue(result.loc[0, "mid_deep_drawdown"])
        self.assertTrue(result.loc[0, "low_sector_high_volume_mid_deep_drawdown"])
        self.assertFalse(result.loc[1, "low_sector_high_volume_mid_deep_drawdown"])

    def test_summarize_combo_rules_returns_quality_metrics(self):
        data = normalize_trades(self.make_frame())

        result = summarize_combo_rules(data)
        combo = result[result["rule"] == "low_sector_high_volume_mid_deep_drawdown"].iloc[0]

        self.assertEqual(combo["matched_trades"], 1)
        self.assertEqual(combo["matched_win_rate_pct"], 0.0)
        self.assertEqual(combo["matched_avg_return_pct"], -5.0)
        self.assertEqual(combo["unmatched_avg_return_pct"], 1.67)
        self.assertEqual(combo["avg_return_gap_pct"], -6.67)

    def test_build_markdown_report_contains_combo_sections(self):
        report = build_markdown_report(self.make_frame(), source="sample.csv")

        self.assertIn("# Risk Combo Diagnostics", report)
        self.assertIn("## 组合规则表现", report)
        self.assertIn("low_sector_high_volume_mid_deep_drawdown", report)


if __name__ == "__main__":
    unittest.main()
