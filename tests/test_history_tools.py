import sqlite3
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from history_db_check import check_history_db, format_check_report
from history_store import HistoryStore
from signal_store import SignalRecord, SignalStore
from stock_history_query import query_stock_history, format_stock_report


class HistoryToolsTest(unittest.TestCase):
    def test_check_history_db_summarizes_tables_and_date_ranges(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "history.db"
            store = HistoryStore(db_path)
            try:
                store.upsert_dataframe(
                    "stock_daily",
                    pd.DataFrame(
                        [
                            {"trade_date": "20250102", "ts_code": "000001.SZ", "close": 10.0},
                            {"trade_date": "20250103", "ts_code": "000001.SZ", "close": 11.0},
                        ]
                    ),
                )
                store.upsert_dataframe(
                    "stock_basic",
                    pd.DataFrame([{"ts_code": "000001.SZ", "symbol": "000001", "name": "平安银行"}]),
                )
            finally:
                store.close()

            result = check_history_db(db_path)
            report = format_check_report(result)

        self.assertEqual(result["tables"]["stock_daily"]["rows"], 2)
        self.assertEqual(result["tables"]["stock_daily"]["min_date"], "20250102")
        self.assertEqual(result["tables"]["stock_daily"]["max_date"], "20250103")
        self.assertEqual(result["tables"]["stock_basic"]["rows"], 1)
        self.assertIn("stock_daily", report)
        self.assertIn("20250102 → 20250103", report)

    def test_check_history_db_warns_when_latest_daily_coverage_is_partial(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "history.db"
            store = HistoryStore(db_path)
            try:
                store.upsert_dataframe(
                    "stock_daily",
                    pd.DataFrame(
                        [
                            {"trade_date": "20250102", "ts_code": "000001.SZ", "close": 10.0},
                            {"trade_date": "20250102", "ts_code": "000002.SZ", "close": 10.0},
                            {"trade_date": "20250102", "ts_code": "000003.SZ", "close": 10.0},
                            {"trade_date": "20250103", "ts_code": "000001.SZ", "close": 11.0},
                            {"trade_date": "20250103", "ts_code": "000002.SZ", "close": 11.0},
                            {"trade_date": "20250103", "ts_code": "000003.SZ", "close": 11.0},
                            {"trade_date": "20250104", "ts_code": "000001.SZ", "close": 12.0},
                        ]
                    ),
                )
            finally:
                store.close()

            result = check_history_db(db_path)

        self.assertEqual(result["tables"]["stock_daily"]["status_label"], "覆盖不足")
        self.assertEqual(result["tables"]["stock_daily"]["status_tone"], "warn")
        self.assertLess(result["daily_coverage"]["coverage_ratio"], 0.7)

    def test_query_stock_history_returns_returns_latest_facts_and_signal_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            history_db = Path(tmpdir) / "history.db"
            store = HistoryStore(history_db)
            try:
                store.upsert_dataframe(
                    "stock_basic",
                    pd.DataFrame(
                        [{"ts_code": "000001.SZ", "symbol": "000001", "name": "平安银行", "industry": "银行"}]
                    ),
                )
                store.upsert_dataframe(
                    "stock_daily",
                    _make_daily_rows(),
                )
                store.upsert_dataframe(
                    "stock_daily_basic",
                    pd.DataFrame(
                        [
                            {
                                "trade_date": "20250322",
                                "ts_code": "000001.SZ",
                                "turnover_rate": 1.2,
                                "volume_ratio": 1.5,
                                "pe_ttm": 8.0,
                                "pb": 0.7,
                                "total_mv": 1000000,
                            }
                        ]
                    ),
                )
                store.upsert_dataframe(
                    "stock_moneyflow",
                    pd.DataFrame(
                        [{"trade_date": "20250322", "ts_code": "000001.SZ", "net_mf_amount": 2500.0}]
                    ),
                )
            finally:
                store.close()

            signal_db = Path(tmpdir) / "signals.db"
            signal_store = SignalStore(signal_db)
            try:
                run_id = signal_store.record_run(
                    trade_date="20250331", mode="short", profile="profile_v9", source="test"
                )
                signal_store.update_pool(
                    run_id,
                    trade_date="20250331",
                    mode="short",
                    profile="profile_v9",
                    records=[SignalRecord(ts_code="000001.SZ", name="平安银行", score=66.0)],
                )
            finally:
                signal_store.close()

            result = query_stock_history("000001", history_db=history_db, signal_db=signal_db)
            name_result = query_stock_history("平安银行", history_db=history_db, signal_db=signal_db)
            report = format_stock_report(result)

        self.assertEqual(result["stock"]["ts_code"], "000001.SZ")
        self.assertEqual(result["stock"]["name"], "平安银行")
        self.assertEqual(name_result["stock"]["ts_code"], "000001.SZ")
        self.assertEqual(name_result["stock"]["name"], "平安银行")
        self.assertAlmostEqual(result["returns"]["10d"], 36.36, places=2)
        self.assertAlmostEqual(result["returns"]["40d"], 25.0, places=2)
        self.assertAlmostEqual(result["returns"]["80d"], 50.0, places=2)
        self.assertEqual(result["latest_basic"]["pe_ttm"], 8.0)
        self.assertEqual(result["latest_moneyflow"]["net_mf_amount"], 2500.0)
        self.assertEqual(result["signal_state"]["state"], "active")
        self.assertEqual(len(result["price_history"]), 81)
        self.assertEqual(result["price_history"][0]["trade_date"], "20250101")
        self.assertEqual(result["price_history"][-1]["trade_date"], "20250322")
        self.assertIsNone(result["price_history"][18]["ma20"])
        self.assertAlmostEqual(result["price_history"][19]["ma20"], 12.85, places=2)
        self.assertIsNotNone(result["price_history"][-1]["ma60"])
        self.assertIn("平安银行", report)
        self.assertIn("近10日", report)


if __name__ == "__main__":
    unittest.main()


def _make_daily_rows():
    dates = pd.date_range("2025-01-01", periods=81, freq="D").strftime("%Y%m%d").tolist()
    rows = []
    for idx, trade_date in enumerate(dates):
        close = 13.0
        if idx == 0:
            close = 10.0
        if idx == 40:
            close = 12.0
        if idx == 70:
            close = 11.0
        if idx == 80:
            close = 15.0
        rows.append({"trade_date": trade_date, "ts_code": "000001.SZ", "close": close})
    return pd.DataFrame(rows)
