import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from market_context_snapshot import write_market_context_snapshot
from web_app.services.sector_service import build_concept_news_radar


class MarketContextSnapshotTest(unittest.TestCase):
    def test_snapshot_prefers_real_concept_provider(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            real_concepts = [{"concept": "AI PC", "change": 2.8, "heat": 70.0, "source": "ths"}]

            with patch(
                "market_context_snapshot.fetch_real_concept_heat", return_value=real_concepts
            ), patch(
                "market_context_snapshot.news_analyzer.get_hot_concepts"
            ) as legacy_concepts, patch(
                "market_context_snapshot.news_analyzer.get_policy_news", return_value=pd.DataFrame()
            ), patch(
                "market_context_snapshot.fetch_market_news", return_value=[]
            ):
                result = write_market_context_snapshot(
                    cache_dir=cache_dir,
                    snapshot_date="20260618",
                    call_ai_api_fn=lambda prompt, system="": "[]",
                )

            saved = json.loads((cache_dir / "hot_concepts_20260618.json").read_text(encoding="utf-8"))

        self.assertEqual(result["concept_count"], 1)
        self.assertEqual(saved[0]["concept"], "AI PC")
        legacy_concepts.assert_not_called()

    def test_snapshot_reuses_existing_concept_cache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            (cache_dir / "hot_concepts_20260618.json").write_text(
                '[{"concept": "Cached Theme", "change": 1.2, "heat": 55.0}]',
                encoding="utf-8",
            )

            with patch("market_context_snapshot.fetch_real_concept_heat") as real_concepts, patch(
                "market_context_snapshot.news_analyzer.get_policy_news", return_value=pd.DataFrame()
            ), patch(
                "market_context_snapshot.fetch_market_news", return_value=[]
            ):
                result = write_market_context_snapshot(
                    cache_dir=cache_dir,
                    snapshot_date="20260618",
                    call_ai_api_fn=lambda prompt, system="": "[]",
                )

            saved = json.loads((cache_dir / "hot_concepts_20260618.json").read_text(encoding="utf-8"))

        self.assertEqual(result["concept_count"], 1)
        self.assertEqual(saved[0]["concept"], "Cached Theme")
        real_concepts.assert_not_called()

    def test_snapshot_writes_ai_theme_filter_cache_once(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            ai_calls = []

            def fake_ai(prompt: str, system: str = "") -> str:
                ai_calls.append(prompt)
                return json.dumps(
                    [
                        {
                            "theme": "AI PC",
                            "level": "strong",
                            "horizon": "short",
                            "verdict": "强催化",
                            "reason": "涨幅靠前且消息催化明确",
                        }
                    ],
                    ensure_ascii=False,
                )

            with patch(
                "market_context_snapshot.fetch_real_concept_heat",
                return_value=[{"concept": "AI PC", "change": 2.8, "heat": 70.0, "reason": "产业消息"}],
            ), patch("market_context_snapshot.news_analyzer.get_policy_news", return_value=pd.DataFrame()), patch(
                "market_context_snapshot.fetch_market_news", return_value=[]
            ):
                result = write_market_context_snapshot(
                    cache_dir=cache_dir,
                    snapshot_date="20260618",
                    call_ai_api_fn=fake_ai,
                )

            saved = json.loads((cache_dir / "theme_filter_20260618.json").read_text(encoding="utf-8"))

        self.assertEqual(result["theme_count"], 1)
        self.assertEqual(saved["items"][0]["theme"], "AI PC")
        self.assertEqual(saved["items"][0]["level"], "strong")
        self.assertEqual(len(ai_calls), 1)

    def test_snapshot_reuses_existing_theme_filter_cache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            (cache_dir / "theme_filter_20260618.json").write_text(
                '{"date": "20260618", "items": [{"theme": "Cached AI", "level": "watch"}]}',
                encoding="utf-8",
            )

            with patch(
                "market_context_snapshot.fetch_real_concept_heat",
                return_value=[{"concept": "AI PC", "change": 2.8, "heat": 70.0}],
            ), patch("market_context_snapshot.news_analyzer.get_policy_news", return_value=pd.DataFrame()), patch(
                "market_context_snapshot.fetch_market_news", return_value=[]
            ):
                result = write_market_context_snapshot(
                    cache_dir=cache_dir,
                    snapshot_date="20260618",
                    call_ai_api_fn=lambda prompt, system="": self.fail("theme cache should avoid AI calls"),
                )

        self.assertEqual(result["theme_count"], 1)

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
            ), patch(
                "market_context_snapshot.fetch_real_concept_heat", return_value=[]
            ), patch(
                "market_context_snapshot.fetch_market_news", return_value=[]
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


    def test_snapshot_writes_raw_news_sources_for_detail_view(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            raw_news = [
                {
                    "title": "设备更新项目清单下达",
                    "source": "财联社",
                    "provider": "cls_key",
                    "providers": ["cls_key"],
                    "sources": ["财联社"],
                    "source_count": 1,
                    "publish_time": "2026-06-18 09:30:00",
                    "url": "https://example.com/news/1",
                    "content_excerpt": "2000亿设备更新清单即将下达，利好制造业。",
                }
            ]

            def fake_ai(prompt: str, system: str = "") -> str:
                return json.dumps(
                    [
                        {
                            "news": "设备更新项目清单下达",
                            "type": "产业政策",
                            "sectors": ["机械设备"],
                            "impact": "positive",
                            "strength": 8,
                            "duration": "1周",
                            "reason": "设备更新资金落地，利好制造业。",
                        }
                    ],
                    ensure_ascii=False,
                )

            with patch("market_context_snapshot.fetch_real_concept_heat", return_value=[]), patch(
                "market_context_snapshot.news_analyzer.get_hot_concepts", return_value=[]
            ), patch("market_context_snapshot.news_analyzer.get_policy_news", return_value=pd.DataFrame()), patch(
                "market_context_snapshot.fetch_market_news", return_value=raw_news, create=True
            ):
                write_market_context_snapshot(
                    cache_dir=cache_dir,
                    snapshot_date="20260618",
                    call_ai_api_fn=fake_ai,
                )

            payload = json.loads((cache_dir / "news_sector_20260618.json").read_text(encoding="utf-8"))

        self.assertEqual(payload["titles"], ["设备更新项目清单下达"])
        self.assertEqual(payload["raw_news"][0]["source"], "财联社")
        self.assertEqual(payload["raw_news"][0]["url"], "https://example.com/news/1")
        self.assertIn("设备更新", payload["raw_news"][0]["content_excerpt"])

    def test_snapshot_uses_top_30_value_ranked_news_for_ai(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            raw_news = [
                {
                    "title": f"高价值新闻{i:02d}",
                    "source": "测试源",
                    "provider": "test",
                    "providers": ["test"],
                    "sources": ["测试源"],
                    "source_count": 1,
                    "publish_time": f"2026-06-18 {i % 24:02d}:00:00",
                    "url": f"https://example.com/news/{i}",
                    "content_excerpt": "用于测试价值排序新闻输入。",
                    "news_value_score": 100 - i,
                }
                for i in range(35)
            ]
            ai_prompts = []

            def fake_ai(prompt: str, system: str = "") -> str:
                ai_prompts.append(prompt)
                return "[]"

            with patch("market_context_snapshot.fetch_real_concept_heat", return_value=[]), patch(
                "market_context_snapshot.news_analyzer.get_hot_concepts", return_value=[]
            ), patch("market_context_snapshot.news_analyzer.get_policy_news", return_value=pd.DataFrame()), patch(
                "market_context_snapshot.fetch_market_news", return_value=raw_news
            ) as fetch_news:
                write_market_context_snapshot(
                    cache_dir=cache_dir,
                    snapshot_date="20260618",
                    call_ai_api_fn=fake_ai,
                )

            payload = json.loads((cache_dir / "news_sector_20260618.json").read_text(encoding="utf-8"))

        fetch_news.assert_called_once_with(days=3, limit=100)
        self.assertEqual(len(payload["titles"]), 35)
        self.assertEqual(len(payload["ai_titles"]), 30)
        self.assertEqual(payload["raw_news_total"], 35)
        self.assertIn("高价值新闻00", ai_prompts[0])
        self.assertIn("高价值新闻29", ai_prompts[0])
        self.assertNotIn("高价值新闻30", ai_prompts[0])


    def test_snapshot_records_missing_ai_key_without_dropping_raw_news(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            raw_news = [
                {
                    "title": "AI infrastructure project approved",
                    "source": "test source",
                    "provider": "test",
                    "publish_time": "2026-07-14 09:00:00",
                    "url": "https://example.com/news/ai",
                    "content_excerpt": "The project entered construction.",
                    "news_value_score": 76.0,
                    "value_reason_text": "policy and industry",
                }
            ]

            with patch("market_context_snapshot.fetch_real_concept_heat", return_value=[]), patch(
                "market_context_snapshot.news_analyzer.get_hot_concepts", return_value=[]
            ), patch("market_context_snapshot.fetch_market_news", return_value=raw_news), patch.dict(
                "market_context_snapshot.config.AI_CONFIG", {"api_key": ""}
            ):
                write_market_context_snapshot(cache_dir=cache_dir, snapshot_date="20260714")

            payload = json.loads((cache_dir / "news_sector_20260714.json").read_text(encoding="utf-8"))

        self.assertEqual(payload["raw_news_total"], 1)
        self.assertEqual(payload["raw_news"][0]["title"], "AI infrastructure project approved")
        self.assertEqual(payload["items"], [])
        self.assertEqual(payload["boosts"], {})
        self.assertEqual(payload["ai_status"], "missing_api_key")
        self.assertIn("DEEPSEEK_API_KEY", payload["ai_message"])


if __name__ == "__main__":
    unittest.main()
