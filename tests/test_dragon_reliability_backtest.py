import tempfile
import unittest
from pathlib import Path

import pandas as pd

from research.dragon_reliability_backtest import (
    DragonReliabilityConfig,
    apply_profit_rule_labels,
    apply_profit_rule_v2_labels,
    apply_profit_rule_v3_labels,
    build_factor_events,
    render_markdown_report,
    summarize_events,
)


class DragonReliabilityBacktestTest(unittest.TestCase):
    def test_build_factor_events_uses_next_day_open_forward_returns(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            limit_dir = root / "limit_pool"
            daily_dir = root / "daily"
            limit_dir.mkdir()
            daily_dir.mkdir()
            pd.DataFrame(
                [
                    {
                        "trade_date": "20250102",
                        "source": "zt_pool",
                        "ts_code": "000001.SZ",
                        "name": "样本A",
                        "pct_chg": 10.0,
                        "amount": 1000000,
                        "turnover_rate": 1.0,
                        "seal_amount": 500000,
                        "first_limit_time": "092500",
                        "open_count": 0,
                        "limit_days": 1,
                        "limit_up_reason": "机器人",
                        "industry": "机械设备",
                        "concept": "机器人",
                    },
                    {
                        "trade_date": "20250102",
                        "source": "zt_pool",
                        "ts_code": "000002.SZ",
                        "name": "样本B",
                        "pct_chg": 10.0,
                        "amount": 800000,
                        "turnover_rate": 9.0,
                        "seal_amount": 10000,
                        "first_limit_time": "145000",
                        "open_count": 6,
                        "limit_days": 3,
                        "limit_up_reason": "机器人",
                        "industry": "机械设备",
                        "concept": "机器人",
                    },
                ]
            ).to_parquet(limit_dir / "20250102.parquet")
            for date, rows in {
                "20250102": [
                    {"ts_code": "000001.SZ", "trade_date": "20250102", "open": 10.0, "high": 11.0, "low": 9.8, "close": 11.0, "pct_chg": 10.0},
                    {"ts_code": "000002.SZ", "trade_date": "20250102", "open": 20.0, "high": 22.0, "low": 19.8, "close": 22.0, "pct_chg": 10.0},
                ],
                "20250103": [
                    {"ts_code": "000001.SZ", "trade_date": "20250103", "open": 12.0, "high": 13.0, "low": 11.5, "close": 12.6, "pct_chg": 9.8},
                    {"ts_code": "000002.SZ", "trade_date": "20250103", "open": 25.0, "high": 25.2, "low": 22.0, "close": 22.5, "pct_chg": 2.2},
                ],
                "20250106": [
                    {"ts_code": "000001.SZ", "trade_date": "20250106", "open": 12.8, "high": 13.5, "low": 12.1, "close": 13.2, "pct_chg": 4.8},
                    {"ts_code": "000002.SZ", "trade_date": "20250106", "open": 22.4, "high": 23.0, "low": 21.0, "close": 21.5, "pct_chg": -4.4},
                ],
            }.items():
                pd.DataFrame(rows).to_parquet(daily_dir / f"{date}.parquet")

            events = build_factor_events(
                DragonReliabilityConfig(
                    limit_dir=limit_dir,
                    daily_dir=daily_dir,
                    start_date="20250102",
                    end_date="20250102",
                    horizons=(1, 2),
                )
            )

        self.assertEqual(len(events), 2)
        first = events[events["ts_code"] == "000001.SZ"].iloc[0]
        self.assertEqual(first["buy_date"], "20250103")
        self.assertAlmostEqual(first["ret_1d_pct"], 5.0, places=4)
        self.assertAlmostEqual(first["ret_2d_pct"], 10.0, places=4)
        self.assertTrue(bool(first["next_limit_up"]))
        self.assertIn(first["bucket"], {"focus", "wait", "avoid"})

    def test_summary_and_report_mark_insufficient_samples(self):
        events = pd.DataFrame(
            [
                {
                    "trade_date": "20250102",
                    "ts_code": "000001.SZ",
                    "bucket": "focus",
                    "lifecycle": "首板高质量",
                    "theme_state": "主线确认",
                    "ret_1d_pct": 5.0,
                    "ret_3d_pct": 7.0,
                    "ret_5d_pct": 8.0,
                    "mfe_5d_pct": 12.0,
                    "mae_5d_pct": -2.0,
                    "next_limit_up": True,
                    "gap_fail": False,
                },
                {
                    "trade_date": "20250102",
                    "ts_code": "000002.SZ",
                    "bucket": "avoid",
                    "lifecycle": "退潮风险",
                    "theme_state": "退潮回避",
                    "ret_1d_pct": -3.0,
                    "ret_3d_pct": -5.0,
                    "ret_5d_pct": -6.0,
                    "mfe_5d_pct": 1.0,
                    "mae_5d_pct": -9.0,
                    "next_limit_up": False,
                    "gap_fail": True,
                },
            ]
        )

        summary, verdict = summarize_events(events, min_group_samples=5, min_total_events=20)
        report = render_markdown_report(summary, verdict)

        self.assertEqual(verdict["rating"], "样本不足")
        self.assertIn("样本不足", report)
        self.assertIn("bucket", set(summary["group_type"]))

    def test_summary_verdict_uses_profit_rule_v2_when_it_separates_winners(self):
        events = pd.DataFrame(
            [
                {"profit_rule_v2": "strong_momentum", "bucket": "focus", "ret_1d_pct": 1.0, "ret_3d_pct": 3.0, "ret_5d_pct": 5.0, "mfe_5d_pct": 8.0, "mae_5d_pct": -3.0, "next_limit_up": False, "gap_fail": False},
                {"profit_rule_v2": "strong_momentum", "bucket": "focus", "ret_1d_pct": 0.5, "ret_3d_pct": 2.0, "ret_5d_pct": 4.0, "mfe_5d_pct": 7.0, "mae_5d_pct": -2.0, "next_limit_up": False, "gap_fail": False},
                {"profit_rule_v2": "low_turnover_trap", "bucket": "avoid", "ret_1d_pct": -1.0, "ret_3d_pct": -2.0, "ret_5d_pct": -3.0, "mfe_5d_pct": 2.0, "mae_5d_pct": -8.0, "next_limit_up": False, "gap_fail": True},
                {"profit_rule_v2": "low_turnover_trap", "bucket": "avoid", "ret_1d_pct": -0.5, "ret_3d_pct": -1.0, "ret_5d_pct": -2.0, "mfe_5d_pct": 3.0, "mae_5d_pct": -7.0, "next_limit_up": False, "gap_fail": True},
            ]
        )

        _, verdict = summarize_events(events, min_group_samples=1, min_total_events=4)

        self.assertEqual(verdict["rating"], "新规则初步有效")

    def test_apply_profit_rule_labels_splits_divergence_from_true_retreat(self):
        events = pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "theme_state": "主线确认",
                    "theme_score": 70,
                    "limit_days": 2,
                    "open_count": 0,
                    "turnover_rate": 6,
                    "first_limit_time": "093500",
                    "source": "zt_pool",
                },
                {
                    "ts_code": "000002.SZ",
                    "theme_state": "分歧中",
                    "theme_score": 48,
                    "limit_days": 3,
                    "open_count": 4,
                    "turnover_rate": 18,
                    "first_limit_time": "134500",
                    "source": "zt_pool",
                },
                {
                    "ts_code": "000003.SZ",
                    "theme_state": "轮动补涨",
                    "theme_score": 18,
                    "limit_days": 1,
                    "open_count": 7,
                    "turnover_rate": 22,
                    "first_limit_time": "145500",
                    "source": "zt_pool",
                },
                {
                    "ts_code": "000004.SZ",
                    "theme_state": "发酵观察",
                    "theme_score": 42,
                    "limit_days": 1,
                    "open_count": 0,
                    "turnover_rate": 4,
                    "first_limit_time": "092800",
                    "source": "zt_pool",
                },
            ]
        )

        labeled = apply_profit_rule_labels(events)

        self.assertEqual(labeled.loc[0, "profit_rule"], "core_watch")
        self.assertEqual(labeled.loc[1, "profit_rule"], "divergence_confirm")
        self.assertEqual(labeled.loc[2, "profit_rule"], "retreat_avoid")
        self.assertEqual(labeled.loc[3, "profit_rule"], "early_probe")

    def test_apply_profit_rule_v2_labels_focuses_on_profitable_patterns(self):
        events = pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "source": "strong_pool",
                    "limit_days": 1,
                    "turnover_rate": 10,
                    "open_count": 0,
                    "first_limit_time": "",
                },
                {
                    "ts_code": "000002.SZ",
                    "source": "zt_pool",
                    "limit_days": 1,
                    "turnover_rate": 2,
                    "open_count": 0,
                    "first_limit_time": "092800",
                },
                {
                    "ts_code": "000003.SZ",
                    "source": "zt_pool",
                    "limit_days": 4,
                    "turnover_rate": 12,
                    "open_count": 1,
                    "first_limit_time": "100500",
                },
                {
                    "ts_code": "000004.SZ",
                    "source": "zt_pool",
                    "limit_days": 2,
                    "turnover_rate": 12,
                    "open_count": 4,
                    "first_limit_time": "134500",
                },
            ]
        )

        labeled = apply_profit_rule_v2_labels(events)

        self.assertEqual(labeled.loc[0, "profit_rule_v2"], "strong_momentum")
        self.assertEqual(labeled.loc[1, "profit_rule_v2"], "low_turnover_trap")
        self.assertEqual(labeled.loc[2, "profit_rule_v2"], "high_board_avoid")
        self.assertEqual(labeled.loc[3, "profit_rule_v2"], "zt_divergence_watch")

    def test_apply_profit_rule_v3_labels_supports_aggressive_profit_rules(self):
        events = pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "source": "previous_pool", "limit_days": 2, "turnover_rate": 9, "open_count": 0, "theme_score": 45, "gap_fail": False},
                {"ts_code": "000002.SZ", "source": "zt_pool", "limit_days": 3, "turnover_rate": 10, "open_count": 1, "theme_score": 55, "gap_fail": False},
                {"ts_code": "000003.SZ", "source": "zt_pool", "limit_days": 1, "turnover_rate": 5, "open_count": 4, "theme_score": 40, "gap_fail": False},
                {"ts_code": "000004.SZ", "source": "zt_pool", "limit_days": 1, "turnover_rate": 2, "open_count": 0, "theme_score": 40, "gap_fail": True},
                {"ts_code": "000005.SZ", "source": "zt_pool", "limit_days": 4, "turnover_rate": 10, "open_count": 1, "theme_score": 55, "gap_fail": False},
            ]
        )

        labeled = apply_profit_rule_v3_labels(events)

        self.assertEqual(labeled.loc[0, "profit_rule_v3"], "aggressive_prev_second")
        self.assertEqual(labeled.loc[1, "profit_rule_v3"], "aggressive_zt_third")
        self.assertEqual(labeled.loc[2, "profit_rule_v3"], "aggressive_first_divergence")
        self.assertEqual(labeled.loc[3, "profit_rule_v3"], "trap_low_turnover")
        self.assertEqual(labeled.loc[4, "profit_rule_v3"], "risk_high_board")


if __name__ == "__main__":
    unittest.main()
