import unittest

import pandas as pd

from research.audit_clean_financial_relative_candidate import max_drawdown


class AuditCleanFinancialRelativeCandidateTest(unittest.TestCase):
    def test_max_drawdown_uses_prior_peak(self):
        nav = pd.Series([1.0, 1.1, 0.99, 1.2])
        self.assertAlmostEqual(max_drawdown(nav), -10.0)

    def test_empty_drawdown_is_zero(self):
        self.assertEqual(max_drawdown(pd.Series(dtype=float)), 0.0)


if __name__ == "__main__":
    unittest.main()
