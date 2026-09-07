"""保存每日正式扫描的市场与空池状态。"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path


ALLOWED_LONGTERM_REGIMES = {"BULL_TREND", "BULL_PULLBACK"}


def build_selection_snapshot(
    selection: dict,
    include_longterm: bool,
    longterm_watch_count: int,
    longterm_elite_count: int,
) -> dict:
    short_count = _frame_count(selection.get("stock_pool"))
    observe_count = _frame_count(selection.get("short_observe_pool"))
    longterm_raw_count = _frame_count(selection.get("longterm_pool"))
    regime = str(selection.get("regime") or "")
    if not include_longterm:
        longterm_status = "disabled"
    elif regime not in ALLOWED_LONGTERM_REGIMES:
        longterm_status = "not_triggered"
    elif longterm_raw_count:
        longterm_status = "completed_with_results"
    else:
        longterm_status = "completed_empty"
    return {
        "trade_date": str(selection.get("trade_date") or "").replace("-", "")[:8],
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "market": {
            "market_state": selection.get("market_state"),
            "market_style": selection.get("market_style"),
            "macro_mode": selection.get("macro_mode"),
            "regime": regime,
            "regime_data": _json_safe(selection.get("regime_data") or {}),
            "operation_mode": selection.get("operation_mode"),
            "sentiment": _json_safe(selection.get("sentiment_data") or {}),
        },
        "short_scan": {
            "status": "completed_with_results" if short_count else "completed_empty",
            "formal_count": short_count,
            "observe_count": observe_count,
        },
        "longterm_scan": {
            "status": longterm_status,
            "raw_count": longterm_raw_count,
            "watch_count": int(longterm_watch_count),
            "elite_count": int(longterm_elite_count),
        },
    }


def save_selection_snapshot(db_path: str | Path, snapshot: dict) -> None:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            create table if not exists daily_selection_snapshots (
                trade_date text primary key,
                created_at text not null,
                snapshot_json text not null
            )
            """
        )
        conn.execute(
            """
            insert into daily_selection_snapshots(trade_date, created_at, snapshot_json)
            values (?, ?, ?)
            on conflict(trade_date) do update set
                created_at = excluded.created_at,
                snapshot_json = excluded.snapshot_json
            """,
            (
                snapshot["trade_date"],
                snapshot["created_at"],
                json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_selection_snapshot(db_path: str | Path, trade_date: str) -> dict | None:
    path = Path(db_path)
    if not path.exists():
        return None
    conn = sqlite3.connect(path)
    try:
        row = conn.execute(
            "select snapshot_json from daily_selection_snapshots where trade_date = ?",
            (str(trade_date).replace("-", "")[:8],),
        ).fetchone()
        return json.loads(row[0]) if row else None
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()


def _frame_count(value) -> int:
    return int(len(value)) if value is not None else 0


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "item"):
        return value.item()
    return value
