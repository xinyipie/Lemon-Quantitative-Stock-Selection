import unittest
from datetime import datetime, timedelta

from news_source_provider import _filter_recent_records, _news_sort_key, _normalize_news_timing


class NewsFreshnessGateTest(unittest.TestCase):
    def test_url_date_is_used_before_recent_filter(self):
        recent = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
        item = _normalize_news_timing(
            {"title": "recent", "publish_time": "", "url": f"https://example.com/{recent}/article"}
        )

        self.assertEqual(item["publish_time_source"], "url")
        self.assertEqual(item["freshness_bucket"], "fresh")
        self.assertEqual(_filter_recent_records([item], days=5), [item])

    def test_old_or_unknown_news_is_rejected(self):
        old = (datetime.now() - timedelta(days=8)).strftime("%Y-%m-%d")
        old_item = _normalize_news_timing(
            {"title": "old", "publish_time": "", "url": f"https://example.com/{old}/article"}
        )
        unknown_item = _normalize_news_timing(
            {"title": "unknown", "publish_time": "", "url": "https://example.com/article"}
        )

        self.assertEqual(_filter_recent_records([old_item, unknown_item], days=5), [])

    def test_newer_news_sorts_before_higher_value_old_news(self):
        newer = {"title": "new", "publish_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "news_value_score": 20}
        older = {"title": "old", "publish_time": (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S"), "news_value_score": 100}

        self.assertGreater(_news_sort_key(newer), _news_sort_key(older))


if __name__ == "__main__":
    unittest.main()
