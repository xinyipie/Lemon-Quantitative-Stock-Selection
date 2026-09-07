from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd


ENGINE_LABELS = {
    "pullback": "趋势回调",
    "breakout": "放量突破",
    "reversal": "超跌修复",
    "balanced_top1": "三引擎各Top1",
}

SPLITS = {
    "train_2016_2021": ("20160101", "20211231"),
    "validation_2022_2024": ("20220101", "20241231"),
    "sealed_2025_2026H1": ("20250101", "20260630"),
}


def _read_parquet(path: Path, columns: list[str] | None = None) -> pd.DataFrame:
    try:
        return pd.read_parquet(path, columns=columns)
    except Exception:
        try:
            frame = pd.read_parquet(path)
            return frame[[column for column in (columns or frame.columns) if column in frame.columns]]
        except Exception:
            return pd.DataFrame()


def _available_dates(cache_dir: Path, start: str, end: str) -> list[str]:
    return sorted(
        path.stem
        for path in (cache_dir / "daily").glob("*.parquet")
        if start <= path.stem <= end
    )


def _load_stock_info(cache_dir: Path) -> pd.DataFrame:
    frame = _read_parquet(cache_dir / "stock_basic.parquet")
    if frame.empty or "ts_code" not in frame.columns:
        return pd.DataFrame(columns=["name", "industry"])
    for column in ("name", "industry"):
        if column not in frame.columns:
            frame[column] = ""
    frame["ts_code"] = frame["ts_code"].astype(str)
    return frame.drop_duplicates("ts_code").set_index("ts_code")[["name", "industry"]]


