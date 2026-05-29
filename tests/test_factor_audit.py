import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from factor_audit import (
    audit_factors,
    build_markdown_report,
    compare_factor_stability,
    build_stability_report,
    factor_quantile_summary,
    infer_factor_direction,
)


class FactorAuditTest(unittest.TestCase):
    def make_frame(self):
        return pd.DataFrame(
            [
                {"market_style": "sideways", "factor_pattern": 20, "factor_sector": 80, "ret_5d": -4, "ret_10d": -3},
                {"market_style": "sideways", "factor_pattern": 40, "factor_sector": 60, "ret_5d": -1, "ret_10d": -1},
                {"market_style": "sideways", "factor_pattern": 60, "factor_sector": 40, "ret_5d": 2, "ret_10d": 3},
                {"market_style": "sideways", "factor_pattern": 80, "factor_sector": 20, "ret_5d": 5, "ret_10d": 6},
                {"market_style": "weak_momentum", "factor_pattern": 30, "factor_sector": 90, "ret_5d": -3, "ret_10d": -2},
                {"market_style": "weak_momentum", "factor_pattern": 50, "factor_sector": 70, "ret_5d": 0, "ret_10d": 1},
                {"market_style": "weak_momentum", "factor_pattern": 70, "factor_sector": 30, "ret_5d": 3, "ret_10d": 4},
                {"market_style": "weak_momentum", "factor_pattern": 90, "factor_sector": 10, "ret_5d": 6, "ret_10d": 7},
            ]
        )

    def test_audit_factors_returns_ic_and_quantile_spread(self):
        result = audit_factors(self.make_frame(), ["factor_pattern", "factor_sector"], ["ret_5d"])

        pattern = result[result["factor"] == "factor_pattern"].iloc[0]
        self.assertGreater(pattern["ic"], 0.9)
        self.assertGreater(pattern["top_minus_bottom"], 0)
        self.assertEqual(pattern["direction"], "higher_is_better")

    def test_infer_factor_direction_detects_lower_is_better(self):
        result = audit_factors(self.make_frame(), ["factor_sector"], ["ret_5d"])

        self.assertEqual(result.iloc[0]["direction"], "lower_is_better")

    def test_factor_quantile_summary_has_bucket_returns(self):
        result = factor_quantile_summary(self.make_frame(), "factor_pattern", "ret_5d", buckets=4)

        self.assertEqual(len(result), 4)
        self.assertIn("avg_target", result.columns)

    def test_infer_factor_direction_handles_small_values(self):
        self.assertEqual(infer_factor_direction(0.01, 0.2), "flat")

    def test_build_markdown_report_contains_plain_chinese_sections(self):
        report = build_markdown_report(self.make_frame(), source="sample.csv")

        self.assertIn("## 先看结论", report)
        self.assertIn("## 单因子体检", report)
        self.assertIn("形态质量", report)

    def test_compare_factor_stability_marks_consistent_factor(self):
        left = audit_factors(self.make_frame(), ["factor_pattern", "factor_sector"], ["ret_5d"])
        right = audit_factors(self.make_frame(), ["factor_pattern", "factor_sector"], ["ret_5d"])

        result = compare_factor_stability(left, right, left_label="2025", right_label="2026Q1")
        pattern = result[result["factor"] == "factor_pattern"].iloc[0]

        self.assertEqual(pattern["stability"], "consistent")

    def test_build_stability_report_contains_action_column(self):
        left = audit_factors(self.make_frame(), ["factor_pattern", "factor_sector"], ["ret_5d"])
        right = audit_factors(self.make_frame(), ["factor_pattern", "factor_sector"], ["ret_5d"])

        report = build_stability_report(left, right, left_label="2025", right_label="2026Q1")

        self.assertIn("## 稳定性结论", report)
        self.assertIn("action", report)


if __name__ == "__main__":
    unittest.main()
