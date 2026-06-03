import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

os.environ.setdefault("LEMON_SKIP_TUSHARE_INIT", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config

config.LOG_FILE_PATH = os.path.join(tempfile.gettempdir(), "lemon_quant_test.log")

import main


class FakePro:
    def __init__(self):
        self.holdertrade_calls = []

    def share_float(self, **kwargs):
        return pd.DataFrame(columns=["ts_code"])

    def stk_holdertrade(self, **kwargs):
        self.holdertrade_calls.append(kwargs)
        if "start_date" in kwargs or "end_date" in kwargs:
            raise AssertionError("stk_holdertrade should filter by ann_date locally")
        return pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "ann_date": "20260525", "in_de": "DE"},
                {"ts_code": "000002.SZ", "ann_date": "20260525", "in_de": "IN"},
                {"ts_code": "000003.SZ", "ann_date": "20260101", "in_de": "DE"},
            ]
        )


class RestrictedFilterTest(unittest.TestCase):
    def test_holder_trade_filters_ann_date_locally(self):
        fake_pro = FakePro()

        with patch.object(main, "pro", fake_pro):
            safe = main.filter_restricted_stocks(
                ["000001", "000002", "000003"],
                "20260603",
            )

        self.assertEqual(safe, ["000002", "000003"])
        self.assertEqual(len(fake_pro.holdertrade_calls), 3)


if __name__ == "__main__":
    unittest.main()
