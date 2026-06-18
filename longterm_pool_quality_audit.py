#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Audit longterm recommendation-pool quality without portfolio position limits."""

from __future__ import annotations

import argparse
import logging
import math
import os
from pathlib import Path
from typing import Iterable
from datetime import datetime, timedelta

import pandas as pd


FACTOR_COLUMNS = [
    "winner_profile_score",
    "pool_rank_score",
    "quality_rank_score",
    "longterm_score",
    "score_marketcap",
    "score_position",
    "score_value",
    "score_safety",
    "score_volume",
    "score_repair_rs",
    "industry_rs",
    "price_vs_ma60",
    "drawdown_from_high",
    "ma20_slope",
    "turnover",
    "volume_ratio",
    "roe",
    "debt_ratio",
    "netprofit_yoy",
    "total_mv",
    "circ_mv",
    "pe_ttm",
    "pb",
    "ps_ttm",
    "dv_ratio",
]


def _fmt_pct(value) -> str:
    if pd.isna(value):
        return "NA"
    return f"{float(value):+.2f}%"


def _table(df: pd.DataFrame, max_rows: int = 40) -> str:
    if df.empty:
        return "无样本\n"
    return df.head(max_rows).to_markdown(index=False) + "\n"


def _normalize_date(value) -> str:
    return str(value).replace("-", "")[:8]


def normalize_pool(pool: pd.DataFrame, select_date: str | None = None) -> pd.DataFrame:
    data = pool.copy()
    if data.empty:
        return data
    if "ts_code" not in data.columns and "code" in data.columns:
        data["ts_code"] = data["code"].astype(str).apply(
            lambda code: code if "." in code else (f"{code}.SH" if code.startswith("6") else f"{code}.SZ")
        )
    if "select_date" not in data.columns:
        data["select_date"] = _normalize_date(select_date or "")
    else:
        data["select_date"] = data["select_date"].astype(str).map(_normalize_date)
    if "longterm_score" not in data.columns and "score" in data.columns:
        data["longterm_score"] = data["score"]
    for col in FACTOR_COLUMNS:
        if col in data.columns:
            data[col] = pd.to_numeric(data[col], errors="coerce")
    return data


def _score_column(df: pd.DataFrame) -> str | None:
    if "winner_profile_score" in df.columns and pd.to_numeric(df["winner_profile_score"], errors="coerce").notna().any():
        return "winner_profile_score"
    if "pool_rank_score" in df.columns and pd.to_numeric(df["pool_rank_score"], errors="coerce").notna().any():
        return "pool_rank_score"
    if "quality_rank_score" in df.columns and pd.to_numeric(df["quality_rank_score"], errors="coerce").notna().any():
        return "quality_rank_score"
    if "longterm_score" in df.columns:
        return "longterm_score"
    return None


def _prepare_daily(daily: pd.DataFrame) -> pd.DataFrame:
    prices = daily.copy()
    prices["trade_date"] = prices["trade_date"].astype(str).map(_normalize_date)
    for col in ["open", "high", "low", "close"]:
        if col in prices.columns:
            prices[col] = pd.to_numeric(prices[col], errors="coerce")
    return prices.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)


def _path_metrics(grp: pd.DataFrame, select_date: str, horizons: Iterable[int]) -> dict:
    g = grp.sort_values("trade_date").reset_index(drop=True)
    dates = g["trade_date"].astype(str).tolist()
    eligible = [i for i, d in enumerate(dates) if d <= select_date]
    if not eligible:
        return {}
    start_idx = eligible[-1]
    start_close = float(g.loc[start_idx, "close"])
    if start_close <= 0:
        return {}

    result = {"start_close": start_close}
    for horizon in horizons:
        end_idx = start_idx + int(horizon)
        if end_idx >= len(g):
            continue
        window = g.iloc[start_idx + 1 : end_idx + 1]
        if window.empty:
            continue
        end_close = float(g.loc[end_idx, "close"])
        result[f"ret_{horizon}d"] = (end_close - start_close) / start_close * 100
        result[f"mfe_{horizon}d"] = (float(window["high"].max()) - start_close) / start_close * 100
        result[f"mae_{horizon}d"] = (float(window["low"].min()) - start_close) / start_close * 100
    return result


def _benchmark_returns(daily: pd.DataFrame, select_dates: Iterable[str], horizons: Iterable[int], benchmark_code: str) -> dict:
    bench = daily[daily["ts_code"] == benchmark_code]
    result = {}
    if bench.empty:
        return result
    for select_date in sorted(set(select_dates)):
        metrics = _path_metrics(bench, select_date, horizons)
        for horizon in horizons:
            ret = metrics.get(f"ret_{horizon}d")
            if ret is not None:
                result[(select_date, int(horizon))] = ret
    return result


