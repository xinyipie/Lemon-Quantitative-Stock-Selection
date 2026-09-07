"""可交易性受限的低风险/短期反转五日篮子研究。"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from research.clean_factor_discovery_confirmation import COLUMNS, prepare_factor_ranks


ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "data" / "research" / "clean_all_market"
REPORT_DIR = ROOT / "reports" / "research"
YEARS = tuple(range(2016, 2022))
TARGET = "ret_5d"
COST_PCT = 0.25


def eligible_universe(ranked: pd.DataFrame) -> pd.DataFrame:
    """排除极端微盘和极端低换手样本，保留中低风险区域。"""

    return ranked[
        ranked["rank_log_amount"].between(0.30, 0.90, inclusive="both")
        & ranked["rank_turnover_rate"].between(0.20, 0.70, inclusive="both")
        & ranked["rank_volatility_20"].between(0.20, 0.70, inclusive="both")
    ].copy()


def add_score(frame: pd.DataFrame) -> pd.DataFrame:
    """使用发现期已经确认方向的固定等价权重组合。"""

    work = frame.copy()
    work["basket_score"] = (
        (1.0 - work["rank_volatility_20"]) * 0.25
        + (1.0 - work["rank_turnover_rate"]) * 0.20
        + (1.0 - work["rank_ret_5"]) * 0.20
        + (1.0 - work["rank_log_amount"]) * 0.15
        + (1.0 - work["rank_ret_20"]) * 0.10
        + (1.0 - work["rank_industry_rs_20"]) * 0.10
    )
    return work


def rebalance_dates(all_dates: list[str], offset: int) -> list[str]:
    """按固定交易日步长生成互不重叠的五日持有起点。"""

    if offset not in range(5):
        raise ValueError("offset必须位于0到4")
    return all_dates[offset::5]


def select_basket_trades(ranked: pd.DataFrame, offset: int) -> pd.DataFrame:
    """T日锁定Top5，T+1无法成交时跳过且不递补。"""

    universe = add_score(eligible_universe(ranked))
    dates = rebalance_dates(sorted(ranked["trade_date"].astype(str).unique().tolist()), offset)
    locked = (
        universe[universe["trade_date"].isin(dates)]
        .sort_values(
            ["trade_date", "basket_score", "ts_code"],
            ascending=[True, False, True],
            kind="mergesort",
        )
        .groupby("trade_date", group_keys=False)
        .head(5)
        .copy()
    )
    executed = locked[
        locked["entry_open"].notna()
        & locked[TARGET].notna()
        & (locked["entry_gap_pct"] < 7.0)
        & (locked["entry_gap_pct"] > -9.5)
    ].copy()
    executed["net_return"] = executed[TARGET] - COST_PCT
    return executed


def basket_summary(trades: pd.DataFrame, ranked: pd.DataFrame) -> dict:
    """以调仓日等权篮子为统计单位，避免同日股票伪独立。"""

    baskets = (
        trades.groupby("trade_date", as_index=False)
        .agg(net_return=("net_return", "mean"), members=("ts_code", "size"))
        .sort_values("trade_date")
    )
    baskets["year"] = baskets["trade_date"].str[:4].astype(int)
    values = baskets["net_return"]
    gains = float(values[values > 0].sum())
    losses = float(-values[values < 0].sum())
    ordered = values.sort_values().reset_index(drop=True)
    trim = int(len(ordered) * 0.05)
    trimmed = ordered.iloc[trim:-trim] if trim and len(ordered) > trim * 2 else ordered

    universe = eligible_universe(ranked)
    benchmark = universe.groupby("trade_date")[TARGET].mean().sub(COST_PCT)
    same_day_benchmark = baskets["trade_date"].map(benchmark)
    yearly = {}
    for year in YEARS:
        part = baskets.loc[baskets["year"] == year, "net_return"]
        year_gains = float(part[part > 0].sum())
        year_losses = float(-part[part < 0].sum())
        yearly[str(year)] = {
            "baskets": int(len(part)),
            "average_net_return_pct": float(part.mean()) if len(part) else None,
            "profit_factor": year_gains / year_losses if year_losses > 0 else None,
        }

    stock_share = trades["ts_code"].value_counts(normalize=True)
    industry_share = trades["industry"].fillna("未知").value_counts(normalize=True)
    return {
        "baskets": int(len(baskets)),
        "stock_trades": int(len(trades)),
        "average_members": float(baskets["members"].mean()) if len(baskets) else None,
        "average_basket_net_return_pct": float(values.mean()) if len(values) else None,
        "basket_profit_factor": gains / losses if losses > 0 else None,
        "win_rate": float((values > 0).mean()) if len(values) else None,
        "trimmed_mean_pct": float(trimmed.mean()) if len(trimmed) else None,
        "double_cost_stress_mean_pct": float(values.mean() - COST_PCT) if len(values) else None,
        "same_day_universe_benchmark_pct": float(same_day_benchmark.mean()) if len(same_day_benchmark) else None,
        "edge_vs_same_day_universe_pct": float(values.mean() - same_day_benchmark.mean()) if len(values) else None,
        "positive_years": int(sum((item["average_net_return_pct"] or 0) > 0 for item in yearly.values())),
        "maximum_single_stock_share": float(stock_share.iloc[0]) if len(stock_share) else None,
        "maximum_single_industry_share": float(industry_share.iloc[0]) if len(industry_share) else None,
        "top_stock": str(stock_share.index[0]) if len(stock_share) else None,
        "top_industry": str(industry_share.index[0]) if len(industry_share) else None,
        "yearly": yearly,
    }


def evaluate(primary: dict, offsets: dict[str, dict]) -> dict:
    """执行主结果和五种调仓起点压力门槛。"""

    checks = {
        "minimum_rebalance_baskets": primary["baskets"] >= 250,
        "minimum_baskets_each_year": all(primary["yearly"][str(year)]["baskets"] >= 40 for year in YEARS),
        "minimum_average_basket_net_return_pct": (primary["average_basket_net_return_pct"] or -999) >= 0.25,
        "minimum_basket_profit_factor": (primary["basket_profit_factor"] or 0) >= 1.15,
        "minimum_positive_years": primary["positive_years"] >= 5,
        "required_positive_years": all(
            (primary["yearly"][str(year)]["average_net_return_pct"] or -999) > 0
            for year in (2019, 2020, 2021)
        ),
        "minimum_edge_vs_same_day_universe_pct": (primary["edge_vs_same_day_universe_pct"] or -999) >= 0.20,
        "minimum_trimmed_mean_pct": (primary["trimmed_mean_pct"] or -999) > 0,
        "minimum_double_cost_stress_mean_pct": (primary["double_cost_stress_mean_pct"] or -999) > 0,
        "maximum_single_stock_share": (primary["maximum_single_stock_share"] or 999) <= 0.03,
        "maximum_single_industry_share": (primary["maximum_single_industry_share"] or 999) <= 0.15,
        "all_offsets_average_return_must_be_positive": all(
            (item["average_basket_net_return_pct"] or -999) > 0 for item in offsets.values()
        ),
        "minimum_profit_factor_each_offset": all(
            (item["basket_profit_factor"] or 0) >= 1.05 for item in offsets.values()
        ),
        "minimum_positive_years_each_offset": all(item["positive_years"] >= 4 for item in offsets.values()),
    }
    return {"passed": all(checks.values()), "checks": checks}


def run() -> dict:
    """运行训练期五偏移研究，未通过时不打开外部年份。"""

    frames = [pd.read_parquet(STORE / f"{year}.parquet", columns=COLUMNS) for year in YEARS]
    ranked = prepare_factor_ranks(pd.concat(frames, ignore_index=True))
    trades_by_offset = {offset: select_basket_trades(ranked, offset) for offset in range(5)}
    summaries = {
        str(offset): basket_summary(trades, ranked)
        for offset, trades in trades_by_offset.items()
    }
    primary = summaries["0"]
    decision = evaluate(primary, summaries)
    result = {
        "research_id": "clean_low_risk_reversal_basket_20260808",
        "status": "training_and_calendar_stress_pass" if decision["passed"] else "training_failed",
        "primary_offset_0": primary,
        "all_calendar_offsets": summaries,
        "decision": decision,
        "external_years_opened": False,
        "note": "按篮子而非股票行统计；失败时不打开2022-2024。",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "clean_low_risk_reversal_basket_20260808.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    for offset, trades in trades_by_offset.items():
        trades.to_csv(
            REPORT_DIR / f"clean_low_risk_reversal_basket_offset{offset}_trades_20260808.csv",
            index=False,
            encoding="utf-8-sig",
        )
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
