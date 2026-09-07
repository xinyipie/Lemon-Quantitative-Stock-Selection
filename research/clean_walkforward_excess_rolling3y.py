"""固定三年滚动训练窗的五日截面超额模型研究。"""

from __future__ import annotations

import json

import pandas as pd

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
    sample_training_rows,
    simulate_portfolio,
    summarize_cohorts,
    tradable_universe,
)

ROLLING_SPLITS = [
    ((2016, 2017, 2018), 2019),
    ((2017, 2018, 2019), 2020),
    ((2018, 2019, 2020), 2021),
]
RESEARCH_ID = "clean_walkforward_excess_rolling3y_20260808"


def rolling_splits() -> list[tuple[tuple[int, ...], int]]:
    """返回预注册的三年滚动训练切分。"""

    return list(ROLLING_SPLITS)


def predict_walkforward(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """仅使用预测年前最近三个完整年份训练。"""

    predictions = []
    metadata = {}
    for train_years, predict_year in rolling_splits():
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


def run() -> dict:
    """运行滚动三年超额模型内部确认。"""

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
        "note": "只改变训练窗时效性；内部失败时不打开2022-2024。",
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
