import unittest

import pandas as pd

from research.dragon_page_backtest import (
    DragonPageBacktestConfig,
    build_page_display,
    summarize_page_display,
)


class DragonPageBacktestTest(unittest.TestCase):
    def test_page_display_filters_hidden_risk_and_does_not_rank_by_future_return(self):
        events = pd.DataFrame(
            [
                {
                    "trade_date": "20260620",
                    "buy_date": "20260621",
                    "ts_code": "000001.SZ",
                    "name": "强势二板",
                    "profit_rule_v5_3d": "three_day_prev_second",
                    "profit_rule_v4": "aggressive_base",
                    "profit_rule_v3": "aggressive_prev_second",
                    "source": "previous_pool",
                    "limit_days": 2,
                    "turnover_rate": 6,
                    "open_count": 1,
                    "first_limit_time": "09:45",
                    "theme_name": "主线",
                    "theme_state": "主线确认",
                    "theme_score": 60,
                    "dragon_score": 80,
                    "lhb_net_buy": 1000000,
                    "lhb_turnover": 10000000,
                    "lhb_reason": "",
                    "is_sub_new": False,
                    "ret_1d_pct": 1,
                    "ret_3d_pct": 3,
                    "ret_5d_pct": 5,
                    "mfe_5d_pct": 8,
                    "mae_5d_pct": -4,
                    "next_limit_up": False,
                    "gap_fail": False,
                },
                {
                    "trade_date": "20260620",
                    "buy_date": "20260621",
                    "ts_code": "000002.SZ",
                    "name": "未来暴涨陷阱",
                    "profit_rule_v5_3d": "three_day_trap",
                    "profit_rule_v4": "trap_avoid",
                    "profit_rule_v3": "trap_low_turnover",
                    "source": "zt_pool",
                    "limit_days": 1,
                    "turnover_rate": 2,
                    "open_count": 0,
                    "first_limit_time": "09:35",
                    "theme_name": "弱分支",
                    "theme_state": "",
                    "theme_score": 20,
                    "dragon_score": 90,
                    "lhb_net_buy": 0,
                    "lhb_turnover": 0,
                    "lhb_reason": "",
                    "is_sub_new": False,
                    "ret_1d_pct": 10,
                    "ret_3d_pct": 30,
                    "ret_5d_pct": 40,
                    "mfe_5d_pct": 45,
                    "mae_5d_pct": -1,
                    "next_limit_up": True,
                    "gap_fail": False,
                },
                {
                    "trade_date": "20260620",
                    "buy_date": "20260621",
                    "ts_code": "000003.SZ",
                    "name": "高收益但弱排序",
                    "profit_rule_v5_3d": "three_day_prev_second",
                    "profit_rule_v4": "aggressive_base",
                    "profit_rule_v3": "aggressive_prev_second",
                    "source": "previous_pool",
                    "limit_days": 2,
                    "turnover_rate": 18,
                    "open_count": 6,
                    "first_limit_time": "14:30",
                    "theme_name": "主线",
                    "theme_state": "主线确认",
                    "theme_score": 35,
                    "dragon_score": 50,
                    "lhb_net_buy": 0,
                    "lhb_turnover": 0,
                    "lhb_reason": "",
                    "is_sub_new": False,
                    "ret_1d_pct": 8,
                    "ret_3d_pct": 20,
                    "ret_5d_pct": 25,
                    "mfe_5d_pct": 30,
                    "mae_5d_pct": -2,
                    "next_limit_up": True,
                    "gap_fail": False,
                },
                {
                    "trade_date": "20260620",
                    "buy_date": "20260621",
                    "ts_code": "000001.SZ",
                    "name": "强势二板重复来源",
                    "profit_rule_v5_3d": "three_day_observe",
                    "profit_rule_v4": "observe_v4",
                    "profit_rule_v3": "observe_v3",
                    "source": "strong_pool",
                    "limit_days": 2,
                    "turnover_rate": 6,
                    "open_count": 1,
                    "first_limit_time": "09:45",
                    "theme_name": "主线",
                    "theme_state": "主线确认",
                    "theme_score": 60,
                    "dragon_score": 80,
                    "lhb_net_buy": 1000000,
                    "lhb_turnover": 10000000,
                    "lhb_reason": "",
                    "is_sub_new": False,
                    "ret_1d_pct": 1,
                    "ret_3d_pct": 3,
                    "ret_5d_pct": 5,
                    "mfe_5d_pct": 8,
                    "mae_5d_pct": -4,
                    "next_limit_up": False,
                    "gap_fail": False,
                },
            ]
        )

        displayed = build_page_display(events, DragonPageBacktestConfig(max_core=2, max_aggressive=0, max_watch=0))

        self.assertEqual(set(displayed["ts_code"]), {"000001.SZ", "000003.SZ"})
        self.assertNotIn("000002.SZ", set(displayed["ts_code"]))
        self.assertEqual(displayed["ts_code"].tolist().count("000001.SZ"), 1)
        self.assertEqual(displayed.iloc[0]["ts_code"], "000001.SZ")
        self.assertEqual(displayed.iloc[0]["display_group"], "core_attack")

    def test_summary_uses_three_day_profit_for_displayed_list(self):
        displayed = pd.DataFrame(
            [
                {"display_group": "core_attack", "page_rule": "three_day_prev_second", "display_rank": 1, "ret_1d_pct": 1, "ret_3d_pct": 6, "mfe_5d_pct": 9, "mae_5d_pct": -2, "next_limit_up": False, "gap_fail": False},
                {"display_group": "core_attack", "page_rule": "three_day_prev_second", "display_rank": 2, "ret_1d_pct": -1, "ret_3d_pct": -2, "mfe_5d_pct": 3, "mae_5d_pct": -5, "next_limit_up": False, "gap_fail": False},
                {"display_group": "aggressive", "page_rule": "three_day_lhb_theme_buy", "display_rank": 1, "ret_1d_pct": 2, "ret_3d_pct": 4, "mfe_5d_pct": 8, "mae_5d_pct": -1, "next_limit_up": True, "gap_fail": False},
            ]
        )

        summary = summarize_page_display(displayed)
        core = summary[(summary["group_type"] == "display_group") & (summary["group_value"] == "core_attack")].iloc[0]

        self.assertEqual(core["sample_count"], 2)
        self.assertEqual(core["avg_ret_3d_pct"], 2.0)
        self.assertEqual(core["win_3d_rate"], 0.5)


if __name__ == "__main__":
    unittest.main()
