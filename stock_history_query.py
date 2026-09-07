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


ASSET_TABLES = {
    "stock": ("stock_basic", "stock_daily"),
    "index": ("index_basic", "index_daily"),
    "fund": ("fund_basic", "fund_daily"),
}

ASSET_LABELS = {"stock": "股票", "index": "指数", "fund": "ETF/场内基金"}

INDEX_ALIASES = {
    "上证": "000001.SH",
    "上证指数": "000001.SH",
    "上证50": "000016.SH",
    "沪深300": "000300.SH",
    "科创50": "000688.SH",
    "中证500": "000905.SH",
    "中证1000": "000852.SH",
    "深证成指": "399001.SZ",
    "深证指数": "399001.SZ",
    "创业板指": "399006.SZ",
    "创业板指数": "399006.SZ",
}


def query_stock_history(
    code: str,
    history_db: str | Path = DEFAULT_HISTORY_DB_PATH,
    signal_db: str | Path | None = DEFAULT_SIGNAL_DB_PATH,
) -> dict:
    query = str(code).strip()
    conn = sqlite3.connect(history_db)
    conn.row_factory = sqlite3.Row
    try:
        instrument = _resolve_instrument(conn, query)
        ts_code = instrument["ts_code"]
        asset_type = instrument["asset_type"]
        daily_table = ASSET_TABLES[asset_type][1]
        daily_rows = conn.execute(
            f"""
            select trade_date, close, pct_chg from {daily_table}
            where ts_code = ?
            order by trade_date desc
            limit 120
            """,
            (ts_code,),
        ).fetchall()
        latest_daily = dict(daily_rows[0]) if daily_rows else {}
        latest_trade_date = latest_daily.get("trade_date")
        latest_basic = _query_latest_by_trade_date(conn, "stock_daily_basic", ts_code) if asset_type == "stock" else {}
        latest_moneyflow = _query_latest_by_trade_date(conn, "stock_moneyflow", ts_code) if asset_type == "stock" else {}
        latest_finance = _query_latest_finance(conn, ts_code) if asset_type == "stock" else {}
        returns = _calc_trailing_returns(daily_rows)
        price_history = _build_price_history(daily_rows)
    finally:
        conn.close()

    signal_state = _query_signal_state(ts_code, signal_db) if signal_db and asset_type == "stock" else {}
    found = bool(instrument.get("name") or latest_daily)
    return {
        "query": query,
        "found": found,
        "stock": instrument,
        "asset_type": asset_type,
        "asset_type_label": ASSET_LABELS[asset_type],
        "latest_daily": latest_daily,
        "latest_basic": latest_basic,
        "latest_moneyflow": latest_moneyflow,
        "latest_finance": latest_finance,
        "returns": returns,
        "price_history": price_history,
        "signal_state": signal_state,
        "latest_trade_date": latest_trade_date,
    }


def _build_price_history(desc_rows: list[sqlite3.Row]) -> list[dict]:
    """生成按日期正序排列的价格与均线序列，供页面只读展示。"""
    rows = [dict(row) for row in reversed(desc_rows)]
    closes = [_safe_float(row.get("close")) for row in rows]
    result = []
    for index, row in enumerate(rows):
        result.append(
            {
                "trade_date": row.get("trade_date"),
                "close": closes[index],
                "pct_chg": _safe_float(row.get("pct_chg")),
                "ma20": _rolling_average(closes, index, 20),
                "ma60": _rolling_average(closes, index, 60),
            }
        )
    return result


def _rolling_average(values: list[float | None], index: int, window: int) -> float | None:
    if index + 1 < window:
        return None
    scoped = values[index + 1 - window : index + 1]
    if any(value is None for value in scoped):
        return None
    return round(sum(scoped) / window, 4)


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


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "select 1 from sqlite_master where type = 'table' and name = ?",
        (table,),
    ).fetchone()
    return bool(row)


def _resolve_instrument(conn: sqlite3.Connection, query: str) -> dict:
    normalized = query.strip()
    alias_code = INDEX_ALIASES.get(normalized)
    candidates = [alias_code] if alias_code else []
    if _looks_like_stock_code(normalized):
        formatted = _format_code(normalized)
        candidates.append(formatted)
        # 纯数字代码存在交易所歧义时，同时检查另一市场，由真实基础表决定。
        if "." not in normalized and not normalized.upper().startswith(("SH", "SZ")):
            suffix = "SZ" if formatted.endswith(".SH") else "SH"
            candidates.append(f"{normalized}.{suffix}")

    for asset_type, (basic_table, _) in ASSET_TABLES.items():
        if not _table_exists(conn, basic_table):
            continue
        for ts_code in candidates:
            row = conn.execute(
                f"select * from {basic_table} where ts_code = ? limit 1",
                (ts_code,),
            ).fetchone()
            if row:
                return _instrument_from_row(dict(row), asset_type)

    if normalized:
        for asset_type, (basic_table, _) in ASSET_TABLES.items():
            if not _table_exists(conn, basic_table):
                continue
            order_sql = "order by list_status = 'L' desc, ts_code asc" if asset_type == "stock" else "order by ts_code asc"
            row = conn.execute(
                f"select * from {basic_table} where name = ? {order_sql} limit 1",
                (normalized,),
            ).fetchone()
            if not row:
                row = conn.execute(
                    f"select * from {basic_table} where name like ? {order_sql} limit 1",
                    (f"%{normalized}%",),
                ).fetchone()
            if row:
                return _instrument_from_row(dict(row), asset_type)

    ts_code = alias_code or _format_code(normalized)
    asset_type = "index" if alias_code else "stock"
    return _instrument_from_row({"ts_code": ts_code, "name": ""}, asset_type)


def _instrument_from_row(row: dict, asset_type: str) -> dict:
    result = dict(row)
    result["asset_type"] = asset_type
    result["asset_type_label"] = ASSET_LABELS[asset_type]
    if asset_type == "index":
        result["industry"] = result.get("category") or "市场指数"
    elif asset_type == "fund":
        result["industry"] = result.get("fund_type") or "场内基金"
    else:
        result.setdefault("industry", "")
    return result


def _resolve_ts_code(conn: sqlite3.Connection, query: str) -> str:
    return _resolve_instrument(conn, query)["ts_code"]


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
    if code.startswith(("5", "6", "9")):
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
