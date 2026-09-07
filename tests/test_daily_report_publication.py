import json
import unittest

from daily_report.publication import (
    REQUIRED_SECTIONS,
    build_public_facts,
    extract_search_keywords,
    report_to_plain_text,
    validate_report,
)


def _facts():
    return {
        "report_date": "20260723",
        "market_date": "20260722",
        "cutoffs": {"data": "2026-07-22 15:00:00", "news": "2026-07-23 08:30:00"},
        "market": {"regime": "BULL_TREND", "market_style": "sideways", "sentiment": {"limit_up_count": 45, "limit_down_count": 8}},
        "market_radar_decision": {"alignment": "主线分裂", "confidence": "中", "focus_industries": ["银行"]},
        "source_status": {
            "short_formal": {"state": "available", "count": 1},
            "short_auxiliary": {"state": "completed_empty", "count": 0},
            "longterm_active": {"state": "not_triggered", "count": 0},
            "market_radar": {"state": "available", "count": 1},
            "dragon": {"state": "available", "count": 1},
            "news": {"state": "available", "count": 1},
        },
        "sectors": {
            "healthy": [{"industry": "银行", "stage": "趋势延续", "heat_score": 72}],
            "risky": [],
        },
        "events": [{"title": "行业政策更新", "industry": "银行", "impact": "中性"}],
        "observations": [{
            "ts_code": "000001.SZ", "name": "平安银行", "industry": "银行",
            "sources": ["short_formal", "market_radar"],
            "source_evidence": {
                "short_formal": {"rank": 1, "score": 81, "reason": "资金承接稳定"},
                "market_radar": {"stage": "趋势延续", "pct_chg": 1.1},
            },
            "resonance": ["多个独立观察来源同时出现"],
            "conflicts": ["行业扩散仍不足"],
            "risks": ["短期波动可能放大"],
            "validation": ["观察行业扩散和成交承接能否延续"],
        }],
        "performance": {
            "short": {"closed_count": 12, "win_rate": 0.5, "avg_ret_5d": 1.5},
            "longterm": {"total_samples": 0, "runs": []},
        },
        "evidence_index": {
            "market:state": {"label": "市场状态", "values": ["分化", 45, 8], "payload": {}},
            "sector:银行:healthy": {"label": "银行行业观察", "values": ["银行", "趋势延续", 72], "payload": {}},
            "stock:000001.SZ:short_formal": {"label": "平安银行观察", "values": [1, 81, "资金承接稳定"], "payload": {}},
            "stock:000001.SZ:market_radar": {"label": "平安银行观察", "values": ["趋势延续", 1.1], "payload": {}},
            "event:1": {"label": "行业政策更新", "values": ["行业政策更新", "银行", "中性"], "payload": {}},
            "performance:short:recent": {"label": "近期成熟短周期样本", "values": [12, 0.5, 1.5], "payload": {}},
        },
        "completeness": {"can_publish": True, "confidence_cap": "中", "warnings": []},
    }


def _valid_document():
    paragraphs = {
        "core_judgement": {"text": "市场仍以结构分化为主，持续性需要后续成交承接确认。", "evidence_ids": ["market:state"], "entity_refs": []},
        "market_context": {"text": "银行方向保持趋势延续，但行业扩散范围仍需观察。", "evidence_ids": ["sector:银行:healthy"], "entity_refs": ["industry:银行"]},
        "focus": {"text": "平安银行同时出现在两个独立观察视角中，短期波动可能放大。", "evidence_ids": ["stock:000001.SZ:short_formal", "stock:000001.SZ:market_radar"], "entity_refs": ["stock:000001.SZ"], "risk_refs": ["stock:000001.SZ:risk:0"]},
        "performance_risk": {"text": "近期成熟样本共12个，结果只能用于描述历史表现。", "evidence_ids": ["performance:short:recent"], "entity_refs": []},
        "watch_points": {"text": "后续重点看行业扩散和成交承接能否延续。", "evidence_ids": ["stock:000001.SZ:market_radar"], "entity_refs": ["stock:000001.SZ"], "validation_refs": ["stock:000001.SZ:validation:0"]},
    }
    return {
        "title": "缩量分化下更需观察承接持续性",
        "sections": [
            {"key": key, "heading": heading, "paragraphs": [paragraphs[key]]}
            for key, heading in zip(REQUIRED_SECTIONS, ["核心判断", "市场脉络", "重点观察", "历史表现与风险", "后续观察"])
        ],
        "keywords": ["银行", "平安银行", "行业政策更新", "波动风险"],
    }


