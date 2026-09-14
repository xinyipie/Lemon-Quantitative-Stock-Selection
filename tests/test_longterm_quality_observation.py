import pandas as pd
import main as stock_main
from longterm_live_pipeline import build_live_watchlists
from web_app.services.signal_service import split_longterm_pool
from daily_report.selection_snapshot import build_selection_snapshot


def inputs():
    stocks = pd.DataFrame([
        dict(code='600001', name='质量公司', industry='制造', close=20, amount=300000,
             total_mv=5000000, pb=2, pe_ttm=25, ps_ttm=2, turnover=0.3, volume_ratio=1),
        dict(code='000001', name='财务缺失', industry='制造', close=20, amount=300000,
             total_mv=1000000, pb=2, pe_ttm=25, ps_ttm=2, turnover=2, volume_ratio=1),
        dict(code='000002', name='质量不足', industry='消费', close=20, amount=300000,
             total_mv=1000000, pb=2, pe_ttm=25, ps_ttm=2, turnover=2, volume_ratio=1),
    ])
    financial = {'600001': {'roe': 15, 'debt_ratio': 40},
                 '000001': {'roe': float('nan'), 'debt_ratio': 40},
                 '000002': {'roe': -1, 'debt_ratio': 40}}
    growth = {code: {'netprofit_yoy': 20} for code in stocks.code}
    return stocks, financial, growth


def test_quality_observation_accepts_large_quiet_stock_without_trend_confirmation():
    stocks, financial, growth = inputs()
    selector = getattr(stock_main, 'select_longterm_quality_pool', None)
    assert callable(selector), '缺少独立质量观察筛选'
    pool, diagnostic = selector(stocks, financial, growth, '20260911')
    assert pool.code.tolist() == ['600001']
    assert not pool.trend_confirmed.any()
    assert diagnostic['input_count'] == 3
    assert diagnostic['missing_financial_count'] == 1
    assert diagnostic['quality_rejected_count'] == 1
    assert diagnostic['quality_count'] == 1


def test_unconfirmed_quality_never_becomes_elite_despite_high_score():
    quality = pd.DataFrame([dict(code='600001', name='质量公司', industry='制造',
        quality_score=99, longterm_score=99, industry_rs=10, drawdown_from_high=10,
        price_vs_ma60=8, turnover=2, pb=2, close=20, trend_confirmed=False)])
    import inspect
    assert 'quality_pool' in inspect.signature(build_live_watchlists).parameters
    result = build_live_watchlists(pd.DataFrame(), '20260911', quality_pool=quality)
    assert len(result.watchlist) == 1
    assert result.elite.empty
    buckets = split_longterm_pool([dict(profile='longterm_watch', latest_score=99)])
    assert len(buckets['watch']) == 1
    assert not buckets['elite']


def test_high_watch_score_does_not_override_explicit_profile():
    buckets = split_longterm_pool([dict(profile='longterm_watch', latest_score=99)])
    assert len(buckets['watch']) == 1


def test_snapshot_uses_actual_quality_scan_in_bear_market():
    selection = dict(trade_date='20260911', regime='BEAR_TREND',
        longterm_diagnostics={'status': 'completed_with_results', 'quality_count': 1,
                              'input_count': 100, 'confirmation_reason': '市场未确认'})
    scan = build_selection_snapshot(selection, True, 1, 0)['longterm_scan']
    assert scan['status'] == 'completed_with_results'
    assert scan['quality_count'] == 1


def test_quality_missing_valuation_is_not_a_zero_price_bargain():
    stocks, financial, growth = inputs()
    stocks.loc[0, 'pb'] = float('nan')
    selector = getattr(stock_main, 'select_longterm_quality_pool', None)
    assert callable(selector)
    pool, diagnostic = selector(stocks, financial, growth, '20260911')
    assert pool.empty
    assert diagnostic['missing_financial_count'] == 2


def test_quality_scan_failure_keeps_previous_pool(tmp_path):
    from longterm_scan import publish_longterm_scan, get_latest_longterm_scan
    from signal_store import SignalStore
    stocks, financial, growth = inputs()
    pool, diagnostic = stock_main.select_longterm_quality_pool(stocks, financial, growth, '20260911')
    lists = build_live_watchlists(pd.DataFrame(), '20260911', quality_pool=pool)
    db = tmp_path / 'signals.db'
    publish_longterm_scan('20260911', diagnostic, lists, db_path=db)
    publish_longterm_scan('20260914', {'status': 'failed', 'reason': '行情滞后'}, None, db_path=db)
    from web_app.services.signal_service import get_active_longterm_pool
    active = get_active_longterm_pool(db)
    assert [row['ts_code'] for row in active] == ['600001.SH']
    assert get_latest_longterm_scan(db)['status'] == 'failed'


