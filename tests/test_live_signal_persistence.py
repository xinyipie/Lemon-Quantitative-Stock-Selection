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
            short_observe = pd.DataFrame(
                [
                    {
                        "code": "000004",
                        "name": "observe",
                        "industry": "AI",
                        "score": 62,
                        "observe_score": 188.5,
                        "observe_profile": "best_balance",
                        "recommendation_layer": "OBSERVE_CANDIDATE",
                    }
                ]
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
                short_observe_pool=short_observe,
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
                ("short", "short_live_observe_best_balance", "000004.SZ", "short_observe"),
            ],
        )

    def test_short_signal_payload_keeps_score_breakdown_and_rule_reasons(self):
        row = pd.Series(
            {
                "code": "000001",
                "score": 56.0,
                "original_score": 66.0,
                "factor_profile": "profile_v9_sector_quality_guard",
                "factor_inflow": 82.0,
                "factor_sector": 61.0,
                "factor_pattern": 38.0,
                "volume_ratio": 3.2,
                "drawdown_from_high": 9.5,
                "main_net_inflow": 1200.0,
                "consensus_profile": "v39",
                "recommendation_layer": "T1_BUY_CANDIDATE",
                "entry_timing": "T1",
            }
        )

        payload = main._signal_factor_payload(row)

        self.assertEqual(payload["original_score"], 66.0)
        self.assertEqual(payload["factor_inflow"], 82.0)
        self.assertIn("资金分较强", payload["rule_reasons"])
        self.assertIn("板块热度较好", payload["rule_reasons"])
        self.assertIn("量比3.20偏热", payload["risk_reasons"])
        self.assertIn("回撤9.5%进入风险区", payload["risk_reasons"])
        self.assertIn("轻仓观察", payload["action_hint"])
        self.assertEqual(payload["consensus_profile"], "v39")
        self.assertEqual(payload["recommendation_layer"], "T1_BUY_CANDIDATE")
        self.assertEqual(payload["entry_timing"], "T1")

    def test_short_signal_payload_marks_factor_breakdown_completeness(self):
        complete = pd.Series(
            {
                "code": "000001",
                "score": 56.0,
                "factor_profile": "profile_v9_sector_quality_guard",
                "factor_inflow": 82.0,
                "factor_sector": 61.0,
                "factor_pattern": 38.0,
                "factor_volume_ratio": 64.0,
                "factor_drawdown": 52.0,
                "factor_wyckoff": 44.0,
            }
        )
        incomplete = pd.Series(
            {
                "code": "000002",
                "score": 72.0,
                "factor_profile": "profile_v9_sector_quality_guard",
                "style_gate": "swing",
            }
        )

        complete_payload = main._signal_factor_payload(complete)
        incomplete_payload = main._signal_factor_payload(incomplete)

        self.assertEqual(complete_payload["factor_payload_status"], "complete")
        self.assertNotIn("factor_missing_columns", complete_payload)
        self.assertEqual(incomplete_payload["factor_payload_status"], "incomplete")
        self.assertIn("factor_inflow", incomplete_payload["factor_missing_columns"])
        self.assertIn("factor_wyckoff", incomplete_payload["factor_missing_columns"])

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
