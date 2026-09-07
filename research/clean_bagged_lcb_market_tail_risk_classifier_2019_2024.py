"""市场五日尾部风险分类器叠加冻结个股候选的六年研究确认。"""

from __future__ import annotations

import json

import pandas as pd
from research.research_integrity import purge_overlapping_label_tail
from sklearn.utils.class_weight import compute_sample_weight

from research.clean_bagged_lcb_existing_regime_gate import evaluate, summarize
from research.clean_bagged_lcb_market_head_2019_2024 import (
    INTERNAL_TRADES,
    MARKET_FEATURES,
    MARKET_TARGET,
    RESEARCH_YEARS,
    VALIDATION_TRADES,
    build_market_daily,
)
from research.clean_bagged_lcb_market_hgb_classifier_2019_2024 import new_market_classifier
from research.clean_walkforward_technical_hgb_excess_target import (
    REPORT_DIR,
    account_metrics,
    simulate_portfolio,
)

RESEARCH_ID = "clean_bagged_lcb_market_tail_risk_classifier_2019_2024_20260808"
TAIL_RISK_RETURN_PCT = -2.0


def predict_market_tail_risk_walkforward() -> tuple[pd.DataFrame, dict]:
    """仅用预测年前的完整年份训练五日尾部风险分类器。"""

    frames = {year: build_market_daily(year) for year in range(2016, 2025)}
    predictions = []
    metadata = {}
    for predict_year in RESEARCH_YEARS:
        train = pd.concat([frames[year] for year in range(2016, predict_year)], ignore_index=True)
        train = purge_overlapping_label_tail(
            train,
            horizon=5,
            prediction_start_date=f"{predict_year}0101",
        )
        target = frames[predict_year].copy()
        labels = (train[MARKET_TARGET] <= TAIL_RISK_RETURN_PCT).astype(int)
        weights = compute_sample_weight(class_weight="balanced", y=labels)
        model = new_market_classifier()
        model.fit(train[MARKET_FEATURES], labels, sample_weight=weights)
        target["market_tail_risk_probability"] = model.predict_proba(target[MARKET_FEATURES])[:, 1]
        target["market_tail_risk_veto"] = target["market_tail_risk_probability"] > 0.50
        correlation = target["market_tail_risk_probability"].corr(
            target[MARKET_TARGET], method="spearman"
        )
        predictions.append(target)
        metadata[str(predict_year)] = {
            "train_years": list(range(2016, predict_year)),
            "training_days": int(len(train)),
            "prediction_days": int(len(target)),
            "training_tail_risk_rate": float(labels.mean()),
            "vetoed_days": int(target["market_tail_risk_veto"].sum()),
            "risk_probability_vs_return_spearman": (
                float(correlation) if pd.notna(correlation) else None
            ),
        }
    return pd.concat(predictions, ignore_index=True), metadata


def apply_market_tail_risk_veto(trades: pd.DataFrame, market: pd.DataFrame) -> pd.DataFrame:
    """仅删除模型判定为高概率五日尾部风险的候选日。"""

    merged = trades.merge(
        market[["trade_date", "market_tail_risk_probability", "market_tail_risk_veto"]],
        on="trade_date",
        how="left",
        validate="many_to_one",
    )
    return merged[~merged["market_tail_risk_veto"].fillna(True)].copy()


def run() -> dict:
    """运行市场尾部风险 veto 六年研究确认。"""

    trades = pd.concat(
        [
            pd.read_csv(INTERNAL_TRADES, dtype={"trade_date": str}),
            pd.read_csv(VALIDATION_TRADES, dtype={"trade_date": str}),
        ],
        ignore_index=True,
    )
    market, market_meta = predict_market_tail_risk_walkforward()
    market["trade_date"] = market["trade_date"].astype(str)
    gated = apply_market_tail_risk_veto(trades, market)
    cohort = summarize(gated)
    base_curve = simulate_portfolio(gated, slots=15, cost_pct=0.25, holding_days=5)
    stress_curve = simulate_portfolio(gated, slots=15, cost_pct=0.50, holding_days=5)
    base_account = account_metrics(base_curve)
    stress_account = account_metrics(stress_curve)
    decision = evaluate(cohort, base_account, stress_account)
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
        "note": "个股候选完全冻结，只删除T日市场截面预测出的高概率五日尾部风险日。",
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
