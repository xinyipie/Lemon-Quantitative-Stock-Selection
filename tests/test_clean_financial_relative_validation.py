import unittest

import pandas as pd

from research.clean_financial_relative_validation import split_walk_forward


class CleanFinancialRelativeValidationTest(unittest.TestCase):
    def test_target_year_never_enters_training_or_calibration(self):
        frame = pd.DataFrame(
            {
                "trade_date": ["20200102", "20210104", "20220104", "20230104"],
                "value": [1, 2, 3, 4],
            }
        )
        training, calibration, target = split_walk_forward(frame, 2022)
        self.assertEqual(training["value"].tolist(), [1])
        self.assertEqual(calibration["value"].tolist(), [2])
        self.assertEqual(target["value"].tolist(), [3])


if __name__ == "__main__":
    unittest.main()
