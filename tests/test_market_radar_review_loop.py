import unittest

from market_radar.review_loop import build_review_loop


class MarketRadarReviewLoopTest(unittest.TestCase):
    def test_build_review_loop_marks_validated_mainline(self):
        decision = {
            "alignment": "主线共振",
            "sector_theses": [
                {
                    "industry": "机械设备",
                    "thesis_label": "主线共振",
                    "research_action": "可重点跟踪",
                    "conviction": "高",
                    "market_validation_score": 82,
                    "event_score": 78,
                    "verification_points": ["观察机械设备是否继续放量承接"],
                }
            ],
            "stock_watchlist": [
                {
                    "ts_code": "000001.SZ",
                    "name": "设备龙头",
                    "industry": "机械设备",
                    "research_action": "可重点跟踪",
                    "stock_role": "领涨",
                    "event_relevance": "行业主线受益",
                    "risks": [],
                }
            ],
            "data_alignment": {"aligned": True, "message": "数据日期已对齐。"},
        }

        review = build_review_loop(decision)

        self.assertEqual(review["closing_judgement"], "主线已验证")
        self.assertEqual(review["validated_mainlines"][0]["industry"], "机械设备")
        self.assertEqual(review["validated_mainlines"][0]["status"], "已验证")
        self.assertTrue(review["next_day_watch_points"])

    def test_build_review_loop_flags_news_without_market_validation(self):
        decision = {
            "alignment": "消息主线",
            "sector_theses": [
                {
                    "industry": "电子",
                    "thesis_label": "消息待验证",
                    "research_action": "先放观察池",
                    "conviction": "中",
                    "market_validation_score": 0,
                    "event_score": 88,
                    "verification_points": ["先验证电子是否从消息热度扩散到量价承接"],
                }
            ],
            "stock_watchlist": [],
            "data_alignment": {"aligned": True, "message": "数据日期已对齐。"},
        }

        review = build_review_loop(decision)

        self.assertEqual(review["closing_judgement"], "仍待验证")
        self.assertEqual(review["unverified_or_failed"][0]["industry"], "电子")
        self.assertIn("量价未验证", review["unverified_or_failed"][0]["reason"])
        self.assertIn("电子", review["next_day_watch_points"][0])

    def test_build_review_loop_audits_risk_and_data_quality(self):
        decision = {
            "alignment": "主线分裂",
            "sector_theses": [
                {
                    "industry": "银行",
                    "thesis_label": "风险冲突",
                    "research_action": "仅复盘",
                    "conviction": "低",
                    "market_validation_score": 20,
                    "event_score": 60,
                    "risk_score": 70,
                    "risks": ["负面事件：融资压力升温"],
                    "verification_points": ["观察银行是否继续走弱"],
                }
            ],
            "stock_watchlist": [
                {
                    "ts_code": "000003.SZ",
                    "name": "高位股",
                    "industry": "通信",
                    "research_action": "等回踩确认",
                    "stock_role": "过热",
                    "event_relevance": "行业主线受益",
                    "risks": ["位置偏高，不追高"],
                }
            ],
            "data_alignment": {"aligned": False, "message": "行业热度与消息日期不一致。"},
        }

        review = build_review_loop(decision)

        self.assertEqual(review["closing_judgement"], "风险优先")
        self.assertIn("个股风险", [item["type"] for item in review["risk_audit"]])
        self.assertEqual(review["data_quality"]["tone"], "warn")
        self.assertIn("日期不一致", review["data_quality"]["reasons"][0])


if __name__ == "__main__":
    unittest.main()
