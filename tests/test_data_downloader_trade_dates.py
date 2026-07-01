import tempfile
import unittest
from pathlib import Path

import pandas as pd

import data_downloader


class EmptyTradeCalPro:
    def trade_cal(self, **kwargs):
        return pd.DataFrame()


class DailyPro:
    def __init__(self):
        self.calls = 0

    def daily(self, **kwargs):
        self.calls += 1
        return pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": kwargs["trade_date"],
                    "open": 10.0,
                    "high": 10.5,
                    "low": 9.8,
                    "close": 10.2,
                    "pct_chg": 1.0,
                    "vol": 1000,
                    "amount": 10000,
                }
            ]
        )


class EmptyDailyPro:
    def daily(self, **kwargs):
        return pd.DataFrame(columns=["ts_code", "trade_date"])

    def daily_basic(self, **kwargs):
        return pd.DataFrame(columns=["ts_code", "turnover_rate", "volume_ratio"])

    def moneyflow(self, **kwargs):
        return pd.DataFrame(columns=["ts_code", "net_mf_amount"])


class IndexPro:
    def __init__(self):
        self.calls = []

    def index_daily(self, **kwargs):
        self.calls.append(kwargs["ts_code"])
        return pd.DataFrame(
            [
                {
                    "ts_code": kwargs["ts_code"],
                    "trade_date": kwargs["trade_date"],
                    "open": 10.0,
                    "high": 10.5,
                    "low": 9.8,
                    "close": 10.2,
                    "pct_chg": 1.0,
                }
            ]
        )


class HolderTradePro:
    def __init__(self):
        self.calls = []

    def stk_holdertrade(self, **kwargs):
        self.calls.append(kwargs)
        if "start_date" in kwargs or "end_date" in kwargs:
            raise AssertionError("stk_holdertrade should not filter by trade_date-like parameters")
        return pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "ann_date": "20260610", "in_de": "DE", "holder_type": kwargs["holder_type"]},
                {"ts_code": "000002.SZ", "ann_date": "20260501", "in_de": "DE", "holder_type": kwargs["holder_type"]},
            ]
        )


class CoreOnlyDailyPro:
    def __init__(self):
        self.calls = []

    def daily(self, **kwargs):
        self.calls.append("daily")
        return pd.DataFrame([{"ts_code": "000001.SZ", "trade_date": kwargs["trade_date"], "close": 10.0}])

    def daily_basic(self, **kwargs):
        self.calls.append("daily_basic")
        return pd.DataFrame([{"ts_code": "000001.SZ", "turnover_rate": 1.0, "volume_ratio": 1.2}])

    def moneyflow(self, **kwargs):
        self.calls.append("moneyflow")
        return pd.DataFrame([{"ts_code": "000001.SZ", "net_mf_amount": 100.0}])

    def index_daily(self, **kwargs):
        raise AssertionError("core_only should skip index_daily")

    def top_list(self, **kwargs):
        raise AssertionError("core_only should skip top_list")

    def top_inst(self, **kwargs):
        raise AssertionError("core_only should skip top_inst")

    def margin_detail(self, **kwargs):
        raise AssertionError("core_only should skip margin_detail")


