"""袋装保守下界选股叠加既有BEAR_TREND门控的六年研究确认。"""

from __future__ import annotations

import json

import pandas as pd

from research.clean_walkforward_technical_hgb_excess_target import (
    REPORT_DIR,
    STORE,
    account_metrics,
    simulate_portfolio,
)

RESEARCH_YEARS = (2019, 2020, 2021, 2022, 2023, 2024)
INTERNAL_TRADES = REPORT_DIR / "clean_walkforward_excess_bagged_lcb_20260808_trades.csv"
VALIDATION_TRADES = REPORT_DIR / "validation_clean_walkforward_excess_bagged_lcb_20260808_trades.csv"
RESEARCH_ID = "clean_bagged_lcb_existing_regime_gate_20260808"


def apply_existing_regime_gate(trades: pd.DataFrame) -> pd.DataFrame:
    """严格复用既有语义，只移除BEAR_TREND信号。"""

    return trades[trades["regime"].astype(str) != "BEAR_TREND"].copy()


def attach_regime(trades: pd.DataFrame) -> pd.DataFrame:
    """从清洁库按交易日补回唯一市场状态，不读取未来信息。"""

    maps = []
    for year in RESEARCH_YEARS:
        part = pd.read_parquet(STORE / f"{year}.parquet", columns=["trade_date", "regime"])
        maps.append(part.drop_duplicates("trade_date"))
    regime_map = pd.concat(maps, ignore_index=True).drop_duplicates("trade_date")
    regime_map["trade_date"] = regime_map["trade_date"].astype(str)
    return trades.drop(columns=["regime"], errors="ignore").merge(
        regime_map, on="trade_date", how="left", validate="many_to_one"
    )


def summarize(trades: pd.DataFrame) -> dict:
    """统计六年研究区的批次收益、增量和集中度。"""

    cohorts = trades.groupby("trade_date", as_index=False).agg(
        net_return=("net_return", "mean"), members=("ts_code", "size")
    )
    cohorts["year"] = cohorts["trade_date"].str[:4].astype(int)
    values = cohorts["net_return"]
    gains = float(values[values > 0].sum())
    losses = float(-values[values < 0].sum())
    ordered = values.sort_values().reset_index(drop=True)
    trim = int(len(ordered) * 0.05)
    trimmed = ordered.iloc[trim:-trim] if trim and len(ordered) > trim * 2 else ordered
    benchmark = (
        trades.assign(universe_net=trades["ret_5d"] - trades["ret_5d_excess"] - 0.25)
        .groupby("trade_date")["universe_net"]
        .first()
    )
    same_day_benchmark = cohorts["trade_date"].map(benchmark)
    yearly = {}
    for year in RESEARCH_YEARS:
        part = cohorts.loc[cohorts["year"] == year, "net_return"]
        year_gains = float(part[part > 0].sum())
        year_losses = float(-part[part < 0].sum())
        yearly[str(year)] = {
            "cohorts": int(len(part)),
            "average_net_return_pct": float(part.mean()) if len(part) else None,
            "profit_factor": year_gains / year_losses if year_losses > 0 else None,
        }
    stock_share = trades["ts_code"].value_counts(normalize=True)
    industry_share = trades["industry"].fillna("未知").value_counts(normalize=True)
    return {
        "cohorts": int(len(cohorts)),
        "stock_trades": int(len(trades)),
        "average_members": float(cohorts["members"].mean()),
        "average_cohort_net_return_pct": float(values.mean()),
        "cohort_profit_factor": gains / losses if losses > 0 else None,
        "win_rate": float((values > 0).mean()),
        "trimmed_mean_pct": float(trimmed.mean()),
        "double_cost_stress_mean_pct": float(values.mean() - 0.25),
        "same_day_universe_benchmark_pct": float(same_day_benchmark.mean()),
        "edge_vs_same_day_universe_pct": float(values.mean() - same_day_benchmark.mean()),
        "maximum_single_stock_share": float(stock_share.iloc[0]),
        "maximum_single_industry_share": float(industry_share.iloc[0]),
        "yearly": yearly,
    }


