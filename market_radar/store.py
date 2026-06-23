"""SQLite persistence for Market Radar v2 research snapshots."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path


def save_market_radar_snapshot(db_path: str | Path, radar_date: str, brief: dict, decision: dict) -> int:
    """Upsert one Market Radar snapshot and return its row id."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _snapshot_payload(str(radar_date or ""), brief, decision)
    conn = sqlite3.connect(path)
    try:
        _ensure_schema(conn)
        conn.execute(
            """
            insert into market_radar_snapshots (
                radar_date, created_at, updated_at, headline, closing_judgement,
                brief_json, event_count, thesis_count, stock_count, risk_count
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(radar_date) do update set
                updated_at = excluded.updated_at,
                headline = excluded.headline,
                closing_judgement = excluded.closing_judgement,
                brief_json = excluded.brief_json,
                event_count = excluded.event_count,
                thesis_count = excluded.thesis_count,
                stock_count = excluded.stock_count,
                risk_count = excluded.risk_count
            """,
            (
                payload["radar_date"],
                payload["now"],
                payload["now"],
                payload["headline"],
                payload["closing_judgement"],
                payload["brief_json"],
                payload["event_count"],
                payload["thesis_count"],
                payload["stock_count"],
                payload["risk_count"],
            ),
        )
        row = conn.execute(
            "select id from market_radar_snapshots where radar_date = ?",
            (payload["radar_date"],),
        ).fetchone()
        conn.commit()
        return int(row[0])
    finally:
        conn.close()


def get_latest_market_radar_snapshot(db_path: str | Path) -> dict | None:
    """Read the newest Market Radar snapshot."""
    path = Path(db_path)
    if not path.exists():
        return None
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        _ensure_schema(conn)
        row = conn.execute(
            """
            select *
            from market_radar_snapshots
            order by radar_date desc, updated_at desc, id desc
            limit 1
            """
        ).fetchone()
        if row is None:
            return None
        return _row_to_snapshot(row)
    finally:
        conn.close()


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        create table if not exists market_radar_snapshots (
            id integer primary key autoincrement,
            radar_date text not null unique,
            created_at text not null,
            updated_at text not null,
            headline text not null default '',
            closing_judgement text not null default '',
            brief_json text not null,
            event_count integer not null default 0,
            thesis_count integer not null default 0,
            stock_count integer not null default 0,
            risk_count integer not null default 0
        )
        """
    )


def _snapshot_payload(radar_date: str, brief: dict, decision: dict) -> dict:
    summary = brief.get("snapshot_summary") if isinstance(brief.get("snapshot_summary"), dict) else {}
    review = decision.get("review_loop") if isinstance(decision.get("review_loop"), dict) else {}
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return {
        "radar_date": radar_date.replace("-", "")[:8],
        "now": now,
        "headline": str(brief.get("headline") or ""),
        "closing_judgement": str(review.get("closing_judgement") or ""),
        "brief_json": json.dumps(brief, ensure_ascii=False, sort_keys=True),
        "event_count": int(summary.get("event_count") or 0),
        "thesis_count": int(summary.get("thesis_count") or 0),
        "stock_count": int(summary.get("stock_count") or 0),
        "risk_count": int(summary.get("risk_count") or 0),
    }


def _row_to_snapshot(row: sqlite3.Row) -> dict:
    try:
        brief = json.loads(row["brief_json"] or "{}")
    except json.JSONDecodeError:
        brief = {}
    return {
        "id": row["id"],
        "radar_date": row["radar_date"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "headline": row["headline"],
        "closing_judgement": row["closing_judgement"],
        "brief": brief,
        "event_count": row["event_count"],
        "thesis_count": row["thesis_count"],
        "stock_count": row["stock_count"],
        "risk_count": row["risk_count"],
    }
