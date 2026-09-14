from types import SimpleNamespace
import pandas as pd
import pytest
import data_downloader as downloader


@pytest.mark.parametrize('name', ['fina_indicator', 'income'])
def test_retired_legacy_identity_is_preserved_but_not_sent_as_api_code(tmp_path, monkeypatch, name):
    monkeypatch.setattr(downloader, 'CACHE_DIR', str(tmp_path))
    monkeypatch.setattr(downloader.time, 'sleep', lambda _: None)
    pd.DataFrame([{'ts_code': '600018.SH', 'list_status': 'L'},
                  {'ts_code': 'T600018.SH', 'list_status': 'D'}]).to_parquet(tmp_path / 'stock_basic.parquet')
    pd.DataFrame([{'ts_code': '600018.SH', 'ann_date': '20260830', 'end_date': '20260630'}]).to_parquet(tmp_path / f'{name}.parquet')
    queries = []
    def fetch(**query):
        queries.append(query)
        return pd.DataFrame()
    getattr(downloader, f'download_{name}')(SimpleNamespace(**{name: fetch}))
    assert [q['ts_code'] for q in queries] == ['600018.SH']
    assert 'T600018.SH' in pd.read_parquet(tmp_path / 'stock_basic.parquet').ts_code.tolist()
