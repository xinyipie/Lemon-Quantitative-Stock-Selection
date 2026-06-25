import os
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("LEMON_SKIP_TUSHARE_INIT", "1")

import main


class OnlineProShouldNotBeCalled:
    def fina_indicator(self, *args, **kwargs):
        raise AssertionError("online fina_indicator should not be called when local cache exists")


class LongtermProfitGrowthTest(unittest.TestCase):
    def test_profit_growth_prefers_local_fina_indicator_cache(self):
        old_pro = main.pro
        main.set_pro(OnlineProShouldNotBeCalled())
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                cache_path = Path(tmpdir) / "fina_indicator.parquet"
                pd.DataFrame(
                    [
                        {
                            "ts_code": "000001.SZ",
                            "ann_date": "20260430",
                            "end_date": "20260331",
                            "netprofit_yoy": 24.0,
                        },
                        {
                            "ts_code": "000001.SZ",
                            "ann_date": "20251030",
                            "end_date": "20250930",
                            "netprofit_yoy": 18.0,
                        },
                    ]
                ).to_parquet(cache_path, index=False)

                result = main.get_net_profit_growth_batch(
                    ["000001"],
                    trade_date="20260623",
                    cache_path=cache_path,
                )
        finally:
            main.pro = old_pro

        self.assertEqual(result["000001"]["netprofit_yoy"], 24.0)
        self.assertTrue(result["000001"]["profit_growth_accel"])


if __name__ == "__main__":
    unittest.main()
