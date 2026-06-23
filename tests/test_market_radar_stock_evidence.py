import unittest

from market_radar.stock_evidence import build_stock_evidence


class MarketRadarStockEvidenceTest(unittest.TestCase):
    def test_build_stock_evidence_marks_mainline_candidate_with_event_support(self):
        candidates = [
            {
                "ts_code": "000001.SZ",
                "name": "设备龙头",
                "industry": "机械设备",
                "candidate_score": 82,
                "ret_5d": 4.2,
                "ret_10d": 9.5,
                "stock_vs_sector_10d": 5.6,
                "volume_ratio": 1.8,
                "risk_note": "",
            }
        ]
        theses = [
            {
                "industry": "机械设备",
                "thesis_label": "主线共振",
                "research_action": "可重点跟踪",
                "conviction": "高",
                "events": [{"mapping_confidence": "medium", "impact": "positive"}],
            }
        ]

        cards = build_stock_evidence(candidates, theses)

        self.assertEqual(cards[0]["ts_code"], "000001.SZ")
        self.assertEqual(cards[0]["stock_role"], "领涨")
        self.assertEqual(cards[0]["event_relevance"], "行业主线受益")
        self.assertEqual(cards[0]["market_behavior"], "放量承接")
        self.assertEqual(cards[0]["strategy_alignment"], "仅板块候选")
        self.assertEqual(cards[0]["research_action"], "可重点跟踪")
        self.assertTrue(cards[0]["reason_cards"])

    def test_build_stock_evidence_demotes_laggard_and_broad_theme(self):
        candidates = [
            {
                "ts_code": "000002.SZ",
                "name": "弱跟随",
                "industry": "电子",
                "candidate_score": 56,
                "ret_5d": 1.0,
                "ret_10d": 2.0,
                "stock_vs_sector_10d": -9.2,
                "risk_note": "",
            }
        ]
        theses = [
            {
                "industry": "电子",
                "thesis_label": "消息待验证",
                "research_action": "先放观察池",
                "conviction": "中",
                "events": [{"mapping_confidence": "broad", "impact": "positive"}],
            }
        ]

        cards = build_stock_evidence(candidates, theses)

        self.assertEqual(cards[0]["stock_role"], "掉队")
        self.assertEqual(cards[0]["event_relevance"], "泛题材")
        self.assertEqual(cards[0]["research_action"], "先放观察池")
        self.assertIn("相对板块落后", cards[0]["risks"])

    def test_build_stock_evidence_keeps_overheated_candidate_in_pullback_confirmation(self):
        candidates = [
            {
                "ts_code": "000003.SZ",
                "name": "高位股",
                "industry": "通信",
                "candidate_score": 88,
                "ret_5d": 16.0,
                "ret_10d": 28.0,
                "stock_vs_sector_10d": 13.5,
                "volume_ratio": 2.2,
                "risk_note": "位置偏高，不追高",
            }
        ]
        theses = [
            {
                "industry": "通信",
                "thesis_label": "主线共振",
                "research_action": "可重点跟踪",
                "conviction": "高",
                "events": [{"mapping_confidence": "medium", "impact": "positive"}],
            }
        ]

        cards = build_stock_evidence(candidates, theses)

        self.assertEqual(cards[0]["stock_role"], "过热")
        self.assertEqual(cards[0]["research_action"], "等回踩确认")
        self.assertIn("不追高", " ".join(cards[0]["risks"]))

    def test_build_stock_evidence_does_not_treat_benign_follow_note_as_risk(self):
        candidates = [
            {
                "ts_code": "000004.SZ",
                "name": "健康跟踪",
                "industry": "玻璃",
                "candidate_score": 72,
                "ret_5d": 4.0,
                "ret_10d": 9.0,
                "stock_vs_sector_10d": 3.0,
                "risk_note": "节奏相对健康，继续跟踪承接",
            }
        ]
        theses = [
            {
                "industry": "玻璃",
                "thesis_label": "趋势主线",
                "research_action": "先放观察池",
                "events": [],
            }
        ]

        cards = build_stock_evidence(candidates, theses)

        self.assertEqual(cards[0]["risks"], [])
        self.assertEqual(cards[0]["reason_cards"][-1]["detail"], "暂无额外风险备注。")


    def test_build_stock_evidence_adds_resonance_and_validation_conditions(self):
        candidates = [
            {
                "ts_code": "688721.SH",
                "name": "龙图光罩",
                "industry": "半导体",
                "candidate_score": 86,
                "ret_5d": 5.5,
                "ret_10d": 13.0,
                "stock_vs_sector_10d": 6.0,
                "volume_ratio": 1.6,
                "risk_note": "",
            },
            {
                "ts_code": "002475.SZ",
                "name": "立讯精密",
                "industry": "消费电子",
                "candidate_score": 78,
                "ret_5d": 2.5,
                "ret_10d": 4.0,
                "stock_vs_sector_10d": 1.0,
                "volume_ratio": 1.1,
                "risk_note": "",
            },
        ]
        theses = [
            {
                "industry": "半导体",
                "thesis_label": "主线共振",
                "research_action": "可重点跟踪",
                "conviction": "高",
                "events": [{"mapping_confidence": "medium", "impact": "positive"}],
            }
        ]

        cards = build_stock_evidence(candidates, theses)

        leader = next(item for item in cards if item["ts_code"] == "688721.SH")
        orphan = next(item for item in cards if item["ts_code"] == "002475.SZ")
        self.assertEqual(leader["resonance_level"], "★★★")
        self.assertEqual(leader["resonance_label"], "策略+主线+事件共振")
        self.assertTrue(any("前60分钟" in item for item in leader["validation_conditions"]))
        self.assertEqual(orphan["resonance_level"], "★")
        self.assertEqual(orphan["resonance_label"], "孤儿信号")
        self.assertTrue(any("补证据" in item for item in orphan["validation_conditions"]))


if __name__ == "__main__":
    unittest.main()
