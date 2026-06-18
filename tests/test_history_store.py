import sqlite3
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from history_store import HistoryStore


class HistoryStoreTest(unittest.TestCase):
    def test_init_schema_creates_history_tables_and_indexes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "history.db"
            store = HistoryStore(db_path)
            try:
                names = {
                    row["name"]
                    for row in store.conn.execute(
                        "select name from sqlite_master where type in ('table', 'index')"
                    )
                }
            finally:
                store.close()

        self.assertIn("stock_daily", names)
        self.assertIn("stock_daily_basic", names)
        self.assertIn("stock_moneyflow", names)
        self.assertIn("index_daily", names)
        self.assertIn("stock_basic", names)
        self.assertIn("fina_indicator", names)
        self.assertIn("income", names)
        self.assertIn("idx_stock_daily_code_date", names)
        self.assertIn("idx_index_daily_code_date", names)

    def test_upsert_dataframe_replaces_existing_daily_row(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "history.db"
            store = HistoryStore(db_path)
            try:
                store.upsert_dataframe(
                    "stock_daily",
                    pd.DataFrame(
                        [
                            {
                                "trade_date": "20250102",
                                "ts_code": "000001.SZ",
                                "open": 10.0,
                                "high": 11.0,
                                "low": 9.5,
                                "close": 10.5,
                                "pct_chg": 2.0,
                            }
                        ]
                    ),
                )
                store.upsert_dataframe(
                    "stock_daily",
                    pd.DataFrame(
                        [
                            {
                                "trade_date": "20250102",
                                "ts_code": "000001.SZ",
                                "open": 10.0,
                                "high": 11.0,
                                "low": 9.5,
                                "close": 12.0,
                                "pct_chg": 5.0,
                            }
                        ]
                    ),
                )

                rows = store.conn.execute(
                    "select trade_date, ts_code, close, pct_chg from stock_daily"
                ).fetchall()
            finally:
                store.close()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["close"], 12.0)
        self.assertEqual(rows[0]["pct_chg"], 5.0)

    def test_unknown_table_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = HistoryStore(Path(tmpdir) / "history.db")
            try:
                with self.assertRaises(ValueError):
                    store.upsert_dataframe("unknown", pd.DataFrame([{"a": 1}]))
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
