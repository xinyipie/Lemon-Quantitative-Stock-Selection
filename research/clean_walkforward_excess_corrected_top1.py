"""修复尺度后每日Top1精度候选内部确认。"""

from __future__ import annotations

import json

import pandas as pd

from research.clean_walkforward_technical_hgb_excess_target import (
    ALL_YEARS,
    RAW_COLUMNS,
    REPORT_DIR,
    STORE,
    TARGET,
    account_metrics,
    add_excess_target,
    build_features,
    evaluate,
    predict_walkforward_excess,
    simulate_portfolio,
    summarize_cohorts,
    tradable_universe,
)

RESEARCH_ID = "clean_walkforward_excess_corrected_top1_20260808"


def execute_daily_top1(predictions: pd.DataFrame) -> pd.DataFrame:
    """先锁定每日预测第一名，再执行T+1成交检查且不递补。"""

    locked = (
        predictions.sort_values(["trade_date", "prediction", "ts_code"], ascending=[True, False, True])
        .groupby("trade_date", as_index=False, group_keys=False)
        .head(1)
        .copy()
    )
    executed = locked[
        locked["entry_open"].notna()
        & locked[TARGET].notna()
        & (locked["entry_gap_pct"] < 7.0)
        & (locked["entry_gap_pct"] > -9.5)
    ].copy()
    executed["net_return"] = executed[TARGET] - 0.25
    return executed


def run() -> dict:
    """运行每日Top1内部确认。"""

    frames = [pd.read_parquet(STORE / f"{year}.parquet", columns=RAW_COLUMNS) for year in ALL_YEARS]
    featured = add_excess_target(tradable_universe(build_features(pd.concat(frames, ignore_index=True))))
    predictions, model_meta = predict_walkforward_excess(featured)
    trades = execute_daily_top1(predictions)
    cohort = summarize_cohorts(trades, predictions)
    base_curve = simulate_portfolio(trades, slots=5, cost_pct=0.25, holding_days=5)
    stress_curve = simulate_portfolio(trades, slots=5, cost_pct=0.50, holding_days=5)
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
        "note": "只测试预注册Top1，不在失败后尝试Top2。",
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
