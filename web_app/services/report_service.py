"""每日研究报告的只读页面服务。"""

from __future__ import annotations

import re
from pathlib import Path

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
    return {
        "report": report,
        "previous_date": previous_date,
        "next_date": next_date,
    }


def _normalize_date(value: str) -> str:
    return re.sub(r"\D", "", str(value or ""))[:8]
