"""三个固定抽样种子的截面超额袋装模型研究。"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from research.research_integrity import purge_overlapping_label_tail

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

SEEDS = (20260808, 20260809, 20260810)
RESEARCH_ID = "clean_walkforward_excess_bagged3_20260808"


def sample_training_rows(
    frame: pd.DataFrame,
    years: tuple[int, ...],
    seed: int,
    *,
    prediction_start_date: str | None = None,
) -> pd.DataFrame:
    """每个集成成员按固定种子独立抽取同等规模年度样本。"""

    parts = []
    for year in years:
        part = frame[frame["year"] == year].dropna(subset=FEATURES + [EXCESS_TARGET]).copy()
        if len(part) > 150_000:
            part = part.sample(n=150_000, random_state=seed + year)
        parts.append(part)
    return purge_overlapping_label_tail(
        pd.concat(parts, ignore_index=True),
        horizon=5,
        prediction_start_date=prediction_start_date,
    )


def average_predictions(predictions: list[np.ndarray]) -> np.ndarray:
    """对冻结成员预测做无权重算术平均。"""

    return np.mean(np.vstack(predictions), axis=0)


def predict_walkforward(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """逐年训练三个成员并平均预测。"""

    outputs = []
    metadata = {}
    for train_years, predict_year in walkforward_splits():
        target = frame[frame["year"] == predict_year].dropna(subset=FEATURES).copy()
        member_predictions = []
        member_rows = []
        for seed in SEEDS:
            train = sample_training_rows(
                frame,
                train_years,
                seed,
                prediction_start_date=f"{predict_year}0101",
            )
            model = new_model().set_params(random_state=seed)
            model.fit(train[FEATURES], train[EXCESS_TARGET].clip(-15.0, 15.0))
            member_predictions.append(model.predict(target[FEATURES]))
            member_rows.append(int(len(train)))
        target["prediction"] = average_predictions(member_predictions)
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
    """运行三成员袋装模型内部确认。"""

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
        "cohort_summary": cohort,
        "base_cost_account": base_account,
        "double_cost_account": stress_account,
        "decision": decision,
        "external_years_opened": False,
        "note": "只使用预注册三个种子的无权重平均，不挑成员。",
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
