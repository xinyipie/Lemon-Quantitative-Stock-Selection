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
            "生物制药",
            {"生物制药": False},
            None,
            "baseline",
        )

        self.assertTrue(blocked)
        self.assertEqual(penalty, 0.0)

    def test_sector_penalty_light_keeps_candidate_with_penalty(self):
        blocked, penalty = main._short_sector_gate_action(
            "生物制药",
            {"生物制药": False},
            None,
            "sector_penalty_light",
        )

        self.assertFalse(blocked)
        self.assertEqual(penalty, 6.0)

    def test_sector_penalty_strict_uses_larger_penalty(self):
        blocked, penalty = main._short_sector_gate_action(
            "生物制药",
            {"生物制药": False},
            None,
            "sector_penalty_strict",
        )

        self.assertFalse(blocked)
        self.assertEqual(penalty, 12.0)


if __name__ == "__main__":
    unittest.main()
