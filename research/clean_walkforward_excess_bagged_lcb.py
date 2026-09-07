"""使用袋装成员保守预测下界排序的内部确认研究。"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from research.clean_walkforward_excess_bagged3 import SEEDS, sample_training_rows
from research.clean_walkforward_technical_hgb_excess_target import (
    ALL_YEARS,
    EXCESS_TARGET,
    FEATURES,
    RAW_COLUMNS,
    REPORT_DIR,
    STORE,
    account_metrics,
    add_excess_target,
    build_features,
    evaluate,
    execute_daily_top3,
    new_model,
    simulate_portfolio,
    summarize_cohorts,
    tradable_universe,
    walkforward_splits,
)

RESEARCH_ID = "clean_walkforward_excess_bagged_lcb_20260808"


def conservative_score(member_predictions: list[np.ndarray]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """计算三成员均值、总体标准差和一个标准差保守下界。"""

    matrix = np.vstack(member_predictions)
    mean = matrix.mean(axis=0)
    std = matrix.std(axis=0, ddof=0)
    return mean, std, mean - std


def predict_walkforward(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """逐年训练固定三成员并按保守下界输出预测。"""

    outputs = []
    metadata = {}
    for train_years, predict_year in walkforward_splits():
        target = frame[frame["year"] == predict_year].dropna(subset=FEATURES).copy()
        member_predictions = []
        member_rows = []
        for seed in SEEDS:
            train = sample_training_rows(frame, train_years, seed)
            model = new_model().set_params(random_state=seed)
            model.fit(train[FEATURES], train[EXCESS_TARGET].clip(-15.0, 15.0))
            member_predictions.append(model.predict(target[FEATURES]))
            member_rows.append(int(len(train)))
        mean, std, lower_bound = conservative_score(member_predictions)
        target["prediction_mean"] = mean
        target["prediction_std"] = std
        target["prediction"] = lower_bound
        target["prediction_rank"] = target.groupby("trade_date")["prediction"].rank(pct=True)
        target["train_end_year"] = max(train_years)
        outputs.append(target)
        metadata[str(predict_year)] = {
            "train_years": list(train_years),
            "member_training_rows": member_rows,
            "prediction_rows": int(len(target)),
            "seeds": list(SEEDS),
        }
    return pd.concat(outputs, ignore_index=True), metadata


def run() -> dict:
    """运行保守预测下界模型内部确认。"""

    frames = [pd.read_parquet(STORE / f"{year}.parquet", columns=RAW_COLUMNS) for year in ALL_YEARS]
    featured = add_excess_target(tradable_universe(build_features(pd.concat(frames, ignore_index=True))))
    predictions, model_meta = predict_walkforward(featured)
    trades = execute_daily_top3(predictions)
    cohort = summarize_cohorts(trades, predictions)
    base_curve = simulate_portfolio(trades, slots=15, cost_pct=0.25, holding_days=5)
    stress_curve = simulate_portfolio(trades, slots=15, cost_pct=0.50, holding_days=5)
    base_account = account_metrics(base_curve)
    stress_account = account_metrics(stress_curve)
    decision = evaluate(cohort, base_account, stress_account)
    result = {
        "research_id": RESEARCH_ID,
        "status": "internal_confirmation_pass" if decision["passed"] else "internal_confirmation_failed",
        "model_meta": model_meta,
        "uncertainty_diagnostics": {
            "selected_mean_prediction_std": float(trades["prediction_std"].mean()),
            "selected_max_prediction_std": float(trades["prediction_std"].max()),
        },
        "cohort_summary": cohort,
        "base_cost_account": base_account,
        "double_cost_account": stress_account,
        "decision": decision,
        "external_years_opened": False,
        "note": "保守下界固定为均值减一个总体标准差，不做系数搜索。",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / f"{RESEARCH_ID}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    trades.to_csv(REPORT_DIR / f"{RESEARCH_ID}_trades.csv", index=False, encoding="utf-8-sig")
    base_curve.to_csv(
        REPORT_DIR / f"{RESEARCH_ID}_account_curve.csv", index=False, encoding="utf-8-sig"
    )
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
