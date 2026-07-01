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


RETIRED_LONGTERM_PROFILE_TEST = unittest.skip(
    "retired longterm research profile; active contracts start at v11/v18"
)


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


class FakeIndexDailyPro:
    def __init__(self):
        self.index_daily_calls = []

    def index_daily(self, **kwargs):
        self.index_daily_calls.append(kwargs)
        dates = pd.bdate_range(end=pd.Timestamp("2026-06-03"), periods=130)
        return pd.DataFrame(
            {
                "trade_date": [d.strftime("%Y%m%d") for d in dates],
                "close": [3000 + i * 2 for i in range(len(dates))],
            }
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

    def test_live_signal_boost_cannot_lift_low_quality_short_candidate(self):
        boosted = main._apply_live_signal_boost(
            base_score=50.0,
            score_threshold=60.0,
            news_boost=30.0,
            concept_boost=10.0,
            top_list_bonus=10.0,
        )

        self.assertEqual(boosted["positive_live_boost"], 0.0)
        self.assertEqual(boosted["final_score"], 50.0)

    def test_live_signal_boost_can_help_near_threshold_candidate_lightly(self):
        boosted = main._apply_live_signal_boost(
            base_score=57.0,
            score_threshold=60.0,
            news_boost=30.0,
            concept_boost=10.0,
            top_list_bonus=10.0,
        )

        self.assertEqual(boosted["positive_live_boost"], 8.0)
        self.assertEqual(boosted["final_score"], 65.0)

    def test_negative_news_still_deducts_score(self):
        boosted = main._apply_live_signal_boost(
            base_score=65.0,
            score_threshold=60.0,
            news_boost=-20.0,
            concept_boost=10.0,
            top_list_bonus=10.0,
        )

        self.assertEqual(boosted["negative_live_boost"], -8.0)
        self.assertEqual(boosted["positive_live_boost"], 6.0)
        self.assertEqual(boosted["final_score"], 63.0)

    def test_short_ai_payload_includes_effective_live_signal_fields(self):
        pool = pd.DataFrame(
            [
                {
                    "code": "000001",
                    "name": "测试股",
                    "industry": "软件服务",
                    "close": 10.0,
                    "change": 1.0,
                    "volume_ratio": 1.8,
                    "main_net_inflow": 1200,
                    "news_boost": 8.0,
                    "concept_boost": 2.0,
                    "hot_concept_match": True,
                    "positive_live_boost": 8.0,
                    "negative_live_boost": 0.0,
                    "news_boost_raw": 30.0,
                }
            ]
        )

        payload = main._short_ai_payload(pool)
        row = payload[0]

        self.assertEqual(row["news_boost"], 8.0)
        self.assertEqual(row["concept_boost"], 2.0)
        self.assertTrue(row["hot_concept_match"])
        self.assertEqual(row["positive_live_boost"], 8.0)
        self.assertEqual(row["negative_live_boost"], 0.0)
        self.assertNotIn("news_boost_raw", row)

    def test_weekly_macro_trend_fetches_enough_history_for_ma100_slope(self):
        fake_pro = FakeIndexDailyPro()

        with patch.object(main, "pro", fake_pro):
            mode, macro_data = main.get_weekly_macro_trend("20260603")

        start_date = pd.Timestamp(fake_pro.index_daily_calls[0]["start_date"])
        end_date = pd.Timestamp(fake_pro.index_daily_calls[0]["end_date"])
        self.assertGreaterEqual((end_date - start_date).days, 300)
        self.assertEqual(mode, "active")
        self.assertGreater(macro_data["ma100_slope_pct"], 0)
        self.assertGreater(macro_data["price_vs_ma100"], 0)
        self.assertGreater(macro_data["idx_ret_120d"], 0)


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

    @RETIRED_LONGTERM_PROFILE_TEST
    def test_repair_v1_prefers_midcap_low_position_over_large_quality_name(self):
        stocks = pd.DataFrame(
            [
                {
                    "code": "000001",
                    "name": "修复弹性",
                    "industry": "制造",
                    "main_net_inflow": 1200,
                    "turnover": 2.4,
                    "volume_ratio": 0.9,
                    "change": 0.3,
                    "amount": 120000,
                    "total_mv": 220000,
                    "circ_mv": 160000,
                    "pb": 1.8,
                    "pe_ttm": 38,
                    "ps_ttm": 2.2,
                    "dv_ratio": 0.5,
                },
                {
                    "code": "000002",
                    "name": "大盘白马",
                    "industry": "消费",
                    "main_net_inflow": 8000,
                    "turnover": 0.7,
                    "volume_ratio": 1.0,
                    "change": 0.1,
                    "amount": 300000,
                    "total_mv": 9000000,
                    "circ_mv": 8000000,
                    "pb": 5.5,
                    "pe_ttm": 22,
                    "ps_ttm": 8.5,
                    "dv_ratio": 3.0,
                },
                {
                    "code": "000003",
                    "name": "爆雷微盘",
                    "industry": "地产",
                    "main_net_inflow": 500,
                    "turnover": 3.0,
                    "volume_ratio": 1.1,
                    "change": 0.2,
                    "amount": 80000,
                    "total_mv": 35000,
                    "circ_mv": 22000,
                    "pb": 0.8,
                    "pe_ttm": 12,
                    "ps_ttm": 0.5,
                    "dv_ratio": 0.0,
                },
            ]
        )
        ma_dict = {
            "000001.SZ": {
                "close": 9.5,
                "ma20": 10.2,
                "ma60": 10.0,
                "ma20_above_ma60": True,
                "ma20_slope": -0.02,
                "drawdown_from_high": 32.0,
                "vol_accelerating": False,
                "eod_strong": False,
                "vol_trend_up": False,
                "is_positive_candle": True,
                "wyckoff_score": 55,
                "high20": 14.0,
                "low20": 8.8,
                "atr_14": 0.25,
            },
            "000002.SZ": {
                "close": 18.0,
                "ma20": 17.5,
                "ma60": 14.0,
                "ma20_above_ma60": True,
                "ma20_slope": 0.3,
                "drawdown_from_high": 6.0,
                "vol_accelerating": False,
                "eod_strong": True,
                "vol_trend_up": True,
                "is_positive_candle": True,
                "wyckoff_score": 70,
                "high20": 19.0,
                "low20": 13.0,
                "atr_14": 0.3,
            },
            "000003.SZ": {
                "close": 6.0,
                "ma20": 6.1,
                "ma60": 6.2,
                "ma20_above_ma60": False,
                "ma20_slope": -0.05,
                "drawdown_from_high": 38.0,
                "vol_accelerating": False,
                "eod_strong": False,
                "vol_trend_up": False,
                "is_positive_candle": False,
                "wyckoff_score": 30,
                "high20": 9.0,
                "low20": 5.8,
                "atr_14": 0.2,
            },
        }
        financial_dict = {
            "000001": {"roe": 2.0, "debt_ratio": 45.0},
            "000002": {"roe": 18.0, "debt_ratio": 30.0},
            "000003": {"roe": -18.0, "debt_ratio": 96.0},
        }
        profit_growth_dict = {
            "000001": {"netprofit_yoy": -12.0},
            "000002": {"netprofit_yoy": 25.0},
            "000003": {"netprofit_yoy": -85.0},
        }

        result = main.select_longterm_pool(
            stocks,
            ma_dict,
            "20260603",
            financial_dict=financial_dict,
            industry_rs={"制造": 2.0, "消费": 4.0, "地产": -4.0},
            profit_growth_dict=profit_growth_dict,
            regime="BULL_TREND",
            score_threshold=0,
            longterm_profile="repair_v1",
        )

        self.assertEqual(result.iloc[0]["code"], "000001")
        self.assertNotIn("000003", result["code"].tolist())
        repair = result[result["code"] == "000001"].iloc[0]
        large = result[result["code"] == "000002"].iloc[0]
        self.assertGreater(repair["score_marketcap"], large["score_marketcap"])
        self.assertGreater(repair["score_position"], large["score_position"])

    @RETIRED_LONGTERM_PROFILE_TEST
    def test_repair_v2_balanced_prefers_reasonable_mid_repair(self):
        stocks = pd.DataFrame(
            [
                {
                    "code": "000011",
                    "name": "balanced",
                    "industry": "steady",
                    "main_net_inflow": 1500,
                    "turnover": 2.2,
                    "volume_ratio": 1.0,
                    "change": 0.2,
                    "amount": 150000,
                    "total_mv": 650000,
                    "circ_mv": 520000,
                    "pb": 2.2,
                    "pe_ttm": 36,
                    "ps_ttm": 2.6,
                    "dv_ratio": 0.8,
                },
                {
                    "code": "000012",
                    "name": "overheated",
                    "industry": "hot",
                    "main_net_inflow": 2400,
                    "turnover": 4.8,
                    "volume_ratio": 1.5,
                    "change": 0.1,
                    "amount": 180000,
                    "total_mv": 420000,
                    "circ_mv": 360000,
                    "pb": 1.6,
                    "pe_ttm": 28,
                    "ps_ttm": 1.8,
                    "dv_ratio": 1.5,
                },
                {
                    "code": "000013",
                    "name": "expensive",
                    "industry": "steady",
                    "main_net_inflow": 1600,
                    "turnover": 2.0,
                    "volume_ratio": 1.0,
                    "change": 0.1,
                    "amount": 140000,
                    "total_mv": 700000,
                    "circ_mv": 610000,
                    "pb": 7.2,
                    "pe_ttm": 160,
                    "ps_ttm": 8.2,
                    "dv_ratio": 0.0,
                },
            ]
        )
        ma_dict = {
            "000011.SZ": {
                "close": 10.8,
                "ma20": 10.5,
                "ma60": 10.0,
                "ma20_above_ma60": True,
                "ma20_slope": 0.08,
                "drawdown_from_high": 17.0,
                "vol_accelerating": False,
                "eod_strong": False,
                "vol_trend_up": False,
                "is_positive_candle": True,
                "wyckoff_score": 58,
                "high20": 13.0,
                "low20": 9.8,
                "atr_14": 0.22,
            },
            "000012.SZ": {
                "close": 8.8,
                "ma20": 8.9,
                "ma60": 8.0,
                "ma20_above_ma60": True,
                "ma20_slope": 0.18,
                "drawdown_from_high": 32.0,
                "vol_accelerating": True,
                "eod_strong": True,
                "vol_trend_up": True,
                "is_positive_candle": True,
                "wyckoff_score": 70,
                "high20": 13.0,
                "low20": 7.8,
                "atr_14": 0.28,
            },
            "000013.SZ": {
                "close": 13.0,
                "ma20": 12.8,
                "ma60": 12.0,
                "ma20_above_ma60": True,
                "ma20_slope": 0.08,
                "drawdown_from_high": 18.0,
                "vol_accelerating": False,
                "eod_strong": False,
                "vol_trend_up": False,
                "is_positive_candle": True,
                "wyckoff_score": 58,
                "high20": 15.5,
                "low20": 11.8,
                "atr_14": 0.25,
            },
        }
        financial_dict = {
            "000011": {"roe": 6.0, "debt_ratio": 45.0},
            "000012": {"roe": 20.0, "debt_ratio": 20.0},
            "000013": {"roe": 8.0, "debt_ratio": 42.0},
        }
        profit_growth_dict = {
            "000011": {"netprofit_yoy": 8.0},
            "000012": {"netprofit_yoy": 60.0},
            "000013": {"netprofit_yoy": 12.0},
        }

        result = main.select_longterm_pool(
            stocks,
            ma_dict,
            "20260603",
            financial_dict=financial_dict,
            industry_rs={"steady": 5.0, "hot": 18.0},
            profit_growth_dict=profit_growth_dict,
            regime="BULL_TREND",
            score_threshold=0,
            longterm_profile="repair_v2_balanced",
        )

        self.assertEqual(result.iloc[0]["code"], "000011")
        balanced = result[result["code"] == "000011"].iloc[0]
        overheated = result[result["code"] == "000012"].iloc[0]
        expensive = result[result["code"] == "000013"].iloc[0]
        self.assertGreater(balanced["longterm_score"], overheated["longterm_score"])
        self.assertGreater(balanced["score_value"], expensive["score_value"])

    @RETIRED_LONGTERM_PROFILE_TEST
    def test_repair_v3_midband_prefers_sweet_spot_over_perfect_scores(self):
        stocks = pd.DataFrame(
            [
                {
                    "code": "000021",
                    "name": "sweet",
                    "industry": "warm",
                    "main_net_inflow": 1200,
                    "turnover": 2.0,
                    "volume_ratio": 1.0,
                    "change": 0.1,
                    "amount": 160000,
                    "total_mv": 900000,
                    "circ_mv": 760000,
                    "pb": 2.4,
                    "pe_ttm": 42,
                    "ps_ttm": 2.4,
                    "dv_ratio": 0.8,
                },
                {
                    "code": "000022",
                    "name": "crowded",
                    "industry": "hot",
                    "main_net_inflow": 3600,
                    "turnover": 6.8,
                    "volume_ratio": 2.5,
                    "change": 0.2,
                    "amount": 230000,
                    "total_mv": 420000,
                    "circ_mv": 360000,
                    "pb": 1.2,
                    "pe_ttm": 24,
                    "ps_ttm": 1.0,
                    "dv_ratio": 2.0,
                },
                {
                    "code": "000023",
                    "name": "too_large",
                    "industry": "warm",
                    "main_net_inflow": 1800,
                    "turnover": 1.5,
                    "volume_ratio": 0.9,
                    "change": 0.1,
                    "amount": 200000,
                    "total_mv": 2600000,
                    "circ_mv": 2300000,
                    "pb": 2.0,
                    "pe_ttm": 34,
                    "ps_ttm": 2.0,
                    "dv_ratio": 1.0,
                },
            ]
        )
        ma_dict = {
            "000021.SZ": {
                "close": 11.0,
                "ma20": 10.8,
                "ma60": 10.2,
                "ma20_above_ma60": True,
                "ma20_slope": 0.08,
                "drawdown_from_high": 15.0,
                "vol_accelerating": False,
                "eod_strong": False,
                "vol_trend_up": False,
                "is_positive_candle": True,
                "wyckoff_score": 58,
                "high20": 13.5,
                "low20": 10.0,
                "atr_14": 0.24,
            },
            "000022.SZ": {
                "close": 8.8,
                "ma20": 8.9,
                "ma60": 8.0,
                "ma20_above_ma60": True,
                "ma20_slope": 0.22,
                "drawdown_from_high": 24.0,
                "vol_accelerating": True,
                "eod_strong": True,
                "vol_trend_up": True,
                "is_positive_candle": True,
                "wyckoff_score": 75,
                "high20": 12.0,
                "low20": 7.8,
                "atr_14": 0.28,
            },
            "000023.SZ": {
                "close": 16.0,
                "ma20": 15.7,
                "ma60": 14.5,
                "ma20_above_ma60": True,
                "ma20_slope": 0.10,
                "drawdown_from_high": 16.0,
                "vol_accelerating": False,
                "eod_strong": False,
                "vol_trend_up": False,
                "is_positive_candle": True,
                "wyckoff_score": 58,
                "high20": 19.0,
                "low20": 14.2,
                "atr_14": 0.3,
            },
        }
        financial_dict = {
            "000021": {"roe": 7.0, "debt_ratio": 45.0},
            "000022": {"roe": 22.0, "debt_ratio": 18.0},
            "000023": {"roe": 8.0, "debt_ratio": 42.0},
        }
        profit_growth_dict = {
            "000021": {"netprofit_yoy": 12.0},
            "000022": {"netprofit_yoy": 70.0},
            "000023": {"netprofit_yoy": 10.0},
        }

        result = main.select_longterm_pool(
            stocks,
            ma_dict,
            "20260603",
            financial_dict=financial_dict,
            industry_rs={"warm": 4.0, "hot": 18.0},
            profit_growth_dict=profit_growth_dict,
            regime="BULL_TREND",
            score_threshold=0,
            longterm_profile="repair_v3_midband",
        )

        self.assertEqual(result.iloc[0]["code"], "000021")
        sweet = result[result["code"] == "000021"].iloc[0]
        crowded = result[result["code"] == "000022"].iloc[0]
        large = result[result["code"] == "000023"].iloc[0]
        self.assertGreater(sweet["longterm_score"], crowded["longterm_score"])
        self.assertGreater(sweet["longterm_score"], large["longterm_score"])

    @RETIRED_LONGTERM_PROFILE_TEST
    def test_repair_v3_defensive_gate_skips_weak_longterm_environment(self):
        stocks = pd.DataFrame(
            [
                {
                    "code": "000031",
                    "name": "weak_a",
                    "industry": "weak",
                    "main_net_inflow": 1200,
                    "turnover": 2.0,
                    "volume_ratio": 1.0,
                    "change": 0.1,
                    "amount": 160000,
                    "total_mv": 900000,
                    "circ_mv": 760000,
                    "pb": 2.4,
                    "pe_ttm": 42,
                    "ps_ttm": 2.4,
                    "dv_ratio": 0.8,
                },
                {
                    "code": "000032",
                    "name": "weak_b",
                    "industry": "weak",
                    "main_net_inflow": 900,
                    "turnover": 1.8,
                    "volume_ratio": 0.9,
                    "change": 0.1,
                    "amount": 150000,
                    "total_mv": 820000,
                    "circ_mv": 720000,
                    "pb": 2.2,
                    "pe_ttm": 38,
                    "ps_ttm": 2.0,
                    "dv_ratio": 0.6,
                },
                {
                    "code": "000033",
                    "name": "weak_c",
                    "industry": "weak",
                    "main_net_inflow": 800,
                    "turnover": 2.1,
                    "volume_ratio": 1.1,
                    "change": 0.1,
                    "amount": 155000,
                    "total_mv": 780000,
                    "circ_mv": 700000,
                    "pb": 2.0,
                    "pe_ttm": 35,
                    "ps_ttm": 2.1,
                    "dv_ratio": 0.5,
                },
            ]
        )
        ma_dict = {
            "000031.SZ": {
                "close": 9.6,
                "ma20": 9.7,
                "ma60": 10.0,
                "ma20_above_ma60": False,
                "ma20_slope": -0.08,
                "drawdown_from_high": 16.0,
                "vol_accelerating": False,
                "eod_strong": False,
                "vol_trend_up": False,
                "is_positive_candle": True,
                "wyckoff_score": 58,
                "high20": 12.0,
                "low20": 9.0,
                "atr_14": 0.22,
            },
            "000032.SZ": {
                "close": 8.7,
                "ma20": 9.4,
                "ma60": 9.2,
                "ma20_above_ma60": True,
                "ma20_slope": -0.06,
                "drawdown_from_high": 18.0,
                "vol_accelerating": False,
                "eod_strong": False,
                "vol_trend_up": False,
                "is_positive_candle": True,
                "wyckoff_score": 58,
                "high20": 10.8,
                "low20": 8.2,
                "atr_14": 0.2,
            },
            "000033.SZ": {
                "close": 7.8,
                "ma20": 8.6,
                "ma60": 8.4,
                "ma20_above_ma60": True,
                "ma20_slope": -0.04,
                "drawdown_from_high": 14.0,
                "vol_accelerating": False,
                "eod_strong": False,
                "vol_trend_up": False,
                "is_positive_candle": True,
                "wyckoff_score": 58,
                "high20": 9.5,
                "low20": 7.4,
                "atr_14": 0.18,
            },
        }

        result = main.select_longterm_pool(
            stocks,
            ma_dict,
            "20260603",
            financial_dict={
                "000031": {"roe": 8.0, "debt_ratio": 45.0},
                "000032": {"roe": 7.0, "debt_ratio": 42.0},
                "000033": {"roe": 6.0, "debt_ratio": 40.0},
            },
            industry_rs={"weak": -6.0},
            profit_growth_dict={
                "000031": {"netprofit_yoy": 10.0},
                "000032": {"netprofit_yoy": 8.0},
                "000033": {"netprofit_yoy": 6.0},
            },
            regime="BULL_TREND",
            score_threshold=0,
            longterm_profile="repair_v3_defensive_gate",
        )

        self.assertTrue(result.empty)

    @RETIRED_LONGTERM_PROFILE_TEST
    def test_repair_v4_market_admission_requires_stronger_environment(self):
        stocks = pd.DataFrame(
            [
                {
                    "code": "000041",
                    "name": "weak_env_a",
                    "industry": "mixed",
                    "main_net_inflow": 1200,
                    "turnover": 2.0,
                    "volume_ratio": 1.0,
                    "change": 0.1,
                    "amount": 160000,
                    "total_mv": 900000,
                    "circ_mv": 760000,
                    "pb": 2.4,
                    "pe_ttm": 42,
                    "ps_ttm": 2.4,
                    "dv_ratio": 0.8,
                },
                {
                    "code": "000042",
                    "name": "weak_env_b",
                    "industry": "mixed",
                    "main_net_inflow": 900,
                    "turnover": 1.8,
                    "volume_ratio": 0.9,
                    "change": 0.1,
                    "amount": 150000,
                    "total_mv": 820000,
                    "circ_mv": 720000,
                    "pb": 2.2,
                    "pe_ttm": 38,
                    "ps_ttm": 2.0,
                    "dv_ratio": 0.6,
                },
                {
                    "code": "000043",
                    "name": "weak_env_c",
                    "industry": "strong",
                    "main_net_inflow": 800,
                    "turnover": 2.1,
                    "volume_ratio": 1.1,
                    "change": 0.1,
                    "amount": 155000,
                    "total_mv": 780000,
                    "circ_mv": 700000,
                    "pb": 2.0,
                    "pe_ttm": 35,
                    "ps_ttm": 2.1,
                    "dv_ratio": 0.5,
                },
            ]
        )
        ma_dict = {
            "000041.SZ": {
                "close": 10.0,
                "ma20": 10.2,
                "ma60": 9.8,
                "ma20_above_ma60": True,
                "ma20_slope": 0.02,
                "drawdown_from_high": 12.0,
                "vol_accelerating": False,
                "eod_strong": False,
                "vol_trend_up": False,
                "is_positive_candle": True,
                "wyckoff_score": 58,
                "high20": 11.5,
                "low20": 9.5,
                "atr_14": 0.2,
            },
            "000042.SZ": {
                "close": 9.0,
                "ma20": 8.9,
                "ma60": 8.7,
                "ma20_above_ma60": True,
                "ma20_slope": -0.03,
                "drawdown_from_high": 10.0,
                "vol_accelerating": False,
                "eod_strong": False,
                "vol_trend_up": False,
                "is_positive_candle": True,
                "wyckoff_score": 58,
                "high20": 10.0,
                "low20": 8.5,
                "atr_14": 0.2,
            },
            "000043.SZ": {
                "close": 8.0,
                "ma20": 7.8,
                "ma60": 7.6,
                "ma20_above_ma60": True,
                "ma20_slope": -0.04,
                "drawdown_from_high": 14.0,
                "vol_accelerating": False,
                "eod_strong": False,
                "vol_trend_up": False,
                "is_positive_candle": True,
                "wyckoff_score": 58,
                "high20": 9.3,
                "low20": 7.5,
                "atr_14": 0.18,
            },
        }

        result = main.select_longterm_pool(
            stocks,
            ma_dict,
            "20260603",
            financial_dict={
                "000041": {"roe": 8.0, "debt_ratio": 45.0},
                "000042": {"roe": 7.0, "debt_ratio": 42.0},
                "000043": {"roe": 6.0, "debt_ratio": 40.0},
            },
            industry_rs={"mixed": -1.0, "strong": 5.0},
            profit_growth_dict={
                "000041": {"netprofit_yoy": 10.0},
                "000042": {"netprofit_yoy": 8.0},
                "000043": {"netprofit_yoy": 6.0},
            },
            regime="BULL_TREND",
            score_threshold=0,
            longterm_profile="repair_v4_market_admission",
        )

        self.assertTrue(result.empty)

    @RETIRED_LONGTERM_PROFILE_TEST
    def test_repair_v4_market_admission_keeps_only_clean_longterm_candidates(self):
        stocks = pd.DataFrame(
            [
                {
                    "code": "000051",
                    "name": "clean",
                    "industry": "strong",
                    "main_net_inflow": 1500,
                    "turnover": 2.4,
                    "volume_ratio": 1.1,
                    "change": 0.5,
                    "amount": 180000,
                    "total_mv": 900000,
                    "circ_mv": 760000,
                    "pb": 2.2,
                    "pe_ttm": 32,
                    "ps_ttm": 2.0,
                    "dv_ratio": 1.0,
                },
                {
                    "code": "000052",
                    "name": "weak_industry",
                    "industry": "weak",
                    "main_net_inflow": 1800,
                    "turnover": 2.0,
                    "volume_ratio": 1.0,
                    "change": 0.4,
                    "amount": 170000,
                    "total_mv": 880000,
                    "circ_mv": 720000,
                    "pb": 2.1,
                    "pe_ttm": 28,
                    "ps_ttm": 1.9,
                    "dv_ratio": 1.0,
                },
                {
                    "code": "000053",
                    "name": "too_hot",
                    "industry": "strong",
                    "main_net_inflow": 2000,
                    "turnover": 12.0,
                    "volume_ratio": 3.2,
                    "change": 3.0,
                    "amount": 220000,
                    "total_mv": 900000,
                    "circ_mv": 800000,
                    "pb": 2.5,
                    "pe_ttm": 45,
                    "ps_ttm": 2.2,
                    "dv_ratio": 0.8,
                },
            ]
        )
        ma_dict = {}
        for code, close, ma20, ma60, slope, drawdown in [
            ("000051.SZ", 10.6, 10.3, 10.0, 0.18, 12.0),
            ("000052.SZ", 9.8, 9.6, 9.3, 0.16, 11.0),
            ("000053.SZ", 13.5, 12.8, 10.0, 0.35, 8.0),
        ]:
            ma_dict[code] = {
                "close": close,
                "ma20": ma20,
                "ma60": ma60,
                "ma20_above_ma60": True,
                "ma20_slope": slope,
                "drawdown_from_high": drawdown,
                "vol_accelerating": False,
                "eod_strong": True,
                "vol_trend_up": False,
                "is_positive_candle": True,
                "wyckoff_score": 62,
                "high20": close * 1.12,
                "low20": close * 0.92,
                "atr_14": close * 0.02,
            }

        result = main.select_longterm_pool(
            stocks,
            ma_dict,
            "20260603",
            financial_dict={
                "000051": {"roe": 10.0, "debt_ratio": 42.0},
                "000052": {"roe": 9.0, "debt_ratio": 45.0},
                "000053": {"roe": 8.0, "debt_ratio": 50.0},
            },
            industry_rs={"strong": 6.0, "weak": -3.0},
            profit_growth_dict={
                "000051": {"netprofit_yoy": 18.0},
                "000052": {"netprofit_yoy": 15.0},
                "000053": {"netprofit_yoy": 20.0},
            },
            regime="BULL_TREND",
            score_threshold=0,
            longterm_profile="repair_v4_market_admission",
        )

        self.assertEqual(result["code"].tolist(), ["000051"])

    @RETIRED_LONGTERM_PROFILE_TEST
    def test_longterm_quality_trend_v1_skips_weak_market_width(self):
        stocks = pd.DataFrame(
            [
                {
                    "code": "000061",
                    "name": "weak_a",
                    "industry": "weak",
                    "main_net_inflow": 1200,
                    "turnover": 2.0,
                    "volume_ratio": 1.0,
                    "change": 0.1,
                    "amount": 160000,
                    "total_mv": 1200000,
                    "circ_mv": 900000,
                    "pb": 2.0,
                    "pe_ttm": 28,
                    "ps_ttm": 2.0,
                    "dv_ratio": 1.0,
                },
                {
                    "code": "000062",
                    "name": "weak_b",
                    "industry": "weak",
                    "main_net_inflow": 900,
                    "turnover": 2.0,
                    "volume_ratio": 1.0,
                    "change": 0.1,
                    "amount": 150000,
                    "total_mv": 1100000,
                    "circ_mv": 850000,
                    "pb": 2.2,
                    "pe_ttm": 32,
                    "ps_ttm": 2.2,
                    "dv_ratio": 0.8,
                },
                {
                    "code": "000063",
                    "name": "weak_c",
                    "industry": "mixed",
                    "main_net_inflow": 800,
                    "turnover": 2.0,
                    "volume_ratio": 1.0,
                    "change": 0.1,
                    "amount": 150000,
                    "total_mv": 1000000,
                    "circ_mv": 800000,
                    "pb": 2.4,
                    "pe_ttm": 35,
                    "ps_ttm": 2.4,
                    "dv_ratio": 0.6,
                },
            ]
        )
        ma_dict = {
            "000061.SZ": {"close": 10, "ma20": 9.8, "ma60": 10.1, "ma20_above_ma60": False, "ma20_slope": -0.02, "drawdown_from_high": 12, "high20": 11, "low20": 9, "atr_14": 0.2},
            "000062.SZ": {"close": 9, "ma20": 9.1, "ma60": 9.0, "ma20_above_ma60": True, "ma20_slope": -0.01, "drawdown_from_high": 10, "high20": 10, "low20": 8.5, "atr_14": 0.2},
            "000063.SZ": {"close": 8, "ma20": 8.2, "ma60": 8.0, "ma20_above_ma60": True, "ma20_slope": 0.01, "drawdown_from_high": 9, "high20": 9, "low20": 7.5, "atr_14": 0.18},
        }

        result = main.select_longterm_pool(
            stocks,
            ma_dict,
            "20260603",
            financial_dict={
                "000061": {"roe": 8.0, "debt_ratio": 45.0},
                "000062": {"roe": 7.0, "debt_ratio": 42.0},
                "000063": {"roe": 6.0, "debt_ratio": 40.0},
            },
            industry_rs={"weak": -4.0, "mixed": 1.0},
            profit_growth_dict={
                "000061": {"netprofit_yoy": 10.0},
                "000062": {"netprofit_yoy": 8.0},
                "000063": {"netprofit_yoy": 6.0},
            },
            regime="BULL_TREND",
            score_threshold=0,
            longterm_profile="longterm_quality_trend_v1",
        )

        self.assertTrue(result.empty)

    @RETIRED_LONGTERM_PROFILE_TEST
    def test_longterm_quality_trend_v1_prefers_confirmed_quality_trend(self):
        stocks = pd.DataFrame(
            [
                {
                    "code": "000071",
                    "name": "quality_trend",
                    "industry": "strong",
                    "main_net_inflow": 1800,
                    "turnover": 3.0,
                    "volume_ratio": 1.2,
                    "change": 0.8,
                    "amount": 200000,
                    "total_mv": 1600000,
                    "circ_mv": 1100000,
                    "pb": 2.5,
                    "pe_ttm": 35,
                    "ps_ttm": 2.5,
                    "dv_ratio": 1.0,
                },
                {
                    "code": "000072",
                    "name": "repair_only",
                    "industry": "weak",
                    "main_net_inflow": 2400,
                    "turnover": 3.2,
                    "volume_ratio": 1.1,
                    "change": 0.4,
                    "amount": 190000,
                    "total_mv": 900000,
                    "circ_mv": 750000,
                    "pb": 1.6,
                    "pe_ttm": 24,
                    "ps_ttm": 1.6,
                    "dv_ratio": 1.2,
                },
                {
                    "code": "000073",
                    "name": "too_extended",
                    "industry": "strong",
                    "main_net_inflow": 2200,
                    "turnover": 5.0,
                    "volume_ratio": 1.8,
                    "change": 2.5,
                    "amount": 230000,
                    "total_mv": 1400000,
                    "circ_mv": 1000000,
                    "pb": 3.0,
                    "pe_ttm": 45,
                    "ps_ttm": 3.2,
                    "dv_ratio": 0.7,
                },
            ]
        )
        ma_dict = {
            "000071.SZ": {"close": 10.8, "ma20": 10.5, "ma60": 10.0, "ma20_above_ma60": True, "ma20_slope": 0.18, "drawdown_from_high": 8.0, "high20": 11.7, "low20": 9.8, "atr_14": 0.22, "eod_strong": True, "is_positive_candle": True, "wyckoff_score": 62},
            "000072.SZ": {"close": 8.8, "ma20": 8.9, "ma60": 9.2, "ma20_above_ma60": False, "ma20_slope": -0.03, "drawdown_from_high": 22.0, "high20": 11.2, "low20": 8.5, "atr_14": 0.2, "eod_strong": True, "is_positive_candle": True, "wyckoff_score": 70},
            "000073.SZ": {"close": 14.0, "ma20": 13.2, "ma60": 10.0, "ma20_above_ma60": True, "ma20_slope": 0.35, "drawdown_from_high": 4.0, "high20": 14.6, "low20": 10.5, "atr_14": 0.35, "eod_strong": True, "is_positive_candle": True, "wyckoff_score": 65},
        }

        result = main.select_longterm_pool(
            stocks,
            ma_dict,
            "20260603",
            financial_dict={
                "000071": {"roe": 12.0, "debt_ratio": 38.0},
                "000072": {"roe": 10.0, "debt_ratio": 35.0},
                "000073": {"roe": 10.0, "debt_ratio": 42.0},
            },
            industry_rs={"strong": 6.0, "weak": -2.0},
            profit_growth_dict={
                "000071": {"netprofit_yoy": 24.0},
                "000072": {"netprofit_yoy": 18.0},
                "000073": {"netprofit_yoy": 22.0},
            },
            regime="BULL_TREND",
            score_threshold=0,
            longterm_profile="longterm_quality_trend_v1",
        )

        self.assertEqual(result["code"].tolist(), ["000071"])

    @RETIRED_LONGTERM_PROFILE_TEST
    def test_longterm_quality_trend_v2_requires_stronger_market_width(self):
        stocks = pd.DataFrame(
            [
                {
                    "code": f"00008{i}",
                    "name": f"stock_{i}",
                    "industry": "strong" if i < 3 else "mixed",
                    "main_net_inflow": 1200,
                    "turnover": 2.5,
                    "volume_ratio": 1.1,
                    "change": 0.4,
                    "amount": 180000,
                    "total_mv": 1200000,
                    "circ_mv": 900000,
                    "pb": 2.2,
                    "pe_ttm": 32,
                    "ps_ttm": 2.0,
                    "dv_ratio": 1.0,
                }
                for i in range(5)
            ]
        )
        ma_dict = {}
        for i in range(5):
            ts_code = f"00008{i}.SZ"
            ma_dict[ts_code] = {
                "close": 10.0,
                "ma20": 10.2 if i < 3 else 9.9,
                "ma60": 10.0,
                "ma20_above_ma60": i < 3,
                "ma20_slope": 0.08 if i < 3 else 0.01,
                "drawdown_from_high": 10.0,
                "high20": 11.0,
                "low20": 9.2,
                "atr_14": 0.2,
                "eod_strong": True,
                "is_positive_candle": True,
                "wyckoff_score": 60,
            }

        result = main.select_longterm_pool(
            stocks,
            ma_dict,
            "20260603",
            financial_dict={f"00008{i}": {"roe": 10.0, "debt_ratio": 40.0} for i in range(5)},
            industry_rs={"strong": 4.0, "mixed": 1.0},
            profit_growth_dict={f"00008{i}": {"netprofit_yoy": 15.0} for i in range(5)},
            regime="BULL_TREND",
            score_threshold=0,
            longterm_profile="longterm_quality_trend_v2",
        )

        self.assertTrue(result.empty)

    @RETIRED_LONGTERM_PROFILE_TEST
    def test_longterm_quality_trend_v3_keeps_v2_market_admission(self):
        stocks = pd.DataFrame(
            [
                {
                    "code": f"00011{i}",
                    "name": f"stock_{i}",
                    "industry": "steady",
                    "main_net_inflow": 1200,
                    "turnover": 2.5,
                    "volume_ratio": 1.1,
                    "change": 0.4,
                    "amount": 180000,
                    "total_mv": 1200000,
                    "circ_mv": 900000,
                    "pb": 2.2,
                    "pe_ttm": 32,
                    "ps_ttm": 2.0,
                    "dv_ratio": 1.0,
                }
                for i in range(5)
            ]
        )
        ma_dict = {}
        for i in range(5):
            ma_dict[f"00011{i}.SZ"] = {
                "close": 10.0,
                "ma20": 10.2 if i < 3 else 9.9,
                "ma60": 10.0,
                "ma20_above_ma60": i < 3,
                "ma20_slope": 0.09 if i < 3 else 0.01,
                "drawdown_from_high": 7.0,
                "high20": 11.0,
                "low20": 9.2,
                "atr_14": 0.2,
                "eod_strong": True,
                "is_positive_candle": True,
                "wyckoff_score": 60,
            }

        result = main.select_longterm_pool(
            stocks,
            ma_dict,
            "20260603",
            financial_dict={f"00011{i}": {"roe": 10.0, "debt_ratio": 40.0} for i in range(5)},
            industry_rs={"steady": 5.0},
            profit_growth_dict={f"00011{i}": {"netprofit_yoy": 15.0} for i in range(5)},
            regime="BULL_TREND",
            score_threshold=0,
            longterm_profile="longterm_quality_trend_v3",
        )

        self.assertTrue(result.empty)

    @RETIRED_LONGTERM_PROFILE_TEST
    def test_longterm_quality_trend_v2_filters_hot_and_low_quality_candidates(self):
        stocks = pd.DataFrame(
            [
                {
                    "code": "000091",
                    "name": "clean_quality",
                    "industry": "steady",
                    "main_net_inflow": 1600,
                    "turnover": 3.0,
                    "volume_ratio": 1.0,
                    "change": 0.6,
                    "amount": 220000,
                    "total_mv": 1300000,
                    "circ_mv": 900000,
                    "pb": 2.4,
                    "pe_ttm": 38,
                    "ps_ttm": 2.6,
                    "dv_ratio": 1.2,
                },
                {
                    "code": "000092",
                    "name": "too_hot_rs",
                    "industry": "overheated",
                    "main_net_inflow": 2200,
                    "turnover": 6.0,
                    "volume_ratio": 1.7,
                    "change": 2.0,
                    "amount": 260000,
                    "total_mv": 1400000,
                    "circ_mv": 950000,
                    "pb": 3.2,
                    "pe_ttm": 48,
                    "ps_ttm": 3.5,
                    "dv_ratio": 0.5,
                },
                {
                    "code": "000093",
                    "name": "expensive_weak_profit",
                    "industry": "steady",
                    "main_net_inflow": 1800,
                    "turnover": 3.5,
                    "volume_ratio": 1.1,
                    "change": 0.5,
                    "amount": 210000,
                    "total_mv": 1100000,
                    "circ_mv": 850000,
                    "pb": 5.8,
                    "pe_ttm": 90,
                    "ps_ttm": 6.4,
                    "dv_ratio": 0.0,
                },
            ]
        )
        ma_dict = {
            "000091.SZ": {"close": 10.8, "ma20": 10.5, "ma60": 10.0, "ma20_above_ma60": True, "ma20_slope": 0.18, "drawdown_from_high": 9.0, "high20": 11.8, "low20": 9.7, "atr_14": 0.22, "eod_strong": True, "is_positive_candle": True, "wyckoff_score": 62},
            "000092.SZ": {"close": 13.0, "ma20": 12.2, "ma60": 10.0, "ma20_above_ma60": True, "ma20_slope": 0.42, "drawdown_from_high": 3.0, "high20": 13.4, "low20": 10.8, "atr_14": 0.35, "eod_strong": True, "is_positive_candle": True, "wyckoff_score": 60},
            "000093.SZ": {"close": 11.5, "ma20": 11.0, "ma60": 10.0, "ma20_above_ma60": True, "ma20_slope": 0.2, "drawdown_from_high": 8.0, "high20": 12.2, "low20": 9.9, "atr_14": 0.28, "eod_strong": True, "is_positive_candle": True, "wyckoff_score": 58},
        }

        result = main.select_longterm_pool(
            stocks,
            ma_dict,
            "20260603",
            financial_dict={
                "000091": {"roe": 12.0, "debt_ratio": 38.0},
                "000092": {"roe": 9.0, "debt_ratio": 48.0},
                "000093": {"roe": 3.0, "debt_ratio": 72.0},
            },
            industry_rs={"steady": 5.0, "overheated": 22.0},
            profit_growth_dict={
                "000091": {"netprofit_yoy": 22.0},
                "000092": {"netprofit_yoy": 12.0},
                "000093": {"netprofit_yoy": -12.0},
            },
            regime="BULL_TREND",
            score_threshold=0,
            longterm_profile="longterm_quality_trend_v2",
        )

        self.assertEqual(result["code"].tolist(), ["000091"])

    @RETIRED_LONGTERM_PROFILE_TEST
    def test_longterm_quality_trend_v3_cleans_shallow_and_extended_entries(self):
        stocks = pd.DataFrame(
            [
                {
                    "code": "000101",
                    "name": "clean_entry",
                    "industry": "steady",
                    "main_net_inflow": 1600,
                    "turnover": 3.0,
                    "volume_ratio": 1.0,
                    "change": 0.6,
                    "amount": 220000,
                    "total_mv": 1300000,
                    "circ_mv": 900000,
                    "pb": 2.4,
                    "pe_ttm": 38,
                    "ps_ttm": 2.6,
                    "dv_ratio": 1.2,
                },
                {
                    "code": "000102",
                    "name": "shallow_pullback",
                    "industry": "steady",
                    "main_net_inflow": 1700,
                    "turnover": 3.2,
                    "volume_ratio": 1.0,
                    "change": 0.5,
                    "amount": 210000,
                    "total_mv": 1200000,
                    "circ_mv": 850000,
                    "pb": 2.2,
                    "pe_ttm": 35,
                    "ps_ttm": 2.4,
                    "dv_ratio": 1.0,
                },
                {
                    "code": "000103",
                    "name": "extended_from_ma60",
                    "industry": "steady",
                    "main_net_inflow": 1800,
                    "turnover": 3.1,
                    "volume_ratio": 1.0,
                    "change": 0.4,
                    "amount": 210000,
                    "total_mv": 1250000,
                    "circ_mv": 860000,
                    "pb": 2.3,
                    "pe_ttm": 36,
                    "ps_ttm": 2.5,
                    "dv_ratio": 1.0,
                },
                {
                    "code": "000104",
                    "name": "rs_overheated",
                    "industry": "hot",
                    "main_net_inflow": 1900,
                    "turnover": 3.0,
                    "volume_ratio": 1.0,
                    "change": 0.5,
                    "amount": 215000,
                    "total_mv": 1250000,
                    "circ_mv": 870000,
                    "pb": 2.3,
                    "pe_ttm": 36,
                    "ps_ttm": 2.5,
                    "dv_ratio": 1.0,
                },
            ]
        )
        ma_dict = {
            "000101.SZ": {"close": 11.0, "ma20": 10.8, "ma60": 10.0, "ma20_above_ma60": True, "ma20_slope": 0.18, "drawdown_from_high": 7.0, "high20": 11.8, "low20": 9.7, "atr_14": 0.22, "eod_strong": True, "is_positive_candle": True, "wyckoff_score": 62},
            "000102.SZ": {"close": 11.0, "ma20": 10.8, "ma60": 10.0, "ma20_above_ma60": True, "ma20_slope": 0.18, "drawdown_from_high": 4.0, "high20": 11.5, "low20": 9.7, "atr_14": 0.22, "eod_strong": True, "is_positive_candle": True, "wyckoff_score": 62},
            "000103.SZ": {"close": 11.6, "ma20": 11.2, "ma60": 10.0, "ma20_above_ma60": True, "ma20_slope": 0.18, "drawdown_from_high": 7.0, "high20": 12.5, "low20": 9.7, "atr_14": 0.24, "eod_strong": True, "is_positive_candle": True, "wyckoff_score": 62},
            "000104.SZ": {"close": 11.0, "ma20": 10.8, "ma60": 10.0, "ma20_above_ma60": True, "ma20_slope": 0.18, "drawdown_from_high": 7.0, "high20": 11.8, "low20": 9.7, "atr_14": 0.22, "eod_strong": True, "is_positive_candle": True, "wyckoff_score": 62},
        }

        result = main.select_longterm_pool(
            stocks,
            ma_dict,
            "20260603",
            financial_dict={
                "000101": {"roe": 12.0, "debt_ratio": 38.0},
                "000102": {"roe": 12.0, "debt_ratio": 38.0},
                "000103": {"roe": 12.0, "debt_ratio": 38.0},
                "000104": {"roe": 12.0, "debt_ratio": 38.0},
            },
            industry_rs={"steady": 8.0, "hot": 16.5},
            profit_growth_dict={
                "000101": {"netprofit_yoy": 22.0},
                "000102": {"netprofit_yoy": 22.0},
                "000103": {"netprofit_yoy": 22.0},
                "000104": {"netprofit_yoy": 22.0},
            },
            regime="BULL_TREND",
            score_threshold=0,
            longterm_profile="longterm_quality_trend_v3",
        )

        self.assertEqual(result["code"].tolist(), ["000101"])

    @RETIRED_LONGTERM_PROFILE_TEST
    def test_longterm_quality_trend_v4_adds_independent_quality_rank(self):
        stocks = pd.DataFrame(
            [
                {
                    "code": "000121",
                    "name": "clean_rank",
                    "industry": "steady",
                    "main_net_inflow": 1200,
                    "turnover": 2.2,
                    "volume_ratio": 0.9,
                    "change": 0.4,
                    "amount": 220000,
                    "total_mv": 1300000,
                    "circ_mv": 900000,
                    "pb": 2.2,
                    "pe_ttm": 32,
                    "ps_ttm": 2.2,
                    "dv_ratio": 1.2,
                },
                {
                    "code": "000122",
                    "name": "riskier_rank",
                    "industry": "steady",
                    "main_net_inflow": 6000,
                    "turnover": 7.6,
                    "volume_ratio": 1.75,
                    "change": 2.8,
                    "amount": 260000,
                    "total_mv": 1500000,
                    "circ_mv": 1000000,
                    "pb": 4.2,
                    "pe_ttm": 76,
                    "ps_ttm": 4.8,
                    "dv_ratio": 0.2,
                },
            ]
        )
        ma_dict = {
            "000121.SZ": {
                "close": 11.0,
                "ma20": 10.8,
                "ma60": 10.0,
                "ma20_above_ma60": True,
                "ma20_slope": 0.18,
                "drawdown_from_high": 9.0,
                "high20": 12.1,
                "low20": 9.7,
                "atr_14": 0.22,
                "eod_strong": True,
                "vol_trend_up": False,
                "is_positive_candle": True,
                "wyckoff_score": 62,
            },
            "000122.SZ": {
                "close": 11.45,
                "ma20": 11.0,
                "ma60": 10.0,
                "ma20_above_ma60": True,
                "ma20_slope": 0.28,
                "drawdown_from_high": 5.2,
                "high20": 12.1,
                "low20": 9.8,
                "atr_14": 0.34,
                "eod_strong": True,
                "vol_trend_up": True,
                "is_positive_candle": True,
                "wyckoff_score": 58,
            },
        }

        result = main.select_longterm_pool(
            stocks,
            ma_dict,
            "20260603",
            financial_dict={
                "000121": {"roe": 12.0, "debt_ratio": 38.0},
                "000122": {"roe": 7.0, "debt_ratio": 63.0},
            },
            industry_rs={"steady": 8.0},
            profit_growth_dict={
                "000121": {"netprofit_yoy": 22.0},
                "000122": {"netprofit_yoy": 4.0},
            },
            regime="BULL_TREND",
            score_threshold=0,
            longterm_profile="longterm_quality_trend_v4_ranked_pool",
        )

        self.assertEqual(result["code"].tolist(), ["000121", "000122"])
        self.assertIn("quality_rank_score", result.columns)
        self.assertIn("risk_flags", result.columns)
        self.assertGreater(result.iloc[0]["quality_rank_score"], result.iloc[1]["quality_rank_score"])
        self.assertIn("位置偏高", result.iloc[1]["risk_flags"])

    @RETIRED_LONGTERM_PROFILE_TEST
    def test_longterm_quality_trend_v5_keeps_only_dual_pool_candidates(self):
        stocks = pd.DataFrame(
            [
                {
                    "code": "000131",
                    "name": "stable_quality",
                    "industry": "steady",
                    "main_net_inflow": 1500,
                    "turnover": 2.0,
                    "volume_ratio": 0.9,
                    "change": 0.6,
                    "amount": 220000,
                    "total_mv": 1500000,
                    "circ_mv": 1100000,
                    "pb": 2.0,
                    "pe_ttm": 28,
                    "ps_ttm": 2.0,
                    "dv_ratio": 1.1,
                },
                {
                    "code": "000132",
                    "name": "strong_trend",
                    "industry": "strong",
                    "main_net_inflow": 6500,
                    "turnover": 5.8,
                    "volume_ratio": 1.28,
                    "change": 2.2,
                    "amount": 260000,
                    "total_mv": 1200000,
                    "circ_mv": 900000,
                    "pb": 3.8,
                    "pe_ttm": 58,
                    "ps_ttm": 3.9,
                    "dv_ratio": 0.4,
                },
                {
                    "code": "000133",
                    "name": "observe_only",
                    "industry": "hot",
                    "main_net_inflow": 9000,
                    "turnover": 7.7,
                    "volume_ratio": 1.76,
                    "change": 4.8,
                    "amount": 300000,
                    "total_mv": 1300000,
                    "circ_mv": 1000000,
                    "pb": 4.4,
                    "pe_ttm": 78,
                    "ps_ttm": 4.9,
                    "dv_ratio": 0.1,
                },
            ]
        )
        ma_dict = {
            "000131.SZ": {
                "close": 11.0,
                "ma20": 10.8,
                "ma60": 10.0,
                "ma20_above_ma60": True,
                "ma20_slope": 0.18,
                "drawdown_from_high": 10.0,
                "high20": 12.2,
                "low20": 9.8,
                "atr_14": 0.22,
                "eod_strong": True,
                "vol_trend_up": False,
                "is_positive_candle": True,
                "wyckoff_score": 62,
            },
            "000132.SZ": {
                "close": 11.2,
                "ma20": 10.9,
                "ma60": 10.0,
                "ma20_above_ma60": True,
                "ma20_slope": 0.36,
                "drawdown_from_high": 6.2,
                "high20": 12.0,
                "low20": 9.9,
                "atr_14": 0.3,
                "eod_strong": True,
                "vol_trend_up": True,
                "is_positive_candle": True,
                "wyckoff_score": 58,
            },
            "000133.SZ": {
                "close": 11.45,
                "ma20": 11.0,
                "ma60": 10.0,
                "ma20_above_ma60": True,
                "ma20_slope": 0.42,
                "drawdown_from_high": 5.2,
                "high20": 12.1,
                "low20": 9.8,
                "atr_14": 0.34,
                "eod_strong": True,
                "vol_trend_up": True,
                "is_positive_candle": True,
                "wyckoff_score": 58,
            },
        }

        result = main.select_longterm_pool(
            stocks,
            ma_dict,
            "20260603",
            financial_dict={
                "000131": {"roe": 13.0, "debt_ratio": 36.0},
                "000132": {"roe": 9.0, "debt_ratio": 55.0},
                "000133": {"roe": 7.0, "debt_ratio": 63.0},
            },
            industry_rs={"steady": 7.0, "strong": 12.0, "hot": 14.5},
            profit_growth_dict={
                "000131": {"netprofit_yoy": 28.0},
                "000132": {"netprofit_yoy": 16.0},
                "000133": {"netprofit_yoy": 4.0},
            },
            regime="BULL_TREND",
            score_threshold=0,
            longterm_profile="longterm_quality_trend_v5_dual_pool",
        )

        self.assertEqual(result["code"].tolist(), ["000131", "000132"])
        self.assertEqual(result["pool_type"].tolist(), ["稳健质量", "强趋势行业"])
        self.assertIn("pool_rank_score", result.columns)
        self.assertNotIn("000133", result["code"].tolist())

    @RETIRED_LONGTERM_PROFILE_TEST
    def test_longterm_quality_trend_v6_filters_dirty_risk_flags(self):
        stocks = pd.DataFrame(
            [
                {
                    "code": "000141",
                    "name": "clean_quality",
                    "industry": "steady",
                    "main_net_inflow": 1200,
                    "turnover": 1.8,
                    "volume_ratio": 0.9,
                    "change": 0.5,
                    "amount": 220000,
                    "total_mv": 1500000,
                    "circ_mv": 1100000,
                    "pb": 2.0,
                    "pe_ttm": 28,
                    "ps_ttm": 2.0,
                    "dv_ratio": 1.1,
                },
                {
                    "code": "000142",
                    "name": "dirty_trend",
                    "industry": "strong",
                    "main_net_inflow": 6600,
                    "turnover": 6.4,
                    "volume_ratio": 1.55,
                    "change": 2.5,
                    "amount": 260000,
                    "total_mv": 1200000,
                    "circ_mv": 900000,
                    "pb": 4.1,
                    "pe_ttm": 72,
                    "ps_ttm": 4.6,
                    "dv_ratio": 0.4,
                },
            ]
        )
        ma_dict = {
            "000141.SZ": {
                "close": 11.0,
                "ma20": 10.8,
                "ma60": 10.0,
                "ma20_above_ma60": True,
                "ma20_slope": 0.18,
                "drawdown_from_high": 10.0,
                "high20": 12.2,
                "low20": 9.8,
                "atr_14": 0.22,
                "eod_strong": True,
                "vol_trend_up": False,
                "is_positive_candle": True,
                "wyckoff_score": 62,
            },
            "000142.SZ": {
                "close": 11.35,
                "ma20": 10.95,
                "ma60": 10.0,
                "ma20_above_ma60": True,
                "ma20_slope": 0.38,
                "drawdown_from_high": 5.6,
                "high20": 12.0,
                "low20": 9.9,
                "atr_14": 0.3,
                "eod_strong": True,
                "vol_trend_up": True,
                "is_positive_candle": True,
                "wyckoff_score": 58,
            },
        }

        result = main.select_longterm_pool(
            stocks,
            ma_dict,
            "20260603",
            financial_dict={
                "000141": {"roe": 13.0, "debt_ratio": 36.0},
                "000142": {"roe": 9.0, "debt_ratio": 55.0},
            },
            industry_rs={"steady": 7.0, "strong": 12.0},
            profit_growth_dict={
                "000141": {"netprofit_yoy": 28.0},
                "000142": {"netprofit_yoy": 16.0},
            },
            regime="BULL_TREND",
            score_threshold=0,
            longterm_profile="longterm_quality_trend_v6_clean_pool",
        )

        self.assertEqual(result["code"].tolist(), ["000141"])
        self.assertEqual(result.iloc[0]["pool_type"], "稳健质量")
        self.assertEqual(result.iloc[0]["risk_flags"], "无")

    @RETIRED_LONGTERM_PROFILE_TEST
    def test_longterm_quality_trend_v7_ranks_by_winner_profile_score(self):
        stocks = pd.DataFrame(
            [
                {
                    "code": "000151",
                    "name": "winner_profile",
                    "industry": "chem",
                    "main_net_inflow": 8500,
                    "turnover": 3.0,
                    "volume_ratio": 1.08,
                    "change": 1.2,
                    "amount": 280000,
                    "total_mv": 3100000,
                    "circ_mv": 2800000,
                    "pb": 2.8,
                    "pe_ttm": 29,
                    "ps_ttm": 2.2,
                    "dv_ratio": 0.8,
                },
                {
                    "code": "000152",
                    "name": "old_score_trap",
                    "industry": "auto",
                    "main_net_inflow": 1200,
                    "turnover": 2.2,
                    "volume_ratio": 0.82,
                    "change": 0.2,
                    "amount": 220000,
                    "total_mv": 1200000,
                    "circ_mv": 1000000,
                    "pb": 2.1,
                    "pe_ttm": 20,
                    "ps_ttm": 1.6,
                    "dv_ratio": 1.5,
                },
                {
                    "code": "000153",
                    "name": "observe_should_drop",
                    "industry": "hot",
                    "main_net_inflow": 9000,
                    "turnover": 7.7,
                    "volume_ratio": 1.76,
                    "change": 4.5,
                    "amount": 240000,
                    "total_mv": 1300000,
                    "circ_mv": 1000000,
                    "pb": 4.4,
                    "pe_ttm": 78,
                    "ps_ttm": 4.9,
                    "dv_ratio": 0.2,
                },
            ]
        )
        ma_dict = {
            "000151.SZ": {
                "close": 11.0,
                "ma20": 10.8,
                "ma60": 10.0,
                "ma20_above_ma60": True,
                "ma20_slope": 0.45,
                "drawdown_from_high": 8.5,
                "high20": 12.0,
                "low20": 9.8,
                "atr_14": 0.28,
                "eod_strong": True,
                "vol_trend_up": True,
                "is_positive_candle": True,
                "wyckoff_score": 60,
            },
            "000152.SZ": {
                "close": 11.0,
                "ma20": 10.8,
                "ma60": 10.0,
                "ma20_above_ma60": True,
                "ma20_slope": 0.18,
                "drawdown_from_high": 10.0,
                "high20": 12.2,
                "low20": 9.8,
                "atr_14": 0.22,
                "eod_strong": True,
                "vol_trend_up": False,
                "is_positive_candle": True,
                "wyckoff_score": 62,
            },
            "000153.SZ": {
                "close": 11.4,
                "ma20": 11.0,
                "ma60": 10.0,
                "ma20_above_ma60": True,
                "ma20_slope": 0.3,
                "drawdown_from_high": 5.5,
                "high20": 12.1,
                "low20": 9.8,
                "atr_14": 0.32,
                "eod_strong": True,
                "vol_trend_up": True,
                "is_positive_candle": True,
                "wyckoff_score": 58,
            },
        }

        result = main.select_longterm_pool(
            stocks,
            ma_dict,
            "20260603",
            financial_dict={
                "000151": {"roe": 9.0, "debt_ratio": 45.0},
                "000152": {"roe": 13.0, "debt_ratio": 36.0},
                "000153": {"roe": 7.0, "debt_ratio": 63.0},
            },
            industry_rs={"chem": 10.5, "auto": 6.0, "hot": 14.5},
            profit_growth_dict={
                "000151": {"netprofit_yoy": 68.0},
                "000152": {"netprofit_yoy": 12.0},
                "000153": {"netprofit_yoy": 4.0},
            },
            regime="BULL_TREND",
            score_threshold=0,
            longterm_profile="longterm_quality_trend_v7_winner_profile",
        )

        self.assertEqual(result["code"].tolist(), ["000151", "000152"])
        self.assertIn("winner_profile_score", result.columns)
        self.assertGreater(result.iloc[0]["winner_profile_score"], result.iloc[1]["winner_profile_score"])
        self.assertNotIn("000153", result["code"].tolist())

    @RETIRED_LONGTERM_PROFILE_TEST
    def test_longterm_quality_trend_v8_blocks_tail_risk_and_keeps_mid_stage_candidate(self):
        stocks = pd.DataFrame(
            [
                {
                    "code": "000161",
                    "name": "mid_stage",
                    "industry": "chem",
                    "main_net_inflow": 7600,
                    "turnover": 2.8,
                    "volume_ratio": 1.12,
                    "change": 1.1,
                    "amount": 280000,
                    "total_mv": 2800000,
                    "circ_mv": 2500000,
                    "pb": 2.6,
                    "pe_ttm": 27,
                    "ps_ttm": 2.1,
                    "dv_ratio": 0.9,
                },
                {
                    "code": "000162",
                    "name": "tail_risk",
                    "industry": "hot_tail",
                    "main_net_inflow": 8600,
                    "turnover": 5.9,
                    "volume_ratio": 1.52,
                    "change": 2.6,
                    "amount": 300000,
                    "total_mv": 2600000,
                    "circ_mv": 2400000,
                    "pb": 2.9,
                    "pe_ttm": 32,
                    "ps_ttm": 2.5,
                    "dv_ratio": 0.6,
                },
                {
                    "code": "000163",
                    "name": "weak_flow",
                    "industry": "steady",
                    "main_net_inflow": 500,
                    "turnover": 2.0,
                    "volume_ratio": 1.05,
                    "change": 0.4,
                    "amount": 220000,
                    "total_mv": 2200000,
                    "circ_mv": 2000000,
                    "pb": 2.2,
                    "pe_ttm": 24,
                    "ps_ttm": 1.8,
                    "dv_ratio": 1.2,
                },
            ]
        )
        ma_dict = {
            "000161.SZ": {
                "close": 10.8,
                "ma20": 10.6,
                "ma60": 10.0,
                "ma20_above_ma60": True,
                "ma20_slope": 0.36,
                "drawdown_from_high": 9.0,
                "high20": 11.8,
                "low20": 9.6,
                "atr_14": 0.24,
                "eod_strong": True,
                "vol_trend_up": True,
                "is_positive_candle": True,
                "wyckoff_score": 62,
            },
            "000162.SZ": {
                "close": 11.35,
                "ma20": 11.0,
                "ma60": 10.0,
                "ma20_above_ma60": True,
                "ma20_slope": 0.66,
                "drawdown_from_high": 6.0,
                "high20": 12.1,
                "low20": 9.9,
                "atr_14": 0.32,
                "eod_strong": True,
                "vol_trend_up": True,
                "is_positive_candle": True,
                "wyckoff_score": 58,
            },
            "000163.SZ": {
                "close": 10.7,
                "ma20": 10.5,
                "ma60": 10.0,
                "ma20_above_ma60": True,
                "ma20_slope": 0.24,
                "drawdown_from_high": 9.5,
                "high20": 11.7,
                "low20": 9.7,
                "atr_14": 0.22,
                "eod_strong": True,
                "vol_trend_up": False,
                "is_positive_candle": True,
                "wyckoff_score": 62,
            },
        }

        result = main.select_longterm_pool(
            stocks,
            ma_dict,
            "20260603",
            financial_dict={
                "000161": {"roe": 10.0, "debt_ratio": 45.0},
                "000162": {"roe": 10.0, "debt_ratio": 45.0},
                "000163": {"roe": 12.0, "debt_ratio": 36.0},
            },
            industry_rs={"chem": 9.8, "hot_tail": 13.6, "steady": 7.2},
            profit_growth_dict={
                "000161": {"netprofit_yoy": 46.0},
                "000162": {"netprofit_yoy": 48.0},
                "000163": {"netprofit_yoy": 18.0},
            },
            regime="BULL_TREND",
            score_threshold=0,
            longterm_profile="longterm_quality_trend_v8_timing_gate",
        )

        self.assertEqual(result["code"].tolist(), ["000161"])
        self.assertIn("v8_timing_reasons", result.columns)
        self.assertTrue(bool(result.iloc[0]["v8_timing_gate"]))

    @RETIRED_LONGTERM_PROFILE_TEST
    def test_longterm_quality_trend_v9_requires_active_market_admission(self):
        stocks = pd.DataFrame(
            [
                {
                    "code": "000171",
                    "name": "qualified",
                    "industry": "chem",
                    "main_net_inflow": 7600,
                    "turnover": 2.4,
                    "volume_ratio": 1.0,
                    "change": 1.0,
                    "amount": 260000,
                    "total_mv": 2600000,
                    "circ_mv": 2300000,
                    "pb": 2.4,
                    "pe_ttm": 24,
                    "ps_ttm": 2.0,
                    "dv_ratio": 1.0,
                },
            ]
        )
        ma_dict = {
            "000171.SZ": {
                "close": 10.8,
                "ma20": 10.6,
                "ma60": 10.0,
                "ma20_above_ma60": True,
                "ma20_slope": 0.36,
                "drawdown_from_high": 9.0,
                "high20": 11.8,
                "low20": 9.6,
                "atr_14": 0.24,
                "eod_strong": True,
                "vol_trend_up": True,
                "is_positive_candle": True,
                "wyckoff_score": 62,
            },
        }

        result = main.select_longterm_pool(
            stocks,
            ma_dict,
            "20260603",
            financial_dict={"000171": {"roe": 12.0, "debt_ratio": 42.0}},
            industry_rs={"chem": 8.8},
            profit_growth_dict={"000171": {"netprofit_yoy": 46.0}},
            regime="BULL_TREND",
            score_threshold=0,
            longterm_profile="longterm_quality_trend_v9_market_admission",
            macro_mode="cautious",
            macro_data={"price_vs_ma100": 1.5, "ma20_slope_pct": 0.15, "ma100_slope_pct": 0.05},
            regime_data={"price_vs_ma60_pct": 2.0, "ma60_slope_pct": 0.02},
        )

        self.assertTrue(result.empty)

    @RETIRED_LONGTERM_PROFILE_TEST
    def test_longterm_quality_trend_v9_keeps_dual_pool_candidate_in_active_market(self):
        stocks = pd.DataFrame(
            [
                {
                    "code": "000172",
                    "name": "qualified",
                    "industry": "chem",
                    "main_net_inflow": 7600,
                    "turnover": 2.4,
                    "volume_ratio": 1.0,
                    "change": 1.0,
                    "amount": 260000,
                    "total_mv": 2600000,
                    "circ_mv": 2300000,
                    "pb": 2.4,
                    "pe_ttm": 24,
                    "ps_ttm": 2.0,
                    "dv_ratio": 1.0,
                },
            ]
        )
        ma_dict = {
            "000172.SZ": {
                "close": 10.8,
                "ma20": 10.6,
                "ma60": 10.0,
                "ma20_above_ma60": True,
                "ma20_slope": 0.36,
                "drawdown_from_high": 9.0,
                "high20": 11.8,
                "low20": 9.6,
                "atr_14": 0.24,
                "eod_strong": True,
                "vol_trend_up": True,
                "is_positive_candle": True,
                "wyckoff_score": 62,
            },
        }

        result = main.select_longterm_pool(
            stocks,
            ma_dict,
            "20260603",
            financial_dict={"000172": {"roe": 12.0, "debt_ratio": 42.0}},
            industry_rs={"chem": 8.8},
            profit_growth_dict={"000172": {"netprofit_yoy": 46.0}},
            regime="BULL_TREND",
            score_threshold=0,
            longterm_profile="longterm_quality_trend_v9_market_admission",
            macro_mode="active",
            macro_data={"price_vs_ma100": 3.5, "ma20_slope_pct": 0.25, "ma100_slope_pct": 0.08},
            regime_data={"price_vs_ma60_pct": 2.0, "ma60_slope_pct": 0.03},
        )

        self.assertEqual(result["code"].tolist(), ["000172"])
        self.assertIn("market_admission", result.columns)
        self.assertTrue(bool(result.iloc[0]["market_admission"]))

    @RETIRED_LONGTERM_PROFILE_TEST
    def test_longterm_quality_trend_v9_blocks_low_roe_candidate_even_in_active_market(self):
        stocks = pd.DataFrame(
            [
                {
                    "code": "000173",
                    "name": "low_roe",
                    "industry": "chem",
                    "main_net_inflow": 7600,
                    "turnover": 2.4,
                    "volume_ratio": 1.0,
                    "change": 1.0,
                    "amount": 260000,
                    "total_mv": 2600000,
                    "circ_mv": 2300000,
                    "pb": 2.4,
                    "pe_ttm": 24,
                    "ps_ttm": 2.0,
                    "dv_ratio": 1.0,
                },
            ]
        )
        ma_dict = {
            "000173.SZ": {
                "close": 10.8,
                "ma20": 10.6,
                "ma60": 10.0,
                "ma20_above_ma60": True,
                "ma20_slope": 0.36,
                "drawdown_from_high": 9.0,
                "high20": 11.8,
                "low20": 9.6,
                "atr_14": 0.24,
                "eod_strong": True,
                "vol_trend_up": True,
                "is_positive_candle": True,
                "wyckoff_score": 62,
            },
        }

        result = main.select_longterm_pool(
            stocks,
            ma_dict,
            "20260603",
            financial_dict={"000173": {"roe": 3.0, "debt_ratio": 42.0}},
            industry_rs={"chem": 8.8},
            profit_growth_dict={"000173": {"netprofit_yoy": 46.0}},
            regime="BULL_TREND",
            score_threshold=0,
            longterm_profile="longterm_quality_trend_v9_market_admission",
            macro_mode="active",
            macro_data={"price_vs_ma100": 3.5, "ma20_slope_pct": 0.25, "ma100_slope_pct": 0.08},
            regime_data={"price_vs_ma60_pct": 2.0, "ma60_slope_pct": 0.03},
        )

        self.assertTrue(result.empty)

    @RETIRED_LONGTERM_PROFILE_TEST
    def test_longterm_quality_trend_v10_blocks_weak_quality_and_overheated_position(self):
        stocks = pd.DataFrame(
            [
                {
                    "code": "000181",
                    "name": "qualified_quality",
                    "industry": "steady",
                    "main_net_inflow": 3600,
                    "turnover": 2.4,
                    "volume_ratio": 1.0,
                    "change": 0.8,
                    "amount": 260000,
                    "total_mv": 1800000,
                    "circ_mv": 1500000,
                    "pb": 2.2,
                    "pe_ttm": 26,
                    "ps_ttm": 1.8,
                    "dv_ratio": 1.0,
                },
                {
                    "code": "000182",
                    "name": "weak_quality_trend",
                    "industry": "strong",
                    "main_net_inflow": 7600,
                    "turnover": 4.2,
                    "volume_ratio": 1.25,
                    "change": 1.8,
                    "amount": 280000,
                    "total_mv": 1600000,
                    "circ_mv": 1300000,
                    "pb": 4.1,
                    "pe_ttm": 66,
                    "ps_ttm": 4.6,
                    "dv_ratio": 0.2,
                },
                {
                    "code": "000183",
                    "name": "overheated_position",
                    "industry": "steady",
                    "main_net_inflow": 4200,
                    "turnover": 2.6,
                    "volume_ratio": 1.05,
                    "change": 1.0,
                    "amount": 270000,
                    "total_mv": 1700000,
                    "circ_mv": 1400000,
                    "pb": 2.4,
                    "pe_ttm": 28,
                    "ps_ttm": 2.0,
                    "dv_ratio": 0.8,
                },
            ]
        )
        ma_dict = {
            "000181.SZ": {
                "close": 10.8,
                "ma20": 10.6,
                "ma60": 10.0,
                "ma20_above_ma60": True,
                "ma20_slope": 0.28,
                "drawdown_from_high": 10.0,
                "high20": 12.0,
                "low20": 9.7,
                "atr_14": 0.24,
                "eod_strong": True,
                "vol_trend_up": False,
                "is_positive_candle": True,
                "wyckoff_score": 62,
            },
            "000182.SZ": {
                "close": 10.9,
                "ma20": 10.7,
                "ma60": 10.0,
                "ma20_above_ma60": True,
                "ma20_slope": 0.42,
                "drawdown_from_high": 8.0,
                "high20": 11.8,
                "low20": 9.7,
                "atr_14": 0.26,
                "eod_strong": True,
                "vol_trend_up": True,
                "is_positive_candle": True,
                "wyckoff_score": 60,
            },
            "000183.SZ": {
                "close": 11.3,
                "ma20": 10.9,
                "ma60": 10.0,
                "ma20_above_ma60": True,
                "ma20_slope": 0.30,
                "drawdown_from_high": 8.0,
                "high20": 12.3,
                "low20": 9.8,
                "atr_14": 0.25,
                "eod_strong": True,
                "vol_trend_up": False,
                "is_positive_candle": True,
                "wyckoff_score": 62,
            },
        }

        result = main.select_longterm_pool(
            stocks,
            ma_dict,
            "20260603",
            financial_dict={
                "000181": {"roe": 13.0, "debt_ratio": 42.0},
                "000182": {"roe": 6.5, "debt_ratio": 58.0},
                "000183": {"roe": 13.0, "debt_ratio": 42.0},
            },
            industry_rs={"steady": 7.5, "strong": 10.5},
            profit_growth_dict={
                "000181": {"netprofit_yoy": 40.0},
                "000182": {"netprofit_yoy": 10.0},
                "000183": {"netprofit_yoy": 40.0},
            },
            regime="BULL_TREND",
            score_threshold=0,
            longterm_profile="longterm_quality_trend_v10_quality_position_guard",
        )

        self.assertEqual(result["code"].tolist(), ["000181"])
        self.assertIn("v10_quality_position_guard", result.columns)
        self.assertTrue(bool(result.iloc[0]["v10_quality_position_guard"]))

    @RETIRED_LONGTERM_PROFILE_TEST
    def test_longterm_quality_trend_v10_relaxed_allows_hot_rs_but_blocks_shallow_pullback(self):
        stocks = pd.DataFrame(
            [
                {
                    "code": "000191",
                    "name": "hot_rs_quality",
                    "industry": "hot_rs",
                    "main_net_inflow": 5200,
                    "turnover": 4.8,
                    "volume_ratio": 1.55,
                    "change": 1.2,
                    "amount": 280000,
                    "total_mv": 1900000,
                    "circ_mv": 1600000,
                    "pb": 2.5,
                    "pe_ttm": 28,
                    "ps_ttm": 2.2,
                    "dv_ratio": 0.8,
                },
                {
                    "code": "000192",
                    "name": "shallow_pullback",
                    "industry": "steady",
                    "main_net_inflow": 3600,
                    "turnover": 2.0,
                    "volume_ratio": 0.9,
                    "change": 0.8,
                    "amount": 260000,
                    "total_mv": 1800000,
                    "circ_mv": 1500000,
                    "pb": 2.1,
                    "pe_ttm": 24,
                    "ps_ttm": 1.7,
                    "dv_ratio": 1.0,
                },
            ]
        )
        ma_dict = {
            "000191.SZ": {
                "close": 10.9,
                "ma20": 10.7,
                "ma60": 10.0,
                "ma20_above_ma60": True,
                "ma20_slope": 0.32,
                "drawdown_from_high": 8.0,
                "high20": 11.9,
                "low20": 9.8,
                "atr_14": 0.24,
                "eod_strong": True,
                "vol_trend_up": True,
                "is_positive_candle": True,
                "wyckoff_score": 64,
            },
            "000192.SZ": {
                "close": 10.6,
                "ma20": 10.4,
                "ma60": 10.0,
                "ma20_above_ma60": True,
                "ma20_slope": 0.25,
                "drawdown_from_high": 5.2,
                "high20": 11.2,
                "low20": 9.8,
                "atr_14": 0.22,
                "eod_strong": True,
                "vol_trend_up": False,
                "is_positive_candle": True,
                "wyckoff_score": 62,
            },
        }

        result = main.select_longterm_pool(
            stocks,
            ma_dict,
            "20260603",
            financial_dict={
                "000191": {"roe": 12.0, "debt_ratio": 42.0},
                "000192": {"roe": 13.0, "debt_ratio": 42.0},
            },
            industry_rs={"hot_rs": 13.5, "steady": 7.0},
            profit_growth_dict={
                "000191": {"netprofit_yoy": 36.0},
                "000192": {"netprofit_yoy": 40.0},
            },
            regime="BULL_TREND",
            score_threshold=0,
            longterm_profile="longterm_quality_trend_v10_relaxed_quality_position_guard",
        )

        self.assertEqual(result["code"].tolist(), ["000191"])
        self.assertIn("v10_relaxed_guard", result.columns)
        self.assertTrue(bool(result.iloc[0]["v10_relaxed_guard"]))

    def test_longterm_quality_trend_v11_balanced_keeps_quality_stock_when_breadth_is_weak(self):
        stocks = pd.DataFrame(
            [
                {
                    "code": "000201",
                    "name": "balanced_quality",
                    "industry": "steady",
                    "main_net_inflow": 4800,
                    "turnover": 3.0,
                    "volume_ratio": 1.2,
                    "change": 1.0,
                    "amount": 280000,
                    "total_mv": 1800000,
                    "circ_mv": 1500000,
                    "pb": 2.4,
                    "pe_ttm": 26,
                    "ps_ttm": 2.0,
                    "dv_ratio": 0.9,
                },
                {
                    "code": "000202",
                    "name": "low_quality",
                    "industry": "steady",
                    "main_net_inflow": 2200,
                    "turnover": 3.4,
                    "volume_ratio": 1.3,
                    "change": 0.8,
                    "amount": 260000,
                    "total_mv": 5000000,
                    "circ_mv": 4500000,
                    "pb": 4.3,
                    "pe_ttm": 72,
                    "ps_ttm": 4.8,
                    "dv_ratio": 0.1,
                },
                {
                    "code": "000203",
                    "name": "weak_breadth_1",
                    "industry": "weak",
                    "main_net_inflow": 500,
                    "turnover": 1.2,
                    "volume_ratio": 0.8,
                    "change": -0.6,
                    "amount": 150000,
                    "total_mv": 1200000,
                    "circ_mv": 1000000,
                    "pb": 2.0,
                    "pe_ttm": 22,
                    "ps_ttm": 1.7,
                    "dv_ratio": 1.0,
                },
                {
                    "code": "000204",
                    "name": "weak_breadth_2",
                    "industry": "weak",
                    "main_net_inflow": 400,
                    "turnover": 1.1,
                    "volume_ratio": 0.7,
                    "change": -0.8,
                    "amount": 140000,
                    "total_mv": 1100000,
                    "circ_mv": 900000,
                    "pb": 2.0,
                    "pe_ttm": 22,
                    "ps_ttm": 1.7,
                    "dv_ratio": 1.0,
                },
            ]
        )
        ma_dict = {
            "000201.SZ": {
                "close": 10.9,
                "ma20": 10.7,
                "ma60": 10.0,
                "ma20_above_ma60": True,
                "ma20_slope": 0.30,
                "drawdown_from_high": 8.0,
                "high20": 11.9,
                "low20": 9.8,
                "atr_14": 0.24,
                "eod_strong": True,
                "vol_trend_up": True,
                "is_positive_candle": True,
                "wyckoff_score": 64,
            },
            "000202.SZ": {
                "close": 10.8,
                "ma20": 10.6,
                "ma60": 10.0,
                "ma20_above_ma60": True,
                "ma20_slope": 0.26,
                "drawdown_from_high": 8.0,
                "high20": 11.8,
                "low20": 9.8,
                "atr_14": 0.24,
                "eod_strong": True,
                "vol_trend_up": True,
                "is_positive_candle": True,
                "wyckoff_score": 62,
            },
            "000203.SZ": {
                "close": 9.2,
                "ma20": 9.3,
                "ma60": 10.0,
                "ma20_above_ma60": False,
                "ma20_slope": -0.10,
                "drawdown_from_high": 18.0,
                "high20": 11.2,
                "low20": 9.0,
                "atr_14": 0.24,
            },
            "000204.SZ": {
                "close": 9.1,
                "ma20": 9.2,
                "ma60": 10.0,
                "ma20_above_ma60": False,
                "ma20_slope": -0.12,
                "drawdown_from_high": 19.0,
                "high20": 11.2,
                "low20": 9.0,
                "atr_14": 0.24,
            },
        }

        result = main.select_longterm_pool(
            stocks,
            ma_dict,
            "20260603",
            financial_dict={
                "000201": {"roe": 13.0, "debt_ratio": 42.0},
                "000202": {"roe": 6.2, "debt_ratio": 60.0},
                "000203": {"roe": 8.0, "debt_ratio": 50.0},
                "000204": {"roe": 8.0, "debt_ratio": 50.0},
            },
            industry_rs={"steady": 8.0, "weak": -4.0},
            profit_growth_dict={
                "000201": {"netprofit_yoy": 42.0},
                "000202": {"netprofit_yoy": 5.0},
                "000203": {"netprofit_yoy": 10.0},
                "000204": {"netprofit_yoy": 10.0},
            },
            regime="BULL_TREND",
            score_threshold=0,
            longterm_profile="longterm_quality_trend_v11_balanced_pool",
        )

        self.assertEqual(result["code"].tolist(), ["000201"])
        self.assertIn("v11_balanced_guard", result.columns)
        self.assertTrue(bool(result.iloc[0]["v11_balanced_guard"]))

        overheated = main.select_longterm_pool(
            stocks,
            ma_dict,
            "20260603",
            financial_dict={
                "000201": {"roe": 13.0, "debt_ratio": 42.0},
                "000202": {"roe": 6.2, "debt_ratio": 60.0},
                "000203": {"roe": 8.0, "debt_ratio": 50.0},
                "000204": {"roe": 8.0, "debt_ratio": 50.0},
            },
            industry_rs={"steady": 8.0, "weak": -4.0},
            profit_growth_dict={
                "000201": {"netprofit_yoy": 42.0},
                "000202": {"netprofit_yoy": 5.0},
                "000203": {"netprofit_yoy": 10.0},
                "000204": {"netprofit_yoy": 10.0},
            },
            regime="BULL_TREND",
            score_threshold=0,
            longterm_profile="longterm_quality_trend_v12_base_reset_pool",
            macro_data={"price_vs_ma100": 12.0, "ma20_slope_pct": 0.5},
        )
        self.assertTrue(overheated.empty)

        base_reset = main.select_longterm_pool(
            stocks,
            ma_dict,
            "20260603",
            financial_dict={
                "000201": {"roe": 13.0, "debt_ratio": 42.0},
                "000202": {"roe": 6.2, "debt_ratio": 60.0},
                "000203": {"roe": 8.0, "debt_ratio": 50.0},
                "000204": {"roe": 8.0, "debt_ratio": 50.0},
            },
            industry_rs={"steady": 8.0, "weak": -4.0},
            profit_growth_dict={
                "000201": {"netprofit_yoy": 42.0},
                "000202": {"netprofit_yoy": 5.0},
                "000203": {"netprofit_yoy": 10.0},
                "000204": {"netprofit_yoy": 10.0},
            },
            regime="BULL_TREND",
            score_threshold=0,
            longterm_profile="longterm_quality_trend_v12_base_reset_pool",
            macro_data={"price_vs_ma100": 3.0, "ma20_slope_pct": 0.5},
        )
        self.assertEqual(base_reset["code"].tolist(), ["000201"])

    def test_longterm_quality_trend_v13_observation_pool_requires_balanced_quality(self):
        stocks = pd.DataFrame(
            [
                {
                    "code": "000301",
                    "name": "balanced_quality",
                    "industry": "steady",
                    "main_net_inflow": 1800,
                    "turnover": 2.4,
                    "volume_ratio": 1.0,
                    "change": 0.2,
                    "amount": 180000,
                    "total_mv": 680000,
                    "circ_mv": 560000,
                    "pb": 2.4,
                    "pe_ttm": 32,
                    "ps_ttm": 2.4,
                    "dv_ratio": 0.8,
                },
                {
                    "code": "000302",
                    "name": "too_hot",
                    "industry": "hot",
                    "main_net_inflow": 5000,
                    "turnover": 7.8,
                    "volume_ratio": 2.2,
                    "change": 3.0,
                    "amount": 240000,
                    "total_mv": 900000,
                    "circ_mv": 760000,
                    "pb": 3.2,
                    "pe_ttm": 48,
                    "ps_ttm": 3.4,
                    "dv_ratio": 0.3,
                },
                {
                    "code": "000303",
                    "name": "missing_value",
                    "industry": "steady",
                    "main_net_inflow": 1200,
                    "turnover": 2.0,
                    "volume_ratio": 1.0,
                    "change": 0.1,
                    "amount": 150000,
                    "total_mv": 500000,
                    "circ_mv": 420000,
                    "pb": None,
                    "pe_ttm": None,
                    "ps_ttm": None,
                    "dv_ratio": 0.5,
                },
                {
                    "code": "000304",
                    "name": "weak_growth",
                    "industry": "steady",
                    "main_net_inflow": 1400,
                    "turnover": 2.2,
                    "volume_ratio": 1.0,
                    "change": 0.1,
                    "amount": 150000,
                    "total_mv": 550000,
                    "circ_mv": 450000,
                    "pb": 2.0,
                    "pe_ttm": 28,
                    "ps_ttm": 2.0,
                    "dv_ratio": 0.5,
                },
            ]
        )
        ma_dict = {
            "000301.SZ": {
                "close": 10.8,
                "ma20": 10.6,
                "ma60": 10.0,
                "ma20_above_ma60": True,
                "ma20_slope": 0.12,
                "drawdown_from_high": 12.0,
                "vol_accelerating": False,
                "eod_strong": False,
                "vol_trend_up": False,
                "is_positive_candle": True,
                "wyckoff_score": 62,
                "high20": 12.5,
                "low20": 10.0,
                "atr_14": 0.22,
            },
            "000302.SZ": {
                "close": 13.5,
                "ma20": 12.8,
                "ma60": 10.0,
                "ma20_above_ma60": True,
                "ma20_slope": 0.42,
                "drawdown_from_high": 4.0,
                "vol_accelerating": True,
                "eod_strong": True,
                "vol_trend_up": True,
                "is_positive_candle": True,
                "wyckoff_score": 76,
                "high20": 14.0,
                "low20": 10.5,
                "atr_14": 0.3,
            },
            "000303.SZ": {
                "close": 10.5,
                "ma20": 10.3,
                "ma60": 10.0,
                "ma20_above_ma60": True,
                "ma20_slope": 0.1,
                "drawdown_from_high": 10.0,
                "vol_accelerating": False,
                "eod_strong": False,
                "vol_trend_up": False,
                "is_positive_candle": True,
                "wyckoff_score": 60,
                "high20": 12.0,
                "low20": 9.8,
                "atr_14": 0.2,
            },
            "000304.SZ": {
                "close": 10.7,
                "ma20": 10.5,
                "ma60": 10.0,
                "ma20_above_ma60": True,
                "ma20_slope": 0.11,
                "drawdown_from_high": 11.0,
                "vol_accelerating": False,
                "eod_strong": False,
                "vol_trend_up": False,
                "is_positive_candle": True,
                "wyckoff_score": 60,
                "high20": 12.0,
                "low20": 9.8,
                "atr_14": 0.2,
            },
        }

        result = main.select_longterm_pool(
            stocks,
            ma_dict,
            "20260603",
            financial_dict={
                "000301": {"roe": 11.0, "debt_ratio": 42.0},
                "000302": {"roe": 24.0, "debt_ratio": 30.0},
                "000303": {"roe": 12.0, "debt_ratio": 40.0},
                "000304": {"roe": 10.0, "debt_ratio": 38.0},
            },
            industry_rs={"steady": 6.0, "hot": 19.0},
            profit_growth_dict={
                "000301": {"netprofit_yoy": 22.0},
                "000302": {"netprofit_yoy": 80.0},
                "000303": {"netprofit_yoy": 25.0},
                "000304": {"netprofit_yoy": 2.0},
            },
            regime="BULL_TREND",
            score_threshold=0,
            longterm_profile="longterm_quality_trend_v13_observation_pool",
            macro_data={"price_vs_ma100": 6.0, "ma20_slope_pct": 1.0},
        )

        self.assertEqual(result["code"].tolist(), ["000301"])
        self.assertEqual(result.iloc[0]["pool_type"], "observation_quality")
        self.assertGreaterEqual(result.iloc[0]["pool_rank_score"], 75.0)

    def test_longterm_quality_trend_v14_large_quiet_pool_requires_macro_and_largecap(self):
        stocks = pd.DataFrame(
            [
                {
                    "code": "000401",
                    "name": "large_quiet",
                    "industry": "steady",
                    "main_net_inflow": 1800,
                    "turnover": 2.1,
                    "volume_ratio": 0.9,
                    "change": 0.2,
                    "amount": 220000,
                    "total_mv": 1200000,
                    "circ_mv": 980000,
                    "pb": 2.4,
                    "pe_ttm": 32,
                    "ps_ttm": 2.4,
                    "dv_ratio": 0.8,
                },
                {
                    "code": "000402",
                    "name": "small_quality",
                    "industry": "steady",
                    "main_net_inflow": 1800,
                    "turnover": 2.0,
                    "volume_ratio": 0.9,
                    "change": 0.2,
                    "amount": 180000,
                    "total_mv": 500000,
                    "circ_mv": 420000,
                    "pb": 2.0,
                    "pe_ttm": 28,
                    "ps_ttm": 2.0,
                    "dv_ratio": 0.5,
                },
                {
                    "code": "000403",
                    "name": "too_shallow",
                    "industry": "steady",
                    "main_net_inflow": 1800,
                    "turnover": 2.0,
                    "volume_ratio": 0.9,
                    "change": 0.2,
                    "amount": 210000,
                    "total_mv": 1200000,
                    "circ_mv": 980000,
                    "pb": 2.0,
                    "pe_ttm": 28,
                    "ps_ttm": 2.0,
                    "dv_ratio": 0.5,
                },
            ]
        )
        ma_dict = {
            "000401.SZ": {
                "close": 10.7,
                "ma20": 10.5,
                "ma60": 10.0,
                "ma20_above_ma60": True,
                "ma20_slope": 0.12,
                "drawdown_from_high": 10.0,
                "vol_accelerating": False,
                "eod_strong": False,
                "vol_trend_up": False,
                "is_positive_candle": True,
                "wyckoff_score": 62,
                "high20": 12.0,
                "low20": 9.8,
                "atr_14": 0.2,
            },
            "000402.SZ": {
                "close": 10.7,
                "ma20": 10.5,
                "ma60": 10.0,
                "ma20_above_ma60": True,
                "ma20_slope": 0.12,
                "drawdown_from_high": 10.0,
                "vol_accelerating": False,
                "eod_strong": False,
                "vol_trend_up": False,
                "is_positive_candle": True,
                "wyckoff_score": 62,
                "high20": 12.0,
                "low20": 9.8,
                "atr_14": 0.2,
            },
            "000403.SZ": {
                "close": 10.7,
                "ma20": 10.5,
                "ma60": 10.0,
                "ma20_above_ma60": True,
                "ma20_slope": 0.12,
                "drawdown_from_high": 6.0,
                "vol_accelerating": False,
                "eod_strong": False,
                "vol_trend_up": False,
                "is_positive_candle": True,
                "wyckoff_score": 62,
                "high20": 12.0,
                "low20": 9.8,
                "atr_14": 0.2,
            },
        }
        common_fin = {
            "000401": {"roe": 11.0, "debt_ratio": 42.0},
            "000402": {"roe": 11.0, "debt_ratio": 42.0},
            "000403": {"roe": 11.0, "debt_ratio": 42.0},
        }
        common_growth = {
            "000401": {"netprofit_yoy": 22.0},
            "000402": {"netprofit_yoy": 22.0},
            "000403": {"netprofit_yoy": 22.0},
        }

        weak_macro = main.select_longterm_pool(
            stocks,
            ma_dict,
            "20260603",
            financial_dict=common_fin,
            industry_rs={"steady": 6.0},
            profit_growth_dict=common_growth,
            regime="BULL_TREND",
            score_threshold=0,
            longterm_profile="longterm_quality_trend_v14_large_quiet_pool",
            macro_data={"price_vs_ma100": -0.5, "ma100_slope_pct": 0.3},
        )
        self.assertTrue(weak_macro.empty)

        result = main.select_longterm_pool(
            stocks,
            ma_dict,
            "20260603",
            financial_dict=common_fin,
            industry_rs={"steady": 6.0},
            profit_growth_dict=common_growth,
            regime="BULL_TREND",
            score_threshold=0,
            longterm_profile="longterm_quality_trend_v14_large_quiet_pool",
            macro_data={"price_vs_ma100": 3.0, "ma100_slope_pct": 0.3, "ma20_slope_pct": 1.0},
        )

        self.assertEqual(result["code"].tolist(), ["000401"])
        self.assertEqual(result.iloc[0]["pool_type"], "large_quiet_observation")

    def test_longterm_quality_trend_v15_confirmed_bull_pool_requires_durable_index_trend(self):
        stocks = pd.DataFrame(
            [
                {
                    "code": "000501",
                    "name": "confirmed_bull",
                    "industry": "steady",
                    "main_net_inflow": 2200,
                    "turnover": 2.0,
                    "volume_ratio": 0.8,
                    "change": 0.2,
                    "amount": 220000,
                    "total_mv": 1500000,
                    "circ_mv": 1200000,
                    "pb": 2.2,
                    "pe_ttm": 26,
                    "ps_ttm": 2.0,
                    "dv_ratio": 1.0,
                },
            ]
        )
        ma_dict = {
            "000501.SZ": {
                "close": 10.7,
                "ma20": 10.5,
                "ma60": 10.0,
                "ma20_above_ma60": True,
                "ma20_slope": 0.12,
                "drawdown_from_high": 10.0,
                "vol_accelerating": False,
                "eod_strong": False,
                "vol_trend_up": False,
                "is_positive_candle": True,
                "wyckoff_score": 62,
                "high20": 12.0,
                "low20": 9.8,
                "atr_14": 0.2,
            },
        }
        common_fin = {"000501": {"roe": 12.0, "debt_ratio": 38.0}}
        common_growth = {"000501": {"netprofit_yoy": 26.0}}

        weak_medium_trend = main.select_longterm_pool(
            stocks,
            ma_dict,
            "20260603",
            financial_dict=common_fin,
            industry_rs={"steady": 6.0},
            profit_growth_dict=common_growth,
            regime="BULL_TREND",
            score_threshold=0,
            longterm_profile="longterm_quality_trend_v15_confirmed_bull_pool",
            macro_data={
                "price_vs_ma100": 3.0,
                "ma100_slope_pct": 0.3,
                "ma20_slope_pct": 1.0,
                "idx_ret_120d": 12.0,
            },
        )
        self.assertTrue(weak_medium_trend.empty)

        result = main.select_longterm_pool(
            stocks,
            ma_dict,
            "20260603",
            financial_dict=common_fin,
            industry_rs={"steady": 6.0},
            profit_growth_dict=common_growth,
            regime="BULL_TREND",
            score_threshold=0,
            longterm_profile="longterm_quality_trend_v15_confirmed_bull_pool",
            macro_data={
                "price_vs_ma100": 6.0,
                "ma100_slope_pct": 0.7,
                "ma20_slope_pct": 1.0,
                "idx_ret_120d": 12.0,
            },
        )

        self.assertEqual(result["code"].tolist(), ["000501"])
        self.assertEqual(result.iloc[0]["pool_type"], "confirmed_bull_observation")

    def test_longterm_quality_lifecycle_v16_elastic_branch_rejects_crowded_expensive_losers(self):
        stocks = pd.DataFrame(
            [
                {
                    "code": "000151",
                    "name": "elastic_quality",
                    "industry": "growth",
                    "main_net_inflow": 1500,
                    "turnover": 3.0,
                    "volume_ratio": 1.0,
                    "change": 0.2,
                    "amount": 180000,
                    "total_mv": 1200000,
                    "circ_mv": 900000,
                    "pb": 3.2,
                    "pe_ttm": 35,
                    "ps_ttm": 3.0,
                    "dv_ratio": 0.6,
                },
                {
                    "code": "000152",
                    "name": "crowded_expensive",
                    "industry": "growth",
                    "main_net_inflow": 3000,
                    "turnover": 8.5,
                    "volume_ratio": 2.4,
                    "change": 0.5,
                    "amount": 260000,
                    "total_mv": 2200000,
                    "circ_mv": 1800000,
                    "pb": 9.5,
                    "pe_ttm": 160,
                    "ps_ttm": 14.0,
                    "dv_ratio": 0.0,
                },
            ]
        )
        ma_dict = {
            "000151.SZ": {
                "close": 12.0,
                "ma20": 12.2,
                "ma60": 11.2,
                "ma20_above_ma60": True,
                "ma20_slope": 0.12,
                "drawdown_from_high": 11.0,
                "vol_accelerating": False,
                "eod_strong": False,
                "vol_trend_up": False,
                "is_positive_candle": True,
                "wyckoff_score": 55,
                "high20": 13.5,
                "low20": 10.9,
                "atr_14": 0.35,
            },
            "000152.SZ": {
                "close": 18.0,
                "ma20": 18.5,
                "ma60": 16.5,
                "ma20_above_ma60": True,
                "ma20_slope": 0.18,
                "drawdown_from_high": 10.0,
                "vol_accelerating": True,
                "eod_strong": True,
                "vol_trend_up": True,
                "is_positive_candle": True,
                "wyckoff_score": 70,
                "high20": 20.0,
                "low20": 15.8,
                "atr_14": 0.6,
            },
        }

        result = main.select_longterm_pool(
            stocks,
            ma_dict,
            "20260603",
            financial_dict={
                "000151": {"roe": 10.0, "debt_ratio": 45.0},
                "000152": {"roe": 18.0, "debt_ratio": 35.0},
            },
            industry_rs={"growth": 8.0},
            profit_growth_dict={
                "000151": {"netprofit_yoy": 12.0},
                "000152": {"netprofit_yoy": 80.0},
            },
            regime="BULL_TREND",
            score_threshold=0,
            longterm_profile="longterm_quality_lifecycle_v16",
            macro_data={"price_vs_ma100": 4.0, "ma100_slope_pct": 0.3, "idx_ret_120d": 8.0},
        )

        self.assertEqual(result["code"].tolist(), ["000151"])
        self.assertEqual(result.iloc[0]["pool_type"], "elastic_quality_lifecycle")
        self.assertTrue(bool(result.iloc[0]["v16_lifecycle_guard"]))

    def test_longterm_quality_lifecycle_v16_defensive_branch_requires_defensive_quality_in_weak_market(self):
        stocks = pd.DataFrame(
            [
                {
                    "code": "000161",
                    "name": "defensive_quality",
                    "industry": "defensive",
                    "main_net_inflow": 800,
                    "turnover": 1.5,
                    "volume_ratio": 0.8,
                    "change": 0.1,
                    "amount": 160000,
                    "total_mv": 1500000,
                    "circ_mv": 1300000,
                    "pb": 2.1,
                    "pe_ttm": 28,
                    "ps_ttm": 2.0,
                    "dv_ratio": 1.6,
                },
                {
                    "code": "000162",
                    "name": "weak_elastic",
                    "industry": "defensive",
                    "main_net_inflow": 1600,
                    "turnover": 4.8,
                    "volume_ratio": 1.4,
                    "change": 0.1,
                    "amount": 140000,
                    "total_mv": 350000,
                    "circ_mv": 300000,
                    "pb": 4.5,
                    "pe_ttm": 65,
                    "ps_ttm": 5.0,
                    "dv_ratio": 0.2,
                },
            ]
        )
        ma_dict = {
            "000161.SZ": {
                "close": 10.0,
                "ma20": 10.1,
                "ma60": 9.8,
                "ma20_above_ma60": True,
                "ma20_slope": -0.02,
                "drawdown_from_high": 9.0,
                "vol_accelerating": False,
                "eod_strong": False,
                "vol_trend_up": False,
                "is_positive_candle": True,
                "wyckoff_score": 52,
                "high20": 11.0,
                "low20": 9.5,
                "atr_14": 0.2,
            },
            "000162.SZ": {
                "close": 8.0,
                "ma20": 8.2,
                "ma60": 7.6,
                "ma20_above_ma60": True,
                "ma20_slope": 0.12,
                "drawdown_from_high": 10.0,
                "vol_accelerating": True,
                "eod_strong": True,
                "vol_trend_up": True,
                "is_positive_candle": True,
                "wyckoff_score": 65,
                "high20": 9.0,
                "low20": 7.4,
                "atr_14": 0.28,
            },
        }

        result = main.select_longterm_pool(
            stocks,
            ma_dict,
            "20260603",
            financial_dict={
                "000161": {"roe": 8.0, "debt_ratio": 50.0},
                "000162": {"roe": 9.0, "debt_ratio": 45.0},
            },
            industry_rs={"defensive": 0.0},
            profit_growth_dict={
                "000161": {"netprofit_yoy": 5.0},
                "000162": {"netprofit_yoy": 20.0},
            },
            regime="BULL_PULLBACK",
            score_threshold=0,
            longterm_profile="longterm_quality_lifecycle_v16",
            macro_data={"price_vs_ma100": -1.0, "ma100_slope_pct": 0.05, "idx_ret_120d": -2.0},
        )

        self.assertEqual(result["code"].tolist(), ["000161"])
        self.assertEqual(result.iloc[0]["pool_type"], "defensive_quality_lifecycle")
        self.assertTrue(bool(result.iloc[0]["v16_lifecycle_guard"]))

    def test_longterm_quality_lifecycle_v17_blocks_late_cycle_momentum_decay(self):
        stocks = pd.DataFrame(
            [
                {
                    "code": "000171",
                    "name": "late_cycle_quality",
                    "industry": "growth",
                    "main_net_inflow": 1500,
                    "turnover": 3.0,
                    "volume_ratio": 1.0,
                    "change": 0.2,
                    "amount": 180000,
                    "total_mv": 1200000,
                    "circ_mv": 900000,
                    "pb": 3.2,
                    "pe_ttm": 35,
                    "ps_ttm": 3.0,
                    "dv_ratio": 0.6,
                },
            ]
        )
        ma_dict = {
            "000171.SZ": {
                "close": 12.0,
                "ma20": 12.2,
                "ma60": 11.2,
                "ma20_above_ma60": True,
                "ma20_slope": 0.12,
                "drawdown_from_high": 11.0,
                "vol_accelerating": False,
                "eod_strong": False,
                "vol_trend_up": False,
                "is_positive_candle": True,
                "wyckoff_score": 55,
                "high20": 13.5,
                "low20": 10.9,
                "atr_14": 0.35,
            },
        }

        result = main.select_longterm_pool(
            stocks,
            ma_dict,
            "20260603",
            financial_dict={"000171": {"roe": 10.0, "debt_ratio": 45.0}},
            industry_rs={"growth": 8.0},
            profit_growth_dict={"000171": {"netprofit_yoy": 12.0}},
            regime="BULL_TREND",
            score_threshold=0,
            longterm_profile="longterm_quality_lifecycle_v17_late_cycle_guard",
            macro_data={
                "price_vs_ma100": 3.0,
                "ma100_slope_pct": 0.5,
                "ma20_slope_pct": 0.6,
                "idx_ret_60d": 2.5,
                "idx_ret_120d": 17.0,
            },
        )

        self.assertTrue(result.empty)

    def test_longterm_quality_lifecycle_v18_requires_market_sync(self):
        stocks = pd.DataFrame(
            [
                {
                    "code": "000181",
                    "name": "quality_but_unsynced_market",
                    "industry": "growth",
                    "main_net_inflow": 1500,
                    "turnover": 3.0,
                    "volume_ratio": 1.0,
                    "change": 0.2,
                    "amount": 180000,
                    "total_mv": 1200000,
                    "circ_mv": 900000,
                    "pb": 3.2,
                    "pe_ttm": 35,
                    "ps_ttm": 3.0,
                    "dv_ratio": 0.6,
                },
            ]
        )
        ma_dict = {
            "000181.SZ": {
                "close": 12.0,
                "ma20": 12.2,
                "ma60": 11.2,
                "ma20_above_ma60": True,
                "ma20_slope": 0.12,
                "drawdown_from_high": 11.0,
                "vol_accelerating": False,
                "eod_strong": False,
                "vol_trend_up": False,
                "is_positive_candle": True,
                "wyckoff_score": 55,
                "high20": 13.5,
                "low20": 10.9,
                "atr_14": 0.35,
            },
        }

        result = main.select_longterm_pool(
            stocks,
            ma_dict,
            "20260603",
            financial_dict={"000181": {"roe": 10.0, "debt_ratio": 45.0}},
            industry_rs={"growth": 8.0},
            profit_growth_dict={"000181": {"netprofit_yoy": 12.0}},
            regime="BULL_TREND",
            score_threshold=0,
            longterm_profile="longterm_quality_lifecycle_v18_market_sync",
            macro_data={
                "price_vs_ma100": 3.0,
                "ma100_slope_pct": 0.2,
                "ma20_slope_pct": 0.5,
                "idx_ret_60d": 2.0,
                "idx_ret_120d": 8.0,
            },
        )

        self.assertTrue(result.empty)

    def test_longterm_quality_lifecycle_v18_allows_synced_market_quality_candidate(self):
        stocks = pd.DataFrame(
            [
                {
                    "code": "000182",
                    "name": "quality_synced_market",
                    "industry": "growth",
                    "main_net_inflow": 1500,
                    "turnover": 3.0,
                    "volume_ratio": 1.0,
                    "change": 0.2,
                    "amount": 180000,
                    "total_mv": 1200000,
                    "circ_mv": 900000,
                    "pb": 3.2,
                    "pe_ttm": 35,
                    "ps_ttm": 3.0,
                    "dv_ratio": 0.6,
                },
            ]
        )
        ma_dict = {
            "000182.SZ": {
                "close": 12.0,
                "ma20": 12.2,
                "ma60": 11.2,
                "ma20_above_ma60": True,
                "ma20_slope": 0.12,
                "drawdown_from_high": 11.0,
                "vol_accelerating": False,
                "eod_strong": False,
                "vol_trend_up": False,
                "is_positive_candle": True,
                "wyckoff_score": 55,
                "high20": 13.5,
                "low20": 10.9,
                "atr_14": 0.35,
            },
        }

        result = main.select_longterm_pool(
            stocks,
            ma_dict,
            "20260603",
            financial_dict={"000182": {"roe": 10.0, "debt_ratio": 45.0}},
            industry_rs={"growth": 8.0},
            profit_growth_dict={"000182": {"netprofit_yoy": 12.0}},
            regime="BULL_TREND",
            score_threshold=0,
            longterm_profile="longterm_quality_lifecycle_v18_market_sync",
            macro_data={
                "price_vs_ma100": 3.0,
                "ma100_slope_pct": 0.3,
                "ma20_slope_pct": 0.5,
                "idx_ret_60d": 6.0,
                "idx_ret_120d": 8.0,
            },
        )

        self.assertEqual(result["code"].tolist(), ["000182"])
        self.assertEqual(result.iloc[0]["pool_type"], "elastic_quality_lifecycle")
        self.assertTrue(bool(result.iloc[0]["v16_lifecycle_guard"]))


if __name__ == "__main__":
    unittest.main()
