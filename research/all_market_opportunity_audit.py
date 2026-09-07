from __future__ import annotations

import argparse
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd


CODE_COLUMNS = ("ts_code", "code", "stock_code")
DATE_COLUMNS = ("trade_date", "signal_date", "select_date", "date")


def _date_text(series: pd.Series) -> pd.Series:
    return series.astype(str).str.replace("-", "", regex=False).str.replace(".0", "", regex=False).str[:8]


def _read_parquet(path: Path) -> pd.DataFrame:
    try:
        return pd.read_parquet(path)
    except Exception:
        return pd.DataFrame()


def _available_dates(cache_dir: Path, start: str, end: str) -> list[str]:
    daily_dir = cache_dir / "daily"
    return sorted(
        path.stem
        for path in daily_dir.glob("*.parquet")
        if start <= path.stem <= end
    )


def _load_daily_maps(cache_dir: Path, dates: list[str]) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    daily: dict[str, pd.DataFrame] = {}
    basic: dict[str, pd.DataFrame] = {}
    for date in dates:
        frame = _read_parquet(cache_dir / "daily" / f"{date}.parquet")
        if not frame.empty and "ts_code" in frame.columns:
            frame = frame.copy()
            frame["ts_code"] = frame["ts_code"].astype(str)
            daily[date] = frame.drop_duplicates("ts_code").set_index("ts_code")

        frame = _read_parquet(cache_dir / "daily_basic" / f"{date}.parquet")
        if not frame.empty and "ts_code" in frame.columns:
            frame = frame.copy()
            frame["ts_code"] = frame["ts_code"].astype(str)
            basic[date] = frame.drop_duplicates("ts_code").set_index("ts_code")
    return daily, basic


def _load_stock_info(cache_dir: Path) -> pd.DataFrame:
    frame = _read_parquet(cache_dir / "stock_basic.parquet")
    if frame.empty or "ts_code" not in frame.columns:
        return pd.DataFrame(columns=["name", "industry", "list_date"])
    frame = frame.copy()
    frame["ts_code"] = frame["ts_code"].astype(str)
    for column in ("name", "industry", "list_date"):
        if column not in frame.columns:
            frame[column] = ""
    frame["list_date"] = _date_text(frame["list_date"])
    return frame.drop_duplicates("ts_code").set_index("ts_code")[["name", "industry", "list_date"]]


def _load_recommendations(data_dir: Path) -> tuple[set[tuple[str, str]], list[str]]:
    recommendations: set[tuple[str, str]] = set()
    sources: list[str] = []
    # 推荐只能来自正式信号库；stock_history.db 是行情仓库，绝不能按日期+代码误判为推荐。
    db_path = data_dir / "stock_signals.db"
    if not db_path.exists():
        return recommendations, sources
    try:
        connection = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    except Exception:
        return recommendations, sources
    try:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "signal_pool" not in tables:
            return recommendations, sources
        rows = connection.execute(
            "SELECT trade_date, ts_code FROM signal_pool "
            "WHERE mode='short' AND trade_date IS NOT NULL AND ts_code IS NOT NULL"
        ).fetchall()
        for date, code in rows:
            date = str(date).replace("-", "")[:8]
            code = str(code).strip()
            if len(date) == 8 and code:
                recommendations.add((date, code))
        sources.append(f"{db_path.name}/signal_pool(short):{len(rows)}")
    finally:
        connection.close()
    return recommendations, sources


def _index_regime_proxy(cache_dir: Path, dates: list[str]) -> dict[str, str]:
    rows: list[pd.DataFrame] = []
    for date in dates:
        frame = _read_parquet(cache_dir / "index_daily" / f"{date}.parquet")
        if frame.empty or "ts_code" not in frame.columns:
            continue
        scoped = frame[frame["ts_code"].astype(str) == "000300.SH"].copy()
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
    regimes: dict[str, str] = {}
    for row in index.itertuples():
        if pd.isna(row.ma60) or pd.isna(row.ma20) or pd.isna(row.ma60_slope):
            regimes[str(row.trade_date)] = "UNKNOWN"
            continue
        long_bull = row.close >= row.ma60 and row.ma60_slope >= 0
        short_up = row.close >= row.ma20
        if long_bull and short_up:
            regime = "BULL_TREND"
        elif long_bull:
            regime = "BULL_PULLBACK"
        elif short_up:
            regime = "BEAR_BOUNCE"
        else:
            regime = "BEAR_TREND"
        regimes[str(row.trade_date)] = regime
    return regimes


