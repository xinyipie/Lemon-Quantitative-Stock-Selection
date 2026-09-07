import unittest
from pathlib import Path

from market_radar.ai_news_brief import _invoke_ai_stage, _validate_result_v2
from market_radar.evidence_pack import build_evidence_pack


class MarketRadarDualEntryTest(unittest.TestCase):
    def test_market_radar_routes_batch_to_flash_and_summary_to_pro(self):
        calls = []

        def fake_ai(prompt, system="", model=None, thinking=None, json_mode=False):
            calls.append({"model": model, "thinking": thinking, "json_mode": json_mode})
            return "{}"

        _invoke_ai_stage(fake_ai, "batch", "system", stage="event")
        _invoke_ai_stage(fake_ai, "summary", "system", stage="summary")

        self.assertEqual(calls[0], {"model": "deepseek-v4-flash", "thinking": False, "json_mode": True})
        self.assertEqual(calls[1], {"model": "deepseek-v4-pro", "thinking": True, "json_mode": True})

    def test_market_radar_template_defaults_to_bullish_and_exposes_direction_tabs(self):
        template = Path("web_app/templates/sectors.html").read_text(encoding="utf-8")

        self.assertIn('data-ai-direction="利多"', template)
        self.assertIn('data-ai-direction="利空"', template)
        self.assertIn('data-ai-direction="中性"', template)
        self.assertIn("利空是风险提示，不代表推荐", template)
        self.assertIn("data-impact-direction", template)

    def test_market_radar_exposes_independent_situation_layer(self):
        template = Path("web_app/templates/sectors.html").read_text(encoding="utf-8")

        self.assertIn('id="radar-situation"', template)
        self.assertIn("最新雷达态势", template)
        self.assertIn("新变化", template)
        self.assertIn("量价共振", template)
        self.assertIn("待确认", template)
        self.assertIn("风险变化", template)
        self.assertIn('href="#ai-news-brief"', template)
        self.assertIn('href="#key-events"', template)
        self.assertIn('href="#mainline-view"', template)
        self.assertIn('href="#risk-sectors"', template)

    def test_direct_company_news_enters_outside_quant_pool(self):
        radar = {"summary": {"headline": "测试"}, "healthy": [], "risky": [], "candidates": [], "news_stock_universe": [{"ts_code": "000001.SZ", "name": "测试股份", "industry": "电子", "ret_5d": 1.0, "ret_10d": 2.0, "above_ma20": True}]}
        news = {"reading_events": [{"title": "测试股份签署重要合同", "content": "测试股份公告新合同。", "source": "巨潮资讯", "publish_time": "2026-08-13 08:00:00"}]}
        pack = build_evidence_pack(radar, news, "20260813")
        stock = next(item for item in pack["stocks"] if item["ts_code"] == "000001.SZ")
        self.assertEqual(stock["candidate_source"], "news_direct")
        self.assertFalse(stock["quant_selected"])
        self.assertTrue(stock["direct_evidence_ids"])

    def test_quant_only_candidate_cannot_be_priority_observation(self):
        event = {"evidence_id": "EV-1", "title": "无关宏观消息", "summary": "市场背景", "mapped_industries": []}
        compact = {"sectors": [], "risky_industries": [], "events": [event], "event_assessments": [{"evidence_id": "EV-1", "mapped_industries": []}], "stocks": [{"ts_code": "000001.SZ", "name": "测试股份", "industry": "电子", "candidate_score": 80, "quant_selected": True, "direct_evidence_ids": [], "reason": "量价较强"}]}
        parsed = {"stock_focus": [{"ts_code": "000001.SZ", "stance": "优先观察", "evidence_ids": ["EV-1"]}]}
        item = _validate_result_v2(parsed, compact)["stock_focus"][0]
        self.assertEqual(item["focus_type"], "仅量价候选")
        self.assertEqual(item["stance"], "等待消息确认")

    def test_negative_company_news_is_a_risk_not_a_recommendation(self):
        event = {"evidence_id": "EV-1", "title": "测试股份订单取消", "summary": "客户取消订单", "mapped_industries": ["电子"]}
        compact = {
            "sectors": [],
            "risky_industries": [],
            "events": [event],
            "event_assessments": [{"evidence_id": "EV-1", "direction": "利空", "mapped_industries": ["电子"]}],
            "stocks": [{"ts_code": "000001.SZ", "name": "测试股份", "industry": "电子", "candidate_score": 80, "quant_selected": True, "direct_evidence_ids": ["EV-1"], "reason": "量价较强"}],
        }
        parsed = {"stock_focus": [{"ts_code": "000001.SZ", "stance": "等待量价确认", "evidence_ids": ["EV-1"]}]}

        result = _validate_result_v2(parsed, compact)
        item = result["stock_focus"][0]

        self.assertEqual(item["impact_direction"], "利空")
        self.assertEqual(item["stance"], "风险回避")
        self.assertEqual(result["risk_focus"], [item])
        self.assertEqual(result["bullish_focus"], [])

    def test_positive_direct_news_remains_a_bullish_watch_item(self):
        event = {"evidence_id": "EV-1", "title": "测试股份获得大额订单", "summary": "订单落地", "mapped_industries": ["电子"]}
        compact = {
            "sectors": [],
            "risky_industries": [],
            "events": [event],
            "event_assessments": [{"evidence_id": "EV-1", "direction": "利多", "mapped_industries": ["电子"]}],
            "stocks": [{"ts_code": "000001.SZ", "name": "测试股份", "industry": "电子", "candidate_score": None, "quant_selected": False, "direct_evidence_ids": ["EV-1"], "reason": "公司订单"}],
        }
        parsed = {"stock_focus": [{"ts_code": "000001.SZ", "stance": "优先观察", "evidence_ids": ["EV-1"]}]}

        result = _validate_result_v2(parsed, compact)
        item = result["stock_focus"][0]

        self.assertEqual(item["impact_direction"], "利多")
        self.assertEqual(item["stance"], "等待量价确认")
        self.assertEqual(result["bullish_focus"], [item])

    def test_conflicting_news_is_neutral_and_waits_for_direction(self):
        events = [
            {"evidence_id": "EV-1", "title": "测试股份获得订单", "summary": "利好", "mapped_industries": ["电子"]},
            {"evidence_id": "EV-2", "title": "测试股份客户取消采购", "summary": "利空", "mapped_industries": ["电子"]},
        ]
        compact = {
            "sectors": [],
            "risky_industries": [],
            "events": events,
            "event_assessments": [
                {"evidence_id": "EV-1", "direction": "利多", "mapped_industries": ["电子"]},
                {"evidence_id": "EV-2", "direction": "利空", "mapped_industries": ["电子"]},
            ],
            "stocks": [{"ts_code": "000001.SZ", "name": "测试股份", "industry": "电子", "candidate_score": 70, "quant_selected": True, "direct_evidence_ids": ["EV-1", "EV-2"], "reason": "消息冲突"}],
        }
        parsed = {"stock_focus": [{"ts_code": "000001.SZ", "stance": "优先观察", "evidence_ids": ["EV-1", "EV-2"]}]}

        result = _validate_result_v2(parsed, compact)
        item = result["stock_focus"][0]

        self.assertEqual(item["impact_direction"], "中性")
        self.assertEqual(item["stance"], "等待方向确认")
        self.assertEqual(result["neutral_focus"], [item])

    def test_news_mapped_sector_is_kept_when_quant_sector_pool_is_empty(self):
        event = {
            "evidence_id": "EV-1",
            "title": "AI服务器需求带动芯片订单增长",
            "summary": "产业链订单改善",
            "mapped_industries": [],
        }
        compact = {
            "sectors": [],
            "risky_industries": [],
            "events": [event],
            "event_assessments": [
                {
                    "evidence_id": "EV-1",
                    "value_level": "高",
                    "direction": "利多",
                    "mapped_industries": ["半导体"],
                    "confidence": "高",
                    "reason": "订单增长直接改善半导体产业链预期。",
                }
            ],
            "stocks": [],
        }
        parsed = {
            "summary": "半导体产业链景气改善。",
            "sector_focus": [
                {
                    "industry": "半导体",
                    "stance": "关注",
                    "confidence": "高",
                    "reason": "AI服务器需求带动芯片订单。",
                    "evidence_ids": ["EV-1"],
                    "validation": "等待板块成交与扩散确认。",
                    "invalidation": "订单预期未兑现。",
                }
            ],
        }

        result = _validate_result_v2(parsed, compact)

        self.assertEqual(len(result["sector_focus"]), 1)
        self.assertEqual(result["sector_focus"][0]["industry"], "半导体")
        self.assertEqual(result["sector_focus"][0]["relation"], "消息关注")
        self.assertEqual(result["sector_focus"][0]["confidence"], "中")

    def test_news_mapped_sector_is_recovered_when_final_ai_omits_sector_focus(self):
        compact = {
            "sectors": [],
            "risky_industries": [],
            "events": [{"evidence_id": "EV-1", "title": "安全应急装备规划发布", "summary": "政策支持产业发展"}],
            "event_assessments": [
                {
                    "evidence_id": "EV-1",
                    "value_level": "高",
                    "direction": "利多",
                    "mapped_industries": ["专用设备"],
                    "confidence": "高",
                    "reason": "政策直接覆盖安全应急装备。",
                }
            ],
            "stocks": [],
        }

        result = _validate_result_v2({"summary": "安全应急装备获得政策支持。", "sector_focus": []}, compact)

        self.assertEqual(len(result["sector_focus"]), 1)
        self.assertEqual(result["sector_focus"][0]["industry"], "专用设备")
        self.assertEqual(result["sector_focus"][0]["relation"], "消息关注")
        self.assertIn("政策直接覆盖", result["sector_focus"][0]["reason"])


if __name__ == "__main__":
    unittest.main()
