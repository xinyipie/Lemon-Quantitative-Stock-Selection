import tempfile
import unittest
from pathlib import Path

import pandas as pd

from research.limit_pool_collector import collect_limit_pool_range


class FakeAk:
    def __init__(self):
        self.calls = []

    def stock_zt_pool_em(self, date):
        self.calls.append(("zt_pool", date))
        return pd.DataFrame(
            [
                {
                    "代码": "000001",
                    "名称": "样本A",
                    "涨跌幅": 10.0,
                    "成交额": 1000000,
                    "换手率": 2.0,
                    "封单金额": 500000,
                    "首次封板时间": "092500",
                    "开板次数": 0,
                    "连板数": 1,
                    "涨停原因": "机器人",
                    "行业": "机械设备",
                }
            ]
        )

    def stock_zt_pool_zbgc_em(self, date):
        self.calls.append(("zbgc_pool", date))
        return pd.DataFrame()

    def stock_zt_pool_previous_em(self, date):
        self.calls.append(("previous_pool", date))
        return pd.DataFrame()

    def stock_zt_pool_strong_em(self, date):
        self.calls.append(("strong_pool", date))
        return pd.DataFrame()


class LimitPoolCollectorRangeTest(unittest.TestCase):
    def test_collect_limit_pool_range_uses_trade_calendar_and_writes_each_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            calendar = ["20260102", "20260105", "20260106"]
            fake = FakeAk()

            result = collect_limit_pool_range(
                start_date="20260101",
                end_date="20260105",
                trade_dates=calendar,
                output_root=tmp,
                ak_module=fake,
                sleep_seconds=0,
            )

            self.assertEqual(result["total_days"], 2)
            self.assertEqual(result["non_empty_days"], 2)
            self.assertTrue((Path(tmp) / "limit_pool" / "20260102.parquet").exists())
            self.assertTrue((Path(tmp) / "limit_pool" / "20260105.parquet").exists())
            self.assertFalse((Path(tmp) / "limit_pool" / "20260106.parquet").exists())
            self.assertEqual(fake.calls[0], ("zt_pool", "20260102"))


if __name__ == "__main__":
    unittest.main()
