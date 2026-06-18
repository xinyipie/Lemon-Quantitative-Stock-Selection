import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from longterm_market_winner_profile_audit import (
    build_report,
    classify_market_samples,
    factor_difference_table,
    make_market_samples,
    read_daily_basic_range,
)


class LongtermMarketWinnerProfileAuditTest(unittest.TestCase):
    def make_daily(self):
        dates = ["20250102", "20250103", "20250106", "20250107", "20250108", "20250109"]
        rows = []
        for i, date in enumerate(dates):
            rows.append({"trade_date": date, "ts_code": "winner.SZ", "close": 10 + i * 2, "high": 10.5 + i * 2, "low": 9.8 + i * 2})
            rows.append({"trade_date": date, "ts_code": "loser.SZ", "close": 10 - i, "high": 10.2 - i, "low": 9.5 - i})
            rows.append({"trade_date": date, "ts_code": "flat.SZ", "close": 10 + i * 0.1, "high": 10.3 + i * 0.1, "low": 9.9 + i * 0.1})
            rows.append({"trade_date": date, "ts_code": "000300.SH", "close": 100 + i, "high": 101 + i, "low": 99 + i})
        return pd.DataFrame(rows)

    def make_basic(self):
        return pd.DataFrame(
            [
                {"trade_date": "20250102", "ts_code": "winner.SZ", "turnover_rate": 2.0, "volume_ratio": 0.9, "total_mv": 1000000, "pb": 2.0, "pe_ttm": 20.0},
                {"trade_date": "20250102", "ts_code": "loser.SZ", "turnover_rate": 8.0, "volume_ratio": 2.5, "total_mv": 200000, "pb": 8.0, "pe_ttm": 90.0},
                {"trade_date": "20250102", "ts_code": "flat.SZ", "turnover_rate": 4.0, "volume_ratio": 1.2, "total_mv": 600000, "pb": 3.0, "pe_ttm": 30.0},
            ]
        )

    def test_make_market_samples_calculates_forward_returns_and_snapshot_factors(self):
        samples = make_market_samples(
            self.make_daily(),
            self.make_basic(),
            select_dates=["20250102"],
            horizons=[2],
            benchmark_code="000300.SH",
        )

        by_code = samples.set_index("ts_code")

        self.assertEqual(len(samples), 3)
        self.assertAlmostEqual(by_code.loc["winner.SZ", "ret_2d"], 40.0)
        self.assertAlmostEqual(by_code.loc["loser.SZ", "ret_2d"], -20.0)
        self.assertGreater(by_code.loc["winner.SZ", "excess_ret_2d"], 0)
        self.assertAlmostEqual(by_code.loc["winner.SZ", "turnover"], 2.0)
        self.assertAlmostEqual(by_code.loc["loser.SZ", "pb"], 8.0)

    def test_classify_market_samples_marks_future_winners_and_losers(self):
        samples = make_market_samples(self.make_daily(), self.make_basic(), ["20250102"], [2])
        classified = classify_market_samples(samples, horizon=2, winner_ret=20, winner_excess=0, loser_ret=-10, loser_excess=-10)

        by_code = classified.set_index("ts_code")

        self.assertEqual(by_code.loc["winner.SZ", "sample_group"], "赢家")
        self.assertEqual(by_code.loc["loser.SZ", "sample_group"], "输家")
        self.assertEqual(by_code.loc["flat.SZ", "sample_group"], "中间")

    def test_factor_difference_table_highlights_winner_loser_gaps(self):
        samples = make_market_samples(self.make_daily(), self.make_basic(), ["20250102"], [2])
        classified = classify_market_samples(samples, horizon=2, winner_ret=20, loser_ret=-10)
        diff = factor_difference_table(classified, ["turnover", "volume_ratio", "pb", "total_mv"])

        by_factor = diff.set_index("factor")

        self.assertLess(by_factor.loc["turnover", "diff"], 0)
        self.assertLess(by_factor.loc["pb", "diff"], 0)
        self.assertGreater(by_factor.loc["total_mv", "diff"], 0)

    def test_build_report_contains_market_profile_sections(self):
        samples = make_market_samples(self.make_daily(), self.make_basic(), ["20250102"], [2])
        classified = classify_market_samples(samples, horizon=2, winner_ret=20, loser_ret=-10)
        report = build_report(classified, horizon=2)

        self.assertIn("全市场长线赢家画像审计", report)
        self.assertIn("赢家/输家因子差异", report)
        self.assertIn("赢家样本", report)

    def test_read_daily_basic_range_uses_trade_date_calls(self):
        class FakeProxy:
            def __init__(self):
                self.calls = []

            def daily_basic(self, trade_date="", fields=""):
                self.calls.append((trade_date, fields))
                return pd.DataFrame([{"trade_date": trade_date, "ts_code": "winner.SZ", "turnover_rate": 2.0}])

        proxy = FakeProxy()
        result = read_daily_basic_range(proxy, ["20250102", "20250103"], "ts_code,trade_date,turnover_rate")

        self.assertEqual([call[0] for call in proxy.calls], ["20250102", "20250103"])
        self.assertEqual(len(result), 2)
        self.assertIn("turnover_rate", result.columns)


if __name__ == "__main__":
    unittest.main()
