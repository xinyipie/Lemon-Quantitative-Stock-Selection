"""用日内标准化预测优势进行弃权的技术HGB走步研究。"""

from __future__ import annotations

import json

import pandas as pd

from research.clean_financial_relative_confidence import enforce_same_stock_cooldown
from research.clean_walkforward_technical_hgb import (
    ALL_YEARS,
    COST_PCT,
    PREDICT_YEARS,
    RAW_COLUMNS,
    REPORT_DIR,
    STORE,
    TARGET,
    build_features,
    predict_walkforward,
    summarize,
    tradable_universe,
)


def add_daily_prediction_zscore(predictions: pd.DataFrame) -> pd.DataFrame:
    """把预测值转为对平移和正比例缩放不敏感的日内置信度。"""

    work = predictions.copy()
    daily = work.groupby("trade_date")["prediction"].agg(prediction_median="median", prediction_std="std")
    work = work.merge(daily, on="trade_date", how="left", validate="many_to_one")
    work["prediction_zscore"] = (
        (work["prediction"] - work["prediction_median"]) / work["prediction_std"].where(work["prediction_std"] > 0)
    )
    return work


def select_zscore_trades(predictions: pd.DataFrame, all_dates: list[str]) -> pd.DataFrame:
    """锁定每日Top1，仅在标准化优势达到2时执行。"""

    scored = add_daily_prediction_zscore(predictions)
    locked = (
        scored.sort_values(
            ["trade_date", "prediction", "ts_code"],
            ascending=[True, False, True],
            kind="mergesort",
        )
        .groupby("trade_date", group_keys=False)
        .head(1)
        .copy()
    )
    locked = locked[locked["prediction_zscore"] >= 2.0].copy()
    executed = locked[
        locked["entry_open"].notna()
        & locked[TARGET].notna()
        & (locked["entry_gap_pct"] < 7.0)
        & (locked["entry_gap_pct"] > -9.5)
    ].copy()
    executed = enforce_same_stock_cooldown(executed, all_dates, cooldown_days=5)
    executed["net_return"] = executed[TARGET] - COST_PCT
    return executed


def evaluate(summary: dict) -> dict:
    """执行冻结的标准化弃权门槛。"""

    checks = {
        "minimum_total_trades": summary["trades"] >= 300,
        "minimum_trades_each_year": all(summary["yearly"][str(year)]["trades"] >= 80 for year in PREDICT_YEARS),
        "minimum_average_net_return_pct": (summary["average_net_return_pct"] or -999) >= 0.50,
        "minimum_profit_factor": (summary["profit_factor"] or 0) >= 1.20,
        "required_positive_years": all(
            (summary["yearly"][str(year)]["average_net_return_pct"] or -999) > 0 for year in PREDICT_YEARS
        ),
        "minimum_edge_vs_same_day_universe_pct": (summary["edge_vs_same_day_universe_pct"] or -999) >= 0.30,
        "minimum_trimmed_mean_pct": (summary["trimmed_mean_pct"] or -999) > 0,
        "minimum_double_cost_stress_mean_pct": (summary["double_cost_stress_mean_pct"] or -999) > 0,
        "maximum_single_stock_share": (summary["maximum_single_stock_share"] or 999) <= 0.03,
        "maximum_single_industry_share": (summary["maximum_single_industry_share"] or 999) <= 0.15,
        "minimum_top_prediction_quintile_edge_pct_each_year": all(
            (summary["prediction_calibration"][str(year)]["top_minus_bottom_pct"] or -999) >= 0.20
            for year in PREDICT_YEARS
        ),
    }
    return {"passed": all(checks.values()), "checks": checks}


def run() -> dict:
    """重新走步训练并执行标准化弃权确认。"""

    frames = [pd.read_parquet(STORE / f"{year}.parquet", columns=RAW_COLUMNS) for year in ALL_YEARS]
    featured = tradable_universe(build_features(pd.concat(frames, ignore_index=True)))
    predictions, model_meta = predict_walkforward(featured)
    trades = select_zscore_trades(predictions, sorted(featured["trade_date"].unique().tolist()))
    summary = summarize(trades, predictions)
    decision = evaluate(summary)
    result = {
        "research_id": "clean_walkforward_technical_hgb_zscore_abstention_20260808",
        "status": "internal_confirmation_pass" if decision["passed"] else "internal_confirmation_failed",
        "model_meta": model_meta,
        "summary": summary,
        "decision": decision,
        "external_years_opened": False,
        "note": "仅使用日内标准化置信度弃权；失败时不打开2022-2024。",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "clean_walkforward_technical_hgb_zscore_abstention_20260808.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    trades.to_csv(
        REPORT_DIR / "clean_walkforward_technical_hgb_zscore_abstention_trades_20260808.csv",
        index=False,
        encoding="utf-8-sig",
    )
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
