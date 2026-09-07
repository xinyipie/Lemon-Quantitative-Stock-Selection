import sys
import json
import re
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ai_prompts


class AiPromptOutputTest(unittest.TestCase):
    def test_short_prompt_renders_valid_observation_schema(self):
        prompt = ai_prompts.PROMPT_STOCK_ANALYSIS.format(
            data_date="20260907", market_context="震荡", stock_list="样本股票"
        )
        schema = json.loads(re.search(r'\{\s*"code".*?\}', prompt, re.S).group())
        self.assertTrue({"summary", "positives", "risks", "watch_plan", "invalidation"} <= schema.keys())
        self.assertFalse({"score", "position_advice", "buy_condition"} & schema.keys())


if __name__ == "__main__":
    unittest.main()
