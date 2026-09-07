"""仅保留正预测超额信号的内部确认研究。"""

from __future__ import annotations

import json

import pandas as pd

from research.clean_walkforward_technical_hgb_excess_target import (
    ALL_YEARS,
    RAW_COLUMNS,
    REPORT_DIR,
    STORE,
    account_metrics,
    add_excess_target,
    build_features,
    evaluate,
    execute_daily_top3,
    predict_walkforward_excess,
    simulate_portfolio,
    summarize_cohorts,
    tradable_universe,
)

RESEARCH_ID = "clean_walkforward_excess_positive_abstention_20260808"


def apply_positive_abstention(trades: pd.DataFrame) -> pd.DataFrame:
    """锁定Top3和成交检查后，仅保留预测超额为正的信号。"""

    return trades[trades["prediction"] > 0.0].copy()


def run() -> dict:
    """运行零阈值弃权候选的内部确认。"""

    frames = [pd.read_parquet(STORE / f"{year}.parquet", columns=RAW_COLUMNS) for year in ALL_YEARS]
    featured = add_excess_target(tradable_universe(build_features(pd.concat(frames, ignore_index=True))))
    predictions, model_meta = predict_walkforward_excess(featured)
    trades = apply_positive_abstention(execute_daily_top3(predictions))
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
        "note": "阈值固定为有经济含义的零，不做回测阈值搜索。",
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
