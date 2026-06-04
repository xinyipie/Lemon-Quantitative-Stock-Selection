import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

os.environ.setdefault("LEMON_SKIP_TUSHARE_INIT", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config

config.LOG_FILE_PATH = os.path.join(tempfile.gettempdir(), "lemon_quant_test.log")

import main


class FakePro:
    def __init__(self):
        self.holdertrade_calls = []

    def share_float(self, **kwargs):
        return pd.DataFrame(columns=["ts_code"])

    def stk_holdertrade(self, **kwargs):
        self.holdertrade_calls.append(kwargs)
        if "start_date" in kwargs or "end_date" in kwargs:
            raise AssertionError("stk_holdertrade should filter by ann_date locally")
        return pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "ann_date": "20260525", "in_de": "DE"},
                {"ts_code": "000002.SZ", "ann_date": "20260525", "in_de": "IN"},
                {"ts_code": "000003.SZ", "ann_date": "20260101", "in_de": "DE"},
            ]
        )


class RestrictedFilterTest(unittest.TestCase):
    def test_holder_trade_filters_ann_date_locally(self):
        fake_pro = FakePro()

        with patch.object(main, "pro", fake_pro):
            safe = main.filter_restricted_stocks(
                ["000001", "000002", "000003"],
                "20260603",
            )

        self.assertEqual(safe, ["000002", "000003"])
        self.assertEqual(len(fake_pro.holdertrade_calls), 3)