class DataDownloaderTradeDatesTest(unittest.TestCase):
    def test_get_trade_dates_falls_back_to_cached_trade_calendar_when_api_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_cache_dir = data_downloader.CACHE_DIR
            data_downloader.CACHE_DIR = tmp
            try:
                cache = pd.DataFrame(
                    {
                        "cal_date": ["20260619", "20260620", "20260622"],
                        "is_open": [1, 0, 1],
                    }
                )
                cache.to_parquet(Path(tmp) / "trade_cal.parquet", index=False)

                dates = data_downloader._get_trade_dates(
                    EmptyTradeCalPro(),
                    "20260619",
                    "20260622",
                )

                self.assertEqual(dates, ["20260619", "20260622"])
            finally:
                data_downloader.CACHE_DIR = old_cache_dir

    def test_get_trade_dates_extends_stale_cached_calendar_with_weekdays(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_cache_dir = data_downloader.CACHE_DIR
            data_downloader.CACHE_DIR = tmp
            try:
                cache = pd.DataFrame(
                    {
                        "cal_date": ["20260624", "20260625"],
                        "is_open": [1, 1],
                    }
                )
                cache.to_parquet(Path(tmp) / "trade_cal.parquet", index=False)

                dates = data_downloader._get_trade_dates(
                    EmptyTradeCalPro(),
                    "20260624",
                    "20260630",
                )

                self.assertEqual(dates, ["20260624", "20260625", "20260626", "20260629", "20260630"])
            finally:
                data_downloader.CACHE_DIR = old_cache_dir

    def test_save_preserves_empty_dataframe_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.parquet"
            data_downloader._save(pd.DataFrame(columns=["cal_date", "is_open"]), str(path))

            saved = pd.read_parquet(path)

            self.assertEqual(list(saved.columns), ["cal_date", "is_open"])
            self.assertTrue(saved.empty)

    def test_download_trade_cal_does_not_overwrite_valid_cache_with_invalid_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_cache_dir = data_downloader.CACHE_DIR
            data_downloader.CACHE_DIR = tmp
            try:
                path = Path(tmp) / "trade_cal.parquet"
                pd.DataFrame(
                    {
                        "cal_date": ["20260619", "20260622"],
                        "is_open": [1, 1],
                    }
                ).to_parquet(path, index=False)

                data_downloader.download_trade_cal(
                    EmptyTradeCalPro(),
                    "20260619",
                    "20260622",
                    force=True,
                )

                saved = pd.read_parquet(path)
                self.assertEqual(list(saved.columns), ["cal_date", "is_open"])
                self.assertEqual(saved["cal_date"].astype(str).tolist(), ["20260619", "20260622"])
            finally:
                data_downloader.CACHE_DIR = old_cache_dir

    def test_get_trade_dates_uses_weekday_fallback_when_api_and_cache_are_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_cache_dir = data_downloader.CACHE_DIR
            data_downloader.CACHE_DIR = tmp
            try:
                pd.DataFrame().to_parquet(Path(tmp) / "trade_cal.parquet", index=False)

                dates = data_downloader._get_trade_dates(
                    EmptyTradeCalPro(),
                    "20260619",
                    "20260622",
                )

                self.assertEqual(dates, ["20260619", "20260622"])
            finally:
                data_downloader.CACHE_DIR = old_cache_dir

    def test_download_daily_redownloads_empty_cache_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_cache_dir = data_downloader.CACHE_DIR
            data_downloader.CACHE_DIR = tmp
            try:
                data_downloader._ensure_dirs()
                path = Path(tmp) / "daily" / "20260618.parquet"
                pd.DataFrame().to_parquet(path, index=False)
                pro = DailyPro()

                ok = data_downloader.download_daily_one_date(pro, "20260618")

                saved = pd.read_parquet(path)
                self.assertTrue(ok)
                self.assertEqual(pro.calls, 1)
                self.assertEqual(len(saved), 1)
                self.assertEqual(saved["trade_date"].astype(str).tolist(), ["20260618"])
            finally:
                data_downloader.CACHE_DIR = old_cache_dir

    def test_core_daily_downloads_do_not_count_empty_api_responses_as_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_cache_dir = data_downloader.CACHE_DIR
            data_downloader.CACHE_DIR = tmp
            try:
                data_downloader._ensure_dirs()
                pro = EmptyDailyPro()

                daily_ok = data_downloader.download_daily_one_date(pro, "20260630")
                basic_ok = data_downloader.download_daily_basic_one_date(pro, "20260630")
                moneyflow_ok = data_downloader.download_moneyflow_one_date(pro, "20260630")

                self.assertFalse(daily_ok)
                self.assertFalse(basic_ok)
                self.assertFalse(moneyflow_ok)
                self.assertTrue((Path(tmp) / "daily" / "20260630.parquet").exists())
                self.assertEqual(len(pd.read_parquet(Path(tmp) / "daily" / "20260630.parquet")), 0)
            finally:
                data_downloader.CACHE_DIR = old_cache_dir

    def test_download_index_redownloads_incomplete_cache_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_cache_dir = data_downloader.CACHE_DIR
            old_index_codes = data_downloader.INDEX_CODES
            old_sleep = data_downloader.time.sleep
            data_downloader.CACHE_DIR = tmp
            data_downloader.INDEX_CODES = ["000001.SH", "000300.SH", "801010.SI"]
            data_downloader.time.sleep = lambda _seconds: None
            try:
                data_downloader._ensure_dirs()
                path = Path(tmp) / "index_daily" / "20260622.parquet"
                pd.DataFrame(
                    [
                        {"ts_code": "000001.SH", "trade_date": "20260622", "close": 4163.0},
                        {"ts_code": "000300.SH", "trade_date": "20260622", "close": 5059.0},
                    ]
                ).to_parquet(path, index=False)
                pro = IndexPro()

                ok = data_downloader.download_index_daily_one_date(pro, "20260622")

                saved = pd.read_parquet(path)
                self.assertTrue(ok)
                self.assertEqual(pro.calls, data_downloader.INDEX_CODES)
                self.assertEqual(len(saved), 3)
                self.assertEqual(set(saved["ts_code"].astype(str)), set(data_downloader.INDEX_CODES))
            finally:
                data_downloader.CACHE_DIR = old_cache_dir
                data_downloader.INDEX_CODES = old_index_codes
                data_downloader.time.sleep = old_sleep

    def test_download_stk_holdertrade_filters_ann_date_locally(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_cache_dir = data_downloader.CACHE_DIR
            old_sleep = data_downloader.time.sleep
            data_downloader.CACHE_DIR = tmp
            data_downloader.time.sleep = lambda _seconds: None
            try:
                data_downloader._ensure_dirs()
                pro = HolderTradePro()

                data_downloader.download_stk_holdertrade(pro, "20260601", "20260625", force=True)

                saved = pd.read_parquet(Path(tmp) / "stk_holdertrade.parquet")
                self.assertEqual(len(pro.calls), 3)
                self.assertTrue(all("start_date" not in call and "end_date" not in call for call in pro.calls))
                self.assertEqual(set(saved["ann_date"].astype(str)), {"20260610"})
                self.assertEqual(set(saved["holder_type"].astype(str)), {"G", "P", "C"})
            finally:
                data_downloader.CACHE_DIR = old_cache_dir
                data_downloader.time.sleep = old_sleep

    def test_download_daily_range_core_only_skips_rate_limited_interfaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_cache_dir = data_downloader.CACHE_DIR
            old_sleep = data_downloader.time.sleep
            data_downloader.CACHE_DIR = tmp
            data_downloader.time.sleep = lambda _seconds: None
            try:
                data_downloader._ensure_dirs()
                pro = CoreOnlyDailyPro()

                result = data_downloader.download_daily_range(pro, ["20260624"], core_only=True)

                self.assertEqual(result[:3], (1, 1, 1))
                self.assertEqual(pro.calls, ["daily", "daily_basic", "moneyflow"])
                self.assertFalse((Path(tmp) / "index_daily" / "20260624.parquet").exists())
                self.assertFalse((Path(tmp) / "top_list" / "20260624.parquet").exists())
            finally:
                data_downloader.CACHE_DIR = old_cache_dir
                data_downloader.time.sleep = old_sleep


if __name__ == "__main__":
    unittest.main()
