import os
import sys
import unittest
import importlib
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config


class TestAIConfig(unittest.TestCase):
    def test_default_ai_provider_uses_deepseek_env_key(self):
        self.assertEqual(config.AI_CONFIG["provider"], "deepseek")
        self.assertEqual(config.AI_CONFIG["api_key"], os.environ.get("DEEPSEEK_API_KEY", ""))
        self.assertEqual(config.AI_CONFIG["base_url"], "https://api.deepseek.com/v1/chat/completions")
        self.assertEqual(config.AI_CONFIG["model"], "deepseek-v4-flash")
        self.assertEqual(config.AI_CONFIG["fast_model"], "deepseek-v4-flash")
        self.assertEqual(config.AI_CONFIG["reasoning_model"], "deepseek-v4-pro")

    def test_tushare_defaults_to_user_confirmed_legacy_relay(self):
        with patch.dict(os.environ, {}, clear=True):
            reloaded = importlib.reload(config)
            self.assertEqual(reloaded.TUSHARE_CONFIG["http_url"], "http://111.170.34.57:8010")
        importlib.reload(config)

    def test_tushare_accepts_original_relay_and_https_override(self):
        self.assertEqual(config.require_secure_tushare_url("http://111.170.34.57:8010/"), "http://111.170.34.57:8010")
        self.assertEqual(config.require_secure_tushare_url("https://provider.example/"), "https://provider.example")

    def test_tushare_rejects_unrelated_http_or_embedded_credentials(self):
        for value in ("http://other.example", "http://111.170.34.57:8010/other", "https://user:password@provider.example", "ftp://provider.example", ""):
            with self.subTest(value=value), self.assertRaises(ValueError):
                config.require_secure_tushare_url(value)


if __name__ == "__main__":
    unittest.main()