def calculate_forward_quality(
    pool: pd.DataFrame,
    daily: pd.DataFrame,
    horizons: list[int] | None = None,
    benchmark_code: str = "000300.SH",
) -> pd.DataFrame:
    """Calculate future path quality for every recommended stock in the pool."""
    horizons = horizons or [10, 40, 80]
    candidates = normalize_pool(pool)
    prices = _prepare_daily(daily)
    if candidates.empty or prices.empty:
        return pd.DataFrame()

    grouped = {code: grp for code, grp in prices.groupby("ts_code")}
    bench = _benchmark_returns(prices, candidates["select_date"].tolist(), horizons, benchmark_code)
    rows = []
    for row in candidates.to_dict("records"):
        ts_code = row.get("ts_code")
        select_date = _normalize_date(row.get("select_date", ""))
        grp = grouped.get(ts_code)
        if grp is None:
            continue
        metrics = _path_metrics(grp, select_date, horizons)
        if not metrics:
            continue
        out = dict(row)
        out.update(metrics)
        for horizon in horizons:
            bret = bench.get((select_date, int(horizon)))
            if bret is None:
                continue
            out[f"benchmark_ret_{horizon}d"] = bret
            ret = out.get(f"ret_{horizon}d")
            if ret is not None:
                out[f"excess_ret_{horizon}d"] = ret - bret
                out[f"outperform_{horizon}d"] = ret > bret
        rows.append(out)
    return pd.DataFrame(rows)


def summarize_forward_quality(df: pd.DataFrame, horizons: list[int] | None = None) -> pd.DataFrame:
    horizons = horizons or [10, 40, 80]
    rows = []
    for horizon in horizons:
        ret_col = f"ret_{horizon}d"
        if ret_col not in df.columns:
            continue
        data = df.dropna(subset=[ret_col])
        if data.empty:
            continue
        out_col = f"outperform_{horizon}d"
        rows.append(
            {
                "horizon": f"{horizon}d",
                "count": int(len(data)),
                "avg_ret": round(float(data[ret_col].mean()), 2),
                "median_ret": round(float(data[ret_col].median()), 2),
                "win_rate": round(float((data[ret_col] > 0).mean() * 100), 2),
                "outperform_rate": round(float(data[out_col].mean() * 100), 2) if out_col in data.columns else None,
                "avg_mfe": round(float(data.get(f"mfe_{horizon}d", pd.Series(dtype=float)).mean()), 2),
                "avg_mae": round(float(data.get(f"mae_{horizon}d", pd.Series(dtype=float)).mean()), 2),
            }
        )
    return pd.DataFrame(rows)


def add_score_layers(df: pd.DataFrame) -> pd.DataFrame:
    data = df.copy()
    score_col = _score_column(data)
    if data.empty or score_col is None:
        return data
    ranked = data.sort_values(["select_date", score_col], ascending=[True, False]).copy()
    ranked["rank_score_used"] = score_col
    ranked["daily_rank"] = ranked.groupby("select_date")[score_col].rank(method="first", ascending=False)
    ranked["daily_count"] = ranked.groupby("select_date")[score_col].transform("count")
    ranked["daily_rank_pct"] = ranked["daily_rank"] / ranked["daily_count"]
    ranked["top10_cutoff"] = ranked["daily_count"].apply(lambda n: max(1, math.ceil(float(n) * 0.10)))
    ranked["top20_cutoff"] = ranked["daily_count"].apply(lambda n: max(1, math.ceil(float(n) * 0.20)))
    ranked["bottom20_cutoff"] = ranked["daily_count"].apply(lambda n: max(1, math.floor(float(n) * 0.80) + 1))
    ranked["score_layer"] = "Middle60%"
    ranked.loc[ranked["daily_rank"] >= ranked["bottom20_cutoff"], "score_layer"] = "Bottom20%"
    ranked.loc[ranked["daily_rank"] <= ranked["top20_cutoff"], "score_layer"] = "Top20%"
    ranked.loc[ranked["daily_rank"] <= ranked["top10_cutoff"], "score_layer"] = "Top10%"
    return ranked


def score_layer_summary(df: pd.DataFrame, horizons: list[int] | None = None) -> pd.DataFrame:
    horizons = horizons or [10, 40, 80]
    data = add_score_layers(df)
    if data.empty or "score_layer" not in data.columns:
        return pd.DataFrame()
    score_col = _score_column(data) or "longterm_score"
    layer_order = ["Top10%", "Top20%", "Middle60%", "Bottom20%"]
    rows = []
    for layer in layer_order:
        sub = data[data["score_layer"] == layer]
        if sub.empty:
            continue
        row = {"score_layer": layer, "count": int(len(sub)), "avg_score": round(float(sub[score_col].mean()), 2)}
        for horizon in horizons:
            ret_col = f"ret_{horizon}d"
            out_col = f"outperform_{horizon}d"
            if ret_col in sub.columns:
                valid = sub.dropna(subset=[ret_col])
                row[f"avg_ret_{horizon}d"] = round(float(valid[ret_col].mean()), 2) if not valid.empty else None
                row[f"win_rate_{horizon}d"] = round(float((valid[ret_col] > 0).mean() * 100), 2) if not valid.empty else None
                row[f"outperform_{horizon}d"] = (
                    round(float(valid[out_col].mean() * 100), 2) if out_col in valid.columns and not valid.empty else None
                )
        rows.append(row)
    return pd.DataFrame(rows)


