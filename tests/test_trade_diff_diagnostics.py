import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trade_diff_diagnostics import build_markdown_report, changed_trade_table, compare_trades, normalize_trades


class TradeDiffDiagnosticsTest(unittest.TestCase):
    def make_base(self):
        return pd.DataFrame(
            [
                {"select_date": 20250102, "ts_code": "keep.SZ", "name": "Keep", "profit_after_fee": 2.0},
                {"select_date": 20250103, "ts_code": "winner.SZ", "name": "Winner", "profit_after_fee": 6.0},
                {"select_date": 20250104, "ts_code": "loser.SZ", "name": "Loser", "profit_after_fee": -4.0},
            ]
        )

    def make_experiment(self):
        return pd.DataFrame(
            [
                {"select_date": 20250102, "ts_code": "keep.SZ", "name": "Keep", "profit_after_fee": 2.0},
                {"select_date": 20250105, "ts_code": "new_bad.SZ", "name": "NewBad", "profit_after_fee": -3.0},
            ]
        )

    def test_normalize_trades_builds_trade_key(self):
        result = normalize_trades(self.make_base())

        self.assertEqual(result.loc[0, "_trade_key"], "20250102|keep.SZ")
        self.assertEqual(result.loc[0, "_return_pct"], 2.0)

    def test_compare_trades_calculates_replacement_delta(self):
        result = compare_trades(self.make_base(), self.make_experiment())
        summary = result["summary"]

        self.assertEqual(summary["common_trades"], 1)
        self.assertEqual(summary["removed_trades"], 2)
        self.assertEqual(summary["added_trades"], 1)
        self.assertAlmostEqual(summary["removed_total_return_pct"], 2.0)
        self.assertAlmostEqual(summary["added_total_return_pct"], -3.0)
        self.assertAlmostEqual(summary["replacement_delta_pct"], -5.0)

    def test_changed_trade_table_orders_removed_winners_first(self):
        result = compare_trades(self.make_base(), self.make_experiment())
        table = changed_trade_table(result["removed"], worst_first=False)

        self.assertEqual(table.iloc[0]["ts_code"], "winner.SZ")

    def test_build_markdown_report_contains_plain_chinese_summary(self):
        report = build_markdown_report(self.make_base(), self.make_experiment(), "base.csv", "experiment.csv")

        self.assertIn("## 先看结论", report)
        self.assertIn("替换收益差", report)
        self.assertIn("实验少买的票", report)
        self.assertIn("experiment.csv", report)


if __name__ == "__main__":
    unittest.main()
