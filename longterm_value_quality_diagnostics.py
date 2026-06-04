#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Audit value/quality factors for a true long-horizon stock strategy."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


FACTOR_COLUMNS = [
    "quality_score_known",
    "quality_score",
    "roe",
    "debt_to_assets",
    "netprofit_yoy",
    "revenue_yoy",
    "pe_ttm",
    "pb",
    "ps_ttm",
    "dv_ratio",
    "total_mv",
    "circ_mv",
    "price_vs_ma_long",
    "ret_1y",
    "drawdown_1y",
    "turnover_rate",
    "volume_ratio",
]


def latest_financial_snapshot(fina: pd.DataFrame, asof_date: str) -> pd.DataFrame:
    if fina is None or fina.empty:
        return pd.DataFrame()
    df = fina.copy()
    df["ann_date"] = df["ann_date"].astype(str).str.replace("-", "").str[:8]
    df = df[df["ann_date"] <= str(asof_date)]
    if df.empty:
        return pd.DataFrame()
    df = df.sort_values(["ts_code", "ann_date", "end_date"]).groupby("ts_code").tail(1)
    return df.set_index("ts_code")


def latest_income_snapshot(income: pd.DataFrame, asof_date: str) -> pd.DataFrame:
    if income is None or income.empty:
        return pd.DataFrame()
    df = income.copy()
    df["ann_date"] = df["ann_date"].astype(str).str.replace("-", "").str[:8]
    df = df[df["ann_date"] <= str(asof_date)]
    if df.empty:
        return pd.DataFrame()
    df = df.sort_values(["ts_code", "ann_date", "end_date"]).groupby("ts_code").tail(1)
    return df.set_index("ts_code")


def _score_roe(value) -> float:
    if pd.isna(value):
        return 50.0
    value = float(value)
    if value >= 15:
        return 100.0
    if value >= 8:
        return 70.0 + (value - 8) / 7 * 30
    if value >= 0:
        return 30.0 + value / 8 * 40
    return 0.0


def _score_growth(value) -> float:
    if pd.isna(value):
        return 50.0
    value = max(min(float(value), 100.0), -50.0)
    if value >= 30:
        return 100.0
    if value >= 0:
        return 50.0 + value / 30 * 50
    return max(0.0, 50.0 + value)


def _score_debt(value) -> float:
    if pd.isna(value):
        return 50.0
    value = float(value)
    if value <= 35:
        return 100.0
    if value <= 60:
        return 70.0 - (value - 35) / 25 * 30
    if value <= 80:
        return 40.0 - (value - 60) / 20 * 30
    return 0.0


def compute_quality_score(row: pd.Series) -> float:
    roe_score = _score_roe(row.get("roe"))
    growth_score = _score_growth(row.get("netprofit_yoy"))
    debt_score = _score_debt(row.get("debt_to_assets"))
    return round(0.45 * roe_score + 0.30 * growth_score + 0.25 * debt_score, 2)


def financial_factor_count(row: pd.Series) -> int:
    return sum(
        0 if pd.isna(row.get(col)) else 1
        for col in ["roe", "netprofit_yoy", "debt_to_assets"]
    )


def _stock_forward_return(grp: pd.DataFrame, asof_date: str, forward_days: int) -> float | None:
    g = grp.sort_values("trade_date").reset_index(drop=True)
    dates = g["trade_date"].astype(str).tolist()
    eligible = [i for i, d in enumerate(dates) if d <= asof_date]
    if not eligible:
        return None
    idx = eligible[-1]
    fwd_idx = idx + forward_days
    if fwd_idx >= len(g):
        return None
    start = float(g.loc[idx, "close"])
    end = float(g.loc[fwd_idx, "close"])
    if start <= 0:
        return None
    return (end - start) / start * 100


