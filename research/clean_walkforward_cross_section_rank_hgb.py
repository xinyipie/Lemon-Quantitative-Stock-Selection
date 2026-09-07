"""每日截面排名归一化技术模型的内部确认研究。"""

from __future__ import annotations

import json

import pandas as pd

from research.clean_walkforward_technical_hgb_excess_target import (
    ALL_YEARS,
    FEATURES,
    PREDICT_YEARS,
    RAW_COLUMNS,
    REPORT_DIR,
    STORE,
    TARGET,
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

RANK_FEATURES = [f"rank_{column}" for column in FEATURES]
RANK_TARGET = "ret_5d_rank"
RESEARCH_ID = "clean_walkforward_cross_section_rank_hgb_20260808"


def add_cross_section_ranks(frame: pd.DataFrame) -> pd.DataFrame:
    """只使用同一交易日可见截面构造中心化百分位特征。"""

    result = frame.copy()
    for source, target in zip(FEATURES, RANK_FEATURES):
        result[target] = result.groupby("trade_date")[source].rank(pct=True) - 0.5
    result[RANK_TARGET] = result.groupby("trade_date")[TARGET].rank(pct=True) - 0.5
    return result


def sample_training_rows(frame: pd.DataFrame, years: tuple[int, ...]) -> pd.DataFrame:
    """使用固定年度样本上限，避免较新年份支配训练。"""

    parts = []
    for year in years:
        part = frame[frame["year"] == year].dropna(subset=RANK_FEATURES + [RANK_TARGET]).copy()
        if len(part) > 150_000:
            part = part.sample(n=150_000, random_state=20260808 + year)
        parts.append(part)
    return pd.concat(parts, ignore_index=True)


def predict_walkforward(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """逐年扩展训练每日截面排名模型。"""

    predictions = []
    metadata = {}
    for train_years, predict_year in walkforward_splits():
        train = sample_training_rows(frame, train_years)
        target = frame[frame["year"] == predict_year].dropna(subset=RANK_FEATURES).copy()
        model = new_model()
        model.fit(train[RANK_FEATURES], train[RANK_TARGET])
        target["prediction"] = model.predict(target[RANK_FEATURES])
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
    """运行截面排名模型的内部批次和账户确认。"""

    frames = [pd.read_parquet(STORE / f"{year}.parquet", columns=RAW_COLUMNS) for year in ALL_YEARS]
    featured = add_cross_section_ranks(
        tradable_universe(build_features(pd.concat(frames, ignore_index=True)))
    )
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
        "note": "所有排名均按信号日独立构造；内部门槛失败时不打开2022-2024。",
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
