import unittest
from unittest.mock import patch

import news_analyzer


class NewsAnalyzerTest(unittest.TestCase):
    def test_get_policy_news_prefers_rich_market_news_provider(self):
        raw_news = [
            {
                "title": "设备更新项目清单下达",
                "source": "财联社",
                "provider": "cls_key",
                "publish_time": "2026-06-18 09:30:00",
                "url": "https://example.com/news/1",
                "content_excerpt": "2000亿设备更新清单即将下达，利好制造业。",
            }
        ]

        with patch("news_analyzer.fetch_market_news", return_value=raw_news):
            df = news_analyzer.get_policy_news(days=3)

        self.assertEqual(df.iloc[0]["title"], "设备更新项目清单下达")
        self.assertEqual(df.iloc[0]["source"], "财联社")
        self.assertEqual(df.iloc[0]["url"], "https://example.com/news/1")
        self.assertIn("利好制造业", df.iloc[0]["content"])


if __name__ == "__main__":
    unittest.main()
