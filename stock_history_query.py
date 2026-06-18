#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Query one stock from history and signal databases."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

from history_store import DEFAULT_HISTORY_DB_PATH
from signal_store import DEFAULT_DB_PATH as DEFAULT_SIGNAL_DB_PATH


def query_stock_history(
    code: str,
    history_db: str | Path = DEFAULT_HISTORY_DB_PATH,
    signal_db: str | Path | None = DEFAULT_SIGNAL_DB_PATH,
) -> dict:
    query = str(code).strip()
    conn = sqlite3.connect(history_db)
    conn.row_factory = sqlite3.Row
    try:
        ts_code = _resolve_ts_code(conn, query)
        stock = _query_stock_basic(conn, ts_code)
        daily_rows = conn.execute(
            """
            select trade_date, close, pct_chg from stock_daily
            where ts_code = ?
            order by trade_date desc
            limit 90
            """,
            (ts_code,),
        ).fetchall()
        latest_daily = dict(daily_rows[0]) if daily_rows else {}
        latest_trade_date = latest_daily.get("trade_date")
        latest_basic = _query_latest_by_trade_date(conn, "stock_daily_basic", ts_code)
        latest_moneyflow = _query_latest_by_trade_date(conn, "stock_moneyflow", ts_code)
        latest_finance = _query_latest_finance(conn, ts_code)
        returns = _calc_trailing_returns(daily_rows)
    finally:
        conn.close()

    signal_state = _query_signal_state(ts_code, signal_db) if signal_db else {}
    found = bool((stock and stock.get("name")) or latest_daily)
    return {
        "query": query,
        "found": found,
        "stock": stock or {"ts_code": ts_code, "name": "", "industry": ""},
        "latest_daily": latest_daily,
        "latest_basic": latest_basic,
        "latest_moneyflow": latest_moneyflow,
        "latest_finance": latest_finance,
        "returns": returns,
        "signal_state": signal_state,
        "latest_trade_date": latest_trade_date,
    }


def format_stock_report(result: dict) -> str:
    stock = result["stock"]
    latest = result.get("latest_daily") or {}
    basic = result.get("latest_basic") or {}
    moneyflow = result.get("latest_moneyflow") or {}
    finance = result.get("latest_finance") or {}
    returns = result.get("returns") or {}
    signal = result.get("signal_state") or {}

    lines = [
        f"# 股票历史查询 {stock.get('ts_code', '')} {stock.get('name', '')}",
        "",
        f"- 行业：{stock.get('industry') or '-'}",
        f"- 最新交易日：{result.get('latest_trade_date') or '-'}",
        f"- 最新收盘：{_fmt(latest.get('close'))} 元",
        f"- 近10日：{_fmt_pct(returns.get('10d'))}，近40日：{_fmt_pct(returns.get('40d'))}，近80日：{_fmt_pct(returns.get('80d'))}",
        f"- 估值：PE(TTM) {_fmt(basic.get('pe_ttm'))}，PB {_fmt(basic.get('pb'))}，总市值 {_fmt_mv(basic.get('total_mv'))}",
        f"- 活跃度：换手率 {_fmt_pct(basic.get('turnover_rate'))}，量比 {_fmt(basic.get('volume_ratio'))}",
        f"- 资金流：主力净流入 {_fmt_money(moneyflow.get('net_mf_amount'))}",
        f"- 财务：ROE {_fmt_pct(finance.get('roe'))}，净利润同比 {_fmt_pct(finance.get('netprofit_yoy'))}，负债率 {_fmt_pct(finance.get('debt_to_assets'))}",
    ]
    if signal:
        lines.append(
            f"- 信号状态：{signal.get('mode', '-')}/{signal.get('profile', '-')} "
            f"{signal.get('state', '-')}，最新分 {_fmt(signal.get('latest_score'))}"
        )
    else:
        lines.append("- 信号状态：未在当前信号库观察池中")
    return "\n".join(lines)


def _query_stock_basic(conn: sqlite3.Connection, ts_code: str) -> dict:
    row = conn.execute("select * from stock_basic where ts_code = ?", (ts_code,)).fetchone()
    return dict(row) if row else {"ts_code": ts_code, "name": "", "industry": ""}


