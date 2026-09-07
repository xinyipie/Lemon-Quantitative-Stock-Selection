"""沪深候选按市场尾部风险切换排序口径的六年研究确认。"""

from __future__ import annotations

import json

import pandas as pd

from research.clean_bagged_lcb_existing_regime_gate import evaluate, summarize
from research.clean_bagged_lcb_market_tail_risk_classifier_2019_2024 import (
    predict_market_tail_risk_walkforward,
)
from research.clean_risk_adjusted_bagged_lcb_market_2019_2024 import risk_adjusted_score
from research.clean_walkforward_absolute_bagged_lcb_2019_2024 import load_featured_year
from research.clean_walkforward_excess_bagged3 import SEEDS
from research.clean_walkforward_excess_bagged_lcb import conservative_score
from research.clean_walkforward_technical_hgb_excess_target import (
    EXCESS_TARGET,
    FEATURES,
    REPORT_DIR,
    account_metrics,
    execute_daily_top3,
    new_model,
    simulate_portfolio,
)
from research.validate_walkforward_excess_bagged_lcb import sample_member_year

PREDICT_YEARS = (2019, 2020, 2021, 2022, 2023, 2024)
RISK_REGIME_THRESHOLD = 0.50
RESEARCH_ID = "clean_shsz_conditional_risk_rank_2019_2024_20260808"


def eligible_shsz(frame: pd.DataFrame) -> pd.DataFrame:
    """统一限定沪深研究域，避免北交所样本进入训练或预测。"""

    return frame[frame["ts_code"].astype(str).str.endswith((".SH", ".SZ"))].copy()


def apply_conditional_ranking(frame: pd.DataFrame) -> pd.Series:
    """尾部风险环境使用单位波动超额，否则保留原始下界。"""

    score = frame["prediction_lower_bound"].copy()
    risk_mask = frame["market_tail_risk_probability"] > RISK_REGIME_THRESHOLD
    score.loc[risk_mask] = risk_adjusted_score(
        frame.loc[risk_mask, "prediction_lower_bound"],
        frame.loc[risk_mask, "volatility_20"],
    )
    return score


def predict_stock_walkforward(market: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """逐年训练冻结个股模型，并按T日市场风险切换日内排序。"""

    market_map = market[["trade_date", "market_tail_risk_probability"]].copy()
    market_map["trade_date"] = market_map["trade_date"].astype(str)
    member_samples: dict[int, list[pd.DataFrame]] = {seed: [] for seed in SEEDS}
    for year in range(2016, min(PREDICT_YEARS)):
        featured = eligible_shsz(load_featured_year(year))
        for seed in SEEDS:
            member_samples[seed].append(sample_member_year(featured, year, seed))

    trades = []
    metadata = {}
    for predict_year in PREDICT_YEARS:
        target = load_featured_year(predict_year).dropna(subset=FEATURES).copy()
        target["trade_date"] = target["trade_date"].astype(str)
        target = eligible_shsz(target)
        target = target.merge(market_map, on="trade_date", how="left", validate="many_to_one")
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
        target["prediction"] = apply_conditional_ranking(target)
        target["risk_adjusted_regime"] = (
            target["market_tail_risk_probability"] > RISK_REGIME_THRESHOLD
        )
        target["prediction_rank"] = target.groupby("trade_date")["prediction"].rank(pct=True)
        target["train_end_year"] = predict_year - 1
        trades.append(execute_daily_top3(target))
        metadata[str(predict_year)] = {
            "train_years": list(range(2016, predict_year)),
            "member_training_rows": member_rows,
            "prediction_rows": int(len(target)),
            "risk_adjusted_prediction_rows": int(target["risk_adjusted_regime"].sum()),
        }
        training_target = eligible_shsz(load_featured_year(predict_year))
        for seed in SEEDS:
            member_samples[seed].append(sample_member_year(training_target, predict_year, seed))
        del target, training_target
    return pd.concat(trades, ignore_index=True), metadata


def run() -> dict:
    """运行条件化风险排序六年研究确认。"""

    market, market_meta = predict_market_tail_risk_walkforward()
    trades, stock_meta = predict_stock_walkforward(market)
    trades["trade_date"] = trades["trade_date"].astype(str)
    cohort = summarize(trades)
    base_curve = simulate_portfolio(trades, slots=15, cost_pct=0.25, holding_days=5)
    stress_curve = simulate_portfolio(trades, slots=15, cost_pct=0.50, holding_days=5)
    base_account = account_metrics(base_curve)
    stress_account = account_metrics(stress_curve)
    decision = evaluate(cohort, base_account, stress_account)
    result = {
        "research_id": RESEARCH_ID,
        "status": "six_year_confirmation_pass" if decision["passed"] else "six_year_confirmation_failed",
        "stock_model_meta": stock_meta,
        "market_model_meta": market_meta,
        "gate_diagnostics": {
            "kept_trades": int(len(trades)),
            "kept_dates": int(trades["trade_date"].nunique()),
            "north_exchange_trades_kept": int(
                trades["ts_code"].astype(str).str.endswith(".BJ").sum()
            ),
            "risk_adjusted_trades": int(trades["risk_adjusted_regime"].sum()),
        },
        "cohort_summary": cohort,
        "base_cost_account": base_account,
        "double_cost_account": stress_account,
        "decision": decision,
        "new_holdout_opened": False,
        "note": "不删除交易日；仅在T日尾部风险概率超过一半时切换沪深候选的日内排序。",
    }
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
