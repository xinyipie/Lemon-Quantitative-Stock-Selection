import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from market_context_snapshot import write_market_context_snapshot
from web_app.services.sector_service import build_concept_news_radar


class MarketContextSnapshotTest(unittest.TestCase):
    def test_snapshot_writes_concept_and_news_cache_for_sector_radar(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            news_df = pd.DataFrame([{"title": "AI算力政策继续支持"}])

            def fake_ai(prompt: str, system: str = "") -> str:
                return json.dumps(
                    [
                        {
                            "news": "AI算力政策继续支持",
                            "type": "产业政策",
                            "sectors": ["计算机"],
                            "impact": "positive",
                            "strength": 8,
                            "duration": "1-3天",
                            "reason": "政策催化",
                        }
                    ],
                    ensure_ascii=False,
                )

            with patch("market_context_snapshot.news_analyzer.get_hot_concepts") as hot_concepts, patch(
                "market_context_snapshot.news_analyzer.get_policy_news", return_value=news_df
            ):
                hot_concepts.return_value = [{"concept": "AI算力", "change": 3.2, "heat": 88.5}]
                result = write_market_context_snapshot(
                    cache_dir=cache_dir,
                    snapshot_date="20260616",
                    call_ai_api_fn=fake_ai,
                )

            radar = build_concept_news_radar(signal_db=cache_dir / "missing.db", cache_dir=cache_dir, today="20260616")

        self.assertTrue(result["concept_count"] >= 1)
        self.assertTrue(result["news_item_count"] >= 1)
        self.assertEqual(radar["concepts"]["items"][0]["concept"], "AI算力")
        self.assertEqual(radar["news"]["positive"][0]["industry"], "计算机")
        self.assertEqual(radar["news"]["positive"][0]["impact_text"], "+24.0")


if __name__ == "__main__":
    unittest.main()
