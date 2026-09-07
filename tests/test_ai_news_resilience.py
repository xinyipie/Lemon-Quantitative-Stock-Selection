import json
import unittest
from unittest.mock import Mock, patch

import news_analyzer
from market_context_snapshot import AI_CALL_DIAGNOSTICS, call_ai_api


class AiNewsResilienceTest(unittest.TestCase):
    def test_parser_accepts_markdown_wrapped_items_object(self):
        payload = {
            "items": [
                {
                    "news": "设备更新",
                    "type": "产业政策",
                    "sectors": ["机械设备"],
                    "impact": "positive",
                    "strength": 8,
                    "duration": "1-3天",
                    "reason": "政策催化",
                }
            ]
        }

        result = news_analyzer.ai_parse_news_to_sectors(
            ["设备更新"],
            lambda prompt, system="": f"分析如下：\n```json\n{json.dumps(payload, ensure_ascii=False)}\n```",
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["sectors"], ["机械设备"])

    def test_parser_reports_invalid_mapping_fields(self):
        result = news_analyzer.ai_parse_news_to_sectors(
            ["设备更新"],
            lambda prompt, system="": '[{"news":"设备更新","sectors":[],"impact":"unknown","strength":8}]',
        )

        self.assertEqual(result, [])
        self.assertIn("字段校验", news_analyzer.get_ai_news_diagnostic())

    @patch("market_context_snapshot.config.AI_CONFIG", {
        "api_key": "test-key",
        "base_url": "https://example.com/chat/completions",
        "model": "deepseek-chat",
        "temperature": 0.1,
        "max_tokens": 100,
        "timeout": 5,
    })
    @patch("market_context_snapshot.requests.post")
    def test_api_retries_once_after_timeout(self, post):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"choices": [{"message": {"content": "[]"}}]}
        post.side_effect = [__import__("requests").Timeout(), response]

        result = call_ai_api("test")

        self.assertEqual(result, "[]")
        self.assertEqual(post.call_count, 2)
        self.assertEqual(AI_CALL_DIAGNOSTICS["status"], "ok")

    @patch("market_context_snapshot.config.AI_CONFIG", {
        "api_key": "test-key",
        "base_url": "https://example.com/chat/completions",
        "model": "deepseek-v4-flash",
        "temperature": 0.1,
        "max_tokens": 100,
        "timeout": 5,
    })
    @patch("market_context_snapshot.requests.post")
    def test_api_supports_reasoning_model_and_json_mode(self, post):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"choices": [{"message": {"content": "{}"}}]}
        post.return_value = response

        result = call_ai_api(
            "test",
            model="deepseek-v4-pro",
            thinking=True,
            json_mode=True,
        )

        self.assertEqual(result, "{}")
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["model"], "deepseek-v4-pro")
        self.assertEqual(payload["thinking"], {"type": "enabled", "reasoning_effort": "high"})
        self.assertEqual(payload["response_format"], {"type": "json_object"})


if __name__ == "__main__":
    unittest.main()
