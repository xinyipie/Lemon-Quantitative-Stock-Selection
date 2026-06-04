import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strategy_profiles import apply_style_gate, available_profiles, available_style_gates, factor_profile_score


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

    def test_adaptive_quality_v5_is_available(self):
        self.assertIn("adaptive_quality_v5", list(available_style_gates()))

    def test_adaptive_quality_v6_is_available(self):
        self.assertIn("adaptive_quality_v6", list(available_style_gates()))

    def test_profile_v8_sector_rank_is_available(self):
        self.assertIn("profile_v8_sector_rank", list(available_profiles()))

    def test_profile_v9_sector_quality_guard_is_available(self):
        self.assertIn("profile_v9_sector_quality_guard", list(available_profiles()))

    def test_profile_v10_mid_deep_drawdown_guard_is_available(self):
        self.assertIn("profile_v10_mid_deep_drawdown_guard", list(available_profiles()))

    def test_profile_v11_mid_deep_drawdown_strict_guard_is_available(self):
        self.assertIn("profile_v11_mid_deep_drawdown_strict_guard", list(available_profiles()))

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

    def test_adaptive_quality_v5_filters_high_score_volume_spike(self):
        df = pd.DataFrame(
            [
                self.make_row(ts_code="quality", score=72, volume_ratio=2.8),
                self.make_row(ts_code="volume_spike", score=72, volume_ratio=3.4),
            ]
        )

        filtered = apply_style_gate(df, "adaptive_quality_v5")

        self.assertEqual(filtered["ts_code"].tolist(), ["quality"])

    def test_adaptive_quality_v6_keeps_strong_sector_volume_spike(self):
        df = pd.DataFrame(
            [
                self.make_row(
                    ts_code="strong_sector_spike",
                    score=71.94,
                    factor_sector=50.85,
                    volume_ratio=3.24,
                ),
                self.make_row(
                    ts_code="weak_sector_spike",
                    score=70.04,
                    factor_sector=29.03,
                    volume_ratio=3.29,
                ),
            ]
        )

        filtered = apply_style_gate(df, "adaptive_quality_v6")

        self.assertEqual(filtered["ts_code"].tolist(), ["strong_sector_spike"])

    def test_profile_v8_sector_rank_adds_small_sector_bonus_on_profile_v4_base(self):
        row = pd.Series(self.make_row(factor_sector=65))

        base = factor_profile_score(row, "profile_v4")
        boosted = factor_profile_score(row, "profile_v8_sector_rank")

        self.assertEqual(boosted, round(min(base + 3.0, 100.0), 2))

    def test_profile_v8_sector_rank_penalizes_weak_sector(self):
        row = pd.Series(self.make_row(factor_sector=25))

        base = factor_profile_score(row, "profile_v4")
        penalized = factor_profile_score(row, "profile_v8_sector_rank")

        self.assertEqual(penalized, round(max(base - 1.0, 0.0), 2))

    def test_profile_v9_rewards_strong_sector_only_when_volume_is_not_spiking(self):
        calm_row = pd.Series(self.make_row(factor_sector=65, volume_ratio=2.4))
        spike_row = pd.Series(self.make_row(factor_sector=65, volume_ratio=3.2))

        calm_base = factor_profile_score(calm_row, "profile_v4")
        spike_base = factor_profile_score(spike_row, "profile_v4")

        self.assertEqual(factor_profile_score(calm_row, "profile_v9_sector_quality_guard"), round(min(calm_base + 3.0, 100.0), 2))
        self.assertEqual(factor_profile_score(spike_row, "profile_v9_sector_quality_guard"), spike_base)

    def test_profile_v9_heavily_penalizes_weak_sector_volume_spike(self):
        row = pd.Series(self.make_row(factor_sector=25, volume_ratio=3.2))

        base = factor_profile_score(row, "profile_v4")
        penalized = factor_profile_score(row, "profile_v9_sector_quality_guard")

        self.assertEqual(penalized, round(max(base - 3.0, 0.0), 2))

    def test_profile_v10_penalizes_only_mid_deep_drawdown_bucket(self):
        mid_deep = pd.Series(self.make_row(drawdown_from_high=9.5))
        extreme = pd.Series(self.make_row(drawdown_from_high=12.5))
        normal = pd.Series(self.make_row(drawdown_from_high=6.5))

        mid_deep_base = factor_profile_score(mid_deep, "profile_v4")
        extreme_base = factor_profile_score(extreme, "profile_v4")
        normal_base = factor_profile_score(normal, "profile_v4")

        self.assertEqual(
            factor_profile_score(mid_deep, "profile_v10_mid_deep_drawdown_guard"),
            round(max(mid_deep_base - 3.0, 0.0), 2),
        )
        self.assertEqual(factor_profile_score(extreme, "profile_v10_mid_deep_drawdown_guard"), extreme_base)
        self.assertEqual(factor_profile_score(normal, "profile_v10_mid_deep_drawdown_guard"), normal_base)

    def test_profile_v11_strictly_penalizes_only_mid_deep_drawdown_bucket(self):
        mid_deep = pd.Series(self.make_row(drawdown_from_high=9.5))
        extreme = pd.Series(self.make_row(drawdown_from_high=12.5))
        normal = pd.Series(self.make_row(drawdown_from_high=6.5))

        mid_deep_base = factor_profile_score(mid_deep, "profile_v4")
        extreme_base = factor_profile_score(extreme, "profile_v4")
        normal_base = factor_profile_score(normal, "profile_v4")

        self.assertEqual(
            factor_profile_score(mid_deep, "profile_v11_mid_deep_drawdown_strict_guard"),
            round(max(mid_deep_base - 6.0, 0.0), 2),
        )
        self.assertEqual(factor_profile_score(extreme, "profile_v11_mid_deep_drawdown_strict_guard"), extreme_base)
        self.assertEqual(factor_profile_score(normal, "profile_v11_mid_deep_drawdown_strict_guard"), normal_base)


if __name__ == "__main__":
    unittest.main()
