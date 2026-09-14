import pandas as pd
import data_downloader as downloader


def test_daily_update_reuses_benchmark_buffer_without_claiming_industry_coverage(tmp_path, monkeypatch):
    monkeypatch.setattr(downloader, 'CACHE_DIR', str(tmp_path))
    monkeypatch.setattr(downloader.time, 'sleep', lambda _: None)
    downloader._ensure_dirs()
    date = '20260911'
    for table in ['daily', 'daily_basic', 'moneyflow', 'fund_daily', 'top_list', 'top_inst', 'margin_detail']:
        pd.DataFrame({'value': [1]}).to_parquet(tmp_path / table / f'{date}.parquet')
    pd.DataFrame({'ts_code': ['000001.SH', '000300.SH'], 'trade_date': [date, date],
                  'close': [3000, 4500]}).to_parquet(tmp_path / 'index_daily' / f'{date}.parquet')
    calls = []
    monkeypatch.setattr(downloader, 'download_index_daily_one_date', lambda *args: calls.append(args) or True)
    downloader.download_daily_range(None, [date], refresh_start='20260912')
    assert not calls
    downloader.download_daily_range(None, [date], refresh_start='20260911')
    assert len(calls) == 1
