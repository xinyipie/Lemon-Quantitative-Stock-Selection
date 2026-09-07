from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from research.all_market_multi_engine_research import (
    _available_dates,
    _build_regimes,
    _load_stock_info,
    build_year_panel,
)


ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "cache"
OUTPUT = ROOT / "reports" / "research" / "full_market_event_research_20260808.md"
FORBIDDEN_SCORE_COLUMNS = {"ret_3d", "ret_5d", "ret_8d", "mfe_8d", "mae_8d", "opportunity_score", "opportunity_rank"}
SCORE_INPUT_COLUMNS = {
    "ret_5",
    "ret_10",
    "ret_20",
    "ret_60",
    "drawdown_20",
    "rsi_14",
    "volatility_20",
    "pct_chg",
    "volume_ratio",
    "turnover_rate",
    "industry_rs_20",
    "close",
    "ma_20",
    "ma_60",
    "prior_high_20",
    "regime",
}


def _rank(frame: pd.DataFrame, value: pd.Series, higher: bool = True) -> pd.Series:
    numeric = pd.to_numeric(value, errors="coerce")
    return numeric.groupby(frame["trade_date"]).rank(pct=True, ascending=higher, method="average") * 100


def _score(frame: pd.DataFrame, terms: list[tuple[pd.Series, float, bool]]) -> pd.Series:
    total = pd.Series(0.0, index=frame.index)
    for values, weight, higher in terms:
        total += _rank(frame, values, higher=higher).fillna(50.0) * weight
    return total.round(4)


def build_event_candidates(panel: pd.DataFrame) -> pd.DataFrame:
    p = panel.copy()
    numeric = SCORE_INPUT_COLUMNS - {"regime"}
    for column in numeric:
        if column in p.columns:
            p[column] = pd.to_numeric(p[column], errors="coerce")
    tradeable = p["tradeable"].astype(str).str.lower().isin(["true", "1"])
    liquid = p["turnover_rate"].between(1, 20) & p["entry_gap_pct"].between(-4, 6)
    risk_on = ~p["regime"].astype(str).eq("BEAR_TREND")
    frames: list[pd.DataFrame] = []

    trend_mask = (
        tradeable & liquid & risk_on
        & (p["close"] > p["ma_20"]) & (p["ma_20"] > p["ma_60"])
        & p["ret_20"].between(8, 40) & p["drawdown_20"].between(4, 15)
        & p["pct_chg"].between(-3, 2) & p["volume_ratio"].between(0.5, 1.6)
        & (p["industry_rs_20"] > -5)
    )
    trend = p[trend_mask].copy()
    if not trend.empty:
        trend["event"] = "trend_pullback"
        trend["event_score"] = _score(
            trend,
            [
                (trend["industry_rs_20"], 0.25, True),
                (trend["ret_20"], 0.20, True),
                (-(trend["drawdown_20"] - 8).abs(), 0.20, True),
                (trend["volatility_20"], 0.15, False),
                (trend["turnover_rate"], 0.10, False),
                (-(trend["volume_ratio"] - 0.9).abs(), 0.10, True),
            ],
        )
        frames.append(trend)

    repair_mask = (
        tradeable & liquid
        & p["ret_5"].between(-20, -5) & p["ret_20"].between(-35, 15)
        & p["rsi_14"].between(22, 42) & p["pct_chg"].between(0.5, 7)
        & p["volume_ratio"].between(0.8, 3.0) & (p["volatility_20"] < 6)
    )
    repair = p[repair_mask].copy()
    if not repair.empty:
        repair["event"] = "oversold_repair"
        repair["event_score"] = _score(
            repair,
            [
                (repair["ret_5"], 0.20, False),
                (repair["pct_chg"], 0.20, True),
                (repair["rsi_14"], 0.15, False),
                (repair["volatility_20"], 0.15, False),
                (repair["industry_rs_20"], 0.20, True),
                (-(repair["volume_ratio"] - 1.5).abs(), 0.10, True),
            ],
        )
        frames.append(repair)

    breakout_mask = (
        tradeable & liquid & risk_on
        & (p["close"] >= p["prior_high_20"] * 0.99)
        & (p["close"] > p["ma_20"]) & (p["ma_20"] > p["ma_60"])
        & p["ret_20"].between(5, 35) & (p["volatility_20"] <= 3.5)
        & p["pct_chg"].between(1, 7) & p["volume_ratio"].between(1.1, 3.0)
        & (p["industry_rs_20"] > -5)
    )
    breakout = p[breakout_mask].copy()
    if not breakout.empty:
        breakout["event"] = "quiet_breakout"
        breakout["event_score"] = _score(
            breakout,
            [
                (breakout["industry_rs_20"], 0.25, True),
                (breakout["ret_20"], 0.20, True),
                (breakout["volatility_20"], 0.20, False),
                (breakout["turnover_rate"], 0.15, False),
                (breakout["volume_ratio"], 0.10, True),
                (breakout["pct_chg"], 0.10, False),
            ],
        )
        frames.append(breakout)

    leader_mask = (
        tradeable & liquid & risk_on
        & (p["close"] > p["ma_20"]) & (p["ma_20"] > p["ma_60"])
        & p["ret_20"].between(25, 80) & p["ret_60"].between(30, 120)
        & p["drawdown_20"].between(0, 8) & p["rsi_14"].between(60, 90)
        & p["pct_chg"].between(-1, 7) & p["volume_ratio"].between(0.9, 2.5)
        & (p["industry_rs_20"] > 10)
    )
    leader = p[leader_mask].copy()
    if not leader.empty:
        leader["event"] = "leader_continuation"
        leader["event_score"] = _score(
            leader,
            [
                (leader["industry_rs_20"], 0.30, True),
                (leader["ret_20"], 0.20, True),
                (leader["ret_60"], 0.15, True),
                (leader["drawdown_20"], 0.15, False),
                (leader["turnover_rate"], 0.10, False),
                (-(leader["volume_ratio"] - 1.3).abs(), 0.10, True),
            ],
        )
        frames.append(leader)

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).drop_duplicates(["trade_date", "event", "ts_code"])