def build_factor_snapshot(
    daily: pd.DataFrame,
    fina: pd.DataFrame,
    income: pd.DataFrame,
    stock_basic: pd.DataFrame,
    asof_date: str,
    daily_basic: pd.DataFrame | None = None,
    forward_days: list[int] | None = None,
    trend_window: int = 250,
) -> pd.DataFrame:
    forward_days = forward_days or [120, 240]
    if daily is None or daily.empty:
        return pd.DataFrame()
    prices = daily.copy()
    prices["trade_date"] = prices["trade_date"].astype(str).str.replace("-", "").str[:8]
    prices = prices.sort_values(["ts_code", "trade_date"])
    fin = latest_financial_snapshot(fina, asof_date)
    inc = latest_income_snapshot(income, asof_date)
    basic = stock_basic.copy() if stock_basic is not None else pd.DataFrame()
    if not basic.empty:
        basic = basic.set_index("ts_code")
    daily_basic_idx = daily_basic.copy() if daily_basic is not None else pd.DataFrame()
    if not daily_basic_idx.empty:
        daily_basic_idx = daily_basic_idx.set_index("ts_code")

    rows = []
    for ts_code, grp in prices.groupby("ts_code"):
        hist = grp[grp["trade_date"] <= str(asof_date)].tail(max(trend_window, 20))
        if hist.empty:
            continue
        close = float(hist.iloc[-1]["close"])
        high = float(hist["high"].max()) if "high" in hist.columns else float(hist["close"].max())
        ma_long = float(hist["close"].tail(min(trend_window, len(hist))).mean())
        first_close = float(hist.iloc[0]["close"])
        row = {
            "asof_date": asof_date,
            "ts_code": ts_code,
            "close": close,
            "ma_long": round(ma_long, 3),
            "price_vs_ma_long": round((close - ma_long) / ma_long * 100, 2) if ma_long > 0 else None,
            "ret_1y": round((close - first_close) / first_close * 100, 2) if first_close > 0 and len(hist) >= 2 else None,
            "drawdown_1y": round((close - high) / high * 100, 2) if high > 0 else None,
        }
        for fd in forward_days:
            row[f"ret_{fd}d"] = _stock_forward_return(grp, asof_date, fd)
        if ts_code in fin.index:
            f = fin.loc[ts_code]
            row["roe"] = f.get("roe")
            row["debt_to_assets"] = f.get("debt_to_assets")
            row["netprofit_yoy"] = f.get("netprofit_yoy")
        if ts_code in inc.index:
            row["revenue"] = inc.loc[ts_code].get("revenue")
        if ts_code in basic.index:
            row["name"] = basic.loc[ts_code].get("name")
            row["industry"] = basic.loc[ts_code].get("industry")
        if ts_code in daily_basic_idx.index:
            db = daily_basic_idx.loc[ts_code]
            for col in [
                "turnover_rate",
                "volume_ratio",
                "pe",
                "pe_ttm",
                "pb",
                "ps",
                "ps_ttm",
                "dv_ratio",
                "dv_ttm",
                "total_mv",
                "circ_mv",
            ]:
                if col in daily_basic_idx.columns:
                    row[col] = db.get(col)

        row_series = pd.Series(row)
        known_count = financial_factor_count(row_series)
        row["financial_factor_count"] = known_count
        row["financial_known"] = known_count >= 2
        row["financial_complete"] = known_count == 3
        row["quality_score"] = compute_quality_score(row_series)
        row["quality_score_known"] = row["quality_score"] if row["financial_known"] else None
        rows.append(row)
    return pd.DataFrame(rows)


