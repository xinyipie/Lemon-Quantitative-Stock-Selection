import sqlite3
import tempfile
import unittest
import os
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("LEMON_SKIP_TUSHARE_INIT", "1")

import main


class TokenFailPro:
    def trade_cal(self, **kwargs):
        raise Exception("您的token不对，请确认。")

    def daily(self, **kwargs):
        raise AssertionError("token 失效时不应继续验证在线行情")


class LatestTradeDateTest(unittest.TestCase):
    def test_init_tushare_passes_token_directly_without_writing_tk_csv(self):
        class FakeTs:
            def __init__(self):
                self.pro_api_calls = []

            def set_token(self, token):
                raise AssertionError("不应写入本机 tk.csv")

            def pro_api(self, **kwargs):
                self.pro_api_calls.append(kwargs)

                class Pro:
                    pass

                return Pro()

        fake_ts = FakeTs()
        with patch.object(main, "ts", fake_ts), patch.dict(
            main.config.TUSHARE_CONFIG,
            {"token": "valid-token", "timeout": 30, "http_url": "http://relay.local/"},
        ):
            pro = main.init_tushare()

        self.assertIsNotNone(pro)
        self.assertEqual(fake_ts.pro_api_calls, [{"token": "valid-token", "timeout": 30}])

    def test_get_latest_trade_date_falls_back_to_history_db_when_tushare_token_is_invalid(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            history_db = Path(tmpdir) / "stock_history.db"
            conn = sqlite3.connect(history_db)
            try:
                conn.execute("create table stock_daily(trade_date text)")
                conn.execute("insert into stock_daily(trade_date) values ('20260624')")
                conn.execute("insert into stock_daily(trade_date) values ('20260625')")
                conn.commit()
            finally:
                conn.close()

            with patch.object(main, "pro", TokenFailPro()), patch.object(main, "DEFAULT_HISTORY_DB_PATH", history_db):
                trade_date = main.get_latest_trade_date()

        self.assertEqual(trade_date, "20260625")


if __name__ == "__main__":
    unittest.main()
