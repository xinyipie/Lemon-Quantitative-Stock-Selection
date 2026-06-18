import unittest

import pandas as pd

from concept_heat_provider import fetch_real_concept_heat


class FakeAkShare:
    def __init__(self, em_df=None, ths_names=None, ths_info=None):
        self.em_df = em_df
        self.ths_names = ths_names
        self.ths_info = ths_info or {}

    def stock_board_concept_name_em(self):
        if isinstance(self.em_df, Exception):
            raise self.em_df
        return self.em_df

    def stock_board_concept_summary_ths(self):
        return self.ths_names

    def stock_board_concept_info_ths(self, symbol):
        value = self.ths_info[symbol]
        if isinstance(value, Exception):
            raise value
        return value


class ConceptHeatProviderTest(unittest.TestCase):
    def test_fetches_and_normalizes_eastmoney_concepts_first(self):
        em_df = pd.DataFrame(
            [
                {"板块名称": "机器人概念", "涨跌幅": 3.2, "换手率": 4.5, "板块代码": "BK001"},
                {"板块名称": "下跌概念", "涨跌幅": -1.0, "换手率": 8.0, "板块代码": "BK002"},
            ]
        )

        items = fetch_real_concept_heat(top_n=5, ak_module=FakeAkShare(em_df=em_df))

        self.assertEqual(items[0]["concept"], "机器人概念")
        self.assertEqual(items[0]["change"], 3.2)
        self.assertEqual(items[0]["source"], "eastmoney")
        self.assertGreater(items[0]["heat"], 0)
        self.assertEqual(len(items), 1)

    def test_falls_back_to_ths_recent_concepts_when_eastmoney_fails(self):
        ths_names = pd.DataFrame(
            [
                {"日期": "2026-06-18", "概念名称": "AI应用", "驱动事件": "产业消息催化"},
                {"日期": "2026-06-17", "概念名称": "水电概念", "驱动事件": "订单需求改善"},
            ]
        )
        ths_info = {
            "AI应用": pd.DataFrame([{"项目": "板块涨幅", "值": "2.50%"}, {"项目": "涨跌家数", "值": "30/10"}]),
            "水电概念": pd.DataFrame([{"项目": "板块涨幅", "值": "-1.20%"}, {"项目": "涨跌家数", "值": "9/21"}]),
        }

        items = fetch_real_concept_heat(
            top_n=5,
            ths_probe_size=5,
            ak_module=FakeAkShare(em_df=ConnectionError("blocked"), ths_names=ths_names, ths_info=ths_info),
        )

        self.assertEqual(items[0]["concept"], "AI应用")
        self.assertEqual(items[0]["change"], 2.5)
        self.assertEqual(items[0]["source"], "ths")
        self.assertIn("产业消息催化", items[0]["reason"])
        self.assertEqual(len(items), 1)


if __name__ == "__main__":
    unittest.main()
