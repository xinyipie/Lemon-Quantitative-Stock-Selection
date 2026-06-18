#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Audit longterm recommendation-pool lifecycle from pool-quality CSV files."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


DEFAULT_HORIZONS = [10, 40, 80]
DISPLAY_COLUMNS = [
    "first_select_date",
    "ts_code",
    "name",
    "industry",
    "appearances",
    "pool_type",
    "pool_rank_score",
    "winner_profile_score",
    "v8_timing_gate",
    "v8_timing_reasons",
    "market_admission",
    "market_admission_reasons",
    "v9_quality_floor",
    "v9_quality_reasons",
    "quality_rank_score",
    "risk_flags",
    "longterm_score",
    "ret_10d",
    "ret_40d",
    "ret_80d",
    "outperform_80d",
]


def _normalize_date(value) -> str:
    return str(value).replace("-", "")[:8]


def _fmt_pct(value) -> str:
    if pd.isna(value):
        return "NA"
    return f"{float(value):+.2f}%"


def _table(df: pd.DataFrame, max_rows: int = 40) -> str:
    if df.empty:
        return "无样本\n"
    return df.head(max_rows).to_markdown(index=False) + "\n"


def load_quality_csv(paths: list[str]) -> pd.DataFrame:
    frames = []
    for path in paths:
        p = Path(path)
        if not p.exists() or p.stat().st_size <= 5:
            continue
        try:
            data = pd.read_csv(p, encoding="utf-8-sig")
        except pd.errors.EmptyDataError:
            continue
        if data.empty:
            continue
        data["source_file"] = p.name
        frames.append(data)
    if not frames:
        return pd.DataFrame()
    data = pd.concat(frames, ignore_index=True)
    if "select_date" in data.columns:
        data["select_date"] = data["select_date"].astype(str).map(_normalize_date)
    for col in data.columns:
        if col.startswith(("ret_", "mfe_", "mae_", "benchmark_ret_", "excess_ret_")) or col in {
            "longterm_score",
            "price_vs_ma60",
            "drawdown_from_high",
            "industry_rs",
            "turnover",
            "volume_ratio",
            "roe",
            "debt_ratio",
            "netprofit_yoy",
            "pe_ttm",
            "pb",
            "ps_ttm",
        }:
            data[col] = pd.to_numeric(data[col], errors="coerce")
        elif col in {"quality_rank_score", "winner_profile_score"}:
            data[col] = pd.to_numeric(data[col], errors="coerce")
        elif col in {"pool_rank_score"}:
            data[col] = pd.to_numeric(data[col], errors="coerce")
    return data


def _score_column(df: pd.DataFrame) -> str:
    if "winner_profile_score" in df.columns and pd.to_numeric(df["winner_profile_score"], errors="coerce").notna().any():
        return "winner_profile_score"
    if "pool_rank_score" in df.columns and pd.to_numeric(df["pool_rank_score"], errors="coerce").notna().any():
        return "pool_rank_score"
    if "quality_rank_score" in df.columns and pd.to_numeric(df["quality_rank_score"], errors="coerce").notna().any():
        return "quality_rank_score"
    return "longterm_score"


