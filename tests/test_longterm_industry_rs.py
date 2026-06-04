import os
import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("LEMON_SKIP_TUSHARE_INIT", "1")

import main


class FakePro:
    def trade_cal(self, exchange="", start_date="", end_date="", is_open=1, fields=""):
        return pd.DataFrame(
            {
                "cal_date": ["20250101", "20250120"],
                "is_open": [1, 1],
            }
        )

    def daily(self, ts_code="", trade_date="", start_date="", end_date="", fields=""):
        return pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "trade_date": "20250101", "close": 10.0},
                {"ts_code": "000002.SZ", "trade_date": "20250101", "close": 20.0},
                {"ts_code": "000003.SZ", "trade_date": "20250101", "close": 10.0},
                {"ts_code": "000004.SZ", "trade_date": "20250101", "close": 10.0},
                {"ts_code": "000001.SZ", "trade_date": "20250120", "close": 12.0},
                {"ts_code": "000002.SZ", "trade_date": "20250120", "close": 25.0},
                {"ts_code": "000003.SZ", "trade_date": "20250120", "close": 9.0},
                {"ts_code": "000004.SZ", "trade_date": "20250120", "close": 9.5},
            ]
        )

    def index_daily(self, ts_code="", trade_date="", start_date="", end_date="", fields=""):
        return pd.DataFrame(
            [
                {"ts_code": "000300.SH", "trade_date": "20250101", "close": 100.0},
                {"ts_code": "000300.SH", "trade_date": "20250120", "close": 110.0},
            ]
        )


class LongtermIndustryRsTest(unittest.TestCase):
    def test_stock_industry_rs_uses_matching_stock_industry_names(self):
        old_pro = main.pro
        main.set_pro(FakePro())
        try:
            stocks = pd.DataFrame(
                [
                    {"code": "000001", "industry": "强行业"},
                    {"code": "000002", "industry": "强行业"},
                    {"code": "000003", "industry": "弱行业"},
                    {"code": "000004", "industry": "弱行业"},
                ]
            )

            result = main.get_stock_industry_rs_scores(stocks, "20250120", lookback_days=20, min_members=2)
        finally:
            main.pro = old_pro

        self.assertGreater(result["强行业"], 10)
        self.assertLess(result["弱行业"], -10)


if __name__ == "__main__":
    unittest.main()
