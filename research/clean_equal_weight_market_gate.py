"""用全市场等权趋势门控低波动动量候选。"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from research.clean_archetype_family import archetype_candidates
from research.clean_financial_relative_confidence import enforce_same_stock_cooldown
from research.clean_moneyflow_overlay import summarize
from research.no_future_signal_pipeline import apply_next_open_execution


ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "data" / "research" / "clean_all_market"
REPORT_DIR = ROOT / "reports" / "research"
YEARS = tuple(range(2016, 2022))
COST_PCT = 0.25

COLUMNS = [
    "ts_code",
    "name",
    "industry",
    "trade_date",
    "close",
    "pct_chg",
    "ret_20",
    "ret_60",
    "ma_20",
    "ma_60",
    "rsi_14",
    "volatility_20",
    "turnover_rate",
    "volume_ratio",
    "industry_rs_20",
    "entry_open",
    "entry_gap_pct",
    "ret_8d",
    "mfe_8d",
    "mae_8d",
]


def add_equal_weight_market_features(frame: pd.DataFrame) -> pd.DataFrame:
    """从T日全市场中位涨跌构造连续等权市场趋势。"""

    work = frame.copy()
    work["trade_date"] = work["trade_date"].astype(str)
    work["above_ma20"] = (work["close"] > work["ma_20"]).astype(float)
    daily = (
        work.groupby("trade_date", as_index=False)
        .agg(
            ew_return=("pct_chg", "median"),
            breadth_ma20=("above_ma20", "mean"),
        )
        .sort_values("trade_date")
    )
    daily["ew_index"] = (1.0 + daily["ew_return"].fillna(0.0) / 100.0).cumprod()
    daily["ew_ma20"] = daily["ew_index"].rolling(20, min_periods=20).mean()
    daily["ew_ma60"] = daily["ew_index"].rolling(60, min_periods=60).mean()
    daily["ew_ma20_change_5d"] = daily["ew_ma20"] - daily["ew_ma20"].shift(5)
    daily["ew_ma60_change_20d"] = daily["ew_ma60"] - daily["ew_ma60"].shift(20)
    daily["breadth_change_5d"] = daily["breadth_ma20"] - daily["breadth_ma20"].shift(5)
    return work.merge(daily, on="trade_date", how="left", validate="many_to_one")


def market_gate(frame: pd.DataFrame, variant: str) -> pd.Series:
    """返回冻结的等权趋势状态。"""

    strict = (
        (frame["ew_index"] > frame["ew_ma20"])
        & (frame["ew_ma20"] > frame["ew_ma60"])
        & (frame["ew_ma60_change_20d"] > 0)
        & (frame["breadth_ma20"] >= 0.50)
    )
    recovery = (
        (frame["ew_index"] > frame["ew_ma20"])
        & (frame["ew_ma20_change_5d"] > 0)
        & (frame["breadth_ma20"] >= 0.55)
        & (frame["breadth_change_5d"] >= 0.03)
    )
    if variant == "baseline":
        return pd.Series(True, index=frame.index)
    if variant == "strict_trend":
        return strict
    if variant == "early_recovery":
        return recovery
    if variant == "adaptive_trend":
        return strict | recovery
    raise ValueError(f"未知版本: {variant}")


def select_variant(enriched: pd.DataFrame, variant: str) -> pd.DataFrame:
    """先锁定市场状态，再按原型分取当日Top1。"""

    candidates = archetype_candidates(enriched, "low_vol_momentum").copy()
    candidates = candidates[market_gate(candidates, variant)].copy()
    selected = (
        candidates.sort_values(
            ["trade_date", "score", "ts_code"],
            ascending=[True, False, True],
            kind="mergesort",
        )
        .groupby("trade_date", group_keys=False)
        .head(1)
        .copy()
    )
    all_dates = sorted(enriched["trade_date"].astype(str).unique().tolist())
    selected = enforce_same_stock_cooldown(selected, all_dates, cooldown_days=8)
    selected = apply_next_open_execution(
        selected,
        cost=COST_PCT,
        outcome_column="ret_8d",
    )
    selected = selected[selected["evaluable"]].copy()
    selected["net_return"] = pd.to_numeric(selected["net_ret"], errors="coerce")
    selected["year"] = selected["trade_date"].str[:4].astype(int)
    selected["variant"] = variant
    return selected


def period_metrics(frame: pd.DataFrame, years: tuple[int, ...]) -> dict:
    """计算发现期或确认期收益与盈亏比。"""

    values = frame.loc[frame["year"].isin(years), "net_return"].dropna()
    gains = float(values[values > 0].sum())
    losses = float(-values[values < 0].sum())
    return {
        "trades": int(len(values)),
        "average_net_return_pct": float(values.mean()) if len(values) else None,
        "profit_factor": gains / losses if losses > 0 else None,
    }


def same_day_universe_edge(selected: pd.DataFrame, enriched: pd.DataFrame) -> float | None:
    """比较信号日候选与当日全市场可评价样本，剔除市场漂移。"""

    benchmark = enriched.groupby("trade_date")["ret_8d"].mean().sub(COST_PCT)
    mapped = selected["trade_date"].map(benchmark)
    if selected.empty or mapped.empty:
        return None
    return float(selected["net_return"].mean() - mapped.mean())


def evaluate(
    summary: dict,
    discovery: dict,
    confirmation: dict,
    edge: float | None,
    baseline: dict,
) -> dict:
    """按预注册标准判定市场门控是否有效。"""

    active_years = [item for item in summary["yearly"].values() if item["trades"] >= 10]
    active_averages = [item["average_net_return_pct"] for item in active_years if item["average_net_return_pct"] is not None]
    checks = {
        "minimum_total_trades": summary["trades"] >= 120,
        "minimum_active_years": len(active_years) >= 5,
        "minimum_average_net_return_pct": (summary["average_net_return_pct"] or -999) >= 0.65,
        "minimum_profit_factor": (summary["profit_factor"] or 0) >= 1.25,
        "minimum_positive_active_years": sum(value > 0 for value in active_averages) >= 4,
        "maximum_worst_active_year_average_pct": bool(active_averages) and min(active_averages) >= -0.50,
        "required_positive_years": all(
            (summary["yearly"][str(year)]["average_net_return_pct"] or -999) > 0
            for year in (2019, 2020, 2021)
        ),
        "minimum_discovery_2016_2018_average_pct": (discovery["average_net_return_pct"] or -999) > 0,
        "minimum_confirmation_2019_2021_average_pct": (confirmation["average_net_return_pct"] or -999) >= 0.65,
        "minimum_confirmation_profit_factor": (confirmation["profit_factor"] or 0) >= 1.25,
        "minimum_edge_vs_same_day_universe_pct": (edge or -999) >= 0.20,
        "minimum_increment_vs_ungated_baseline_pct": (
            (summary["average_net_return_pct"] or -999) - (baseline["average_net_return_pct"] or 0)
        ) >= 0.20,
        "minimum_trimmed_mean_pct": (summary["trimmed_mean_pct"] or -999) > 0,
        "minimum_double_cost_stress_mean_pct": (summary["double_cost_stress_mean_pct"] or -999) > 0,
        "maximum_single_stock_share": (summary["maximum_single_stock_share"] or 999) <= 0.05,
        "maximum_single_industry_share": (summary["maximum_single_industry_share"] or 999) <= 0.20,
    }
    return {"passed": all(checks.values()), "checks": checks}


def run() -> dict:
    """执行六年训练研究，失败时不打开外部年份。"""

    frames = [pd.read_parquet(STORE / f"{year}.parquet", columns=COLUMNS) for year in YEARS]
    enriched = add_equal_weight_market_features(pd.concat(frames, ignore_index=True))
    variants = ("baseline", "strict_trend", "early_recovery", "adaptive_trend")
    selections = {variant: select_variant(enriched, variant) for variant in variants}
    summaries = {variant: summarize(frame) for variant, frame in selections.items()}
    baseline = summaries["baseline"]
    details = {}
    decisions = {}
    for variant in variants[1:]:
        discovery = period_metrics(selections[variant], (2016, 2017, 2018))
        confirmation = period_metrics(selections[variant], (2019, 2020, 2021))
        edge = same_day_universe_edge(selections[variant], enriched)
        details[variant] = {
            "discovery_2016_2018": discovery,
            "confirmation_2019_2021": confirmation,
            "edge_vs_same_day_universe_pct": edge,
        }
        decisions[variant] = evaluate(summaries[variant], discovery, confirmation, edge, baseline)

    result = {
        "research_id": "clean_equal_weight_market_gate_20260808",
        "status": "training_pass" if any(item["passed"] for item in decisions.values()) else "training_failed",
        "summaries": summaries,
        "details": details,
        "decisions": decisions,
        "external_years_opened": False,
        "note": "市场门控与个股评分完全分离；失败时不打开外部年份。",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "clean_equal_weight_market_gate_20260808.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    for variant, frame in selections.items():
        frame.to_csv(
            REPORT_DIR / f"clean_equal_weight_market_gate_{variant}_trades_20260808.csv",
            index=False,
            encoding="utf-8-sig",
        )
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
