import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from longterm_factor_stability_audit import (
    factor_stability,
    make_observation_table,
)


class LongtermFactorStabilityAuditTest(unittest.TestCase):
    def make_frame(self):
        rows = []
        for stage in ["2024H2", "2025H2"]:
            rows.extend(
                [
                    {
                        "source_label": f"{stage}_v5",
                        "stage": stage,
                        "select_date": "20250102",
                        "ts_code": f"smooth_{stage}.SZ",
                        "name": "smooth",
                        "ret_40d": 18.0,
                        "mfe_40d": 24.0,
                        "mae_40d": -4.0,
                        "turnover": 2.0,
                        "price_vs_ma60": 5.0,
                        "industry_rs": 8.0,
                    },
                    {
                        "source_label": f"{stage}_v5",
                        "stage": stage,
                        "select_date": "20250102",
                        "ts_code": f"bad_{stage}.SZ",
                        "name": "bad",
                        "ret_40d": -12.0,
                        "mfe_40d": 3.0,
                        "mae_40d": -15.0,
                        "turnover": 8.0,
                        "price_vs_ma60": 15.0,
                        "industry_rs": 3.0,
                    },
                ]
            )
        return pd.DataFrame(rows)

    def test_make_observation_table_compares_smooth_and_bad_by_stage(self):
        obs = make_observation_table(self.make_frame(), horizon=40)

        self.assertEqual(len(obs), 6)
        turnover = obs[(obs["stage"] == "2024H2") & (obs["factor"] == "turnover")].iloc[0]
        self.assertEqual(turnover["direction"], "bad_higher")
        self.assertEqual(turnover["bad_minus_smooth"], 6.0)

    def test_factor_stability_keeps_consistent_cross_stage_directions(self):
        stable = factor_stability(make_observation_table(self.make_frame(), horizon=40), min_observations=2)

        turnover = stable[stable["factor"] == "turnover"].iloc[0]
        industry = stable[stable["factor"] == "industry_rs"].iloc[0]

        self.assertEqual(turnover["dominant_direction"], "bad_higher")
        self.assertEqual(turnover["consistent_count"], 2)
        self.assertEqual(industry["dominant_direction"], "bad_lower")


if __name__ == "__main__":
    unittest.main()
