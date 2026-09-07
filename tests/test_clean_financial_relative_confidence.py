import unittest

import pandas as pd

from research.clean_financial_abstention import daily_top_with_margin
from research.clean_financial_relative_confidence import enforce_same_stock_cooldown


class CleanFinancialRelativeConfidenceTest(unittest.TestCase):
    def test_daily_top_contains_cross_sectional_z_scores(self):
        frame = pd.DataFrame(
            {
                "trade_date": ["20200102", "20200102", "20200102"],
                "ts_code": ["A", "B", "C"],
                "prediction": [3.0, 2.0, 1.0],
            }
        )
        top = daily_top_with_margin(frame)
        self.assertAlmostEqual(float(top.iloc[0]["prediction_z"]), 1.0)
        self.assertAlmostEqual(float(top.iloc[0]["prediction_margin_z"]), 1.0)

    def test_same_stock_cooldown_does_not_replace(self):
        selected = pd.DataFrame(
            {
                "trade_date": [f"202001{day:02d}" for day in range(1, 11)],
                "ts_code": ["A"] * 10,
                "prediction": list(range(10)),
            }
        )
        kept = enforce_same_stock_cooldown(
            selected,
            selected["trade_date"].tolist(),
            cooldown_days=8,
        )
        self.assertEqual(kept["trade_date"].tolist(), ["20200101", "20200109"])
        self.assertEqual(kept["ts_code"].tolist(), ["A", "A"])


if __name__ == "__main__":
    unittest.main()
