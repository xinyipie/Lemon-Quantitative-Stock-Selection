import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from longterm_candidate_quality_diagnostics import (
    build_report,
    classify_quality,
    compare_quality_groups,
    normalize_candidates,
)


class LongtermCandidateQualityDiagnosticsTest(unittest.TestCase):
    def make_candidates(self):
        return pd.DataFrame(
            [
                {
                    "select_date": "20250102",
                    "ts_code": "smooth.SZ",
                    "longterm_score": 70,
                    "mfe_pct": 25,
                    "mae_pct": -5,
                    "window_end_pct": 8,
                    "price_vs_ma60": 6,
                    "turnover": 4,
                    "industry_rs": 8,
                    "score_entry": 2,
                },
                {
                    "select_date": "20250102",
                    "ts_code": "volatile.SZ",
                    "longterm_score": 72,
                    "mfe_pct": 30,
                    "mae_pct": -18,
                    "window_end_pct": 5,
                    "price_vs_ma60": 18,
                    "turnover": 9,
                    "industry_rs": 10,
                    "score_entry": 1,
                },
                {
                    "select_date": "20250102",
                    "ts_code": "trap.SZ",
                    "longterm_score": 71,
                    "mfe_pct": 4,
                    "mae_pct": -20,
                    "window_end_pct": -12,
                    "price_vs_ma60": 20,
                    "turnover": 12,
                    "industry_rs": 3,
                    "score_entry": 1,
                },
                {
                    "select_date": "20250102",
                    "ts_code": "dead.SZ",
                    "longterm_score": 69,
                    "mfe_pct": 5,
                    "mae_pct": -6,
                    "window_end_pct": -4,
                    "price_vs_ma60": 9,
                    "turnover": 3,
                    "industry_rs": 1,
                    "score_entry": 0,
                },
            ]
        )

    def test_classify_quality_assigns_path_groups(self):
        df = normalize_candidates(self.make_candidates())
        labeled = classify_quality(df)

        groups = dict(zip(labeled["ts_code"], labeled["quality_group"]))

        self.assertEqual(groups["smooth.SZ"], "smooth_winner")
        self.assertEqual(groups["volatile.SZ"], "volatile_winner")
        self.assertEqual(groups["trap.SZ"], "trap")
        self.assertEqual(groups["dead.SZ"], "dead_money")

    def test_normalize_preserves_existing_source_labels(self):
        df = normalize_candidates(self.make_candidates(), label="2025")
        labeled = classify_quality(df)

        self.assertEqual(set(labeled["source_label"]), {"2025"})

    def test_compare_quality_groups_reports_factor_differences(self):
        labeled = classify_quality(normalize_candidates(self.make_candidates()))
        diff = compare_quality_groups(labeled)

        price_row = diff[diff["factor"] == "price_vs_ma60"].iloc[0]

        self.assertGreater(price_row["trap_avg"], price_row["smooth_winner_avg"])
        self.assertIn("trap_minus_smooth", diff.columns)

    def test_build_report_contains_v7_sections(self):
        labeled = classify_quality(normalize_candidates(self.make_candidates()))
        report = build_report(labeled, title="candidate quality test")

        self.assertIn("# candidate quality test", report)
        self.assertIn("先看结论", report)
        self.assertIn("路径质量分组", report)
        self.assertIn("trap vs smooth_winner", report)
        self.assertIn("v7选股质量线索", report)


if __name__ == "__main__":
    unittest.main()
