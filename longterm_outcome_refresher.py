#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""只刷新既有长线审计样本的收益路径，不重新生成历史候选。"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import pandas as pd

from history_store import DEFAULT_HISTORY_DB_PATH
from longterm_pool_quality_audit import calculate_forward_quality
from signal_store import DEFAULT_DB_PATH


def refresh_longterm_outcomes(
    signal_db: str | Path = DEFAULT_DB_PATH,
    history_db: str | Path = DEFAULT_HISTORY_DB_PATH,
) -> dict[str, int]:
    signal_path = Path(signal_db)
    history_path = Path(history_db)
    if not signal_path.exists() or not history_path.exists():
        return {"samples": 0, "updated": 0, "matured_80d": 0}

    signal_conn = sqlite3.connect(signal_path)
    signal_conn.row_factory = sqlite3.Row
    try:
        samples = pd.read_sql_query(
            """
            select id, run_id, select_date, ts_code
            from longterm_audit_samples
            order by select_date, ts_code
            """,
            signal_conn,
        )
        if samples.empty:
            return {"samples": 0, "updated": 0, "matured_80d": 0}

        daily = _load_price_history(history_path, samples)
        calculated = calculate_forward_quality(samples, daily, horizons=[10, 40, 80])
        if calculated.empty:
            return {"samples": len(samples), "updated": 0, "matured_80d": 0}

        updated = 0
        matured_80d = 0
        with signal_conn:
            for row in calculated.to_dict("records"):
                values = (
                    _num(row.get("ret_10d")),
                    _num(row.get("ret_40d")),
                    _num(row.get("ret_80d")),
                    _num(row.get("mfe_80d")),
                    _num(row.get("mae_80d")),
                    _num(row.get("benchmark_ret_80d")),
                    _num(row.get("excess_ret_80d")),
                    _bool_int(row.get("outperform_80d")),
                    int(row["id"]),
                )
                signal_conn.execute(
                    """
                    update longterm_audit_samples
                    set ret_10d = coalesce(?, ret_10d),
                        ret_40d = coalesce(?, ret_40d),
                        ret_80d = coalesce(?, ret_80d),
                        mfe_80d = coalesce(?, mfe_80d),
                        mae_80d = coalesce(?, mae_80d),
                        benchmark_ret_80d = coalesce(?, benchmark_ret_80d),
                        excess_ret_80d = coalesce(?, excess_ret_80d),
                        outperform_80d = coalesce(?, outperform_80d)
                    where id = ?
                    """,
                    values,
                )
                updated += 1
                if values[2] is not None:
                    matured_80d += 1
            _refresh_run_summaries(signal_conn)
        return {"samples": len(samples), "updated": updated, "matured_80d": matured_80d}
    finally:
        signal_conn.close()


def _load_price_history(history_db: Path, samples: pd.DataFrame) -> pd.DataFrame:
    codes = sorted(set(samples["ts_code"].dropna().astype(str)))
    start_date = str(samples["select_date"].min())
    history_conn = sqlite3.connect(history_db)
    try:
        frames = []
        for offset in range(0, len(codes), 500):
            batch = codes[offset : offset + 500]
            placeholders = ",".join("?" for _ in batch)
            frames.append(
                pd.read_sql_query(
                    f"""
                    select trade_date, ts_code, close, high, low
                    from stock_daily
                    where ts_code in ({placeholders}) and trade_date >= ?
                    """,
                    history_conn,
                    params=[*batch, start_date],
                )
            )
        benchmark = pd.read_sql_query(
            """
            select trade_date, ts_code, close, high, low
            from index_daily
            where ts_code = '000300.SH' and trade_date >= ?
            """,
            history_conn,
            params=[start_date],
        )
        frames.append(benchmark)
        return pd.concat([frame for frame in frames if not frame.empty], ignore_index=True)
    finally:
        history_conn.close()


def _refresh_run_summaries(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        update longterm_audit_runs
        set sample_count = (select count(*) from longterm_audit_samples s where s.run_id = longterm_audit_runs.id),
            date_start = (select min(select_date) from longterm_audit_samples s where s.run_id = longterm_audit_runs.id),
            date_end = (select max(select_date) from longterm_audit_samples s where s.run_id = longterm_audit_runs.id),
            avg_ret_10d = (select avg(ret_10d) from longterm_audit_samples s where s.run_id = longterm_audit_runs.id),
            avg_ret_40d = (select avg(ret_40d) from longterm_audit_samples s where s.run_id = longterm_audit_runs.id),
            avg_ret_80d = (select avg(ret_80d) from longterm_audit_samples s where s.run_id = longterm_audit_runs.id),
            win_rate_80d = (select avg(case when ret_80d is not null then ret_80d > 0 end) from longterm_audit_samples s where s.run_id = longterm_audit_runs.id),
            outperform_rate_80d = (select avg(outperform_80d) from longterm_audit_samples s where s.run_id = longterm_audit_runs.id)
        """
    )


def _num(value):
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _bool_int(value):
    if value is None or pd.isna(value):
        return None
    return int(bool(value))


def main() -> None:
    parser = argparse.ArgumentParser(description="刷新既有长线样本的未来收益路径")
    parser.add_argument("--signal-db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--history-db", default=str(DEFAULT_HISTORY_DB_PATH))
    args = parser.parse_args()
    print(refresh_longterm_outcomes(args.signal_db, args.history_db))


if __name__ == "__main__":
    main()
