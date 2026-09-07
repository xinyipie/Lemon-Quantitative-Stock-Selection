import unittest

from market_radar.ai_news_brief import _validate_result
from market_radar.evidence_pack import build_evidence_pack


class AiNewsBriefQualityTest(unittest.TestCase):
    def test_cninfo_raw_announcement_enters_final_evidence(self):
        concept_news = {
            "news": {
                "raw_news": [
                    {
                        "title": "测试公司关于重大合同的公告",
                        "source": "巨潮资讯",
                        "provider": "cninfo_announcements",
                        "publish_time": "2026-08-12 18:30:00",
                        "url": "https://static.cninfo.com.cn/test.pdf",
                        "content_excerpt": "测试公司签订重大合同。",
                    }
                ]
            }
        }

        pack = build_evidence_pack({}, concept_news, "20260812")

        self.assertEqual(len(pack["events"]), 1)
        self.assertEqual(pack["events"][0]["sources"], ["巨潮资讯"])
        self.assertEqual(pack["input_audit"]["source_pipeline"][0]["sent_to_ai"], 1)

    def test_cross_media_same_event_is_merged(self):
        concept_news = {
            "news": {
                "raw_news": [
                    {
                        "title": "国家发改委推进新一轮设备更新项目落地",
                        "source": "财联社",
                        "publish_time": "2026-08-12 09:00:00",
                        "content_excerpt": "新一轮设备更新项目清单加快下达。",
                    },
                    {
                        "title": "发改委加快推动新一轮设备更新项目落地",
                        "source": "东方财富",
                        "publish_time": "2026-08-12 09:20:00",
                        "content_excerpt": "新一轮设备更新项目清单加快下达。",
                    },
                ]
            }
        }

        pack = build_evidence_pack({}, concept_news, "20260812")

        self.assertEqual(len(pack["events"]), 1)
        self.assertEqual(set(pack["events"][0]["sources"]), {"财联社", "东方财富"})

    def test_weak_stock_relation_cannot_be_priority(self):
        compact = {
            "sectors": [],
            "stocks": [{"ts_code": "000001.SZ", "name": "平安银行", "industry": "银行", "candidate_score": 80}],
            "events": [{"evidence_id": "EV-1", "title": "锂盐价格上涨", "summary": "锂矿供给收紧"}],
            "event_assessments": [{"evidence_id": "EV-1", "mapped_industries": ["锂"]}],
            "risky_industries": [],
        }
        parsed = {
            "stock_focus": [
                {
                    "ts_code": "000001.SZ",
                    "stance": "优先观察",
                    "evidence_ids": ["EV-1"],
                    "reason": "量化排名较高",
                    "news_logic": "间接参考锂盐消息",
                }
            ]
        }

        result = _validate_result(parsed, compact)

        self.assertEqual(result["stock_focus"][0]["relation_level"], "weak")
        self.assertEqual(result["stock_focus"][0]["stance"], "等待确认")


if __name__ == "__main__":
    unittest.main()