def test_quality_scan_does_not_overwrite_short_run(tmp_path):
    from longterm_scan import publish_longterm_scan
    from signal_store import SignalStore
    import sqlite3
    db = tmp_path / 'signals.db'
    store = SignalStore(db)
    store.record_run(trade_date='20260911', mode='short', profile='existing', source='live')
    store.close()
    publish_longterm_scan('20260911', {'status': 'completed_empty'},
                         build_live_watchlists(pd.DataFrame(), '20260911'), db_path=db)
    with sqlite3.connect(db) as conn:
        assert conn.execute("select count(*) from signal_runs where mode='short'").fetchone()[0] == 1


def test_quality_fetch_disables_single_day_flow_gate(monkeypatch):
    stocks, financial, growth = inputs()
    import market_data_clock
    monkeypatch.setattr(market_data_clock, 'require_update_freshness', lambda *a, **kw: {})
    def fetch(**kwargs):
        assert kwargs.get('require_positive_flow') is False
        return stocks, '20260911', 0, pd.DataFrame()
    monkeypatch.setattr(stock_main, 'get_all_stocks', fetch)
    monkeypatch.setattr(stock_main, 'get_financial_data_batch', lambda *a, **kw: financial)
    monkeypatch.setattr(stock_main, 'get_net_profit_growth_batch', lambda *a, **kw: growth)
    result = stock_main.attach_longterm_quality_observation(
        {'trade_date': '20260911', 'regime': 'BEAR_TREND', 'longterm_pool': pd.DataFrame()})
    assert len(result['longterm_quality_pool']) == 1
    assert result['longterm_diagnostics']['confirmed_count'] == 0


def test_published_quality_exposes_unconfirmed_state_on_read(tmp_path):
    from longterm_scan import publish_longterm_scan
    from web_app.services.signal_service import get_active_longterm_pool
    stocks, financial, growth = inputs()
    pool, diagnostic = stock_main.select_longterm_quality_pool(stocks, financial, growth, '20260911')
    db = tmp_path / 'signals.db'
    publish_longterm_scan('20260911', diagnostic,
                         build_live_watchlists(pd.DataFrame(), '20260911', quality_pool=pool), db_path=db)
    active = get_active_longterm_pool(db)
    assert active[0].get('trend_confirmed') is False
    assert '质量排序' in active[0]['score_basis']


def test_longterm_page_shows_scan_funnel_and_unconfirmed_quality(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import importlib
    app_module = importlib.import_module('web_app.app')
    from longterm_scan import publish_longterm_scan
    stocks, financial, growth = inputs()
    pool, diagnostic = stock_main.select_longterm_quality_pool(stocks, financial, growth, '20260911')
    diagnostic.update(confirmation_reason='测试市场尚未确认', confirmed_count=0)
    db = tmp_path / 'signals.db'
    publish_longterm_scan('20260911', diagnostic,
                         build_live_watchlists(pd.DataFrame(), '20260911', quality_pool=pool), db_path=db)
    monkeypatch.setattr(app_module, 'DEFAULT_SIGNAL_DB_PATH', db)
    response = TestClient(app_module.app).get('/longterm')
    assert response.status_code == 200
    assert '质量扫描漏斗' in response.text
    assert '测试市场尚未确认' in response.text
    assert '未确认，仅观察' in response.text
    assert '财务数据缺失' in response.text
    assert '质量扫描完成' in response.text
    assert '候选漏斗未采集' not in response.text


def test_quality_signal_explanation_does_not_invent_short_technical_strength():
    payload = stock_main._signal_factor_payload(pd.Series(dict(
        observation_version='quality_observation_v1', volume_ratio=1,
        observation_reason='财务质量达标；趋势尚未确认', quality_score=95)))
    assert '板块不弱' not in str(payload)


def test_formal_filter_diagnostics_count_missing_technical_data():
    import inspect
    assert 'diagnostics' in inspect.signature(stock_main.select_longterm_pool).parameters
    stocks, financial, growth = inputs()
    diagnostic = {}
    result = stock_main.select_longterm_pool(stocks, {}, '20260911',
        financial_dict=financial, profit_growth_dict=growth,
        longterm_profile='longterm_quality_lifecycle_v18_market_sync',
        macro_data=dict(idx_ret_60d=6, idx_ret_120d=6, ma100_slope_pct=.2, price_vs_ma100=2),
        diagnostics=diagnostic)
    assert result.empty
    assert diagnostic['missing_technical_count'] == 3
    assert diagnostic['status'] == 'completed_empty'


def test_formal_sync_failure_is_not_reported_as_individual_stock_failure():
    import inspect
    assert 'diagnostics' in inspect.signature(stock_main.select_longterm_pool).parameters
    stocks, financial, growth = inputs()
    diagnostic = {}
    stock_main.select_longterm_pool(stocks, {}, '20260911',
        longterm_profile='longterm_quality_lifecycle_v18_market_sync', diagnostics=diagnostic)
    assert diagnostic['status'] == 'not_triggered'
    assert '市场同步' in diagnostic['reason']
