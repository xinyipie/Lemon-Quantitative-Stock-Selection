"""最近三年市场方向头叠加袋装选股的六年研究确认。"""

from __future__ import annotations

import json

import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from research.clean_bagged_lcb_existing_regime_gate import summarize
from research.clean_bagged_lcb_market_head_2019_2024 import (
    INTERNAL_TRADES,
    MARKET_FEATURES,
    MARKET_TARGET,
    RESEARCH_YEARS,
    VALIDATION_TRADES,
    build_market_daily,
    evaluate_market_head,
)
from research.clean_bagged_lcb_market_head_hard_gate_2019_2024 import apply_market_hard_gate
from research.clean_walkforward_technical_hgb_excess_target import (
    REPORT_DIR,
    account_metrics,
    simulate_portfolio,
)

RESEARCH_ID = "clean_bagged_lcb_market_head_rolling3y_2019_2024_20260808"


def predict_market_rolling3y() -> tuple[pd.DataFrame, dict]:
    """每个预测年仅用最近三个完整年份训练每日市场模型。"""

    frames = {year: build_market_daily(year) for year in range(2016, 2025)}
    predictions = []
    metadata = {}
    for predict_year in RESEARCH_YEARS:
        train_years = list(range(predict_year - 3, predict_year))
        train = pd.concat([frames[year] for year in train_years], ignore_index=True)
        target = frames[predict_year].copy()
        model = make_pipeline(StandardScaler(), Ridge(alpha=1.0))
        model.fit(train[MARKET_FEATURES], train[MARKET_TARGET].clip(-10.0, 10.0))
        target["market_prediction"] = model.predict(target[MARKET_FEATURES])
        correlation = target["market_prediction"].corr(target[MARKET_TARGET], method="spearman")
        predictions.append(target)
        metadata[str(predict_year)] = {
            "train_years": train_years,
            "training_days": int(len(train)),
            "prediction_days": int(len(target)),
            "spearman": float(correlation) if pd.notna(correlation) else None,
        }
    return pd.concat(predictions, ignore_index=True), metadata


def run() -> dict:
    """运行最近三年市场头六年研究确认。"""

    trades = pd.concat(
        [
            pd.read_csv(INTERNAL_TRADES, dtype={"trade_date": str}),
            pd.read_csv(VALIDATION_TRADES, dtype={"trade_date": str}),
        ],
        ignore_index=True,
    )
    trades["trade_date"] = trades["trade_date"].astype(str).str.replace(".0", "", regex=False)
    market, market_meta = predict_market_rolling3y()
    market["trade_date"] = market["trade_date"].astype(str)
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
        "note": "市场头训练窗固定三年，不测试相邻窗口。",
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
