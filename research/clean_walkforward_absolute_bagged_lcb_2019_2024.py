"""未来五日绝对收益三成员保守下界模型的六年研究确认。"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from research.clean_bagged_lcb_existing_regime_gate import evaluate, summarize
from research.clean_walkforward_excess_bagged3 import SEEDS
from research.clean_walkforward_excess_bagged_lcb import conservative_score
from research.clean_walkforward_technical_hgb_excess_target import (
    FEATURES,
    RAW_COLUMNS,
    REPORT_DIR,
    STORE,
    TARGET,
    account_metrics,
    add_excess_target,
    build_features,
    execute_daily_top3,
    new_model,
    simulate_portfolio,
    tradable_universe,
)

PREDICT_YEARS = (2019, 2020, 2021, 2022, 2023, 2024)
RESEARCH_ID = "clean_walkforward_absolute_bagged_lcb_2019_2024_20260808"


def load_featured_year(year: int) -> pd.DataFrame:
    """按年构造修复尺度后的T日特征和截面基准。"""

    raw = pd.read_parquet(STORE / f"{year}.parquet", columns=RAW_COLUMNS)
    return add_excess_target(tradable_universe(build_features(raw)))


def sample_member_year(frame: pd.DataFrame, year: int, seed: int) -> pd.DataFrame:
    """按固定年度上限抽取绝对收益训练样本。"""

    part = frame.dropna(subset=FEATURES + [TARGET]).copy()
    if len(part) > 150_000:
        part = part.sample(n=150_000, random_state=seed + year)
    return part[FEATURES + [TARGET]].reset_index(drop=True)


def predict_walkforward() -> tuple[pd.DataFrame, dict]:
    """从2019到2024逐年扩展训练并锁定当年Top3。"""

    member_samples: dict[int, list[pd.DataFrame]] = {seed: [] for seed in SEEDS}
    for year in range(2016, min(PREDICT_YEARS)):
        featured = load_featured_year(year)
        for seed in SEEDS:
            member_samples[seed].append(sample_member_year(featured, year, seed))

    trades = []
    metadata = {}
    for predict_year in PREDICT_YEARS:
        target = load_featured_year(predict_year).dropna(subset=FEATURES).copy()
        member_predictions = []
        member_rows = []
        for seed in SEEDS:
            train = pd.concat(member_samples[seed], ignore_index=True)
            model = new_model().set_params(random_state=seed)
            model.fit(train[FEATURES], train[TARGET].clip(-15.0, 15.0))
            member_predictions.append(model.predict(target[FEATURES]))
            member_rows.append(int(len(train)))
            del train
        mean, std, lower_bound = conservative_score(member_predictions)
        target["prediction_mean"] = mean
        target["prediction_std"] = std
        target["prediction"] = lower_bound
        target["prediction_rank"] = target.groupby("trade_date")["prediction"].rank(pct=True)
        target["train_end_year"] = predict_year - 1
        trades.append(execute_daily_top3(target))
        metadata[str(predict_year)] = {
            "train_years": list(range(2016, predict_year)),
            "member_training_rows": member_rows,
            "prediction_rows": int(len(target)),
        }
        for seed in SEEDS:
            member_samples[seed].append(sample_member_year(target, predict_year, seed))
        del target
    return pd.concat(trades, ignore_index=True), metadata


def evaluate_absolute(cohort: dict, base_account: dict, stress_account: dict) -> dict:
    """收紧样本门槛到六年每日覆盖，其余沿用六年确认标准。"""

    decision = evaluate(cohort, base_account, stress_account)
    decision["checks"]["minimum_daily_cohorts"] = cohort["cohorts"] >= 1200
    decision["checks"]["minimum_cohorts_each_year"] = all(
        cohort["yearly"][str(year)]["cohorts"] >= 200 for year in PREDICT_YEARS
    )
    decision["passed"] = all(decision["checks"].values())
    return decision


def run() -> dict:
    """运行绝对收益目标六年研究确认。"""

    trades, model_meta = predict_walkforward()
    cohort = summarize(trades)
    base_curve = simulate_portfolio(trades, slots=15, cost_pct=0.25, holding_days=5)
    stress_curve = simulate_portfolio(trades, slots=15, cost_pct=0.50, holding_days=5)
    base_account = account_metrics(base_curve)
    stress_account = account_metrics(stress_curve)
    decision = evaluate_absolute(cohort, base_account, stress_account)
    result = {
        "research_id": RESEARCH_ID,
        "status": "six_year_confirmation_pass" if decision["passed"] else "six_year_confirmation_failed",
        "model_meta": model_meta,
        "cohort_summary": cohort,
        "base_cost_account": base_account,
        "double_cost_account": stress_account,
        "decision": decision,
        "new_holdout_opened": False,
        "note": "直接预测绝对收益，不与超额目标做事后混合。",
    }
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
