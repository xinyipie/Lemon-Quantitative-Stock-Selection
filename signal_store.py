#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""SQLite storage for usable stock signals and watch-pool state."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = Path("data") / "stock_signals.db"


@dataclass
class SignalRecord:
    ts_code: str
    name: str = ""
    industry: str = ""
    rank: int | None = None
    score: float | None = None
    pool_type: str = "watch"
    reason: str = ""
    factors: dict[str, Any] = field(default_factory=dict)


class SignalStore:
    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.init_schema()

    def close(self) -> None:
        self.conn.close()

    def init_schema(self) -> None:
        self.conn.executescript(
            """
            create table if not exists signal_runs (
                run_id integer primary key autoincrement,
                run_date text not null,
                trade_date text not null,
                mode text not null,
                profile text not null,
                source text not null default 'live',
                label text,
                created_at text not null
            );

            create table if not exists signal_pool (
                id integer primary key autoincrement,
                run_id integer not null,
                trade_date text not null,
                mode text not null,
                profile text not null,
                ts_code text not null,
                name text,
                industry text,
                rank integer,
                score real,
                pool_type text,
                reason text,
                factor_json text,
                created_at text not null,
                foreign key(run_id) references signal_runs(run_id),
                unique(run_id, ts_code)
            );

            create table if not exists pool_state (
                id integer primary key autoincrement,
                mode text not null,
                profile text not null,
                ts_code text not null,
                name text,
                industry text,
                state text not null,
                first_seen_date text,
                last_seen_date text,
                removed_date text,
                entry_score real,
                latest_score real,
                highest_score real,
                days_in_pool integer not null default 1,
                last_reason text,
                updated_at text not null,
                unique(mode, profile, ts_code)
            );

            create table if not exists pool_events (
                id integer primary key autoincrement,
                event_date text not null,
                mode text not null,
                profile text not null,
                ts_code text not null,
                event_type text not null,
                old_state text,
                new_state text,
                old_score real,
                new_score real,
                message text,
                created_at text not null,
                unique(event_date, mode, profile, ts_code, event_type)
            );
            """
        )
        self.conn.commit()

    def record_run(
        self,
        trade_date: str,
        mode: str,
        profile: str,
        source: str = "live",
        label: str | None = None,
        run_date: str | None = None,
    ) -> int:
        now = _now()
        cur = self.conn.execute(
            """
            insert into signal_runs(run_date, trade_date, mode, profile, source, label, created_at)
            values(?, ?, ?, ?, ?, ?, ?)
            """,
            (run_date or trade_date, trade_date, mode, profile, source, label, now),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def update_pool(
        self,
        run_id: int,
        trade_date: str,
        mode: str,
        profile: str,
        records: list[SignalRecord],
    ) -> None:
        now = _now()
        normalized = _dedupe_records(records)
        current_codes = {record.ts_code for record in normalized}

        with self.conn:
            for record in normalized:
                self._insert_signal_pool(run_id, trade_date, mode, profile, record, now)
                self._upsert_active_state(trade_date, mode, profile, record, now)

            active_rows = self.conn.execute(
                """
                select * from pool_state
                where mode = ? and profile = ? and state = 'active'
                """,
                (mode, profile),
            ).fetchall()
            for row in active_rows:
                if row["ts_code"] not in current_codes:
                    self._remove_state(trade_date, mode, profile, row, now)

    def _insert_signal_pool(
        self,
        run_id: int,
        trade_date: str,
        mode: str,
        profile: str,
        record: SignalRecord,
        now: str,
    ) -> None:
        self.conn.execute(
            """
            insert or ignore into signal_pool(
                run_id, trade_date, mode, profile, ts_code, name, industry,
                rank, score, pool_type, reason, factor_json, created_at
            )
            values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                trade_date,
                mode,
                profile,
                record.ts_code,
                record.name,
                record.industry,
                record.rank,
                record.score,
                record.pool_type,
                record.reason,
                json.dumps(record.factors or {}, ensure_ascii=False, sort_keys=True),
                now,
            ),
        )

    def _upsert_active_state(
        self,
        trade_date: str,
        mode: str,
        profile: str,
        record: SignalRecord,
        now: str,
    ) -> None:
        existing = self.conn.execute(
            "select * from pool_state where mode = ? and profile = ? and ts_code = ?",
            (mode, profile, record.ts_code),
        ).fetchone()
        if existing is None or existing["state"] != "active":
            self.conn.execute(
                """
                insert into pool_state(
                    mode, profile, ts_code, name, industry, state,
                    first_seen_date, last_seen_date, removed_date,
                    entry_score, latest_score, highest_score, days_in_pool,
                    last_reason, updated_at
                )
                values(?, ?, ?, ?, ?, 'active', ?, ?, null, ?, ?, ?, 1, ?, ?)
                on conflict(mode, profile, ts_code) do update set
                    name = excluded.name,
                    industry = excluded.industry,
                    state = 'active',
                    first_seen_date = excluded.first_seen_date,
                    last_seen_date = excluded.last_seen_date,
                    removed_date = null,
                    entry_score = excluded.entry_score,
                    latest_score = excluded.latest_score,
                    highest_score = excluded.highest_score,
                    days_in_pool = 1,
                    last_reason = excluded.last_reason,
                    updated_at = excluded.updated_at
                """,
                (
                    mode,
                    profile,
                    record.ts_code,
                    record.name,
                    record.industry,
                    trade_date,
                    trade_date,
                    record.score,
                    record.score,
                    record.score,
                    record.reason,
                    now,
                ),
            )
            self._insert_event(
                event_date=trade_date,
                mode=mode,
                profile=profile,
                ts_code=record.ts_code,
                event_type="NEW",
                old_state=existing["state"] if existing else None,
                new_state="active",
                old_score=existing["latest_score"] if existing else None,
                new_score=record.score,
                message=f"{record.ts_code} 新进入 {mode}/{profile} 观察池",
                now=now,
            )
            return

        days_in_pool = self._count_pool_days(mode, profile, record.ts_code)
        highest_score = _max_score(existing["highest_score"], record.score)
        self.conn.execute(
            """
            update pool_state
            set name = ?, industry = ?, last_seen_date = ?, latest_score = ?,
                highest_score = ?, days_in_pool = ?, last_reason = ?, updated_at = ?
            where mode = ? and profile = ? and ts_code = ?
            """,
            (
                record.name,
                record.industry,
                trade_date,
                record.score,
                highest_score,
                days_in_pool,
                record.reason,
                now,
                mode,
                profile,
                record.ts_code,
            ),
        )

    def _remove_state(self, trade_date: str, mode: str, profile: str, row: sqlite3.Row, now: str) -> None:
        self.conn.execute(
            """
            update pool_state
            set state = 'removed', removed_date = ?, updated_at = ?
            where mode = ? and profile = ? and ts_code = ? and state = 'active'
            """,
            (trade_date, now, mode, profile, row["ts_code"]),
        )
        self._insert_event(
            event_date=trade_date,
            mode=mode,
            profile=profile,
            ts_code=row["ts_code"],
            event_type="REMOVED",
            old_state=row["state"],
            new_state="removed",
            old_score=row["latest_score"],
            new_score=None,
            message=f"{row['ts_code']} 移出 {mode}/{profile} 观察池",
            now=now,
        )

    def _insert_event(
        self,
        event_date: str,
        mode: str,
        profile: str,
        ts_code: str,
        event_type: str,
        old_state: str | None,
        new_state: str | None,
        old_score: float | None,
        new_score: float | None,
        message: str,
        now: str,
    ) -> None:
        self.conn.execute(
            """
            insert or ignore into pool_events(
                event_date, mode, profile, ts_code, event_type,
                old_state, new_state, old_score, new_score, message, created_at
            )
            values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (event_date, mode, profile, ts_code, event_type, old_state, new_state, old_score, new_score, message, now),
        )

    def _count_pool_days(self, mode: str, profile: str, ts_code: str) -> int:
        row = self.conn.execute(
            """
            select count(distinct trade_date) as cnt
            from signal_pool
            where mode = ? and profile = ? and ts_code = ?
            """,
            (mode, profile, ts_code),
        ).fetchone()
        return int(row["cnt"] or 1)


def _dedupe_records(records: list[SignalRecord]) -> list[SignalRecord]:
    deduped: dict[str, SignalRecord] = {}
    for record in records:
        deduped[record.ts_code] = record
    return list(deduped.values())


def _max_score(old_score: float | None, new_score: float | None) -> float | None:
    scores = [s for s in [old_score, new_score] if s is not None]
    return max(scores) if scores else None


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