def select_topn(frame: pd.DataFrame, topn: int) -> pd.DataFrame:
    return (
        frame.sort_values(["trade_date", "event", "event_score", "ts_code"], ascending=[True, True, False, True])
        .groupby(["trade_date", "event"], group_keys=False)
        .head(topn)
        .drop_duplicates(["trade_date", "event", "ts_code"])
        .copy()
    )


def _metrics(frame: pd.DataFrame, cost: float) -> dict[str, float]:
    if frame.empty:
        return {"trades": 0, "avg": np.nan, "win_rate": np.nan, "profit_factor": np.nan, "positive_years": 0, "years": 0}
    values = pd.to_numeric(frame["ret_5d"], errors="coerce").dropna() - cost
    gains = values[values > 0].sum()
    losses = -values[values < 0].sum()
    work = frame.loc[values.index].copy()
    work["net"] = values
    yearly = work.assign(year=work["trade_date"].astype(str).str[:4]).groupby("year")["net"].mean()
    return {
        "trades": int(len(values)),
        "avg": float(values.mean()),
        "win_rate": float((values > 0).mean()),
        "profit_factor": float(gains / losses) if losses > 0 else np.inf,
        "positive_years": int((yearly > 0).sum()),
        "years": int(len(yearly)),
    }


def _period(frame: pd.DataFrame, start: int, end: int) -> pd.DataFrame:
    year = frame["trade_date"].astype(str).str[:4].astype(int)
    return frame[year.between(start, end)]


def _max_drawdown(values: pd.Series) -> float:
    equity = (1 + pd.to_numeric(values, errors="coerce").fillna(0) / 100).cumprod()
    return float((equity / equity.cummax() - 1).min() * 100) if len(equity) else np.nan


def _sleeve_metrics(frame: pd.DataFrame, cost: float) -> tuple[int, float, float]:
    daily = frame.groupby("trade_date", as_index=False)["ret_5d"].mean().sort_values("trade_date")
    daily["net"] = daily["ret_5d"] - cost
    rows = []
    for offset in range(5):
        sleeve = daily.iloc[offset::5]
        rows.append((float(sleeve["net"].mean()), _max_drawdown(sleeve["net"])))
    positive = sum(avg > 0 for avg, _ in rows)
    return positive, float(np.median([dd for _, dd in rows])), float(min(dd for _, dd in rows))


def _bootstrap(frame: pd.DataFrame, cost: float, repetitions: int = 4000) -> float:
    daily = frame.groupby("trade_date")["ret_5d"].mean().sort_index().to_numpy(float) - cost
    if len(daily) < 20:
        return np.nan
    rng = np.random.default_rng(20260808)
    starts = np.arange(len(daily) - 19)
    means = []
    blocks = int(np.ceil(len(daily) / 20))
    for _ in range(repetitions):
        sample = np.concatenate([daily[start : start + 20] for start in rng.choice(starts, blocks, replace=True)])[: len(daily)]
        means.append(sample.mean())
    return float((np.asarray(means) <= 0).mean())


