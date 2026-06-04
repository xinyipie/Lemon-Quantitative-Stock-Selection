import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test import select_periods, select_scenarios, select_topn_values
import config


class TestRunnerConfig(unittest.TestCase):
    def test_v5_scenario_is_registered(self):
        args = SimpleNamespace(scenario="profile_v4_adaptive_quality_v5", matrix=False)

        scenarios = select_scenarios(args)

        self.assertEqual(scenarios[0]["label"], "profile_v4_adaptive_quality_v5")
        self.assertEqual(scenarios[0]["factor_profile"], "profile_v4")
        self.assertEqual(scenarios[0]["style_gate"], "adaptive_quality_v5")

    def test_v6_scenario_is_registered(self):
        args = SimpleNamespace(scenario="profile_v4_adaptive_quality_v6", matrix=False)

        scenarios = select_scenarios(args)

        self.assertEqual(scenarios[0]["label"], "profile_v4_adaptive_quality_v6")
        self.assertEqual(scenarios[0]["factor_profile"], "profile_v4")
        self.assertEqual(scenarios[0]["style_gate"], "adaptive_quality_v6")

    def test_v7_sector_penalty_scenarios_are_registered(self):
        args = SimpleNamespace(
            scenario="profile_v4_adaptive_quality_v7_sector_light,profile_v4_adaptive_quality_v7_sector_strict",
            matrix=False,
        )

        scenarios = select_scenarios(args)

        self.assertEqual(scenarios[0]["short_filter_profile"], "sector_penalty_light")
        self.assertEqual(scenarios[1]["short_filter_profile"], "sector_penalty_strict")
        self.assertEqual(scenarios[0]["style_gate"], "adaptive_quality_v6")
        self.assertEqual(scenarios[1]["style_gate"], "adaptive_quality_v6")

    def test_v8_sector_rank_scenario_is_registered(self):
        args = SimpleNamespace(scenario="profile_v4_adaptive_quality_v8_sector_rank", matrix=False)

        scenarios = select_scenarios(args)

        self.assertEqual(scenarios[0]["factor_profile"], "profile_v8_sector_rank")
        self.assertEqual(scenarios[0]["style_gate"], "adaptive_quality_v6")
        self.assertEqual(scenarios[0].get("short_filter_profile", "baseline"), "baseline")

    def test_v9_sector_quality_guard_scenario_is_registered(self):
        args = SimpleNamespace(scenario="profile_v4_adaptive_quality_v9_sector_quality_guard", matrix=False)

        scenarios = select_scenarios(args)

        self.assertEqual(scenarios[0]["factor_profile"], "profile_v9_sector_quality_guard")
        self.assertEqual(scenarios[0]["style_gate"], "adaptive_quality_v6")
        self.assertEqual(scenarios[0].get("short_filter_profile", "baseline"), "baseline")

    def test_v10_mid_deep_drawdown_guard_scenario_is_registered(self):
        args = SimpleNamespace(scenario="profile_v4_adaptive_quality_v10_mid_deep_drawdown_guard", matrix=False)

        scenarios = select_scenarios(args)

        self.assertEqual(scenarios[0]["factor_profile"], "profile_v10_mid_deep_drawdown_guard")
        self.assertEqual(scenarios[0]["style_gate"], "adaptive_quality_v6")
        self.assertEqual(scenarios[0].get("short_filter_profile", "baseline"), "baseline")

    def test_v11_mid_deep_drawdown_strict_guard_scenario_is_registered(self):
        args = SimpleNamespace(scenario="profile_v4_adaptive_quality_v11_mid_deep_drawdown_strict_guard", matrix=False)

        scenarios = select_scenarios(args)

        self.assertEqual(scenarios[0]["factor_profile"], "profile_v11_mid_deep_drawdown_strict_guard")
        self.assertEqual(scenarios[0]["style_gate"], "adaptive_quality_v6")
        self.assertEqual(scenarios[0].get("short_filter_profile", "baseline"), "baseline")

    def test_default_core_scenario_uses_v9_candidate(self):
        args = SimpleNamespace(scenario=None, matrix=False)

        scenarios = select_scenarios(args)

        self.assertEqual(scenarios[1]["label"], "profile_v4_adaptive_quality_v9_sector_quality_guard")

    def test_live_short_config_uses_v9_candidate(self):
        self.assertEqual(config.SHORT_LIVE_FACTOR_PROFILE, "profile_v9_sector_quality_guard")
        self.assertEqual(config.SHORT_LIVE_STYLE_GATE, "adaptive_quality_v6")
        self.assertEqual(config.SHORT_LIVE_SCORE_ORDER, "desc")

    def test_live_report_defaults_to_short_only(self):
        self.assertFalse(config.ENABLE_LONGTERM_LIVE)

    def test_monthly_periods_cover_calendar_year(self):
        args = SimpleNamespace(
            start=None,
            end=None,
            label="custom",
            monthly="2025",
            full=False,
            matrix=False,
        )

        periods = select_periods(args)

        self.assertEqual(len(periods), 12)
        self.assertEqual(periods[0], {"label": "2025M01", "start": "20250101", "end": "20250131"})
        self.assertEqual(periods[1], {"label": "2025M02", "start": "20250201", "end": "20250228"})
        self.assertEqual(periods[-1], {"label": "2025M12", "start": "20251201", "end": "20251231"})

    def test_monthly_rejects_custom_start_end(self):
        args = SimpleNamespace(
            start="20250101",
            end="20250131",
            label="custom",
            monthly="2025",
            full=False,
            matrix=False,
        )

        with self.assertRaises(SystemExit):
            select_periods(args)

    def test_topn_grid_defaults_to_single_topn(self):
        args = SimpleNamespace(topn="3", topn_grid=None)

        self.assertEqual(select_topn_values(args), [3])

    def test_topn_grid_parses_multiple_values(self):
        args = SimpleNamespace(topn="3", topn_grid="3,5,8")

        self.assertEqual(select_topn_values(args), [3, 5, 8])


if __name__ == "__main__":
    unittest.main()
