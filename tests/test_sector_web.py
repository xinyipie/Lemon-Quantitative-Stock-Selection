import tempfile
import unittest
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from history_store import HistoryStore
from signal_store import SignalRecord, SignalStore
from web_app.app import app
from web_app.services.sector_service import build_concept_news_radar, build_sector_radar


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
        self.assertIn("过热/退潮", response.text)
        self.assertIn("sector-candidate-group", response.text)
        self.assertIn("concept-heat-panel", response.text)
        self.assertIn("news-impact-panel", response.text)

    def test_concept_news_radar_reads_cache_and_signal_boosts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            signal_db = Path(tmpdir) / "signals.db"
            cache_dir = Path(tmpdir) / "cache"
            cache_dir.mkdir()
            (cache_dir / "hot_concepts_20260616.json").write_text(
                '[{"concept":"AI","change":3.2,"heat":88.5},{"concept":"Robotics","change":1.1,"heat":55.0}]',
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
        self.assertEqual(radar["news"]["positive"][0]["industry"], "Software")
        self.assertEqual(radar["news"]["positive"][0]["top_stocks"][0]["ts_code"], "000001.SZ")
        self.assertEqual(radar["news"]["negative"][0]["industry"], "Property")


if __name__ == "__main__":
    unittest.main()
