"""使用已落库行情结算短线信号的前向表现，不重新运行选股策略。"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from pathlib import Path


DEFAULT_SIGNAL_DB = Path("data/stock_signals.db")
DEFAULT_HISTORY_DB = Path("data/stock_history.db")


def _date_text(value) -> str:
    return str(value or "").replace("-", "")[:8]


def _number(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _pct(value: float, base: float) -> float:
    return round((value / base - 1) * 100, 2)


def _load_prices(history_db: Path, codes: list[str], start: str, end: str) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    conn = sqlite3.connect(history_db)
    conn.row_factory = sqlite3.Row
    try:
        for offset in range(0, len(codes), 500):
            chunk = codes[offset : offset + 500]
            placeholders = ",".join("?" for _ in chunk)
            rows = conn.execute(
                f"""
                select trade_date, ts_code, open, high, low, close
                from stock_daily
                where ts_code in ({placeholders})
                  and trade_date >= ?
                  and trade_date <= ?
                order by ts_code, trade_date
                """,
                [*chunk, start, end],
            ).fetchall()
            for row in rows:
                grouped[str(row["ts_code"])].append(dict(row))
    finally:
        conn.close()
    return grouped


def refresh_short_signal_outcomes(
    signal_db: Path = DEFAULT_SIGNAL_DB,
    history_db: Path = DEFAULT_HISTORY_DB,
    end_date: str | None = None,
) -> dict:
    end_text = _date_text(end_date) or "99991231"
    conn = sqlite3.connect(signal_db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            select p.id, p.trade_date, p.ts_code, p.factor_json
            from signal_pool p
            where p.mode = 'short'
            order by p.trade_date, p.id
            """
        ).fetchall()
        pending = []
        for row in rows:
            try:
                factors = json.loads(row["factor_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                factors = {}
            if factors.get("ret_5d") is None:
                pending.append((row, factors))

        if not pending:
            return {"pending": 0, "updated": 0, "matured": 0, "waiting": 0}

        codes = sorted({str(row["ts_code"]) for row, _ in pending})
        start_text = min(_date_text(row["trade_date"]) for row, _ in pending)
        prices = _load_prices(history_db, codes, start_text, end_text)
        updated = 0
        matured = 0

        with conn:
            for row, factors in pending:
                signal_date = _date_text(row["trade_date"])
                buy_date = _date_text(factors.get("buy_date"))
                available = prices.get(str(row["ts_code"]), [])
                if buy_date:
                    forward = [item for item in available if _date_text(item["trade_date"]) >= buy_date]
                else:
                    forward = [item for item in available if _date_text(item["trade_date"]) > signal_date]
                    if forward:
                        buy_date = _date_text(forward[0]["trade_date"])
                if not forward:
                    continue

                buy_open = _number(factors.get("buy_open")) or _number(forward[0].get("open"))
                if not buy_open or buy_open <= 0:
                    continue

                window = forward[:5]
                highs = [_number(item.get("high")) for item in window]
                lows = [_number(item.get("low")) for item in window]
                closes = [_number(item.get("close")) for item in window]
                highs = [value for value in highs if value is not None]
                lows = [value for value in lows if value is not None]
                closes = [value for value in closes if value is not None]
                if not closes:
                    continue

                factors["buy_date"] = buy_date
                factors["buy_open"] = round(buy_open, 4)
                factors["signal_window_days"] = len(window)
                factors["mfe_pct"] = _pct(max(highs), buy_open) if highs else None
                factors["mae_pct"] = _pct(min(lows), buy_open) if lows else None
                factors["best_close_pct"] = _pct(max(closes), buy_open)
                factors["worst_close_pct"] = _pct(min(closes), buy_open)
                factors["window_end_pct"] = _pct(closes[-1], buy_open)
                factors["hit_3pct"] = bool(factors["mfe_pct"] is not None and factors["mfe_pct"] >= 3)
                factors["hit_5pct"] = bool(factors["mfe_pct"] is not None and factors["mfe_pct"] >= 5)
                factors["hit_10pct"] = bool(factors["mfe_pct"] is not None and factors["mfe_pct"] >= 10)
                if len(window) >= 5:
                    factors["ret_5d"] = _pct(closes[4], buy_open)
                    matured += 1

                conn.execute(
                    "update signal_pool set factor_json = ? where id = ?",
                    (json.dumps(factors, ensure_ascii=False, sort_keys=True), int(row["id"])),
                )
                updated += 1

        return {
            "pending": len(pending),
            "updated": updated,
            "matured": matured,
            "waiting": len(pending) - matured,
        }
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="结算已存档短线信号的5日收益、MFE和MAE")
    parser.add_argument("--signal-db", type=Path, default=DEFAULT_SIGNAL_DB)
    parser.add_argument("--history-db", type=Path, default=DEFAULT_HISTORY_DB)
    parser.add_argument("--end", default=None, help="行情截止日 YYYYMMDD")
    args = parser.parse_args()
    summary = refresh_short_signal_outcomes(args.signal_db, args.history_db, args.end)
    print("短线信号到期结算：" + " ".join(f"{key}={value}" for key, value in summary.items()))


if __name__ == "__main__":
    main()
