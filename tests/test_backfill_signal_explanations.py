import tempfile
import unittest
from pathlib import Path

from signal_store import SignalRecord, SignalStore

from backfill_signal_explanations import collect_signal_targets


class BackfillSignalExplanationsTest(unittest.TestCase):
    def test_collect_signal_targets_filters_date_mode_profile_and_source(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            signal_db = Path(tmpdir) / "signals.db"
            store = SignalStore(signal_db)
            try:
                run_id = store.record_run("20260601", mode="short", profile="short_v9_final", source="backtest_ic_short")
                store.update_pool(
                    run_id,
                    "20260601",
                    mode="short",
                    profile="short_v9_final",
                    records=[SignalRecord(ts_code="000001.SZ", score=60)],
                )
                live_run_id = store.record_run("20260602", mode="short", profile="profile_v9_sector_quality_guard", source="live")
                store.update_pool(
                    live_run_id,
                    "20260602",
                    mode="short",
                    profile="profile_v9_sector_quality_guard",
                    records=[SignalRecord(ts_code="000002.SZ", score=70)],
                )
            finally:
                store.close()

            targets = collect_signal_targets(
                signal_db,
                start="20260601",
                end="20260601",
                mode="short",
                profile="short_v9_final",
                source="backtest_ic_short",
            )

        self.assertEqual(targets, [{"trade_date": "20260601", "ts_code": "000001.SZ"}])


if __name__ == "__main__":
    unittest.main()
