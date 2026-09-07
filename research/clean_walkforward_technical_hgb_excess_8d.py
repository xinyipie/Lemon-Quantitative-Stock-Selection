"""八日截面超额技术模型的内部确认研究。"""

from __future__ import annotations

import json

import pandas as pd

from research.research_integrity import purge_overlapping_label_tail

from research.clean_walkforward_technical_hgb_excess_target import (
    ALL_YEARS,
    FEATURES,
    PREDICT_YEARS,
    RAW_COLUMNS,
    REPORT_DIR,
    STORE,
    account_metrics,
    build_features,
    evaluate,
    execute_daily_top3,
    new_model,
    simulate_portfolio,
    summarize_cohorts,
    tradable_universe,
    walkforward_splits,
)

TARGET_8D = "ret_8d"
EXCESS_TARGET_8D = "ret_8d_excess"
RESEARCH_ID = "clean_walkforward_technical_hgb_excess_8d_20260808"


def add_excess_target_8d(frame: pd.DataFrame) -> pd.DataFrame:
    """按信号日构造未来八日截面超额标签。"""

    result = frame.copy()
    daily_mean = result.groupby("trade_date")[TARGET_8D].transform("mean")
    result[EXCESS_TARGET_8D] = result[TARGET_8D] - daily_mean
    return result


def sample_training_rows_8d(
    frame: pd.DataFrame,
    years: tuple[int, ...],
    *,
    prediction_start_date: str | None = None,
) -> pd.DataFrame:
    """保持既有固定随机种子和年度样本上限。"""

    parts = []
    for year in years:
        part = frame[frame["year"] == year].dropna(subset=FEATURES + [EXCESS_TARGET_8D]).copy()
        if len(part) > 150_000:
            part = part.sample(n=150_000, random_state=20260808 + year)
        parts.append(part)
    return purge_overlapping_label_tail(
        pd.concat(parts, ignore_index=True),
        horizon=8,
        prediction_start_date=prediction_start_date,
    )


def predict_walkforward_8d(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """逐年扩展训练并预测八日截面超额。"""

    predictions = []
    metadata = {}
    for train_years, predict_year in walkforward_splits():
        train = sample_training_rows_8d(
            frame,
            train_years,
            prediction_start_date=f"{predict_year}0101",
        )
        target = frame[frame["year"] == predict_year].dropna(subset=FEATURES + [TARGET_8D]).copy()
        model = new_model()
        model.fit(train[FEATURES], train[EXCESS_TARGET_8D].clip(-20.0, 20.0))
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


def adapt_to_shared_evaluation(frame: pd.DataFrame) -> pd.DataFrame:
    """仅为复用冻结统计器，将八日收益映射到统一收益字段。"""

    result = frame.copy()
    result["ret_5d"] = result[TARGET_8D]
    return result


def run() -> dict:
    """运行八日模型的内部批次和账户确认。"""

    columns = list(dict.fromkeys(RAW_COLUMNS + [TARGET_8D]))
    frames = [pd.read_parquet(STORE / f"{year}.parquet", columns=columns) for year in ALL_YEARS]
    featured = add_excess_target_8d(
        tradable_universe(build_features(pd.concat(frames, ignore_index=True)))
    )
    predictions, model_meta = predict_walkforward_8d(featured)
    evaluation_predictions = adapt_to_shared_evaluation(predictions)
    trades = execute_daily_top3(evaluation_predictions)
    cohort = summarize_cohorts(trades, evaluation_predictions)
    base_curve = simulate_portfolio(trades, slots=24, cost_pct=0.25, holding_days=8)
    stress_curve = simulate_portfolio(trades, slots=24, cost_pct=0.50, holding_days=8)
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
        "note": "八日标签仅用于历史训练；内部双门槛失败时不打开2022-2024。",
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
