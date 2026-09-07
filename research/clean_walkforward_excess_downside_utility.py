"""以连续下行幅度惩罚截面超额收益的内部确认研究。"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from research.clean_walkforward_technical_hgb_excess_target import (
    ALL_YEARS,
    EXCESS_TARGET,
    FEATURES,
    PREDICT_YEARS,
    RAW_COLUMNS,
    REPORT_DIR,
    STORE,
    TARGET,
    account_metrics,
    add_excess_target,
    build_features,
    execute_daily_top3,
    new_model,
    sample_training_rows,
    simulate_portfolio,
    summarize_cohorts,
    tradable_universe,
    walkforward_splits,
)

DOWNSIDE_TARGET = "downside_5d"
UTILITY_COLUMN = "prediction_utility"
RESEARCH_ID = "clean_walkforward_excess_downside_utility_20260808"


def add_downside_target(frame: pd.DataFrame) -> pd.DataFrame:
    """构造与收益同量纲的未来五日下行幅度标签。"""

    result = frame.copy()
    result[DOWNSIDE_TARGET] = (-result[TARGET]).clip(lower=0.0, upper=15.0)
    return result


def calculate_utility(predicted_excess: pd.Series, predicted_downside: pd.Series) -> pd.Series:
    """不调权重，直接以百分比单位计算收益风险效用。"""

    return predicted_excess - predicted_downside.clip(lower=0.0)


def predict_walkforward_utility(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict, dict]:
    """逐年扩展训练收益头与下行头，并计算连续效用。"""

    predictions = []
    metadata = {}
    downside_diagnostics = {}
    for train_years, predict_year in walkforward_splits():
        train = sample_training_rows(frame, train_years).dropna(subset=[DOWNSIDE_TARGET])
        target = frame[frame["year"] == predict_year].dropna(subset=FEATURES + [DOWNSIDE_TARGET]).copy()

        return_model = new_model()
        downside_model = new_model()
        return_model.fit(train[FEATURES], train[EXCESS_TARGET].clip(-15.0, 15.0))
        downside_model.fit(train[FEATURES], train[DOWNSIDE_TARGET])

        target["predicted_excess"] = return_model.predict(target[FEATURES])
        target["predicted_downside"] = downside_model.predict(target[FEATURES]).clip(min=0.0)
        target[UTILITY_COLUMN] = calculate_utility(
            target["predicted_excess"], target["predicted_downside"]
        )
        target["prediction"] = target[UTILITY_COLUMN]
        target["prediction_rank"] = target.groupby("trade_date")["prediction"].rank(pct=True)
        target["train_end_year"] = max(train_years)
        predictions.append(target)

        correlation = target["predicted_downside"].corr(target[DOWNSIDE_TARGET], method="spearman")
        downside_diagnostics[str(predict_year)] = {
            "rows": int(len(target)),
            "spearman": float(correlation) if pd.notna(correlation) else None,
            "realized_downside_rate": float((target[DOWNSIDE_TARGET] > 0).mean()),
        }
        metadata[str(predict_year)] = {
            "train_years": list(train_years),
            "training_rows": int(len(train)),
            "prediction_rows": int(len(target)),
        }

    return pd.concat(predictions, ignore_index=True), metadata, downside_diagnostics


def evaluate(
    cohort: dict,
    base_account: dict,
    stress_account: dict,
    downside_diagnostics: dict,
) -> dict:
    """按预注册门槛联合评估收益、风险与下行头有效性。"""

    cohort_checks = {
        "minimum_daily_cohorts": cohort["cohorts"] >= 600,
        "minimum_cohorts_each_year": all(
            cohort["yearly"][str(year)]["cohorts"] >= 200 for year in PREDICT_YEARS
        ),
        "minimum_average_net_return_pct": (cohort["average_cohort_net_return_pct"] or -999) >= 0.50,
        "minimum_profit_factor": (cohort["cohort_profit_factor"] or 0) >= 1.25,
        "required_positive_years": all(
            (cohort["yearly"][str(year)]["average_net_return_pct"] or -999) > 0
            for year in PREDICT_YEARS
        ),
        "minimum_edge_vs_same_day_universe_pct": (
            cohort["edge_vs_same_day_universe_pct"] or -999
        ) >= 0.30,
        "minimum_trimmed_mean_pct": (cohort["trimmed_mean_pct"] or -999) > 0,
        "minimum_double_cost_stress_mean_pct": (
            cohort["double_cost_stress_mean_pct"] or -999
        ) > 0,
    }
    yearly_values = [base_account["yearly_returns_pct"].get(str(year), -999.0) for year in PREDICT_YEARS]
    account_checks = {
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
    downside_checks = {
        "minimum_downside_spearman_each_year": all(
            (downside_diagnostics[str(year)]["spearman"] or -999) >= 0.05
            for year in PREDICT_YEARS
        )
    }
    checks = {**downside_checks, **cohort_checks, **account_checks}
    return {"passed": all(checks.values()), "checks": checks}


def run() -> dict:
    """运行连续下行效用模型的内部确认。"""

    frames = [pd.read_parquet(STORE / f"{year}.parquet", columns=RAW_COLUMNS) for year in ALL_YEARS]
    featured = add_downside_target(
        add_excess_target(tradable_universe(build_features(pd.concat(frames, ignore_index=True))))
    )
    predictions, model_meta, downside_diagnostics = predict_walkforward_utility(featured)
    trades = execute_daily_top3(predictions)
    cohort = summarize_cohorts(trades, predictions)
    base_curve = simulate_portfolio(trades, slots=15, cost_pct=0.25, holding_days=5)
    stress_curve = simulate_portfolio(trades, slots=15, cost_pct=0.50, holding_days=5)
    base_account = account_metrics(base_curve)
    stress_account = account_metrics(stress_curve)
    decision = evaluate(cohort, base_account, stress_account, downside_diagnostics)
    result = {
        "research_id": RESEARCH_ID,
        "status": "internal_confirmation_pass" if decision["passed"] else "internal_confirmation_failed",
        "model_meta": model_meta,
        "downside_diagnostics": downside_diagnostics,
        "cohort_summary": cohort,
        "base_cost_account": base_account,
        "double_cost_account": stress_account,
        "decision": decision,
        "external_years_opened": False,
        "note": "连续效用不含调参权重；内部联合门槛失败时不打开2022-2024。",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / f"{RESEARCH_ID}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    trades.to_csv(
        REPORT_DIR / f"{RESEARCH_ID}_trades.csv", index=False, encoding="utf-8-sig"
    )
    base_curve.to_csv(
        REPORT_DIR / f"{RESEARCH_ID}_account_curve.csv", index=False, encoding="utf-8-sig"
    )
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
