import unittest

import pandas as pd

from web_app.services.dragon_service import enrich_short_pool_with_dragon_sentiment


class DragonShortLinkTest(unittest.TestCase):
    def test_enrich_short_pool_adds_explainable_adjustment(self):
        pool = pd.DataFrame(
            [
                {
                    "code": "000001",
                    "name": "低位制造",
                    "industry": "机械设备",
                    "score": 60.0,
                }
            ]
        )
        observation = {
            "themes": [
                {
                    "theme_name": "机器人",
                    "primary_industry": "机械设备",
                    "theme_state": "主线确认",
                    "theme_score": 82.0,
                    "risk_notes": [],
                }
            ]
        }

        enriched = enrich_short_pool_with_dragon_sentiment(pool, observation)

        self.assertGreater(enriched.iloc[0]["score"], 60.0)
        self.assertEqual(enriched.iloc[0]["dragon_theme_state"], "主线确认")
        self.assertIn("主线共振", enriched.iloc[0]["dragon_reason"])

    def test_enrich_short_pool_penalizes_receding_theme(self):
        pool = pd.DataFrame([{"code": "000002", "name": "高位跟风", "industry": "传媒", "score": 55.0}])
        observation = {
            "themes": [
                {
                    "theme_name": "短剧",
                    "primary_industry": "传媒",
                    "theme_state": "退潮回避",
                    "theme_score": 18.0,
                    "risk_notes": ["高位断板扩散"],
                }
            ]
        }

        enriched = enrich_short_pool_with_dragon_sentiment(pool, observation)

        self.assertLess(enriched.iloc[0]["score"], 55.0)
        self.assertEqual(enriched.iloc[0]["dragon_risk"], "高位断板扩散")

    def test_signal_factor_payload_keeps_dragon_fields(self):
        from main import _signal_factor_payload

        row = pd.Series(
            {
                "score": 66.0,
                "factor_inflow": 60,
                "factor_sector": 65,
                "factor_pattern": 70,
                "factor_volume_ratio": 55,
                "factor_drawdown": 50,
                "factor_wyckoff": 45,
                "volume_ratio": 1.8,
                "dragon_adjustment": 6.0,
                "dragon_theme_state": "主线确认",
                "dragon_theme_name": "机器人",
                "dragon_theme_score": 82.0,
                "dragon_reason": "龙头情绪：主线共振 +6",
                "dragon_risk": "",
            }
        )

        payload = _signal_factor_payload(row)

        self.assertEqual(payload["dragon_adjustment"], 6.0)
        self.assertEqual(payload["dragon_theme_state"], "主线确认")
        self.assertIn("主线共振", payload["dragon_reason"])


if __name__ == "__main__":
    unittest.main()
