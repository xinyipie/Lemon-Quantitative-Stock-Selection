"""持续恶化市场宽度门控的内部确认研究。"""

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

BREADTH_DELTA = "market_breadth_ma20_delta5"
RISK_OFF = "falling_breadth_risk_off"
RESEARCH_ID = "clean_walkforward_excess_falling_breadth_gate_20260808"


def add_falling_breadth_gate(frame: pd.DataFrame) -> pd.DataFrame:
    """用T日与五个交易日前的市场宽度构造持续恶化标记。"""

    daily = (
        frame[["trade_date", "market_breadth_ma20", "market_median_ret5", "market_median_ret20"]]
        .drop_duplicates("trade_date")
        .sort_values("trade_date")
        .copy()
    )
    daily[BREADTH_DELTA] = daily["market_breadth_ma20"] - daily["market_breadth_ma20"].shift(5)
    daily[RISK_OFF] = (
        (daily["market_median_ret5"] < 0)
        & (daily["market_median_ret20"] < 0)
        & (daily[BREADTH_DELTA] < 0)
    )
    return frame.merge(
        daily[["trade_date", BREADTH_DELTA, RISK_OFF]],
        on="trade_date",
        how="left",
        validate="many_to_one",
    )


def apply_gate(trades: pd.DataFrame) -> pd.DataFrame:
    """不递补地移除持续恶化阶段信号。"""

    return trades[~trades[RISK_OFF].fillna(False)].copy()


def run() -> dict:
    """运行动态市场宽度门控内部确认。"""

    frames = [pd.read_parquet(STORE / f"{year}.parquet", columns=RAW_COLUMNS) for year in ALL_YEARS]
    featured = add_falling_breadth_gate(
        add_excess_target(tradable_universe(build_features(pd.concat(frames, ignore_index=True))))
    )
    predictions, model_meta = predict_walkforward_excess(featured)
    all_trades = execute_daily_top3(predictions)
    trades = apply_gate(all_trades)
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
        "gate_diagnostics": {
            "all_trades": int(len(all_trades)),
            "kept_trades": int(len(trades)),
            "removed_trades": int(len(all_trades) - len(trades)),
            "removed_dates": int(all_trades.loc[all_trades[RISK_OFF].fillna(False), "trade_date"].nunique()),
        },
        "cohort_summary": cohort,
        "base_cost_account": base_account,
        "double_cost_account": stress_account,
        "decision": decision,
        "external_years_opened": False,
        "note": "门控只识别持续恶化，不排除已经超跌但开始修复的市场。",
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