def first_entry_table(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    data = df.copy()
    data["select_date"] = data["select_date"].astype(str).map(_normalize_date)
    score_col = _score_column(data)
    data = data.sort_values(["ts_code", "select_date", score_col], ascending=[True, True, False])
    first = data.drop_duplicates("ts_code", keep="first").copy()
    counts = data.groupby("ts_code").agg(
        appearances=("ts_code", "size"),
        last_select_date=("select_date", "max"),
    )
    first = first.merge(counts, left_on="ts_code", right_index=True, how="left")
    first = first.rename(columns={"select_date": "first_select_date"})
    first = first.sort_values(["first_select_date", score_col], ascending=[True, False]).reset_index(drop=True)
    return first


def lifecycle_entry_table(df: pd.DataFrame) -> pd.DataFrame:
    """Keep the first row of every continuous in-pool episode for each stock."""
    if df.empty:
        return pd.DataFrame()
    data = df.copy()
    data["select_date"] = data["select_date"].astype(str).map(_normalize_date)
    score_col = _score_column(data)
    reset_cols = [col for col in ["source_file", "stage", "source_label"] if col in data.columns]
    if reset_cols:
        data["_reset_key"] = data[reset_cols].fillna("NA").astype(str).agg("|".join, axis=1)
    else:
        data["_reset_key"] = "all"

    # 同一股票同一扫描日可能有重复记录，只保留当日排序分最高的一条。
    data = data.sort_values(["_reset_key", "ts_code", "select_date", score_col], ascending=[True, True, True, False])
    data = data.drop_duplicates(["_reset_key", "ts_code", "select_date"], keep="first")

    scan_days = data[["_reset_key", "select_date"]].drop_duplicates().sort_values(["_reset_key", "select_date"])
    scan_days["_scan_index"] = scan_days.groupby("_reset_key").cumcount()
    data = data.merge(scan_days, on=["_reset_key", "select_date"], how="left")
    data = data.sort_values(["_reset_key", "ts_code", "_scan_index", score_col], ascending=[True, True, True, False])

    prev_index = data.groupby(["_reset_key", "ts_code"], sort=False)["_scan_index"].shift(1)
    data["_new_episode"] = prev_index.isna() | ((data["_scan_index"] - prev_index) > 1)
    data["_episode_id"] = data.groupby(["_reset_key", "ts_code"], sort=False)["_new_episode"].cumsum()

    episode_keys = ["_reset_key", "ts_code", "_episode_id"]
    first = data.drop_duplicates(episode_keys, keep="first").copy()
    counts = data.groupby(episode_keys).agg(
        appearances=("ts_code", "size"),
        last_select_date=("select_date", "max"),
    )
    first = first.merge(counts, left_on=episode_keys, right_index=True, how="left")
    first = first.rename(columns={"select_date": "first_select_date"})
    first["lifecycle_id"] = first["ts_code"].astype(str) + "#" + first["_episode_id"].astype(int).astype(str)
    helper_cols = ["_reset_key", "_scan_index", "_new_episode", "_episode_id"]
    first = first.drop(columns=[col for col in helper_cols if col in first.columns])
    first = first.sort_values(["first_select_date", score_col], ascending=[True, False]).reset_index(drop=True)
    return first


def summarize_first_entries(first: pd.DataFrame, horizons: list[int] | None = None) -> pd.DataFrame:
    horizons = horizons or DEFAULT_HORIZONS
    rows = []
    for horizon in horizons:
        ret_col = f"ret_{horizon}d"
        if ret_col not in first.columns:
            continue
        data = first.dropna(subset=[ret_col])
        if data.empty:
            continue
        out_col = f"outperform_{horizon}d"
        rows.append(
            {
                "horizon": f"{horizon}d",
                "new_stocks": int(len(data)),
                "avg_ret": round(float(data[ret_col].mean()), 2),
                "median_ret": round(float(data[ret_col].median()), 2),
                "win_rate": round(float((data[ret_col] > 0).mean() * 100), 2),
                "outperform_rate": round(float(data[out_col].mean() * 100), 2) if out_col in data.columns else None,
            }
        )
    return pd.DataFrame(rows)


def active_pool_timeline(first: pd.DataFrame, hold_days: int = 80) -> pd.DataFrame:
    if first.empty:
        return pd.DataFrame(columns=["date", "new_count", "active_count"])
    entries = first.copy()
    entries["entry_dt"] = pd.to_datetime(entries["first_select_date"], format="%Y%m%d", errors="coerce")
    entries = entries.dropna(subset=["entry_dt"])
    if entries.empty:
        return pd.DataFrame(columns=["date", "new_count", "active_count"])
    start = entries["entry_dt"].min()
    end = entries["entry_dt"].max() + pd.Timedelta(days=int(hold_days))
    dates = pd.date_range(start, end, freq="D")
    rows = []
    for dt in dates:
        active = entries[(entries["entry_dt"] <= dt) & (entries["entry_dt"] + pd.Timedelta(days=int(hold_days)) >= dt)]
        rows.append(
            {
                "date": dt.strftime("%Y%m%d"),
                "new_count": int((entries["entry_dt"] == dt).sum()),
                "active_count": int(len(active)),
            }
        )
    return pd.DataFrame(rows)


def industry_summary(first: pd.DataFrame, horizons: list[int] | None = None) -> pd.DataFrame:
    horizons = horizons or DEFAULT_HORIZONS
    if first.empty or "industry" not in first.columns:
        return pd.DataFrame()
    rows = []
    for industry, group in first.groupby("industry", dropna=False):
        row = {"industry": industry, "new_stocks": int(len(group))}
        for horizon in horizons:
            ret_col = f"ret_{horizon}d"
            if ret_col in group.columns:
                valid = group.dropna(subset=[ret_col])
                row[f"avg_ret_{horizon}d"] = round(float(valid[ret_col].mean()), 2) if not valid.empty else None
                row[f"win_rate_{horizon}d"] = round(float((valid[ret_col] > 0).mean() * 100), 2) if not valid.empty else None
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["new_stocks", f"avg_ret_{horizons[-1]}d"], ascending=[False, False])


