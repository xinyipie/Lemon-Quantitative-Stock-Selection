"""超额目标HGB叠加极端市场风险日弃权的研究。"""

from __future__ import annotations

import json

import pandas as pd

from research.clean_broad_cross_sectional_rank import simulate_portfolio
from research.clean_walkforward_technical_hgb import ALL_YEARS, RAW_COLUMNS, REPORT_DIR, STORE, build_features, tradable_universe
from research.clean_walkforward_technical_hgb_daily_top3 import execute_daily_top3, summarize_cohorts
from research.clean_walkforward_technical_hgb_daily_top3_account import account_metrics
from research.clean_walkforward_technical_hgb_excess_target import add_excess_target, predict_walkforward_excess


PARENT_DRAWDOWN = -24.977765350659674
PARENT_EDGE = 0.23216984898851784


def risk_off_mask(frame: pd.DataFrame) -> pd.Series:
    """识别T日全市场极弱或恐慌分化状态。"""

    severe_weakness = (
        (frame["market_breadth_ma20"] < 0.30)
        & (frame["market_median_ret20"] < -5.0)
    )
    panic_dispersion = (
        (frame["market_median_pct_chg"] < -1.5)
        & (frame["market_dispersion_pct_chg"] > 2.5)
    )
    return severe_weakness | panic_dispersion


def evaluate(cohort: dict, base: dict, stress: dict) -> dict:
    """执行原门槛及相对父研究的增量要求。"""

    years = (2019, 2020, 2021)
    yearly_values = [base["yearly_returns_pct"].get(str(year), -999.0) for year in years]
    checks = {
        "minimum_daily_cohorts": cohort["cohorts"] >= 600,
        "minimum_cohorts_each_year": all(cohort["yearly"][str(year)]["cohorts"] >= 190 for year in years),
        "minimum_average_net_return_pct": (cohort["average_cohort_net_return_pct"] or -999) >= 0.50,
        "minimum_profit_factor": (cohort["cohort_profit_factor"] or 0) >= 1.25,
        "required_positive_cohort_years": all(
            (cohort["yearly"][str(year)]["average_net_return_pct"] or -999) > 0 for year in years
        ),
        "minimum_edge_vs_same_day_universe_pct": (cohort["edge_vs_same_day_universe_pct"] or -999) >= 0.30,
        "minimum_trimmed_mean_pct": (cohort["trimmed_mean_pct"] or -999) > 0,
        "minimum_double_cost_stress_mean_pct": (cohort["double_cost_stress_mean_pct"] or -999) > 0,
        "minimum_annualized_return_pct": (base["annualized_return_pct"] or -999) >= 12.0,
        "maximum_drawdown_pct": (base["max_drawdown_pct"] or -999) >= -20.0,
        "minimum_sharpe": (base["sharpe"] or -999) >= 0.80,
        "required_positive_account_years": all(value > 0 for value in yearly_values),
        "minimum_worst_year_return_pct": min(yearly_values) >= 3.0,
        "minimum_double_cost_annualized_return_pct": (stress["annualized_return_pct"] or -999) >= 8.0,
        "maximum_double_cost_drawdown_pct": (stress["max_drawdown_pct"] or -999) >= -25.0,
        "minimum_drawdown_improvement_points": (
            (base["max_drawdown_pct"] or -999) - PARENT_DRAWDOWN
        ) >= 3.0,
        "minimum_edge_improvement_points": (
            (cohort["edge_vs_same_day_universe_pct"] or -999) - PARENT_EDGE
        ) >= 0.05,
    }
    return {"passed": all(checks.values()), "checks": checks}


def run() -> dict:
    """运行极端风险日弃权的内部批次与账户确认。"""

    frames = [pd.read_parquet(STORE / f"{year}.parquet", columns=RAW_COLUMNS) for year in ALL_YEARS]
    featured = add_excess_target(tradable_universe(build_features(pd.concat(frames, ignore_index=True))))
    predictions, model_meta = predict_walkforward_excess(featured)
    allowed_predictions = predictions[~risk_off_mask(predictions)].copy()
    trades = execute_daily_top3(allowed_predictions)
    cohort = summarize_cohorts(trades, predictions)
    base_curve = simulate_portfolio(trades, slots=15, cost_pct=0.25, holding_days=5)
    stress_curve = simulate_portfolio(trades, slots=15, cost_pct=0.50, holding_days=5)
    base = account_metrics(base_curve)
    stress = account_metrics(stress_curve)
    decision = evaluate(cohort, base, stress)
    result = {
        "research_id": "clean_walkforward_technical_hgb_excess_risk_gate_20260808",
        "status": "internal_confirmation_pass" if decision["passed"] else "internal_confirmation_failed",
        "model_meta": model_meta,
        "risk_off_dates": int(predictions.loc[risk_off_mask(predictions), "trade_date"].nunique()),
        "cohort_summary": cohort,
        "base_cost_account": base,
        "double_cost_account": stress,
        "decision": decision,
        "external_years_opened": False,
        "note": "风险门控只停止新信号，不改变个股排序；失败时不打开2022-2024。",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "clean_walkforward_technical_hgb_excess_risk_gate_20260808.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    trades.to_csv(
        REPORT_DIR / "clean_walkforward_technical_hgb_excess_risk_gate_trades_20260808.csv",
        index=False,
        encoding="utf-8-sig",
    )
    base_curve.to_csv(
        REPORT_DIR / "clean_walkforward_technical_hgb_excess_risk_gate_account_curve_20260808.csv",
        index=False,
        encoding="utf-8-sig",
    )
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
