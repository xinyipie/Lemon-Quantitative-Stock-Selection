#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Import historical long-term pool audit CSVs into the signal database."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from signal_store import DEFAULT_DB_PATH


KEY_COLUMNS = {
    "select_date",
    "ts_code",
    "code",
    "name",
    "industry",
    "longterm_profile",
    "pool_type",
    "regime",
    "longterm_score",
    "pool_rank_score",
    "industry_rs",
    "drawdown_from_high",
    "ret_10d",
    "ret_40d",
    "ret_80d",
    "mfe_80d",
    "mae_80d",
    "benchmark_ret_80d",
    "excess_ret_80d",
    "outperform_80d",
}


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        create table if not exists longterm_audit_runs (
            id integer primary key autoincrement,
            period text not null,
            profile text not null,
            source_file text not null unique,
            sample_count integer not null default 0,
            date_start text,
            date_end text,
            avg_ret_10d real,
            avg_ret_40d real,
            avg_ret_80d real,
            win_rate_80d real,
            outperform_rate_80d real,
            created_at text not null
        );

        create table if not exists longterm_audit_samples (
            id integer primary key autoincrement,
            run_id integer not null,
            select_date text not null,
            ts_code text not null,
            name text,
            industry text,
            profile text,
            pool_type text,
            regime text,
            score real,
            pool_rank_score real,
            industry_rs real,
            drawdown_from_high real,
            ret_10d real,
            ret_40d real,
            ret_80d real,
            mfe_80d real,
            mae_80d real,
            benchmark_ret_80d real,
            excess_ret_80d real,
            outperform_80d integer,
            factor_json text,
            created_at text not null,
            foreign key(run_id) references longterm_audit_runs(id),
            unique(run_id, select_date, ts_code)
        );
        """
    )
    conn.commit()


def import_longterm_audit_csv(csv_path: str | Path, db_path: str | Path = DEFAULT_DB_PATH) -> dict[str, Any]:
    path = Path(csv_path)
    db = Path(db_path)
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    try:
        init_schema(conn)
        df = _read_csv(path)
        period = _infer_period(path.name)
        profile = _infer_profile(df, path.name)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        summary = _build_summary(df)
        with conn:
            conn.execute("delete from longterm_audit_samples where run_id in (select id from longterm_audit_runs where source_file = ?)", (str(path),))
            conn.execute("delete from longterm_audit_runs where source_file = ?", (str(path),))
            cur = conn.execute(
                """
                insert into longterm_audit_runs(
                    period, profile, source_file, sample_count, date_start, date_end,
                    avg_ret_10d, avg_ret_40d, avg_ret_80d, win_rate_80d,
                    outperform_rate_80d, created_at
                )
                values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    period,
                    profile,
                    str(path),
                    len(df),
                    summary["date_start"],
                    summary["date_end"],
                    summary["avg_ret_10d"],
                    summary["avg_ret_40d"],
                    summary["avg_ret_80d"],
                    summary["win_rate_80d"],
                    summary["outperform_rate_80d"],
                    now,
                ),
            )
            run_id = int(cur.lastrowid)
            rows = [_sample_tuple(run_id, row, now) for _, row in df.iterrows()]
            conn.executemany(
                """
                insert or ignore into longterm_audit_samples(
                    run_id, select_date, ts_code, name, industry, profile, pool_type,
                    regime, score, pool_rank_score, industry_rs, drawdown_from_high,
                    ret_10d, ret_40d, ret_80d, mfe_80d, mae_80d,
                    benchmark_ret_80d, excess_ret_80d, outperform_80d,
                    factor_json, created_at
                )
                values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

        return {
            "source": str(path),
            "period": period,
            "profile": profile,
            "import_rows": len(df),
            **summary,
        }
    finally:
        conn.close()


def import_many(paths: list[Path], db_path: str | Path = DEFAULT_DB_PATH) -> list[dict[str, Any]]:
    results = []
    for path in paths:
        results.append(import_longterm_audit_csv(path, db_path))
    return results


def _read_csv(path: Path) -> pd.DataFrame:
    try:
        df = pd.read_csv(path, encoding="utf-8-sig")
    except pd.errors.EmptyDataError:
        df = pd.DataFrame()
    if df.empty:
        return pd.DataFrame(columns=sorted(KEY_COLUMNS))
    if "ts_code" not in df.columns and "code" in df.columns:
        df["ts_code"] = df["code"].map(_to_ts_code)
    df["select_date"] = df.get("select_date", "").astype(str).str.replace("-", "", regex=False).str[:8]
    df["ts_code"] = df["ts_code"].astype(str).map(_to_ts_code)
    return df


def _build_summary(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty:
        return {
            "date_start": None,
            "date_end": None,
            "avg_ret_10d": None,
            "avg_ret_40d": None,
            "avg_ret_80d": None,
            "win_rate_80d": None,
            "outperform_rate_80d": None,
        }
    ret80 = _series(df, "ret_80d")
    outperform = _bool_series(df, "outperform_80d")
    return {
        "date_start": str(df["select_date"].min()),
        "date_end": str(df["select_date"].max()),
        "avg_ret_10d": _mean(df, "ret_10d"),
        "avg_ret_40d": _mean(df, "ret_40d"),
        "avg_ret_80d": _mean(df, "ret_80d"),
        "win_rate_80d": float((ret80 > 0).mean()) if not ret80.empty else None,
        "outperform_rate_80d": float(outperform.mean()) if not outperform.empty else None,
    }


def _sample_tuple(run_id: int, row: pd.Series, now: str) -> tuple:
    factors = {key: _json_value(row.get(key)) for key in row.index if key not in KEY_COLUMNS}
    return (
        run_id,
        str(row.get("select_date") or ""),
        _to_ts_code(row.get("ts_code") or row.get("code") or ""),
        str(row.get("name") or ""),
        str(row.get("industry") or ""),
        str(row.get("longterm_profile") or ""),
        str(row.get("pool_type") or ""),
        str(row.get("regime") or ""),
        _num(row.get("longterm_score")),
        _num(row.get("pool_rank_score")),
        _num(row.get("industry_rs")),
        _num(row.get("drawdown_from_high")),
        _num(row.get("ret_10d")),
        _num(row.get("ret_40d")),
        _num(row.get("ret_80d")),
        _num(row.get("mfe_80d")),
        _num(row.get("mae_80d")),
        _num(row.get("benchmark_ret_80d")),
        _num(row.get("excess_ret_80d")),
        _bool_int(row.get("outperform_80d")),
        json.dumps(factors, ensure_ascii=False, sort_keys=True),
        now,
    )


def _infer_period(filename: str) -> str:
    match = re.search(r"(20\d{2}H[12]|20\d{2}Q[1-4]|20\d{2})", filename)
    return match.group(1) if match else "unknown"


def _infer_profile(df: pd.DataFrame, filename: str) -> str:
    if not df.empty and "longterm_profile" in df.columns:
        values = [str(v) for v in df["longterm_profile"].dropna().unique() if str(v)]
        if values:
            return values[0]
    marker = filename.replace("longterm_pool_quality_", "").replace(".csv", "")
    return marker


def _to_ts_code(value) -> str:
    text = str(value or "").strip()
    if not text or text.lower() == "nan":
        return ""
    if "." in text:
        code, suffix = text.split(".", 1)
        return f"{code.zfill(6)}.{suffix.upper()}"
    raw = text.split(".")[0].zfill(6)
    suffix = "SH" if raw.startswith(("6", "9")) else "SZ"
    return f"{raw}.{suffix}"


def _series(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(df[column], errors="coerce").dropna()


def _bool_series(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(dtype=float)
    return df[column].map(_bool_int).dropna().astype(float)


def _mean(df: pd.DataFrame, column: str) -> float | None:
    values = _series(df, column)
    if values.empty:
        return None
    return float(values.mean())


def _num(value) -> float | None:
    try:
        if pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _bool_int(value) -> int | None:
    if pd.isna(value):
        return None
    if isinstance(value, bool):
        return int(value)
    text = str(value).strip().lower()
    if text in {"true", "1", "yes"}:
        return 1
    if text in {"false", "0", "no"}:
        return 0
    return None


def _json_value(value):
    if pd.isna(value):
        return None
    if isinstance(value, (int, float, str, bool)):
        return value
    return str(value)


def main() -> None:
    parser = argparse.ArgumentParser(description="Import historical long-term pool audit CSVs")
    parser.add_argument("--source", nargs="+", required=True, help="CSV 文件或 glob，例如 reports/longterm_pool_quality_*v18*_full.csv")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="stock_signals.db 路径")
    args = parser.parse_args()

    paths: list[Path] = []
    for source in args.source:
        matched = sorted(Path().glob(source)) if any(ch in source for ch in "*?[]") else [Path(source)]
        paths.extend(matched)
    results = import_many(paths, args.db)
    print("longterm history import summary:")
    for result in results:
        print(
            f"  {Path(result['source']).name}: rows={result['import_rows']} "
            f"period={result['period']} avg80={result['avg_ret_80d']}"
        )


if __name__ == "__main__":
    main()
