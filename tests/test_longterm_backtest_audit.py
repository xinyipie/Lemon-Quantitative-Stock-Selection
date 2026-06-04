import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from longterm_backtest_audit import audit_trades


class LongtermBacktestAuditTest(unittest.TestCase):
    def test_audit_detects_overlapping_exposure_and_duplicate_positions(self):
        trades = pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "buy_date": "20250102", "sell_date": "20250110", "profit_after_fee": 5.0, "exit_reason": "weak_close_exit"},
                {"ts_code": "000001.SZ", "buy_date": "20250103", "sell_date": "20250108", "profit_after_fee": -3.0, "exit_reason": "stop_loss"},
                {"ts_code": "000002.SZ", "buy_date": "20250103", "sell_date": "20250109", "profit_after_fee": 2.0, "exit_reason": "trailing_stop"},
                {"ts_code": "000003.SZ", "buy_date": "20250103", "sell_date": "20250109", "profit_after_fee": 1.0, "exit_reason": "trailing_stop"},
            ]
        )

        result = audit_trades(trades, top_n=3)

        self.assertEqual(result["total_trades"], 4)
        self.assertGreater(result["max_open_positions"], 3)
        self.assertGreater(result["max_slot_exposure_pct"], 100)
        self.assertEqual(result["duplicate_overlap_count"], 1)
        self.assertIn("000001.SZ", result["duplicate_overlap_examples"][0])


if __name__ == "__main__":
    unittest.main()
