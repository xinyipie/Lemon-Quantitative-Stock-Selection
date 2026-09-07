import json
import unittest

from daily_report.writer import generate_report_document


class _Response:
    def __init__(self, content):
        self.content = content
        self.status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": self.content}}]}


class DailyReportWriterTest(unittest.TestCase):
    def test_two_pass_writer_sends_public_facts_and_returns_document(self):
        calls = []
        draft = {
            "judgements": [{"text": "结构分化", "confidence": "中", "evidence_ids": ["market:state"]}],
            "focus_entities": ["stock:000001.SZ"],
            "conflicts": [{"text": "扩散不足", "evidence_ids": ["market:state"]}],
            "watch_questions": [{"text": "承接能否延续", "evidence_ids": ["market:state"]}],
        }
        document = {
            "title": "缩量分化下更需观察承接持续性",
            "sections": [{"key": key, "heading": key, "paragraphs": [{"text": "事实段落。", "evidence_ids": ["market:state"], "entity_refs": []}]}
                         for key in ("core_judgement", "market_context", "focus", "performance_risk", "watch_points")],
            "keywords": ["银行"],
        }

        def post(url, **kwargs):
            calls.append({"url": url, **kwargs})
            payload = draft if len(calls) == 1 else document
            return _Response("```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```")

        result = generate_report_document(
            {"report_date": "20260723", "evidence": {"market:state": {"values": [45]}}},
            ai_config={"api_key": "test-key", "base_url": "https://example.test/chat/completions", "model": "test-model", "timeout": 3},
            post=post,
        )

        self.assertEqual(len(calls), 2)
        second_prompt = calls[1]["json"]["messages"][1]["content"]
        self.assertIn("结构分化", second_prompt)
        self.assertNotIn("short_formal", second_prompt)
        self.assertEqual(result["title"], document["title"])
        self.assertEqual(len(result["sections"]), 5)

    def test_daily_report_uses_flash_for_evidence_and_reasoning_model_for_final_copy(self):
        calls = []
        draft = {
            "judgements": [{"text": "结构分化", "confidence": "中", "evidence_ids": ["market:state"]}],
            "focus_entities": [],
            "conflicts": [],
            "watch_questions": [],
        }
        document = {
            "title": "结构分化下继续验证行业承接",
            "sections": [
                {"key": key, "heading": key, "paragraphs": [{"text": "事实段落。", "evidence_ids": ["market:state"], "entity_refs": []}]}
                for key in ("core_judgement", "market_context", "focus", "performance_risk", "watch_points")
            ],
            "keywords": [],
        }

        def post(url, **kwargs):
            calls.append(kwargs["json"])
            payload = draft if len(calls) == 1 else document
            return _Response(json.dumps(payload, ensure_ascii=False))

        result = generate_report_document(
            {"report_date": "20260813", "evidence": {"market:state": {"values": [45]}}},
            ai_config={
                "api_key": "test-key",
                "base_url": "https://example.test/chat/completions",
                "model": "deepseek-v4-flash",
                "reasoning_model": "deepseek-v4-pro",
                "timeout": 3,
            },
            post=post,
        )

        self.assertEqual([call["model"] for call in calls], ["deepseek-v4-flash", "deepseek-v4-pro"])
        self.assertEqual(calls[0]["thinking"]["type"], "disabled")
        self.assertEqual(calls[1]["thinking"]["type"], "enabled")
        self.assertEqual(calls[1]["thinking"]["reasoning_effort"], "high")
        self.assertEqual(result["ai_model"], "deepseek-v4-pro")
        self.assertEqual(result["ai_thinking"], "high")
        self.assertEqual(result["ai_pipeline"], "two_pass_reasoning")

    def test_missing_key_and_malformed_json_return_none(self):
        self.assertIsNone(generate_report_document({}, ai_config={"api_key": ""}, post=lambda *a, **k: None))

        def malformed(*args, **kwargs):
            return _Response("not json")

        self.assertIsNone(
            generate_report_document(
                {},
                ai_config={"api_key": "key", "base_url": "https://example.test", "model": "m", "timeout": 1},
                post=malformed,
            )
        )

    def test_timeout_returns_none(self):
        def timeout(*args, **kwargs):
            raise TimeoutError("timeout")

        self.assertIsNone(
            generate_report_document(
                {},
                ai_config={"api_key": "key", "base_url": "https://example.test", "model": "m", "timeout": 1},
                post=timeout,
            )
        )


if __name__ == "__main__":
    unittest.main()
