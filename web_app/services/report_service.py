"""每日研究报告的只读页面服务。"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from daily_report.store import get_adjacent_report_dates, get_report, search_reports


def build_report_archive_context(
    db_path: str | Path,
    query: str = "",
    start: str = "",
    end: str = "",
) -> dict:
    return {
        "query": str(query or "").strip(),
        "start": _normalize_date(start),
        "end": _normalize_date(end),
        "items": search_reports(db_path, query=query, start=start, end=end, limit=100),
    }


def build_report_detail_context(db_path: str | Path, report_date: str) -> dict | None:
    report = get_report(db_path, report_date)
    if not report:
        return None
    previous_date, next_date = get_adjacent_report_dates(db_path, report_date)
    from daily_report.publication import safe_source_url
    from market_data_clock import require_report_freshness

    document = report.get('document') or {}
    snapshot = document.get('evidence_snapshot') or {}
    for section in document.get('sections') or []:
        for paragraph in section.get('paragraphs') or []:
            sources = []
            for key in paragraph.get('evidence_ids') or []:
                item = snapshot.get(key)
                if isinstance(item, dict):
                    sources.append({
                        'label': str(item.get('label') or '公开依据')[:120],
                        'text': str(item.get('text') or '')[:800],
                        'source_url': safe_source_url(item.get('source_url')),
                        'published_at': str(item.get('published_at') or '')[:80],
                    })
            paragraph['display_evidence'] = sources
    warning = ''
    recorded_clock = document.get('data_freshness') or {}
    if not (recorded_clock.get('status') == 'fresh'
            and recorded_clock.get('target_date') == report['report_date']
            and recorded_clock.get('actual_date') == report['market_date']):
        try:
            require_report_freshness(report['report_date'], report['market_date'], Path(db_path).parent / 'stock_history.db')
        except ValueError as exc:
            warning = str(exc)
    return {
        "report": report,
        "previous_date": previous_date,
        "next_date": next_date,
        "report_warning": warning,
        "is_historical_report": report['report_date'] < datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d'),
        "has_evidence_snapshot": bool(snapshot),
    }


def _normalize_date(value: str) -> str:
    return re.sub(r"\D", "", str(value or ""))[:8]