def _resolve_ts_code(conn: sqlite3.Connection, query: str) -> str:
    if _looks_like_stock_code(query):
        return _format_code(query)

    name = query.strip()
    row = conn.execute(
        """
        select ts_code from stock_basic
        where name = ? or symbol = ?
        order by list_status = 'L' desc, ts_code asc
        limit 1
        """,
        (name, name),
    ).fetchone()
    if row:
        return row["ts_code"]

    fuzzy = conn.execute(
        """
        select ts_code from stock_basic
        where name like ?
        order by list_status = 'L' desc, ts_code asc
        limit 1
        """,
        (f"%{name}%",),
    ).fetchone()
    if fuzzy:
        return fuzzy["ts_code"]
    return _format_code(query)


def _looks_like_stock_code(query: str) -> bool:
    q = query.strip().upper()
    if q.startswith(("SH", "SZ")) and q[2:].isdigit():
        return True
    if "." in q:
        left, right = q.split(".", 1)
        return left.isdigit() and right in ("SH", "SZ")
    return q.isdigit()


def _format_code(code: str) -> str:
    code = code.strip().upper()
    if code.startswith("SH") or code.startswith("SZ"):
        prefix = code[:2]
        code = code[2:]
        return f"{code}.{prefix}"
    if "." in code:
        return code
    if code.startswith(("6", "9")):
        return f"{code}.SH"
    return f"{code}.SZ"


def _query_latest_by_trade_date(conn: sqlite3.Connection, table: str, ts_code: str) -> dict:
    row = conn.execute(
        f"""
        select * from {table}
        where ts_code = ?
        order by trade_date desc
        limit 1
        """,
        (ts_code,),
    ).fetchone()
    return dict(row) if row else {}


def _query_latest_finance(conn: sqlite3.Connection, ts_code: str) -> dict:
    row = conn.execute(
        """
        select * from fina_indicator
        where ts_code = ?
        order by ann_date desc, end_date desc
        limit 1
        """,
        (ts_code,),
    ).fetchone()
    return dict(row) if row else {}


def _calc_trailing_returns(desc_rows: list[sqlite3.Row]) -> dict[str, float | None]:
    if not desc_rows:
        return {"10d": None, "40d": None, "80d": None}
    latest_close = _safe_float(desc_rows[0]["close"])
    result: dict[str, float | None] = {}
    for days in (10, 40, 80):
        if latest_close is None or len(desc_rows) <= days:
            result[f"{days}d"] = None
            continue
        base_close = _safe_float(desc_rows[days]["close"])
        if not base_close:
            result[f"{days}d"] = None
        else:
            result[f"{days}d"] = round((latest_close - base_close) / base_close * 100, 2)
    return result


def _query_signal_state(ts_code: str, signal_db: str | Path) -> dict:
    path = Path(signal_db)
    if not path.exists():
        return {}
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            """
            select * from pool_state
            where ts_code = ?
            order by updated_at desc
            limit 1
            """,
            (ts_code,),
        ).fetchone()
        return dict(row) if row else {}
    finally:
        conn.close()


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt(value: Any) -> str:
    val = _safe_float(value)
    return "-" if val is None else f"{val:.2f}"


def _fmt_pct(value: Any) -> str:
    val = _safe_float(value)
    return "-" if val is None else f"{val:+.2f}%"


def _fmt_money(value: Any) -> str:
    val = _safe_float(value)
    return "-" if val is None else f"{val:+.0f} 万元"


def _fmt_mv(value: Any) -> str:
    val = _safe_float(value)
    if val is None:
        return "-"
    return f"{val / 10000:.2f} 亿元"


def main() -> None:
    parser = argparse.ArgumentParser(description="Query one stock from local history database")
    parser.add_argument("code", help="股票代码，如 000001 / 000001.SZ / sh600000")
    parser.add_argument("--history-db", default=str(DEFAULT_HISTORY_DB_PATH), help="历史数据库路径")
    parser.add_argument("--signal-db", default=str(DEFAULT_SIGNAL_DB_PATH), help="信号数据库路径")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    result = query_stock_history(args.code, history_db=args.history_db, signal_db=args.signal_db)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_stock_report(result))


if __name__ == "__main__":
    main()
