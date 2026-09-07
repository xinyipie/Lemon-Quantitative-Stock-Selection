"""以同日截面超额收益为目标的技术HGB走步研究。"""

from __future__ import annotations

import json

import pandas as pd

from research.clean_broad_cross_sectional_rank import simulate_portfolio
from research.clean_walkforward_technical_hgb import (
    ALL_YEARS,
    FEATURES,
    PREDICT_YEARS,
    RANDOM_STATE,
    RAW_COLUMNS,
    REPORT_DIR,
    STORE,
    TARGET,
    build_features,
    new_model,
    tradable_universe,
    walkforward_splits,
)
from research.clean_walkforward_technical_hgb_daily_top3 import execute_daily_top3, summarize_cohorts
from research.clean_walkforward_technical_hgb_daily_top3_account import account_metrics


EXCESS_TARGET = "ret_5d_excess"


def add_excess_target(frame: pd.DataFrame) -> pd.DataFrame:
    """构造同一信号日相对可交易样本均值的未来超额标签。"""

    work = frame.copy()
    daily_mean = work.groupby("trade_date")[TARGET].transform("mean")
    work[EXCESS_TARGET] = work[TARGET] - daily_mean
    return work


def sample_training_rows(frame: pd.DataFrame, years: tuple[int, ...]) -> pd.DataFrame:
    """按年份等上限抽取超额目标训练样本。"""

    parts = []
    for year in years:
        part = frame[(frame["year"] == year) & frame[EXCESS_TARGET].notna()].dropna(subset=FEATURES)
        if len(part) > 150000:
            part = part.sample(n=150000, random_state=RANDOM_STATE + year)
        parts.append(part)
    return pd.concat(parts, ignore_index=True)


def predict_walkforward_excess(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """逐年扩展训练并预测下一年截面超额。"""

    predictions = []
    metadata = {}
    for train_years, predict_year in walkforward_splits():
        train = sample_training_rows(frame, train_years)
        target = frame[frame["year"] == predict_year].dropna(subset=FEATURES).copy()
        model = new_model()
        model.fit(train[FEATURES], train[EXCESS_TARGET].clip(-15.0, 15.0))
        target["prediction"] = model.predict(target[FEATURES])
        target["prediction_rank"] = target.groupby("trade_date")["prediction"].rank(pct=True)
        target["train_end_year"] = max(train_years)
        predictions.append(target)
        metadata[str(predict_year)] = {
            "train_years": list(train_years),
            "training_rows": int(len(train)),
            "prediction_rows": int(len(target)),
        }
    return pd.concat(predictions, ignore_index=True), metadata


def evaluate(cohort: dict, base_account: dict, stress_account: dict) -> dict:
    """执行批次和账户双重冻结门槛。"""

    cohort_checks = {
        "minimum_daily_cohorts": cohort["cohorts"] >= 600,
        "minimum_cohorts_each_year": all(cohort["yearly"][str(year)]["cohorts"] >= 200 for year in PREDICT_YEARS),
        "minimum_average_net_return_pct": (cohort["average_cohort_net_return_pct"] or -999) >= 0.50,
        "minimum_profit_factor": (cohort["cohort_profit_factor"] or 0) >= 1.25,
        "required_positive_years": all(
            (cohort["yearly"][str(year)]["average_net_return_pct"] or -999) > 0 for year in PREDICT_YEARS
        ),
        "minimum_edge_vs_same_day_universe_pct": (cohort["edge_vs_same_day_universe_pct"] or -999) >= 0.30,
        "minimum_trimmed_mean_pct": (cohort["trimmed_mean_pct"] or -999) > 0,
        "minimum_double_cost_stress_mean_pct": (cohort["double_cost_stress_mean_pct"] or -999) > 0,
    }
    yearly_values = [base_account["yearly_returns_pct"].get(str(year), -999.0) for year in PREDICT_YEARS]
    account_checks = {
        "minimum_annualized_return_pct": (base_account["annualized_return_pct"] or -999) >= 12.0,
        "maximum_drawdown_pct": (base_account["max_drawdown_pct"] or -999) >= -20.0,
        "minimum_sharpe": (base_account["sharpe"] or -999) >= 0.80,
        "required_positive_account_years": all(value > 0 for value in yearly_values),
        "minimum_worst_year_return_pct": min(yearly_values) >= 3.0,
        "minimum_double_cost_annualized_return_pct": (stress_account["annualized_return_pct"] or -999) >= 8.0,
        "maximum_double_cost_drawdown_pct": (stress_account["max_drawdown_pct"] or -999) >= -25.0,
    }
    checks = {**cohort_checks, **account_checks}
    return {"passed": all(checks.values()), "checks": checks}


def run() -> dict:
    """运行超额目标模型的内部批次和账户确认。"""

    frames = [pd.read_parquet(STORE / f"{year}.parquet", columns=RAW_COLUMNS) for year in ALL_YEARS]
    featured = add_excess_target(tradable_universe(build_features(pd.concat(frames, ignore_index=True))))
    predictions, model_meta = predict_walkforward_excess(featured)
    trades = execute_daily_top3(predictions)
    cohort = summarize_cohorts(trades, predictions)
    base_curve = simulate_portfolio(trades, slots=15, cost_pct=0.25, holding_days=5)
    stress_curve = simulate_portfolio(trades, slots=15, cost_pct=0.50, holding_days=5)
    base_account = account_metrics(base_curve)
    stress_account = account_metrics(stress_curve)
    decision = evaluate(cohort, base_account, stress_account)
    result = {
        "research_id": "clean_walkforward_technical_hgb_excess_target_20260808",
        "status": "internal_confirmation_pass" if decision["passed"] else "internal_confirmation_failed",
        "model_meta": model_meta,
        "cohort_summary": cohort,
        "base_cost_account": base_account,
        "double_cost_account": stress_account,
        "decision": decision,
        "external_years_opened": False,
        "note": "超额标签仅用于历史训练；内部双门槛失败时不打开2022-2024。",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "clean_walkforward_technical_hgb_excess_target_20260808.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    trades.to_csv(
        REPORT_DIR / "clean_walkforward_technical_hgb_excess_target_trades_20260808.csv",
        index=False,
        encoding="utf-8-sig",
    )
    base_curve.to_csv(
        REPORT_DIR / "clean_walkforward_technical_hgb_excess_target_account_curve_20260808.csv",
        index=False,
        encoding="utf-8-sig",
    )
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