class DailyReportPublicationTest(unittest.TestCase):
    def test_public_projection_removes_internal_strategy_details(self):
        public = build_public_facts(_facts())
        text = json.dumps(public, ensure_ascii=False)
        self.assertNotIn("short_formal", text)
        self.assertNotIn("BULL_TREND", text)
        self.assertNotIn('"score"', text)
        self.assertNotIn("81", text)
        self.assertNotIn("heat", public["sectors"][0])
        self.assertNotIn(72, public["evidence"]["sector:银行:healthy"]["values"])
        self.assertIn("平安银行", text)
        self.assertIn("短周期正式观察", text)

    def test_valid_report_is_traceable_and_searchable(self):
        facts = _facts()
        public = build_public_facts(facts)
        document = _valid_document()
        self.assertEqual(validate_report(document, facts, public), [])
        plain = report_to_plain_text(document)
        self.assertIn("缩量分化下更需观察承接持续性", plain)
        self.assertEqual(
            extract_search_keywords(document, public),
            ["银行", "平安银行", "行业政策更新", "波动风险", "000001.SZ"],
        )

    def test_risk_fact_can_be_used_as_evidence_for_stock_focus(self):
        facts = _facts()
        public = build_public_facts(facts)
        document = _valid_document()
        focus = document["sections"][2]["paragraphs"][0]
        focus["evidence_ids"] = ["stock:000001.SZ:risk:0"]
        focus.pop("risk_refs")
        self.assertEqual(validate_report(document, facts, public), [])

    def test_percentage_conversion_is_traceable_to_decimal_evidence(self):
        facts = _facts()
        public = build_public_facts(facts)
        public["evidence"]["market:state"]["values"] = [0.0624]
        document = _valid_document()
        document["sections"][0]["paragraphs"][0]["text"] = "可追溯样本变化为 6.24%，仍需结合后续数据观察。"
        self.assertEqual(validate_report(document, facts, public), [])

    def test_percentage_rounding_is_traceable_to_precise_evidence(self):
        facts = _facts()
        public = build_public_facts(facts)
        public["evidence"]["market:state"]["values"] = [-0.481099]
        document = _valid_document()
        document["sections"][0]["paragraphs"][0]["text"] = "成熟样本平均变化为 -0.48%，仅描述历史表现。"
        self.assertEqual(validate_report(document, facts, public), [])

    def test_precise_decimal_is_not_mistaken_for_a_stock_code(self):
        facts = _facts()
        public = build_public_facts(facts)
        public["evidence"]["market:state"]["values"] = [-0.481099]
        document = _valid_document()
        document["sections"][0]["paragraphs"][0]["text"] = "成熟样本平均变化为 -0.481099，仅描述历史表现。"
        self.assertEqual(validate_report(document, facts, public), [])

    def test_market_view_is_a_traceable_public_evidence_source(self):
        facts = _facts()
        public = build_public_facts(facts)
        document = _valid_document()
        document["sections"][0]["paragraphs"][0] = {
            "text": "市场综合观察显示主线仍有分裂，后续需要继续确认。",
            "evidence_ids": ["market_view"],
            "entity_refs": [],
        }
        self.assertEqual(validate_report(document, facts, public), [])

    def test_rejects_internal_language_unknown_evidence_and_unapproved_stock(self):
        facts = _facts()
        public = build_public_facts(facts)
        document = _valid_document()
        document["sections"][0]["paragraphs"][0] = {
            "text": "AI模型评分显示600519必涨。",
            "evidence_ids": ["missing:evidence"],
            "entity_refs": ["stock:600519.SH"],
        }
        errors = validate_report(document, facts, public)
        joined = " | ".join(errors)
        self.assertIn("unknown evidence id: missing:evidence", joined)
        self.assertIn("unapproved stock code: 600519", joined)
        self.assertIn("banned language", joined)

    def test_rejects_public_evidence_alias_in_article_text(self):
        facts = _facts()
        public = build_public_facts(facts)
        document = _valid_document()
        document["sections"][3]["paragraphs"][0]["text"] = "caution_view显示分歧仍然存在。"
        self.assertIn("banned language", " | ".join(validate_report(document, facts, public)))

    def test_allows_ai_industry_news_but_rejects_ai_generation_language(self):
        facts = _facts()
        public = build_public_facts(facts)
        document = _valid_document()
        paragraph = document["sections"][1]["paragraphs"][0]
        paragraph["text"] = "AI软件产业景气仍需结合行业扩散和成交承接继续确认。"
        self.assertNotIn("banned language", " | ".join(validate_report(document, facts, public)))

        paragraph["text"] = "本段内容由AI生成，行业方向仍需继续确认。"
        self.assertIn("banned language", " | ".join(validate_report(document, facts, public)))


if __name__ == "__main__":
    unittest.main()
