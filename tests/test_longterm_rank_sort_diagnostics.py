import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from longterm_rank_sort_diagnostics import (
    add_rank_layers,
    build_report,
    factor_layer_diff,
    score_layer_summary,
)


class LongtermRankSortDiagnosticsTest(unittest.TestCase):
    def make_frame(self):
        rows = []
        for i, score in enumerate([95, 90, 82, 78, 70, 62, 55, 48, 40, 35], start=1):
            rows.append(
                {
                    "stage": "sample",
                    "select_date": "20250102",
                    "ts_code": f"{i:06d}.SZ",
                    "name": f"stock{i}",
                    "pool_rank_score": score,
                    "quality_rank_score": score,
                    "ret_80d": [-8, -5, 1, 3, 5, 8, 12, 18, 25, 30][i - 1],
                    "mfe_80d": [5, 8, 10, 12, 14, 18, 22, 28, 35, 40][i - 1],
                    "mae_80d": [-15, -12, -8, -7, -6, -5, -4, -3, -2, -2][i - 1],
                    "pb": [5.0, 4.5, 3.8, 3.5, 3.0, 2.6, 2.2, 1.8, 1.5, 1.2][i - 1],
                    "turnover": [9, 8, 7, 6, 5, 4, 3, 2.5, 2, 1.8][i - 1],
                    "industry_rs": [3, 4, 5, 6, 7, 8, 9, 10, 12, 14][i - 1],
                }
            )
        return pd.DataFrame(rows)

    def test_add_rank_layers_marks_daily_top_and_bottom(self):
        layered = add_rank_layers(self.make_frame(), score_col="pool_rank_score")

        by_code = layered.set_index("ts_code")
        self.assertEqual(by_code.loc["000001.SZ", "rank_layer"], "Top10%")
        self.assertEqual(by_code.loc["000009.SZ", "rank_layer"], "Bottom20%")
        self.assertEqual(by_code.loc["000010.SZ", "rank_layer"], "Bottom20%")

    def test_score_layer_summary_exposes_inverted_returns(self):
        summary = score_layer_summary(add_rank_layers(self.make_frame()), horizon=80)

        top = summary[summary["rank_layer"] == "Top10%"].iloc[0]
        bottom = summary[summary["rank_layer"] == "Bottom20%"].iloc[0]
        self.assertLess(top["avg_ret"], bottom["avg_ret"])

    def test_factor_layer_diff_compares_top_and_bottom_factors(self):
        diff = factor_layer_diff(add_rank_layers(self.make_frame()))

        pb = diff[diff["factor"] == "pb"].iloc[0]
        industry = diff[diff["factor"] == "industry_rs"].iloc[0]
        self.assertGreater(pb["top10_avg"], pb["bottom20_avg"])
        self.assertLess(industry["top10_avg"], industry["bottom20_avg"])

    def test_build_report_contains_diagnosis_sections(self):
        report = build_report(add_rank_layers(self.make_frame()), horizon=80, title="rank test")

        self.assertIn("# rank test", report)
        self.assertIn("先看结论", report)
        self.assertIn("排序有效性", report)
        self.assertIn("高分低收益", report)
        self.assertIn("低分高收益", report)


if __name__ == "__main__":
    unittest.main()
