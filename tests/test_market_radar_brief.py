import unittest

from market_radar.brief import build_research_brief


class MarketRadarBriefTest(unittest.TestCase):
    def test_build_research_brief_aggregates_v2_workspace(self):
        decision = {
            "alignment": "主线共振",
            "confidence": "高",
            "primary_action": "优先观察机械设备的策略信号，等待承接，不追高。",
            "data_alignment": {"aligned": True, "sector_date": "20260622", "news_date": "20260622", "message": "数据日期已对齐。"},
            "sector_theses": [
                {
                    "industry": "机械设备",
                    "thesis_label": "主线共振",
                    "research_action": "可重点跟踪",
                    "conviction": "高",
                    "summary": "机械设备属于主线共振。",
                    "risks": [],
                    "verification_points": ["观察机械设备是否继续放量承接"],
                }
            ],
            "stock_watchlist": [
                {
                    "ts_code": "000001.SZ",
                    "name": "设备龙头",
                    "industry": "机械设备",
                    "research_action": "可重点跟踪",
                    "event_relevance": "行业主线受益",
                    "reason_cards": [{"type": "量价", "label": "放量承接", "detail": "相对板块领先。"}],
                    "risks": [],
                }
            ],
            "review_loop": {
                "closing_judgement": "主线已验证",
                "risk_audit": [],
                "next_day_watch_points": ["观察机械设备是否继续放量承接"],
                "data_quality": {"tone": "ok", "reasons": []},
            },
        }
        concept_news = {
            "event_summary": {"event_count": 2, "top_materiality": "A"},
            "events": [
                {
                    "title": "设备更新项目清单下达",
                    "materiality": "A",
                    "event_type": "产业政策",
                    "source_quality": "官方/监管",
                    "mapped_industries": ["机械设备"],
                    "verification_points": ["观察机械设备是否继续放量承接"],
                }
            ],
        }
        radar = {"end_date": "20260622", "summary": {"headline": "市场有主线", "market_line": "有主线"}}

        brief = build_research_brief(decision, concept_news, radar)

        self.assertIn("主线已验证", brief["headline"])
        self.assertEqual(brief["mainlines"][0]["industry"], "机械设备")
        self.assertEqual(brief["event_watchlist"][0]["title"], "设备更新项目清单下达")
        self.assertEqual(brief["sector_theses"][0]["thesis_label"], "主线共振")
        self.assertEqual(brief["stock_watchlist"][0]["ts_code"], "000001.SZ")
        self.assertEqual(brief["risk_board"], [])
        self.assertIn("机械设备", brief["verification_checklist"][0])
        self.assertEqual(brief["data_quality"]["tone"], "ok")

    def test_build_research_brief_surfaces_risk_and_low_confidence(self):
        decision = {
            "alignment": "消息主线",
            "confidence": "低",
            "primary_action": "只把消息热度当线索。",
            "data_alignment": {"aligned": False, "message": "行业热度与消息日期不一致。"},
            "sector_theses": [
                {
                    "industry": "电子",
                    "thesis_label": "消息待验证",
                    "research_action": "先放观察池",
                    "conviction": "中",
                    "summary": "电子属于消息待验证。",
                    "risks": ["行业映射偏泛化"],
                    "verification_points": ["先验证电子是否放量承接"],
                }
            ],
            "stock_watchlist": [],
            "review_loop": {
                "closing_judgement": "仍待验证",
                "risk_audit": [{"type": "数据风险", "target": "日期", "reason": "日期不一致"}],
                "next_day_watch_points": ["先验证电子是否放量承接"],
                "data_quality": {"tone": "warn", "reasons": ["行业热度与消息日期不一致。"]},
            },
        }
        concept_news = {"event_summary": {"event_count": 1}, "events": []}
        radar = {"end_date": "20260622", "summary": {"headline": "消息偏强"}}

        brief = build_research_brief(decision, concept_news, radar)

        self.assertEqual(brief["headline"], "仍待验证：消息主线，结论需降置信。")
        self.assertEqual(brief["risk_board"][0]["reason"], "日期不一致")
        self.assertEqual(brief["data_quality"]["tone"], "warn")


    def test_build_research_brief_adds_blocker_when_a_level_negative_event_hits_risk_thesis(self):
        decision = {
            "alignment": "主线分裂",
            "confidence": "低",
            "primary_action": "先看风险释放。",
            "data_alignment": {"aligned": True},
            "sector_theses": [
                {
                    "industry": "计算机",
                    "thesis_label": "风险冲突",
                    "research_action": "仅复盘",
                    "conviction": "低",
                    "summary": "计算机存在事件冲突。",
                    "risks": ["A级负面事件冲击"],
                    "verification_points": [],
                }
            ],
            "stock_watchlist": [],
            "review_loop": {"closing_judgement": "风险优先", "risk_audit": [], "next_day_watch_points": []},
        }
        concept_news = {
            "event_summary": {"event_count": 1, "top_materiality": "A"},
            "events": [
                {
                    "title": "美国限制外国获取AI模型",
                    "impact": "negative",
                    "materiality": "A",
                    "mapped_industries": ["计算机"],
                }
            ],
        }

        brief = build_research_brief(decision, concept_news, {})

        self.assertEqual(brief["risk_blocker"]["level"], "暂停新关注")
        self.assertEqual(brief["risk_blocker"]["tone"], "danger")
        self.assertIn("计算机", brief["risk_blocker"]["reason"])
        self.assertIn("美国限制外国获取AI模型", brief["risk_blocker"]["reason"])

    def test_build_research_brief_groups_events_by_user_attention(self):
        decision = {
            "alignment": "主线分裂",
            "data_alignment": {"aligned": True},
            "sector_theses": [],
            "stock_watchlist": [],
            "review_loop": {"risk_audit": [], "next_day_watch_points": []},
        }
        concept_news = {
            "events": [
                {"title": "risk event", "event_bucket": "risk", "impact": "negative"},
                {"title": "positive event", "event_bucket": "positive", "impact": "positive"},
                {"title": "unknown source", "event_bucket": "unverified", "impact": "mixed"},
            ],
            "event_summary": {"event_count": 3},
        }

        brief = build_research_brief(decision, concept_news, {})

        self.assertEqual([item["title"] for item in brief["event_groups"]["risk"]], ["risk event"])
        self.assertEqual([item["title"] for item in brief["event_groups"]["positive"]], ["positive event"])
        self.assertEqual([item["title"] for item in brief["event_groups"]["unverified"]], ["unknown source"])
        self.assertEqual(len(brief["event_groups"]["all"]), 3)

    def test_build_research_brief_groups_events_by_trading_workflow(self):
        decision = {
            "alignment": "主线分裂",
            "data_alignment": {"aligned": True},
            "sector_theses": [],
            "stock_watchlist": [],
            "review_loop": {"risk_audit": [], "next_day_watch_points": []},
        }
        concept_news = {
            "events": [
                {"title": "today catalyst", "trade_priority": "catalyst", "event_bucket": "positive"},
                {"title": "risk blocker", "trade_priority": "risk", "event_bucket": "risk"},
                {"title": "old background", "trade_priority": "background", "event_bucket": "background"},
                {"title": "missing source", "trade_priority": "source_gap", "event_bucket": "unverified"},
            ],
            "event_summary": {"event_count": 4},
        }

        brief = build_research_brief(decision, concept_news, {})

        self.assertEqual([item["title"] for item in brief["trade_event_groups"]["catalysts"]], ["today catalyst"])
        self.assertEqual([item["title"] for item in brief["trade_event_groups"]["risks"]], ["risk blocker"])
        self.assertEqual([item["title"] for item in brief["trade_event_groups"]["background"]], ["old background"])
        self.assertEqual([item["title"] for item in brief["trade_event_groups"]["source_gaps"]], ["missing source"])


if __name__ == "__main__":
    unittest.main()
