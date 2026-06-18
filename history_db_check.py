#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Inspect stock_history.db coverage and basic health."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from history_store import DEFAULT_HISTORY_DB_PATH, TABLE_COLUMNS


DATE_COLUMNS = {
    "stock_daily": "trade_date",
    "stock_daily_basic": "trade_date",
    "stock_moneyflow": "trade_date",
    "index_daily": "trade_date",
    "fina_indicator": "ann_date",
    "income": "ann_date",
}


def check_history_db(db_path: str | Path = DEFAULT_HISTORY_DB_PATH) -> dict:
    db_path = Path(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        tables = {}
        for table in TABLE_COLUMNS:
            if not _table_exists(conn, table):
                tables[table] = {"exists": False, "rows": 0, "min_date": None, "max_date": None}
                continue
            rows = conn.execute(f"select count(*) as n from {table}").fetchone()["n"]
            info = {"exists": True, "rows": int(rows), "min_date": None, "max_date": None}
            date_col = DATE_COLUMNS.get(table)
            if date_col:
                row = conn.execute(
                    f"select min({date_col}) as min_date, max({date_col}) as max_date from {table}"
                ).fetchone()
                info["min_date"] = row["min_date"]
                info["max_date"] = row["max_date"]
            tables[table] = info

        latest_trade_date = _latest_date(tables, "stock_daily")
        stock_count = _count_distinct(conn, "stock_basic", "ts_code") if tables["stock_basic"]["exists"] else 0
        daily_stock_count = (
            _count_distinct_where(conn, "stock_daily", "ts_code", "trade_date", latest_trade_date)
            if latest_trade_date
            else 0
        )
        return {
            "db_path": str(db_path),
            "tables": tables,
            "latest_trade_date": latest_trade_date,
            "stock_count": stock_count,
            "latest_daily_stock_count": daily_stock_count,
        }
    finally:
        conn.close()


def format_check_report(result: dict) -> str:
    lines = [
        "# 历史数据库体检",
        "",
        f"- 数据库：`{result['db_path']}`",
        f"- 最新交易日：`{result.get('latest_trade_date') or 'NA'}`",
        f"- 股票基础数量：`{result.get('stock_count', 0)}`",
        f"- 最新交易日日线股票数：`{result.get('latest_daily_stock_count', 0)}`",
        "",
        "## 表覆盖",
    ]
    for table, info in result["tables"].items():
        if not info["exists"]:
            lines.append(f"- `{table}`：缺失")
            continue
        date_range = ""
        if info.get("min_date") or info.get("max_date"):
            date_range = f" | {info.get('min_date') or 'NA'} → {info.get('max_date') or 'NA'}"
        lines.append(f"- `{table}`：{info['rows']} 行{date_range}")
    return "\n".join(lines)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "select 1 from sqlite_master where type = 'table' and name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _latest_date(tables: dict, table: str) -> str | None:
    info = tables.get(table) or {}
    return info.get("max_date")


def _count_distinct(conn: sqlite3.Connection, table: str, column: str) -> int:
    return int(conn.execute(f"select count(distinct {column}) as n from {table}").fetchone()["n"])


def _count_distinct_where(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    where_col: str,
    where_value: str,
) -> int:
    return int(
        conn.execute(
            f"select count(distinct {column}) as n from {table} where {where_col} = ?",
            (where_value,),
        ).fetchone()["n"]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Check stock_history.db coverage")
    parser.add_argument("--db", default=str(DEFAULT_HISTORY_DB_PATH), help="SQLite 历史数据库路径")
    args = parser.parse_args()
    print(format_check_report(check_history_db(args.db)))


if __name__ == "__main__":
    main()