def summarize_factor_quantiles(
    df: pd.DataFrame,
    target_col: str,
    factors: list[str] | None = None,
    buckets: int = 5,
) -> pd.DataFrame:
    factors = [c for c in (factors or FACTOR_COLUMNS) if c in df.columns]
    rows = []
    for factor in factors:
        data = df[[factor, target_col]].dropna().copy()
        if len(data) < max(buckets, 2) or data[factor].nunique() < 2:
            continue
        data["bucket"] = pd.qcut(data[factor], q=min(buckets, data[factor].nunique()), duplicates="drop")
        grouped = data.groupby("bucket", observed=True).agg(
            count=(target_col, "size"),
            factor_min=(factor, "min"),
            factor_max=(factor, "max"),
            avg_return=(target_col, "mean"),
            median_return=(target_col, "median"),
            win_rate=(target_col, lambda s: (s > 0).mean() * 100),
        )
        for _, rec in grouped.reset_index().iterrows():
            rows.append(
                {
                    "factor": factor,
                    "bucket": str(rec["bucket"]),
                    "count": int(rec["count"]),
                    "factor_min": round(float(rec["factor_min"]), 2),
                    "factor_max": round(float(rec["factor_max"]), 2),
                    "avg_return": round(float(rec["avg_return"]), 2),
                    "median_return": round(float(rec["median_return"]), 2),
                    "win_rate": round(float(rec["win_rate"]), 2),
                }
            )
    return pd.DataFrame(rows)


def factor_correlations(df: pd.DataFrame, target_col: str, factors: list[str] | None = None) -> pd.DataFrame:
    factors = [c for c in (factors or FACTOR_COLUMNS) if c in df.columns]
    rows = []
    for factor in factors:
        data = df[[factor, target_col]].dropna()
        if len(data) < 20 or data[factor].nunique() < 2:
            continue
        corr = data[factor].corr(data[target_col], method="spearman")
        if pd.isna(corr):
            continue
        rows.append({"factor": factor, "spearman_corr": round(float(corr), 4), "n": len(data)})
    return pd.DataFrame(rows).sort_values("spearman_corr", key=lambda s: s.abs(), ascending=False) if rows else pd.DataFrame()


def _table(df: pd.DataFrame, max_rows: int = 40) -> str:
    if df is None or df.empty:
        return "无样本\n"
    return df.head(max_rows).to_markdown(index=False) + "\n"


def build_report(snapshot: pd.DataFrame, quantiles: pd.DataFrame, title: str = "长线质量因子审计") -> str:
    if snapshot.empty:
        return f"# {title}\n\n无样本。\n"
    target_cols = [c for c in snapshot.columns if c.startswith("ret_") and c.endswith("d")]
    target = target_cols[0] if target_cols else None
    corr = factor_correlations(snapshot, target) if target else pd.DataFrame()
    financial_known = snapshot["financial_known"].fillna(False) if "financial_known" in snapshot.columns else pd.Series(False, index=snapshot.index)
    financial_complete = snapshot["financial_complete"].fillna(False) if "financial_complete" in snapshot.columns else pd.Series(False, index=snapshot.index)
    known_count = int(financial_known.sum())
    complete_count = int(financial_complete.sum())
    coverage = known_count / len(snapshot) * 100 if len(snapshot) else 0.0

    lines = [
        f"# {title}\n\n",
        "## 先看结论\n",
        f"- 共分析 `{len(snapshot)}` 个长线截面样本。\n",
        f"- 财务质量字段覆盖：至少2项有效 `{known_count}` 个，占 `{coverage:.1f}%`；3项完整 `{complete_count}` 个。\n",
    ]
    if target:
        avg_ret = snapshot[target].mean()
        med_ret = snapshot[target].median()
        lines.append(f"- 主要前瞻收益 `{target}`：均值 `{avg_ret:+.2f}%`，中位数 `{med_ret:+.2f}%`。\n")
    if not corr.empty:
        top = corr.head(5)
        text = "、".join(f"`{r.factor}` 相关 {r.spearman_corr:+.3f}" for r in top.itertuples())
        lines.append(f"- 相关性最明显的因子：{text}。\n")
    if known_count < len(snapshot) * 0.2:
        lines.append("- 注意：当前财务覆盖偏低，`quality_score_known` 比 `quality_score` 更适合判断质量因子的真实效果。\n")

    high_quality = snapshot.copy()
    if "quality_score_known" in high_quality.columns:
        high_quality = high_quality.dropna(subset=["quality_score_known"]).sort_values("quality_score_known", ascending=False)
    else:
        high_quality = high_quality.sort_values("quality_score", ascending=False)

    sample_cols = [
        "asof_date",
        "ts_code",
        "name",
        "industry",
        "quality_score_known",
        "quality_score",
        "financial_factor_count",
        "roe",
        "debt_to_assets",
        "netprofit_yoy",
    ] + target_cols
    lines.extend(
        [
            "\n## 因子相关性\n",
            _table(corr),
            "\n## 因子分桶\n",
            _table(quantiles, max_rows=90),
            "\n## 高质量样本示例\n",
            _table(high_quality[[c for c in sample_cols if c in high_quality.columns]], max_rows=30),
            "\n## 下一步\n",
            "- 先用 `quality_score_known` 观察已知财务样本，不把缺失财务的股票误判为中等质量。\n",
            "- 当前 daily_basic 缺少 PE/PB，估值维度暂未纳入；后续补充估值缓存后再审计。\n",
        ]
    )
    return "".join(lines)


