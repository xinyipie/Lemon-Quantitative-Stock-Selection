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
        self.assertEqual(config.AI_CONFIG["model"], "deepseek-chat")

    def test_tushare_uses_project_relay_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            reloaded = importlib.reload(config)
            self.assertEqual(reloaded.TUSHARE_CONFIG["http_url"], "http://14.nat0.cn:32817")
        importlib.reload(config)


if __name__ == "__main__":
    unittest.main()
