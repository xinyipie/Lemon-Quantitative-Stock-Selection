import unittest

from market_radar.sector_thesis import build_sector_theses


class MarketRadarSectorThesisTest(unittest.TestCase):
    def test_build_sector_theses_marks_mainline_when_market_and_event_align(self):
        radar = {
            "healthy": [
                {
                    "industry": "机械设备",
                    "heat_score": 82,
                    "stage": "趋势延续",
                    "volume_ratio": 1.35,
                    "stock_count": 42,
                }
            ],
            "risky": [],
        }
        events = [
            {
                "title": "两部门推动设备更新项目清单下达",
                "event_type": "产业政策",
                "impact": "positive",
                "materiality": "A",
                "mapped_industries": ["机械设备", "电力设备"],
                "mapping_confidence": "medium",
                "source_quality": "官方/监管",
                "verification_points": ["观察机械设备是否放量承接"],
                "risk_note": "仍需量价验证。",
            }
        ]

        theses = build_sector_theses(radar, events)

        thesis = next(item for item in theses if item["industry"] == "机械设备")
        self.assertEqual(thesis["industry"], "机械设备")
        self.assertEqual(thesis["thesis_label"], "主线共振")
        self.assertEqual(thesis["research_action"], "可重点跟踪")
        self.assertEqual(thesis["conviction"], "高")
        self.assertGreaterEqual(thesis["thesis_score"], 75)
        self.assertTrue(thesis["evidence"])
        self.assertTrue(thesis["verification_points"])

    def test_build_sector_theses_flags_positive_news_without_market_validation(self):
        radar = {"healthy": [], "risky": []}
        events = [
            {
                "title": "AI产业链出口改善",
                "event_type": "产业趋势",
                "impact": "positive",
                "materiality": "B",
                "mapped_industries": ["电子", "通信", "计算机", "传媒"],
                "mapping_confidence": "broad",
                "source_quality": "主流财经",
                "verification_points": ["观察电子是否放量承接"],
                "risk_note": "行业映射偏泛化。",
            }
        ]

        theses = build_sector_theses(radar, events)

        self.assertEqual(theses[0]["industry"], "电子")
        self.assertEqual(theses[0]["thesis_label"], "消息待验证")
        self.assertEqual(theses[0]["research_action"], "先放观察池")
        self.assertEqual(theses[0]["conviction"], "中")
        self.assertIn("行业映射偏泛化", " ".join(theses[0]["risks"]))

    def test_build_sector_theses_flags_risky_sector_and_negative_event(self):
        radar = {
            "healthy": [],
            "risky": [
                {
                    "industry": "银行",
                    "heat_score": 74,
                    "stage": "过热高潮",
                    "volume_ratio": 1.8,
                }
            ],
        }
        events = [
            {
                "title": "银行转债融资压力升温",
                "event_type": "资金压力",
                "impact": "negative",
                "materiality": "B",
                "mapped_industries": ["银行"],
                "mapping_confidence": "precise",
                "source_quality": "主流财经",
                "verification_points": ["观察银行是否继续走弱"],
                "risk_note": "负面事件需要先看风险释放。",
            }
        ]

        theses = build_sector_theses(radar, events)

        self.assertEqual(theses[0]["industry"], "银行")
        self.assertEqual(theses[0]["thesis_label"], "风险冲突")
        self.assertEqual(theses[0]["research_action"], "仅复盘")
        self.assertEqual(theses[0]["conviction"], "低")
        self.assertIn("负面事件", " ".join(theses[0]["risks"]))


if __name__ == "__main__":
    unittest.main()
