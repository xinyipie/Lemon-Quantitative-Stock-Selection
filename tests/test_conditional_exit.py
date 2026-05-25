import unittest
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtest_v2 import BacktestV2


def make_backtest(enabled=True):
    bt = BacktestV2.__new__(BacktestV2)
    bt.conditional_lock_enabled = enabled
    bt.conditional_lock_activation_pct = 6.0
    bt.conditional_lock_trailing_pct = 4.8
    return bt


class ConditionalExitTest(unittest.TestCase):
    def test_conditional_lock_tightens_only_weak_quality_after_profit(self):
        bt = make_backtest()
        row = pd.Series(
            {
                "factor_pattern": 52,
                "factor_wyckoff": 58,
                "factor_volume_ratio": 55,
                "factor_drawdown": 94,
                "drawdown_from_high": 9,
            }
        )

        self.assertEqual(
            bt._conditional_trailing_pct(row, current_profit_pct=6.5, mfe_pct=7.0, base_trailing_pct=7.0),
            4.8,
        )

    def test_conditional_lock_keeps_baseline_for_strong_quality(self):
        bt = make_backtest()
        row = pd.Series(
            {
                "factor_pattern": 70,
                "factor_wyckoff": 75,
                "factor_volume_ratio": 72,
                "factor_drawdown": 70,
                "drawdown_from_high": 3,
            }
        )

        self.assertEqual(
            bt._conditional_trailing_pct(row, current_profit_pct=8.0, mfe_pct=9.0, base_trailing_pct=7.0),
            7.0,
        )

    def test_conditional_lock_keeps_baseline_before_activation(self):
        bt = make_backtest()
        row = pd.Series(
            {
                "factor_pattern": 52,
                "factor_wyckoff": 58,
                "factor_volume_ratio": 55,
                "factor_drawdown": 94,
                "drawdown_from_high": 9,
            }
        )

        self.assertEqual(
            bt._conditional_trailing_pct(row, current_profit_pct=3.5, mfe_pct=4.0, base_trailing_pct=7.0),
            7.0,
        )


if __name__ == "__main__":
    unittest.main()
