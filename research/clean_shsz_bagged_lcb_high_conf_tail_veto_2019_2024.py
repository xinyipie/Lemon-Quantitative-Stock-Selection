"""沪深A股候选叠加高置信市场尾部风险 veto 的六年研究确认。"""

from __future__ import annotations

import json

import pandas as pd

from research.clean_bagged_lcb_existing_regime_gate import evaluate, summarize
from research.clean_bagged_lcb_market_head_2019_2024 import (
    INTERNAL_TRADES,
    VALIDATION_TRADES,
)
from research.clean_bagged_lcb_market_tail_risk_classifier_2019_2024 import (
    predict_market_tail_risk_walkforward,
)
from research.clean_walkforward_technical_hgb_excess_target import (
    REPORT_DIR,
    account_metrics,
    simulate_portfolio,
)

RESEARCH_ID = "clean_shsz_bagged_lcb_high_conf_tail_veto_2019_2024_20260808"
HIGH_CONFIDENCE_RISK_THRESHOLD = 2.0 / 3.0


def apply_shsz_high_confidence_tail_veto(
    trades: pd.DataFrame, market: pd.DataFrame
) -> pd.DataFrame:
    """保留沪深股票，并只删除高置信市场尾部风险日。"""

    shsz = trades[trades["ts_code"].astype(str).str.endswith((".SH", ".SZ"))].copy()
    merged = shsz.merge(
        market[["trade_date", "market_tail_risk_probability"]],
        on="trade_date",
        how="left",
        validate="many_to_one",
    )
    return merged[
        merged["market_tail_risk_probability"].notna()
        & (merged["market_tail_risk_probability"] <= HIGH_CONFIDENCE_RISK_THRESHOLD)
    ].copy()


def run() -> dict:
    """运行沪深研究域与高置信尾部风险 veto 六年确认。"""

    trades = pd.concat(
        [
            pd.read_csv(INTERNAL_TRADES, dtype={"trade_date": str}),
            pd.read_csv(VALIDATION_TRADES, dtype={"trade_date": str}),
        ],
        ignore_index=True,
    )
    market, market_meta = predict_market_tail_risk_walkforward()
    market["trade_date"] = market["trade_date"].astype(str)
    gated = apply_shsz_high_confidence_tail_veto(trades, market)
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
            "eligible_shsz_trades": int(
                trades["ts_code"].astype(str).str.endswith((".SH", ".SZ")).sum()
            ),
            "kept_trades": int(len(gated)),
            "kept_dates": int(gated["trade_date"].nunique()),
            "north_exchange_trades_kept": int(
                gated["ts_code"].astype(str).str.endswith(".BJ").sum()
            ),
        },
        "cohort_summary": cohort,
        "base_cost_account": base_account,
        "double_cost_account": stress_account,
        "decision": decision,
        "new_holdout_opened": False,
        "note": "北交所保留给独立模型；沪深候选仅在尾部风险概率超过三分之二时暂停。",
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
