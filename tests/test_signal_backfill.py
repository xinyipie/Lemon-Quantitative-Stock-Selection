import sqlite3
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from signal_backfill import backfill_ic_short


class SignalBackfillTest(unittest.TestCase):
    def test_backfill_ic_short_imports_topn_v9_signals_with_performance_factors(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "ic_short.csv"
            db_path = Path(tmpdir) / "signals.db"
            pd.DataFrame(
                [
                    _row("20250102", "000001.SZ", 80, "profile_v9_sector_quality_guard", "银行", 5.0),
                    _row("20250102", "000002.SZ", 70, "profile_v9_sector_quality_guard", "地产", 3.0),
                    _row("20250102", "000003.SZ", 60, "profile_v9_sector_quality_guard", "制造", -1.0),
                    _row("20250102", "000004.SZ", 50, "profile_v9_sector_quality_guard", "医药", -2.0),
                    _row("20250103", "000006.SZ", 90, "profile_v9_sector_quality_guard", "银行", 6.0),
                    _row("20250103", "000007.SZ", 85, "profile_v9_sector_quality_guard", "电子", 4.0),
                    _row("20250102", "000005.SZ", 99, "old_profile", "其他", 20.0),
                ]
            ).to_csv(source, index=False, encoding="utf-8-sig")

            summary = backfill_ic_short(
                source,
                db_path=db_path,
                profile="short_v9",
                top=3,
                dry_run=False,
            )
            second = backfill_ic_short(
                source,
                db_path=db_path,
                profile="short_v9",
                top=3,
                dry_run=False,
            )

            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            try:
                runs = conn.execute("select count(*) n from signal_runs").fetchone()["n"]
                rows = conn.execute(
                    "select trade_date, ts_code, rank, score, factor_json from signal_pool order by trade_date, rank"
                ).fetchall()
            finally:
                conn.close()

        self.assertEqual(summary["import_rows"], 5)
        self.assertEqual(summary["skipped_profile_rows"], 1)
        self.assertEqual(second["import_rows"], 5)
        self.assertEqual(runs, 2)
        self.assertEqual(len(rows), 5)
        first_day = [row for row in rows if row["trade_date"] == "20250102"]
        second_day = [row for row in rows if row["trade_date"] == "20250103"]
        self.assertEqual([row["ts_code"] for row in first_day], ["000001.SZ", "000002.SZ", "000003.SZ"])
        self.assertEqual([row["rank"] for row in first_day], [1, 2, 3])
        self.assertEqual([row["ts_code"] for row in second_day], ["000006.SZ", "000007.SZ"])
        self.assertIn("ret_5d", rows[0]["factor_json"])


def _row(select_date, ts_code, score, factor_profile, industry, ret_5d):
    return {
        "select_date": select_date,
        "buy_date": "20250103",
        "ts_code": ts_code,
        "score": score,
        "original_score": score + 10,
        "factor_profile": factor_profile,
        "style_gate": "adaptive_quality_v6",
        "industry": industry,
        "mfe_pct": 8.0,
        "mae_pct": -2.0,
        "ret_5d": ret_5d,
        "ret_10d": ret_5d + 1,
        "ret_20d": ret_5d + 2,
        "window_end_pct": ret_5d + 3,
        "factor_inflow": 80,
        "factor_sector": 60,
        "factor_pattern": 50,
    }


if __name__ == "__main__":
    unittest.main()
