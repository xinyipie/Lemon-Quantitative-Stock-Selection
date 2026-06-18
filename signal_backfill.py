#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Backfill historical strategy signals into stock_signals.db."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd

from signal_store import DEFAULT_DB_PATH


V9_PROFILE_NAMES = {
    "profile_v9_sector_quality_guard",
    "profile_v4_adaptive_quality_v9_sector_quality_guard",
}


def backfill_ic_short(
    source: str | Path,
    db_path: str | Path = DEFAULT_DB_PATH,
    profile: str = "short_v9",
    top: int = 3,
    dry_run: bool = False,
) -> dict:
    source = Path(source)
    df = pd.read_csv(source, encoding="utf-8-sig")
    required = {"select_date", "ts_code", "score"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{source} 缺少必要字段：{sorted(missing)}")

    total_rows = len(df)
    filtered = _filter_short_v9(df)
    skipped_profile_rows = total_rows - len(filtered)
    ranked = _select_topn_by_date(filtered, top=top)

    summary = {
        "source": str(source),
        "mode": "short",
        "profile": profile,
        "top": top,
        "total_rows": total_rows,
        "matched_rows": len(filtered),
        "skipped_profile_rows": skipped_profile_rows,
        "import_rows": len(ranked),
        "date_start": str(ranked["select_date"].min()) if not ranked.empty else None,
        "date_end": str(ranked["select_date"].max()) if not ranked.empty else None,
        "dry_run": dry_run,
    }
    if dry_run or ranked.empty:
        return summary

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        _ensure_signal_schema(conn)
        _write_ranked_signals(conn, ranked, source=source, profile=profile, top=top)
    finally:
        conn.close()
    return summary


def _filter_short_v9(df: pd.DataFrame) -> pd.DataFrame:
    if "factor_profile" not in df.columns:
        return df.copy()
    profiles = df["factor_profile"].astype(str)
    return df[profiles.isin(V9_PROFILE_NAMES)].copy()


def _select_topn_by_date(df: pd.DataFrame, top: int) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    work = df.copy()
    work["select_date"] = work["select_date"].astype(str).str.replace("-", "", regex=False).str[:8]
    work["score"] = pd.to_numeric(work["score"], errors="coerce").fillna(-999999)
    work = work.sort_values(["select_date", "score", "ts_code"], ascending=[True, False, True])
    work["rank"] = work.groupby("select_date").cumcount() + 1
    return work[work["rank"] <= top].reset_index(drop=True)


def _ensure_signal_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
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

        """
    )
    conn.commit()


def _write_ranked_signals(
    conn: sqlite3.Connection,
    ranked: pd.DataFrame,
    source: Path,
    profile: str,
    top: int,
) -> None:
    created_at = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
    label = f"backfill:{source.name}:top{top}"
    with conn:
        for select_date, group in ranked.groupby("select_date", sort=True):
            run_id = _get_or_create_run(
                conn,
                trade_date=str(select_date),
                profile=profile,
                source="backtest_ic_short",
                label=label,
                created_at=created_at,
            )
            for _, row in group.iterrows():
                conn.execute(
                    """
                    insert into signal_pool(
                        run_id, trade_date, mode, profile, ts_code, name, industry,
                        rank, score, pool_type, reason, factor_json, created_at
                    )
                    values(?, ?, 'short', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    on conflict(run_id, ts_code) do update set
                        name = excluded.name,
                        industry = excluded.industry,
                        rank = excluded.rank,
                        score = excluded.score,
                        pool_type = excluded.pool_type,
                        reason = excluded.reason,
                        factor_json = excluded.factor_json
                    """,
                    (
                        run_id,
                        str(select_date),
                        profile,
                        str(row.get("ts_code", "")),
                        str(row.get("name", "")) if "name" in row.index and pd.notna(row.get("name")) else "",
                        str(row.get("industry", "")) if pd.notna(row.get("industry")) else "",
                        int(row.get("rank")),
                        _safe_float(row.get("score")),
                        f"top{top}",
                        _build_reason(row),
                        json.dumps(_factor_payload(row), ensure_ascii=False, sort_keys=True),
                        created_at,
                    ),
                )


def _get_or_create_run(
    conn: sqlite3.Connection,
    trade_date: str,
    profile: str,
    source: str,
    label: str,
    created_at: str,
) -> int:
    existing = conn.execute(
        """
        select run_id from signal_runs
        where trade_date = ? and mode = 'short' and profile = ? and source = ? and label = ?
        """,
        (trade_date, profile, source, label),
    ).fetchone()
    if existing:
        return int(existing["run_id"])
    cur = conn.execute(
        """
        insert into signal_runs(run_date, trade_date, mode, profile, source, label, created_at)
        values(?, ?, 'short', ?, ?, ?, ?)
        """,
        (trade_date, trade_date, profile, source, label, created_at),
    )
    return int(cur.lastrowid)


def _build_reason(row: pd.Series) -> str:
    parts = [
        f"短线v9 Top{int(row.get('rank', 0))}",
        f"score={_safe_float(row.get('score')):.2f}" if _safe_float(row.get("score")) is not None else "",
    ]
    if "ret_5d" in row.index and pd.notna(row.get("ret_5d")):
        parts.append(f"5日={_safe_float(row.get('ret_5d')):+.2f}%")
    if "mfe_pct" in row.index and pd.notna(row.get("mfe_pct")):
        parts.append(f"MFE={_safe_float(row.get('mfe_pct')):+.2f}%")
    return " | ".join([p for p in parts if p])


def _factor_payload(row: pd.Series) -> dict[str, Any]:
    keep_cols = [
        "buy_date", "original_score", "factor_profile", "style_gate",
        "select_close", "buy_open", "signal_target_price", "signal_stop_price",
        "factor_volume_ratio", "factor_drawdown", "factor_inflow",
        "factor_turnover", "factor_sector", "factor_pattern",
        "factor_counter_trend", "factor_wyckoff", "change", "volume_ratio",
        "drawdown_from_high", "turnover", "market_style", "macro_mode",
        "signal_window_days", "mfe_pct", "mae_pct", "best_close_pct",
        "worst_close_pct", "window_end_pct", "hit_3pct", "hit_5pct",
        "hit_10pct", "ret_5d", "ret_10d", "ret_20d",
    ]
    payload = {}
    for col in keep_cols:
        if col in row.index and pd.notna(row.get(col)):
            value = row.get(col)
            payload[col] = value.item() if hasattr(value, "item") else value
    return payload


def _safe_float(value) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill historical signals into stock_signals.db")
    parser.add_argument("--source", required=True, help="ic_short CSV 文件路径")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="stock_signals.db 路径")
    parser.add_argument("--mode", default="short", choices=["short"], help="当前仅支持 short")
    parser.add_argument("--profile", default="short_v9", help="写入 signal_runs/profile 的名称")
    parser.add_argument("--top", type=int, default=3, help="每个 select_date 导入 TopN")
    parser.add_argument("--dry-run", action="store_true", help="只统计不写入")
    args = parser.parse_args()

    summary = backfill_ic_short(
        args.source,
        db_path=args.db,
        profile=args.profile,
        top=args.top,
        dry_run=args.dry_run,
    )
    print("signal backfill summary:")
    for key, value in summary.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
