import unittest

from market_radar.events import build_event_summary, build_events_from_news_payload


class MarketRadarEventsTest(unittest.TestCase):
    def test_build_events_merges_duplicate_titles_and_keeps_raw_sources(self):
        payload = {
            "date": "20260622",
            "items": [
                {
                    "news": "两部门推动设备更新项目清单下达",
                    "type": "产业政策",
                    "sectors": ["机械设备"],
                    "impact": "positive",
                    "strength": 8,
                    "duration": "1-2周",
                    "reason": "政策支持设备更新需求",
                },
                {
                    "news": "两部门推动设备更新项目清单下达",
                    "type": "产业政策",
                    "sectors": ["电力设备"],
                    "impact": "positive",
                    "strength": 7,
                    "duration": "1-2周",
                    "reason": "电力设备也受益",
                },
            ],
            "raw_news": [
                {
                    "title": "两部门推动设备更新项目清单下达",
                    "source": "交易所快讯",
                    "provider": "official",
                    "url": "https://example.com/equipment",
                    "publish_time": "2026-06-22 08:30:00",
                    "news_value_score": 88,
                }
            ],
        }

        events = build_events_from_news_payload(payload)

        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["title"], "两部门推动设备更新项目清单下达")
        self.assertEqual(event["event_type"], "产业政策")
        self.assertEqual(event["impact"], "positive")
        self.assertEqual(event["materiality"], "A")
        self.assertEqual(event["source_quality"], "官方/监管")
        self.assertEqual(event["mapped_industries"], ["机械设备", "电力设备"])
        self.assertEqual(event["mapping_confidence"], "medium")
        self.assertEqual(event["evidence_urls"][0]["url"], "https://example.com/equipment")
        self.assertTrue(event["verification_points"])
        self.assertTrue(event["invalidation_points"])

    def test_build_events_marks_broad_mapping_as_low_confidence(self):
        payload = {
            "date": "20260622",
            "items": [
                {
                    "news": "AI产业链出口改善",
                    "type": "产业趋势",
                    "sectors": ["电子", "通信", "计算机", "传媒"],
                    "impact": "positive",
                    "strength": 6,
                    "duration": "1-3天",
                    "reason": "AI产业链较宽",
                }
            ],
            "raw_news": [
                {
                    "title": "AI产业链出口改善",
                    "source": "财经媒体",
                    "provider": "caixin",
                    "url": "https://example.com/ai",
                    "news_value_score": 65,
                }
            ],
        }

        events = build_events_from_news_payload(payload)
        summary = build_event_summary(events)

        self.assertEqual(events[0]["materiality"], "B")
        self.assertEqual(events[0]["mapping_confidence"], "broad")
        self.assertIn("泛化", events[0]["risk_note"])
        self.assertEqual(summary["event_count"], 1)
        self.assertEqual(summary["positive_count"], 1)
        self.assertEqual(summary["top_materiality"], "B")
        self.assertEqual(summary["source_count"], 1)

    def test_build_events_keeps_source_timing_and_catalyst_clock(self):
        payload = {
            "date": "20260622",
            "collected_at": "2026-06-22 20:00:00",
            "items": [
                {
                    "news": "Copper export order improves",
                    "type": "industry order",
                    "sectors": ["Copper"],
                    "impact": "positive",
                    "strength": 7,
                    "duration": "1-3d",
                    "reason": "order catalyst",
                }
            ],
            "raw_news": [
                {
                    "title": "Copper export order improves",
                    "source": "Reuters",
                    "provider": "mainstream",
                    "url": "https://example.com/copper",
                    "publish_time": "2026-06-20 09:15:00",
                    "news_value_score": 76,
                }
            ],
        }

        events = build_events_from_news_payload(payload)

        event = events[0]
        self.assertEqual(event["source_name"], "Reuters")
        self.assertEqual(event["publish_time"], "2026-06-20 09:15:00")
        self.assertEqual(event["collected_at"], "2026-06-22 20:00:00")
        self.assertEqual(event["catalyst_age_days"], 2)
        self.assertEqual(event["catalyst_clock"], "D2 发酵中")

    def test_build_events_adds_direction_source_clarity_and_jump_targets(self):
        payload = {
            "date": "20260622",
            "items": [
                {
                    "news": "US restricts access to AI models",
                    "type": "regulation",
                    "sectors": ["Computer"],
                    "impact": "negative",
                    "strength": 8,
                    "duration": "1w",
                    "reason": "risk appetite pressure",
                }
            ],
            "raw_news": [
                {
                    "title": "US restricts access to AI models",
                    "source": "Reuters",
                    "provider": "mainstream",
                    "url": "https://example.com/ai-risk",
                    "publish_time": "2026-06-22 09:15:00",
                    "news_value_score": 82,
                }
            ],
        }

        event = build_events_from_news_payload(payload)[0]

        self.assertEqual(event["impact_label"], "利空")
        self.assertEqual(event["impact_tone"], "bad")
        self.assertEqual(event["event_bucket"], "risk")
        self.assertIn("A级利空", event["impact_degree_text"])
        self.assertIn("风险偏好", event["effect_summary"])
        self.assertEqual(event["original_source"], "Reuters")
        self.assertEqual(event["collection_source"], "本地新闻缓存")
        self.assertEqual(event["source_url"], "https://example.com/ai-risk")
        self.assertEqual(event["industry_anchor"], "thesis-Computer")
        self.assertEqual(event["stock_anchor"], "stocks-Computer")

    def test_build_events_finds_raw_source_when_summary_title_is_shortened(self):
        payload = {
            "date": "20260622",
            "items": [
                {
                    "news": "美国限制外国获取AI模型",
                    "type": "国际政治",
                    "sectors": ["计算机"],
                    "impact": "negative",
                    "strength": 8,
                    "duration": "1w",
                    "reason": "限制前沿AI模型访问",
                }
            ],
            "raw_news": [
                {
                    "title": "美国政府此前从未采取如此广泛的措施，限制外国用户获取美国公司开发的前沿人工智能模型",
                    "source": "市场动态",
                    "provider": "caixin",
                    "url": "https://database.caixin.com/2026-06-15/102454182.html",
                    "publish_time": "",
                    "news_value_score": 82,
                }
            ],
        }

        event = build_events_from_news_payload(payload)[0]

        self.assertEqual(event["original_source"], "市场动态")
        self.assertEqual(event["source_url"], "https://database.caixin.com/2026-06-15/102454182.html")
        self.assertEqual(event["publish_time"], "2026-06-15")
        self.assertEqual(event["event_bucket"], "risk")

    def test_build_events_uses_reason_to_disambiguate_similar_short_titles(self):
        payload = {
            "date": "20260622",
            "items": [
                {
                    "news": "铝价短期承压",
                    "type": "行业动态",
                    "sectors": ["有色金属"],
                    "impact": "negative",
                    "strength": 6,
                    "duration": "1-3天",
                    "reason": "供应缓解需求担忧利空铝",
                }
            ],
            "raw_news": [
                {
                    "title": "受COMEX银价回落及美元指数高位影响，白银价格承压下跌",
                    "source": "CCI快报",
                    "url": "https://example.com/silver",
                },
                {
                    "title": "随着供应风险缓解、而需求担忧持续，短期内铝价看起来容易承压",
                    "source": "市场动态",
                    "url": "https://database.caixin.com/2026-06-16/102454525.html",
                },
            ],
        }

        event = build_events_from_news_payload(payload)[0]

        self.assertEqual(event["original_source"], "市场动态")
        self.assertEqual(event["source_url"], "https://database.caixin.com/2026-06-16/102454525.html")


if __name__ == "__main__":
    unittest.main()