def run() -> None:
    dates = _available_dates(CACHE, "20160101", "20260630")
    regimes = _build_regimes(CACHE, dates)
    stock_info = _load_stock_info(CACHE)
    selected: list[pd.DataFrame] = []
    for year in range(2016, 2027):
        panel = build_year_panel(CACHE, stock_info, regimes, dates, year, f"{year}0101", "20260630" if year == 2026 else f"{year}1231")
        events = build_event_candidates(panel)
        if not events.empty:
            selected.append(select_topn(events, 5))
        print(f"year={year} panel={len(panel)} events={len(events)}")
    all_selected = pd.concat(selected, ignore_index=True) if selected else pd.DataFrame()
    rows = []
    yearly_rows = []
    for event in sorted(all_selected["event"].unique()):
        event_frame = all_selected[all_selected["event"].eq(event)]
        for topn in (1, 3, 5):
            chosen = select_topn(event_frame, topn)
            train = _metrics(_period(chosen, 2016, 2021), 0.25)
            validation = _metrics(_period(chosen, 2022, 2024), 0.25)
            recent = _metrics(_period(chosen, 2025, 2026), 0.25)
            stress = _metrics(_period(chosen, 2022, 2024), 0.35)
            validation_frame = _period(chosen, 2022, 2024)
            positive_sleeves, median_dd, worst_dd = _sleeve_metrics(validation_frame, 0.25)
            bootstrap_p = _bootstrap(validation_frame, 0.25)
            row = {
                "event": event,
                "topn": topn,
                **{f"train_{key}": value for key, value in train.items()},
                **{f"validation_{key}": value for key, value in validation.items()},
                **{f"recent_{key}": value for key, value in recent.items()},
                "stress_avg": stress["avg"],
                "stress_pf": stress["profit_factor"],
                "positive_sleeves": positive_sleeves,
                "median_dd": median_dd,
                "worst_dd": worst_dd,
                "bootstrap_p": bootstrap_p,
            }
            rows.append(row)
            for year, group in chosen.groupby(chosen["trade_date"].astype(str).str[:4]):
                yearly_rows.append({"event": event, "topn": topn, "year": year, **_metrics(group, 0.25)})
    result = pd.DataFrame(rows)
    yearly = pd.DataFrame(yearly_rows)
    result["strict_pass"] = (
        (result["train_avg"] > 0)
        & (result["train_profit_factor"] > 1.05)
        & (result["train_positive_years"] >= 4)
        & (result["validation_trades"] >= 120)
        & (result["validation_avg"] > 0.25)
        & (result["validation_profit_factor"] > 1.15)
        & (result["validation_positive_years"] == 3)
        & (result["recent_avg"] > 0)
        & (result["recent_positive_years"] >= 1)
        & (result["stress_avg"] > 0)
        & (result["stress_pf"] > 1.10)
        & (result["positive_sleeves"] >= 4)
        & (result["median_dd"] >= -25)
        & (result["bootstrap_p"] < 0.10)
    )
    # TopN 邻域必须至少有另一档验证三年为正。
    for index, row in result.iterrows():
        neighbors = result[(result["event"].eq(row["event"])) & (~result["topn"].eq(row["topn"]))]
        neighbor_pass = ((neighbors["validation_positive_years"] == 3) & (neighbors["validation_profit_factor"] > 1.10)).any()
        result.loc[index, "neighbor_pass"] = bool(neighbor_pass)
        result.loc[index, "strict_pass"] = bool(row["strict_pass"] and neighbor_pass)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUTPUT.with_name(OUTPUT.stem + "_summary.csv"), index=False, encoding="utf-8-sig")
    yearly.to_csv(OUTPUT.with_name(OUTPUT.stem + "_yearly.csv"), index=False, encoding="utf-8-sig")
    all_selected.to_csv(OUTPUT.with_name(OUTPUT.stem + "_selected_top5.csv"), index=False, encoding="utf-8-sig")
    lines = [
        "# 全市场事件型短线研究",
        "",
        "## 总结",
        "",
        f"- 严格通过组合数：{int(result['strict_pass'].sum())}。",
        "- 所有排名只使用信号日字段，未来收益仅用于本页评价。",
        "",
        result.sort_values(["strict_pass", "validation_profit_factor", "validation_avg"], ascending=False).to_markdown(index=False, floatfmt=".4f"),
        "",
        "## 逐年",
        "",
        yearly.to_markdown(index=False, floatfmt=".4f"),
    ]
    OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    print(result.sort_values(["strict_pass", "validation_profit_factor"], ascending=False).to_string(index=False))
    print(f"wrote={OUTPUT}")


if __name__ == "__main__":
    run()
