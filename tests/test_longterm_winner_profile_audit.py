import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from longterm_winner_profile_audit import (
    build_report,
    classify_samples,
    factor_difference_table,
    segment_summary,
)


class LongtermWinnerProfileAuditTest(unittest.TestCase):
    def make_samples(self):
        return pd.DataFrame(
            [
                {
                    "ts_code": "winner.SZ",
                    "name": "赢家",
                    "industry": "机器人",
                    "pool_type": "强趋势行业",
                    "ret_80d": 32.0,
                    "excess_ret_80d": 12.0,
                    "outperform_80d": True,
                    "industry_rs": 12.0,
                    "drawdown_from_high": 10.0,
                    "price_vs_ma60": 8.0,
                    "turnover": 3.0,
                },
                {
                    "ts_code": "loser.SZ",
                    "name": "输家",
                    "industry": "医药",
                    "pool_type": "稳健质量",
                    "ret_80d": -18.0,
                    "excess_ret_80d": -20.0,
                    "outperform_80d": False,
                    "industry_rs": 1.0,
                    "drawdown_from_high": 24.0,
                    "price_vs_ma60": 14.0,
                    "turnover": 7.0,
                },
                {
                    "ts_code": "middle.SZ",
                    "name": "普通",
                    "industry": "电力",
                    "pool_type": "稳健质量",
                    "ret_80d": 4.0,
                    "excess_ret_80d": -1.0,
                    "outperform_80d": False,
                    "industry_rs": 6.0,
                    "drawdown_from_high": 14.0,
                    "price_vs_ma60": 9.0,
                    "turnover": 4.0,
                },
            ]
        )

    def test_classify_samples_marks_winners_and_losers(self):
        result = classify_samples(self.make_samples(), 80, winner_ret=15, loser_ret=-10)

        by_code = result.set_index("ts_code")

        self.assertEqual(by_code.loc["winner.SZ", "sample_group"], "赢家")
        self.assertEqual(by_code.loc["loser.SZ", "sample_group"], "输家")
        self.assertEqual(by_code.loc["middle.SZ", "sample_group"], "中间")

    def test_factor_difference_table_compares_winners_and_losers(self):
        classified = classify_samples(self.make_samples(), 80, winner_ret=15, loser_ret=-10)
        diff = factor_difference_table(classified, ["industry_rs", "drawdown_from_high", "turnover"])

        by_factor = diff.set_index("factor")

        self.assertAlmostEqual(by_factor.loc["industry_rs", "winner_mean"], 12.0)
        self.assertAlmostEqual(by_factor.loc["industry_rs", "loser_mean"], 1.0)
        self.assertAlmostEqual(by_factor.loc["industry_rs", "diff"], 11.0)
        self.assertAlmostEqual(by_factor.loc["drawdown_from_high", "diff"], -14.0)

    def test_segment_summary_groups_by_pool_type(self):
        classified = classify_samples(self.make_samples(), 80, winner_ret=15, loser_ret=-10)
        summary = segment_summary(classified, "pool_type", 80)

        trend = summary[summary["pool_type"] == "强趋势行业"].iloc[0]

        self.assertEqual(trend["count"], 1)
        self.assertEqual(trend["winner_count"], 1)
        self.assertAlmostEqual(trend["avg_ret_80d"], 32.0)

    def test_build_report_includes_core_sections(self):
        classified = classify_samples(self.make_samples(), 80, winner_ret=15, loser_ret=-10)
        report = build_report(classified, 80)

        self.assertIn("长线赢家画像审计", report)
        self.assertIn("赢家", report)
        self.assertIn("因子差异", report)


if __name__ == "__main__":
    unittest.main()