def _load_daily(cache_dir: Path, dates: list[str]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    columns = ["ts_code", "open", "high", "low", "close", "pre_close", "pct_chg", "vol", "amount"]
    for date in dates:
        frame = _read_parquet(cache_dir / "daily" / f"{date}.parquet", columns)
        if frame.empty or "ts_code" not in frame.columns:
            continue
        frame = frame.copy()
        frame["trade_date"] = date
        frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _load_daily_basic(cache_dir: Path, dates: list[str]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    columns = ["ts_code", "turnover_rate", "volume_ratio", "circ_mv"]
    for date in dates:
        frame = _read_parquet(cache_dir / "daily_basic" / f"{date}.parquet", columns)
        if frame.empty or "ts_code" not in frame.columns:
            continue
        frame = frame.copy()
        frame["trade_date"] = date
        frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _rolling_sum(grouped, series_name: str, window: int) -> pd.Series:
    return (
        grouped[series_name]
        .rolling(window, min_periods=window)
        .sum()
        .reset_index(level=0, drop=True)
    )


def _rolling_mean(grouped, series_name: str, window: int) -> pd.Series:
    return (
        grouped[series_name]
        .rolling(window, min_periods=window)
        .mean()
        .reset_index(level=0, drop=True)
    )


def _rolling_max_prev(grouped, series_name: str, window: int) -> pd.Series:
    shifted = grouped[series_name].shift(1)
    return (
        shifted.groupby(grouped.obj["ts_code"], sort=False)
        .rolling(window, min_periods=window)
        .max()
        .reset_index(level=0, drop=True)
    )


def _build_regimes(cache_dir: Path, dates: list[str]) -> dict[str, str]:
    rows: list[pd.DataFrame] = []
    for date in dates:
        frame = _read_parquet(
            cache_dir / "index_daily" / f"{date}.parquet",
            ["ts_code", "close"],
        )
        if frame.empty or "ts_code" not in frame.columns:
            continue
        scoped = frame[frame["ts_code"].astype(str).eq("000300.SH")].copy()
        if scoped.empty:
            continue
        scoped["trade_date"] = date
        rows.append(scoped[["trade_date", "close"]])
    if not rows:
        return {}
    index = pd.concat(rows, ignore_index=True).sort_values("trade_date")
    index["close"] = pd.to_numeric(index["close"], errors="coerce")
    index["ma20"] = index["close"].rolling(20).mean()
    index["ma60"] = index["close"].rolling(60).mean()
    index["ma60_slope"] = index["ma60"].pct_change(5)
    result: dict[str, str] = {}
    for row in index.itertuples():
        if pd.isna(row.ma20) or pd.isna(row.ma60) or pd.isna(row.ma60_slope):
            result[str(row.trade_date)] = "UNKNOWN"
        elif row.close >= row.ma60 and row.ma60_slope >= 0 and row.close >= row.ma20:
            result[str(row.trade_date)] = "BULL_TREND"
        elif row.close >= row.ma60 and row.ma60_slope >= 0:
            result[str(row.trade_date)] = "BULL_PULLBACK"
        elif row.close >= row.ma20:
            result[str(row.trade_date)] = "BEAR_BOUNCE"
        else:
            result[str(row.trade_date)] = "BEAR_TREND"
    return result


def _future_path(panel: pd.DataFrame, grouped) -> pd.DataFrame:
    entry_open = grouped["open"].shift(-1)
    # T 日收盘选股、T+1 开盘成交：跳空基准应直接使用 T 日收盘价。
    # 部分历史缓存没有 pre_close，依赖该字段会把全部样本误判为不可交易。
    entry_pre_close = panel["close"]
    entry_close = grouped["close"].shift(-1)
    panel["entry_open"] = entry_open
    panel["entry_gap_pct"] = (entry_open / entry_pre_close - 1) * 100

    day1_factor = entry_close / entry_open
    future_log_returns: dict[int, pd.Series] = {}
    for horizon in range(2, 9):
        future_log_returns[horizon] = grouped["log_return"].shift(-horizon)

    for horizon in (3, 5, 8):
        log_sum = sum(future_log_returns[index] for index in range(2, horizon + 1))
        panel[f"ret_{horizon}d"] = (day1_factor * np.exp(log_sum) - 1) * 100

    path_highs = []
    path_lows = []
    cumulative_close = pd.Series(1.0, index=panel.index)
    for horizon in range(1, 9):
        day_open = grouped["open"].shift(-horizon)
        day_high = grouped["high"].shift(-horizon)
        day_low = grouped["low"].shift(-horizon)
        # 未来第 N 日的昨收，就是未来第 N-1 日的收盘价。
        day_pre_close = grouped["close"].shift(-(horizon - 1))
        if horizon == 1:
            path_highs.append(day_high / day_open - 1)
            path_lows.append(day_low / day_open - 1)
            cumulative_close = grouped["close"].shift(-1) / day_open
        else:
            path_highs.append(cumulative_close * (day_high / day_pre_close) - 1)
            path_lows.append(cumulative_close * (day_low / day_pre_close) - 1)
            cumulative_close = cumulative_close * np.exp(grouped["log_return"].shift(-horizon))
    panel["mfe_8d"] = pd.concat(path_highs, axis=1).max(axis=1) * 100
    panel["mae_8d"] = pd.concat(path_lows, axis=1).min(axis=1) * 100
    return panel


def _signal_day_tradeable(panel: pd.DataFrame) -> pd.Series:
    """只使用信号日及次日开盘已知信息判断样本是否可交易。"""
    # 未来收益是否齐全只决定对应持有期能否进入统计，不能反向决定信号日资格。
    return (
        ~panel["name"].astype(str).str.upper().str.contains("ST|退", regex=True, na=False)
        & panel["history_count"].ge(60)
        & panel["entry_open"].gt(0)
        & panel["entry_gap_pct"].lt(9.5)
        & panel["turnover_rate"].notna()
    )

def build_year_panel(
    cache_dir: Path,
    stock_info: pd.DataFrame,
    regimes: dict[str, str],
    all_dates: list[str],
    year: int,
    start: str,
    end: str,
) -> pd.DataFrame:
    target_dates = [date for date in all_dates if start <= date <= end and date.startswith(str(year))]
    if not target_dates:
        return pd.DataFrame()
    first_pos = all_dates.index(target_dates[0])
    last_pos = all_dates.index(target_dates[-1])
    # 干净研究库要求至少 120 个历史交易日；预热窗口必须覆盖该门槛，
    # 否则每个自然年年初都会被错误丢弃约 50 个交易日。
    chunk_dates = all_dates[max(0, first_pos - 130) : min(len(all_dates), last_pos + 9)]
    panel = _load_daily(cache_dir, chunk_dates)
    if panel.empty:
        return panel
    panel["ts_code"] = panel["ts_code"].astype(str)
    numeric_columns = ["open", "high", "low", "close", "pre_close", "pct_chg", "vol", "amount"]
    for column in numeric_columns:
        panel[column] = pd.to_numeric(panel.get(column), errors="coerce")
    panel = panel.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    panel["log_return"] = np.log1p(panel["pct_chg"].clip(lower=-99.0) / 100.0)
    grouped = panel.groupby("ts_code", sort=False)
    panel["history_count"] = grouped.cumcount() + 1
    panel["synthetic_close"] = np.exp(grouped["log_return"].cumsum())
    grouped = panel.groupby("ts_code", sort=False)

    for window in (5, 10, 20, 60):
        panel[f"ret_{window}"] = (np.exp(_rolling_sum(grouped, "log_return", window)) - 1) * 100
    for window in (5, 10, 20, 60):
        panel[f"ma_{window}"] = _rolling_mean(grouped, "synthetic_close", window)
    panel["prior_high_20"] = _rolling_max_prev(grouped, "synthetic_close", 20)
    panel["drawdown_20"] = (1 - panel["synthetic_close"] / panel["prior_high_20"]) * 100

    delta = grouped["synthetic_close"].diff()
    panel["gain"] = delta.clip(lower=0)
    panel["loss"] = (-delta.clip(upper=0))
    grouped = panel.groupby("ts_code", sort=False)
    avg_gain = _rolling_mean(grouped, "gain", 14)
    avg_loss = _rolling_mean(grouped, "loss", 14)
    rs = avg_gain / avg_loss.replace(0, np.nan)
    panel["rsi_14"] = (100 - 100 / (1 + rs)).fillna(50)
    panel["volatility_20"] = (
        grouped["pct_chg"].rolling(20, min_periods=20).std().reset_index(level=0, drop=True)
    )
    panel = _future_path(panel, grouped)

    panel = panel[panel["trade_date"].isin(target_dates)].copy()
    basic = _load_daily_basic(cache_dir, target_dates)
    if not basic.empty:
        basic["ts_code"] = basic["ts_code"].astype(str)
        panel = panel.merge(basic, on=["trade_date", "ts_code"], how="left")
    else:
        panel["turnover_rate"] = np.nan
        panel["volume_ratio"] = np.nan
        panel["circ_mv"] = np.nan

    panel = panel.join(stock_info, on="ts_code")
    panel["name"] = panel["name"].fillna("").astype(str)
    panel["industry"] = panel["industry"].fillna("未知行业").astype(str)
    panel["regime"] = panel["trade_date"].map(regimes).fillna("UNKNOWN")
    industry_ret = panel.groupby(["trade_date", "industry"])["ret_20"].transform("median")
    panel["industry_rs_20"] = panel["ret_20"] - industry_ret
    panel["tradeable"] = _signal_day_tradeable(panel)
    panel["opportunity_score"] = panel[["ret_3d", "ret_5d", "ret_8d"]].max(axis=1)
    eligible = panel["tradeable"] & panel["opportunity_score"].ge(8)
    panel["opportunity_rank"] = np.nan
    panel.loc[eligible, "opportunity_rank"] = (
        panel.loc[eligible].groupby("trade_date")["opportunity_score"]
        .rank(method="first", ascending=False)
    )
    panel["top20_opportunity"] = eligible & panel["opportunity_rank"].le(20)
    return panel


def _engine_masks(panel: pd.DataFrame) -> dict[str, tuple[pd.Series, pd.Series]]:
    common = panel["tradeable"] & panel["amount"].fillna(0).gt(0)

    pullback = (
        common
        & panel["synthetic_close"].gt(panel["ma_20"])
        & panel["ma_20"].gt(panel["ma_60"])
        & panel["ret_20"].between(5, 35)
        & panel["drawdown_20"].between(2, 12)
        & panel["pct_chg"].between(-4, 3)
        & panel["volume_ratio"].between(0.5, 1.8)
        & panel["turnover_rate"].between(1, 20)
    )
    pullback_score = (
        panel["ret_20"] * 0.25
        + panel["industry_rs_20"] * 0.45
        - (panel["drawdown_20"] - 6).abs() * 0.8
        - panel["pct_chg"].abs() * 0.25
        - panel["volatility_20"].fillna(0) * 0.2
    )

    breakout = (
        common
        & panel["synthetic_close"].ge(panel["prior_high_20"] * 0.98)
        & panel["synthetic_close"].gt(panel["ma_20"])
        & panel["ma_20"].gt(panel["ma_60"])
        & panel["ret_20"].between(8, 50)
        & panel["pct_chg"].between(1, 9.5)
        & panel["volume_ratio"].between(1.2, 5)
        & panel["turnover_rate"].between(1, 30)
    )
    breakout_score = (
        panel["ret_20"] * 0.35
        + panel["industry_rs_20"] * 0.45
        + panel["volume_ratio"].clip(upper=5) * 2
        + panel["pct_chg"] * 0.5
        - panel["volatility_20"].fillna(0) * 0.25
    )

    reversal = (
        common
        & panel["ret_5"].between(-25, -5)
        & panel["ret_20"].between(-35, 10)
        & panel["rsi_14"].le(38)
        & panel["pct_chg"].between(0.5, 7)
        & panel["volume_ratio"].between(0.8, 4)
        & panel["turnover_rate"].between(1, 25)
    )
    reversal_score = (
        -panel["ret_5"] * 0.6
        - panel["ret_20"].clip(upper=0) * 0.2
        + (40 - panel["rsi_14"]) * 0.4
        + panel["pct_chg"] * 0.4
        + panel["industry_rs_20"] * 0.15
    )
    return {
        "pullback": (pullback, pullback_score),
        "breakout": (breakout, breakout_score),
        "reversal": (reversal, reversal_score),
    }


def select_engines(panel: pd.DataFrame) -> pd.DataFrame:
    selections: list[pd.DataFrame] = []
    for engine, (mask, score) in _engine_masks(panel).items():
        scoped = panel.loc[mask].copy()
        scoped["engine_score"] = score.loc[scoped.index]
        scoped = scoped.sort_values(
            ["trade_date", "engine_score", "ts_code"],
            ascending=[True, False, True],
        )
        scoped["engine_rank"] = scoped.groupby("trade_date").cumcount() + 1
        scoped = scoped[scoped["engine_rank"].le(10)].copy()
        scoped["engine"] = engine
        selections.append(scoped)
    if not selections:
        return pd.DataFrame()
    return pd.concat(selections, ignore_index=True, sort=False)


def _metrics(group: pd.DataFrame, label: str) -> dict:
    if group.empty:
        return {
            "group": label,
            "signals": 0,
            "active_days": 0,
            "win3_pct": 0.0,
            "win5_pct": 0.0,
            "win8_pct": 0.0,
            "avg3_pct": 0.0,
            "avg5_pct": 0.0,
            "avg8_pct": 0.0,
            "avg_mfe8_pct": 0.0,
            "avg_mae8_pct": 0.0,
            "top20_hits": 0,
            "top20_precision_pct": 0.0,
        }
    return {
        "group": label,
        "signals": int(len(group)),
        "active_days": int(group["trade_date"].nunique()),
        "win3_pct": round(float(group["ret_3d"].gt(0).mean() * 100), 2),
        "win5_pct": round(float(group["ret_5d"].gt(0).mean() * 100), 2),
        "win8_pct": round(float(group["ret_8d"].gt(0).mean() * 100), 2),
        "avg3_pct": round(float(group["ret_3d"].mean()), 2),
        "avg5_pct": round(float(group["ret_5d"].mean()), 2),
        "avg8_pct": round(float(group["ret_8d"].mean()), 2),
        "avg_mfe8_pct": round(float(group["mfe_8d"].mean()), 2),
        "avg_mae8_pct": round(float(group["mae_8d"].mean()), 2),
        "top20_hits": int(group["top20_opportunity"].sum()),
        "top20_precision_pct": round(float(group["top20_opportunity"].mean() * 100), 2),
    }


def summarize(selections: pd.DataFrame, opportunities: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    layers: list[pd.DataFrame] = []
    for top_n in (3, 10):
        scoped = selections[selections["engine_rank"].le(top_n)].copy()
        scoped["layer"] = f"top{top_n}"
        layers.append(scoped)
    top1_union = (
        selections[selections["engine_rank"].eq(1)]
        .sort_values(["trade_date", "engine", "engine_score"], ascending=[True, True, False])
        .drop_duplicates(["trade_date", "ts_code"])
        .copy()
    )
    top1_union["engine"] = "balanced_top1"
    top1_union["layer"] = "top3_capacity"
    layers.append(top1_union)
    combined = pd.concat(layers, ignore_index=True, sort=False)

    summary_rows = []
    segment_rows = []
    regime_rows = []
    for (engine, layer), group in combined.groupby(["engine", "layer"]):
        row = _metrics(group, f"{engine}/{layer}")
        opportunity_scope = opportunities[
            opportunities["trade_date"].between(group["trade_date"].min(), group["trade_date"].max())
        ]
        row["top20_recall_pct"] = round(
            float(group["top20_opportunity"].sum() / max(len(opportunity_scope), 1) * 100), 2
        )
        summary_rows.append(row)
        for split, (start, end) in SPLITS.items():
            scoped = group[group["trade_date"].between(start, end)]
            split_row = _metrics(scoped, f"{engine}/{layer}")
            split_row["split"] = split
            segment_rows.append(split_row)
        for regime, scoped in group.groupby("regime"):
            regime_row = _metrics(scoped, f"{engine}/{layer}")
            regime_row["regime"] = regime
            regime_rows.append(regime_row)
    return pd.DataFrame(summary_rows), pd.DataFrame(segment_rows), pd.DataFrame(regime_rows)


def _yearly(selections: pd.DataFrame) -> pd.DataFrame:
    top3 = selections[selections["engine_rank"].le(3)].copy()
    top3["year"] = top3["trade_date"].str[:4]
    rows = []
    for (engine, year), group in top3.groupby(["engine", "year"]):
        row = _metrics(group, engine)
        row["year"] = year
        rows.append(row)
    return pd.DataFrame(rows)


def _acceptance(segment: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for group, scoped in segment.groupby("group"):
        required = set(SPLITS)
        available = set(scoped.loc[scoped["signals"].ge(80), "split"])
        all_positive = bool((scoped["avg5_pct"] > 0).all()) if len(scoped) == len(SPLITS) else False
        all_win = bool((scoped["win5_pct"] > 50).all()) if len(scoped) == len(SPLITS) else False
        rows.append(
            {
                "group": group,
                "enough_samples_all_splits": required.issubset(available),
                "positive_avg5_all_splits": all_positive,
                "win5_above_50_all_splits": all_win,
                "research_pass": required.issubset(available) and all_positive and all_win,
            }
        )
    return pd.DataFrame(rows)


def build_report(
    summary: pd.DataFrame,
    segment: pd.DataFrame,
    yearly: pd.DataFrame,
    regime: pd.DataFrame,
    acceptance: pd.DataFrame,
    opportunity_count: int,
    date_start: str,
    date_end: str,
) -> str:
    lines = [
        "# 全市场三引擎统一研究",
        "",
        f"- 生成时间：{datetime.now().isoformat(timespec='seconds')}",
        f"- 行情范围：{date_start} 至 {date_end}",
        f"- 每日全市场前20机会样本：{opportunity_count}",
        "- 三套引擎参数在运行前固定，不做网格搜索，不使用未来收益调参。",
        "- 收益使用 pct_chg 复权链，T日收盘观察、T+1开盘买入，降低除权除息失真。",
        "- AI、新闻和历史旧候选池均不参与本研究。",
        "",
        "## 全区间表现",
        "",
        summary.to_markdown(index=False),
        "",
        "## 训练/验证/封存分段",
        "",
        segment.to_markdown(index=False),
        "",
        "## 研究准入",
        "",
        acceptance.to_markdown(index=False),
        "",
        "## 分年度 Top3",
        "",
        yearly.to_markdown(index=False),
        "",
        "## 分市场状态",
        "",
        regime.to_markdown(index=False),
        "",
        "## 解释边界",
        "",
        "- 这是候选生成研究，不代表可直接交易或上线。",
        "- stock_basic 使用当前缓存，退市股票名称信息可能不完整，存在轻微存续偏差。",
        "- 本轮只判断固定规则是否值得继续；未通过准入时不围绕封存结果继续调参。",
    ]
    return "\n".join(lines) + "\n"


def run_research(root: Path, start: str, end: str) -> dict:
    cache_dir = root / "data" / "cache"
    all_dates = _available_dates(cache_dir, "19900101", end)
    if not all_dates:
        raise SystemExit("没有本地日线缓存")
    stock_info = _load_stock_info(cache_dir)
    regimes = _build_regimes(cache_dir, all_dates)
    selections: list[pd.DataFrame] = []
    opportunities: list[pd.DataFrame] = []
    for year in range(int(start[:4]), int(end[:4]) + 1):
        print(f"processing {year}", flush=True)
        panel = build_year_panel(cache_dir, stock_info, regimes, all_dates, year, start, end)
        if panel.empty:
            continue
        selected = select_engines(panel)
        if not selected.empty:
            selections.append(selected)
        opportunities.append(panel[panel["top20_opportunity"]].copy())
    selected_all = pd.concat(selections, ignore_index=True, sort=False) if selections else pd.DataFrame()
    opportunity_all = pd.concat(opportunities, ignore_index=True, sort=False) if opportunities else pd.DataFrame()
    if selected_all.empty:
        raise SystemExit("三套引擎均未生成候选")
    summary, segment, regime = summarize(selected_all, opportunity_all)
    yearly = _yearly(selected_all)
    acceptance = _acceptance(segment)
    return {
        "selected": selected_all,
        "opportunities": opportunity_all,
        "summary": summary,
        "segment": segment,
        "yearly": yearly,
        "regime": regime,
        "acceptance": acceptance,
        "report": build_report(
            summary,
            segment,
            yearly,
            regime,
            acceptance,
            len(opportunity_all),
            start,
            end,
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="真正全市场的趋势回调、突破、反转三引擎研究")
    parser.add_argument("--root", default=".")
    parser.add_argument("--start", default="20160101")
    parser.add_argument("--end", default="20260630")
    parser.add_argument("--output", default="reports/research/all_market_multi_engine_20260807.md")
    parser.add_argument("--trades-output", default="reports/research/all_market_multi_engine_trades_20260807.csv")
    parser.add_argument("--opportunities-output", default="reports/research/all_market_top20_opportunities_20260807.csv")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    result = run_research(root, args.start, args.end)
    output = root / args.output
    trades_output = root / args.trades_output
    opportunities_output = root / args.opportunities_output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(result["report"], encoding="utf-8")
    result["selected"].to_csv(trades_output, index=False, encoding="utf-8-sig")
    result["opportunities"].to_csv(opportunities_output, index=False, encoding="utf-8-sig")
    print("\nSUMMARY")
    print(result["summary"].to_string(index=False))
    print("\nACCEPTANCE")
    print(result["acceptance"].to_string(index=False))


if __name__ == "__main__":
    main()