def factor_correlations(df: pd.DataFrame, horizons: list[int] | None = None) -> pd.DataFrame:
    horizons = horizons or [10, 40, 80]
    rows = []
    for horizon in horizons:
        target = f"ret_{horizon}d"
        if target not in df.columns:
            continue
        for factor in [c for c in FACTOR_COLUMNS if c in df.columns]:
            data = df[[factor, target]].dropna()
            if len(data) < 20 or data[factor].nunique() < 2:
                continue
            rows.append(
                {
                    "horizon": f"{horizon}d",
                    "factor": factor,
                    "corr": round(float(data[factor].corr(data[target])), 4),
                    "n": int(len(data)),
                }
            )
    if not rows:
        return pd.DataFrame(columns=["horizon", "factor", "corr", "n"])
    return pd.DataFrame(rows).sort_values("corr", key=lambda s: s.abs(), ascending=False).reset_index(drop=True)


def pool_type_summary(df: pd.DataFrame, horizons: list[int] | None = None) -> pd.DataFrame:
    horizons = horizons or [10, 40, 80]
    if df.empty or "pool_type" not in df.columns:
        return pd.DataFrame()
    rows = []
    for pool_type, sub in df.groupby("pool_type", dropna=False):
        row = {"pool_type": pool_type, "count": int(len(sub))}
        for horizon in horizons:
            ret_col = f"ret_{horizon}d"
            out_col = f"outperform_{horizon}d"
            if ret_col not in sub.columns:
                continue
            valid = sub.dropna(subset=[ret_col])
            row[f"avg_ret_{horizon}d"] = round(float(valid[ret_col].mean()), 2) if not valid.empty else None
            row[f"win_rate_{horizon}d"] = round(float((valid[ret_col] > 0).mean() * 100), 2) if not valid.empty else None
            row[f"outperform_{horizon}d"] = (
                round(float(valid[out_col].mean() * 100), 2) if out_col in valid.columns and not valid.empty else None
            )
        rows.append(row)
    return pd.DataFrame(rows)


def build_report(df: pd.DataFrame, horizons: list[int] | None = None, title: str = "长线股票池质量审计") -> str:
    horizons = horizons or [10, 40, 80]
    overall = summarize_forward_quality(df, horizons)
    layers = score_layer_summary(df, horizons)
    corrs = factor_correlations(df, horizons)
    pool_types = pool_type_summary(df, horizons)
    data = add_score_layers(df)

    lines = [
        f"# {title}\n\n",
        "## 先看结论\n",
        f"- 本报告评估的是“推荐股票池质量”，不受 `max-positions`、资金占用、买入顺序影响。\n",
        f"- 共分析 `{len(data)}` 个入池样本，前瞻窗口：`{', '.join(str(x) + '日' for x in horizons)}`。\n",
    ]
    if not overall.empty:
        main = overall.iloc[-1]
        lines.append(
            f"- 最长窗口 `{main['horizon']}`：平均收益 `{_fmt_pct(main['avg_ret'])}`，"
            f"胜率 `{main['win_rate']:.2f}%`，跑赢沪深300比例 `{main['outperform_rate']:.2f}%`。\n"
        )
    if not layers.empty and f"avg_ret_{horizons[-1]}d" in layers.columns:
        top = layers.iloc[0]
        bottom = layers[layers["score_layer"] == "Bottom20%"]
        if not bottom.empty:
            b = bottom.iloc[0]
            lines.append(
                f"- 分数有效性：`{top['score_layer']}` {horizons[-1]}日均收益 `{_fmt_pct(top.get(f'avg_ret_{horizons[-1]}d'))}`，"
                f"`Bottom20%` `{_fmt_pct(b.get(f'avg_ret_{horizons[-1]}d'))}`。\n"
            )
    score_col = _score_column(data)
    if data.empty or "select_date" not in data.columns or score_col is None:
        preview = pd.DataFrame()
    else:
        preview = data.sort_values(["select_date", score_col], ascending=[True, False])

    lines.extend(
        [
            "\n## 整体前瞻表现\n",
            _table(overall, max_rows=20),
            "\n## 按每日评分分层\n",
            _table(layers, max_rows=20),
            "\n## 按池类型分组\n",
            _table(pool_types, max_rows=20),
            "\n## 因子相关性\n",
            _table(corrs, max_rows=40),
            "\n## 高分样本预览\n",
            _table(preview, max_rows=40),
        ]
    )
    return "".join(lines)


