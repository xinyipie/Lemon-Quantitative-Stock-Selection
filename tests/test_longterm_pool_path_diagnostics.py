import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from longterm_pool_path_diagnostics import (
    build_report,
    classify_paths,
    factor_group_diff,
    normalize_pool_paths,
    path_summary,
)


class LongtermPoolPathDiagnosticsTest(unittest.TestCase):
    def make_frame(self):
        return pd.DataFrame(
            [
                {
                    "stage": "sample",
                    "select_date": "20250102",
                    "ts_code": "smooth.SZ",
                    "name": "smooth",
                    "ret_80d": 22.0,
                    "mfe_80d": 32.0,
                    "mae_80d": -5.0,
                    "roe": 12.0,
                    "turnover": 2.0,
                    "price_vs_ma60": 6.0,
                    "industry_rs": 8.0,
                },
                {
                    "stage": "sample",
                    "select_date": "20250102",
                    "ts_code": "giveback.SZ",
                    "name": "giveback",
                    "ret_80d": -3.0,
                    "mfe_80d": 28.0,
                    "mae_80d": -7.0,
                    "roe": 11.0,
                    "turnover": 3.0,
                    "price_vs_ma60": 8.0,
                    "industry_rs": 10.0,
                },
                {
                    "stage": "sample",
                    "select_date": "20250102",
                    "ts_code": "early.SZ",
                    "name": "early",
                    "ret_80d": 12.0,
                    "mfe_80d": 25.0,
                    "mae_80d": -18.0,
                    "roe": 9.0,
                    "turnover": 4.0,
                    "price_vs_ma60": 12.0,
                    "industry_rs": 7.0,
                },
                {
                    "stage": "sample",
                    "select_date": "20250102",
                    "ts_code": "bad.SZ",
                    "name": "bad",
                    "ret_80d": -15.0,
                    "mfe_80d": 4.0,
                    "mae_80d": -16.0,
                    "roe": 7.0,
                    "turnover": 8.0,
                    "price_vs_ma60": 18.0,
                    "industry_rs": 3.0,
                },
            ]
        )

    def test_classify_paths_splits_selection_and_exit_problems(self):
        labeled = classify_paths(normalize_pool_paths(self.make_frame()), horizon=80)
        groups = dict(zip(labeled["ts_code"], labeled["path_group"]))

        self.assertEqual(groups["smooth.SZ"], "smooth_winner")
        self.assertEqual(groups["giveback.SZ"], "profit_giveback")
        self.assertEqual(groups["early.SZ"], "early_entry")
        self.assertEqual(groups["bad.SZ"], "bad_selection")

    def test_path_summary_reports_counts_by_stage_and_group(self):
        labeled = classify_paths(normalize_pool_paths(self.make_frame()), horizon=80)
        summary = path_summary(labeled)

        self.assertEqual(int(summary["count"].sum()), 4)
        self.assertIn("profit_giveback", set(summary["path_group"].astype(str)))

    def test_factor_group_diff_compares_bad_selection_with_smooth_winner(self):
        labeled = classify_paths(normalize_pool_paths(self.make_frame()), horizon=80)
        diff = factor_group_diff(labeled)

        price = diff[diff["factor"] == "price_vs_ma60"].iloc[0]

        self.assertGreater(price["bad_selection_avg"], price["smooth_winner_avg"])
        self.assertIn("bad_minus_smooth", diff.columns)

    def test_build_report_contains_decision_sections(self):
        labeled = classify_paths(normalize_pool_paths(self.make_frame()), horizon=80)
        report = build_report(labeled, horizon=80, title="path test")

        self.assertIn("# path test", report)
        self.assertIn("先看结论", report)
        self.assertIn("路径质量分组", report)
        self.assertIn("下一步判断", report)

    def test_load_pool_paths_skips_empty_csv_file(self):
        from longterm_pool_path_diagnostics import load_pool_paths

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.csv"
            path.write_text("", encoding="utf-8")

            df = load_pool_paths(path, label="empty")

        self.assertTrue(df.empty)


if __name__ == "__main__":
    unittest.main()
