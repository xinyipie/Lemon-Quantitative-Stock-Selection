"""发现期选因子、确认期盲检验的全市场短线研究流程。"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from research.clean_financial_relative_confidence import enforce_same_stock_cooldown


ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "data" / "research" / "clean_all_market"
REPORT_DIR = ROOT / "reports" / "research"
DISCOVERY_YEARS = (2016, 2017, 2018)
CONFIRMATION_YEARS = (2019, 2020, 2021)
ALL_YEARS = DISCOVERY_YEARS + CONFIRMATION_YEARS
TARGET = "ret_5d"
COST_PCT = 0.25

FACTOR_NAMES = (
    "ret_5",
    "ret_20",
    "ret_60",
    "industry_rs_20",
    "volatility_20",
    "turnover_rate",
    "volume_ratio",
    "rsi_14",
    "drawdown_20",
    "price_to_ma20",
    "ma20_to_ma60",
    "log_amount",
)

COLUMNS = [
    "ts_code",
    "name",
    "industry",
    "trade_date",
    "close",
    "amount",
    "ret_5",
    "ret_20",
    "ret_60",
    "ma_20",
    "ma_60",
    "drawdown_20",
    "rsi_14",
    "volatility_20",
    "turnover_rate",
    "volume_ratio",
    "industry_rs_20",
    "entry_open",
    "entry_gap_pct",
    "ret_5d",
]


def benjamini_hochberg(p_values: dict[str, float]) -> dict[str, float]:
    """对固定因子集合执行Benjamini-Hochberg多重检验校正。"""

    ordered = sorted(p_values.items(), key=lambda item: (item[1], item[0]))
    count = len(ordered)
    adjusted: dict[str, float] = {}
    running = 1.0
    for reverse_index in range(count - 1, -1, -1):
        name, value = ordered[reverse_index]
        rank = reverse_index + 1
        running = min(running, value * count / rank)
        adjusted[name] = min(1.0, running)
    return adjusted


def prepare_factor_ranks(frame: pd.DataFrame) -> pd.DataFrame:
    """只用T日字段构造因子，并生成当日截面百分位。"""

    work = frame.copy()
    work["trade_date"] = work["trade_date"].astype(str)
    work["year"] = work["trade_date"].str[:4].astype(int)
    work["price_to_ma20"] = work["close"] / work["ma_20"] - 1.0
    work["ma20_to_ma60"] = work["ma_20"] / work["ma_60"] - 1.0
    work["log_amount"] = np.log1p(pd.to_numeric(work["amount"], errors="coerce").clip(lower=0))
    for factor in FACTOR_NAMES:
        work[f"rank_{factor}"] = work.groupby("trade_date")[factor].rank(pct=True)
    work["target_rank"] = work.groupby("trade_date")[TARGET].rank(pct=True)
    return work


def _daily_ic(frame: pd.DataFrame, rank_column: str) -> pd.Series:
    return frame.groupby("trade_date", sort=False).apply(
        lambda part: part[rank_column].corr(part["target_rank"]),
        include_groups=False,
    ).dropna()


def factor_diagnostics(discovery: pd.DataFrame) -> dict[str, dict]:
    """仅用发现期标签确定因子方向、显著性和年度一致性。"""

    raw: dict[str, dict] = {}
    p_values: dict[str, float] = {}
    for factor in FACTOR_NAMES:
        rank_column = f"rank_{factor}"
        daily_ic = _daily_ic(discovery, rank_column)
        mean_ic = float(daily_ic.mean()) if len(daily_ic) else 0.0
        direction = 1 if mean_ic >= 0 else -1
        test = stats.ttest_1samp(daily_ic, 0.0, nan_policy="omit") if len(daily_ic) > 1 else None
        p_value = float(test.pvalue) if test is not None and np.isfinite(test.pvalue) else 1.0
        p_values[factor] = p_value

        yearly_ic = {}
        yearly_spread = {}
        for year, part in discovery.groupby("year"):
            year_daily_ic = _daily_ic(part, rank_column)
            yearly_ic[str(int(year))] = float(year_daily_ic.mean()) if len(year_daily_ic) else None
            top = part[part[rank_column] >= 0.80][TARGET]
            bottom = part[part[rank_column] <= 0.20][TARGET]
            spread = float(top.mean() - bottom.mean()) if len(top) and len(bottom) else np.nan
            yearly_spread[str(int(year))] = spread * direction if np.isfinite(spread) else None

        same_sign_years = sum(
            value is not None and value * direction > 0 for value in yearly_ic.values()
        )
        positive_spread_years = sum(
            value is not None and value > 0 for value in yearly_spread.values()
        )
        raw[factor] = {
            "mean_daily_ic": mean_ic,
            "direction": direction,
            "p_value": p_value,
            "same_sign_years": int(same_sign_years),
            "positive_directional_spread_years": int(positive_spread_years),
            "yearly_ic": yearly_ic,
            "yearly_directional_quintile_spread": yearly_spread,
        }

    adjusted = benjamini_hochberg(p_values)
    for factor, item in raw.items():
        item["bh_q_value"] = adjusted[factor]
        item["qualified"] = bool(
            abs(item["mean_daily_ic"]) >= 0.01
            and item["same_sign_years"] >= 2
            and item["positive_directional_spread_years"] >= 2
            and item["bh_q_value"] <= 0.10
        )
    return raw


def choose_low_correlation_factors(discovery: pd.DataFrame, diagnostics: dict[str, dict]) -> list[dict]:
    """按冻结排序贪心选择最多三个低相关因子。"""

    qualified = [name for name, item in diagnostics.items() if item["qualified"]]
    qualified.sort(key=lambda name: (-abs(diagnostics[name]["mean_daily_ic"]), name))
    selected: list[dict] = []
    for factor in qualified:
        direction = diagnostics[factor]["direction"]
        signed = discovery[f"rank_{factor}"] * direction
        acceptable = True
        for existing in selected:
            existing_signed = discovery[f"rank_{existing['factor']}"] * existing["direction"]
            correlation = signed.corr(existing_signed)
            if pd.notna(correlation) and abs(correlation) >= 0.70:
                acceptable = False
                break
        if acceptable:
            selected.append({"factor": factor, "direction": direction})
        if len(selected) >= 3:
            break
    return selected


def build_composite(frame: pd.DataFrame, selected_factors: list[dict]) -> pd.DataFrame:
    """按发现期冻结的因子方向等权生成复合分。"""

    work = frame.copy()
    if not selected_factors:
        work["composite_score"] = np.nan
        return work.iloc[0:0]
    components = []
    for item in selected_factors:
        rank = work[f"rank_{item['factor']}"]
        components.append(rank if item["direction"] > 0 else 1.0 - rank)
    work["composite_score"] = pd.concat(components, axis=1).mean(axis=1)
    return work


def select_trades(frame: pd.DataFrame, selected_factors: list[dict]) -> pd.DataFrame:
    """T日锁定Top1，T+1不可成交时跳过且不递补。"""

    scored = build_composite(frame, selected_factors)
    locked = (
        scored.dropna(subset=["composite_score"])
        .sort_values(
            ["trade_date", "composite_score", "ts_code"],
            ascending=[True, False, True],
            kind="mergesort",
        )
        .groupby("trade_date", group_keys=False)
        .head(1)
        .copy()
    )
    executable = locked[
        locked["entry_open"].notna()
        & (locked["entry_gap_pct"] < 7.0)
        & (locked["entry_gap_pct"] > -9.5)
        & locked[TARGET].notna()
    ].copy()
    all_dates = sorted(frame["trade_date"].astype(str).unique().tolist())
    executable = enforce_same_stock_cooldown(executable, all_dates, cooldown_days=5)
    executable["net_return"] = executable[TARGET] - COST_PCT
    return executable


def summarize_period(trades: pd.DataFrame, universe: pd.DataFrame, years: tuple[int, ...]) -> dict:
    """汇总指定阶段，并用相同信号日的全市场均值作为基准。"""

    part = trades[trades["year"].isin(years)].copy()
    values = part["net_return"].dropna()
    gains = float(values[values > 0].sum())
    losses = float(-values[values < 0].sum())
    ordered = values.sort_values().reset_index(drop=True)
    trim = int(len(ordered) * 0.05)
    trimmed = ordered.iloc[trim:-trim] if trim and len(ordered) > trim * 2 else ordered

    benchmark = (
        universe[universe["year"].isin(years)]
        .groupby("trade_date")[TARGET]
        .mean()
        .sub(COST_PCT)
    )
    signal_benchmark = part["trade_date"].map(benchmark)
    yearly = {}
    for year in years:
        year_values = part.loc[part["year"] == year, "net_return"].dropna()
        year_gains = float(year_values[year_values > 0].sum())
        year_losses = float(-year_values[year_values < 0].sum())
        yearly[str(year)] = {
            "trades": int(len(year_values)),
            "average_net_return_pct": float(year_values.mean()) if len(year_values) else None,
            "profit_factor": year_gains / year_losses if year_losses > 0 else None,
        }
    stock_share = part["ts_code"].value_counts(normalize=True)
    industry_share = part["industry"].fillna("未知").value_counts(normalize=True)
    return {
        "trades": int(len(values)),
        "average_net_return_pct": float(values.mean()) if len(values) else None,
        "profit_factor": gains / losses if losses > 0 else None,
        "trimmed_mean_pct": float(trimmed.mean()) if len(trimmed) else None,
        "double_cost_stress_mean_pct": float(values.mean() - COST_PCT) if len(values) else None,
        "daily_universe_benchmark_pct": float(signal_benchmark.mean()) if len(signal_benchmark) else None,
        "edge_vs_daily_universe_pct": float(values.mean() - signal_benchmark.mean()) if len(values) else None,
        "maximum_single_stock_share": float(stock_share.iloc[0]) if len(stock_share) else None,
        "maximum_single_industry_share": float(industry_share.iloc[0]) if len(industry_share) else None,
        "yearly": yearly,
    }


def confirmation_factor_check(frame: pd.DataFrame, selected_factors: list[dict]) -> dict:
    """确认冻结因子的IC方向是否在确认期保持一致。"""

    result = {}
    for item in selected_factors:
        daily_ic = _daily_ic(frame, f"rank_{item['factor']}")
        mean_ic = float(daily_ic.mean()) if len(daily_ic) else 0.0
        result[item["factor"]] = {
            "discovery_direction": item["direction"],
            "confirmation_mean_daily_ic": mean_ic,
            "direction_matches": bool(mean_ic * item["direction"] > 0),
        }
    return result


def evaluate_gates(
    selected_factors: list[dict],
    discovery: dict,
    confirmation: dict,
    factor_confirmation: dict,
) -> dict:
    """执行冻结的内部确认门槛。"""

    checks = {
        "minimum_selected_factors": len(selected_factors) >= 1,
        "minimum_discovery_trades": discovery["trades"] >= 300,
        "minimum_discovery_average_net_return_pct": (discovery["average_net_return_pct"] or -999) > 0,
        "minimum_discovery_profit_factor": (discovery["profit_factor"] or 0) >= 1.10,
        "minimum_confirmation_trades": confirmation["trades"] >= 300,
        "minimum_confirmation_trades_each_year": all(
            confirmation["yearly"][str(year)]["trades"] >= 80 for year in CONFIRMATION_YEARS
        ),
        "minimum_confirmation_average_net_return_pct": (confirmation["average_net_return_pct"] or -999) >= 0.35,
        "minimum_confirmation_profit_factor": (confirmation["profit_factor"] or 0) >= 1.15,
        "required_positive_confirmation_years": all(
            (confirmation["yearly"][str(year)]["average_net_return_pct"] or -999) > 0
            for year in CONFIRMATION_YEARS
        ),
        "minimum_confirmation_edge_vs_daily_universe_pct": (confirmation["edge_vs_daily_universe_pct"] or -999) >= 0.30,
        "minimum_confirmation_trimmed_mean_pct": (confirmation["trimmed_mean_pct"] or -999) > 0,
        "minimum_confirmation_double_cost_stress_mean_pct": (confirmation["double_cost_stress_mean_pct"] or -999) > 0,
        "maximum_single_stock_share": (confirmation["maximum_single_stock_share"] or 999) <= 0.03,
        "maximum_single_industry_share": (confirmation["maximum_single_industry_share"] or 999) <= 0.15,
        "selected_factor_confirmation_direction_must_match": bool(factor_confirmation)
        and all(item["direction_matches"] for item in factor_confirmation.values()),
    }
    return {"passed": all(checks.values()), "checks": checks}


def run() -> dict:
    """运行发现与内部确认，失败时不打开外部年份。"""

    frames = [pd.read_parquet(STORE / f"{year}.parquet", columns=COLUMNS) for year in ALL_YEARS]
    ranked = prepare_factor_ranks(pd.concat(frames, ignore_index=True))
    discovery_frame = ranked[ranked["year"].isin(DISCOVERY_YEARS)].copy()
    confirmation_frame = ranked[ranked["year"].isin(CONFIRMATION_YEARS)].copy()
    diagnostics = factor_diagnostics(discovery_frame)
    selected_factors = choose_low_correlation_factors(discovery_frame, diagnostics)
    trades = select_trades(ranked, selected_factors)
    discovery = summarize_period(trades, ranked, DISCOVERY_YEARS)
    confirmation = summarize_period(trades, ranked, CONFIRMATION_YEARS)
    factor_confirmation = confirmation_factor_check(confirmation_frame, selected_factors)
    decision = evaluate_gates(selected_factors, discovery, confirmation, factor_confirmation)

    result = {
        "research_id": "clean_factor_discovery_confirmation_20260808",
        "status": "internal_confirmation_pass" if decision["passed"] else "internal_confirmation_failed",
        "selected_factors": selected_factors,
        "factor_diagnostics_discovery_only": diagnostics,
        "factor_confirmation": factor_confirmation,
        "discovery_2016_2018": discovery,
        "internal_confirmation_2019_2021": confirmation,
        "decision": decision,
        "external_years_opened": False,
        "note": "因子选择仅使用2016-2018；内部确认失败时不查看2022-2024。",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "clean_factor_discovery_confirmation_20260808.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    trades.to_csv(
        REPORT_DIR / "clean_factor_discovery_confirmation_trades_20260808.csv",
        index=False,
        encoding="utf-8-sig",
    )
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
