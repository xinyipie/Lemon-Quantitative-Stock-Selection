import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient

from history_store import HistoryStore
from signal_store import SignalRecord, SignalStore
from sector_heat_diagnostics import rank_sector_stocks
import web_app.app as web_app_module
from web_app.app import app, load_sector_page_cache, save_sector_page_cache
from web_app.services.sector_service import (
    build_concept_news_radar,
    build_market_radar_decision,
    build_sector_radar,
    build_strategy_overlap,
    decorate_sector_candidate_for_display,
)


def daily_rows(code: str, closes: list[float], industry: str, name: str) -> tuple[list[dict], dict]:
    rows = []
    prev = None
    for idx, close in enumerate(closes, start=1):
        trade_date = f"202501{idx:02d}"
        rows.append(
            {
                "trade_date": trade_date,
                "ts_code": code,
                "open": close,
                "high": close * 1.02,
                "low": close * 0.98,
                "close": close,
                "pct_chg": 0.0 if prev is None else (close - prev) / prev * 100,
                "amount": 1200 + idx * 50,
            }
        )
        prev = close
    return rows, {"ts_code": code, "symbol": code[:6], "name": name, "industry": industry, "list_status": "L"}


class SectorWebTest(unittest.TestCase):
    def setUp(self):
        web_app_module._sector_page_cache.clear()

    def make_history_db(self) -> Path:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        db_path = Path(tmpdir.name) / "history.db"
        store = HistoryStore(db_path)
        try:
            all_daily = []
            basics = []
            for code, name, industry, closes in [
                ("000001.SZ", "主线A", "稳步主线", [10, 10.1, 10.2, 10.4, 10.7, 11.0, 11.4, 11.8, 12.0, 12.3, 12.6, 12.9]),
                ("000002.SZ", "主线B", "稳步主线", [9, 9.1, 9.2, 9.5, 9.7, 10.0, 10.2, 10.5, 10.8, 11.0, 11.2, 11.5]),
                ("000003.SZ", "主线C", "稳步主线", [8, 8.1, 8.2, 8.3, 8.5, 8.7, 8.9, 9.1, 9.3, 9.5, 9.8, 10.0]),
                ("000004.SZ", "主线D", "稳步主线", [7, 7.1, 7.2, 7.3, 7.5, 7.7, 7.8, 8.0, 8.2, 8.4, 8.6, 8.8]),
                ("000011.SZ", "退潮A", "退潮板块", [10, 9.8, 9.7, 9.5, 9.3, 9.1, 8.9, 8.8, 8.6, 8.4, 8.2, 8.0]),
                ("000012.SZ", "退潮B", "退潮板块", [9, 8.9, 8.8, 8.6, 8.4, 8.3, 8.1, 7.9, 7.8, 7.6, 7.5, 7.3]),
                ("000013.SZ", "退潮C", "退潮板块", [8, 7.9, 7.8, 7.6, 7.5, 7.3, 7.2, 7.0, 6.9, 6.8, 6.6, 6.5]),
            ]:
                rows, basic = daily_rows(code, closes, industry, name)
                all_daily.extend(rows)
                basics.append(basic)
            store.upsert_dataframe("stock_daily", pd.DataFrame(all_daily))
            store.upsert_dataframe("stock_basic", pd.DataFrame(basics))
            daily_basic = [
                {"trade_date": "20250112", "ts_code": item["ts_code"], "turnover_rate": 4.0, "volume_ratio": 1.4, "total_mv": 100000}
                for item in basics
            ]
            store.upsert_dataframe("stock_daily_basic", pd.DataFrame(daily_basic))
            moneyflow = [
                {"trade_date": "20250112", "ts_code": item["ts_code"], "net_mf_amount": 2000 if item["industry"] == "稳步主线" else -1000}
                for item in basics
            ]
            store.upsert_dataframe("stock_moneyflow", pd.DataFrame(moneyflow))
            index_rows, _ = daily_rows("000300.SH", [10, 10, 10.1, 10.1, 10.2, 10.3, 10.3, 10.4, 10.5, 10.5, 10.6, 10.7], "", "")
            store.upsert_dataframe("index_daily", pd.DataFrame(index_rows))
        finally:
            store.close()
        return db_path

    def test_sector_radar_service_builds_user_facing_buckets(self):
        radar = build_sector_radar(self.make_history_db(), end_date="20250112", min_stocks=3)

        self.assertEqual(radar["end_date"], "20250112")
        self.assertEqual(radar["summary"]["market_line"], "有主线")
        self.assertGreaterEqual(len(radar["healthy"]), 1)
        self.assertGreaterEqual(len(radar["risky"]), 1)
        self.assertGreaterEqual(len(radar["candidates"]), 1)
        self.assertGreaterEqual(len(radar["candidate_groups"]), 1)
        self.assertEqual(radar["healthy"][0]["industry"], "稳步主线")
        self.assertEqual(radar["candidate_groups"][0]["industry"], "稳步主线")
        self.assertGreaterEqual(len(radar["candidate_groups"][0]["candidates"]), 1)
        self.assertIn(radar["healthy"][0]["action"], {"看承接", "低吸观察", "谨慎观察"})

    def test_sector_page_renders_market_radar(self):
        client = TestClient(app)

        response = client.get("/sectors")

        self.assertEqual(response.status_code, 200)
        self.assertIn("市场雷达", response.text)
        self.assertIn("健康主线", response.text)
        self.assertIn("板块候选", response.text)
        self.assertIn('id="risk-sectors"', response.text)
        self.assertIn("退潮中", response.text)
        self.assertIn("sector-candidate-group", response.text)
        self.assertIn("concept-heat-panel", response.text)
        self.assertIn("message-radar-panel", response.text)
        self.assertIn("\u5386\u53f2\u590d\u76d8", response.text)
        self.assertIn('id="radar-history-date" type="date"', response.text)
        self.assertIn('href="#news-concepts"', response.text)
        self.assertIn('id="sector-candidates"', response.text)

    def test_sector_page_renders_market_radar_v2_sections(self):
        client = TestClient(app)

        response = client.get("/sectors")

        self.assertEqual(response.status_code, 200)
        self.assertIn("market-radar-v2-brief", response.text)
        self.assertIn("radar-summary-bar", response.text)
        self.assertIn("radar-workbench", response.text)
        self.assertIn("event-workbench-main", response.text)
        self.assertIn("event-impact-columns", response.text)
        self.assertIn("risk-column", response.text)
        self.assertIn("positive-column", response.text)
        self.assertIn("radar-side-rail", response.text)
        self.assertIn("event-watchlist-panel", response.text)
        self.assertIn("sector-thesis-panel", response.text)
        self.assertIn("stock-evidence-panel", response.text)
        self.assertIn("research-grid", response.text)
        self.assertIn("stock-evidence-table", response.text)
        self.assertIn("review-loop-panel", response.text)
        self.assertIn("stock-evidence-reasons", response.text)
        self.assertLess(response.text.find("market-radar-v2-brief"), response.text.find('id="mainline-view"'))

    def test_sector_page_has_radar_only_update_button(self):
        client = TestClient(app)

        response = client.get("/sectors")

        self.assertEqual(response.status_code, 200)
        self.assertIn('action="/sectors/update"', response.text)
        self.assertIn("data-background-update-form", response.text)
        self.assertIn('data-update-status-url="/update/status"', response.text)
        self.assertIn("更新行情并刷新雷达", response.text)

    def test_sector_update_button_starts_radar_refresh_and_returns_to_page(self):
        client = TestClient(app)

        with patch("web_app.app.start_web_update") as start_update:
            start_update.return_value = {"state": "running", "started": True}
            response = client.post("/sectors/update", follow_redirects=False)

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/sectors")
        start_update.assert_called_once_with(mode="radar")

    def test_sector_update_button_can_start_without_page_redirect_for_ajax(self):
        client = TestClient(app)

        with patch("web_app.app.start_web_update") as start_update:
            start_update.return_value = {"state": "running", "started": True, "mode": "radar"}
            response = client.post("/sectors/update", headers={"Accept": "application/json"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["mode"], "radar")
        start_update.assert_called_once_with(mode="radar")

    def test_sector_page_reuses_short_lived_payload_cache(self):
        client = TestClient(app)
        fake_radar = {
            "end_date": "20260617",
            "summary": {
                "tone": "watch",
                "headline": "market test",
                "stance": "watch",
                "top_sector": "AI",
                "top_stage": "trend",
                "top_score": 80,
                "healthy_count": 1,
                "healthy_display_count": 1,
                "risky_count": 0,
                "risky_display_count": 0,
            },
            "message": "",
            "healthy": [],
            "risky": [],
            "candidate_groups": [],
        }
        fake_news = {
            "concepts": {"items": [], "source_date": "20260617", "source_kind": "empty", "message": ""},
            "theme_filter": {"items": [], "source_date": "20260617"},
            "news": {"source_date": "20260617", "selection": {}, "positive": [], "negative": [], "message": "", "items": []},
        }
        fake_decision = {
            "tone": "watch",
            "confidence": "medium",
            "alignment": "split",
            "primary_action": "watch",
            "explanation": "test",
            "focus_industries": [],
            "avoid_industries": [],
            "source_note": "source",
        }
        fake_overlap = {"source_date": "20260617", "items": [], "orphan_items": [], "conflict_items": [], "message": "no overlap"}
        with patch("web_app.app.build_sector_radar", return_value=fake_radar) as build_radar, patch(
            "web_app.app.build_concept_news_radar", return_value=fake_news
        ) as build_news, patch("web_app.app.build_market_radar_decision", return_value=fake_decision) as build_decision, patch(
            "web_app.app.build_strategy_overlap", return_value=fake_overlap
        ) as build_overlap:
            first = client.get("/sectors?end=20260617")
            second = client.get("/sectors?end=20260617")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(build_radar.call_count, 1)
        self.assertEqual(build_news.call_count, 1)
        self.assertEqual(build_decision.call_count, 1)
        self.assertEqual(build_overlap.call_count, 1)

    def test_sector_page_persisted_cache_round_trip_and_key_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "radar.pkl"
            payload = {
                "radar": {"end_date": "20260709"},
                "concept_news": {},
                "decision": {},
                "strategy_overlap": {},
            }

            save_sector_page_cache(cache_path, ("latest", "v1"), payload)
            dated_payload = {"radar": {"end_date": "20260708"}}
            save_sector_page_cache(cache_path, ("20260708", "v1"), dated_payload)

            self.assertEqual(
                load_sector_page_cache(cache_path, ("latest", "v1"))["radar"]["end_date"],
                "20260709",
            )
            self.assertEqual(
                load_sector_page_cache(cache_path, ("20260708", "v1"))["radar"]["end_date"],
                "20260708",
            )
            self.assertIsNone(load_sector_page_cache(cache_path, ("20260707", "v1")))

    def test_sector_page_uses_trader_message_workbench_layout(self):
        client = TestClient(app)

        response = client.get("/sectors")

        self.assertEqual(response.status_code, 200)
        self.assertIn("radar-refresh-strip", response.text)
        self.assertIn("历史复盘", response.text)
        self.assertIn("今日新增催化", response.text)
        self.assertIn("风险阻断", response.text)
        self.assertIn("背景消息", response.text)
        self.assertIn('id="key-events"', response.text)
        self.assertIn('id="strategy-overlap"', response.text)
        self.assertIn('id="sector-candidates"', response.text)

    def test_concept_news_radar_reads_cache_and_signal_boosts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            signal_db = Path(tmpdir) / "signals.db"
            cache_dir = Path(tmpdir) / "cache"
            cache_dir.mkdir()
            (cache_dir / "hot_concepts_20260616.json").write_text(
                '[{"concept":"AI","change":3.2,"heat":88.5},{"concept":"Robotics","change":1.1,"heat":55.0}]',
                encoding="utf-8",
            )
            (cache_dir / "theme_filter_20260616.json").write_text(
                '{"date":"20260616","items":[{"theme":"AI","level":"strong","verdict":"强催化","horizon":"short","reason":"真实概念热度靠前"}]}',
                encoding="utf-8",
            )
            store = SignalStore(signal_db)
            try:
                run_id = store.record_run(
                    "20260616",
                    mode="short",
                    profile="profile_v9_sector_quality_guard",
                    source="live",
                    label="daily",
                )
                store.update_pool(
                    run_id,
                    "20260616",
                    mode="short",
                    profile="profile_v9_sector_quality_guard",
                    records=[
                        SignalRecord(
                            ts_code="000001.SZ",
                            name="Alpha",
                            industry="Software",
                            score=76,
                            factors={"news_boost": 12, "concept_boost": 6, "hot_concept_match": True},
                        ),
                        SignalRecord(
                            ts_code="000002.SZ",
                            name="Beta",
                            industry="Property",
                            score=21,
                            factors={"news_boost": -8, "concept_boost": 0, "hot_concept_match": False},
                        ),
                    ],
                )
            finally:
                store.close()

            radar = build_concept_news_radar(signal_db=signal_db, cache_dir=cache_dir, today="20260616")

        self.assertEqual(radar["concepts"]["source_date"], "20260616")
        self.assertEqual(radar["concepts"]["items"][0]["concept"], "AI")
        self.assertEqual(radar["concepts"]["items"][0]["heat_text"], "88.5")
        self.assertEqual(radar["theme_filter"]["items"][0]["theme"], "AI")
        self.assertEqual(radar["theme_filter"]["items"][0]["level"], "strong")
        self.assertEqual(radar["news"]["positive"][0]["industry"], "Software")
        self.assertEqual(radar["news"]["positive"][0]["top_stocks"][0]["ts_code"], "000001.SZ")
        self.assertEqual(radar["news"]["negative"][0]["industry"], "Property")

    def test_sector_radar_exposes_display_counts_and_anchors(self):
        heat_rows = []
        for idx in range(9):
            heat_rows.append(
                {
                    "industry": f"健康{idx}",
                    "stage": "趋势延续",
                    "heat_score": 90 - idx,
                    "avg_ret_5d": 2.0,
                    "rel_ret_10d": 3.0,
                    "above_ma20_ratio": 0.8,
                    "volume_expansion_ratio": 0.5,
                    "stock_count": 12,
                    "summary": "健康主线",
                }
            )
        for idx in range(9):
            heat_rows.append(
                {
                    "industry": f"风险{idx}",
                    "stage": "退潮中",
                    "heat_score": 60 - idx,
                    "avg_ret_5d": -2.0,
                    "rel_ret_10d": -3.0,
                    "above_ma20_ratio": 0.2,
                    "volume_expansion_ratio": 0.3,
                    "stock_count": 10,
                    "summary": "风险板块",
                }
            )
        candidate_rows = [
            {
                "industry": "健康0",
                "candidate_rank": 1,
                "ts_code": "000001.SZ",
                "name": "候选A",
                "candidate_score": 72,
                "ret_5d": 1.2,
                "ret_10d": 3.4,
                "stock_vs_sector_10d": 0.8,
                "risk_note": "",
                "candidate_reason": "强于板块",
            }
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "history.db"
            db_path.touch()
            fake_frames = {"daily": pd.DataFrame(), "stock_basic": pd.DataFrame(), "daily_basic": pd.DataFrame(), "moneyflow": pd.DataFrame(), "index_daily": pd.DataFrame()}
            with patch("web_app.services.sector_service._latest_trade_date", return_value="20260616"), patch(
                "web_app.services.sector_service.load_history_frames", return_value=fake_frames
            ), patch(
                "web_app.services.sector_service.calculate_sector_heat",
                return_value=(pd.DataFrame(heat_rows), pd.DataFrame()),
            ), patch(
                "web_app.services.sector_service.rank_sector_stocks",
                return_value=pd.DataFrame(candidate_rows),
            ):
                radar = build_sector_radar(db_path, top_sectors=8)

        self.assertEqual(radar["summary"]["healthy_count"], 9)
        self.assertEqual(radar["summary"]["healthy_display_count"], 8)
        self.assertEqual(radar["summary"]["risky_count"], 9)
        self.assertEqual(radar["summary"]["risky_display_count"], 8)
        self.assertEqual(radar["healthy"][0]["anchor_id"], "sector-健康0")
        self.assertEqual(radar["candidate_groups"][0]["anchor_id"], "sector-健康0")

    def test_concept_heat_falls_back_to_news_sector_cache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir) / "cache"
            cache_dir.mkdir()
            (cache_dir / "hot_concepts_20260616.json").write_text("[]", encoding="utf-8")
            (cache_dir / "news_sector_20260616.json").write_text(
                """
                {
                  "date": "20260616",
                  "items": [
                    {"news": "AI算力政策继续支持", "sectors": ["计算机"], "impact": "positive", "strength": 8, "reason": "政策催化"}
                  ],
                  "boosts": {"计算机": 21}
                }
                """,
                encoding="utf-8",
            )
            radar = build_concept_news_radar(signal_db=Path(tmpdir) / "missing.db", cache_dir=cache_dir, today="20260616")

        self.assertEqual(radar["concepts"]["source_date"], "20260616")
        self.assertEqual(radar["concepts"]["source_kind"], "news_proxy")
        self.assertEqual(radar["concepts"]["items"][0]["concept"], "消息面：计算机")
        self.assertIn("政策催化", radar["news"]["positive"][0]["reasons"])

    def test_news_cache_exposes_selection_audit_and_ranked_news_items(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir) / "cache"
            cache_dir.mkdir()
            (cache_dir / "news_sector_20260616.json").write_text(
                """
                {
                  "date": "20260616",
                  "titles": [
                    "两部门推动设备更新，电力设备和机械设备需求提升",
                    "银行转债融资压力升温",
                    "普通公司动态不构成行业催化",
                    "重复报道：设备更新政策继续推进"
                  ],
                  "items": [
                    {
                      "news": "两部门推动设备更新，电力设备和机械设备需求提升",
                      "type": "产业政策",
                      "sectors": ["机械设备", "电力设备"],
                      "impact": "positive",
                      "strength": 8,
                      "duration": "1-3天",
                      "reason": "政策催化明确，利好设备链"
                    },
                    {
                      "news": "银行转债融资压力升温",
                      "type": "资金压力",
                      "sectors": ["银行"],
                      "impact": "negative",
                      "strength": 6,
                      "duration": "短期",
                      "reason": "资本补充压力扰动估值"
                    }
                  ],
                  "boosts": {"机械设备": 24, "电力设备": 24, "银行": -12}
                }
                """,
                encoding="utf-8",
            )

            radar = build_concept_news_radar(signal_db=Path(tmpdir) / "missing.db", cache_dir=cache_dir, today="20260616")

        selection = radar["news"]["selection"]
        self.assertEqual(selection["raw_title_count"], 4)
        self.assertEqual(selection["ai_item_count"], 2)
        self.assertEqual(selection["displayed_sector_count"], 3)
        self.assertIn("4条候选新闻", selection["path_text"])
        self.assertIn("价值排序", selection["path_text"])
        self.assertEqual(radar["news"]["items"][0]["grade"], "A级")
        self.assertEqual(radar["news"]["items"][0]["quality"], "产业政策")
        self.assertIn("入选依据", radar["news"]["items"][0]["why_selected"])
        self.assertEqual(radar["news"]["items"][1]["grade"], "B级")
        self.assertEqual(radar["event_summary"]["event_count"], 2)
        self.assertEqual(radar["event_summary"]["positive_count"], 1)
        self.assertEqual(radar["events"][0]["materiality"], "A")
        self.assertEqual(radar["events"][0]["event_type"], "产业政策")
        self.assertTrue(radar["events"][0]["verification_points"])

    def test_news_cache_merges_duplicate_news_and_adds_trade_details(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir) / "cache"
            cache_dir.mkdir()
            (cache_dir / "news_sector_20260616.json").write_text(
                """
                {
                  "date": "20260616",
                  "titles": [
                    "设备更新项目清单下达",
                    "设备更新项目清单下达",
                    "银行转债融资压力升温"
                  ],
                  "items": [
                    {
                      "news": "设备更新项目清单下达",
                      "type": "产业政策",
                      "sectors": ["机械设备"],
                      "impact": "positive",
                      "strength": 8,
                      "duration": "1周+",
                      "reason": "设备更新资金落地，利好制造业"
                    },
                    {
                      "news": "设备更新项目清单下达",
                      "type": "产业政策",
                      "sectors": ["电力设备"],
                      "impact": "positive",
                      "strength": 8,
                      "duration": "1周+",
                      "reason": "同一事件继续映射设备链"
                    },
                    {
                      "news": "银行转债融资压力升温",
                      "type": "资金压力",
                      "sectors": ["银行"],
                      "impact": "negative",
                      "strength": 6,
                      "duration": "短期",
                      "reason": "资本补充压力扰动估值"
                    }
                  ],
                  "boosts": {"机械设备": 24, "电力设备": 24, "银行": -12}
                }
                """,
                encoding="utf-8",
            )

            radar = build_concept_news_radar(signal_db=Path(tmpdir) / "missing.db", cache_dir=cache_dir, today="20260616")

        news_items = radar["news"]["items"]
        self.assertEqual(len(news_items), 2)
        self.assertEqual(news_items[0]["title"], "设备更新项目清单下达")
        self.assertEqual(set(news_items[0]["sectors"]), {"机械设备", "电力设备"})
        self.assertIn("产业政策 → 机械设备、电力设备", news_items[0]["impact_path"])
        self.assertIn("不单独构成买入理由", news_items[0]["trading_hint"])
        self.assertGreaterEqual(len(news_items[0]["verification_points"]), 2)
        self.assertIn("持续性", news_items[0]["risk_note"])

    def test_sector_page_shows_news_detail_control_without_duplicate_news_section(self):
        client = TestClient(app)

        response = client.get("/sectors")

        self.assertEqual(response.status_code, 200)
        self.assertIn('id="news-concepts"', response.text)
        self.assertIn('href="#sector-candidates"', response.text)
        self.assertNotIn("消息行业明细", response.text)

    def test_news_cache_attaches_raw_source_details_to_ai_item(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir) / "cache"
            cache_dir.mkdir()
            (cache_dir / "news_sector_20260618.json").write_text(
                json.dumps(
                    {
                        "date": "20260618",
                        "titles": ["设备更新项目清单下达"],
                        "raw_news": [
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
                        ],
                        "items": [
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
                        "boosts": {"机械设备": 24},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            radar = build_concept_news_radar(signal_db=Path(tmpdir) / "missing.db", cache_dir=cache_dir, today="20260618")

        item = radar["news"]["items"][0]
        self.assertEqual(item["source_title"], "设备更新项目清单下达")
        self.assertEqual(item["source"], "财联社")
        self.assertEqual(item["source_url"], "https://example.com/news/1")
        self.assertIn("利好制造业", item["source_excerpt"])

    def test_news_cache_matches_short_ai_title_to_long_raw_title(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir) / "cache"
            cache_dir.mkdir()
            (cache_dir / "news_sector_20260618.json").write_text(
                json.dumps(
                    {
                        "date": "20260618",
                        "titles": ["国家安全部：警惕软件供应链投毒"],
                        "raw_news": [
                            {
                                "title": "国家安全部：警惕软件供应链投毒",
                                "source": "东方财富",
                                "provider": "eastmoney",
                                "providers": ["eastmoney"],
                                "sources": ["东方财富"],
                                "source_count": 1,
                                "publish_time": "2026-06-18 07:13:02",
                                "url": "https://example.com/security",
                                "content_excerpt": "近期集中爆发多起供应链投毒攻击事件。",
                            }
                        ],
                        "items": [
                            {
                                "news": "警惕软件供应链投毒",
                                "type": "风险提示",
                                "sectors": ["计算机"],
                                "impact": "negative",
                                "strength": 6,
                                "duration": "短期",
                                "reason": "软件供应链安全风险升温。",
                            }
                        ],
                        "boosts": {"计算机": -12},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            radar = build_concept_news_radar(signal_db=Path(tmpdir) / "missing.db", cache_dir=cache_dir, today="20260618")

        item = radar["news"]["items"][0]
        self.assertEqual(item["source_title"], "国家安全部：警惕软件供应链投毒")
        self.assertEqual(item["source_url"], "https://example.com/security")

    def test_news_cache_fuzzy_matches_ai_summary_title_to_raw_title(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir) / "cache"
            cache_dir.mkdir()
            (cache_dir / "news_sector_20260618.json").write_text(
                json.dumps(
                    {
                        "date": "20260618",
                        "titles": ["美国总统特朗普签署了一项旨在结束对伊战争并重开霍尔木兹海峡的临时协议"],
                        "raw_news": [
                            {
                                "title": "美国总统特朗普签署了一项旨在结束对伊战争并重开霍尔木兹海峡的临时协议",
                                "source": "财新",
                                "provider": "caixin",
                                "providers": ["caixin"],
                                "sources": ["财新"],
                                "source_count": 1,
                                "publish_time": "2026-06-18",
                                "url": "https://example.com/hormuz",
                                "content_excerpt": "协议结束战争并重开海峡。",
                            }
                        ],
                        "items": [
                            {
                                "news": "特朗普签署霍尔木兹协议",
                                "type": "国际政治",
                                "sectors": ["采掘"],
                                "impact": "positive",
                                "strength": 9,
                                "duration": "1周+",
                                "reason": "利好油价稳定预期。",
                            }
                        ],
                        "boosts": {"采掘": 27},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            radar = build_concept_news_radar(signal_db=Path(tmpdir) / "missing.db", cache_dir=cache_dir, today="20260618")

        item = radar["news"]["items"][0]
        self.assertEqual(item["source_title"], "美国总统特朗普签署了一项旨在结束对伊战争并重开霍尔木兹海峡的临时协议")
        self.assertEqual(item["source_url"], "https://example.com/hormuz")

    def test_sector_page_renders_raw_news_source_details(self):
        client = TestClient(app)
        fake_radar = {
            "end_date": "20260618",
            "summary": {
                "tone": "neutral",
                "headline": "行业热度测试",
                "stance": "仅测试",
                "top_sector": "-",
                "top_stage": "-",
                "top_score": 0,
                "healthy_count": 0,
                "healthy_display_count": 0,
                "risky_count": 0,
                "risky_display_count": 0,
            },
            "message": "",
            "healthy": [],
            "risky": [],
            "candidate_groups": [],
        }
        fake_news = {
            "concepts": {"items": [], "message": "", "source_kind": "empty"},
            "theme_filter": {"items": []},
            "news": {
                "source_date": "20260618",
                "selection": {"path_text": "1条原始新闻", "quality_text": "A", "rule_text": "测试"},
                "positive": [],
                "negative": [],
                "message": "",
                "items": [
                    {
                        "tone": "ok",
                        "grade": "A级",
                        "title": "设备更新项目清单下达",
                        "impact": "positive",
                        "impact_text": "利好",
                        "boost_text": "+24.0",
                        "quality": "产业政策",
                        "strength_text": "8/10",
                        "duration": "1周",
                        "sectors_text": "机械设备",
                        "reason": "设备更新资金落地。",
                        "why_selected": "来源可信。",
                        "source_title": "设备更新项目清单下达",
                        "source": "财联社",
                        "source_time": "2026-06-18 09:30:00",
                        "source_url": "https://example.com/news/1",
                        "source_excerpt": "2000亿设备更新清单即将下达，利好制造业。",
                        "source_providers_text": "财联社",
                        "raw_source_count": 1,
                        "impact_path": "产业政策 -> 机械设备",
                        "trading_hint": "只做催化解释。",
                        "risk_note": "注意兑现风险。",
                        "verification_points": ["看行业承接"],
                    }
                ],
            },
        }
        with patch("web_app.app.build_sector_radar", return_value=fake_radar), patch(
            "web_app.app.build_concept_news_radar", return_value=fake_news
        ), patch("web_app.app.build_market_radar_decision", return_value={"tone": "neutral", "confidence": "低", "alignment": "测试", "primary_action": "观察", "explanation": "", "focus_industries": [], "avoid_industries": [], "source_note": ""}), patch(
            "web_app.app.build_strategy_overlap", return_value={"items": [], "message": "无"}
        ):
            response = client.get("/sectors")

        self.assertEqual(response.status_code, 200)
        self.assertIn("原始新闻", response.text)
        self.assertIn("财联社", response.text)
        self.assertIn("message-source-time", response.text)
        self.assertIn("2026-06-18 09:30:00", response.text)
        self.assertIn("https://example.com/news/1", response.text)
        self.assertIn("2000亿设备更新", response.text)

    def test_sector_page_get_does_not_persist_market_radar_snapshot(self):
        client = TestClient(app)
        fake_radar = {
            "end_date": "20260622",
            "summary": {
                "tone": "neutral",
                "headline": "行业热度测试",
                "stance": "仅测试",
                "top_sector": "-",
                "top_stage": "-",
                "top_score": 0,
                "healthy_count": 0,
                "healthy_display_count": 0,
                "risky_count": 0,
                "risky_display_count": 0,
            },
            "message": "",
            "healthy": [],
            "risky": [],
            "candidate_groups": [],
        }
        fake_news = {
            "concepts": {"items": [], "message": "", "source_kind": "empty"},
            "theme_filter": {"items": []},
            "news": {"source_date": "20260622", "selection": {}, "positive": [], "negative": [], "message": "", "items": []},
            "events": [],
            "event_summary": {"event_count": 0},
        }
        fake_brief = {
            "headline": "仍待验证：无清晰主线。",
            "snapshot_summary": {"event_count": 1, "thesis_count": 0, "stock_count": 1, "risk_count": 0},
            "risk_blocker": {
                "level": "暂停新关注",
                "tone": "danger",
                "reason": "计算机 命中A级负面事件：美国限制外国获取AI模型",
                "research_guardrail": "先记录风险释放和承接修复。",
            },
            "event_groups": {
                "risk": [
                    {
                        "title": "美国限制外国获取AI模型",
                        "impact_label": "利空",
                        "impact_tone": "bad",
                        "materiality": "A",
                        "impact_degree_text": "A级利空：可能改变板块风险偏好",
                        "effect_summary": "压制计算机风险偏好，先看风险是否释放。",
                        "event_type": "监管",
                        "source_quality": "主流财经",
                        "mapping_confidence": "medium",
                        "mapped_industries": ["计算机"],
                        "original_source": "财联社",
                        "collection_source": "本地新闻缓存",
                        "publish_time": "2026-06-22 09:15:00",
                        "collected_at": "2026-06-22 20:00:00",
                        "catalyst_clock": "D0 新催化",
                        "verification_points": ["观察计算机是否继续释放风险"],
                        "industry_anchor": "thesis-计算机",
                        "stock_anchor": "stocks-计算机",
                        "source_url": "https://example.com/ai",
                    }
                ],
                "positive": [],
                "unverified": [],
                "all": [],
            },
            "mainlines": [],
            "event_watchlist": [
                {
                    "title": "美国限制外国获取AI模型",
                    "materiality": "A",
                    "event_type": "监管",
                    "source_quality": "主流财经",
                    "mapping_confidence": "medium",
                    "mapped_industries": ["计算机"],
                    "source_name": "财联社",
                    "publish_time": "2026-06-22 09:15:00",
                    "collected_at": "2026-06-22 20:00:00",
                    "catalyst_clock": "D0 新催化",
                    "verification_points": ["观察计算机是否继续释放风险"],
                }
            ],
            "sector_theses": [],
            "stock_watchlist": [
                {
                    "ts_code": "688721.SH",
                    "name": "龙图光罩",
                    "industry": "半导体",
                    "stock_role": "领涨",
                    "event_relevance": "行业主线受益",
                    "market_behavior": "放量承接",
                    "research_action": "可重点跟踪",
                    "resonance_level": "★★★",
                    "resonance_label": "策略+主线+事件共振",
                    "reason_cards": [{"type": "量价", "label": "放量承接"}],
                    "validation_conditions": ["盘中观察：半导体前60分钟成交额是否高于近5日同段均值。"],
                }
            ],
            "risk_board": [],
            "verification_checklist": [],
            "data_quality": {"tone": "ok"},
        }
        fake_decision = {
            "tone": "neutral",
            "confidence": "低",
            "alignment": "无清晰主线",
            "primary_action": "观察",
            "explanation": "",
            "focus_industries": [],
            "avoid_industries": [],
            "source_note": "",
            "research_brief": fake_brief,
        }
        with patch("web_app.app.build_sector_radar", return_value=fake_radar), patch(
            "web_app.app.build_concept_news_radar", return_value=fake_news
        ), patch("web_app.app.build_market_radar_decision", return_value=fake_decision), patch(
            "web_app.app.build_strategy_overlap", return_value={"items": [], "message": "无"}
        ), patch("web_app.app.save_market_radar_snapshot", return_value=1) as save_snapshot, patch(
            "web_app.app.get_latest_market_radar_snapshot",
            return_value={"radar_date": "20260622", "headline": fake_brief["headline"]},
        ):
            response = client.get("/sectors")

        self.assertEqual(response.status_code, 200)
        save_snapshot.assert_not_called()
        self.assertIn("\u98ce\u9669\u963b\u65ad", response.text)
        self.assertIn("\u6682\u505c\u65b0\u5173\u6ce8", response.text)
        self.assertIn("\u98ce\u9669\u4f18\u5148", response.text)
        self.assertIn("\u4eca\u65e5\u65b0\u589e\u50ac\u5316", response.text)
        self.assertIn("\u6765\u6e90\u5f85\u6838\u9a8c", response.text)
        self.assertIn("\u5229\u7a7a A\u7ea7", response.text)
        self.assertIn("A\u7ea7\u5229\u7a7a\uff1a\u53ef\u80fd\u6539\u53d8\u677f\u5757\u98ce\u9669\u504f\u597d", response.text)
        self.assertIn("\u539f\u59cb\u5a92\u4f53\uff1a\u8d22\u8054\u793e", response.text)
        self.assertIn("\u91c7\u96c6\u901a\u9053\uff1a\u65b0\u95fb\u7f13\u5b58", response.text)
        self.assertIn('href="#thesis-\u8ba1\u7b97\u673a', response.text)
        self.assertIn('href="https://example.com/ai"', response.text)
        self.assertIn('class="event-title-link"', response.text)
        self.assertIn("\u53d1\u5e03\uff1a2026-06-22 09:15:00", response.text)
        self.assertIn("\u2605\u2605\u2605 \u7b56\u7565+\u4e3b\u7ebf+\u4e8b\u4ef6\u5171\u632f", response.text)
        self.assertIn("\u524d60\u5206\u949f\u6210\u4ea4\u989d", response.text)

    def test_risky_sector_actions_are_nuanced(self):
        heat_rows = [
            {
                "industry": "过热A",
                "stage": "过热高潮",
                "heat_score": 90,
                "avg_ret_5d": 12.0,
                "rel_ret_10d": 9.0,
                "above_ma20_ratio": 0.95,
                "volume_expansion_ratio": 0.9,
                "stock_count": 20,
                "summary": "加速过热",
            },
            {
                "industry": "退潮A",
                "stage": "退潮中",
                "heat_score": 40,
                "avg_ret_5d": -6.0,
                "rel_ret_10d": -8.0,
                "above_ma20_ratio": 0.1,
                "volume_expansion_ratio": 0.2,
                "stock_count": 20,
                "summary": "退潮较深",
            },
            {
                "industry": "退潮B",
                "stage": "退潮中",
                "heat_score": 55,
                "avg_ret_5d": -1.0,
                "rel_ret_10d": -1.5,
                "above_ma20_ratio": 0.45,
                "volume_expansion_ratio": 0.35,
                "stock_count": 20,
                "summary": "等待企稳",
            },
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "history.db"
            db_path.touch()
            fake_frames = {"daily": pd.DataFrame(), "stock_basic": pd.DataFrame(), "daily_basic": pd.DataFrame(), "moneyflow": pd.DataFrame(), "index_daily": pd.DataFrame()}
            with patch("web_app.services.sector_service._latest_trade_date", return_value="20260616"), patch(
                "web_app.services.sector_service.load_history_frames", return_value=fake_frames
            ), patch(
                "web_app.services.sector_service.calculate_sector_heat",
                return_value=(pd.DataFrame(heat_rows), pd.DataFrame()),
            ), patch(
                "web_app.services.sector_service.rank_sector_stocks",
                return_value=pd.DataFrame(),
            ):
                radar = build_sector_radar(db_path, top_sectors=8)

        actions = {item["action"] for item in radar["risky"]}
        self.assertIn("停止追涨", actions)
        self.assertIn("暂不参与", actions)
        self.assertIn("等待企稳", actions)

    def test_sector_candidate_action_labels_are_actionable(self):
        strong = decorate_sector_candidate_for_display(
            {"candidate_score": 82, "stock_vs_sector_10d": 3.0, "risk_note": ""}
        )
        normal = decorate_sector_candidate_for_display(
            {"candidate_score": 55, "stock_vs_sector_10d": 1.0, "risk_note": ""}
        )
        overheated = decorate_sector_candidate_for_display(
            {"candidate_score": 88, "stock_vs_sector_10d": 12.0, "risk_note": "位置偏高，不追高"}
        )

        self.assertEqual(strong["action_tag"], "可重点跟踪")
        self.assertEqual(strong["tone"], "ok")
        self.assertEqual(normal["action_tag"], "先放观察池")
        self.assertEqual(normal["tone"], "watch")
        self.assertEqual(overheated["action_tag"], "等回踩确认")
        self.assertEqual(overheated["tone"], "warn")

    def test_market_radar_decision_identifies_mainline_alignment(self):
        radar = {
            "end_date": "20260616",
            "summary": {"market_line": "有主线", "healthy_count": 2, "risky_count": 1},
            "healthy": [
                {"industry": "计算机", "stage": "趋势延续", "heat_score": 82, "action": "看承接"},
                {"industry": "铜", "stage": "低位启动", "heat_score": 76, "action": "低吸观察"},
            ],
            "risky": [{"industry": "银行", "stage": "退潮中", "heat_score": 35}],
        }
        concept_news = {
            "news": {
                "positive": [{"industry": "计算机", "impact_score": 21}],
                "negative": [{"industry": "银行", "impact_score": -12}],
            },
            "concepts": {"items": []},
            "theme_filter": {"items": []},
        }

        decision = build_market_radar_decision(radar, concept_news)

        self.assertEqual(decision["alignment"], "主线共振")
        self.assertEqual(decision["confidence"], "高")
        self.assertEqual(decision["focus_industries"], ["计算机"])
        self.assertIn("优先", decision["primary_action"])
        self.assertIn("银行", decision["avoid_industries"])
        self.assertEqual(decision["top_thesis"]["industry"], "计算机")
        self.assertEqual(decision["top_thesis"]["thesis_label"], "主线共振")
        self.assertTrue(decision["sector_theses"])

    def test_market_radar_decision_uses_event_thesis_when_news_group_is_missing(self):
        radar = {
            "end_date": "20260616",
            "summary": {"market_line": "有主线", "healthy_count": 1, "risky_count": 0},
            "healthy": [
                {"industry": "机械设备", "stage": "趋势延续", "heat_score": 84, "volume_ratio": 1.4},
            ],
            "risky": [],
        }
        concept_news = {
            "news": {"positive": [], "negative": []},
            "events": [
                {
                    "title": "设备更新项目清单下达",
                    "event_type": "产业政策",
                    "impact": "positive",
                    "materiality": "A",
                    "mapped_industries": ["机械设备"],
                    "mapping_confidence": "medium",
                    "source_quality": "官方/监管",
                    "verification_points": ["观察机械设备是否放量承接"],
                }
            ],
            "concepts": {"items": []},
            "theme_filter": {"items": []},
        }

        decision = build_market_radar_decision(radar, concept_news)

        self.assertEqual(decision["alignment"], "主线共振")
        self.assertEqual(decision["focus_industries"], ["机械设备"])
        self.assertEqual(decision["top_thesis"]["research_action"], "可重点跟踪")

    def test_market_radar_decision_outputs_stock_watchlist_evidence_cards(self):
        radar = {
            "end_date": "20260616",
            "summary": {"market_line": "有主线", "healthy_count": 1, "risky_count": 0},
            "healthy": [
                {"industry": "机械设备", "stage": "趋势延续", "heat_score": 84, "volume_ratio": 1.4},
            ],
            "risky": [],
            "candidates": [
                {
                    "ts_code": "000001.SZ",
                    "name": "设备龙头",
                    "industry": "机械设备",
                    "candidate_score": 82,
                    "ret_5d": 4.2,
                    "ret_10d": 9.5,
                    "stock_vs_sector_10d": 5.6,
                    "volume_ratio": 1.8,
                    "risk_note": "",
                }
            ],
        }
        concept_news = {
            "news": {"positive": [], "negative": []},
            "events": [
                {
                    "title": "设备更新项目清单下达",
                    "event_type": "产业政策",
                    "impact": "positive",
                    "materiality": "A",
                    "mapped_industries": ["机械设备"],
                    "mapping_confidence": "medium",
                    "source_quality": "官方/监管",
                    "verification_points": ["观察机械设备是否放量承接"],
                }
            ],
            "concepts": {"items": []},
            "theme_filter": {"items": []},
        }

        decision = build_market_radar_decision(radar, concept_news)

        self.assertEqual(decision["stock_watchlist"][0]["ts_code"], "000001.SZ")
        self.assertEqual(decision["stock_watchlist"][0]["event_relevance"], "行业主线受益")
        self.assertEqual(decision["stock_watchlist"][0]["research_action"], "可重点跟踪")
        self.assertTrue(decision["stock_watchlist"][0]["reason_cards"])

    def test_market_radar_decision_outputs_review_loop(self):
        radar = {
            "end_date": "20260616",
            "summary": {"market_line": "有主线", "healthy_count": 1, "risky_count": 0},
            "healthy": [
                {"industry": "机械设备", "stage": "趋势延续", "heat_score": 84, "volume_ratio": 1.4},
            ],
            "risky": [],
            "candidates": [
                {
                    "ts_code": "000001.SZ",
                    "name": "设备龙头",
                    "industry": "机械设备",
                    "candidate_score": 82,
                    "ret_10d": 9.5,
                    "stock_vs_sector_10d": 5.6,
                    "volume_ratio": 1.8,
                }
            ],
        }
        concept_news = {
            "news": {"positive": [], "negative": []},
            "events": [
                {
                    "title": "设备更新项目清单下达",
                    "event_type": "产业政策",
                    "impact": "positive",
                    "materiality": "A",
                    "mapped_industries": ["机械设备"],
                    "mapping_confidence": "medium",
                    "source_quality": "官方/监管",
                    "verification_points": ["观察机械设备是否放量承接"],
                }
            ],
            "concepts": {"items": []},
            "theme_filter": {"items": []},
        }

        decision = build_market_radar_decision(radar, concept_news)

        self.assertEqual(decision["review_loop"]["closing_judgement"], "主线已验证")
        self.assertEqual(decision["review_loop"]["validated_mainlines"][0]["industry"], "机械设备")
        self.assertTrue(decision["review_loop"]["next_day_watch_points"])
        self.assertEqual(decision["research_brief"]["mainlines"][0]["industry"], "机械设备")
        self.assertEqual(decision["research_brief"]["event_watchlist"][0]["title"], "设备更新项目清单下达")
        self.assertTrue(decision["research_brief"]["verification_checklist"])

    def test_strategy_overlap_uses_real_signals_inside_healthy_or_news_sectors(self):
        radar = {
            "end_date": "20260616",
            "healthy": [
                {"industry": "计算机", "stage": "趋势延续", "heat_score": 82, "action": "看承接"},
                {"industry": "铜", "stage": "低位启动", "heat_score": 76, "action": "低吸观察"},
            ],
        }
        concept_news = {
            "news": {
                "positive": [{"industry": "计算机", "impact_score": 21}],
                "negative": [],
            }
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            signal_db = Path(tmpdir) / "signals.db"
            store = SignalStore(signal_db)
            try:
                run_id = store.record_run(
                    "20260616",
                    mode="short",
                    profile="profile_v9_sector_quality_guard",
                    source="live",
                    label="daily",
                )
                store.update_pool(
                    run_id,
                    "20260616",
                    mode="short",
                    profile="profile_v9_sector_quality_guard",
                    records=[
                        SignalRecord(ts_code="000001.SZ", name="AI强股", industry="计算机", score=70, rank=1, reason="短线信号"),
                        SignalRecord(ts_code="000002.SZ", name="铜强股", industry="铜", score=66, rank=2, reason="短线信号"),
                        SignalRecord(ts_code="000003.SZ", name="无关强股", industry="银行", score=90, rank=3, reason="短线信号"),
                    ],
                )
            finally:
                store.close()

            overlap = build_strategy_overlap(signal_db, radar, concept_news, limit=5)

        codes = [item["ts_code"] for item in overlap["items"]]
        self.assertEqual(codes, ["000001.SZ", "000002.SZ"])
        self.assertEqual(overlap["source_date"], "20260616")
        self.assertEqual(overlap["items"][0]["industry"], "计算机")
        self.assertIn("策略信号", overlap["items"][0]["reason"])


    def test_strategy_overlap_filters_st_risk_names(self):
        radar = {
            "end_date": "20260616",
            "healthy": [{"industry": "components", "stage": "trend", "heat_score": 82, "action": "watch"}],
        }
        concept_news = {"news": {"positive": [], "negative": []}}
        with tempfile.TemporaryDirectory() as tmpdir:
            signal_db = Path(tmpdir) / "signals.db"
            store = SignalStore(signal_db)
            try:
                run_id = store.record_run(
                    "20260616",
                    mode="short",
                    profile="profile_v9_sector_quality_guard",
                    source="live",
                    label="daily",
                )
                store.update_pool(
                    run_id,
                    "20260616",
                    mode="short",
                    profile="profile_v9_sector_quality_guard",
                    records=[
                        SignalRecord(ts_code="002217.SZ", name="ST risk sample", industry="components", score=70, rank=1, reason="short"),
                        SignalRecord(ts_code="000001.SZ", name="normal sample", industry="components", score=65, rank=2, reason="short"),
                    ],
                )
            finally:
                store.close()

            overlap = build_strategy_overlap(signal_db, radar, concept_news, limit=5)

        codes = [item["ts_code"] for item in overlap["items"]]
        self.assertEqual(codes, ["000001.SZ"])

    def test_strategy_overlap_filters_profit_collapse_risk(self):
        radar = {
            "end_date": "20260616",
            "healthy": [{"industry": "components", "stage": "trend", "heat_score": 82, "action": "watch"}],
        }
        concept_news = {"news": {"positive": [], "negative": []}}
        with tempfile.TemporaryDirectory() as tmpdir:
            signal_db = Path(tmpdir) / "signals.db"
            history_db = Path(tmpdir) / "history.db"
            conn = sqlite3.connect(history_db)
            conn.execute(
                """
                create table fina_indicator (
                    ts_code text,
                    ann_date text,
                    end_date text,
                    roe real,
                    debt_to_assets real,
                    netprofit_yoy real,
                    grossprofit_margin real,
                    netprofit_margin real
                )
                """
            )
            conn.executemany(
                "insert into fina_indicator values (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    ("002217.SZ", "20260423", "20260331", 0.04, 26.3, -79.7, 17.8, 0.48),
                    ("000001.SZ", "20260423", "20260331", 9.0, 45.0, 8.0, 30.0, 12.0),
                ],
            )
            conn.commit()
            conn.close()

            store = SignalStore(signal_db)
            try:
                run_id = store.record_run(
                    "20260616",
                    mode="short",
                    profile="profile_v9_sector_quality_guard",
                    source="live",
                    label="daily",
                )
                store.update_pool(
                    run_id,
                    "20260616",
                    mode="short",
                    profile="profile_v9_sector_quality_guard",
                    records=[
                        SignalRecord(ts_code="002217.SZ", name="profit collapse sample", industry="components", score=70, rank=1, reason="short"),
                        SignalRecord(ts_code="000001.SZ", name="normal sample", industry="components", score=65, rank=2, reason="short"),
                    ],
                )
            finally:
                store.close()

            overlap = build_strategy_overlap(signal_db, radar, concept_news, limit=5, history_db=history_db)

        codes = [item["ts_code"] for item in overlap["items"]]
        self.assertEqual(codes, ["000001.SZ"])

    def test_strategy_overlap_separates_resonant_orphan_and_conflict_signals(self):
        radar = {
            "end_date": "20260616",
            "healthy": [{"industry": "AI", "stage": "trend", "heat_score": 82, "action": "watch"}],
            "risky": [{"industry": "Bank", "stage": "fade", "heat_score": 30, "action": "avoid"}],
        }
        concept_news = {"news": {"positive": [], "negative": [{"industry": "Bank", "impact_score": -12}]}}
        with tempfile.TemporaryDirectory() as tmpdir:
            signal_db = Path(tmpdir) / "signals.db"
            store = SignalStore(signal_db)
            try:
                run_id = store.record_run("20260616", mode="short", profile="profile", source="live", label="daily")
                store.update_pool(
                    run_id,
                    "20260616",
                    mode="short",
                    profile="profile",
                    records=[
                        SignalRecord(ts_code="000001.SZ", name="resonant", industry="AI", score=70, rank=1, reason="short"),
                        SignalRecord(ts_code="000002.SZ", name="orphan", industry="Retail", score=80, rank=2, reason="short"),
                        SignalRecord(ts_code="000003.SZ", name="conflict", industry="Bank", score=90, rank=3, reason="short"),
                    ],
                )
            finally:
                store.close()

            overlap = build_strategy_overlap(signal_db, radar, concept_news, limit=5)

        self.assertEqual([item["ts_code"] for item in overlap["items"]], ["000001.SZ"])
        self.assertEqual([item["ts_code"] for item in overlap["orphan_items"]], ["000002.SZ"])
        self.assertEqual([item["ts_code"] for item in overlap["conflict_items"]], ["000003.SZ"])

    def test_sector_candidate_relative_copy_uses_neutral_wording(self):
        lagging = decorate_sector_candidate_for_display(
            {
                "candidate_score": 55.0,
                "ret_5d": 12.5,
                "ret_10d": 9.8,
                "stock_vs_sector_10d": -14.01,
                "risk_note": "节奏相对健康，继续跟踪承接",
                "candidate_reason": "强于板块-14.01%，量能2.36倍，资金+4129万",
                "industry": "玻璃",
            }
        )
        leading = decorate_sector_candidate_for_display(
            {
                "candidate_score": 55.0,
                "ret_5d": 12.5,
                "ret_10d": 9.8,
                "stock_vs_sector_10d": 6.5,
                "risk_note": "节奏相对健康，继续跟踪承接",
                "candidate_reason": "强于板块+6.50%，量能2.36倍，资金+4129万",
                "industry": "玻璃",
            }
        )

        self.assertEqual(lagging["sector_relative_label"], "落后板块")
        self.assertIn("相对板块-14.01%", lagging["candidate_reason"])
        self.assertNotIn("强于板块", lagging["candidate_reason"])
        self.assertEqual(leading["sector_relative_label"], "领先板块")
        self.assertIn("相对板块+6.50%", leading["candidate_reason"])

    def test_sector_candidate_ranking_demotes_severe_sector_laggard(self):
        stocks = pd.DataFrame(
            [
                {
                    "industry": "Glass",
                    "ts_code": "000001.SZ",
                    "name": "laggard",
                    "ret_5d": 4.0,
                    "ret_10d": 11.0,
                    "sector_ret_10d": 25.0,
                    "above_ma20": True,
                    "amount_ratio_5d": 2.0,
                    "net_mf_amount": 5000.0,
                    "turnover_rate": 8.0,
                    "position_20d": 0.60,
                },
                {
                    "industry": "Glass",
                    "ts_code": "000002.SZ",
                    "name": "leader",
                    "ret_5d": 3.0,
                    "ret_10d": 27.0,
                    "sector_ret_10d": 25.0,
                    "above_ma20": True,
                    "amount_ratio_5d": 1.0,
                    "net_mf_amount": 0.0,
                    "turnover_rate": 2.0,
                    "position_20d": 0.65,
                },
            ]
        )
        sectors = pd.DataFrame([{"industry": "Glass", "stage": "trend", "heat_score": 85.0}])

        ranked = rank_sector_stocks(stocks, sectors, top_sectors=1, top_stocks=2)

        self.assertEqual(ranked.iloc[0]["ts_code"], "000002.SZ")
        self.assertGreater(ranked.iloc[1]["candidate_priority"], ranked.iloc[0]["candidate_priority"])

    def test_market_radar_decision_flags_misaligned_sector_and_news_dates(self):
        radar = {
            "end_date": "20260617",
            "summary": {"market_line": "ok", "healthy_count": 1, "risky_count": 0},
            "healthy": [{"industry": "AI", "stage": "trend", "heat_score": 82}],
            "risky": [],
        }
        concept_news = {
            "news": {"source_date": "20260622", "positive": [{"industry": "AI", "impact_score": 21}], "negative": []},
            "concepts": {"source_date": "20260622", "items": []},
            "theme_filter": {"source_date": "20260622", "items": []},
        }

        decision = build_market_radar_decision(radar, concept_news)

        self.assertFalse(decision["data_alignment"]["aligned"])
        self.assertEqual(decision["data_alignment"]["sector_date"], "20260617")
        self.assertEqual(decision["data_alignment"]["news_date"], "20260622")
        self.assertEqual(decision["data_alignment"]["tone"], "warn")
        self.assertNotEqual(decision["confidence"], "高")

    def test_broad_news_sector_mapping_is_marked_as_low_confidence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir) / "cache"
            cache_dir.mkdir()
            (cache_dir / "news_sector_20260622.json").write_text(
                json.dumps(
                    {
                        "date": "20260622",
                        "titles": ["AI export improves"],
                        "items": [
                            {
                                "news": "AI export improves",
                                "type": "industry trend",
                                "sectors": ["electronics", "computer", "telecom", "media"],
                                "impact": "positive",
                                "strength": 7,
                                "duration": "1w",
                                "reason": "generic AI chain benefit",
                            }
                        ],
                        "boosts": {"electronics": 21, "computer": 21, "telecom": 21, "media": 12},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            radar = build_concept_news_radar(signal_db=Path(tmpdir) / "missing.db", cache_dir=cache_dir, today="20260622")

        item = radar["news"]["items"][0]
        self.assertEqual(item["mapping_confidence"], "broad")
        self.assertEqual(item["mapping_confidence_text"], "泛化映射")
        self.assertIn("broad", item["mapping_note"])

    def test_raw_news_remains_visible_when_ai_mapping_is_unavailable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir) / "cache"
            cache_dir.mkdir()
            (cache_dir / "news_sector_20260714.json").write_text(
                json.dumps(
                    {
                        "date": "20260714",
                        "raw_news_total": 1,
                        "raw_news": [
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
                        ],
                        "items": [],
                        "boosts": {},
                        "ai_status": "missing_api_key",
                        "ai_message": "AI mapping unavailable; raw news is visible but does not affect sector scores.",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            radar = build_concept_news_radar(
                signal_db=Path(tmpdir) / "missing.db",
                cache_dir=cache_dir,
                today="20260714",
            )

        self.assertEqual(radar["news"]["source_date"], "20260714")
        self.assertEqual(len(radar["news"]["items"]), 1)
        self.assertEqual(radar["news"]["items"][0]["title"], "AI infrastructure project approved")
        self.assertEqual(radar["news"]["items"][0]["impact"], "neutral")
        self.assertEqual(radar["news"]["positive"], [])
        self.assertEqual(radar["news"]["negative"], [])
        self.assertIn("does not affect sector scores", radar["news"]["message"])

    def test_strategy_overlap_empty_db_returns_stable_bucket_schema(self):
        overlap = build_strategy_overlap(
            signal_db=Path("missing_signal_pool_for_test.db"),
            radar={"healthy": [], "risky": []},
            concept_news={"news": {"positive": [], "negative": []}},
        )

        self.assertEqual(overlap["items"], [])
        self.assertEqual(overlap["orphan_items"], [])
        self.assertEqual(overlap["conflict_items"], [])
        self.assertEqual(overlap["orphan_count"], 0)
        self.assertEqual(overlap["conflict_count"], 0)

    def test_sector_page_renders_alignment_and_strategy_signal_buckets(self):
        client = TestClient(app)
        fake_radar = {
            "end_date": "20260617",
            "summary": {
                "tone": "watch",
                "headline": "market test",
                "stance": "watch",
                "top_sector": "AI",
                "top_stage": "trend",
                "top_score": 80,
                "healthy_count": 1,
                "healthy_display_count": 1,
                "risky_count": 1,
                "risky_display_count": 1,
            },
            "message": "",
            "healthy": [],
            "risky": [],
            "candidate_groups": [],
        }
        fake_news = {
            "concepts": {"items": [], "source_date": "20260622", "source_kind": "empty", "message": ""},
            "theme_filter": {"items": [], "source_date": "20260622"},
            "news": {
                "source_date": "20260622",
                "selection": {},
                "positive": [],
                "negative": [],
                "message": "",
                "items": [
                    {
                        "tone": "ok",
                        "grade": "B",
                        "title": "AI export improves",
                        "impact": "positive",
                        "impact_text": "good",
                        "boost_text": "+21.0",
                        "quality": "industry trend",
                        "strength_text": "7/10",
                        "duration": "1w",
                        "sectors_text": "electronics, computer, telecom, media",
                        "reason": "generic",
                        "why_selected": "selected",
                        "mapping_confidence": "broad",
                        "mapping_note": "broad mapping: test",
                        "verification_points": [],
                    }
                ],
            },
        }
        fake_decision = {
            "tone": "watch",
            "confidence": "medium",
            "alignment": "split",
            "primary_action": "watch",
            "explanation": "test",
            "focus_industries": [],
            "avoid_industries": [],
            "source_note": "source",
            "data_alignment": {
                "aligned": False,
                "tone": "warn",
                "sector_date": "20260617",
                "news_date": "20260622",
                "concept_date": "20260622",
                "message": "dates mismatch",
            },
        }
        fake_overlap = {
            "source_date": "20260617",
            "items": [],
            "orphan_items": [{"ts_code": "000001.SZ", "name": "orphan", "score_text": "80.0", "industry": "Retail", "mode_text": "short", "action": "watch", "reason": "no sector"}],
            "conflict_items": [{"ts_code": "000002.SZ", "name": "conflict", "score_text": "70.0", "industry": "Bank", "mode_text": "short", "action": "review", "reason": "risk"}],
            "message": "no overlap",
        }
        with patch("web_app.app.build_sector_radar", return_value=fake_radar), patch(
            "web_app.app.build_concept_news_radar", return_value=fake_news
        ), patch("web_app.app.build_market_radar_decision", return_value=fake_decision), patch(
            "web_app.app.build_strategy_overlap", return_value=fake_overlap
        ):
            response = client.get("/sectors")

        self.assertEqual(response.status_code, 200)
        self.assertIn("dates mismatch", response.text)
        self.assertIn("orphan", response.text)
        self.assertIn("conflict", response.text)
        self.assertIn("broad mapping: test", response.text)


if __name__ == "__main__":
    unittest.main()
