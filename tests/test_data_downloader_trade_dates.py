import tempfile
import unittest
from pathlib import Path

import pandas as pd

import data_downloader


class EmptyTradeCalPro:
    def trade_cal(self, **kwargs):
        return pd.DataFrame()


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


if __name__ == "__main__":
    unittest.main()
