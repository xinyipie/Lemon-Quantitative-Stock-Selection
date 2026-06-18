#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Reverse-audit all-market longterm winners and losers before strategy design."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

import pandas as pd


FACTOR_COLUMNS = [
    "ret_20d",
    "ret_60d",
    "price_vs_ma60",
    "drawdown_120d",
    "turnover",
    "volume_ratio",
    "total_mv",
    "circ_mv",
    "pe_ttm",
    "pb",
    "ps_ttm",
    "dv_ratio",
]

DISPLAY_COLUMNS = [
    "select_date",
    "ts_code",
    "name",
    "industry",
    "ret_10d",
    "ret_40d",
    "ret_80d",
    "ret_120d",
    "excess_ret_80d",
    "sample_group",
    "ret_20d",
    "ret_60d",
    "price_vs_ma60",
    "drawdown_120d",
    "turnover",
    "volume_ratio",
    "total_mv",
    "pe_ttm",
    "pb",
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


def _prepare_daily(daily: pd.DataFrame) -> pd.DataFrame:
    data = daily.copy()
    data["trade_date"] = data["trade_date"].astype(str).map(_normalize_date)
    for col in ["open", "high", "low", "close"]:
        if col in data.columns:
            data[col] = pd.to_numeric(data[col], errors="coerce")
    return data.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)


def _prepare_basic(daily_basic: pd.DataFrame) -> pd.DataFrame:
    data = daily_basic.copy()
    if data.empty:
        return data
    data["trade_date"] = data["trade_date"].astype(str).map(_normalize_date)
    rename = {"turnover_rate": "turnover"}
    data = data.rename(columns={k: v for k, v in rename.items() if k in data.columns})
    for col in ["turnover", "volume_ratio", "total_mv", "circ_mv", "pe_ttm", "pb", "ps_ttm", "dv_ratio"]:
        if col in data.columns:
            data[col] = pd.to_numeric(data[col], errors="coerce")
    return data


def _path_metrics(group: pd.DataFrame, select_date: str, horizons: Iterable[int]) -> dict:
    g = group.sort_values("trade_date").reset_index(drop=True)
    dates = g["trade_date"].astype(str).tolist()
    eligible = [i for i, date in enumerate(dates) if date <= select_date]
    if not eligible:
        return {}
    idx = eligible[-1]
    close = float(g.loc[idx, "close"])
    if close <= 0:
        return {}

    out = {"start_close": close}
    if idx >= 20:
        close_20 = float(g.loc[idx - 20, "close"])
        out["ret_20d"] = (close - close_20) / close_20 * 100 if close_20 else None
    if idx >= 60:
        close_60 = float(g.loc[idx - 60, "close"])
        out["ret_60d"] = (close - close_60) / close_60 * 100 if close_60 else None
        ma60 = float(g.loc[idx - 59 : idx, "close"].mean())
        out["price_vs_ma60"] = (close - ma60) / ma60 * 100 if ma60 else None
    lookback_start = max(0, idx - 119)
    high_120 = float(g.loc[lookback_start:idx, "high"].max())
    out["drawdown_120d"] = (high_120 - close) / high_120 * 100 if high_120 else None

    for horizon in horizons:
        end_idx = idx + int(horizon)
        if end_idx >= len(g):
            continue
        window = g.iloc[idx + 1 : end_idx + 1]
        if window.empty:
            continue
        end_close = float(g.loc[end_idx, "close"])
        out[f"ret_{horizon}d"] = (end_close - close) / close * 100
        out[f"mfe_{horizon}d"] = (float(window["high"].max()) - close) / close * 100
        out[f"mae_{horizon}d"] = (float(window["low"].min()) - close) / close * 100
    return out


def _benchmark_lookup(daily: pd.DataFrame, select_dates: list[str], horizons: list[int], benchmark_code: str) -> dict:
    bench = daily[daily["ts_code"] == benchmark_code]
    if bench.empty:
        return {}
    out = {}
    for select_date in sorted(set(select_dates)):
        metrics = _path_metrics(bench, select_date, horizons)
        for horizon in horizons:
            value = metrics.get(f"ret_{horizon}d")
            if value is not None:
                out[(select_date, int(horizon))] = value
    return out


