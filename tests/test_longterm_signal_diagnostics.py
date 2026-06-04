import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from longterm_signal_diagnostics import (
    add_candidate_rank,
    build_markdown_report,
    compare_topn_vs_missed,
    find_high_mfe_losers,
    find_missed_good_candidates,
    summarize_entry_buckets,
)


class LongtermSignalDiagnosticsTest(unittest.TestCase):
    def make_candidates(self):
        return pd.DataFrame(
            [
                {
                    "select_date": "20250102",
                    "ts_code": "top_good.SZ",
                    "score": 90,
                    "longterm_score": 90,
                    "mfe_pct": 12,
                    "mae_pct": -5,
                    "window_end_pct": 6,
                    "price_vs_ma60": 5,
                    "drawdown_from_high": 8,
                    "turnover": 2,
                    "ma20_slope": 1.2,
                    "score_entry": 70,
                },
                {
                    "select_date": "20250102",
                    "ts_code": "top_bad.SZ",
                    "score": 85,
                    "longterm_score": 85,
                    "mfe_pct": 4,
                    "mae_pct": -13,
                    "window_end_pct": -8,
                    "price_vs_ma60": 18,
                    "drawdown_from_high": 3,
                    "turnover": 7,
                    "ma20_slope": 0.3,
                    "score_entry": 40,
                },
                {
                    "select_date": "20250102",
                    "ts_code": "top_mid.SZ",
                    "score": 80,
                    "longterm_score": 80,
                    "mfe_pct": 6,
                    "mae_pct": -7,
                    "window_end_pct": 1,
                    "price_vs_ma60": 7,
                    "drawdown_from_high": 10,
                    "turnover": 3,
                    "ma20_slope": 0.8,
                    "score_entry": 60,
                },
                {
                    "select_date": "20250102",
                    "ts_code": "missed_good.SZ",
                    "score": 70,
                    "longterm_score": 70,
                    "mfe_pct": 20,
                    "mae_pct": -4,
                    "window_end_pct": 12,
                    "price_vs_ma60": 4,
                    "drawdown_from_high": 12,
                    "turnover": 2,
                    "ma20_slope": 1.6,
                    "score_entry": 82,
                },
            ]
        )

    def make_trades(self):
        return pd.DataFrame(
            [
                {
                    "select_date": "20250102",
                    "ts_code": "top_bad.SZ",
                    "profit_after_fee": -8,
                    "exit_reason": "stop_loss",
                    "mfe_pct": 18,
                    "mae_pct": -13,
                    "window_end_pct": 9,
                    "price_vs_ma60": 18,
                    "drawdown_from_high": 3,
                    "turnover": 7,
                    "ma20_slope": 0.3,
                    "score_entry": 40,
                }
            ]
        )

    def test_find_high_mfe_losers_flags_trades_that_had_large_upside_but_lost(self):
        losers = find_high_mfe_losers(self.make_trades(), mfe_threshold=10)

        self.assertEqual(losers.iloc[0]["ts_code"], "top_bad.SZ")
        self.assertEqual(losers.iloc[0]["exit_reason"], "stop_loss")

    def test_find_missed_good_candidates_compares_rank_4_10_to_daily_top3(self):
        ranked = add_candidate_rank(self.make_candidates(), top_n=3)
        missed = find_missed_good_candidates(ranked, top_n=3, compare_max_rank=10)

        self.assertEqual(list(missed["ts_code"]), ["missed_good.SZ"])

    def test_compare_topn_vs_missed_reports_factor_differences(self):
        ranked = add_candidate_rank(self.make_candidates(), top_n=3)
        missed = find_missed_good_candidates(ranked, top_n=3)

        diff = compare_topn_vs_missed(ranked, missed)

        self.assertIn("score_entry", set(diff["factor"]))
        entry = diff[diff["factor"] == "score_entry"].iloc[0]
        self.assertGreater(entry["missed_avg"], entry["topn_avg"])

    def test_summarize_entry_buckets_groups_risk_features(self):
        summary = summarize_entry_buckets(self.make_candidates(), "price_vs_ma60", bins=[-99, 6, 12, 99])

        self.assertIn("<=6", set(summary["bucket"]))
        self.assertIn("avg_mfe_pct", summary.columns)

    def test_build_report_contains_decision_sections(self):
        report = build_markdown_report(
            candidates=self.make_candidates(),
            trades=self.make_trades(),
            source="sample",
            title="波段信号诊断测试",
        )

        self.assertIn("# 波段信号诊断测试", report)
        self.assertIn("高MFE但最终亏损", report)
        self.assertIn("Top3 vs 后排好票", report)
        self.assertIn("入场风险分桶", report)
        self.assertIn("missed_good.SZ", report)


if __name__ == "__main__":
    unittest.main()