class LongtermPoolResilienceTest(unittest.TestCase):
    def test_longterm_pool_skips_none_ma_entries(self):
        stocks = pd.DataFrame(
            [
                {"code": "000001", "name": "平安银行", "industry": "银行"},
            ]
        )

        result = main.select_longterm_pool(
            stocks,
            {"000001.SZ": None},
            "20260603",
            regime="BULL_TREND",
        )

        self.assertTrue(result.empty)

    def test_legacy_raw_score_allows_shallow_pullback_and_uses_raw_score(self):
        stocks = pd.DataFrame(
            [
                {
                    "code": "000001",
                    "name": "平安银行",
                    "industry": "银行",
                    "main_net_inflow": 2500,
                    "turnover": 2.0,
                    "volume_ratio": 1.4,
                    "change": 1.2,
                    "amount": 100000,
                },
                {
                    "code": "000002",
                    "name": "万科A",
                    "industry": "地产",
                    "main_net_inflow": 100,
                    "turnover": 1.0,
                    "volume_ratio": 1.1,
                    "change": 0.2,
                    "amount": 80000,
                },
            ]
        )
        ma_dict = {
            "000001.SZ": {
                "close": 10.0,
                "ma20": 10.5,
                "ma60": 9.8,
                "ma20_above_ma60": True,
                "ma20_slope": 0.3,
                "drawdown_from_high": 1.0,
                "vol_accelerating": True,
                "eod_strong": True,
                "vol_trend_up": False,
                "is_positive_candle": True,
                "wyckoff_score": 70,
                "high20": 11.0,
                "low20": 9.0,
                "atr_14": 0.2,
            },
            "000002.SZ": {
                "close": 8.0,
                "ma20": 8.2,
                "ma60": 7.9,
                "ma20_above_ma60": True,
                "ma20_slope": 0.1,
                "drawdown_from_high": 2.0,
                "vol_accelerating": False,
                "eod_strong": False,
                "vol_trend_up": True,
                "is_positive_candle": False,
                "wyckoff_score": 20,
                "high20": 8.5,
                "low20": 7.5,
                "atr_14": 0.15,
            },
        }

        current = main.select_longterm_pool(
            stocks,
            ma_dict,
            "20260603",
            regime="BULL_TREND",
            score_threshold=70,
        )
        legacy = main.select_longterm_pool(
            stocks,
            ma_dict,
            "20260603",
            regime="BULL_TREND",
            score_threshold=70,
            longterm_profile="legacy_raw_score_v1",
        )

        self.assertTrue(current.empty)
        self.assertEqual(legacy.iloc[0]["code"], "000001")
        self.assertGreater(legacy.iloc[0]["longterm_score"], 40)
        self.assertGreater(legacy.iloc[0]["score_flow"], 0)

    def test_zscore_v5_quality_guard_prefers_clean_entry_over_hot_financial_score(self):
        stocks = pd.DataFrame(
            [
                {
                    "code": "000001",
                    "name": "高财务过热",
                    "industry": "强行业",
                    "main_net_inflow": 5000,
                    "turnover": 18.0,
                    "volume_ratio": 2.5,
                    "change": 3.0,
                    "amount": 120000,
                },
                {
                    "code": "000002",
                    "name": "稳健入场",
                    "industry": "强行业",
                    "main_net_inflow": 3000,
                    "turnover": 7.0,
                    "volume_ratio": 1.6,
                    "change": 1.0,
                    "amount": 100000,
                },
                {
                    "code": "000003",
                    "name": "普通一",
                    "industry": "普通行业",
                    "main_net_inflow": 1000,
                    "turnover": 5.0,
                    "volume_ratio": 1.2,
                    "change": 0.5,
                    "amount": 90000,
                },
                {
                    "code": "000004",
                    "name": "普通二",
                    "industry": "普通行业",
                    "main_net_inflow": -500,
                    "turnover": 4.0,
                    "volume_ratio": 1.1,
                    "change": 0.2,
                    "amount": 90000,
                },
                {
                    "code": "000005",
                    "name": "普通三",
                    "industry": "弱行业",
                    "main_net_inflow": 500,
                    "turnover": 3.0,
                    "volume_ratio": 1.0,
                    "change": 0.1,
                    "amount": 90000,
                },
            ]
        )
        ma_dict = {
            "000001.SZ": {
                "close": 12.8,
                "ma20": 12.0,
                "ma60": 10.0,
                "ma20_above_ma60": True,
                "ma20_slope": 0.55,
                "drawdown_from_high": 6.0,
                "vol_accelerating": True,
                "eod_strong": True,
                "vol_trend_up": True,
                "is_positive_candle": True,
                "wyckoff_score": 55,
                "high20": 14.0,
                "low20": 9.0,
                "atr_14": 0.3,
            },
            "000002.SZ": {
                "close": 10.5,
                "ma20": 10.4,
                "ma60": 10.0,
                "ma20_above_ma60": True,
                "ma20_slope": 0.25,
                "drawdown_from_high": 10.0,
                "vol_accelerating": False,
                "eod_strong": True,
                "vol_trend_up": False,
                "is_positive_candle": True,
                "wyckoff_score": 75,
                "bb_width_pct": 0.35,
                "atr_ratio": 0.55,
                "vsa_no_supply": True,
                "high20": 11.5,
                "low20": 9.5,
                "atr_14": 0.2,
            },
        }
        for code in ["000003.SZ", "000004.SZ", "000005.SZ"]:
            ma_dict[code] = {
                "close": 10.0,
                "ma20": 10.2,
                "ma60": 9.8,
                "ma20_above_ma60": True,
                "ma20_slope": 0.1,
                "drawdown_from_high": 12.0,
                "vol_accelerating": False,
                "eod_strong": False,
                "vol_trend_up": False,
                "is_positive_candle": False,
                "wyckoff_score": 40,
                "high20": 11.0,
                "low20": 9.0,
                "atr_14": 0.2,
            }

        financial_dict = {
            "000001": {"roe": 30.0, "debt_ratio": 35.0},
            "000002": {"roe": 12.0, "debt_ratio": 35.0},
        }
        profit_growth_dict = {
            "000001": {"netprofit_yoy": 1000.0, "profit_growth_accel": True},
            "000002": {"netprofit_yoy": 30.0, "profit_growth_accel": False},
        }

        v5 = main.select_longterm_pool(
            stocks,
            ma_dict,
            "20260603",
            financial_dict=financial_dict,
            industry_rs={"强行业": 12.0, "普通行业": 2.0, "弱行业": -4.0},
            profit_growth_dict=profit_growth_dict,
            regime="BULL_TREND",
            score_threshold=0,
            longterm_profile="zscore_v5_quality_guard",
        )

        self.assertEqual(v5.iloc[0]["code"], "000002")
        hot = v5[v5["code"] == "000001"].iloc[0]
        clean = v5[v5["code"] == "000002"].iloc[0]
        self.assertLess(hot["longterm_score"], clean["longterm_score"])
        self.assertLess(abs(hot["score_fin"]), 8)

    def test_zscore_v7_quality_guard_penalizes_overheated_false_strength(self):
        stocks = pd.DataFrame(
            [
                {
                    "code": "000001",
                    "name": "过热假强",
                    "industry": "过热行业",
                    "main_net_inflow": 6000,
                    "turnover": 12.0,
                    "volume_ratio": 1.8,
                    "change": 2.0,
                    "amount": 120000,
                },
                {
                    "code": "000002",
                    "name": "稳态趋势",
                    "industry": "稳态行业",
                    "main_net_inflow": 3500,
                    "turnover": 5.0,
                    "volume_ratio": 1.3,
                    "change": 0.8,
                    "amount": 100000,
                },
                {
                    "code": "000003",
                    "name": "普通参照一",
                    "industry": "普通行业",
                    "main_net_inflow": 1500,
                    "turnover": 4.0,
                    "volume_ratio": 1.1,
                    "change": 0.3,
                    "amount": 90000,
                },
                {
                    "code": "000004",
                    "name": "普通参照二",
                    "industry": "普通行业",
                    "main_net_inflow": 1000,
                    "turnover": 3.0,
                    "volume_ratio": 1.0,
                    "change": 0.2,
                    "amount": 90000,
                },
            ]
        )
        ma_dict = {
            "000001.SZ": {
                "close": 12.3,
                "ma20": 11.0,
                "ma60": 10.0,
                "ma20_above_ma60": True,
                "ma20_slope": 0.05,
                "drawdown_from_high": 9.0,
                "vol_accelerating": True,
                "eod_strong": True,
                "vol_trend_up": True,
                "is_positive_candle": True,
                "wyckoff_score": 65,
                "high20": 13.0,
                "low20": 9.0,
                "atr_14": 0.25,
            },
            "000002.SZ": {
                "close": 10.8,
                "ma20": 10.5,
                "ma60": 10.0,
                "ma20_above_ma60": True,
                "ma20_slope": 0.35,
                "drawdown_from_high": 10.0,
                "vol_accelerating": False,
                "eod_strong": True,
                "vol_trend_up": False,
                "is_positive_candle": True,
                "wyckoff_score": 70,
                "bb_width_pct": 0.45,
                "atr_ratio": 0.65,
                "high20": 11.5,
                "low20": 9.5,
                "atr_14": 0.2,
            },
        }
        for code in ["000003.SZ", "000004.SZ"]:
            ma_dict[code] = {
                "close": 10.0,
                "ma20": 10.2,
                "ma60": 9.8,
                "ma20_above_ma60": True,
                "ma20_slope": 0.2,
                "drawdown_from_high": 11.0,
                "vol_accelerating": False,
                "eod_strong": False,
                "vol_trend_up": False,
                "is_positive_candle": False,
                "wyckoff_score": 45,
                "high20": 11.0,
                "low20": 9.0,
                "atr_14": 0.2,
            }

        result = main.select_longterm_pool(
            stocks,
            ma_dict,
            "20260603",
            industry_rs={"过热行业": 16.0, "稳态行业": 6.0, "普通行业": 3.0},
            regime="BULL_TREND",
            score_threshold=0,
            longterm_profile="zscore_v7_quality_guard",
        )

        self.assertEqual(result.iloc[0]["code"], "000002")
        overheated = result[result["code"] == "000001"].iloc[0]
        stable = result[result["code"] == "000002"].iloc[0]
        self.assertLess(overheated["longterm_score"], stable["longterm_score"])
        self.assertLess(overheated["score_quality_guard"], 0)
        self.assertIn("行业过热", overheated["quality_guard_reasons"])
        self.assertIn("换手偏热", overheated["quality_guard_reasons"])


if __name__ == "__main__":
    unittest.main()
