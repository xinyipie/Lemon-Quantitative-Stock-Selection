import unittest

import pandas as pd

from news_source_provider import fetch_market_news, normalize_news_records


class NewsSourceProviderTest(unittest.TestCase):
    def test_normalize_news_records_keeps_source_url_and_excerpt(self):
        df = pd.DataFrame(
            [
                {
                    "标题": "设备更新项目清单下达",
                    "发布时间": "2026-06-18 09:30:00",
                    "来源": "财联社",
                    "链接": "https://example.com/news/1",
                    "内容": "2000亿设备更新清单即将下达，利好制造业。",
                }
            ]
        )

        records = normalize_news_records(df, provider="cls")

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["title"], "设备更新项目清单下达")
        self.assertEqual(records[0]["source"], "财联社")
        self.assertEqual(records[0]["provider"], "cls")
        self.assertEqual(records[0]["publish_time"], "2026-06-18 09:30:00")
        self.assertEqual(records[0]["url"], "https://example.com/news/1")
        self.assertIn("利好制造业", records[0]["content_excerpt"])

    def test_fetch_market_news_merges_duplicate_titles_across_sources(self):
        def provider_a():
            return pd.DataFrame(
                [
                    {
                        "title": "设备更新项目清单下达",
                        "time": "2026-06-18 09:30:00",
                        "source": "财联社",
                        "url": "https://example.com/a",
                        "content": "短期设备更新催化。",
                    }
                ]
            )

        def provider_b():
            return pd.DataFrame(
                [
                    {
                        "summary": " 设备更新项目清单下达 ",
                        "url": "https://example.com/b",
                        "tag": "市场动态",
                    },
                    {
                        "summary": "算力硬件板块持续领涨",
                        "url": "https://example.com/c",
                        "tag": "市场动态",
                    },
                ]
            )

        records = fetch_market_news(
            providers=[("cls", provider_a), ("caixin", provider_b)],
            limit=10,
        )

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["title"], "设备更新项目清单下达")
        self.assertEqual(records[0]["source_count"], 2)
        self.assertIn("cls", records[0]["providers"])
        self.assertIn("caixin", records[0]["providers"])
        self.assertEqual(records[1]["title"], "算力硬件板块持续领涨")

    def test_fetch_market_news_prefers_trading_value_over_latest_noise(self):
        def provider():
            return pd.DataFrame(
                [
                    {
                        "title": "端午假期食品抽检结果发布",
                        "time": "2026-06-18 16:00:00",
                        "source": "地方新闻",
                        "url": "https://example.com/noise",
                        "content": "节日消费抽检整体合格。",
                    },
                    {
                        "title": "国家发改委推进设备更新项目清单下达",
                        "time": "2026-06-18 09:00:00",
                        "source": "财联社",
                        "url": "https://example.com/equipment",
                        "content": "设备更新项目清单加速下达，利好机械设备和电力设备。",
                    },
                    {
                        "title": "算力硬件板块持续领涨",
                        "time": "2026-06-18 10:00:00",
                        "source": "东方财富",
                        "url": "https://example.com/ai",
                        "content": "算力、服务器、光模块方向资金继续聚集。",
                    },
                ]
            )

        records = fetch_market_news(providers=[("eastmoney", provider)], limit=3)

        self.assertEqual(records[0]["title"], "国家发改委推进设备更新项目清单下达")
        self.assertGreater(records[0]["news_value_score"], records[-1]["news_value_score"])
        self.assertIn("value_reason_text", records[0])
        self.assertNotEqual(records[0]["title"], "端午假期食品抽检结果发布")


if __name__ == "__main__":
    unittest.main()
