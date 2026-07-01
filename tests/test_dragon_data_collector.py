import tempfile
import unittest
from pathlib import Path

import pandas as pd

from research.dragon_data_collector import (
    collect_dragon_aux_range,
    normalize_hot_rank_detail,
    normalize_lhb_detail,
)


class FakeAk:
    def stock_zt_pool_dtgc_em(self, date):
        return pd.DataFrame([{"代码": "000001", "名称": "跌停A", "涨跌幅": -10, "所属行业": "测试"}])

    def stock_zt_pool_sub_new_em(self, date):
        return pd.DataFrame([{"代码": "000002", "名称": "次新B", "涨跌幅": 5, "所属行业": "测试"}])

    def stock_lhb_detail_em(self, start_date, end_date):
        return pd.DataFrame(
            [
                {
                    "代码": "000003",
                    "名称": "龙虎C",
                    "上榜日": start_date,
                    "龙虎榜净买额": 12000000,
                    "龙虎榜买入额": 30000000,
                    "龙虎榜卖出额": 18000000,
                    "龙虎榜成交额": 48000000,
                    "上榜原因": "日涨幅偏离值达7%",
                }
            ]
        )


class DragonDataCollectorTest(unittest.TestCase):
    def test_normalize_lhb_detail_keeps_hot_money_fields(self):
        raw = pd.DataFrame(
            [
                {
                    "代码": "000001",
                    "名称": "样本A",
                    "上榜日": "2026-06-20",
                    "龙虎榜净买额": 1000,
                    "龙虎榜买入额": 3000,
                    "龙虎榜卖出额": 2000,
                    "龙虎榜成交额": 5000,
                    "上榜原因": "换手率达20%",
                }
            ]
        )

        result = normalize_lhb_detail(raw)

        self.assertEqual(result.loc[0, "trade_date"], "20260620")
        self.assertEqual(result.loc[0, "ts_code"], "000001.SZ")
        self.assertEqual(result.loc[0, "lhb_net_buy"], 1000)
        self.assertEqual(result.loc[0, "lhb_reason"], "换手率达20%")

    def test_normalize_hot_rank_detail_uses_history_rank(self):
        raw = pd.DataFrame(
            [
                {"时间": "2026-06-20", "排名": 88, "证券代码": "SZ000001", "新晋粉丝": 0.6, "铁杆粉丝": 0.4}
            ]
        )

        result = normalize_hot_rank_detail(raw, ts_code="000001.SZ")

        self.assertEqual(result.loc[0, "trade_date"], "20260620")
        self.assertEqual(result.loc[0, "ts_code"], "000001.SZ")
        self.assertEqual(result.loc[0, "hot_rank"], 88)

    def test_collect_dragon_aux_range_writes_aux_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = collect_dragon_aux_range(
                start_date="20260620",
                end_date="20260620",
                trade_dates=["20260620"],
                output_root=tmp,
                ak_module=FakeAk(),
                sleep_seconds=0,
            )

            self.assertEqual(result["total_days"], 1)
            self.assertTrue((Path(tmp) / "dragon_aux" / "dt_pool" / "20260620.parquet").exists())
            self.assertTrue((Path(tmp) / "dragon_aux" / "sub_new_pool" / "20260620.parquet").exists())
            self.assertTrue((Path(tmp) / "dragon_aux" / "lhb_detail" / "20260620.parquet").exists())


if __name__ == "__main__":
    unittest.main()
