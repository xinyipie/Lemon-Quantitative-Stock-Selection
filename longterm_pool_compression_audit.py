#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Compress v18 longterm candidate pools into a smaller pushable watchlist."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


DEFAULT_HORIZONS = [10, 40, 80]
DISPLAY_COLUMNS = [
    "select_date",
    "ts_code",
    "name",
    "industry",
    "compression_score",
    "recent_appearances",
    "pool_rank_score",
    "industry_rs",
    "price_vs_ma60",
    "drawdown_from_high",
    "turnover",
    "pb",
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


def _table(df: pd.DataFrame, max_rows: int = 60, columns: list[str] | None = None) -> str:
    if df.empty:
        return "无样本\n"
    view = df.copy()
    if columns:
        view = view[[col for col in columns if col in view.columns]]
    return view.head(max_rows).to_markdown(index=False) + "\n"


def _clip_score(series: pd.Series, low: float, high: float) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").fillna(low)
    return ((values - low) / (high - low) * 100).clip(0, 100)


def _band_score(series: pd.Series, low: float, high: float, best_low: float, best_high: float) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    score = pd.Series(0.0, index=series.index)
    left = values.between(low, best_low, inclusive="left")
    mid = values.between(best_low, best_high, inclusive="both")
    right = values.between(best_high, high, inclusive="right")
    score.loc[left] = ((values.loc[left] - low) / max(best_low - low, 1e-9) * 100).clip(0, 100)
    score.loc[mid] = 100
    score.loc[right] = ((high - values.loc[right]) / max(high - best_high, 1e-9) * 100).clip(0, 100)
    return score.fillna(0)


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
    return normalize_pool(pd.concat(frames, ignore_index=True))


def normalize_pool(df: pd.DataFrame) -> pd.DataFrame:
    data = df.copy()
    if data.empty:
        return data
    if "select_date" in data.columns:
        data["select_date"] = data["select_date"].astype(str).map(_normalize_date)
    if "pool_rank_score" not in data.columns and "longterm_score" in data.columns:
        data["pool_rank_score"] = data["longterm_score"]
    numeric_cols = [
        "pool_rank_score",
        "quality_rank_score",
        "longterm_score",
        "industry_rs",
        "price_vs_ma60",
        "drawdown_from_high",
        "turnover",
        "pb",
        "pe_ttm",
        "roe",
        "netprofit_yoy",
    ]
    for prefix in ["ret_", "mfe_", "mae_", "outperform_", "benchmark_ret_", "excess_ret_"]:
        numeric_cols.extend([col for col in data.columns if col.startswith(prefix)])
    for col in sorted(set(numeric_cols)):
        if col in data.columns:
            data[col] = pd.to_numeric(data[col], errors="coerce")
    for col in ["ts_code", "name", "industry", "source_file"]:
        if col in data.columns:
            data[col] = data[col].fillna("NA").astype(str)
    return data


def add_compression_features(df: pd.DataFrame, lookback_days: int = 20) -> pd.DataFrame:
    data = normalize_pool(df)
    if data.empty:
        return data
    data = data.sort_values(["select_date", "ts_code"]).copy()
    dates = sorted(data["select_date"].dropna().astype(str).unique().tolist())
    date_index = {date: idx for idx, date in enumerate(dates)}
    data["_scan_index"] = data["select_date"].map(date_index)

    recent_counts = []
    for _, row in data[["ts_code", "_scan_index"]].iterrows():
        code = row["ts_code"]
        idx = int(row["_scan_index"])
        start = idx - int(lookback_days)
        history = data[(data["ts_code"] == code) & (data["_scan_index"] >= start) & (data["_scan_index"] <= idx)]
        recent_counts.append(int(history["select_date"].nunique()))
    data["recent_appearances"] = recent_counts

    industry_score = _clip_score(data.get("industry_rs", pd.Series(0, index=data.index)), -5, 15)
    trend_score = _band_score(data.get("price_vs_ma60", pd.Series(0, index=data.index)), 0, 22, 5, 16)
    pullback_score = _band_score(data.get("drawdown_from_high", pd.Series(0, index=data.index)), 0, 28, 6, 18)
    turnover_score = _band_score(data.get("turnover", pd.Series(0, index=data.index)), 0.5, 8, 1.5, 5)
    repeat_score = data["recent_appearances"].clip(1, 4).map({1: 55, 2: 75, 3: 90, 4: 100}).fillna(55)
    value_penalty = (pd.to_numeric(data.get("pb", pd.Series(0, index=data.index)), errors="coerce").fillna(0) - 6).clip(lower=0) * 4

    data["compression_score"] = (
        industry_score * 0.30
        + trend_score * 0.20
        + pullback_score * 0.18
        + turnover_score * 0.12
        + repeat_score * 0.20
        - value_penalty
    ).round(2)
    return data.drop(columns=["_scan_index"])


def compress_pool(
    df: pd.DataFrame,
    max_active: int = 10,
    max_new_per_day: int = 2,
    max_industry_active: int = 2,
    hold_days: int = 80,
    lookback_days: int = 20,
) -> pd.DataFrame:
    data = add_compression_features(df, lookback_days=lookback_days)
    if data.empty:
        return data
    data["_select_dt"] = pd.to_datetime(data["select_date"], format="%Y%m%d", errors="coerce")
    data = data.dropna(subset=["_select_dt"]).sort_values(["_select_dt", "compression_score"], ascending=[True, False])
    active: list[dict] = []
    selected = []
    for select_date, group in data.groupby("select_date", sort=True):
        current_dt = pd.to_datetime(select_date, format="%Y%m%d", errors="coerce")
        active = [item for item in active if item["exit_dt"] >= current_dt]
        active_codes = {item["ts_code"] for item in active}
        industry_counts = {}
        for item in active:
            industry_counts[item["industry"]] = industry_counts.get(item["industry"], 0) + 1

        new_today = 0
        candidates = group.sort_values(["compression_score", "pool_rank_score"], ascending=[False, False])
        for _, row in candidates.iterrows():
            if len(active) >= int(max_active) or new_today >= int(max_new_per_day):
                break
            code = str(row.get("ts_code", ""))
            industry = str(row.get("industry", "NA"))
            if code in active_codes:
                continue
            if industry_counts.get(industry, 0) >= int(max_industry_active):
                continue
            record = row.to_dict()
            record["active_before"] = len(active)
            record["active_after"] = len(active) + 1
            record["planned_exit_date"] = (current_dt + pd.Timedelta(days=int(hold_days))).strftime("%Y%m%d")
            selected.append(record)
            active.append(
                {
                    "ts_code": code,
                    "industry": industry,
                    "entry_dt": current_dt,
                    "exit_dt": current_dt + pd.Timedelta(days=int(hold_days)),
                }
            )
            active_codes.add(code)
            industry_counts[industry] = industry_counts.get(industry, 0) + 1
            new_today += 1

    result = pd.DataFrame(selected)
    if result.empty:
        return result
    drop_cols = [col for col in ["_select_dt"] if col in result.columns]
    return result.drop(columns=drop_cols).sort_values(["select_date", "compression_score"], ascending=[True, False]).reset_index(drop=True)


def compress_snapshot_pool(
    df: pd.DataFrame,
    max_active: int = 10,
    max_industry_active: int = 2,
    lookback_days: int = 20,
) -> pd.DataFrame:
    """Build a small current watchlist for each scan date without locking names."""
    data = add_compression_features(df, lookback_days=lookback_days)
    if data.empty:
        return data
    selected = []
    data = data.sort_values(["select_date", "compression_score", "pool_rank_score"], ascending=[True, False, False])
    for select_date, group in data.groupby("select_date", sort=True):
        industry_counts = {}
        daily = []
        candidates = group.sort_values(["compression_score", "pool_rank_score"], ascending=[False, False])
        for _, row in candidates.iterrows():
            if len(daily) >= int(max_active):
                break
            industry = str(row.get("industry", "NA"))
            if industry_counts.get(industry, 0) >= int(max_industry_active):
                continue
            record = row.to_dict()
            record["snapshot_rank"] = len(daily) + 1
            daily.append(record)
            industry_counts[industry] = industry_counts.get(industry, 0) + 1
        selected.extend(daily)
    result = pd.DataFrame(selected)
    if result.empty:
        return result
    return result.sort_values(["select_date", "snapshot_rank"]).reset_index(drop=True)


def summarize_compressed_pool(df: pd.DataFrame, horizons: list[int] | None = None) -> pd.DataFrame:
    horizons = horizons or DEFAULT_HORIZONS
    rows = []
    for horizon in horizons:
        ret_col = f"ret_{horizon}d"
        if ret_col not in df.columns:
            continue
        valid = df.dropna(subset=[ret_col])
        if valid.empty:
            continue
        out_col = f"outperform_{horizon}d"
        rows.append(
            {
                "horizon": f"{horizon}d",
                "count": int(len(valid)),
                "avg_ret": round(float(valid[ret_col].mean()), 2),
                "median_ret": round(float(valid[ret_col].median()), 2),
                "win_rate": round(float((valid[ret_col] > 0).mean() * 100), 2),
                "outperform_rate": round(float(valid[out_col].mean() * 100), 2) if out_col in valid.columns else None,
            }
        )
    return pd.DataFrame(rows)


def active_timeline(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["date", "new_count", "active_count"])
    if "planned_exit_date" not in df.columns:
        result = (
            df.groupby("select_date", dropna=False)
            .agg(new_count=("ts_code", "size"), active_count=("ts_code", "size"))
            .reset_index()
            .rename(columns={"select_date": "date"})
        )
        return result[["date", "new_count", "active_count"]]
    rows = []
    entries = df.copy()
    entries["entry_dt"] = pd.to_datetime(entries["select_date"], format="%Y%m%d", errors="coerce")
    entries["exit_dt"] = pd.to_datetime(entries["planned_exit_date"], format="%Y%m%d", errors="coerce")
    dates = pd.date_range(entries["entry_dt"].min(), entries["exit_dt"].max(), freq="D")
    for dt in dates:
        active = entries[(entries["entry_dt"] <= dt) & (entries["exit_dt"] >= dt)]
        rows.append(
            {
                "date": dt.strftime("%Y%m%d"),
                "new_count": int((entries["entry_dt"] == dt).sum()),
                "active_count": int(len(active)),
            }
        )
    return pd.DataFrame(rows)


def industry_summary(df: pd.DataFrame, horizons: list[int] | None = None) -> pd.DataFrame:
    horizons = horizons or DEFAULT_HORIZONS
    if df.empty or "industry" not in df.columns:
        return pd.DataFrame()
    rows = []
    for industry, group in df.groupby("industry", dropna=False):
        row = {"industry": industry, "count": int(len(group))}
        for horizon in horizons:
            ret_col = f"ret_{horizon}d"
            if ret_col in group.columns:
                valid = group.dropna(subset=[ret_col])
                row[f"avg_ret_{horizon}d"] = round(float(valid[ret_col].mean()), 2) if not valid.empty else None
                row[f"win_rate_{horizon}d"] = round(float((valid[ret_col] > 0).mean() * 100), 2) if not valid.empty else None
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["count", f"avg_ret_{horizons[-1]}d"], ascending=[False, False])