def load_daily_range(cache_dir: Path, start_date: str, end_date: str) -> pd.DataFrame:
    frames = []
    daily_dir = cache_dir / "daily"
    for path in sorted(daily_dir.glob("*.parquet")):
        date = path.stem
        if start_date <= date <= end_date:
            frames.append(pd.read_parquet(path))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def load_daily_basic_snapshot(cache_dir: Path, asof_date: str) -> pd.DataFrame:
    daily_basic_dir = cache_dir / "daily_basic"
    if not daily_basic_dir.exists():
        return pd.DataFrame()
    files = sorted(path for path in daily_basic_dir.glob("*.parquet") if path.stem <= asof_date)
    if not files:
        return pd.DataFrame()
    return pd.read_parquet(files[-1])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit long-horizon value/quality factors.")
    parser.add_argument("--cache-dir", default="data/cache", help="Local cache directory.")
    parser.add_argument("--asof-date", required=True, help="Snapshot date YYYYMMDD.")
    parser.add_argument("--start", default=None, help="Daily data start date. Defaults to cache range if omitted.")
    parser.add_argument("--end", default=None, help="Daily data end date. Defaults to latest cached date.")
    parser.add_argument("--forward-days", nargs="+", type=int, default=[120, 240], help="Forward trading-day horizons.")
    parser.add_argument("--output", required=True, help="Markdown report path.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cache_dir = Path(args.cache_dir)
    daily_files = sorted((cache_dir / "daily").glob("*.parquet"))
    if not daily_files:
        raise SystemExit("未找到 daily 缓存")
    start = args.start or daily_files[0].stem
    end = args.end or daily_files[-1].stem
    daily = load_daily_range(cache_dir, start, end)
    fina = pd.read_parquet(cache_dir / "fina_indicator.parquet")
    income = pd.read_parquet(cache_dir / "income.parquet") if (cache_dir / "income.parquet").exists() else pd.DataFrame()
    stock_basic = pd.read_parquet(cache_dir / "stock_basic.parquet")
    daily_basic = load_daily_basic_snapshot(cache_dir, args.asof_date)
    snapshot = build_factor_snapshot(
        daily=daily,
        fina=fina,
        income=income,
        stock_basic=stock_basic,
        daily_basic=daily_basic,
        asof_date=args.asof_date,
        forward_days=args.forward_days,
    )
    target = f"ret_{args.forward_days[0]}d"
    quantiles = summarize_factor_quantiles(snapshot, target_col=target)
    report = build_report(snapshot, quantiles, title=f"长线质量因子审计 {args.asof_date}")
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"Report written: {out}")
    print("\n".join(report.splitlines()[:8]))


if __name__ == "__main__":
    main()
