import sqlite3
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from history_db_importer import import_history_cache


class HistoryDbImporterTest(unittest.TestCase):
    def test_import_history_cache_loads_requested_date_range(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cache_dir = root / "cache"
            (cache_dir / "daily").mkdir(parents=True)
            (cache_dir / "daily_basic").mkdir(parents=True)

            pd.DataFrame(
                [{"trade_date": "20250102", "ts_code": "000001.SZ", "close": 10.0}]
            ).to_parquet(cache_dir / "daily" / "20250102.parquet", index=False)
            pd.DataFrame(
                [{"trade_date": "20250103", "ts_code": "000001.SZ", "close": 11.0}]
            ).to_parquet(cache_dir / "daily" / "20250103.parquet", index=False)
            pd.DataFrame(
                [{"trade_date": "20250103", "ts_code": "000001.SZ", "turnover_rate": 2.5}]
            ).to_parquet(cache_dir / "daily_basic" / "20250103.parquet", index=False)
            pd.DataFrame(
                [{"ts_code": "000001.SZ", "symbol": "000001", "name": "平安银行"}]
            ).to_parquet(cache_dir / "stock_basic.parquet", index=False)

            db_path = root / "history.db"
            summary = import_history_cache(
                cache_dir=cache_dir,
                db_path=db_path,
                start="20250103",
                end="20250103",
                tables=["daily", "daily_basic", "stock_basic"],
            )

            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            try:
                daily_rows = conn.execute("select * from stock_daily").fetchall()
                basic_rows = conn.execute("select * from stock_daily_basic").fetchall()
                stock_rows = conn.execute("select * from stock_basic").fetchall()
            finally:
                conn.close()

        self.assertEqual(summary["stock_daily"], 1)
        self.assertEqual(summary["stock_daily_basic"], 1)
        self.assertEqual(summary["stock_basic"], 1)
        self.assertEqual(len(daily_rows), 1)
        self.assertEqual(daily_rows[0]["trade_date"], "20250103")
        self.assertEqual(daily_rows[0]["close"], 11.0)
        self.assertEqual(basic_rows[0]["turnover_rate"], 2.5)
        self.assertEqual(stock_rows[0]["name"], "平安银行")


if __name__ == "__main__":
    unittest.main()
