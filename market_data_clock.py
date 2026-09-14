"""按交易日历核验报告与更新任务所需的行情日期。"""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd


def _date(value):
    text = str(value or '').replace('-', '').strip()
    if len(text) != 8:
        raise ValueError('日期必须为 YYYYMMDD')
    datetime.strptime(text, '%Y%m%d')
    return text


def check_market_freshness(target_date, actual_date, calendar, *, include_target):
    """目标日前或当日最后交易日为最低要求；缺失日历时不猜测。"""
    result = {'target_date': str(target_date), 'actual_date': str(actual_date or ''),
              'expected_date': '', 'status': 'unknown', 'reason': ''}
    try:
        target = _date(target_date)
        actual = _date(actual_date) if actual_date else ''
        if actual and actual > target:
            return {**result, 'status': 'invalid', 'reason': '行情日期晚于目标日期，不能用于历史研判'}
        if calendar is None or not {'cal_date', 'is_open'}.issubset(calendar.columns):
            raise ValueError('交易日历缺失，无法核验数据时效')
        frame = calendar.copy()
        if 'exchange' in frame.columns:
            frame = frame[frame['exchange'].eq('SSE')]
        frame['cal_date'] = frame['cal_date'].astype(str).str.replace(r'\.0$', '', regex=True).str.replace('-', '')
        frame['is_open'] = pd.to_numeric(frame['is_open'], errors='coerce')
        frame = frame[frame['cal_date'] <= target]
        if frame.empty or target not in set(frame['cal_date']):
            raise ValueError(f'交易日历未覆盖 {target}，无法核验数据时效')
        if frame.groupby('cal_date')['is_open'].nunique().gt(1).any():
            raise ValueError('交易日历存在冲突')
        available = frame[frame['is_open'].eq(1)]
        available = available[available['cal_date'] <= target if include_target else available['cal_date'] < target]
        if available.empty:
            raise ValueError('交易日历缺少目标日前有效交易日')
        expected = available['cal_date'].max()
        interval = pd.date_range(datetime.strptime(expected, '%Y%m%d'), datetime.strptime(target, '%Y%m%d')).strftime('%Y%m%d')
        valid_dates = set(frame.loc[frame['is_open'].isin([0, 1]), 'cal_date'])
        if not set(interval).issubset(valid_dates):
            raise ValueError('交易日历区间不完整，无法核验数据时效')
        result['expected_date'] = expected
        if not actual or actual < expected:
            return {**result, 'status': 'stale', 'reason': f'行情仍滞后：应至少到 {expected}，实际为 {actual or "无有效行情"}；暂停当日研判'}
        if actual not in set(frame.loc[frame['is_open'].eq(1), 'cal_date']):
            return {**result, 'status': 'invalid', 'reason': '行情日期不是已核验的交易日'}
        return {**result, 'status': 'fresh', 'reason': f'行情已覆盖所需交易日 {expected}'}
    except (ValueError, TypeError) as exc:
        return {**result, 'reason': str(exc)}


def _calendar(cache_dir):
    try:
        return pd.read_parquet(Path(cache_dir) / 'trade_cal.parquet')
    except (OSError, ValueError):
        return None


def _require(result):
    if result['status'] != 'fresh':
        raise ValueError(result['reason'])
    return result


def require_report_freshness(report_date, market_date, history_db, *, cache_dir=None):
    """早报至少使用报告日前最近交易日，允许同日报告使用已获取的当日行情。"""
    return _require(check_market_freshness(
        report_date, market_date, _calendar(cache_dir if cache_dir is not None else Path(history_db).parent / 'cache'), include_target=False,
    ))


def require_update_freshness(target_date, actual_date, cache_dir, *, now=None):
    """当日18点前允许前一交易日，历史任务必须覆盖指定日期的已完成行情。"""
    now = now or datetime.now(ZoneInfo('Asia/Shanghai'))
    now = now.astimezone(ZoneInfo('Asia/Shanghai'))
    target = _date(target_date)
    today = now.strftime('%Y%m%d')
    if target > today:
        raise ValueError('更新目标不能晚于当前日期')
    include_target = target < today or now.hour >= 18
    return _require(check_market_freshness(target, actual_date, _calendar(cache_dir), include_target=include_target))
