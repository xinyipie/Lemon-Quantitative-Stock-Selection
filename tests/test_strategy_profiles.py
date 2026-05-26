import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strategy_profiles import apply_style_gate, available_style_gates


class StyleGateTest(unittest.TestCase):
    def make_row(self, **overrides):
        row = {
            "ts_code": "quality",
            "market_style": "weak_momentum",
            "macro_mode": "active",
            "score": 72,
            "factor_pattern": 64,
            "factor_sector": 44,
            "factor_drawdown": 78,
            "drawdown_from_high": 5.0,
            "volume_ratio": 2.2,
        }
        row.update(overrides)
        return row

    def test_adaptive_quality_v2_is_available(self):
        self.assertIn("adaptive_quality_v2", list(available_style_gates()))

    def test_adaptive_quality_v2_filters_extreme_high_score_risk(self):
        df = pd.DataFrame(
            [
                self.make_row(ts_code="quality"),
                self.make_row(
                    ts_code="risk",
                    score=82,
                    factor_pattern=48,
                    factor_sector=58,
                    factor_drawdown=92,
                    drawdown_from_high=10.5,
                    volume_ratio=3.4,
                ),
            ]
        )

        filtered = apply_style_gate(df, "adaptive_quality_v2")

        self.assertEqual(filtered["ts_code"].tolist(), ["quality"])

    def test_adaptive_quality_v2_uses_experiment_score_for_risk(self):
        df = pd.DataFrame(
            [
                self.make_row(
                    ts_code="reranked_risk",
                    score=55.19,
                    experiment_score=79.84,
                    factor_pattern=43.33,
                    factor_sector=14.67,
                    factor_drawdown=100.0,
                    drawdown_from_high=9.5,
                    volume_ratio=1.93,
                )
            ]
        )

        filtered = apply_style_gate(df, "adaptive_quality_v2")

        self.assertTrue(filtered.empty)

    def test_adaptive_quality_v2_keeps_sideways_quality_candidate(self):
        df = pd.DataFrame(
            [
                self.make_row(
                    ts_code="sideways_quality",
                    market_style="sideways",
                    macro_mode="active",
                    factor_pattern=62,
                    factor_sector=46,
                    factor_drawdown=74,
                    drawdown_from_high=4.5,
                    volume_ratio=1.8,
                )
            ]
        )

        filtered = apply_style_gate(df, "adaptive_quality_v2")

        self.assertEqual(filtered["ts_code"].tolist(), ["sideways_quality"])


if __name__ == "__main__":
    unittest.main()
