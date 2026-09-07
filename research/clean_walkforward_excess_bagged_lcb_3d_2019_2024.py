"""三日超额下界模型的六年走步研究确认。"""

from __future__ import annotations

import json

import pandas as pd

from research.research_integrity import purge_overlapping_label_tail

from research.clean_bagged_lcb_existing_regime_gate import evaluate, summarize
from research.clean_walkforward_absolute_bagged_lcb_2019_2024 import load_featured_year
from research.clean_walkforward_excess_bagged3 import SEEDS
from research.clean_walkforward_excess_bagged_lcb import conservative_score
from research.clean_walkforward_technical_hgb_daily_top3 import COST_PCT, lock_daily_top3
from research.clean_walkforward_technical_hgb_excess_target import (
    FEATURES,
    REPORT_DIR,
    account_metrics,
    new_model,
    simulate_portfolio,
)

PREDICT_YEARS = (2019, 2020, 2021, 2022, 2023, 2024)
TARGET_3D = "ret_3d"
EXCESS_TARGET_3D = "ret_3d_excess"
RESEARCH_ID = "clean_walkforward_excess_bagged_lcb_3d_2019_2024_20260808"


def add_3d_excess_target(frame: pd.DataFrame) -> pd.DataFrame:
    """构造同一信号日相对可交易样本均值的三日未来超额标签。"""

    work = frame.copy()
    daily_mean = work.groupby("trade_date")[TARGET_3D].transform("mean")
    work[EXCESS_TARGET_3D] = work[TARGET_3D] - daily_mean
    return work


def sample_member_year_3d(frame: pd.DataFrame, year: int, seed: int) -> pd.DataFrame:
    """按既有年度上限和固定种子抽取三日标签训练样本。"""

    part = frame.dropna(subset=FEATURES + [EXCESS_TARGET_3D]).copy()
    if len(part) > 150_000:
        part = part.sample(n=150_000, random_state=seed + year)
    sampled = part[
        FEATURES + [EXCESS_TARGET_3D, "trade_date", "label_exit_date_3d"]
    ].reset_index(drop=True)
    purged = purge_overlapping_label_tail(
        sampled,
        horizon=3,
        prediction_start_date=f"{year + 1}0101",
    )
    return purged[FEATURES + [EXCESS_TARGET_3D]].reset_index(drop=True)


def execute_daily_top3_3d(predictions: pd.DataFrame) -> pd.DataFrame:
    """锁定三日模型Top3后执行T+1可成交检查，不递补。"""

    locked = lock_daily_top3(predictions)
    executed = locked[
        locked["entry_open"].notna()
        & locked[TARGET_3D].notna()
        & (locked["entry_gap_pct"] < 7.0)
        & (locked["entry_gap_pct"] > -9.5)
    ].copy()
    executed["net_return"] = executed[TARGET_3D] - COST_PCT
    # 复用已冻结的六年统计口径，字段含义在本研究中均为三日。
    executed["ret_5d"] = executed[TARGET_3D]
    executed["ret_5d_excess"] = executed[EXCESS_TARGET_3D]
    return executed


def load_featured_year_3d(year: int) -> pd.DataFrame:
    """读取修正价格尺度后的特征并追加三日超额标签。"""

    return add_3d_excess_target(load_featured_year(year))


def predict_stock_walkforward() -> tuple[pd.DataFrame, dict]:
    """逐年扩展训练三成员三日超额模型。"""

    member_samples: dict[int, list[pd.DataFrame]] = {seed: [] for seed in SEEDS}
    for year in range(2016, min(PREDICT_YEARS)):
        featured = load_featured_year_3d(year)
        for seed in SEEDS:
            member_samples[seed].append(sample_member_year_3d(featured, year, seed))

    trades = []
    metadata = {}
    for predict_year in PREDICT_YEARS:
        target = load_featured_year_3d(predict_year).dropna(subset=FEATURES).copy()
        member_predictions = []
        member_rows = []
        for seed in SEEDS:
            train = pd.concat(member_samples[seed], ignore_index=True)
            model = new_model().set_params(random_state=seed)
            model.fit(train[FEATURES], train[EXCESS_TARGET_3D].clip(-15.0, 15.0))
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
        trades.append(execute_daily_top3_3d(target))
        metadata[str(predict_year)] = {
            "train_years": list(range(2016, predict_year)),
            "member_training_rows": member_rows,
            "prediction_rows": int(len(target)),
        }
        for seed in SEEDS:
            member_samples[seed].append(sample_member_year_3d(target, predict_year, seed))
        del target
    return pd.concat(trades, ignore_index=True), metadata


def run() -> dict:
    """运行三日超额模型六年研究确认。"""

    trades, stock_meta = predict_stock_walkforward()
    trades["trade_date"] = trades["trade_date"].astype(str)
    cohort = summarize(trades)
    base_curve = simulate_portfolio(trades, slots=9, cost_pct=0.25, holding_days=3)
    stress_curve = simulate_portfolio(trades, slots=9, cost_pct=0.50, holding_days=3)
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
        },
        "cohort_summary": cohort,
        "base_cost_account": base_account,
        "double_cost_account": stress_account,
        "decision": decision,
        "new_holdout_opened": False,
        "note": "三日标签、三日持有和九个固定等权槽位；未使用市场硬门控。",
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