def repeated_entries(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    score_col = _score_column(df)
    counts = (
        df.groupby(["ts_code", "name", "industry"], dropna=False)
        .agg(
            appearances=("ts_code", "size"),
            first_select_date=("select_date", "min"),
            last_select_date=("select_date", "max"),
            avg_score=(score_col, "mean"),
            ret_80d=("ret_80d", "first"),
        )
        .reset_index()
    )
    return counts[counts["appearances"] > 1].sort_values(["appearances", "avg_score"], ascending=[False, False])


def build_report(df: pd.DataFrame, horizons: list[int] | None = None, hold_days: int = 80, title: str = "长线股票池生命周期审计") -> str:
    horizons = horizons or DEFAULT_HORIZONS
    first = lifecycle_entry_table(df)
    summary = summarize_first_entries(first, horizons)
    timeline = active_pool_timeline(first, hold_days)
    industries = industry_summary(first, horizons)
    repeats = repeated_entries(df)
    display_cols = [c for c in DISPLAY_COLUMNS if c in first.columns]

    max_active = int(timeline["active_count"].max()) if not timeline.empty else 0
    avg_active = round(float(timeline["active_count"].mean()), 2) if not timeline.empty else 0.0

    lines = [
        f"# {title}\n\n",
        "## 先看结论\n",
        f"- 原始入池样本 `{len(df)}` 个，按连续在池生命周期去重后 `{len(first)}` 次入池事件。\n",
        f"- 按 `{hold_days}` 天观察期估算：最大活跃池 `{max_active}` 只，平均活跃池 `{avg_active}` 只。\n",
    ]
    if not summary.empty:
        main = summary.iloc[-1]
        lines.append(
            f"- 入池事件最长窗口 `{main['horizon']}`：平均收益 `{_fmt_pct(main['avg_ret'])}`，"
            f"胜率 `{main['win_rate']:.2f}%`，跑赢沪深300比例 `{main['outperform_rate']:.2f}%`。\n"
        )
    lines.extend(
        [
            "\n## 首次入池表现\n",
            _table(summary, max_rows=20),
            "\n## 池子规模时间线\n",
            _table(timeline[timeline["new_count"] > 0], max_rows=80),
            "\n## 行业分布\n",
            _table(industries, max_rows=40),
            "\n## 反复入池股票\n",
            _table(repeats, max_rows=40),
            "\n## 首次入池明细\n",
            _table(first[display_cols], max_rows=80) if display_cols else _table(first, max_rows=80),
        ]
    )
    return "".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Longterm recommendation-pool lifecycle audit")
    parser.add_argument("--input", nargs="+", required=True, help="longterm_pool_quality CSV path(s)")
    parser.add_argument("--output", required=True, help="Markdown report path")
    parser.add_argument("--horizons", nargs="+", type=int, default=DEFAULT_HORIZONS)
    parser.add_argument("--hold-days", type=int, default=80, help="estimated active observation window")
    parser.add_argument("--title", default="长线股票池生命周期审计")
    args = parser.parse_args()

    data = load_quality_csv(args.input)
    report = build_report(data, args.horizons, args.hold_days, args.title)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"Report written: {out}")
    print("\n".join(report.splitlines()[:8]))


if __name__ == "__main__":
    main()