def collect_longterm_pool(
    start: str,
    end: str,
    longterm_profile: str,
    cache_dir: str = "data/cache",
    sample_step: int = 1,
    forward_days: list[int] | None = None,
    quiet: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    os.environ.setdefault("LEMON_SKIP_TUSHARE_INIT", "1")
    from local_data_proxy import LocalDataProxy
    import main as stock_main

    if quiet:
        stock_main.logger.setLevel(logging.ERROR)

    proxy = LocalDataProxy(cache_dir=cache_dir)
    stock_main.set_pro(proxy)
    cal = proxy.trade_cal(exchange="SSE", start_date=start, end_date=end, is_open=1, fields="cal_date")
    trade_dates = sorted(cal["cal_date"].astype(str).tolist())
    selected_dates = trade_dates[:: max(1, int(sample_step))]
    frames = []
    for trade_date in selected_dates:
        if longterm_profile == "longterm_quality_trend_v15_confirmed_bull_pool":
            _, macro_data = stock_main.get_weekly_macro_trend(trade_date)
            price_vs_ma100 = float(macro_data.get("price_vs_ma100", 0.0) or 0.0)
            ma100_slope_pct = float(macro_data.get("ma100_slope_pct", 0.0) or 0.0)
            idx_ret_120d = float(macro_data.get("idx_ret_120d", 0.0) or 0.0)
            if price_vs_ma100 <= 0.0 or ma100_slope_pct < 0.6 or idx_ret_120d < 10.0:
                continue
        sel = stock_main.run_daily_selection(
            trade_date=trade_date,
            enable_news=False,
            longterm_profile=longterm_profile,
        )
        pool = sel.get("longterm_pool", pd.DataFrame())
        if pool is None or pool.empty:
            continue
        norm = normalize_pool(pool, select_date=trade_date)
        norm["regime"] = sel.get("regime", "")
        frames.append(norm)
    pool_df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    max_forward = max(forward_days or [10, 40, 80])
    price_end = (datetime.strptime(end, "%Y%m%d") + timedelta(days=max_forward * 2 + 30)).strftime("%Y%m%d")
    daily = proxy.daily(start_date=start, end_date=price_end, fields="ts_code,trade_date,open,high,low,close")
    benchmark = proxy.index_daily(
        ts_code="000300.SH",
        start_date=start,
        end_date=price_end,
        fields="ts_code,trade_date,open,high,low,close",
    )
    if not benchmark.empty and "ts_code" not in benchmark.columns:
        benchmark = benchmark.copy()
        benchmark["ts_code"] = "000300.SH"
    if not benchmark.empty:
        daily = pd.concat([daily, benchmark], ignore_index=True)
    return pool_df, daily


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit longterm recommendation-pool future quality.")
    parser.add_argument("--start", required=True, help="Selection start date, YYYYMMDD.")
    parser.add_argument("--end", required=True, help="Selection end date, YYYYMMDD.")
    parser.add_argument("--longterm-profile", default="repair_v3_defensive_gate", help="Longterm profile to audit.")
    parser.add_argument("--cache-dir", default="data/cache", help="Local cache directory.")
    parser.add_argument("--forward-days", nargs="+", type=int, default=[10, 40, 80], help="Forward trading-day windows.")
    parser.add_argument("--sample-step", type=int, default=1, help="Use every Nth trading day to speed up probes.")
    parser.add_argument("--output", required=True, help="Markdown report path.")
    parser.add_argument("--csv-output", default=None, help="Optional detailed CSV output path.")
    parser.add_argument("--title", default="长线股票池质量审计", help="Report title.")
    parser.add_argument("--quiet", action="store_true", help="Reduce selection logs during large audits.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pool, daily = collect_longterm_pool(
        start=args.start,
        end=args.end,
        longterm_profile=args.longterm_profile,
        cache_dir=args.cache_dir,
        sample_step=args.sample_step,
        forward_days=args.forward_days,
        quiet=args.quiet,
    )
    quality = calculate_forward_quality(pool, daily, args.forward_days)
    report = build_report(quality, args.forward_days, args.title)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    if args.csv_output:
        csv_output = Path(args.csv_output)
        csv_output.parent.mkdir(parents=True, exist_ok=True)
        quality.to_csv(csv_output, index=False, encoding="utf-8-sig")
    print(f"Report written: {output}")
    print("\n".join(report.splitlines()[:8]))


if __name__ == "__main__":
    main()
