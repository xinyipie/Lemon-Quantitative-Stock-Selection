import tempfile
import unittest
import sqlite3
from pathlib import Path

from market_radar.store import (
    MarketRadarStoreBusyError,
    get_latest_market_radar_snapshot,
    save_market_radar_snapshot,
)


class MarketRadarStoreTest(unittest.TestCase):
    def test_save_market_radar_snapshot_upserts_by_date_and_round_trips_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "signals.db"
            brief = {
                "headline": "主线已验证：机械设备。",
                "snapshot_summary": {"event_count": 2, "thesis_count": 1, "stock_count": 1, "risk_count": 0},
                "verification_checklist": ["观察机械设备是否继续承接"],
            }
            decision = {"review_loop": {"closing_judgement": "主线已验证"}}

            first_id = save_market_radar_snapshot(db_path, "20260622", brief, decision)
            second_id = save_market_radar_snapshot(
                db_path,
                "20260622",
                {**brief, "headline": "主线已验证：机械设备，继续核验。"},
                decision,
            )
            latest = get_latest_market_radar_snapshot(db_path)

        self.assertEqual(first_id, second_id)
        self.assertEqual(latest["radar_date"], "20260622")
        self.assertEqual(latest["headline"], "主线已验证：机械设备，继续核验。")
        self.assertEqual(latest["closing_judgement"], "主线已验证")
        self.assertEqual(latest["brief"]["snapshot_summary"]["event_count"], 2)

    def test_get_latest_market_radar_snapshot_returns_empty_when_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            latest = get_latest_market_radar_snapshot(Path(tmpdir) / "missing.db")

        self.assertIsNone(latest)

    def test_read_does_not_create_schema_in_existing_empty_database(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "signals.db"
            sqlite3.connect(db_path).close()

            latest = get_latest_market_radar_snapshot(db_path)
            conn = sqlite3.connect(db_path)
            try:
                table = conn.execute(
                    "select name from sqlite_master where type='table' and name='market_radar_snapshots'"
                ).fetchone()
            finally:
                conn.close()

        self.assertIsNone(latest)
        self.assertIsNone(table)

    def test_read_reports_an_exclusive_database_lock(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "signals.db"
            save_market_radar_snapshot(db_path, "20260622", {"headline": "测试"}, {})
            conn = sqlite3.connect(db_path)
            conn.execute("begin exclusive")
            try:
                with self.assertRaises(MarketRadarStoreBusyError):
                    get_latest_market_radar_snapshot(db_path)
            finally:
                conn.rollback()
                conn.close()


if __name__ == "__main__":
    unittest.main()
