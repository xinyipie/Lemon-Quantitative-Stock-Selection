import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

os.environ["LEMON_SKIP_TUSHARE_INIT"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
from signal_store import SignalRecord, SignalStore


class LiveSignalPersistenceTest(unittest.TestCase):
    def test_persist_signal_snapshot_saves_short_watch_and_elite_profiles(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "signals.db"
            short_pool = pd.DataFrame(
                [{"code": "000001", "name": "短A", "industry": "银行", "score": 56, "factor_profile": "profile_v9_sector_quality_guard"}]
            )
            long_watch = pd.DataFrame(
                [{"ts_code": "000002.SZ", "name": "长B", "industry": "AI", "compression_score": 82, "pool_type": "longterm_watch"}]
            )
            long_elite = pd.DataFrame(
                [{"ts_code": "000003.SZ", "name": "长C", "industry": "医药", "compression_score": 91, "pool_type": "longterm_elite"}]
            )

            main._persist_signal_snapshot(
                trade_date="20260612",
                stock_pool=short_pool,
                longterm_watch=long_watch,
                longterm_elite=long_elite,
                db_path=db_path,
            )

            conn = sqlite3.connect(db_path)
            try:
                rows = conn.execute(
                    "select mode, profile, ts_code, pool_type from signal_pool order by ts_code"
                ).fetchall()
            finally:
                conn.close()

        self.assertEqual(
            rows,
            [
                ("short", "profile_v9_sector_quality_guard", "000001.SZ", "short_top"),
                ("longterm", "longterm_watch", "000002.SZ", "longterm_watch"),
                ("longterm", "longterm_elite", "000003.SZ", "longterm_elite"),
            ],
        )

    def test_elite_cooldown_suppresses_recent_repeated_alerts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "signals.db"
            store = SignalStore(db_path)
            try:
                run_id = store.record_run("20260601", "longterm", "longterm_elite", source="live")
                store.update_pool(
                    run_id,
                    "20260601",
                    "longterm",
                    "longterm_elite",
                    [SignalRecord(ts_code="000001.SZ", name="A", score=91, pool_type="longterm_elite")],
                )
            finally:
                store.close()

            watch = pd.DataFrame(
                [{"ts_code": "000001.SZ", "name": "A", "elite_alert": True, "alert_tier": "elite"}]
            )
            elite = pd.DataFrame(
                [{"ts_code": "000001.SZ", "name": "A", "compression_score": 92, "pool_type": "longterm_elite"}]
            )

            filtered_watch, filtered_elite = main._apply_longterm_elite_cooldown(
                watch,
                elite,
                trade_date="20260612",
                db_path=db_path,
            )

        self.assertTrue(filtered_elite.empty)
        self.assertFalse(bool(filtered_watch.iloc[0]["elite_alert"]))
        self.assertEqual(filtered_watch.iloc[0]["alert_tier"], "watch")


if __name__ == "__main__":
    unittest.main()
