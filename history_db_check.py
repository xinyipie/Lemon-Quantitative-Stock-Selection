#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Inspect stock_history.db coverage and basic health."""

from __future__ import annotations

import argparse
import sqlite3
from statistics import median
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
        daily_coverage = (
            _latest_daily_coverage(conn, latest_trade_date)
            if latest_trade_date and tables["stock_daily"]["exists"]
            else {"latest_count": daily_stock_count, "recent_median": None, "coverage_ratio": None, "status_label": "OK"}
        )
        _attach_table_status_labels(tables, latest_trade_date)
        if daily_coverage.get("status_label") == "覆盖不足":
            tables["stock_daily"]["status_label"] = "覆盖不足"
            tables["stock_daily"]["status_tone"] = "warn"
            tables["stock_daily"]["coverage_ratio"] = daily_coverage.get("coverage_ratio")
            tables["stock_daily"]["recent_median_count"] = daily_coverage.get("recent_median")
        return {
            "db_path": str(db_path),
            "tables": tables,
            "latest_trade_date": latest_trade_date,
            "stock_count": stock_count,
            "latest_daily_stock_count": daily_stock_count,
            "daily_coverage": daily_coverage,
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


def _attach_table_status_labels(tables: dict, latest_trade_date: str | None) -> None:
    same_day_tables = {"stock_daily", "stock_daily_basic", "stock_moneyflow", "index_daily"}
    for table, info in tables.items():
        if not info.get("exists"):
            info["status_label"] = "缺失"
            info["status_tone"] = "bad"
            continue
        if int(info.get("rows") or 0) <= 0:
            info["status_label"] = "空表"
            info["status_tone"] = "bad"
            continue
        max_date = info.get("max_date")
        if table in same_day_tables and latest_trade_date and max_date and str(max_date) < str(latest_trade_date):
            info["status_label"] = "滞后"
            info["status_tone"] = "warn"
            continue
        info["status_label"] = "OK"
        info["status_tone"] = "ok"


def _latest_daily_coverage(conn: sqlite3.Connection, latest_trade_date: str) -> dict:
    rows = conn.execute(
        """
        select trade_date, count(distinct ts_code) as n
        from stock_daily
        where trade_date <= ?
        group by trade_date
        order by trade_date desc
        limit 21
        """,
        (latest_trade_date,),
    ).fetchall()
    counts = [(str(row["trade_date"]), int(row["n"] or 0)) for row in rows]
    latest_count = next((count for date, count in counts if date == str(latest_trade_date)), 0)
    previous_counts = [count for date, count in counts if date != str(latest_trade_date)]
    if not previous_counts:
        return {
            "latest_count": latest_count,
            "recent_median": None,
            "coverage_ratio": None,
            "status_label": "OK",
        }

    recent_median = float(median(previous_counts))
    coverage_ratio = latest_count / recent_median if recent_median > 0 else None
    status_label = "覆盖不足" if coverage_ratio is not None and coverage_ratio < 0.7 else "OK"
    return {
        "latest_count": latest_count,
        "recent_median": recent_median,
        "coverage_ratio": coverage_ratio,
        "status_label": status_label,
    }


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
