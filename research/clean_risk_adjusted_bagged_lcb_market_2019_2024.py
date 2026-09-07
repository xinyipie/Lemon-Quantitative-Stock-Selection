"""风险调整超额下界排序叠加滚动市场头的六年研究确认。"""

from __future__ import annotations

import json

import pandas as pd

from research.clean_bagged_lcb_existing_regime_gate import summarize
from research.clean_bagged_lcb_market_head_2019_2024 import evaluate_market_head
from research.clean_bagged_lcb_market_head_hard_gate_2019_2024 import apply_market_hard_gate
from research.clean_bagged_lcb_market_head_rolling3y_2019_2024 import predict_market_rolling3y
from research.clean_walkforward_absolute_bagged_lcb_2019_2024 import load_featured_year
from research.clean_walkforward_excess_bagged3 import SEEDS
from research.clean_walkforward_excess_bagged_lcb import conservative_score
from research.clean_walkforward_technical_hgb_excess_target import (
    EXCESS_TARGET,
    FEATURES,
    REPORT_DIR,
    TARGET,
    account_metrics,
    execute_daily_top3,
    new_model,
    simulate_portfolio,
)
from research.validate_walkforward_excess_bagged_lcb import sample_member_year

PREDICT_YEARS = (2019, 2020, 2021, 2022, 2023, 2024)
RESEARCH_ID = "clean_risk_adjusted_bagged_lcb_market_2019_2024_20260808"


def risk_adjusted_score(lower_bound: pd.Series, volatility: pd.Series) -> pd.Series:
    """按T日20日波动率计算单位风险超额下界。"""

    safe_volatility = pd.to_numeric(volatility, errors="coerce").clip(lower=1e-6)
    return lower_bound / safe_volatility


def predict_stock_walkforward() -> tuple[pd.DataFrame, dict]:
    """逐年扩展训练袋装超额模型并按风险调整分数锁定Top3。"""

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
            model.fit(train[FEATURES], train[EXCESS_TARGET].clip(-15.0, 15.0))
            member_predictions.append(model.predict(target[FEATURES]))
            member_rows.append(int(len(train)))
            del train
        mean, std, lower_bound = conservative_score(member_predictions)
        target["prediction_mean"] = mean
        target["prediction_std"] = std
        target["prediction_lower_bound"] = lower_bound
        target["prediction"] = risk_adjusted_score(
            pd.Series(lower_bound, index=target.index), target["volatility_20"]
        )
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


def run() -> dict:
    """运行风险调整股票头与滚动市场头六年研究确认。"""

    trades, stock_meta = predict_stock_walkforward()
    market, market_meta = predict_market_rolling3y()
    market["trade_date"] = market["trade_date"].astype(str)
    trades["trade_date"] = trades["trade_date"].astype(str)
    gated = apply_market_hard_gate(trades, market)
    cohort = summarize(gated)
    base_curve = simulate_portfolio(gated, slots=15, cost_pct=0.25, holding_days=5)
    stress_curve = simulate_portfolio(gated, slots=15, cost_pct=0.50, holding_days=5)
    base_account = account_metrics(base_curve)
    stress_account = account_metrics(stress_curve)
    decision = evaluate_market_head(cohort, base_account, stress_account, market_meta)
    result = {
        "research_id": RESEARCH_ID,
        "status": "six_year_confirmation_pass" if decision["passed"] else "six_year_confirmation_failed",
        "stock_model_meta": stock_meta,
        "market_model_meta": market_meta,
        "gate_diagnostics": {
            "all_trades": int(len(trades)),
            "kept_trades": int(len(gated)),
            "removed_trades": int(len(trades) - len(gated)),
            "kept_dates": int(gated["trade_date"].nunique()),
        },
        "cohort_summary": cohort,
        "base_cost_account": base_account,
        "double_cost_account": stress_account,
        "decision": decision,
        "new_holdout_opened": False,
        "note": "风险调整只改变日内排序，不改变固定等权槽位。",
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
