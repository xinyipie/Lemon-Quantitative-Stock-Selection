"""截面超额头与每日市场方向头分层组合的六年研究确认。"""

from __future__ import annotations

import json

import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from research.clean_bagged_lcb_existing_regime_gate import evaluate, summarize
from research.clean_walkforward_absolute_bagged_lcb_2019_2024 import load_featured_year
from research.clean_walkforward_technical_hgb_excess_target import (
    REPORT_DIR,
    TARGET,
    account_metrics,
    simulate_portfolio,
)

RESEARCH_YEARS = (2019, 2020, 2021, 2022, 2023, 2024)
MARKET_FEATURES = [
    "market_breadth_ma20",
    "market_breadth_ma60",
    "market_median_ret5",
    "market_median_ret20",
    "market_median_ret60",
    "market_median_pct_chg",
    "market_dispersion_pct_chg",
]
MARKET_TARGET = "market_future_5d"
INTERNAL_TRADES = REPORT_DIR / "clean_walkforward_excess_bagged_lcb_20260808_trades.csv"
VALIDATION_TRADES = REPORT_DIR / "validation_clean_walkforward_excess_bagged_lcb_20260808_trades.csv"
RESEARCH_ID = "clean_bagged_lcb_market_head_2019_2024_20260808"


def build_market_daily(year: int) -> pd.DataFrame:
    """每个交易日仅保留一行市场状态和未来平均收益。"""

    featured = load_featured_year(year)
    aggregations = {column: (column, "first") for column in MARKET_FEATURES}
    aggregations[MARKET_TARGET] = (TARGET, "mean")
    daily = featured.groupby("trade_date", as_index=False).agg(**aggregations)
    daily["year"] = year
    return daily.dropna(subset=MARKET_FEATURES + [MARKET_TARGET]).reset_index(drop=True)


def predict_market_walkforward() -> tuple[pd.DataFrame, dict]:
    """用预测年前全部完整年份训练每日市场Ridge。"""

    frames = {year: build_market_daily(year) for year in range(2016, 2025)}
    predictions = []
    metadata = {}
    for predict_year in RESEARCH_YEARS:
        train = pd.concat([frames[year] for year in range(2016, predict_year)], ignore_index=True)
        target = frames[predict_year].copy()
        model = make_pipeline(StandardScaler(), Ridge(alpha=1.0))
        model.fit(train[MARKET_FEATURES], train[MARKET_TARGET].clip(-10.0, 10.0))
        target["market_prediction"] = model.predict(target[MARKET_FEATURES])
        correlation = target["market_prediction"].corr(target[MARKET_TARGET], method="spearman")
        predictions.append(target)
        metadata[str(predict_year)] = {
            "train_years": list(range(2016, predict_year)),
            "training_days": int(len(train)),
            "prediction_days": int(len(target)),
            "spearman": float(correlation) if pd.notna(correlation) else None,
        }
    return pd.concat(predictions, ignore_index=True), metadata


def apply_predicted_absolute_gate(trades: pd.DataFrame, market: pd.DataFrame) -> pd.DataFrame:
    """个股超额保守下界加市场预测后，仅保留绝对预测为正信号。"""

    merged = trades.merge(
        market[["trade_date", "market_prediction"]],
        on="trade_date",
        how="left",
        validate="many_to_one",
    )
    merged["predicted_absolute_return"] = merged["prediction"] + merged["market_prediction"]
    return merged[merged["predicted_absolute_return"] > 0.0].copy()


def evaluate_market_head(
    cohort: dict,
    base_account: dict,
    stress_account: dict,
    market_meta: dict,
) -> dict:
    """联合检验市场头有效性和六年策略门槛。"""

    decision = evaluate(cohort, base_account, stress_account)
    correlations = [market_meta[str(year)]["spearman"] for year in RESEARCH_YEARS]
    weighted = sum(
        market_meta[str(year)]["spearman"] * market_meta[str(year)]["prediction_days"]
        for year in RESEARCH_YEARS
    ) / sum(market_meta[str(year)]["prediction_days"] for year in RESEARCH_YEARS)
    decision["checks"]["minimum_market_forecast_overall_spearman"] = weighted >= 0.05
    decision["checks"]["minimum_positive_market_forecast_years"] = sum(
        correlation > 0 for correlation in correlations
    ) >= 4
    decision["passed"] = all(decision["checks"].values())
    return decision


def run() -> dict:
    """运行分层市场头六年研究确认。"""

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
    gated = apply_predicted_absolute_gate(trades, market)
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
        "note": "市场方向按日建模，个股超额与市场预测仅在同一百分比单位相加。",
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
