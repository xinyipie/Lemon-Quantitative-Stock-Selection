import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rule_hit_diagnostics import (
    add_candidate_rank,
    build_markdown_report,
    evaluate_rule,
    summarize_rule_hits,
)


class RuleHitDiagnosticsTest(unittest.TestCase):
    def make_candidates(self):
        return pd.DataFrame(
            [
                {
                    "select_date": 20250102,
                    "ts_code": "risk_top.SZ",
                    "score": 82,
                    "factor_pattern": 48,
                    "factor_drawdown": 92,
                    "factor_sector": 58,
                    "drawdown_from_high": 10.5,
                    "volume_ratio": 3.4,
                    "ret_5d": -4.0,
                },
                {
                    "select_date": 20250102,
                    "ts_code": "quality.SZ",
                    "score": 80,
                    "factor_pattern": 66,
                    "factor_drawdown": 72,
                    "factor_sector": 45,
                    "drawdown_from_high": 4.0,
                    "volume_ratio": 2.0,
                    "ret_5d": 5.0,
                },
                {
                    "select_date": 20250102,
                    "ts_code": "risk_late.SZ",
                    "score": 55,
                    "factor_pattern": 49,
                    "factor_drawdown": 95,
                    "factor_sector": 60,
                    "drawdown_from_high": 11.0,
                    "volume_ratio": 3.8,
                    "ret_5d": -2.0,
                },
            ]
        )

    def make_trades(self):
        return pd.DataFrame(
            [
                {
                    "select_date": 20250102,
                    "ts_code": "risk_top.SZ",
                    "profit_after_fee": -3.0,
                },
                {
                    "select_date": 20250102,
                    "ts_code": "quality.SZ",
                    "profit_after_fee": 4.0,
                },
            ]
        )

    def test_evaluate_rule_marks_high_score_drawdown_risk(self):
        result = evaluate_rule(self.make_candidates(), "high_score_drawdown_risk")

        self.assertEqual(result["_rule_hit"].tolist(), [True, False, False])

    def test_add_candidate_rank_ranks_by_select_date_score(self):
        result = add_candidate_rank(self.make_candidates())

        self.assertEqual(result.loc[result["ts_code"] == "risk_top.SZ", "candidate_rank"].iloc[0], 1)
        self.assertEqual(result.loc[result["ts_code"] == "risk_late.SZ", "candidate_rank"].iloc[0], 3)

    def test_summarize_rule_hits_compares_selected_hit_returns(self):
        candidates = evaluate_rule(add_candidate_rank(self.make_candidates()), "high_score_drawdown_risk")
        summary = summarize_rule_hits(candidates, self.make_trades())

        self.assertEqual(summary["candidate_hit_count"], 1)
        self.assertEqual(summary["selected_hit_count"], 1)
        self.assertAlmostEqual(summary["selected_hit_total_return_pct"], -3.0)
        self.assertAlmostEqual(summary["selected_non_hit_total_return_pct"], 4.0)

    def test_build_markdown_report_explains_top3_impact(self):
        candidates = evaluate_rule(add_candidate_rank(self.make_candidates()), "high_score_drawdown_risk")
        report = build_markdown_report(candidates, self.make_trades(), rule_name="high_score_drawdown_risk")

        self.assertIn("## 先看结论", report)
        self.assertIn("命中实际买入", report)
        self.assertIn("Top3", report)


if __name__ == "__main__":
    unittest.main()
