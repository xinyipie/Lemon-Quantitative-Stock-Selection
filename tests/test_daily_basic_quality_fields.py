import pandas as pd
from types import SimpleNamespace
import data_downloader as downloader


def test_old_turnover_only_cache_is_refreshed_with_quality_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(downloader, 'CACHE_DIR', str(tmp_path))
    path = tmp_path / 'daily_basic' / '20260911.parquet'
    path.parent.mkdir()
    pd.DataFrame({'ts_code': ['000001.SZ'], 'turnover_rate': [1], 'volume_ratio': [1]}).to_parquet(path)
    calls = []
    def fetch(**query):
        calls.append(query)
        requested = set(query['fields'].split(','))
        assert {'pb', 'pe_ttm', 'ps_ttm', 'total_mv', 'circ_mv', 'dv_ratio'}.issubset(requested)
        return pd.DataFrame([{field: ('000001.SZ' if field == 'ts_code' else 1) for field in requested}])
    assert downloader.download_daily_basic_one_date(SimpleNamespace(daily_basic=fetch), '20260911')
    assert len(calls) == 1
    assert {'pb', 'total_mv', 'ps_ttm'}.issubset(pd.read_parquet(path).columns)
