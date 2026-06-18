import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from signal_store import SignalRecord, SignalStore


class SignalStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "signals.db"
        self.store = SignalStore(self.db_path)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def fetch_events(self):
        conn = sqlite3.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute("select * from pool_events order by id")]
        finally:
            conn.close()

    def fetch_state(self):
        conn = sqlite3.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute("select * from pool_state order by ts_code")]
        finally:
            conn.close()

    def test_first_snapshot_creates_run_pool_rows_and_new_events(self):
        run_id = self.store.record_run(
            trade_date="20250605",
            mode="short",
            profile="short_v9",
            source="live",
            label="daily",
        )

        self.store.update_pool(
            run_id=run_id,
            trade_date="20250605",
            mode="short",
            profile="short_v9",
            records=[
                SignalRecord(ts_code="000001.SZ", name="平安银行", industry="银行", rank=1, score=88.5, pool_type="buyable", reason="短线强势"),
                SignalRecord(ts_code="000002.SZ", name="万科A", industry="地产", rank=2, score=82.0, pool_type="watch", reason="修复观察"),
            ],
        )

        events = self.fetch_events()
        state = self.fetch_state()
        self.assertEqual([e["event_type"] for e in events], ["NEW", "NEW"])
        self.assertEqual(len(state), 2)
        self.assertTrue(all(row["state"] == "active" for row in state))
        self.assertEqual(state[0]["first_seen_date"], "20250605")

    def test_second_snapshot_adds_new_removes_missing_and_keeps_existing_without_duplicate_new(self):
        first_run = self.store.record_run("20250605", "longterm", "repair_v1", source="live")
        self.store.update_pool(
            run_id=first_run,
            trade_date="20250605",
            mode="longterm",
            profile="repair_v1",
            records=[
                SignalRecord(ts_code="000001.SZ", name="平安银行", industry="银行", rank=1, score=70),
                SignalRecord(ts_code="000002.SZ", name="万科A", industry="地产", rank=2, score=68),
            ],
        )

        second_run = self.store.record_run("20250606", "longterm", "repair_v1", source="live")
        self.store.update_pool(
            run_id=second_run,
            trade_date="20250606",
            mode="longterm",
            profile="repair_v1",
            records=[
                SignalRecord(ts_code="000001.SZ", name="平安银行", industry="银行", rank=1, score=72),
                SignalRecord(ts_code="000003.SZ", name="国华网安", industry="软件服务", rank=2, score=69),
            ],
        )

        events = self.fetch_events()
        state = self.fetch_state()
        self.assertEqual([e["event_type"] for e in events], ["NEW", "NEW", "NEW", "REMOVED"])
        by_code = {row["ts_code"]: row for row in state}
        self.assertEqual(by_code["000001.SZ"]["state"], "active")
        self.assertEqual(by_code["000001.SZ"]["days_in_pool"], 2)
        self.assertEqual(by_code["000002.SZ"]["state"], "removed")
        self.assertEqual(by_code["000002.SZ"]["removed_date"], "20250606")
        self.assertEqual(by_code["000003.SZ"]["state"], "active")

    def test_repeating_same_snapshot_is_idempotent_for_events(self):
        run_id = self.store.record_run("20250605", "short", "short_v9", source="live")
        records = [SignalRecord(ts_code="000001.SZ", name="平安银行", industry="银行", rank=1, score=88)]

        self.store.update_pool(run_id, "20250605", "short", "short_v9", records)
        self.store.update_pool(run_id, "20250605", "short", "short_v9", records)

        events = self.fetch_events()
        state = self.fetch_state()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "NEW")
        self.assertEqual(len(state), 1)

    def test_daily_run_key_is_reused_and_signal_row_is_updated(self):
        first_run = self.store.record_run("20250605", "short", "short_v9", source="live", label="daily")
        second_run = self.store.record_run("20250605", "short", "short_v9", source="live", label="daily")

        self.assertEqual(first_run, second_run)

        self.store.update_pool(
            first_run,
            "20250605",
            "short",
            "short_v9",
            [SignalRecord(ts_code="000001.SZ", name="旧名", rank=1, score=70)],
        )
        self.store.update_pool(
            second_run,
            "20250605",
            "short",
            "short_v9",
            [SignalRecord(ts_code="000001.SZ", name="新名", rank=1, score=88)],
        )

        conn = sqlite3.connect(self.db_path)
        try:
            run_count = conn.execute("select count(*) from signal_runs").fetchone()[0]
            row = conn.execute("select name, score from signal_pool where run_id = ?", (first_run,)).fetchone()
        finally:
            conn.close()

        self.assertEqual(run_count, 1)
        self.assertEqual(row[0], "新名")
        self.assertEqual(row[1], 88)

    def test_recent_event_codes_returns_codes_inside_cooldown_window(self):
        first_run = self.store.record_run("20250605", "longterm", "longterm_elite", source="live")
        self.store.update_pool(
            first_run,
            "20250605",
            "longterm",
            "longterm_elite",
            [SignalRecord(ts_code="000001.SZ", name="A", score=90, pool_type="longterm_elite")],
        )
        old_run = self.store.record_run("20250101", "longterm", "longterm_elite", source="live")
        self.store.update_pool(
            old_run,
            "20250101",
            "longterm",
            "longterm_elite",
            [SignalRecord(ts_code="000002.SZ", name="B", score=91, pool_type="longterm_elite")],
        )

        recent = self.store.recent_event_codes(
            mode="longterm",
            profile="longterm_elite",
            event_type="NEW",
            asof_date="20250620",
            cooldown_days=80,
        )

        self.assertEqual(recent, {"000001.SZ"})

    def test_longterm_tier_changes_are_recorded_as_upgrade_and_downgrade_events(self):
        watch_run = self.store.record_run("20250605", "longterm", "longterm_watch", source="live")
        self.store.update_pool(
            watch_run,
            "20250605",
            "longterm",
            "longterm_watch",
            [SignalRecord(ts_code="000001.SZ", name="A", score=82, pool_type="longterm_watch")],
        )

        elite_run = self.store.record_run("20250606", "longterm", "longterm_elite", source="live")
        self.store.update_pool(
            elite_run,
            "20250606",
            "longterm",
            "longterm_elite",
            [SignalRecord(ts_code="000001.SZ", name="A", score=91, pool_type="longterm_elite")],
        )

        watch_again_run = self.store.record_run("20250607", "longterm", "longterm_watch", source="live")
        self.store.update_pool(
            watch_again_run,
            "20250607",
            "longterm",
            "longterm_watch",
            [SignalRecord(ts_code="000001.SZ", name="A", score=84, pool_type="longterm_watch")],
        )

        events = self.fetch_events()
        event_types = [item["event_type"] for item in events]

        self.assertIn("UPGRADED", event_types)
        self.assertIn("DOWNGRADED", event_types)


if __name__ == "__main__":
    unittest.main()
