import tempfile
import unittest
from pathlib import Path

import pandas as pd

from research.short_signal_factor_miner import build_rule_candidates, classify_summary, load_trade_frames, summarize_rule


class ShortSignalFactorMinerTest(unittest.TestCase):
    def test_summarize_rule_computes_short_window_metrics(self):
        df = pd.DataFrame(
            [
                {
                    "period": "2024",
                    "profit_after_fee": 2.0,
                    "mfe_pct": 5.0,
                    "mae_pct": -1.0,
                    "window_end_pct": 1.0,
                    "hit_3pct": True,
                    "hit_5pct": True,
                },
                {
                    "period": "2024",
                    "profit_after_fee": -1.0,
                    "mfe_pct": 3.2,
                    "mae_pct": -3.0,
                    "window_end_pct": -0.5,
                    "hit_3pct": True,
                    "hit_5pct": False,
                },
                {
                    "period": "2025",
                    "profit_after_fee": 4.0,
                    "mfe_pct": 8.0,
                    "mae_pct": -0.8,
                    "window_end_pct": 3.0,
                    "hit_3pct": True,
                    "hit_5pct": True,
                },
            ]
        )

        summary = summarize_rule("demo", df)

        self.assertEqual(summary["sample_count"], 3)
        self.assertEqual(summary["period_count"], 2)
        self.assertEqual(summary["win_rate"], 66.67)
        self.assertEqual(summary["hit_3pct_rate"], 100.0)
        self.assertEqual(summary["hit_5pct_rate"], 66.67)
        self.assertEqual(summary["avg_mfe_pct"], 5.4)
        self.assertEqual(summary["avg_mae_pct"], -1.6)

    def test_build_rule_candidates_includes_sector_and_regime_buckets(self):
        df = pd.DataFrame(
            [
                {
                    "period": "2024",
                    "market_style": "weak_momentum",
                    "macro_mode": "active",
                    "factor_sector": 30.0,
                    "factor_pattern": 20.0,
                    "profit_after_fee": 1.0,
                    "mfe_pct": 4.0,
                    "mae_pct": -1.0,
                    "window_end_pct": 1.0,
                    "hit_3pct": True,
                    "hit_5pct": False,
                },
                {
                    "period": "2025",
                    "market_style": "weak_momentum",
                    "macro_mode": "active",
                    "factor_sector": 70.0,
                    "factor_pattern": 80.0,
                    "profit_after_fee": -1.0,
                    "mfe_pct": 2.0,
                    "mae_pct": -4.0,
                    "window_end_pct": -1.0,
                    "hit_3pct": False,
                    "hit_5pct": False,
                },
            ]
        )

        rules = build_rule_candidates(df, min_samples=1)
        names = {item["rule"] for item in rules}

        self.assertIn("market_style=weak_momentum", names)
        self.assertIn("factor_sector<=45", names)
        self.assertIn("factor_sector>60", names)
        self.assertIn("market_style=weak_momentum & factor_sector<=45", names)
        self.assertIn("factor_sector<=45 & factor_pattern<=40", names)

    def test_classify_summary_rejects_rules_with_bad_period(self):
        summary = {
            "sample_count": 12,
            "period_count": 3,
            "avg_profit_pct": 3.0,
            "hit_3pct_rate": 85.0,
            "hit_5pct_rate": 55.0,
            "periods": [
                {"period": "2024", "sample_count": 3, "avg_profit_pct": -2.0, "hit_3pct_rate": 50.0, "hit_5pct_rate": 25.0},
                {"period": "2025", "sample_count": 6, "avg_profit_pct": 4.0, "hit_3pct_rate": 90.0, "hit_5pct_rate": 60.0},
                {"period": "2026H1", "sample_count": 3, "avg_profit_pct": 5.0, "hit_3pct_rate": 100.0, "hit_5pct_rate": 80.0},
            ],
        }

        self.assertEqual(classify_summary(summary, min_samples=3), "reject")

    def test_load_trade_frames_uses_ret_5d_for_candidate_level_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "ic_short_demo.csv"
            pd.DataFrame(
                [
                    {
                        "select_date": 20250102,
                        "ret_5d": 3.5,
                        "mfe_pct": 5.0,
                        "mae_pct": -1.0,
                        "hit_3pct": True,
                        "hit_5pct": False,
                    }
                ]
            ).to_csv(path, index=False)

            df = load_trade_frames([path])

        self.assertIn("profit_after_fee", df.columns)
        self.assertEqual(df.loc[0, "profit_after_fee"], 3.5)
        self.assertEqual(df.loc[0, "period"], "2025")


if __name__ == "__main__":
    unittest.main()
