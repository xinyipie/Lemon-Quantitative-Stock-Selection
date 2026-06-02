import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test import select_periods, select_scenarios


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


if __name__ == "__main__":
    unittest.main()