def _series(frame: pd.DataFrame, column: str) -> pd.Series:
    if frame.empty or column not in frame.columns:
        return pd.Series(dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce")


def _future_slice(
    base: pd.DataFrame,
    daily: dict[str, pd.DataFrame],
    future_dates: list[str],
) -> pd.DataFrame:
    result = base.copy()
    entry_date = future_dates[0]
    entry = daily[entry_date]
    result["entry_date"] = entry_date
    result["entry_open"] = _series(entry, "open").reindex(result.index)
    result["next_gap_pct"] = (
        result["entry_open"] / pd.to_numeric(result["close"], errors="coerce") - 1
    ) * 100

    highs = []
    lows = []
    for date in future_dates[:8]:
        frame = daily[date]
        highs.append(_series(frame, "high").rename(date))
        lows.append(_series(frame, "low").rename(date))
    result["mfe_8d"] = (pd.concat(highs, axis=1).max(axis=1).reindex(result.index) / result["entry_open"] - 1) * 100
    result["mae_8d"] = (pd.concat(lows, axis=1).min(axis=1).reindex(result.index) / result["entry_open"] - 1) * 100

    for horizon in (3, 5, 8):
        exit_date = future_dates[horizon - 1]
        exit_close = _series(daily[exit_date], "close").reindex(result.index)
        result[f"exit_{horizon}d_date"] = exit_date
        result[f"ret_{horizon}d"] = (exit_close / result["entry_open"] - 1) * 100
    return result


def build_samples(cache_dir: Path, data_dir: Path, start: str, end: str) -> tuple[pd.DataFrame, dict]:
    all_dates = _available_dates(cache_dir, "19900101", end)
    analysis_dates = [date for date in all_dates if start <= date <= end]
    daily, basic = _load_daily_maps(cache_dir, all_dates)
    valid_dates = [date for date in all_dates if date in daily]
    stock_info = _load_stock_info(cache_dir)
    recommendations, recommendation_sources = _load_recommendations(data_dir)
    regimes = _index_regime_proxy(cache_dir, all_dates)
    date_positions = {date: index for index, date in enumerate(valid_dates)}

    frames: list[pd.DataFrame] = []
    for date in analysis_dates:
        position = date_positions.get(date)
        if position is None or position + 8 >= len(valid_dates):
            continue
        future_dates = valid_dates[position + 1 : position + 9]
        base = daily[date].copy()
        if base.empty:
            continue
        base.index = base.index.astype(str)
        base["signal_date"] = date
        base = _future_slice(base, daily, future_dates)
        day_basic = basic.get(date, pd.DataFrame())
        turnover = _series(day_basic, "turnover_rate")
        volume_ratio = _series(day_basic, "volume_ratio")
        base["turnover_rate"] = turnover.reindex(base.index)
        base["volume_ratio"] = volume_ratio.reindex(base.index)
        base = base.join(stock_info, how="left", rsuffix="_basic")
        frames.append(base.reset_index().rename(columns={"index": "ts_code"}))

    if not frames:
        return pd.DataFrame(), {"recommendation_sources": recommendation_sources}
    samples = pd.concat(frames, ignore_index=True)
    samples["name"] = samples["name"].fillna("").astype(str)
    samples["industry"] = samples["industry"].fillna("未知行业").astype(str)
    samples["pct_chg"] = pd.to_numeric(samples.get("pct_chg"), errors="coerce")
    samples["listed_days"] = (
        pd.to_datetime(samples["signal_date"], format="%Y%m%d", errors="coerce")
        - pd.to_datetime(samples["list_date"], format="%Y%m%d", errors="coerce")
    ).dt.days
    samples["is_tradeable"] = (
        ~samples["name"].str.upper().str.contains("ST|退", regex=True)
        & (samples["listed_days"] >= 60)
        & samples["entry_open"].gt(0)
        & samples["next_gap_pct"].lt(9.5)
    )
    # 用收盘可兑现收益定义机会，不把盘中短暂冲高直接视为可捕捉机会。
    samples["opportunity_score"] = samples[["ret_3d", "ret_5d", "ret_8d"]].max(axis=1)
    samples["quality_opportunity"] = samples["is_tradeable"] & samples["opportunity_score"].ge(8)
    samples["opportunity_rank"] = np.nan
    quality_mask = samples["quality_opportunity"]
    samples.loc[quality_mask, "opportunity_rank"] = (
        samples.loc[quality_mask].groupby("signal_date")["opportunity_score"]
        .rank(method="first", ascending=False)
    )
    # 每天只审计最强20只，和正式策略有限推荐容量进行公平比较。
    samples["is_opportunity"] = samples["quality_opportunity"] & samples["opportunity_rank"].le(20)
    samples["recommended"] = [
        (str(date), str(code)) in recommendations
        for date, code in zip(samples["signal_date"], samples["ts_code"])
    ]
    samples["regime_proxy"] = samples["signal_date"].map(regimes).fillna("UNKNOWN")
    samples["base_pct_ok"] = samples["pct_chg"].between(-5, 7, inclusive="both")
    samples["base_turnover_ok"] = samples["turnover_rate"].between(1, 20, inclusive="both")
    samples["base_gate_ok"] = samples["base_pct_ok"] & samples["base_turnover_ok"]

    def primary_reason(row: pd.Series) -> str:
        if row["recommended"]:
            return "正式推荐已捕捉"
        if row["regime_proxy"] == "BEAR_TREND":
            return "大盘BEAR_TREND门控"
        if pd.isna(row["turnover_rate"]):
            return "缺少换手率数据"
        if row["pct_chg"] > 7:
            return "当日涨幅超过7%"
        if row["pct_chg"] < -5:
            return "当日跌幅超过5%"
        if row["turnover_rate"] < 1:
            return "换手率低于1%"
        if row["turnover_rate"] > 20:
            return "换手率超过20%"
        return "后续技术/板块/评分过滤"

    samples["primary_reason"] = samples.apply(primary_reason, axis=1)
    meta = {
        "recommendation_sources": recommendation_sources,
        "recommendation_pairs": len(recommendations),
        "analysis_dates": sorted(samples["signal_date"].unique()),
        "latest_market_date": valid_dates[-1] if valid_dates else "",
    }
    return samples, meta


def _summary(group: pd.DataFrame, label: str) -> dict:
    return {
        "分组": label,
        "样本数": int(len(group)),
        "平均3日%": round(float(group["ret_3d"].mean()), 2),
        "平均5日%": round(float(group["ret_5d"].mean()), 2),
        "平均8日%": round(float(group["ret_8d"].mean()), 2),
        "平均MFE8%": round(float(group["mfe_8d"].mean()), 2),
        "平均MAE8%": round(float(group["mae_8d"].mean()), 2),
    }


def build_report(samples: pd.DataFrame, meta: dict) -> tuple[str, dict]:
    opportunities = samples[samples["is_opportunity"]].copy()
    captured = opportunities[opportunities["recommended"]]
    base_eligible = opportunities[opportunities["base_gate_ok"]]
    recommendations = samples[samples["recommended"] & samples["is_tradeable"]].copy()
    reason_counts = opportunities["primary_reason"].value_counts().rename_axis("首要漏选环节").reset_index(name="机会数")
    reason_counts["占比%"] = (reason_counts["机会数"] / max(len(opportunities), 1) * 100).round(2)

    regime_rows = []
    for regime, group in opportunities.groupby("regime_proxy"):
        regime_rows.append(
            {
                "市场状态代理": regime,
                "机会数": len(group),
                "占全部机会%": round(len(group) / max(len(opportunities), 1) * 100, 2),
                "基础入口可进入%": round(group["base_gate_ok"].mean() * 100, 2),
                "正式推荐捕捉%": round(group["recommended"].mean() * 100, 2),
            }
        )
    regime_table = pd.DataFrame(regime_rows).sort_values("机会数", ascending=False)

    industry = opportunities.groupby("industry", dropna=False).agg(
        机会数=("ts_code", "size"),
        平均5日收益=("ret_5d", "mean"),
        平均MFE8=("mfe_8d", "mean"),
        正式捕捉数=("recommended", "sum"),
    ).reset_index()
    industry["捕捉率%"] = (industry["正式捕捉数"] / industry["机会数"] * 100).round(2)
    industry = industry.sort_values(["机会数", "平均MFE8"], ascending=False).head(20).round(2)

    daily = opportunities.groupby("signal_date").agg(
        机会数=("ts_code", "size"),
        正式捕捉数=("recommended", "sum"),
        平均5日收益=("ret_5d", "mean"),
        平均MFE8=("mfe_8d", "mean"),
    ).reset_index()
    daily["捕捉率%"] = (daily["正式捕捉数"] / daily["机会数"] * 100).round(2)
    daily = daily.sort_values("signal_date", ascending=False).head(20).round(2)

    comparisons = pd.DataFrame(
        [
            _summary(opportunities, "每日全市场前20机会"),
            _summary(base_eligible, "可通过现有基础入口"),
            _summary(captured, "被正式推荐捕捉"),
            _summary(recommendations, "全部可评价正式推荐"),
        ]
    )
    capture_rate = len(captured) / max(len(opportunities), 1) * 100
    base_rate = len(base_eligible) / max(len(opportunities), 1) * 100
    recommendation_hit_rate = recommendations["is_opportunity"].mean() * 100 if len(recommendations) else 0.0
    lines = [
        "# 全市场机会漏选审计",
        "",
        f"- 生成时间：{datetime.now().isoformat(timespec='seconds')}",
        f"- 行情覆盖：{meta.get('analysis_dates', [''])[0]} 至 {meta.get('latest_market_date', '')}",
        f"- 可评价信号日：{len(meta.get('analysis_dates', []))} 个（末尾8个交易日因前瞻数据不足不评价）",
        f"- 正式推荐数据源：{', '.join(meta.get('recommendation_sources', [])) or '未在数据库中识别到'}",
        "- 口径：T日收盘观察，T+1开盘买入；排除ST/退市、上市不足60天及次日高开9.5%以上的不可执行样本。",
        "- 机会定义：未来3/5/8日收盘收益的最大值至少8%，再按每日全市场排名取前20只；盘中短暂冲高不单独算机会。",
        "- 市场状态为沪深300 MA20/MA60与MA60斜率的代理复算；Override不在本审计中复写，因此只用于定位结构性问题。",
        "",
        "## 核心结论",
        "",
        f"- 每日全市场前20可执行机会：{len(opportunities)} 个；正式推荐捕捉：{len(captured)} 个，召回率 {capture_rate:.2f}%。",
        f"- 仅基础涨跌幅和换手率入口可覆盖 {len(base_eligible)} 个机会，覆盖率 {base_rate:.2f}%。",
        f"- 基础入口之后仍未成为正式推荐：{max(len(base_eligible) - len(captured), 0)} 个，代表市场门控、技术、板块或评分链路的额外损失。",
        f"- 可评价正式推荐：{len(recommendations)} 个，其中进入当日全市场前20机会的比例为 {recommendation_hit_rate:.2f}%。",
        "",
        "## 首要漏选环节",
        "",
        reason_counts.to_markdown(index=False),
        "",
        "## 不同市场状态中的机会",
        "",
        regime_table.to_markdown(index=False) if not regime_table.empty else "（无）",
        "",
        "## 收益质量对比",
        "",
        comparisons.to_markdown(index=False),
        "",
        "## 机会最多的行业",
        "",
        industry.to_markdown(index=False),
        "",
        "## 最近20个可评价信号日",
        "",
        daily.to_markdown(index=False),
        "",
        "## 解释边界",
        "",
        "- 这是漏选诊断，不是把所有事后上涨股票倒推成可交易信号。",
        "- 正式推荐记录以数据库可识别表为准；若数据库未保存某阶段候选，本报告会低估历史捕捉率。",
        "- 下一步应针对占比最高的漏选环节做独立候选层回测，而不是直接取消风控。",
    ]
    stats = {
        "opportunities": len(opportunities),
        "captured": len(captured),
        "capture_rate": round(capture_rate, 2),
        "base_eligible": len(base_eligible),
        "base_coverage_rate": round(base_rate, 2),
        "recommendations_evaluable": len(recommendations),
        "recommendation_hit_rate": round(recommendation_hit_rate, 2),
        "opportunity_performance": _summary(opportunities, "每日全市场前20机会"),
        "recommendation_performance": _summary(recommendations, "全部可评价正式推荐"),
        "recommendation_win_rates": {
            "3日正收益%": round(float(recommendations["ret_3d"].gt(0).mean() * 100), 2) if len(recommendations) else 0.0,
            "5日正收益%": round(float(recommendations["ret_5d"].gt(0).mean() * 100), 2) if len(recommendations) else 0.0,
            "8日正收益%": round(float(recommendations["ret_8d"].gt(0).mean() * 100), 2) if len(recommendations) else 0.0,
            "8日最大浮盈>=5%%": round(float(recommendations["mfe_8d"].ge(5).mean() * 100), 2) if len(recommendations) else 0.0,
        },
        "top_reasons": reason_counts.head(8).to_dict("records"),
        "recommendation_sources": meta.get("recommendation_sources", []),
    }
    return "\n".join(lines) + "\n", stats


def main() -> None:
    parser = argparse.ArgumentParser(description="全市场短线机会漏选审计")
    parser.add_argument("--root", default=".")
    parser.add_argument("--cache-dir", default="data/cache")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--start", default="20260301")
    parser.add_argument("--end", default="99991231")
    parser.add_argument("--output", default="reports/all_market_opportunity_audit_latest.md")
    parser.add_argument("--samples-output", default="reports/all_market_opportunity_audit_latest.csv")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    cache_dir = (root / args.cache_dir).resolve()
    data_dir = (root / args.data_dir).resolve()
    samples, meta = build_samples(cache_dir, data_dir, args.start, args.end)
    if samples.empty:
        raise SystemExit("没有可用行情样本")
    report, stats = build_report(samples, meta)
    output = root / args.output
    samples_output = root / args.samples_output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    samples[samples["is_opportunity"]].to_csv(samples_output, index=False, encoding="utf-8-sig")
    print(stats)


if __name__ == "__main__":
    main()
