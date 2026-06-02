import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test import select_scenarios


class TestRunnerConfig(unittest.TestCase):
    def test_v5_scenario_is_registered(self):
        args = SimpleNamespace(scenario="profile_v4_adaptive_quality_v5", matrix=False)

        scenarios = select_scenarios(args)

        self.assertEqual(scenarios[0]["label"], "profile_v4_adaptive_quality_v5")
        self.assertEqual(scenarios[0]["factor_profile"], "profile_v4")
        self.assertEqual(scenarios[0]["style_gate"], "adaptive_quality_v5")


if __name__ == "__main__":
    unittest.main()
