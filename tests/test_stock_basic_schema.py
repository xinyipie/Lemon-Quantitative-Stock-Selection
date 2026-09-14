import os
from types import SimpleNamespace

import pandas as pd
import pytest

os.environ.setdefault('LEMON_SKIP_TUSHARE_INIT', '1')
import data_downloader as downloader


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(downloader, 'CACHE_DIR', str(tmp_path))
    monkeypatch.setattr(downloader, '_china_date', lambda: '20260914')
    monkeypatch.setattr(downloader.time, 'sleep', lambda _: None)
    return tmp_path


def run_download(frames):
    def fetch(**kwargs):
        result = frames.get(kwargs['list_status'], pd.DataFrame())
        if result is None:
            raise RuntimeError('状态暂不可用')
        return result
    downloader.download_stock_basic(SimpleNamespace(stock_basic=fetch), force=True)


def test_mixed_symbols_round_trip_to_real_parquet(cache):
    run_download({'L': pd.DataFrame([
        {'ts_code': '000001.SZ', 'symbol': '000001', 'list_date': '19910403', 'name': '样本'},
        {'ts_code': '000002.SZ', 'symbol': 2.0, 'list_date': 19910129.0, 'name': 2.0},
        {'ts_code': '000003.SZ', 'symbol': None, 'list_date': None, 'name': None},
    ]), 'D': pd.DataFrame([
        {'ts_code': '000004.SZ', 'symbol': '4.0', 'list_date': pd.Timestamp('1991-01-14'),
         'delist_date': 20250101.0},
    ])})
    for path in (cache / 'stock_basic.parquet', cache / 'stock_basic_history/20260914.parquet'):
        saved = pd.read_parquet(path).set_index('ts_code')
        assert saved.loc['000001.SZ', 'symbol'] == '000001'
        assert saved.loc['000002.SZ', 'symbol'] == '000002'
        assert pd.isna(saved.loc['000003.SZ', 'symbol'])
        assert saved.loc['000004.SZ', 'symbol'] == '000004'
        assert saved.loc['000002.SZ', 'list_date'] == '19910129'
        assert saved.loc['000004.SZ', 'list_date'] == '19910114'
        assert saved.loc['000004.SZ', 'delist_date'] == '20250101'
        assert pd.isna(saved.loc['000003.SZ', 'list_date'])


def test_partial_status_normalizes_old_cache_without_new_history(cache):
    pd.DataFrame([{'ts_code': '000004.SZ', 'symbol': 4.0, 'list_status': 'D',
                   'list_date': 19910114.0, 'basic_snapshot_date': 20260901.0,
                   'numeric_metric': 1.5}]).to_parquet(cache / 'stock_basic.parquet')
    run_download({'L': pd.DataFrame([{'ts_code': '000001.SZ', 'symbol': '000001'}]), 'D': None})
    saved = pd.read_parquet(cache / 'stock_basic.parquet').set_index('ts_code')
    assert saved.loc['000004.SZ', 'symbol'] == '000004'
    assert saved.loc['000004.SZ', 'basic_snapshot_date'] == '20260901'
    assert saved.loc['000004.SZ', 'numeric_metric'] == 1.5
    assert not (cache / 'stock_basic_history/20260914.parquet').exists()


@pytest.mark.parametrize('bad', [None, '', 'nan', '123.SZ', '000001.BAD'])
def test_invalid_codes_preserve_cache_and_history(cache, bad):
    path = cache / 'stock_basic.parquet'
    pd.DataFrame([{'ts_code': '000001.SZ', 'symbol': '000001'}]).to_parquet(path)
    before = path.read_bytes()
    with pytest.raises(ValueError, match='ts_code'):
        run_download({'L': pd.DataFrame([{'ts_code': bad, 'symbol': '000002'}])})
    assert path.read_bytes() == before
    assert not (cache / 'stock_basic_history/20260914.parquet').exists()


@pytest.mark.parametrize('rows', [
    [{'symbol': '000002'}],
    [{'ts_code': '000002.SZ'}, {'ts_code': None}],
])
def test_incomplete_primary_keys_do_not_replace_existing_snapshot(cache, rows):
    path = cache / 'stock_basic.parquet'
    history = cache / 'stock_basic_history/20260914.parquet'
    history.parent.mkdir()
    old = pd.DataFrame([{'ts_code': '000001.SZ', 'symbol': '000001'}])
    old.to_parquet(path)
    old.to_parquet(history)
    before = (path.read_bytes(), history.read_bytes())
    with pytest.raises(ValueError, match='ts_code'):
        run_download({'L': pd.DataFrame(rows)})
    assert (path.read_bytes(), history.read_bytes()) == before


def test_invalid_dates_and_symbols_remain_missing(cache):
    run_download({'L': pd.DataFrame([
        {'ts_code': '000001.SZ', 'symbol': 1.5, 'list_date': '20260230'},
        {'ts_code': '000002.SZ', 'symbol': '', 'list_date': 'nan'},
        {'ts_code': '000003.SZ', 'symbol': float('nan'), 'list_date': ''},
    ])})
    saved = pd.read_parquet(cache / 'stock_basic.parquet')
    assert saved['symbol'].isna().all()
    assert saved['list_date'].isna().all()


@pytest.mark.parametrize('existing', [False, True])
@pytest.mark.parametrize('frames', [{}, {'L': None, 'D': None, 'P': None}])
def test_unavailable_master_data_raises_without_overwriting_cache(cache, existing, frames):
    path = cache / 'stock_basic.parquet'
    if existing:
        pd.DataFrame([{'ts_code': '000001.SZ'}]).to_parquet(path)
    before = path.read_bytes() if existing else None
    with pytest.raises(RuntimeError, match='stock_basic'):
        run_download(frames)
    assert (path.read_bytes() if path.exists() else None) == before
    assert not (cache / 'stock_basic_history/20260914.parquet').exists()