def make_market_samples(
    daily: pd.DataFrame,
    daily_basic: pd.DataFrame,
    select_dates: list[str],
    horizons: list[int] | None = None,
    benchmark_code: str = "000300.SH",
    stock_basic: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build all-market factor snapshots and future path returns for selected dates."""
    horizons = horizons or [10, 40, 80]
    prices = _prepare_daily(daily)
    basics = _prepare_basic(daily_basic)
    if prices.empty:
        return pd.DataFrame()

    name_map = {}
    industry_map = {}
    if stock_basic is not None and not stock_basic.empty:
        if "ts_code" in stock_basic.columns:
            if "name" in stock_basic.columns:
                name_map = stock_basic.set_index("ts_code")["name"].to_dict()
            if "industry" in stock_basic.columns:
                industry_map = stock_basic.set_index("ts_code")["industry"].to_dict()

    grouped = {code: group for code, group in prices.groupby("ts_code")}
    benchmark = _benchmark_lookup(prices, [_normalize_date(d) for d in select_dates], horizons, benchmark_code)
    basic_by_date = {
        date: group.set_index("ts_code")
        for date, group in basics.groupby("trade_date")
    } if not basics.empty else {}

    rows = []
    for select_date in [_normalize_date(d) for d in select_dates]:
        today = prices[prices["trade_date"] == select_date]
        if today.empty:
            continue
        basic_today = basic_by_date.get(select_date, pd.DataFrame())
        for ts_code in today["ts_code"].dropna().unique():
            if ts_code == benchmark_code:
                continue
            metrics = _path_metrics(grouped.get(ts_code, pd.DataFrame()), select_date, horizons)
            if not metrics:
                continue
            row = {
                "select_date": select_date,
                "ts_code": ts_code,
                "name": name_map.get(ts_code, ""),
                "industry": industry_map.get(ts_code, ""),
            }
            row.update(metrics)
            if not basic_today.empty and ts_code in basic_today.index:
                basic_row = basic_today.loc[ts_code]
                if isinstance(basic_row, pd.DataFrame):
                    basic_row = basic_row.iloc[0]
                for col in ["turnover", "volume_ratio", "total_mv", "circ_mv", "pe_ttm", "pb", "ps_ttm", "dv_ratio"]:
                    if col in basic_row.index:
                        row[col] = basic_row[col]
            for horizon in horizons:
                ret = row.get(f"ret_{horizon}d")
                bret = benchmark.get((select_date, int(horizon)))
                if ret is not None and bret is not None:
                    row[f"benchmark_ret_{horizon}d"] = bret
                    row[f"excess_ret_{horizon}d"] = ret - bret
                    row[f"outperform_{horizon}d"] = ret > bret
            rows.append(row)
    return pd.DataFrame(rows)


def read_daily_basic_range(proxy, trade_dates: list[str], fields: str) -> pd.DataFrame:
    """Read daily_basic for multiple dates from LocalDataProxy-compatible objects."""
    frames = []
    for trade_date in trade_dates:
        df = proxy.daily_basic(trade_date=trade_date, fields=fields)
        if not df.empty:
            frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def classify_market_samples(
    df: pd.DataFrame,
    horizon: int = 80,
    winner_ret: float = 20.0,
    winner_excess: float = 5.0,
    loser_ret: float = -10.0,
    loser_excess: float = -10.0,
) -> pd.DataFrame:
    data = df.copy()
    ret_col = f"ret_{horizon}d"
    excess_col = f"excess_ret_{horizon}d"
    if data.empty or ret_col not in data.columns:
        data["sample_group"] = pd.Series(dtype=object)
        return data
    data = data.dropna(subset=[ret_col]).copy()
    if excess_col not in data.columns:
        data[excess_col] = data[ret_col]
    winner = (data[ret_col] >= winner_ret) & (data[excess_col] >= winner_excess)
    loser = (data[ret_col] <= loser_ret) | (data[excess_col] <= loser_excess)
    data["sample_group"] = "中间"
    data.loc[winner, "sample_group"] = "赢家"
    data.loc[loser & ~winner, "sample_group"] = "输家"
    return data


def factor_difference_table(df: pd.DataFrame, factors: list[str] | None = None) -> pd.DataFrame:
    factors = factors or FACTOR_COLUMNS
    winners = df[df.get("sample_group") == "赢家"]
    losers = df[df.get("sample_group") == "输家"]
    rows = []
    for factor in factors:
        if factor not in df.columns:
            continue
        w = pd.to_numeric(winners[factor], errors="coerce").dropna()
        l = pd.to_numeric(losers[factor], errors="coerce").dropna()
        if w.empty or l.empty:
            continue
        rows.append({
            "factor": factor,
            "winner_mean": round(float(w.mean()), 2),
            "loser_mean": round(float(l.mean()), 2),
            "diff": round(float(w.mean() - l.mean()), 2),
            "winner_n": int(len(w)),
            "loser_n": int(len(l)),
        })
    if not rows:
        return pd.DataFrame(columns=["factor", "winner_mean", "loser_mean", "diff", "winner_n", "loser_n"])
    return pd.DataFrame(rows).sort_values("diff", key=lambda s: s.abs(), ascending=False).reset_index(drop=True)


def group_summary(df: pd.DataFrame, column: str, horizon: int = 80) -> pd.DataFrame:
    ret_col = f"ret_{horizon}d"
    if df.empty or column not in df.columns or ret_col not in df.columns:
        return pd.DataFrame()
    rows = []
    for value, group in df.groupby(column, dropna=False):
        valid = group.dropna(subset=[ret_col])
        if valid.empty:
            continue
        rows.append({
            column: value,
            "count": int(len(valid)),
            "winner_count": int((valid["sample_group"] == "赢家").sum()),
            "loser_count": int((valid["sample_group"] == "输家").sum()),
            f"avg_ret_{horizon}d": round(float(valid[ret_col].mean()), 2),
            f"win_rate_{horizon}d": round(float((valid[ret_col] > 0).mean() * 100), 2),
        })
    return pd.DataFrame(rows).sort_values(["winner_count", f"avg_ret_{horizon}d"], ascending=[False, False])


def build_report(df: pd.DataFrame, horizon: int = 80, title: str = "全市场长线赢家画像审计") -> str:
    data = df.copy()
    ret_col = f"ret_{horizon}d"
    valid = data.dropna(subset=[ret_col]) if ret_col in data.columns else pd.DataFrame()
    winners = data[data.get("sample_group") == "赢家"].sort_values(ret_col, ascending=False) if not data.empty else pd.DataFrame()
    losers = data[data.get("sample_group") == "输家"].sort_values(ret_col, ascending=True) if not data.empty else pd.DataFrame()
    diff = factor_difference_table(data)
    by_industry = group_summary(data, "industry", horizon)
    display_cols = [col for col in DISPLAY_COLUMNS if col in data.columns]

    lines = [
        f"# {title}\n\n",
        "## 先看结论\n",
        f"- 本报告不依赖现有策略池，直接从全市场反推未来 `{horizon}` 日赢家/输家画像。\n",
        f"- 有效样本 `{len(valid)}` 个；赢家 `{len(winners)}` 个，输家 `{len(losers)}` 个。\n",
    ]
    if not valid.empty:
        lines.append(f"- 全市场样本 `{horizon}` 日平均收益 `{_fmt_pct(valid[ret_col].mean())}`。\n")
    if not diff.empty:
        top = diff.iloc[0]
        lines.append(
            f"- 赢家/输家差异最大的因子：`{top['factor']}`，差值 `{top['diff']}`。\n"
        )
    lines.extend([
        "\n## 赢家/输家因子差异\n",
        _table(diff, 60),
        "\n## 行业分布\n",
        _table(by_industry, 40),
        "\n## 赢家样本\n",
        _table(winners[display_cols] if display_cols else winners, 40),
        "\n## 输家样本\n",
        _table(losers[display_cols] if display_cols else losers, 40),
    ])
    return "".join(lines)


def collect_market_samples(
    start: str,
    end: str,
    cache_dir: str = "data/cache",
    sample_step: int = 5,
    horizons: list[int] | None = None,
) -> pd.DataFrame:
    from local_data_proxy import LocalDataProxy

    horizons = horizons or [10, 40, 80, 120]
    proxy = LocalDataProxy(cache_dir=cache_dir)
    cal = proxy.trade_cal(exchange="SSE", start_date=start, end_date=end, is_open=1, fields="cal_date")
    select_dates = sorted(cal["cal_date"].astype(str).tolist())[:: max(1, int(sample_step))]
    lookback_start = (datetime.strptime(start, "%Y%m%d") - timedelta(days=260)).strftime("%Y%m%d")
    price_end = (datetime.strptime(end, "%Y%m%d") + timedelta(days=max(horizons) * 2 + 30)).strftime("%Y%m%d")
    daily = proxy.daily(start_date=lookback_start, end_date=price_end, fields="ts_code,trade_date,open,high,low,close")
    basic_fields = "ts_code,trade_date,turnover_rate,volume_ratio,total_mv,circ_mv,pe_ttm,pb,ps_ttm,dv_ratio"
    basic = read_daily_basic_range(proxy, select_dates, basic_fields)
    stock_basic = proxy.stock_basic(fields="ts_code,name,industry")
    benchmark = proxy.index_daily(
        ts_code="000300.SH",
        start_date=lookback_start,
        end_date=price_end,
        fields="ts_code,trade_date,open,high,low,close",
    )
    if not benchmark.empty and "ts_code" not in benchmark.columns:
        benchmark = benchmark.copy()
        benchmark["ts_code"] = "000300.SH"
    if not benchmark.empty:
        daily = pd.concat([daily, benchmark], ignore_index=True)
    return make_market_samples(daily, basic, select_dates, horizons, stock_basic=stock_basic)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit all-market longterm winners and losers.")
    parser.add_argument("--start", required=True, help="Selection start date, YYYYMMDD.")
    parser.add_argument("--end", required=True, help="Selection end date, YYYYMMDD.")
    parser.add_argument("--cache-dir", default="data/cache", help="Local cache directory.")
    parser.add_argument("--forward-days", nargs="+", type=int, default=[10, 40, 80, 120], help="Forward trading-day windows.")
    parser.add_argument("--horizon", type=int, default=80, help="Classification horizon.")
    parser.add_argument("--sample-step", type=int, default=5, help="Use every Nth trading day.")
    parser.add_argument("--winner-ret", type=float, default=20.0, help="Winner minimum forward return.")
    parser.add_argument("--winner-excess", type=float, default=5.0, help="Winner minimum excess return.")
    parser.add_argument("--loser-ret", type=float, default=-10.0, help="Loser maximum forward return.")
    parser.add_argument("--loser-excess", type=float, default=-10.0, help="Loser maximum excess return.")
    parser.add_argument("--output", required=True, help="Markdown report path.")
    parser.add_argument("--csv-output", default=None, help="Optional classified CSV output path.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    samples = collect_market_samples(args.start, args.end, args.cache_dir, args.sample_step, args.forward_days)
    classified = classify_market_samples(
        samples,
        horizon=args.horizon,
        winner_ret=args.winner_ret,
        winner_excess=args.winner_excess,
        loser_ret=args.loser_ret,
        loser_excess=args.loser_excess,
    )
    report = build_report(classified, args.horizon)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    if args.csv_output:
        csv_path = Path(args.csv_output)
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        classified.to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(f"Report written: {output}")
    print(report.split("\n## 赢家/输家因子差异", 1)[0])


if __name__ == "__main__":
    main()
