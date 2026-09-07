"""每日研究报告的版本化归档、生成任务与检索。"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


STALE_AFTER = timedelta(minutes=45)


def _connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    _init_schema(conn)
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        create table if not exists daily_reports (
            id integer primary key autoincrement,
            report_date text not null unique,
            market_date text not null,
            title text not null,
            document_json text not null,
            body_text text not null,
            keywords_json text not null,
            input_hash text not null,
            data_cutoff text not null,
            news_cutoff text not null,
            version_id integer not null,
            published_at text not null,
            updated_at text not null
        );

        create table if not exists daily_report_versions (
            id integer primary key autoincrement,
            report_date text not null,
            market_date text not null,
            title text not null,
            document_json text not null,
            body_text text not null,
            keywords_json text not null,
            input_hash text not null,
            data_cutoff text not null,
            news_cutoff text not null,
            created_at text not null
        );

        create index if not exists idx_daily_report_versions_date
            on daily_report_versions(report_date, id desc);

        create table if not exists daily_report_jobs (
            report_date text primary key,
            status text not null,
            slot text not null,
            attempt_count integer not null default 0,
            last_error text not null default '',
            started_at text not null,
            updated_at text not null
        );
        """
    )
    _init_fts(conn)
    conn.commit()


def _init_fts(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute(
            """
            create virtual table if not exists daily_report_search using fts5(
                report_date unindexed,
                title,
                body_text,
                keywords
            )
            """
        )
        return True
    except sqlite3.OperationalError:
        return False


def _now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clean_date(value: str | None) -> str:
    return re.sub(r"\D", "", str(value or ""))[:8]


def _is_stale(started_at: str) -> bool:
    try:
        parsed = datetime.fromisoformat(started_at)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - parsed.astimezone(timezone.utc) > STALE_AFTER
    except (TypeError, ValueError):
        return True


def begin_generation(
    db_path: str | Path,
    report_date: str,
    slot: str,
    retry_if_missing: bool = False,
    force: bool = False,
) -> bool:
    """原子占用某个发布日期；已有有效报告时默认不重复生成。"""
    normalized = _clean_date(report_date)
    if len(normalized) != 8:
        raise ValueError("report_date must be YYYYMMDD")
    conn = _connect(db_path)
    now = _now_text()
    try:
        conn.execute("begin immediate")
        published = conn.execute(
            "select 1 from daily_reports where report_date = ?", (normalized,)
        ).fetchone()
        job = conn.execute(
            "select * from daily_report_jobs where report_date = ?", (normalized,)
        ).fetchone()
        if not force:
            if published is not None:
                conn.rollback()
                return False
            if retry_if_missing and job is not None and job["status"] == "published":
                conn.rollback()
                return False
            if job is not None and job["status"] == "running" and not _is_stale(job["started_at"]):
                conn.rollback()
                return False
        attempt_count = int(job["attempt_count"]) + 1 if job is not None else 1
        conn.execute(
            """
            insert into daily_report_jobs(
                report_date, status, slot, attempt_count, last_error, started_at, updated_at
            ) values (?, 'running', ?, ?, '', ?, ?)
            on conflict(report_date) do update set
                status = 'running',
                slot = excluded.slot,
                attempt_count = excluded.attempt_count,
                last_error = '',
                started_at = excluded.started_at,
                updated_at = excluded.updated_at
            """,
            (normalized, str(slot or "manual"), attempt_count, now, now),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def finish_generation(
    db_path: str | Path,
    report_date: str,
    status: str,
    error: str = "",
) -> None:
    """记录本次生成结论，失败信息不进入公开报告。"""
    if status not in {"published", "failed"}:
        raise ValueError("status must be published or failed")
    normalized = _clean_date(report_date)
    conn = _connect(db_path)
    try:
        conn.execute(
            """
            update daily_report_jobs
            set status = ?, last_error = ?, updated_at = ?
            where report_date = ?
            """,
            (status, str(error or "")[:500], _now_text(), normalized),
        )
        conn.commit()
    finally:
        conn.close()


def publish_report(
    db_path: str | Path,
    *,
    report_date: str,
    market_date: str,
    title: str,
    document: dict,
    body_text: str,
    keywords: list[str],
    input_hash: str,
    data_cutoff: str,
    news_cutoff: str,
) -> int:
    """先保留不可变版本，再原子替换该发布日期的当前版本。"""
    normalized_report = _clean_date(report_date)
    normalized_market = _clean_date(market_date)
    if len(normalized_report) != 8 or len(normalized_market) != 8:
        raise ValueError("report_date and market_date must be YYYYMMDD")
    document_json = json.dumps(document, ensure_ascii=False, sort_keys=True)
    keywords_json = json.dumps(list(dict.fromkeys(keywords)), ensure_ascii=False)
    now = _now_text()
    conn = _connect(db_path)
    try:
        conn.execute("begin immediate")
        cursor = conn.execute(
            """
            insert into daily_report_versions(
                report_date, market_date, title, document_json, body_text,
                keywords_json, input_hash, data_cutoff, news_cutoff, created_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                normalized_report,
                normalized_market,
                title,
                document_json,
                body_text,
                keywords_json,
                input_hash,
                data_cutoff,
                news_cutoff,
                now,
            ),
        )
        version_id = int(cursor.lastrowid)
        conn.execute(
            """
            insert into daily_reports(
                report_date, market_date, title, document_json, body_text,
                keywords_json, input_hash, data_cutoff, news_cutoff,
                version_id, published_at, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(report_date) do update set
                market_date = excluded.market_date,
                title = excluded.title,
                document_json = excluded.document_json,
                body_text = excluded.body_text,
                keywords_json = excluded.keywords_json,
                input_hash = excluded.input_hash,
                data_cutoff = excluded.data_cutoff,
                news_cutoff = excluded.news_cutoff,
                version_id = excluded.version_id,
                updated_at = excluded.updated_at
            """,
            (
                normalized_report,
                normalized_market,
                title,
                document_json,
                body_text,
                keywords_json,
                input_hash,
                data_cutoff,
                news_cutoff,
                version_id,
                now,
                now,
            ),
        )
        if _init_fts(conn):
            conn.execute("delete from daily_report_search where report_date = ?", (normalized_report,))
            conn.execute(
                "insert into daily_report_search(report_date, title, body_text, keywords) values (?, ?, ?, ?)",
                (normalized_report, title, body_text, " ".join(keywords)),
            )
        conn.commit()
        return version_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _decode_report(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    result = dict(row)
    result["document"] = json.loads(result.pop("document_json"))
    result["keywords"] = json.loads(result.pop("keywords_json"))
    return result


def get_report(db_path: str | Path, report_date: str) -> dict | None:
    path = Path(db_path)
    if not path.exists():
        return None
    conn = _connect(path)
    try:
        row = conn.execute(
            "select * from daily_reports where report_date = ?", (_clean_date(report_date),)
        ).fetchone()
        return _decode_report(row)
    finally:
        conn.close()


def get_latest_report(db_path: str | Path) -> dict | None:
    path = Path(db_path)
    if not path.exists():
        return None
    conn = _connect(path)
    try:
        return _decode_report(
            conn.execute("select * from daily_reports order by report_date desc limit 1").fetchone()
        )
    finally:
        conn.close()


def get_adjacent_report_dates(
    db_path: str | Path, report_date: str
) -> tuple[str | None, str | None]:
    path = Path(db_path)
    if not path.exists():
        return None, None
    normalized = _clean_date(report_date)
    conn = _connect(path)
    try:
        previous = conn.execute(
            "select max(report_date) from daily_reports where report_date < ?", (normalized,)
        ).fetchone()[0]
        following = conn.execute(
            "select min(report_date) from daily_reports where report_date > ?", (normalized,)
        ).fetchone()[0]
        return previous, following
    finally:
        conn.close()


def search_reports(
    db_path: str | Path,
    query: str = "",
    start: str = "",
    end: str = "",
    limit: int = 100,
) -> list[dict]:
    path = Path(db_path)
    if not path.exists():
        return []
    conn = _connect(path)
    try:
        where = ["1 = 1"]
        params: list[Any] = []
        if start:
            where.append("report_date >= ?")
            params.append(_clean_date(start))
        if end:
            where.append("report_date <= ?")
            params.append(_clean_date(end))
        cleaned_query = str(query or "").strip()
        if cleaned_query:
            like = f"%{cleaned_query}%"
            where.append("(title like ? or body_text like ? or keywords_json like ?)")
            params.extend([like, like, like])
        params.append(max(1, min(int(limit), 500)))
        rows = conn.execute(
            f"""
            select report_date, market_date, title, body_text, published_at
            from daily_reports
            where {' and '.join(where)}
            order by report_date desc
            limit ?
            """,
            params,
        ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            text = item.pop("body_text")
            item["snippet"] = _snippet(text, cleaned_query)
            results.append(item)
        return results
    finally:
        conn.close()


def _snippet(body: str, query: str, width: int = 140) -> str:
    compact = re.sub(r"\s+", " ", str(body or "")).strip()
    if not query:
        return compact[:width]
    index = compact.lower().find(query.lower())
    if index < 0:
        return compact[:width]
    start = max(0, index - width // 3)
    return compact[start : start + width]


def get_generation_job(db_path: str | Path, report_date: str) -> dict | None:
    path = Path(db_path)
    if not path.exists():
        return None
    conn = _connect(path)
    try:
        row = conn.execute(
            "select * from daily_report_jobs where report_date = ?", (_clean_date(report_date),)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()