def evaluate(cohort: dict, base_account: dict, stress_account: dict) -> dict:
    """执行预注册六年研究确认门槛。"""

    yearly_values = [base_account["yearly_returns_pct"].get(str(year), -999.0) for year in RESEARCH_YEARS]
    checks = {
        "minimum_daily_cohorts": cohort["cohorts"] >= 900,
        "minimum_cohorts_each_year": all(
            cohort["yearly"][str(year)]["cohorts"] >= 100 for year in RESEARCH_YEARS
        ),
        "minimum_average_net_return_pct": cohort["average_cohort_net_return_pct"] >= 0.50,
        "minimum_profit_factor": (cohort["cohort_profit_factor"] or 0) >= 1.25,
        "required_positive_years": all(
            (cohort["yearly"][str(year)]["average_net_return_pct"] or -999) > 0
            for year in RESEARCH_YEARS
        ),
        "minimum_edge_vs_same_day_universe_pct": cohort["edge_vs_same_day_universe_pct"] >= 0.30,
        "minimum_trimmed_mean_pct": cohort["trimmed_mean_pct"] > 0,
        "minimum_double_cost_stress_mean_pct": cohort["double_cost_stress_mean_pct"] > 0,
        "minimum_annualized_return_pct": (base_account["annualized_return_pct"] or -999) >= 12.0,
        "maximum_drawdown_pct": (base_account["max_drawdown_pct"] or -999) >= -20.0,
        "minimum_sharpe": (base_account["sharpe"] or -999) >= 0.80,
        "required_positive_account_years": all(value > 0 for value in yearly_values),
        "minimum_worst_year_return_pct": min(yearly_values) >= 3.0,
        "minimum_double_cost_annualized_return_pct": (
            stress_account["annualized_return_pct"] or -999
        ) >= 8.0,
        "maximum_double_cost_drawdown_pct": (
            stress_account["max_drawdown_pct"] or -999
        ) >= -25.0,
    }
    return {"passed": all(checks.values()), "checks": checks}


def run() -> dict:
    """运行六年既有状态机门控研究确认。"""

    trades = pd.concat(
        [
            pd.read_csv(INTERNAL_TRADES, dtype={"trade_date": str}),
            pd.read_csv(VALIDATION_TRADES, dtype={"trade_date": str}),
        ],
        ignore_index=True,
    )
    trades["trade_date"] = trades["trade_date"].astype(str).str.replace(".0", "", regex=False)
    trades = attach_regime(trades)
    gated = apply_existing_regime_gate(trades)
    cohort = summarize(gated)
    base_curve = simulate_portfolio(gated, slots=15, cost_pct=0.25, holding_days=5)
    stress_curve = simulate_portfolio(gated, slots=15, cost_pct=0.50, holding_days=5)
    base_account = account_metrics(base_curve)
    stress_account = account_metrics(stress_curve)
    decision = evaluate(cohort, base_account, stress_account)
    result = {
        "research_id": RESEARCH_ID,
        "status": "six_year_confirmation_pass" if decision["passed"] else "six_year_confirmation_failed",
        "gate_diagnostics": {
            "all_trades": int(len(trades)),
            "kept_trades": int(len(gated)),
            "removed_trades": int(len(trades) - len(gated)),
            "regime_counts_before": trades["regime"].value_counts().to_dict(),
            "regime_counts_after": gated["regime"].value_counts().to_dict(),
        },
        "cohort_summary": cohort,
        "base_cost_account": base_account,
        "double_cost_account": stress_account,
        "decision": decision,
        "new_holdout_opened": False,
        "note": "六年仅为新候选研究确认；全部通过后才允许打开2025。",
    }
    (REPORT_DIR / f"{RESEARCH_ID}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    gated.to_csv(REPORT_DIR / f"{RESEARCH_ID}_trades.csv", index=False, encoding="utf-8-sig")
    base_curve.to_csv(
        REPORT_DIR / f"{RESEARCH_ID}_account_curve.csv", index=False, encoding="utf-8-sig"
    )
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
