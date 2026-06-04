import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("LEMON_SKIP_TUSHARE_INIT", "1")

from backtest_v2 import BacktestLongterm


class LongtermPortfolioFrameworkTest(unittest.TestCase):
    def make_backtest(self, max_positions=3):
        bt = BacktestLongterm.__new__(BacktestLongterm)
        bt.max_positions = max_positions
        bt.top_n = 2
        bt.max_hold_days = 60
        bt.longterm_profile = "zscore_v4_1"
        bt._is_offline = True
        return bt

    def test_longterm_filters_new_buys_by_open_slots_and_duplicate_codes(self):
        bt = self.make_backtest(max_positions=3)
        existing_trades = [
            {"ts_code": "000001.SZ", "buy_date": "20250102", "sell_date": "20250110"},
            {"ts_code": "000002.SZ", "buy_date": "20250103", "sell_date": "20250112"},
        ]
        selected_items = [
            {"ts_code": "000001.SZ", "longterm_score": 80},
            {"ts_code": "000003.SZ", "longterm_score": 79},
            {"ts_code": "000004.SZ", "longterm_score": 78},
        ]

        allowed = bt._filter_selected_items_for_portfolio(
            selected_items,
            existing_trades,
            "20250106",
        )

        self.assertEqual([item["ts_code"] for item in allowed], ["000003.SZ"])

    def test_longterm_position_weight_uses_max_positions_not_daily_topn(self):
        bt = self.make_backtest(max_positions=10)

        self.assertEqual(bt._position_weight(), 0.1)

    def test_longterm_selection_returns_full_candidate_pool_for_signal_quality(self):
        bt = self.make_backtest(max_positions=10)
        pool = pd.DataFrame(
            [
                {"code": "000001", "longterm_score": 80, "close": 10, "score_momentum": 70},
                {"code": "000002", "longterm_score": 75, "close": 20, "score_momentum": 60},
                {"code": "000003", "longterm_score": 65, "close": 30, "score_momentum": 50},
            ]
        )
        selection = {
            "trade_date": "20250102",
            "regime": "BULL_TREND",
            "longterm_pool": pool,
        }

        with patch("backtest_v2.stock_main.run_daily_selection", return_value=selection):
            selected, ic_pool = bt._select_stocks_for_date("20250102")

        self.assertEqual([item["ts_code"] for item in selected], ["000001.SZ", "000002.SZ"])
        self.assertEqual([item["ts_code"] for item in ic_pool], ["000001.SZ", "000002.SZ", "000003.SZ"])
        self.assertEqual(ic_pool[0]["score"], 80)
        self.assertEqual(ic_pool[0]["score_momentum"], 70)
        self.assertEqual(ic_pool[0]["factor_profile"], "zscore_v4_1")


if __name__ == "__main__":
    unittest.main()
