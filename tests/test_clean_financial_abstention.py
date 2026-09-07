import unittest

import pandas as pd

from research.clean_financial_abstention import (
    apply_confidence_gate,
    calibration_thresholds,
    daily_top_with_margin,
)


class CleanFinancialAbstentionTest(unittest.TestCase):
    def test_daily_top_is_locked_before_gate(self):
        frame = pd.DataFrame(
            {
                "trade_date": ["20200102", "20200102"],
                "ts_code": ["A", "B"],
                "prediction": [1.2, 1.0],
            }
        )
        top = daily_top_with_margin(frame)
        selected = apply_confidence_gate(top, score_threshold=1.3, margin_threshold=0.0)
        self.assertEqual(top["ts_code"].tolist(), ["A"])
        self.assertTrue(selected.empty)

    def test_margin_uses_second_place(self):
        frame = pd.DataFrame(
            {
                "trade_date": ["20200102", "20200102", "20200102"],
                "ts_code": ["B", "A", "C"],
                "prediction": [1.0, 1.2, 0.1],
            }
        )
        top = daily_top_with_margin(frame)
        self.assertAlmostEqual(float(top.iloc[0]["prediction_margin"]), 0.2)

    def test_thresholds_only_use_calibration_values(self):
        calibration = pd.DataFrame(
            {
                "prediction": [1.0, 2.0, 3.0, 4.0],
                "prediction_margin": [0.1, 0.2, 0.3, 0.4],
            }
        )
        score, margin = calibration_thresholds(calibration, 0.75, 0.50)
        self.assertAlmostEqual(score, 3.25)
        self.assertAlmostEqual(margin, 0.25)


if __name__ == "__main__":
    unittest.main()