def build_report(
    compressed: pd.DataFrame,
    original: pd.DataFrame,
    horizons: list[int] | None = None,
    title: str = "长线 v18 候选池压缩审计",
) -> str:
    horizons = horizons or DEFAULT_HORIZONS
    summary = summarize_compressed_pool(compressed, horizons)
    timeline = active_timeline(compressed)
    industries = industry_summary(compressed, horizons)
    max_active = int(timeline["active_count"].max()) if not timeline.empty else 0
    avg_active = round(float(timeline["active_count"].mean()), 2) if not timeline.empty else 0.0
    lines = [
        f"# {title}\n\n",
        "## 先看结论\n",
        f"- 原始候选 `{len(original)}` 条，压缩后推荐 `{len(compressed)}` 条。\n",
        f"- 压缩后最大活跃池 `{max_active}` 只，平均活跃池 `{avg_active}` 只。\n",
    ]
    if not summary.empty:
        main = summary.iloc[-1]
        lines.append(
            f"- 最长窗口 `{main['horizon']}`：平均收益 `{_fmt_pct(main['avg_ret'])}`，"
            f"胜率 `{main['win_rate']:.2f}%`，跑赢沪深300比例 `{main['outperform_rate']:.2f}%`。\n"
        )
    lines.extend(
        [
            "\n## 压缩后表现\n",
            _table(summary, max_rows=20),
            "\n## 活跃池规模\n",
            _table(timeline[timeline["new_count"] > 0], max_rows=100),
            "\n## 行业分布\n",
            _table(industries, max_rows=40),
            "\n## 推荐明细\n",
            _table(compressed, max_rows=120, columns=DISPLAY_COLUMNS),
        ]
    )
    return "".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compress longterm v18 pool-quality CSV files.")
    parser.add_argument("--input", nargs="+", required=True, help="longterm_pool_quality CSV path(s)")
    parser.add_argument("--output", required=True, help="Markdown report path")
    parser.add_argument("--csv-output", default=None, help="Optional compressed CSV output path")
    parser.add_argument("--max-active", type=int, default=10)
    parser.add_argument("--max-new-per-day", type=int, default=2)
    parser.add_argument("--max-industry-active", type=int, default=2)
    parser.add_argument("--hold-days", type=int, default=80)
    parser.add_argument("--lookback-days", type=int, default=20)
    parser.add_argument("--mode", choices=["snapshot", "entry-lock"], default="snapshot")
    parser.add_argument("--horizons", nargs="+", type=int, default=DEFAULT_HORIZONS)
    parser.add_argument("--title", default="长线 v18 候选池压缩审计")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    original = load_quality_csv(args.input)
    if args.mode == "entry-lock":
        compressed = compress_pool(
            original,
            max_active=args.max_active,
            max_new_per_day=args.max_new_per_day,
            max_industry_active=args.max_industry_active,
            hold_days=args.hold_days,
            lookback_days=args.lookback_days,
        )
    else:
        compressed = compress_snapshot_pool(
            original,
            max_active=args.max_active,
            max_industry_active=args.max_industry_active,
            lookback_days=args.lookback_days,
        )
    report = build_report(compressed, original, horizons=args.horizons, title=args.title)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    if args.csv_output:
        csv_out = Path(args.csv_output)
        csv_out.parent.mkdir(parents=True, exist_ok=True)
        compressed.to_csv(csv_out, index=False, encoding="utf-8-sig")
    print(f"Report written: {out}")
    print("\n".join(report.splitlines()[:8]))


if __name__ == "__main__":
    main()
