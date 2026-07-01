import unittest

import pandas as pd

from research.dragon_fast_money_experiment import (
    apply_profit_rule_v4_labels,
    apply_profit_rule_v5_3d_labels,
    enrich_fast_money_events,
)
from research.dragon_reliability_backtest import summarize_events


class DragonFastMoneyExperimentTest(unittest.TestCase):
    def test_enrich_fast_money_events_merges_lhb_hot_and_risk_flags(self):
        events = pd.DataFrame(
            [
                {
                    "trade_date": "20260620",
                    "ts_code": "000001.SZ",
                    "profit_rule_v3": "aggressive_first_divergence",
                    "ret_5d_pct": 8.0,
                }
            ]
        )
        lhb = pd.DataFrame(
            [
                {
                    "trade_date": "20260620",
                    "ts_code": "000001.SZ",
                    "lhb_net_buy": 12000000,
                    "lhb_buy_amount": 30000000,
                    "lhb_sell_amount": 18000000,
                    "lhb_turnover": 48000000,
                    "lhb_reason": "换手率达20%",
                }
            ]
        )
        hot = pd.DataFrame(
            [
                {
                    "trade_date": "20260620",
                    "ts_code": "000001.SZ",
                    "hot_rank": 88,
                    "new_fans_ratio": 0.6,
                    "loyal_fans_ratio": 0.4,
                }
            ]
        )
        dt = pd.DataFrame(columns=["trade_date", "ts_code"])
        sub_new = pd.DataFrame([{"trade_date": "20260620", "ts_code": "000001.SZ"}])

        enriched = enrich_fast_money_events(events, lhb=lhb, hot=hot, dt_pool=dt, sub_new_pool=sub_new)

        self.assertEqual(enriched.loc[0, "lhb_net_buy"], 12000000)
        self.assertEqual(enriched.loc[0, "hot_rank"], 88)
        self.assertTrue(bool(enriched.loc[0, "is_sub_new"]))
        self.assertFalse(bool(enriched.loc[0, "is_dt_pool"]))

    def test_apply_profit_rule_v4_labels_upgrades_confirmed_money(self):
        events = pd.DataFrame(
            [
                {
                    "profit_rule_v3": "aggressive_first_divergence",
                    "lhb_net_buy": 12000000,
                    "hot_rank": 88,
                    "is_dt_pool": False,
                    "is_sub_new": False,
                },
                {
                    "profit_rule_v3": "aggressive_prev_second",
                    "lhb_net_buy": -5000000,
                    "hot_rank": 300,
                    "is_dt_pool": False,
                    "is_sub_new": False,
                },
                {
                    "profit_rule_v3": "trap_low_turnover",
                    "lhb_net_buy": 0,
                    "hot_rank": 1000,
                    "is_dt_pool": False,
                    "is_sub_new": False,
                },
                {
                    "profit_rule_v3": "aggressive_strong_mid_turnover",
                    "lhb_net_buy": 0,
                    "hot_rank": 120,
                    "is_dt_pool": False,
                    "is_sub_new": False,
                },
            ]
        )

        labeled = apply_profit_rule_v4_labels(events)

        self.assertEqual(labeled.loc[0, "profit_rule_v4"], "confirmed_hot_money")
        self.assertEqual(labeled.loc[1, "profit_rule_v4"], "lhb_divergence_wash")
        self.assertEqual(labeled.loc[2, "profit_rule_v4"], "trap_avoid")
        self.assertEqual(labeled.loc[3, "profit_rule_v4"], "crowd_confirmed")

    def test_summary_includes_profit_rule_v4(self):
        events = pd.DataFrame(
            [
                {
                    "profit_rule_v4": "confirmed_hot_money",
                    "ret_1d_pct": 1.0,
                    "ret_3d_pct": 3.0,
                    "ret_5d_pct": 6.0,
                    "mfe_5d_pct": 9.0,
                    "mae_5d_pct": -3.0,
                    "next_limit_up": False,
                    "gap_fail": False,
                }
            ]
        )

        summary, _ = summarize_events(events, min_group_samples=1, min_total_events=1)

        self.assertIn("profit_rule_v4", set(summary["group_type"]))
        self.assertIn("win_3d_rate", set(summary.columns))

    def test_apply_profit_rule_v5_3d_labels_focuses_on_three_day_fast_money(self):
        events = pd.DataFrame(
            [
                {"source": "zt_pool", "limit_days": 3, "theme_score": 35, "gap_fail": False, "lhb_turnover": 1000, "lhb_net_buy": 0, "turnover_rate": 10},
                {"source": "previous_pool", "limit_days": 2, "theme_score": 35, "gap_fail": False, "lhb_turnover": 0, "lhb_net_buy": 0, "turnover_rate": 10},
                {"source": "zt_pool", "limit_days": 1, "theme_score": 55, "gap_fail": False, "lhb_turnover": 1000, "lhb_net_buy": 6000000, "turnover_rate": 5},
                {"source": "zt_pool", "limit_days": 1, "theme_score": 35, "gap_fail": False, "lhb_turnover": 0, "lhb_net_buy": 0, "turnover_rate": 2},
            ]
        )

        labeled = apply_profit_rule_v5_3d_labels(events)

        self.assertEqual(labeled.loc[0, "profit_rule_v5_3d"], "three_day_space_lhb")
        self.assertEqual(labeled.loc[1, "profit_rule_v5_3d"], "three_day_prev_second")
        self.assertEqual(labeled.loc[2, "profit_rule_v5_3d"], "three_day_lhb_theme_buy")
        self.assertEqual(labeled.loc[3, "profit_rule_v5_3d"], "three_day_trap")


if __name__ == "__main__":
    unittest.main()
