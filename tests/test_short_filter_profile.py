import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("LEMON_SKIP_TUSHARE_INIT", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config

config.LOG_FILE_PATH = os.path.join(tempfile.gettempdir(), "lemon_quant_test.log")

import main


class ShortFilterProfileTest(unittest.TestCase):
    def test_baseline_blocks_sector_below_ma10(self):
        blocked, penalty = main._short_sector_gate_action(
            "biomed",
            {"biomed": False},
            None,
            "baseline",
        )

        self.assertTrue(blocked)
        self.assertEqual(penalty, 0.0)

    def test_sector_penalty_light_keeps_candidate_with_penalty(self):
        blocked, penalty = main._short_sector_gate_action(
            "biomed",
            {"biomed": False},
            None,
            "sector_penalty_light",
        )

        self.assertFalse(blocked)
        self.assertEqual(penalty, 6.0)

    def test_sector_penalty_strict_uses_larger_penalty(self):
        blocked, penalty = main._short_sector_gate_action(
            "biomed",
            {"biomed": False},
            None,
            "sector_penalty_strict",
        )

        self.assertFalse(blocked)
        self.assertEqual(penalty, 12.0)

    def test_short_live_risk_guard_does_not_block_by_manual_event_blacklist(self):
        blocked, reasons = main.short_live_risk_guard(
            {"code": "002217", "name": "sample"},
            {},
        )

        self.assertFalse(blocked)
        self.assertEqual(reasons, [])

    def test_short_live_risk_guard_blocks_severe_financial_distress(self):
        blocked, reasons = main.short_live_risk_guard(
            {"code": "000001", "name": "risk_sample"},
            {"roe": -25.0, "debt_ratio": 92.0, "revenue_growth": -60.0},
        )

        self.assertTrue(blocked)
        reason_text = ";".join(reasons)
        self.assertIn("ROE", reason_text)
        self.assertEqual(len(reasons), 3)

    def test_short_live_risk_guard_blocks_profit_collapse_with_weak_roe(self):
        blocked, reasons = main.short_live_risk_guard(
            {"code": "002217", "name": "profit_collapse_sample"},
            {"roe": 0.04, "debt_ratio": 26.3, "netprofit_yoy": -79.7},
        )

        self.assertTrue(blocked)
        self.assertGreaterEqual(len(reasons), 1)

    def test_short_live_risk_guard_keeps_normal_candidate(self):
        blocked, reasons = main.short_live_risk_guard(
            {"code": "000001", "name": "normal_sample"},
            {"roe": 8.0, "debt_ratio": 55.0, "revenue_growth": -5.0},
        )

        self.assertFalse(blocked)
        self.assertEqual(reasons, [])


if __name__ == "__main__":
    unittest.main()
