import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from longterm_loss_path_diagnostics import build_report, compare_path_groups, normalize_trades


class LongtermLossPathDiagnosticsTest(unittest.TestCase):
    def make_frame(self):
        return pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "profit_pct": -10.0,
                    "exit_reason": "stop_loss",
                    "mfe_pct": 3.0,
                    "mae_pct": -18.0,
                    "price_vs_ma60": 22.0,
                    "turnover": 14.0,
                    "industry_rs": 2.0,
                    "longterm_score": 71.0,
                },
                {
                    "ts_code": "000002.SZ",
                    "profit_pct": 18.0,
                    "exit_reason": "trailing_stop",
                    "mfe_pct": 35.0,
                    "mae_pct": -6.0,
                    "price_vs_ma60": 8.0,
                    "turnover": 5.0,
                    "industry_rs": 8.0,
                    "longterm_score": 70.5,
                },
                {
                    "ts_code": "000003.SZ",
                    "profit_pct": 7.0,
                    "exit_reason": "weak_close_exit",
                    "mfe_pct": 20.0,
                    "mae_pct": -5.0,
                    "price_vs_ma60": 10.0,
                    "turnover": 4.0,
                    "industry_rs": 6.0,
                    "longterm_score": 69.0,
                },
                {
                    "ts_code": "000004.SZ",
                    "profit_pct": -6.0,
                    "exit_reason": "time_stop",
                    "mfe_pct": 12.0,
                    "mae_pct": -14.0,
                    "price_vs_ma60": 18.0,
                    "turnover": 9.0,
                    "industry_rs": 3.0,
                    "longterm_score": 72.0,
                },
            ]
        )

    def test_compare_path_groups_separates_stop_loss_from_good_exits(self):
        df = normalize_trades(self.make_frame(), label="sample")
        summary = compare_path_groups(df)

        price_row = summary[summary["factor"] == "price_vs_ma60"].iloc[0]
        turnover_row = summary[summary["factor"] == "turnover"].iloc[0]

        self.assertGreater(price_row["stop_loss_avg"], price_row["good_exit_avg"])
        self.assertGreater(turnover_row["stop_loss_avg"], turnover_row["good_exit_avg"])

    def test_build_report_contains_actionable_sections(self):
        df = normalize_trades(self.make_frame(), label="sample")
        report = build_report(df, title="loss path test")

        self.assertIn("# loss path test", report)
        self.assertIn("先看结论", report)
        self.assertIn("止损票 vs 好出场票", report)
        self.assertIn("v7候选规则", report)
        self.assertIn("price_vs_ma60", report)


if __name__ == "__main__":
    unittest.main()
