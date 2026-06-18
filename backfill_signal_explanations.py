#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Backfill cached AI explanation documents for stored signal records."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from history_store import DEFAULT_HISTORY_DB_PATH
from signal_store import DEFAULT_DB_PATH
from web_app.services.explanation_service import get_or_create_signal_explanation


def collect_signal_targets(
    signal_db: str | Path = DEFAULT_DB_PATH,
    start: str | None = None,
    end: str | None = None,
    mode: str | None = None,
    profile: str | None = None,
    source: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    path = Path(signal_db)
    if not path.exists():
        return []
    filters = []
    params: list = []
    if start:
        filters.append("p.trade_date >= ?")
        params.append(_date_text(start))
    if end:
        filters.append("p.trade_date <= ?")
        params.append(_date_text(end))
    if mode:
        filters.append("p.mode = ?")
        params.append(mode)
    if profile:
        filters.append("p.profile = ?")
        params.append(profile)
    if source:
        filters.append("r.source = ?")
        params.append(source)
    where_sql = "where " + " and ".join(filters) if filters else ""
    limit_sql = "limit ?" if limit and limit > 0 else ""
    if limit_sql:
        params.append(int(limit))
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            f"""
            select p.trade_date, p.ts_code
            from signal_pool p
            left join signal_runs r on r.run_id = p.run_id
            {where_sql}
            group by p.trade_date, p.ts_code
            order by p.trade_date desc, p.rank asc, p.ts_code asc
            {limit_sql}
            """,
            params,
        ).fetchall()
        return [{"trade_date": row["trade_date"], "ts_code": row["ts_code"]} for row in rows]
    finally:
        conn.close()


def backfill_explanations(
    targets: list[dict],
    signal_db: str | Path = DEFAULT_DB_PATH,
    history_db: str | Path | None = DEFAULT_HISTORY_DB_PATH,
    force: bool = False,
) -> dict:
    stats = {"total": len(targets), "cache": 0, "ai": 0, "fallback": 0, "not_found": 0}
    for target in targets:
        result = get_or_create_signal_explanation(
            target["trade_date"],
            target["ts_code"],
            signal_db=signal_db,
            history_db=history_db,
            force=force,
        )
        source = result.get("source") or "not_found"
        stats[source] = stats.get(source, 0) + 1
        print(f"{target['trade_date']} {target['ts_code']} -> {source}")
    return stats


def _date_text(value: str) -> str:
    return str(value or "").replace("-", "")[:8]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="批量生成并缓存短线/长线信号AI解释文档")
    parser.add_argument("--signal-db", default=str(DEFAULT_DB_PATH), help="信号数据库路径")
    parser.add_argument("--history-db", default=str(DEFAULT_HISTORY_DB_PATH), help="历史行情数据库路径")
    parser.add_argument("--start", default="", help="开始日期，例如 20260501")
    parser.add_argument("--end", default="", help="结束日期，例如 20260618")
    parser.add_argument("--mode", default="short", help="信号模式：short 或 longterm")
    parser.add_argument("--profile", default="", help="策略名，可留空")
    parser.add_argument("--source", default="", help="来源：live/backtest_ic_short，可留空")
    parser.add_argument("--limit", type=int, default=0, help="最多生成多少条，0 表示不限")
    parser.add_argument("--force", action="store_true", help="忽略缓存，强制重新生成")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    targets = collect_signal_targets(
        args.signal_db,
        start=args.start or None,
        end=args.end or None,
        mode=args.mode or None,
        profile=args.profile or None,
        source=args.source or None,
        limit=args.limit or None,
    )
    print(f"待处理信号：{len(targets)} 条")
    stats = backfill_explanations(
        targets,
        signal_db=args.signal_db,
        history_db=args.history_db,
        force=args.force,
    )
    print(
        "完成："
        f"total={stats.get('total', 0)} "
        f"cache={stats.get('cache', 0)} "
        f"ai={stats.get('ai', 0)} "
        f"fallback={stats.get('fallback', 0)} "
        f"not_found={stats.get('not_found', 0)}"
    )


if __name__ == "__main__":
    main()
