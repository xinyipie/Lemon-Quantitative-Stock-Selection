"""沪深五日横截面排名袋装模型的六年研究确认。"""

from __future__ import annotations

import json

import pandas as pd

from research.research_integrity import purge_overlapping_label_tail

from research.clean_bagged_lcb_existing_regime_gate import evaluate, summarize
from research.clean_shsz_conditional_risk_rank_2019_2024 import eligible_shsz
from research.clean_walkforward_absolute_bagged_lcb_2019_2024 import load_featured_year
from research.clean_walkforward_excess_bagged3 import SEEDS
from research.clean_walkforward_excess_bagged_lcb import conservative_score
from research.clean_walkforward_technical_hgb_excess_target import (
    FEATURES,
    REPORT_DIR,
    TARGET,
    account_metrics,
    execute_daily_top3,
    new_model,
    simulate_portfolio,
)

PREDICT_YEARS = (2019, 2020, 2021, 2022, 2023, 2024)
RANK_TARGET = "ret_5d_cross_section_rank"
RESEARCH_ID = "clean_shsz_bagged_cross_section_rank_2019_2024_20260808"


def add_cross_section_rank_target(frame: pd.DataFrame) -> pd.DataFrame:
    """构造同一信号日沪深可交易样本的五日收益百分位标签。"""

    work = eligible_shsz(frame)
    work[RANK_TARGET] = work.groupby("trade_date")[TARGET].rank(
        method="average", pct=True
    )
    return work


def sample_member_year_rank(frame: pd.DataFrame, year: int, seed: int) -> pd.DataFrame:
    """按冻结年度上限和种子抽取排名标签训练样本。"""

    part = frame.dropna(subset=FEATURES + [RANK_TARGET]).copy()
    if len(part) > 150_000:
        part = part.sample(n=150_000, random_state=seed + year)
    sampled = part[
        FEATURES + [RANK_TARGET, "trade_date", "label_exit_date_5d"]
    ].reset_index(drop=True)
    purged = purge_overlapping_label_tail(
        sampled,
        horizon=5,
        prediction_start_date=f"{year + 1}0101",
    )
    return purged[FEATURES + [RANK_TARGET]].reset_index(drop=True)


def load_ranked_year(year: int) -> pd.DataFrame:
    """读取修正价格尺度后的特征并追加横截面排名标签。"""

    return add_cross_section_rank_target(load_featured_year(year))


def predict_stock_walkforward() -> tuple[pd.DataFrame, dict]:
    """逐年扩展训练三成员横截面排名模型。"""

    member_samples: dict[int, list[pd.DataFrame]] = {seed: [] for seed in SEEDS}
    for year in range(2016, min(PREDICT_YEARS)):
        featured = load_ranked_year(year)
        for seed in SEEDS:
            member_samples[seed].append(sample_member_year_rank(featured, year, seed))

    trades = []
    metadata = {}
    for predict_year in PREDICT_YEARS:
        target = load_ranked_year(predict_year).dropna(subset=FEATURES).copy()
        member_predictions = []
        member_rows = []
        for seed in SEEDS:
            train = pd.concat(member_samples[seed], ignore_index=True)
            model = new_model().set_params(random_state=seed)
            model.fit(train[FEATURES], train[RANK_TARGET])
            member_predictions.append(model.predict(target[FEATURES]))
            member_rows.append(int(len(train)))
            del train
        mean, std, lower_bound = conservative_score(member_predictions)
        target["prediction_mean"] = mean
        target["prediction_std"] = std
        target["prediction_lower_bound"] = lower_bound
        target["prediction"] = lower_bound
        target["prediction_rank"] = target.groupby("trade_date")["prediction"].rank(pct=True)
        target["train_end_year"] = predict_year - 1
        daily_mean = target.groupby("trade_date")[TARGET].transform("mean")
        target["ret_5d_excess"] = target[TARGET] - daily_mean
        trades.append(execute_daily_top3(target))
        metadata[str(predict_year)] = {
            "train_years": list(range(2016, predict_year)),
            "member_training_rows": member_rows,
            "prediction_rows": int(len(target)),
        }
        for seed in SEEDS:
            member_samples[seed].append(sample_member_year_rank(target, predict_year, seed))
        del target
    return pd.concat(trades, ignore_index=True), metadata


def run() -> dict:
    """运行横截面排名模型六年研究确认。"""

    trades, stock_meta = predict_stock_walkforward()
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
        "gate_diagnostics": {
            "kept_trades": int(len(trades)),
            "kept_dates": int(trades["trade_date"].nunique()),
            "north_exchange_trades_kept": int(
                trades["ts_code"].astype(str).str.endswith(".BJ").sum()
            ),
        },
        "cohort_summary": cohort,
        "base_cost_account": base_account,
        "double_cost_account": stress_account,
        "decision": decision,
        "new_holdout_opened": False,
        "note": "模型目标为同日沪深未来五日收益百分位，不使用市场 gate。",
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
