import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strategy_profiles import (
    apply_live_short_postprocess,
    apply_style_gate,
    available_profiles,
    available_style_gates,
    build_consensus_candidates,
    build_live_observation_candidates,
    factor_profile_score,
    normalize_consensus_profile,
)


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

    def _v40_row(self, code: str, **overrides):
        row = {
            "code": code,
            "ts_code": f"{code}.SZ",
            "score": 80.0,
            "market_style": "weak_momentum",
            "macro_mode": "active",
            "regime": "BULL_TREND",
            "market_index_change": 0.3,
            "limit_up_count": 85,
            "limit_down_count": 2,
            "limit_up_down_ratio": 20.0,
            "sector_ma10_ratio": 78.0,
            "change": 3.0,
            "volume_ratio": 2.0,
            "drawdown_from_high": 5.0,
            "factor_volume_ratio": 70.0,
            "factor_drawdown": 60.0,
            "factor_inflow": 99.0,
            "factor_turnover": 55.0,
            "factor_sector": 40.0,
            "factor_pattern": 65.0,
            "factor_counter_trend": 50.0,
            "factor_wyckoff": 68.0,
            "factor_accel": 50.0,
        }
        row.update(overrides)
        return row

    def test_adaptive_quality_v2_is_available(self):
        self.assertIn("adaptive_quality_v2", list(available_style_gates()))

    def test_adaptive_quality_v5_is_available(self):
        self.assertIn("adaptive_quality_v5", list(available_style_gates()))

    def test_adaptive_quality_v6_is_available(self):
        self.assertIn("adaptive_quality_v6", list(available_style_gates()))

    def test_adaptive_quality_v13_is_available(self):
        self.assertIn("adaptive_quality_v13", list(available_style_gates()))

    def test_adaptive_quality_v14_is_available(self):
        self.assertIn("adaptive_quality_v14", list(available_style_gates()))

    def test_adaptive_quality_v15_is_available(self):
        self.assertIn("adaptive_quality_v15", list(available_style_gates()))

    def test_adaptive_quality_v16_is_available(self):
        self.assertIn("adaptive_quality_v16", list(available_style_gates()))

    def test_adaptive_quality_v17_is_available(self):
        self.assertIn("adaptive_quality_v17", list(available_style_gates()))

    def test_adaptive_quality_v18_is_available(self):
        self.assertIn("adaptive_quality_v18", list(available_style_gates()))

    def test_adaptive_quality_v19_is_available(self):
        self.assertIn("adaptive_quality_v19", list(available_style_gates()))

    def test_adaptive_quality_v20_is_available(self):
        self.assertIn("adaptive_quality_v20", list(available_style_gates()))

    def test_adaptive_quality_v21_is_available(self):
        self.assertIn("adaptive_quality_v21", list(available_style_gates()))

    def test_adaptive_quality_v22_is_available(self):
        self.assertIn("adaptive_quality_v22", list(available_style_gates()))

    def test_adaptive_quality_v23_is_available(self):
        self.assertIn("adaptive_quality_v23", list(available_style_gates()))

    def test_adaptive_quality_v24_is_available(self):
        self.assertIn("adaptive_quality_v24", list(available_style_gates()))

    def test_adaptive_quality_v25_is_available(self):
        self.assertIn("adaptive_quality_v25", list(available_style_gates()))

    def test_adaptive_quality_v26_is_available(self):
        self.assertIn("adaptive_quality_v26", list(available_style_gates()))

    def test_adaptive_quality_v27_is_available(self):
        self.assertIn("adaptive_quality_v27", list(available_style_gates()))

    def test_adaptive_quality_v28_is_available(self):
        self.assertIn("adaptive_quality_v28", list(available_style_gates()))

    def test_profile_v8_sector_rank_is_available(self):
        self.assertIn("profile_v8_sector_rank", list(available_profiles()))

    def test_profile_v9_sector_quality_guard_is_available(self):
        self.assertIn("profile_v9_sector_quality_guard", list(available_profiles()))

    def test_profile_v10_mid_deep_drawdown_guard_is_available(self):
        self.assertIn("profile_v10_mid_deep_drawdown_guard", list(available_profiles()))

    def test_profile_v11_mid_deep_drawdown_strict_guard_is_available(self):
        self.assertIn("profile_v11_mid_deep_drawdown_strict_guard", list(available_profiles()))

    def test_profile_v12_2026h1_guard_is_available(self):
        self.assertIn("profile_v12_2026h1_guard", list(available_profiles()))

    def test_profile_v13_high_win_quality_gate_is_available(self):
        self.assertIn("profile_v13_high_win_quality_gate", list(available_profiles()))

    def test_profile_v14_sector_pattern_gate_is_available(self):
        self.assertIn("profile_v14_sector_pattern_gate", list(available_profiles()))

    def test_profile_v15_dual_lane_quality_gate_is_available(self):
        self.assertIn("profile_v15_dual_lane_quality_gate", list(available_profiles()))

    def test_profile_v16_window_confidence_is_available(self):
        self.assertIn("profile_v16_window_confidence", list(available_profiles()))

    def test_profile_v17_followthrough_factor_is_available(self):
        self.assertIn("profile_v17_followthrough_factor", list(available_profiles()))

    def test_profile_v18_stable_followthrough_is_available(self):
        self.assertIn("profile_v18_stable_followthrough", list(available_profiles()))

    def test_profile_v19_calm_followthrough_is_available(self):
        self.assertIn("profile_v19_calm_followthrough", list(available_profiles()))

    def test_profile_v20_low_noise_followthrough_is_available(self):
        self.assertIn("profile_v20_low_noise_followthrough", list(available_profiles()))

    def test_profile_v21_sector_calm_followthrough_is_available(self):
        self.assertIn("profile_v21_sector_calm_followthrough", list(available_profiles()))

    def test_profile_v22_two_lane_followthrough_is_available(self):
        self.assertIn("profile_v22_two_lane_followthrough", list(available_profiles()))

    def test_profile_v23_cautious_window_is_available(self):
        self.assertIn("profile_v23_cautious_window", list(available_profiles()))

    def test_profile_v24_momentum_pullback_is_available(self):
        self.assertIn("profile_v24_momentum_pullback", list(available_profiles()))

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

    def test_adaptive_quality_v13_keeps_only_hard_quality_candidates(self):
        df = pd.DataFrame(
            [
                self.make_row(
                    ts_code="quality",
                    factor_pattern=76,
                    factor_inflow=82,
                    factor_sector=52,
                    drawdown_from_high=4.8,
                    volume_ratio=2.1,
                    change=2.2,
                ),
                self.make_row(ts_code="low_pattern", factor_pattern=52, factor_inflow=90),
                self.make_row(ts_code="low_inflow", factor_pattern=80, factor_inflow=55),
                self.make_row(ts_code="deep_drawdown", factor_pattern=80, factor_inflow=90, drawdown_from_high=9.0),
                self.make_row(ts_code="volume_spike", factor_pattern=80, factor_inflow=90, volume_ratio=3.6),
                self.make_row(ts_code="bear_style", market_style="bear", factor_pattern=90, factor_inflow=90),
            ]
        )

        filtered = apply_style_gate(df, "adaptive_quality_v13")

        self.assertEqual(filtered["ts_code"].tolist(), ["quality"])

    def test_adaptive_quality_v28_requires_market_heat(self):
        df = pd.DataFrame(
            [
                self.make_row(
                    ts_code="heated_followthrough",
                    factor_inflow=100.0,
                    factor_wyckoff=66.0,
                    factor_sector=40.0,
                    change=3.8,
                    drawdown_from_high=4.0,
                    regime="BULL_TREND",
                    market_index_change=0.1,
                    sector_ma10_ratio=80.0,
                    limit_up_count=75,
                    limit_down_count=8,
                ),
                self.make_row(
                    ts_code="cold_followthrough",
                    factor_inflow=100.0,
                    factor_wyckoff=66.0,
                    factor_sector=40.0,
                    change=3.8,
                    drawdown_from_high=4.0,
                    regime="BULL_TREND",
                    market_index_change=0.1,
                    sector_ma10_ratio=80.0,
                    limit_up_count=45,
                    limit_down_count=8,
                ),
            ]
        )

        filtered = apply_style_gate(df, "adaptive_quality_v28")

        self.assertEqual(filtered["ts_code"].tolist(), ["heated_followthrough"])

    def test_adaptive_quality_v14_requires_sector_pattern_and_calm_entry(self):
        df = pd.DataFrame(
            [
                self.make_row(
                    ts_code="quality",
                    factor_pattern=78,
                    factor_inflow=86,
                    factor_sector=72,
                    drawdown_from_high=3.8,
                    volume_ratio=2.1,
                    change=2.6,
                ),
                self.make_row(ts_code="weak_sector", factor_pattern=82, factor_inflow=90, factor_sector=54),
                self.make_row(ts_code="weak_pattern", factor_pattern=63, factor_inflow=90, factor_sector=80),
                self.make_row(ts_code="hot_entry", factor_pattern=82, factor_inflow=90, factor_sector=80, change=3.4),
                self.make_row(ts_code="deep_entry", factor_pattern=82, factor_inflow=90, factor_sector=80, drawdown_from_high=6.2),
                self.make_row(ts_code="volume_spike", factor_pattern=82, factor_inflow=90, factor_sector=80, volume_ratio=3.2),
            ]
        )

        filtered = apply_style_gate(df, "adaptive_quality_v14")

        self.assertEqual(filtered["ts_code"].tolist(), ["quality"])

    def test_adaptive_quality_v15_keeps_v14_lane_and_controlled_weak_momentum_lane(self):
        df = pd.DataFrame(
            [
                self.make_row(
                    ts_code="lane_a",
                    market_style="momentum",
                    factor_pattern=78,
                    factor_inflow=82,
                    factor_sector=70,
                    drawdown_from_high=3.8,
                    volume_ratio=2.1,
                    change=2.6,
                ),
                self.make_row(
                    ts_code="lane_b",
                    market_style="weak_momentum",
                    factor_pattern=82,
                    factor_inflow=86,
                    factor_sector=42,
                    drawdown_from_high=5.2,
                    volume_ratio=2.2,
                    change=2.4,
                ),
                self.make_row(ts_code="weak_sector", factor_pattern=82, factor_inflow=90, factor_sector=30),
                self.make_row(ts_code="weak_pattern", factor_pattern=70, factor_inflow=90, factor_sector=42),
                self.make_row(ts_code="weak_inflow", factor_pattern=82, factor_inflow=76, factor_sector=42),
                self.make_row(ts_code="hot_entry", factor_pattern=82, factor_inflow=90, factor_sector=42, change=3.4),
                self.make_row(ts_code="deep_entry", factor_pattern=82, factor_inflow=90, factor_sector=42, drawdown_from_high=6.2),
                self.make_row(ts_code="volume_spike", factor_pattern=82, factor_inflow=90, factor_sector=42, volume_ratio=2.9),
                self.make_row(ts_code="bear_style", market_style="bear", factor_pattern=90, factor_inflow=90, factor_sector=90),
                self.make_row(ts_code="sideways_lane_b", market_style="sideways", factor_pattern=82, factor_inflow=90, factor_sector=42),
            ]
        )

        filtered = apply_style_gate(df, "adaptive_quality_v15")

        self.assertEqual(filtered["ts_code"].tolist(), ["lane_a", "lane_b"])

    def test_adaptive_quality_v16_keeps_only_high_confidence_window_setups(self):
        df = pd.DataFrame(
            [
                self.make_row(
                    ts_code="strong_sector_lane",
                    market_style="momentum",
                    factor_pattern=78,
                    factor_inflow=82,
                    factor_sector=72,
                    drawdown_from_high=3.8,
                    volume_ratio=2.1,
                    change=2.4,
                ),
                self.make_row(
                    ts_code="confirmed_weak_lane",
                    market_style="weak_momentum",
                    factor_pattern=84,
                    factor_inflow=88,
                    factor_sector=64,
                    drawdown_from_high=4.4,
                    volume_ratio=2.0,
                    change=2.2,
                ),
                self.make_row(
                    ts_code="v15_relaxed_weak_noise",
                    market_style="weak_momentum",
                    factor_pattern=82,
                    factor_inflow=86,
                    factor_sector=42,
                    drawdown_from_high=5.2,
                    volume_ratio=2.2,
                    change=2.4,
                ),
                self.make_row(
                    ts_code="mid_deep_drawdown",
                    factor_pattern=90,
                    factor_inflow=90,
                    factor_sector=90,
                    drawdown_from_high=9.8,
                    volume_ratio=2.0,
                    change=2.0,
                ),
                self.make_row(
                    ts_code="hot_entry",
                    factor_pattern=90,
                    factor_inflow=90,
                    factor_sector=90,
                    drawdown_from_high=3.0,
                    volume_ratio=2.0,
                    change=3.4,
                ),
                self.make_row(
                    ts_code="volume_spike",
                    factor_pattern=90,
                    factor_inflow=90,
                    factor_sector=90,
                    drawdown_from_high=3.0,
                    volume_ratio=2.9,
                    change=2.0,
                ),
            ]
        )

        filtered = apply_style_gate(df, "adaptive_quality_v16")

        self.assertEqual(filtered["ts_code"].tolist(), ["strong_sector_lane", "confirmed_weak_lane"])

    def test_adaptive_quality_v16_keeps_broader_main_lane_without_hot_or_deep_entries(self):
        df = pd.DataFrame(
            [
                self.make_row(
                    ts_code="broader_main_lane",
                    market_style="momentum",
                    factor_pattern=70,
                    factor_inflow=70,
                    factor_sector=60,
                    drawdown_from_high=5.2,
                    volume_ratio=2.75,
                    change=2.8,
                ),
                self.make_row(
                    ts_code="deep_entry",
                    market_style="momentum",
                    factor_pattern=90,
                    factor_inflow=90,
                    factor_sector=90,
                    drawdown_from_high=5.8,
                    volume_ratio=2.2,
                    change=2.0,
                ),
                self.make_row(
                    ts_code="hot_entry",
                    market_style="momentum",
                    factor_pattern=90,
                    factor_inflow=90,
                    factor_sector=90,
                    drawdown_from_high=3.0,
                    volume_ratio=2.2,
                    change=3.2,
                ),
                self.make_row(
                    ts_code="weak_structure",
                    market_style="momentum",
                    factor_pattern=66,
                    factor_inflow=90,
                    factor_sector=90,
                    drawdown_from_high=3.0,
                    volume_ratio=2.2,
                    change=2.0,
                ),
                self.make_row(
                    ts_code="weak_momentum_low_sector_noise",
                    market_style="weak_momentum",
                    factor_pattern=76,
                    factor_inflow=90,
                    factor_sector=61,
                    drawdown_from_high=2.2,
                    volume_ratio=2.49,
                    change=2.0,
                ),
            ]
        )

        filtered = apply_style_gate(df, "adaptive_quality_v16")

        self.assertEqual(filtered["ts_code"].tolist(), ["broader_main_lane"])

    def test_adaptive_quality_v17_keeps_followthrough_lanes_without_sideways_or_heat(self):
        df = pd.DataFrame(
            [
                self.make_row(
                    ts_code="lane_a",
                    market_style="momentum",
                    factor_pattern=66,
                    factor_inflow=92,
                    factor_sector=55,
                    factor_wyckoff=64,
                    drawdown_from_high=6.5,
                    volume_ratio=2.7,
                    change=4.8,
                ),
                self.make_row(
                    ts_code="lane_b",
                    market_style="weak_momentum",
                    factor_pattern=62,
                    factor_inflow=74,
                    factor_sector=72,
                    factor_wyckoff=76,
                    drawdown_from_high=5.8,
                    volume_ratio=2.4,
                    change=4.0,
                ),
                self.make_row(
                    ts_code="sideways_noise",
                    market_style="sideways",
                    factor_pattern=90,
                    factor_inflow=100,
                    factor_sector=60,
                    factor_wyckoff=50,
                    drawdown_from_high=3.0,
                    volume_ratio=2.0,
                    change=2.0,
                ),
                self.make_row(
                    ts_code="bear_noise",
                    market_style="bear",
                    factor_pattern=90,
                    factor_inflow=100,
                    factor_sector=60,
                    factor_wyckoff=50,
                    drawdown_from_high=3.0,
                    volume_ratio=2.0,
                    change=2.0,
                ),
                self.make_row(
                    ts_code="sector_too_hot",
                    market_style="weak_momentum",
                    factor_pattern=62,
                    factor_inflow=74,
                    factor_sector=92,
                    factor_wyckoff=76,
                    drawdown_from_high=5.8,
                    volume_ratio=2.4,
                    change=4.0,
                ),
                self.make_row(
                    ts_code="volume_spike",
                    market_style="momentum",
                    factor_pattern=66,
                    factor_inflow=92,
                    factor_sector=55,
                    factor_wyckoff=64,
                    drawdown_from_high=6.5,
                    volume_ratio=3.0,
                    change=4.8,
                ),
                self.make_row(
                    ts_code="deep_drawdown",
                    market_style="momentum",
                    factor_pattern=66,
                    factor_inflow=92,
                    factor_sector=55,
                    factor_wyckoff=64,
                    drawdown_from_high=7.4,
                    volume_ratio=2.7,
                    change=4.8,
                ),
                self.make_row(
                    ts_code="weak_inflow",
                    market_style="weak_momentum",
                    factor_pattern=62,
                    factor_inflow=68,
                    factor_sector=72,
                    factor_wyckoff=76,
                    drawdown_from_high=5.8,
                    volume_ratio=2.4,
                    change=4.0,
                ),
            ]
        )

        filtered = apply_style_gate(df, "adaptive_quality_v17")

        self.assertEqual(filtered["ts_code"].tolist(), ["lane_a", "lane_b"])

    def test_adaptive_quality_v18_keeps_stable_followthrough_without_noise(self):
        df = pd.DataFrame(
            [
                self.make_row(
                    ts_code="stable_followthrough",
                    market_style="weak_momentum",
                    factor_inflow=100,
                    factor_wyckoff=66,
                    factor_sector=48,
                    drawdown_from_high=4.8,
                    volume_ratio=2.4,
                    change=2.2,
                ),
                self.make_row(
                    ts_code="low_inflow",
                    market_style="weak_momentum",
                    factor_inflow=96,
                    factor_wyckoff=66,
                    factor_sector=48,
                    drawdown_from_high=4.8,
                    volume_ratio=2.4,
                    change=2.2,
                ),
                self.make_row(
                    ts_code="weak_structure",
                    market_style="weak_momentum",
                    factor_inflow=100,
                    factor_wyckoff=54,
                    factor_sector=48,
                    drawdown_from_high=4.8,
                    volume_ratio=2.4,
                    change=2.2,
                ),
                self.make_row(
                    ts_code="volume_spike",
                    market_style="weak_momentum",
                    factor_inflow=100,
                    factor_wyckoff=66,
                    factor_sector=48,
                    drawdown_from_high=4.8,
                    volume_ratio=3.1,
                    change=2.2,
                ),
                self.make_row(
                    ts_code="sideways_noise",
                    market_style="sideways",
                    factor_inflow=100,
                    factor_wyckoff=66,
                    factor_sector=48,
                    drawdown_from_high=4.8,
                    volume_ratio=2.4,
                    change=2.2,
                ),
                self.make_row(
                    ts_code="bear_noise",
                    market_style="bear",
                    factor_inflow=100,
                    factor_wyckoff=66,
                    factor_sector=48,
                    drawdown_from_high=4.8,
                    volume_ratio=2.4,
                    change=2.2,
                ),
            ]
        )

        filtered = apply_style_gate(df, "adaptive_quality_v18")

        self.assertEqual(filtered["ts_code"].tolist(), ["stable_followthrough"])

    def test_adaptive_quality_v19_rejects_hot_structure_and_deeper_pullback(self):
        df = pd.DataFrame(
            [
                self.make_row(
                    ts_code="calm_followthrough",
                    market_style="weak_momentum",
                    factor_inflow=100,
                    factor_wyckoff=70,
                    factor_sector=48,
                    drawdown_from_high=5.8,
                    volume_ratio=2.3,
                    change=2.8,
                ),
                self.make_row(
                    ts_code="hot_structure",
                    market_style="weak_momentum",
                    factor_inflow=100,
                    factor_wyckoff=79,
                    factor_sector=48,
                    drawdown_from_high=5.8,
                    volume_ratio=2.3,
                    change=2.8,
                ),
                self.make_row(
                    ts_code="deep_pullback",
                    market_style="weak_momentum",
                    factor_inflow=100,
                    factor_wyckoff=70,
                    factor_sector=48,
                    drawdown_from_high=7.4,
                    volume_ratio=2.3,
                    change=2.8,
                ),
            ]
        )

        filtered = apply_style_gate(df, "adaptive_quality_v19")

        self.assertEqual(filtered["ts_code"].tolist(), ["calm_followthrough"])

    def test_adaptive_quality_v20_rejects_noisy_followthrough_entries(self):
        df = pd.DataFrame(
            [
                self.make_row(
                    ts_code="low_noise_followthrough",
                    market_style="weak_momentum",
                    factor_inflow=100,
                    factor_sector=56,
                    factor_wyckoff=68,
                    drawdown_from_high=4.6,
                    volume_ratio=2.1,
                    change=3.2,
                ),
                self.make_row(
                    ts_code="late_chase",
                    market_style="weak_momentum",
                    factor_inflow=100,
                    factor_sector=56,
                    factor_wyckoff=68,
                    drawdown_from_high=4.6,
                    volume_ratio=2.1,
                    change=4.7,
                ),
                self.make_row(
                    ts_code="sector_too_hot",
                    market_style="weak_momentum",
                    factor_inflow=100,
                    factor_sector=90,
                    factor_wyckoff=68,
                    drawdown_from_high=4.6,
                    volume_ratio=2.1,
                    change=3.2,
                ),
            ]
        )

        filtered = apply_style_gate(df, "adaptive_quality_v20")

        self.assertEqual(filtered["ts_code"].tolist(), ["low_noise_followthrough"])

    def test_adaptive_quality_v21_rejects_hot_sector_followthrough_entries(self):
        df = pd.DataFrame(
            [
                self.make_row(
                    ts_code="low_sector_calm_followthrough",
                    market_style="weak_momentum",
                    factor_inflow=100,
                    factor_sector=42,
                    factor_wyckoff=68,
                    drawdown_from_high=4.6,
                    volume_ratio=2.1,
                    change=3.2,
                ),
                self.make_row(
                    ts_code="mid_hot_sector",
                    market_style="weak_momentum",
                    factor_inflow=100,
                    factor_sector=56,
                    factor_wyckoff=68,
                    drawdown_from_high=4.6,
                    volume_ratio=2.1,
                    change=3.2,
                ),
                self.make_row(
                    ts_code="hot_sector",
                    market_style="weak_momentum",
                    factor_inflow=100,
                    factor_sector=76,
                    factor_wyckoff=68,
                    drawdown_from_high=4.6,
                    volume_ratio=2.1,
                    change=3.2,
                ),
            ]
        )

        filtered = apply_style_gate(df, "adaptive_quality_v21")

        self.assertEqual(filtered["ts_code"].tolist(), ["low_sector_calm_followthrough"])

    def test_adaptive_quality_v22_keeps_low_sector_and_active_pattern_lanes(self):
        df = pd.DataFrame(
            [
                self.make_row(
                    ts_code="low_sector_lane",
                    market_style="weak_momentum",
                    macro_mode="cautious",
                    factor_inflow=100,
                    factor_sector=42,
                    factor_pattern=58,
                    factor_wyckoff=68,
                    drawdown_from_high=4.6,
                    volume_ratio=2.1,
                    change=3.2,
                ),
                self.make_row(
                    ts_code="active_pattern_lane",
                    market_style="weak_momentum",
                    macro_mode="active",
                    factor_inflow=92,
                    factor_sector=58,
                    factor_pattern=36,
                    factor_wyckoff=68,
                    drawdown_from_high=4.6,
                    volume_ratio=2.1,
                    change=3.2,
                ),
                self.make_row(
                    ts_code="hot_active_pattern",
                    market_style="weak_momentum",
                    macro_mode="active",
                    factor_inflow=92,
                    factor_sector=76,
                    factor_pattern=36,
                    factor_wyckoff=68,
                    drawdown_from_high=4.6,
                    volume_ratio=2.1,
                    change=3.2,
                ),
            ]
        )

        filtered = apply_style_gate(df, "adaptive_quality_v22")

        self.assertEqual(filtered["ts_code"].tolist(), ["low_sector_lane", "active_pattern_lane"])

    def test_adaptive_quality_v23_keeps_cautious_nonactive_window_with_score_floor(self):
        df = pd.DataFrame(
            [
                self.make_row(
                    ts_code="cautious_window",
                    market_style="weak_momentum",
                    macro_mode="cautious",
                    score=20,
                    factor_sector=42,
                    factor_wyckoff=68,
                    drawdown_from_high=4.6,
                    change=3.2,
                ),
                self.make_row(
                    ts_code="active_window",
                    market_style="weak_momentum",
                    macro_mode="active",
                    score=20,
                    factor_sector=42,
                    factor_wyckoff=68,
                    drawdown_from_high=4.6,
                    change=3.2,
                ),
                self.make_row(
                    ts_code="low_score_window",
                    market_style="weak_momentum",
                    macro_mode="cautious",
                    score=12,
                    factor_sector=42,
                    factor_wyckoff=68,
                    drawdown_from_high=4.6,
                    change=3.2,
                ),
                self.make_row(
                    ts_code="hot_sector_window",
                    market_style="weak_momentum",
                    macro_mode="cautious",
                    score=20,
                    factor_sector=62,
                    factor_wyckoff=68,
                    drawdown_from_high=4.6,
                    change=3.2,
                ),
            ]
        )

        filtered = apply_style_gate(df, "adaptive_quality_v23")

        self.assertEqual(filtered["ts_code"].tolist(), ["cautious_window"])

    def test_adaptive_quality_v24_keeps_momentum_pullback_entries(self):
        df = pd.DataFrame(
            [
                self.make_row(
                    ts_code="momentum_pullback",
                    market_style="momentum",
                    factor_pattern=43,
                    drawdown_from_high=3.5,
                    volume_ratio=2.4,
                    change=3.2,
                ),
                self.make_row(
                    ts_code="weak_style",
                    market_style="weak_momentum",
                    factor_pattern=43,
                    drawdown_from_high=3.5,
                    volume_ratio=2.4,
                    change=3.2,
                ),
                self.make_row(
                    ts_code="too_shallow",
                    market_style="momentum",
                    factor_pattern=43,
                    drawdown_from_high=1.2,
                    volume_ratio=2.4,
                    change=3.2,
                ),
                self.make_row(
                    ts_code="too_deep",
                    market_style="momentum",
                    factor_pattern=43,
                    drawdown_from_high=12.0,
                    volume_ratio=2.4,
                    change=3.2,
                ),
                self.make_row(
                    ts_code="volume_spike",
                    market_style="momentum",
                    factor_pattern=43,
                    drawdown_from_high=3.5,
                    volume_ratio=3.4,
                    change=3.2,
                ),
                self.make_row(
                    ts_code="weak_pattern",
                    market_style="momentum",
                    factor_pattern=20,
                    drawdown_from_high=3.5,
                    volume_ratio=2.4,
                    change=3.2,
                ),
            ]
        )

        filtered = apply_style_gate(df, "adaptive_quality_v24")

        self.assertEqual(filtered["ts_code"].tolist(), ["momentum_pullback"])

    def test_adaptive_quality_v25_adds_market_protection_to_v19_followthrough(self):
        df = pd.DataFrame(
            [
                self.make_row(
                    ts_code="protected_followthrough",
                    market_style="weak_momentum",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    drawdown_from_high=4.6,
                    volume_ratio=2.1,
                    change=3.2,
                    regime="BULL_TREND",
                    sector_ma10_ratio=74,
                    market_index_change=-0.2,
                ),
                self.make_row(
                    ts_code="bull_pullback",
                    market_style="weak_momentum",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    drawdown_from_high=4.6,
                    volume_ratio=2.1,
                    change=3.2,
                    regime="BULL_PULLBACK",
                    sector_ma10_ratio=74,
                    market_index_change=-0.2,
                ),
                self.make_row(
                    ts_code="sector_overheated",
                    market_style="weak_momentum",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    drawdown_from_high=4.6,
                    volume_ratio=2.1,
                    change=3.2,
                    regime="BULL_TREND",
                    sector_ma10_ratio=98,
                    market_index_change=-0.2,
                ),
                self.make_row(
                    ts_code="index_breakdown",
                    market_style="weak_momentum",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    drawdown_from_high=4.6,
                    volume_ratio=2.1,
                    change=3.2,
                    regime="BULL_TREND",
                    sector_ma10_ratio=74,
                    market_index_change=-0.9,
                ),
                self.make_row(
                    ts_code="v19_quality_fail",
                    market_style="weak_momentum",
                    factor_inflow=100,
                    factor_wyckoff=82,
                    drawdown_from_high=4.6,
                    volume_ratio=2.1,
                    change=3.2,
                    regime="BULL_TREND",
                    sector_ma10_ratio=74,
                    market_index_change=-0.2,
                ),
            ]
        )

        filtered = apply_style_gate(df, "adaptive_quality_v25")

        self.assertEqual(filtered["ts_code"].tolist(), ["protected_followthrough"])

    def test_adaptive_quality_v26_adds_sentiment_and_hot_followthrough_lanes(self):
        df = pd.DataFrame(
            [
                self.make_row(
                    ts_code="protected_followthrough",
                    market_style="weak_momentum",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    drawdown_from_high=4.6,
                    volume_ratio=2.1,
                    change=3.2,
                    regime="BULL_TREND",
                    sector_ma10_ratio=74,
                    market_index_change=-0.2,
                    limit_up_count=82,
                    limit_down_count=8,
                ),
                self.make_row(
                    ts_code="hot_followthrough",
                    market_style="weak_momentum",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    drawdown_from_high=3.6,
                    volume_ratio=1.9,
                    change=3.2,
                    regime="BULL_TREND",
                    sector_ma10_ratio=98,
                    market_index_change=0.4,
                    limit_up_count=110,
                    limit_down_count=4,
                ),
                self.make_row(
                    ts_code="weak_sentiment",
                    market_style="weak_momentum",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    drawdown_from_high=4.6,
                    volume_ratio=2.1,
                    change=3.2,
                    regime="BULL_TREND",
                    sector_ma10_ratio=74,
                    market_index_change=-0.2,
                    limit_up_count=56,
                    limit_down_count=17,
                ),
                self.make_row(
                    ts_code="hot_but_index_not_confirmed",
                    market_style="weak_momentum",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    drawdown_from_high=3.6,
                    volume_ratio=1.9,
                    change=3.2,
                    regime="BULL_TREND",
                    sector_ma10_ratio=98,
                    market_index_change=0.1,
                    limit_up_count=110,
                    limit_down_count=4,
                ),
                self.make_row(
                    ts_code="hot_but_too_many_limit_ups",
                    market_style="weak_momentum",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    drawdown_from_high=3.6,
                    volume_ratio=1.9,
                    change=3.2,
                    regime="BULL_TREND",
                    sector_ma10_ratio=98,
                    market_index_change=0.4,
                    limit_up_count=170,
                    limit_down_count=4,
                ),
                self.make_row(
                    ts_code="bull_pullback",
                    market_style="weak_momentum",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    drawdown_from_high=4.6,
                    volume_ratio=2.1,
                    change=3.2,
                    regime="BULL_PULLBACK",
                    sector_ma10_ratio=74,
                    market_index_change=0.4,
                    limit_up_count=82,
                    limit_down_count=8,
                ),
            ]
        )

        filtered = apply_style_gate(df, "adaptive_quality_v26")

        self.assertEqual(filtered["ts_code"].tolist(), ["protected_followthrough", "hot_followthrough"])

    def test_adaptive_quality_v27_combines_sector_calm_and_protected_lanes(self):
        df = pd.DataFrame(
            [
                self.make_row(
                    ts_code="sector_calm_lane",
                    market_style="weak_momentum",
                    factor_inflow=100,
                    factor_sector=32,
                    factor_wyckoff=68,
                    drawdown_from_high=4.2,
                    volume_ratio=2.1,
                    change=3.2,
                    regime="BULL_PULLBACK",
                    sector_ma10_ratio=52,
                    market_index_change=-0.8,
                ),
                self.make_row(
                    ts_code="protected_lane",
                    market_style="weak_momentum",
                    factor_inflow=100,
                    factor_sector=62,
                    factor_wyckoff=68,
                    drawdown_from_high=4.2,
                    volume_ratio=2.1,
                    change=3.2,
                    regime="BULL_TREND",
                    sector_ma10_ratio=74,
                    market_index_change=-0.2,
                ),
                self.make_row(
                    ts_code="chasing_high",
                    market_style="weak_momentum",
                    factor_inflow=100,
                    factor_sector=32,
                    factor_wyckoff=68,
                    drawdown_from_high=2.4,
                    volume_ratio=2.1,
                    change=3.2,
                    regime="BULL_TREND",
                    sector_ma10_ratio=74,
                    market_index_change=-0.2,
                ),
                self.make_row(
                    ts_code="unprotected_hot_sector",
                    market_style="weak_momentum",
                    factor_inflow=100,
                    factor_sector=62,
                    factor_wyckoff=68,
                    drawdown_from_high=4.2,
                    volume_ratio=2.1,
                    change=3.2,
                    regime="BULL_TREND",
                    sector_ma10_ratio=98,
                    market_index_change=-0.2,
                ),
                self.make_row(
                    ts_code="index_breakdown",
                    market_style="weak_momentum",
                    factor_inflow=100,
                    factor_sector=62,
                    factor_wyckoff=68,
                    drawdown_from_high=4.2,
                    volume_ratio=2.1,
                    change=3.2,
                    regime="BULL_TREND",
                    sector_ma10_ratio=74,
                    market_index_change=-0.9,
                ),
            ]
        )

        filtered = apply_style_gate(df, "adaptive_quality_v27")

        self.assertEqual(filtered["ts_code"].tolist(), ["sector_calm_lane", "protected_lane"])

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

    def test_profile_v12_prefers_controlled_weak_momentum_over_sideways_spike(self):
        quality = pd.Series(
            self.make_row(
                market_style="weak_momentum",
                macro_mode="active",
                factor_inflow=72,
                factor_pattern=62,
                factor_turnover=76,
                factor_sector=42,
                volume_ratio=2.0,
                drawdown_from_high=5.0,
                change=2.4,
            )
        )
        sideways_spike = pd.Series(
            self.make_row(
                market_style="sideways",
                macro_mode="active",
                factor_inflow=88,
                factor_pattern=48,
                factor_turnover=82,
                factor_sector=68,
                volume_ratio=3.6,
                drawdown_from_high=9.5,
                change=4.8,
            )
        )

        self.assertGreater(
            factor_profile_score(quality, "profile_v12_2026h1_guard"),
            factor_profile_score(sideways_spike, "profile_v12_2026h1_guard") + 20,
        )

    def test_profile_v13_strongly_prefers_three_to_five_day_quality_setup(self):
        quality = pd.Series(
            self.make_row(
                market_style="weak_momentum",
                macro_mode="active",
                factor_inflow=86,
                factor_pattern=82,
                factor_turnover=76,
                factor_sector=54,
                volume_ratio=2.0,
                drawdown_from_high=4.5,
                change=2.0,
            )
        )
        noisy_leader = pd.Series(
            self.make_row(
                market_style="sideways",
                macro_mode="active",
                score=82,
                factor_inflow=42,
                factor_pattern=30,
                factor_turnover=88,
                factor_sector=85,
                volume_ratio=3.8,
                drawdown_from_high=12.0,
                change=4.9,
            )
        )

        self.assertGreater(
            factor_profile_score(quality, "profile_v13_high_win_quality_gate"),
            factor_profile_score(noisy_leader, "profile_v13_high_win_quality_gate") + 20,
        )

    def test_profile_v14_prefers_sector_pattern_calm_entry(self):
        quality = pd.Series(
            self.make_row(
                factor_inflow=90,
                factor_pattern=82,
                factor_sector=76,
                volume_ratio=2.1,
                drawdown_from_high=3.8,
                change=2.4,
            )
        )
        noisy = pd.Series(
            self.make_row(
                score=85,
                factor_inflow=100,
                factor_pattern=64,
                factor_sector=42,
                volume_ratio=2.7,
                drawdown_from_high=6.0,
                change=4.2,
            )
        )

        self.assertGreater(
            factor_profile_score(quality, "profile_v14_sector_pattern_gate"),
            factor_profile_score(noisy, "profile_v14_sector_pattern_gate") + 25,
        )

    def test_profile_v15_rewards_controlled_weak_momentum_lane_over_hot_low_sector_noise(self):
        lane_b = pd.Series(
            self.make_row(
                market_style="weak_momentum",
                factor_inflow=88,
                factor_pattern=84,
                factor_sector=42,
                volume_ratio=2.1,
                drawdown_from_high=5.0,
                change=2.3,
            )
        )
        noisy = pd.Series(
            self.make_row(
                market_style="weak_momentum",
                score=88,
                factor_inflow=100,
                factor_pattern=66,
                factor_sector=30,
                volume_ratio=3.0,
                drawdown_from_high=6.5,
                change=4.0,
            )
        )

        self.assertGreater(
            factor_profile_score(lane_b, "profile_v15_dual_lane_quality_gate"),
            factor_profile_score(noisy, "profile_v15_dual_lane_quality_gate") + 20,
        )

    def test_profile_v16_prefers_confirmed_window_setup_over_v15_relaxed_weak_lane(self):
        confirmed = pd.Series(
            self.make_row(
                market_style="weak_momentum",
                factor_inflow=88,
                factor_pattern=84,
                factor_sector=64,
                volume_ratio=2.0,
                drawdown_from_high=4.4,
                change=2.2,
            )
        )
        relaxed_noise = pd.Series(
            self.make_row(
                market_style="weak_momentum",
                factor_inflow=86,
                factor_pattern=82,
                factor_sector=42,
                volume_ratio=2.2,
                drawdown_from_high=5.2,
                change=2.4,
            )
        )

        self.assertGreater(
            factor_profile_score(confirmed, "profile_v16_window_confidence"),
            factor_profile_score(relaxed_noise, "profile_v16_window_confidence") + 20,
        )

    def test_profile_v16_calibrates_confirmed_window_setups_above_trade_threshold(self):
        strong_sector = pd.Series(
            self.make_row(
                market_style="momentum",
                factor_inflow=82,
                factor_pattern=78,
                factor_sector=72,
                volume_ratio=2.1,
                drawdown_from_high=3.8,
                change=2.4,
            )
        )
        confirmed_weak = pd.Series(
            self.make_row(
                market_style="weak_momentum",
                factor_inflow=88,
                factor_pattern=84,
                factor_sector=64,
                volume_ratio=2.0,
                drawdown_from_high=4.4,
                change=2.2,
            )
        )

        self.assertGreaterEqual(factor_profile_score(strong_sector, "profile_v16_window_confidence"), 70)
        self.assertGreaterEqual(factor_profile_score(confirmed_weak, "profile_v16_window_confidence"), 70)

    def test_profile_v17_prefers_balanced_followthrough_over_hot_sideways_noise(self):
        followthrough = pd.Series(
            self.make_row(
                market_style="weak_momentum",
                factor_inflow=78,
                factor_pattern=64,
                factor_sector=72,
                factor_wyckoff=76,
                volume_ratio=2.3,
                drawdown_from_high=5.8,
                change=4.0,
            )
        )
        noisy = pd.Series(
            self.make_row(
                market_style="sideways",
                score=88,
                factor_inflow=100,
                factor_pattern=48,
                factor_sector=92,
                factor_wyckoff=92,
                volume_ratio=3.2,
                drawdown_from_high=8.4,
                change=5.4,
            )
        )

        self.assertGreater(
            factor_profile_score(followthrough, "profile_v17_followthrough_factor"),
            factor_profile_score(noisy, "profile_v17_followthrough_factor") + 20,
        )

    def test_profile_v18_prefers_stable_followthrough_over_hot_structure_noise(self):
        stable = pd.Series(
            self.make_row(
                market_style="weak_momentum",
                factor_inflow=100,
                factor_wyckoff=68,
                factor_sector=48,
                volume_ratio=2.3,
                drawdown_from_high=4.5,
                change=2.0,
            )
        )
        noisy = pd.Series(
            self.make_row(
                market_style="weak_momentum",
                score=88,
                factor_inflow=100,
                factor_wyckoff=92,
                factor_sector=92,
                volume_ratio=3.3,
                drawdown_from_high=8.4,
                change=5.2,
            )
        )

        self.assertGreater(
            factor_profile_score(stable, "profile_v18_stable_followthrough"),
            factor_profile_score(noisy, "profile_v18_stable_followthrough") + 18,
        )

    def test_profile_v19_penalizes_hot_structure_inside_stable_followthrough(self):
        calm = pd.Series(
            self.make_row(
                market_style="weak_momentum",
                factor_inflow=100,
                factor_wyckoff=70,
                factor_sector=48,
                volume_ratio=2.3,
                drawdown_from_high=5.8,
                change=2.8,
            )
        )
        hot = pd.Series(
            self.make_row(
                market_style="weak_momentum",
                factor_inflow=100,
                factor_wyckoff=79,
                factor_sector=48,
                volume_ratio=2.3,
                drawdown_from_high=5.8,
                change=2.8,
            )
        )

        self.assertGreater(
            factor_profile_score(calm, "profile_v19_calm_followthrough"),
            factor_profile_score(hot, "profile_v19_calm_followthrough") + 8,
        )

    def test_profile_v21_prefers_low_sector_calm_followthrough(self):
        low_sector = pd.Series(
            self.make_row(
                market_style="weak_momentum",
                factor_inflow=100,
                factor_wyckoff=68,
                factor_sector=42,
                factor_pattern=38,
                volume_ratio=2.1,
                drawdown_from_high=4.6,
                change=3.2,
            )
        )
        hot_sector = pd.Series(
            self.make_row(
                market_style="weak_momentum",
                factor_inflow=100,
                factor_wyckoff=68,
                factor_sector=76,
                factor_pattern=38,
                volume_ratio=2.1,
                drawdown_from_high=4.6,
                change=3.2,
            )
        )

        self.assertGreater(
            factor_profile_score(low_sector, "profile_v21_sector_calm_followthrough"),
            factor_profile_score(hot_sector, "profile_v21_sector_calm_followthrough") + 10,
        )

    def test_profile_v22_scores_active_pattern_lane_above_hot_active_pattern(self):
        active_pattern = pd.Series(
            self.make_row(
                market_style="weak_momentum",
                macro_mode="active",
                factor_inflow=92,
                factor_wyckoff=68,
                factor_sector=58,
                factor_pattern=36,
                volume_ratio=2.1,
                drawdown_from_high=4.6,
                change=3.2,
            )
        )
        hot_pattern = pd.Series(
            self.make_row(
                market_style="weak_momentum",
                macro_mode="active",
                factor_inflow=92,
                factor_wyckoff=68,
                factor_sector=76,
                factor_pattern=36,
                volume_ratio=2.1,
                drawdown_from_high=4.6,
                change=3.2,
            )
        )

        self.assertGreater(
            factor_profile_score(active_pattern, "profile_v22_two_lane_followthrough"),
            factor_profile_score(hot_pattern, "profile_v22_two_lane_followthrough") + 8,
        )

    def test_profile_v23_prefers_cautious_nonactive_window_over_active_noise(self):
        cautious = pd.Series(
            self.make_row(
                market_style="weak_momentum",
                macro_mode="cautious",
                factor_sector=42,
                factor_wyckoff=68,
                drawdown_from_high=4.6,
                change=3.2,
                score=20,
            )
        )
        active = pd.Series(
            self.make_row(
                market_style="weak_momentum",
                macro_mode="active",
                factor_sector=42,
                factor_wyckoff=68,
                drawdown_from_high=4.6,
                change=3.2,
                score=20,
            )
        )

        self.assertGreater(
            factor_profile_score(cautious, "profile_v23_cautious_window"),
            factor_profile_score(active, "profile_v23_cautious_window") + 8,
        )

    def test_v29_consensus_requires_at_least_two_virtual_votes(self):
        df = pd.DataFrame(
            [
                self.make_row(
                    code="three_vote",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    factor_sector=40,
                    volume_ratio=2.1,
                    drawdown_from_high=5.0,
                    change=3.0,
                    regime="BULL_TREND",
                    sector_ma10_ratio=80,
                    market_index_change=0.1,
                ),
                self.make_row(
                    code="two_vote",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    factor_sector=40,
                    volume_ratio=2.1,
                    drawdown_from_high=5.0,
                    change=3.0,
                    regime="BULL_TREND",
                    sector_ma10_ratio=80,
                    market_index_change=-1.0,
                ),
                self.make_row(
                    code="single_vote",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    factor_sector=70,
                    volume_ratio=2.1,
                    drawdown_from_high=2.0,
                    change=3.0,
                    regime="BULL_TREND",
                    sector_ma10_ratio=80,
                    market_index_change=-1.0,
                ),
            ]
        )

        result = build_consensus_candidates(df, consensus_profile="v29", min_votes=2)

        self.assertEqual(["three_vote", "two_vote"], result["code"].tolist())
        self.assertEqual([3, 2], result["consensus_votes"].tolist())
        self.assertIn("consensus_score", result.columns)

    def test_v30_consensus_requires_market_heat_acceptance(self):
        df = pd.DataFrame(
            [
                self.make_row(
                    code="accepted_heat",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    factor_sector=40,
                    volume_ratio=2.1,
                    drawdown_from_high=5.0,
                    change=3.0,
                    regime="BULL_TREND",
                    limit_up_count=72,
                    sector_ma10_ratio=80,
                    market_index_change=0.1,
                ),
                self.make_row(
                    code="cold_heat",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    factor_sector=40,
                    volume_ratio=2.1,
                    drawdown_from_high=5.0,
                    change=3.0,
                    regime="BULL_TREND",
                    limit_up_count=42,
                    sector_ma10_ratio=80,
                    market_index_change=0.1,
                ),
                self.make_row(
                    code="neutral_breadth",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    factor_sector=40,
                    volume_ratio=2.1,
                    drawdown_from_high=5.0,
                    change=3.0,
                    regime="BULL_TREND",
                    limit_up_count=72,
                    sector_ma10_ratio=60,
                    market_index_change=0.1,
                ),
            ]
        )

        result = build_consensus_candidates(df, consensus_profile="v30", min_votes=2)

        self.assertEqual(["accepted_heat"], result["code"].tolist())
        self.assertEqual([3], result["consensus_votes"].tolist())

    def test_v31_consensus_keeps_mid_breadth_with_penalty(self):
        df = pd.DataFrame(
            [
                self.make_row(
                    code="nonmid_heat",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    factor_sector=40,
                    volume_ratio=2.1,
                    drawdown_from_high=5.0,
                    change=3.0,
                    regime="BULL_TREND",
                    limit_up_count=78,
                    sector_ma10_ratio=82,
                    market_index_change=0.1,
                ),
                self.make_row(
                    code="mid_breadth_heat",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    factor_sector=40,
                    volume_ratio=2.1,
                    drawdown_from_high=5.0,
                    change=3.0,
                    regime="BULL_TREND",
                    limit_up_count=78,
                    sector_ma10_ratio=60,
                    market_index_change=0.1,
                ),
                self.make_row(
                    code="cold_heat",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    factor_sector=40,
                    volume_ratio=2.1,
                    drawdown_from_high=5.0,
                    change=3.0,
                    regime="BULL_TREND",
                    limit_up_count=52,
                    sector_ma10_ratio=82,
                    market_index_change=0.1,
                ),
                self.make_row(
                    code="overextended",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    factor_sector=40,
                    volume_ratio=2.1,
                    drawdown_from_high=5.0,
                    change=5.2,
                    regime="BULL_TREND",
                    limit_up_count=78,
                    sector_ma10_ratio=82,
                    market_index_change=0.1,
                ),
            ]
        )

        result = build_consensus_candidates(df, consensus_profile="v31", min_votes=2)

        self.assertEqual(["nonmid_heat", "mid_breadth_heat"], result["code"].tolist())
        scores = result.set_index("code")["consensus_score"]
        self.assertGreater(scores["nonmid_heat"], scores["mid_breadth_heat"])

    def test_v32_consensus_requires_moderate_heat_and_volume(self):
        df = pd.DataFrame(
            [
                self.make_row(
                    code="accepted",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    factor_sector=40,
                    volume_ratio=2.1,
                    drawdown_from_high=5.0,
                    change=3.0,
                    regime="BULL_TREND",
                    limit_up_count=58,
                    sector_ma10_ratio=60,
                    market_index_change=0.1,
                ),
                self.make_row(
                    code="cold",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    factor_sector=40,
                    volume_ratio=2.1,
                    drawdown_from_high=5.0,
                    change=3.0,
                    regime="BULL_TREND",
                    limit_up_count=42,
                    sector_ma10_ratio=82,
                    market_index_change=0.1,
                ),
                self.make_row(
                    code="volume_spike",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    factor_sector=40,
                    volume_ratio=2.8,
                    drawdown_from_high=5.0,
                    change=3.0,
                    regime="BULL_TREND",
                    limit_up_count=58,
                    sector_ma10_ratio=82,
                    market_index_change=0.1,
                ),
            ]
        )

        result = build_consensus_candidates(df, consensus_profile="v32", min_votes=2)

        self.assertEqual(["accepted"], result["code"].tolist())
        self.assertEqual([3], result["consensus_votes"].tolist())

    def test_v33_consensus_uses_defensive_core_and_selective_mid_breadth_lane(self):
        df = pd.DataFrame(
            [
                self.make_row(
                    code="core_non_mid",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    factor_sector=40,
                    volume_ratio=2.4,
                    drawdown_from_high=5.0,
                    change=3.0,
                    regime="BULL_TREND",
                    limit_up_count=62,
                    limit_down_count=8,
                    sector_ma10_ratio=75,
                    market_index_change=0.1,
                ),
                self.make_row(
                    code="cold_non_mid",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    factor_sector=40,
                    volume_ratio=2.1,
                    drawdown_from_high=5.0,
                    change=3.0,
                    regime="BULL_TREND",
                    limit_up_count=57,
                    limit_down_count=8,
                    sector_ma10_ratio=75,
                    market_index_change=0.1,
                ),
                self.make_row(
                    code="mid_clean",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    factor_sector=40,
                    volume_ratio=2.2,
                    drawdown_from_high=5.0,
                    change=3.0,
                    regime="BULL_TREND",
                    limit_up_count=80,
                    limit_down_count=2,
                    sector_ma10_ratio=62,
                    market_index_change=0.1,
                ),
                self.make_row(
                    code="mid_repair",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    factor_sector=40,
                    volume_ratio=2.2,
                    drawdown_from_high=5.0,
                    change=3.0,
                    regime="BULL_TREND",
                    limit_up_count=80,
                    limit_down_count=22,
                    sector_ma10_ratio=62,
                    market_index_change=0.1,
                ),
                self.make_row(
                    code="mid_mushy",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    factor_sector=40,
                    volume_ratio=2.2,
                    drawdown_from_high=5.0,
                    change=3.0,
                    regime="BULL_TREND",
                    limit_up_count=80,
                    limit_down_count=8,
                    sector_ma10_ratio=62,
                    market_index_change=0.1,
                ),
                self.make_row(
                    code="mid_overvolume",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    factor_sector=40,
                    volume_ratio=2.4,
                    drawdown_from_high=5.0,
                    change=3.0,
                    regime="BULL_TREND",
                    limit_up_count=80,
                    limit_down_count=2,
                    sector_ma10_ratio=62,
                    market_index_change=0.1,
                ),
            ]
        )

        result = build_consensus_candidates(df, consensus_profile="v33", min_votes=2)

        self.assertEqual(["core_non_mid", "mid_clean", "mid_repair"], result["code"].tolist())
        self.assertTrue((result["consensus_votes"] >= 2).all())

    def test_v34_consensus_filters_cautious_mode_mid_down_limit_friction(self):
        df = pd.DataFrame(
            [
                self.make_row(
                    code="active_normal",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    factor_sector=40,
                    volume_ratio=2.1,
                    drawdown_from_high=5.0,
                    change=3.0,
                    macro_mode="active",
                    regime="BULL_TREND",
                    limit_up_count=80,
                    limit_down_count=10,
                    sector_ma10_ratio=75,
                    market_index_change=0.1,
                ),
                self.make_row(
                    code="cautious_clean",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    factor_sector=40,
                    volume_ratio=2.1,
                    drawdown_from_high=5.0,
                    change=3.0,
                    macro_mode="cautious",
                    regime="BULL_TREND",
                    limit_up_count=80,
                    limit_down_count=3,
                    sector_ma10_ratio=75,
                    market_index_change=0.1,
                ),
                self.make_row(
                    code="cautious_repair",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    factor_sector=40,
                    volume_ratio=2.1,
                    drawdown_from_high=5.0,
                    change=3.0,
                    macro_mode="cautious",
                    regime="BULL_TREND",
                    limit_up_count=80,
                    limit_down_count=20,
                    sector_ma10_ratio=75,
                    market_index_change=0.1,
                ),
                self.make_row(
                    code="cautious_mushy_down",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    factor_sector=40,
                    volume_ratio=2.1,
                    drawdown_from_high=5.0,
                    change=3.0,
                    macro_mode="cautious",
                    regime="BULL_TREND",
                    limit_up_count=80,
                    limit_down_count=10,
                    sector_ma10_ratio=75,
                    market_index_change=0.1,
                ),
            ]
        )

        result = build_consensus_candidates(df, consensus_profile="v34", min_votes=2)

        self.assertEqual(["active_normal", "cautious_clean", "cautious_repair"], result["code"].tolist())

    def test_v35_consensus_allows_high_pattern_cautious_friction_exception(self):
        df = pd.DataFrame(
            [
                self.make_row(
                    code="active_normal",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    factor_sector=40,
                    factor_pattern=40,
                    volume_ratio=2.1,
                    drawdown_from_high=5.0,
                    change=3.0,
                    macro_mode="active",
                    regime="BULL_TREND",
                    limit_up_count=80,
                    limit_down_count=10,
                    sector_ma10_ratio=75,
                    market_index_change=0.1,
                ),
                self.make_row(
                    code="cautious_low_pattern",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    factor_sector=40,
                    factor_pattern=53,
                    volume_ratio=2.1,
                    drawdown_from_high=5.0,
                    change=3.0,
                    macro_mode="cautious",
                    regime="BULL_TREND",
                    limit_up_count=80,
                    limit_down_count=10,
                    sector_ma10_ratio=75,
                    market_index_change=0.1,
                ),
                self.make_row(
                    code="cautious_high_pattern",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    factor_sector=40,
                    factor_pattern=63,
                    volume_ratio=2.1,
                    drawdown_from_high=5.0,
                    change=3.0,
                    macro_mode="cautious",
                    regime="BULL_TREND",
                    limit_up_count=80,
                    limit_down_count=10,
                    sector_ma10_ratio=75,
                    market_index_change=0.1,
                ),
            ]
        )

        result = build_consensus_candidates(df, consensus_profile="v35", min_votes=2)

        self.assertEqual(["active_normal", "cautious_high_pattern"], result["code"].tolist())

    def test_v36_consensus_uses_snapshot_top_rule_heat_volume_and_breadth(self):
        df = pd.DataFrame(
            [
                self.make_row(
                    code="accepted_core",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    factor_sector=40,
                    factor_pattern=45,
                    volume_ratio=2.1,
                    drawdown_from_high=5.0,
                    change=3.0,
                    macro_mode="active",
                    regime="BULL_TREND",
                    limit_up_count=65,
                    limit_down_count=2,
                    sector_ma10_ratio=82,
                    market_index_change=0.1,
                ),
                self.make_row(
                    code="neutral_breadth",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    factor_sector=40,
                    factor_pattern=45,
                    volume_ratio=2.1,
                    drawdown_from_high=5.0,
                    change=3.0,
                    macro_mode="active",
                    regime="BULL_TREND",
                    limit_up_count=80,
                    limit_down_count=2,
                    sector_ma10_ratio=60,
                    market_index_change=0.1,
                ),
                self.make_row(
                    code="high_volume",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    factor_sector=40,
                    factor_pattern=45,
                    volume_ratio=2.8,
                    drawdown_from_high=5.0,
                    change=3.0,
                    macro_mode="active",
                    regime="BULL_TREND",
                    limit_up_count=65,
                    limit_down_count=2,
                    sector_ma10_ratio=82,
                    market_index_change=0.1,
                ),
                self.make_row(
                    code="cautious_low_pattern",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    factor_sector=40,
                    factor_pattern=55,
                    volume_ratio=2.1,
                    drawdown_from_high=5.0,
                    change=3.0,
                    macro_mode="cautious",
                    regime="BULL_TREND",
                    limit_up_count=65,
                    limit_down_count=10,
                    sector_ma10_ratio=82,
                    market_index_change=0.1,
                ),
                self.make_row(
                    code="cautious_high_pattern",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    factor_sector=40,
                    factor_pattern=65,
                    volume_ratio=2.1,
                    drawdown_from_high=5.0,
                    change=3.0,
                    macro_mode="cautious",
                    regime="BULL_TREND",
                    limit_up_count=65,
                    limit_down_count=10,
                    sector_ma10_ratio=82,
                    market_index_change=0.1,
                ),
            ]
        )

        result = build_consensus_candidates(df, consensus_profile="v36", min_votes=2)

        self.assertEqual(["accepted_core", "cautious_high_pattern"], result["code"].tolist())

    def test_v37_consensus_reranks_v35_candidates_by_short_quality(self):
        df = pd.DataFrame(
            [
                self.make_row(
                    code="hot_loose",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    factor_sector=70,
                    factor_pattern=45,
                    volume_ratio=2.7,
                    drawdown_from_high=5.0,
                    change=3.0,
                    macro_mode="active",
                    regime="BULL_TREND",
                    limit_up_count=80,
                    limit_down_count=10,
                    sector_ma10_ratio=82,
                    market_index_change=0.1,
                ),
                self.make_row(
                    code="calm_quality",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    factor_sector=35,
                    factor_pattern=65,
                    volume_ratio=2.0,
                    drawdown_from_high=5.0,
                    change=3.0,
                    macro_mode="active",
                    regime="BULL_TREND",
                    limit_up_count=80,
                    limit_down_count=2,
                    sector_ma10_ratio=82,
                    market_index_change=0.1,
                ),
            ]
        )

        result = build_consensus_candidates(df, consensus_profile="v37", min_votes=2)

        self.assertEqual(["calm_quality", "hot_loose"], result["code"].tolist())
        scores = result.set_index("code")["consensus_score"]
        self.assertGreater(scores["calm_quality"], scores["hot_loose"])

    def test_v38_consensus_keeps_rank_protection_when_quality_is_only_low_sector(self):
        df = pd.DataFrame(
            [
                self.make_row(
                    code="rank_first",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    factor_sector=32,
                    factor_pattern=0,
                    volume_ratio=2.4,
                    drawdown_from_high=5.0,
                    change=3.0,
                    macro_mode="active",
                    regime="BULL_TREND",
                    limit_up_count=80,
                    limit_down_count=12,
                    sector_ma10_ratio=44,
                    market_index_change=0.1,
                ),
                self.make_row(
                    code="low_sector_late_rank",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    factor_sector=20,
                    factor_pattern=0,
                    volume_ratio=2.4,
                    drawdown_from_high=5.0,
                    change=3.0,
                    macro_mode="active",
                    regime="BULL_TREND",
                    limit_up_count=80,
                    limit_down_count=12,
                    sector_ma10_ratio=44,
                    market_index_change=0.1,
                ),
            ]
        )

        result = build_consensus_candidates(df, consensus_profile="v38", min_votes=2)

        self.assertEqual(["v38"], result["consensus_profile"].unique().tolist())
        self.assertEqual(["rank_first", "low_sector_late_rank"], result["code"].tolist())

    def test_v39_consensus_keeps_only_strong_average_rank_candidates(self):
        df = pd.DataFrame(
            [
                self.make_row(
                    code="strong_rank",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    factor_sector=40,
                    factor_pattern=65,
                    volume_ratio=2.1,
                    drawdown_from_high=5.0,
                    change=3.0,
                    macro_mode="active",
                    regime="BULL_TREND",
                    limit_up_count=80,
                    limit_down_count=2,
                    sector_ma10_ratio=82,
                    market_index_change=0.1,
                ),
                self.make_row(
                    code="late_rank",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    factor_sector=40,
                    factor_pattern=20,
                    volume_ratio=2.1,
                    drawdown_from_high=5.0,
                    change=3.0,
                    macro_mode="active",
                    regime="BULL_TREND",
                    limit_up_count=80,
                    limit_down_count=2,
                    sector_ma10_ratio=82,
                    market_index_change=0.1,
                ),
            ]
        )

        result = build_consensus_candidates(df, consensus_profile="v39", min_votes=2)

        self.assertEqual(["v39"], result["consensus_profile"].unique().tolist())
        self.assertEqual(["strong_rank"], result["code"].tolist())
        self.assertLessEqual(float(result.iloc[0]["consensus_avg_rank"]), 1.5)

    def test_v40_consensus_profile_is_registered(self):
        self.assertEqual(
            normalize_consensus_profile("v40"),
            "v40",
        )

    def test_v40_prefers_v35_primary_lane_when_available(self):
        df = pd.DataFrame(
            [
                self._v40_row("000001", factor_pattern=65.0, factor_sector=35.0),
                self._v40_row("000002", factor_pattern=20.0, factor_sector=70.0),
            ]
        )

        result = build_consensus_candidates(df, consensus_profile="v40", min_votes=2)

        self.assertGreaterEqual(len(result), 1)
        self.assertEqual("primary_v35", result.iloc[0]["consensus_layer"])
        self.assertEqual("v40", result.iloc[0]["consensus_profile"])

    def test_v40_uses_gap_fill_when_primary_lane_is_empty(self):
        df = pd.DataFrame(
            [
                self._v40_row(
                    "000001",
                    macro_mode="cautious",
                    limit_down_count=10,
                    factor_pattern=50.0,
                ),
                self._v40_row(
                    "000002",
                    macro_mode="active",
                    limit_down_count=8,
                    sector_ma10_ratio=60.0,
                    factor_pattern=30.0,
                    factor_sector=35.0,
                    volume_ratio=2.0,
                    drawdown_from_high=4.5,
                    factor_wyckoff=68.0,
                ),
            ]
        )

        result = build_consensus_candidates(df, consensus_profile="v40", min_votes=2)

        self.assertGreaterEqual(len(result), 1)
        self.assertEqual("gap_fill", result.iloc[0]["consensus_layer"])
        self.assertIn("gap_fill_score", result.columns)
        self.assertEqual("v40", result.iloc[0]["consensus_profile"])

    def test_v40_gap_fill_rejects_high_risk_candidates(self):
        df = pd.DataFrame(
            [
                self._v40_row(
                    "000001",
                    macro_mode="cautious",
                    limit_down_count=10,
                    factor_pattern=50.0,
                    volume_ratio=3.4,
                    drawdown_from_high=9.0,
                    factor_wyckoff=45.0,
                )
            ]
        )

        result = build_consensus_candidates(df, consensus_profile="v40", min_votes=2)

        self.assertEqual(0, len(result))

    def test_v41_consensus_profile_is_registered(self):
        self.assertEqual(
            normalize_consensus_profile("v41"),
            "v41",
        )

    def test_v41_keeps_only_strong_rank_high_pattern_not_overheated_breadth(self):
        df = pd.DataFrame(
            [
                self.make_row(
                    code="good",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    factor_sector=35,
                    factor_pattern=65,
                    volume_ratio=2.1,
                    drawdown_from_high=5.0,
                    change=3.0,
                    macro_mode="active",
                    regime="BULL_TREND",
                    limit_up_count=80,
                    limit_down_count=2,
                    sector_ma10_ratio=44,
                    market_index_change=0.1,
                ),
                self.make_row(
                    code="low_pattern",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    factor_sector=35,
                    factor_pattern=30,
                    volume_ratio=2.1,
                    drawdown_from_high=5.0,
                    change=3.0,
                    macro_mode="active",
                    regime="BULL_TREND",
                    limit_up_count=80,
                    limit_down_count=2,
                    sector_ma10_ratio=44,
                    market_index_change=0.1,
                ),
                self.make_row(
                    code="overheated",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    factor_sector=35,
                    factor_pattern=70,
                    volume_ratio=2.1,
                    drawdown_from_high=5.0,
                    change=3.0,
                    macro_mode="active",
                    regime="BULL_TREND",
                    limit_up_count=80,
                    limit_down_count=2,
                    sector_ma10_ratio=82,
                    market_index_change=0.1,
                ),
            ]
        )

        result = build_consensus_candidates(df, consensus_profile="v41", min_votes=2)

        self.assertEqual(["v41"], result["consensus_profile"].unique().tolist())
        self.assertEqual(["good"], result["code"].tolist())

    def test_v42_can_keep_low_pattern_when_rank_and_breadth_pass(self):
        df = pd.DataFrame(
            [
                self.make_row(
                    code="low_pattern_but_ranked",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    factor_sector=35,
                    factor_pattern=30,
                    volume_ratio=2.1,
                    drawdown_from_high=5.0,
                    change=3.0,
                    macro_mode="active",
                    regime="BULL_TREND",
                    limit_up_count=80,
                    limit_down_count=2,
                    sector_ma10_ratio=44,
                    market_index_change=0.1,
                ),
            ]
        )

        result = build_consensus_candidates(df, consensus_profile="v42", min_votes=2)

        self.assertEqual(["v42"], result["consensus_profile"].unique().tolist())
        self.assertEqual(["low_pattern_but_ranked"], result["code"].tolist())

    def test_v43_keeps_cautious_rank_two_consensus(self):
        df = pd.DataFrame(
            [
                self.make_row(
                    code="cautious_rank",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    factor_sector=35,
                    factor_pattern=30,
                    volume_ratio=2.1,
                    drawdown_from_high=5.0,
                    change=3.0,
                    macro_mode="cautious",
                    regime="BULL_TREND",
                    limit_up_count=80,
                    limit_down_count=10,
                    sector_ma10_ratio=82,
                    market_index_change=0.1,
                ),
                self.make_row(
                    code="active_rank",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    factor_sector=35,
                    factor_pattern=70,
                    volume_ratio=2.1,
                    drawdown_from_high=5.0,
                    change=3.0,
                    macro_mode="active",
                    regime="BULL_TREND",
                    limit_up_count=80,
                    limit_down_count=2,
                    sector_ma10_ratio=44,
                    market_index_change=0.1,
                ),
            ]
        )

        result = build_consensus_candidates(df, consensus_profile="v43", min_votes=2)

        self.assertEqual(["v43"], result["consensus_profile"].unique().tolist())
        self.assertEqual(["cautious_rank"], result["code"].tolist())

    def test_v44_keeps_pattern_with_low_down_pressure(self):
        df = pd.DataFrame(
            [
                self.make_row(
                    code="pattern_low_down",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    factor_sector=35,
                    factor_pattern=55,
                    volume_ratio=2.1,
                    drawdown_from_high=5.0,
                    change=3.0,
                    macro_mode="active",
                    regime="BULL_TREND",
                    limit_up_count=80,
                    limit_down_count=4,
                    sector_ma10_ratio=44,
                    market_index_change=0.1,
                ),
                self.make_row(
                    code="pattern_high_down",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    factor_sector=35,
                    factor_pattern=70,
                    volume_ratio=2.1,
                    drawdown_from_high=5.0,
                    change=3.0,
                    macro_mode="active",
                    regime="BULL_TREND",
                    limit_up_count=80,
                    limit_down_count=18,
                    sector_ma10_ratio=44,
                    market_index_change=0.1,
                ),
            ]
        )

        result = build_consensus_candidates(df, consensus_profile="v44", min_votes=2)

        self.assertEqual(["v44"], result["consensus_profile"].unique().tolist())
        self.assertEqual(["pattern_low_down"], result["code"].tolist())

    def test_live_postprocess_can_select_v39_high_confidence_consensus(self):
        df = pd.DataFrame(
            [
                self.make_row(
                    code="strong_rank",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    factor_sector=40,
                    factor_pattern=65,
                    volume_ratio=2.1,
                    drawdown_from_high=5.0,
                    change=3.0,
                    macro_mode="active",
                    regime="BULL_TREND",
                    limit_up_count=80,
                    limit_down_count=2,
                    sector_ma10_ratio=82,
                    market_index_change=0.1,
                ),
                self.make_row(
                    code="late_rank",
                    factor_inflow=100,
                    factor_wyckoff=68,
                    factor_sector=40,
                    factor_pattern=20,
                    volume_ratio=2.1,
                    drawdown_from_high=5.0,
                    change=3.0,
                    macro_mode="active",
                    regime="BULL_TREND",
                    limit_up_count=80,
                    limit_down_count=2,
                    sector_ma10_ratio=82,
                    market_index_change=0.1,
                ),
            ]
        )

        result = apply_live_short_postprocess(df, consensus_profile="v39")

        self.assertEqual(["strong_rank"], result["code"].tolist())
        self.assertEqual(["v39"], result["consensus_profile"].unique().tolist())

    def test_live_postprocess_without_consensus_keeps_existing_profile_path(self):
        df = pd.DataFrame(
            [
                self.make_row(code="low_score", score=10),
                self.make_row(code="high_score", score=90),
            ]
        )

        result = apply_live_short_postprocess(df, score_order="desc")

        self.assertEqual(["high_score", "low_score"], result["code"].tolist())
        self.assertEqual(["original"], result["factor_profile"].unique().tolist())
        self.assertEqual(["none"], result["style_gate"].unique().tolist())

    def test_live_observation_candidates_use_best_balance_without_strong_duplicates(self):
        df = pd.DataFrame(
            [
                self.make_row(
                    code="strong_rank",
                    score=92,
                    factor_inflow=100,
                    factor_wyckoff=68,
                    factor_sector=40,
                    factor_pattern=65,
                    volume_ratio=2.1,
                    drawdown_from_high=5.0,
                    change=3.0,
                    macro_mode="active",
                    regime="BULL_TREND",
                    limit_up_count=80,
                    limit_down_count=2,
                    sector_ma10_ratio=92,
                    market_index_change=0.1,
                    market_style="weak_momentum",
                ),
                self.make_row(
                    code="weak_breadth",
                    score=88,
                    factor_inflow=82,
                    factor_wyckoff=62,
                    factor_sector=48,
                    factor_pattern=58,
                    volume_ratio=2.0,
                    drawdown_from_high=4.0,
                    change=2.2,
                    macro_mode="active",
                    regime="BULL_TREND",
                    limit_up_count=70,
                    limit_down_count=2,
                    sector_ma10_ratio=94,
                    market_index_change=0.1,
                    market_style="weak_momentum",
                ),
                self.make_row(
                    code="weak_breadth_2",
                    score=84,
                    factor_inflow=80,
                    factor_wyckoff=60,
                    factor_sector=45,
                    factor_pattern=55,
                    volume_ratio=1.9,
                    drawdown_from_high=4.5,
                    change=1.8,
                    macro_mode="active",
                    regime="BULL_TREND",
                    limit_up_count=70,
                    limit_down_count=2,
                    sector_ma10_ratio=93,
                    market_index_change=0.1,
                    market_style="weak_momentum",
                ),
            ]
        )

        result = build_live_observation_candidates(
            df,
            profile="best_balance",
            top_n=2,
            exclude_codes=["strong_rank"],
        )

        self.assertEqual(["weak_breadth_2"], result["code"].tolist())
        self.assertEqual(["best_balance"], result["observe_profile"].unique().tolist())
        self.assertEqual(["OBSERVE_CANDIDATE"], result["recommendation_layer"].unique().tolist())


if __name__ == "__main__":
    unittest.main()
