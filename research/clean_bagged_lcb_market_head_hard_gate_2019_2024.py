"""每日市场预测为正才允许个股Top3的六年研究确认。"""

from __future__ import annotations

import json

import pandas as pd

from research.clean_bagged_lcb_existing_regime_gate import summarize
from research.clean_bagged_lcb_market_head_2019_2024 import (
    INTERNAL_TRADES,
    VALIDATION_TRADES,
    evaluate_market_head,
    predict_market_walkforward,
)
from research.clean_walkforward_technical_hgb_excess_target import (
    REPORT_DIR,
    account_metrics,
    simulate_portfolio,
)

RESEARCH_ID = "clean_bagged_lcb_market_head_hard_gate_2019_2024_20260808"


def apply_market_hard_gate(trades: pd.DataFrame, market: pd.DataFrame) -> pd.DataFrame:
    """市场预测不为正时整日弃权，不用个股超额抵消。"""

    merged = trades.merge(
        market[["trade_date", "market_prediction"]],
        on="trade_date",
        how="left",
        validate="many_to_one",
    )
    return merged[merged["market_prediction"] > 0.0].copy()


def run() -> dict:
    """运行市场头独立硬门控六年研究确认。"""

    trades = pd.concat(
        [
            pd.read_csv(INTERNAL_TRADES, dtype={"trade_date": str}),
            pd.read_csv(VALIDATION_TRADES, dtype={"trade_date": str}),
        ],
        ignore_index=True,
    )
    trades["trade_date"] = trades["trade_date"].astype(str).str.replace(".0", "", regex=False)
    market, market_meta = predict_market_walkforward()
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
        "note": "市场头仅控制整日暴露，个股头仅负责日内排序。",
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
