import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ai_prompts


class AiPromptOutputTest(unittest.TestCase):
    def test_short_prompt_requires_conditional_execution_plan(self):
        prompt = ai_prompts.PROMPT_STOCK_ANALYSIS

        for field in [
            "buy_condition",
            "avoid_condition",
            "stop_plan",
            "take_profit_plan",
            "position_advice",
        ]:
            self.assertIn(field, prompt)

        self.assertIn("明日执行计划", prompt)
        self.assertIn("条件式", prompt)
        self.assertIn("不承诺收益", prompt)
        self.assertIn("不生成自动下单", prompt)


if __name__ == "__main__":
    unittest.main()
