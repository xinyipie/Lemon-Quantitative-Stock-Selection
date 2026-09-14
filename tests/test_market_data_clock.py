from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from market_data_clock import check_market_freshness, require_report_freshness


def calendar():
    dates = pd.date_range('2026-09-04', '2026-09-14')
    return pd.DataFrame({'cal_date': dates.strftime('%Y%m%d'), 'is_open': [int(d.weekday() < 5) for d in dates]})


def test_old_data_is_rejected_but_monday_previous_friday_is_valid():
    result = check_market_freshness('20260914', '20260904', calendar(), include_target=False)
    assert result['status'] == 'stale'
    assert result['expected_date'] == '20260911'
    assert check_market_freshness('20260914', '20260911', calendar(), include_target=False)['status'] == 'fresh'


def test_holiday_uses_calendar_not_weekdays():
    frame = calendar()
    frame.loc[frame.cal_date.between('20260907', '20260911'), 'is_open'] = 0
    assert check_market_freshness('20260914', '20260904', frame, include_target=False)['status'] == 'fresh'


def test_missing_calendar_coverage_and_future_data_are_blocked():
    assert check_market_freshness('20260914', '20260904', calendar().iloc[:-1], include_target=False)['status'] == 'unknown'
    assert check_market_freshness('20260914', '20260915', calendar(), include_target=False)['status'] == 'invalid'


def test_missing_actual_does_not_fall_back_to_requested_date():
    assert check_market_freshness('20260914', None, calendar(), include_target=True)['status'] == 'stale'


def test_report_guard_reads_neighbor_cache_and_fails_closed(tmp_path):
    with pytest.raises(ValueError, match='日历'):
        require_report_freshness('20260914', '20260904', tmp_path / 'history.db')
    (tmp_path / 'cache').mkdir()
    calendar().to_parquet(tmp_path / 'cache' / 'trade_cal.parquet')
    with pytest.raises(ValueError, match='20260911'):
        require_report_freshness('20260914', '20260904', tmp_path / 'history.db')
    require_report_freshness('20260914', '20260911', tmp_path / 'history.db')


def test_update_guard_before_close_and_stale_radar(tmp_path):
    from market_data_clock import require_update_freshness
    calendar().to_parquet(tmp_path / 'trade_cal.parquet')
    morning = datetime(2026, 9, 14, 12, tzinfo=ZoneInfo('Asia/Shanghai'))
    require_update_freshness('20260914', '20260911', tmp_path, now=morning)
    with pytest.raises(ValueError, match='20260911'):
        require_update_freshness('20260914', '20260904', tmp_path, now=morning)
    evening = morning.replace(hour=19)
    with pytest.raises(ValueError, match='20260914'):
        require_update_freshness('20260914', '20260911', tmp_path, now=evening)


def test_report_guard_uses_explicit_cache_directory(tmp_path):
    cache = tmp_path / 'custom_cache'
    cache.mkdir()
    calendar().to_parquet(cache / 'trade_cal.parquet')
    require_report_freshness('20260914', '20260911', tmp_path / 'db' / 'history.db', cache_dir=cache)


def test_stale_report_stops_before_facts_and_ai_and_records_failure(tmp_path):
    from daily_report.service import generate_daily_report
    from daily_report.store import get_generation_job, get_report
    cache = tmp_path / 'custom_cache'
    cache.mkdir()
    calendar().to_parquet(cache / 'trade_cal.parquet')
    calls = []
    result = generate_daily_report(
        '20260914', '20260904', tmp_path / 'signals.db', tmp_path / 'history.db',
        cache_dir=cache, facts_builder=lambda *args: calls.append('facts'),
        writer=lambda *args: calls.append('ai'),
    )
    assert result['status'] == 'failed'
    assert '20260911' in result['reason']
    assert calls == []
    assert get_report(tmp_path / 'signals.db', '20260914') is None
    assert get_generation_job(tmp_path / 'signals.db', '20260914')['status'] == 'failed'
