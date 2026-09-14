"""独立运行长线扫描并保存诊断，不覆盖短线运行或日报快照。"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def get_latest_longterm_scan(db_path='data/stock_signals.db'):
    if not Path(db_path).exists():
        return {}
    with sqlite3.connect(db_path) as conn:
        if not conn.execute("select 1 from sqlite_master where type='table' and name='longterm_scan_runs'").fetchone():
            return {}
        row = conn.execute('select diagnostic_json from longterm_scan_runs order by id desc limit 1').fetchone()
        return json.loads(row[0]) if row else {}


def publish_longterm_scan(trade_date, diagnostic, lists, *, db_path='data/stock_signals.db'):
    import main as stock_main
    from signal_store import SignalStore
    details = {**diagnostic, 'trade_date': trade_date,
               'scanned_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds')}
    store = SignalStore(db_path)
    try:
        missing = set(details.get('missing_financial_codes') or [])
        active = {row[0] for row in store.conn.execute(
            "select ts_code from pool_state where mode='longterm' and profile='longterm_watch' and state='active'")}
        retained = set(lists.watchlist['ts_code']) if lists is not None and not lists.watchlist.empty else set()
        missing_active = sorted((missing & active) - retained)
        if missing_active:
            details.update(status='failed', missing_active_codes=missing_active,
                           reason='原观察股财务缺失，保留旧池：' + '、'.join(missing_active))
        # 失败只写诊断，绝不把上次有效候选当成本次全部退出。
        if lists is not None and str(details.get('status', '')).startswith('completed_'):
            for profile, frame in [('longterm_watch', lists.watchlist), ('longterm_elite', lists.elite)]:
                stock_main._persist_one_signal_pool(
                    store, trade_date, 'longterm', profile,
                    stock_main._signal_records_from_df(frame, pool_type=profile, score_col='compression_score'))
            details.update(watch_count=len(lists.watchlist), elite_count=len(lists.elite))
    finally:
        store.close()
    with sqlite3.connect(db_path) as conn:
        conn.execute('create table if not exists longterm_scan_runs (id integer primary key, diagnostic_json text not null)')
        conn.execute('insert into longterm_scan_runs(diagnostic_json) values (?)',
                     (json.dumps(details, ensure_ascii=False, allow_nan=False),))
    return details


def run_scan(target_date=None):
    import pandas as pd
    import config
    import main as stock_main
    from market_data_clock import check_market_freshness, require_update_freshness
    from longterm_live_pipeline import build_live_watchlists
    now = datetime.now(ZoneInfo('Asia/Shanghai'))
    target_date = target_date or now.strftime('%Y%m%d')
    trade_date = target_date
    try:
        calendar = pd.read_parquet('data/cache/trade_cal.parquet')
        clock = check_market_freshness(target_date, '', calendar,
                    include_target=target_date < now.strftime('%Y%m%d') or now.hour >= 18)
        trade_date = clock['expected_date']
        if not trade_date:
            raise ValueError(clock['reason'])
        require_update_freshness(target_date, trade_date, 'data/cache', now=now)
        selection = stock_main.run_daily_selection(trade_date, enable_news=False, include_longterm=True)
        stock_main.attach_longterm_quality_observation(selection, target_date=target_date)
        lists = build_live_watchlists(
            selection['longterm_pool'], trade_date,
            max_watch=config.LONGTERM_LIVE_TOPN,
            max_industry=config.LONGTERM_LIVE_MAX_INDUSTRY_PER_DAY,
            elite_min_score=config.LONGTERM_ELITE_MIN_COMPRESSION_SCORE,
            elite_min_industry_rs=config.LONGTERM_ELITE_MIN_INDUSTRY_RS,
            elite_min_drawdown=config.LONGTERM_ELITE_DRAWDOWN_MIN,
            elite_max_drawdown=config.LONGTERM_ELITE_DRAWDOWN_MAX,
            quality_pool=selection['longterm_quality_pool'], quality_top_n=config.LONGTERM_QUALITY_TOPN)
        lists.watchlist, lists.elite = stock_main._apply_longterm_elite_cooldown(
            lists.watchlist, lists.elite, trade_date)
        details = publish_longterm_scan(trade_date, selection['longterm_diagnostics'], lists)
        if details['status'] == 'failed':
            raise ValueError(details['reason'])
        print(json.dumps(details, ensure_ascii=False))
        if not lists.watchlist.empty:
            print(lists.watchlist[['ts_code', 'name', 'industry', 'trend_confirmed']].to_string(index=False))
        return details
    except Exception as exc:
        publish_longterm_scan(trade_date or target_date, {'status': 'failed', 'reason': str(exc)}, None)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='扫描最新完整交易日的长线质量观察与趋势确认')
    parser.add_argument('--target-date', default=None)
    run_scan(parser.parse_args().target_date)
