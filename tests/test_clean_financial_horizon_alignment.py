import unittest

from research.clean_financial_event_hgb import FEATURE_COLUMNS


class CleanFinancialHorizonAlignmentTest(unittest.TestCase):
    def test_future_targets_are_not_features(self):
        for column in ("ret_3d", "ret_5d", "ret_8d", "entry_open", "entry_gap_pct"):
            self.assertNotIn(column, FEATURE_COLUMNS)


if __name__ == "__main__":
    unittest.main()
