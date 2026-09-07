from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path


def attach_history_price_context(
    items: list[dict], history_db: str | Path | None, *, signal_date_key: str
) -> None:
    """批量补充 T+1 基准价、最新价和当前浮盈亏，不改变既有复盘收益。"""
    if not items or not history_db or not Path(history_db).exists():
        return
    valid_items = [item for item in items if item.get("ts_code") and item.get(signal_date_key)]
    if not valid_items:
        return

    codes = sorted({str(item["ts_code"]) for item in valid_items})
    signal_dates = [str(item[signal_date_key]).replace("-", "") for item in valid_items]
    query_start = _shift_date(min(signal_dates), days=-10)
    placeholders = ",".join("?" for _ in codes)
    conn = sqlite3.connect(history_db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            f"""
            select ts_code, trade_date, open, high, low, close
            from stock_daily
            where ts_code in ({placeholders}) and trade_date >= ?
            order by ts_code asc, trade_date asc
            """,
            [*codes, query_start],
        ).fetchall()
    finally:
        conn.close()

    paths: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        paths[str(row["ts_code"])].append(dict(row))

    for item in valid_items:
        signal_date = str(item[signal_date_key]).replace("-", "")
        path = paths.get(str(item["ts_code"])) or []
        recommendation_row = None
        entry_row = None
        for row in path:
            trade_date = str(row.get("trade_date") or "")
            if trade_date <= signal_date:
                recommendation_row = row
            elif entry_row is None:
                entry_row = row

        latest_row = path[-1] if path else None
        entry_price = _num(entry_row.get("open")) if entry_row else None
        entry_source = "T+1开盘"
        entry_date = entry_row.get("trade_date") if entry_row else None
        entry_is_fallback = False
        if entry_price is None and recommendation_row:
            entry_price = _num(recommendation_row.get("close"))
            entry_source = "推荐日收盘回退"
            entry_date = recommendation_row.get("trade_date")
            entry_is_fallback = entry_price is not None

        latest_price = _num(latest_row.get("close")) if latest_row else None
        current_return = None
        if entry_price and latest_price is not None:
            current_return = (latest_price - entry_price) / entry_price * 100

        peak_start_date = str(entry_date or signal_date)
        peak_candidates = [
            row
            for row in path
            if str(row.get("trade_date") or "") >= peak_start_date and _num(row.get("high")) is not None
        ]
        peak_row = max(peak_candidates, key=lambda row: _num(row.get("high")) or 0) if peak_candidates else None
        peak_price = _num(peak_row.get("high")) if peak_row else None
        peak_return = None
        if entry_price and peak_price is not None:
            peak_return = (peak_price - entry_price) / entry_price * 100
        trough_candidates = [
            row
            for row in path
            if str(row.get("trade_date") or "") >= peak_start_date and _num(row.get("low")) is not None
        ]
        trough_row = min(trough_candidates, key=lambda row: _num(row.get("low")) or float("inf")) if trough_candidates else None
        trough_price = _num(trough_row.get("low")) if trough_row else None
        trough_return = None
        if entry_price and trough_price is not None:
            trough_return = (trough_price - entry_price) / entry_price * 100

        item["history_entry_price"] = entry_price
        item["history_entry_price_text"] = _price_text(entry_price)
        item["history_entry_date"] = entry_date
        item["history_entry_source"] = entry_source if entry_price is not None else "暂无行情"
        item["history_entry_is_fallback"] = entry_is_fallback
        item["history_latest_price"] = latest_price
        item["history_latest_price_text"] = _price_text(latest_price)
        item["history_latest_date"] = latest_row.get("trade_date") if latest_row else None
        item["history_current_return"] = current_return
        item["history_current_return_text"] = _pct_text(current_return)
        item["history_current_return_tone"] = _pct_tone(current_return)
        item["history_peak_price"] = peak_price
        item["history_peak_price_text"] = _price_text(peak_price)
        item["history_peak_date"] = peak_row.get("trade_date") if peak_row else None
        item["history_peak_return"] = peak_return
        item["history_peak_return_text"] = _pct_text(peak_return)
        item["history_peak_return_tone"] = _pct_tone(peak_return)
        item["history_trough_price"] = trough_price
        item["history_trough_price_text"] = _price_text(trough_price)
        item["history_trough_date"] = trough_row.get("trade_date") if trough_row else None
        item["history_trough_return"] = trough_return
        item["history_trough_return_text"] = _pct_text(trough_return)
        item["history_trough_return_tone"] = _pct_tone(trough_return)
        entry_index = path.index(entry_row) if entry_row in path else None
        for horizon in (3, 8):
            target_index = entry_index + horizon - 1 if entry_index is not None else None
            target_row = path[target_index] if target_index is not None and target_index < len(path) else None
            target_close = _num(target_row.get("close")) if target_row else None
            horizon_return = None
            if entry_price and target_close is not None:
                horizon_return = (target_close - entry_price) / entry_price * 100
            item[f"history_ret_{horizon}d"] = horizon_return
            item[f"history_ret_{horizon}d_text"] = (
                f"{horizon}日{horizon_return:+.2f}%" if horizon_return is not None else f"待满{horizon}日"
            )
            item[f"history_ret_{horizon}d_date"] = target_row.get("trade_date") if target_row else None
            item[f"history_ret_{horizon}d_tone"] = _pct_tone(horizon_return)


def _shift_date(value: str, *, days: int) -> str:
    try:
        return (datetime.strptime(value, "%Y%m%d") + timedelta(days=days)).strftime("%Y%m%d")
    except (TypeError, ValueError):
        return value


def _num(value) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _price_text(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def _pct_text(value: float | None) -> str:
    return "暂无对比" if value is None else f"{value:+.2f}%"


def _pct_tone(value: float | None) -> str:
    if value is None or value == 0:
        return "muted"
    return "market-up" if value > 0 else "market-down"
