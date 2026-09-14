from datetime import datetime
from types import SimpleNamespace

import pandas as pd
import pytest

import data_downloader as downloader


@pytest.mark.parametrize('table,download', [
    ('fina_indicator', downloader.download_fina_indicator),
    ('income', downloader.download_income),
])
def test_old_financial_watermark_is_batched_without_exceeding_provider_limit(tmp_path, monkeypatch, table, download):
    monkeypatch.setattr(downloader, 'CACHE_DIR', str(tmp_path))
    monkeypatch.setattr(downloader, '_china_date', lambda: '20260914')
    monkeypatch.setattr(downloader.time, 'sleep', lambda _: None)
    pd.DataFrame({'ts_code': ['000001.SZ', '000002.SZ']}).to_parquet(tmp_path / 'stock_basic.parquet')
    pd.DataFrame([
        dict(ts_code='000001.SZ', ann_date='19970101', end_date='19961231', roe=8),
        dict(ts_code='000002.SZ', ann_date='20260830', end_date='20260630', roe=9),
    ]).to_parquet(tmp_path / f'{table}.parquet')
    calls = []
    def fetch(**query):
        start = datetime.strptime(query['start_date'], '%Y%m%d')
        end = datetime.strptime(query.get('end_date', '20260914'), '%Y%m%d')
        assert (end - start).days < 3000
        calls.append(query)
        return pd.DataFrame([dict(ts_code='000002.SZ', ann_date='20260910', end_date='20260630', roe=10)])
    download(SimpleNamespace(**{table: fetch}))
    old = [q for q in calls if '000001.SZ' in q['ts_code'].split(',')]
    recent = [q for q in calls if '000002.SZ' in q['ts_code'].split(',')]
    assert old[0]['start_date'] == '19970101'
    assert old[-1]['end_date'] == '20260914'
    assert len(recent) == 1
    assert recent[0]['start_date'] == '20260830'
    for a, b in zip(old, old[1:]):
        assert (datetime.strptime(b['start_date'], '%Y%m%d') - datetime.strptime(a['end_date'], '%Y%m%d')).days == 1
    assert '19970101' in pd.read_parquet(tmp_path / f'{table}.parquet')['ann_date'].tolist()


def test_failed_financial_batch_preserves_cache_and_marks_update_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(downloader, 'CACHE_DIR', str(tmp_path))
    monkeypatch.setattr(downloader.time, 'sleep', lambda _: None)
    pd.DataFrame({'ts_code': ['000001.SZ']}).to_parquet(tmp_path / 'stock_basic.parquet')
    target = tmp_path / 'fina_indicator.parquet'
    pd.DataFrame([dict(ts_code='000001.SZ', ann_date='20260101', end_date='20251231')]).to_parquet(target)
    before = target.read_bytes()
    with pytest.raises(RuntimeError, match='财务'):
        downloader.download_fina_indicator(SimpleNamespace(fina_indicator=lambda **_: None))
    assert target.read_bytes() == before
