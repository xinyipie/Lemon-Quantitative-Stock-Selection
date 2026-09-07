"""沪深五日横截面前十分位分类器的六年研究确认。"""

from __future__ import annotations

import json

import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.utils.class_weight import compute_sample_weight

from research.research_integrity import purge_overlapping_label_tail

from research.clean_bagged_lcb_existing_regime_gate import evaluate, summarize
from research.clean_shsz_bagged_cross_section_rank_2019_2024 import (
    RANK_TARGET,
    load_ranked_year,
)
from research.clean_walkforward_excess_bagged3 import SEEDS
from research.clean_walkforward_excess_bagged_lcb import conservative_score
from research.clean_walkforward_technical_hgb_excess_target import (
    FEATURES,
    REPORT_DIR,
    TARGET,
    account_metrics,
    execute_daily_top3,
    simulate_portfolio,
)

PREDICT_YEARS = (2019, 2020, 2021, 2022, 2023, 2024)
TOP_DECILE_TARGET = "future_5d_top_decile"
TOP_DECILE_BOUNDARY = 0.90
RESEARCH_ID = "clean_shsz_bagged_top_decile_classifier_2019_2024_20260808"


def add_top_decile_target(frame: pd.DataFrame) -> pd.DataFrame:
    """把同日未来五日收益前十分位标记为正类。"""

    work = frame.copy()
    rank = pd.to_numeric(work[RANK_TARGET], errors="coerce")
    work[TOP_DECILE_TARGET] = pd.Series(pd.NA, index=work.index, dtype="Int64")
    valid = rank.notna()
    work.loc[valid, TOP_DECILE_TARGET] = rank.loc[valid].ge(TOP_DECILE_BOUNDARY).astype(int)
    return work


def new_top_decile_classifier(seed: int) -> HistGradientBoostingClassifier:
    """构建冻结参数的低复杂度领先股分类器。"""

    return HistGradientBoostingClassifier(
        learning_rate=0.05,
        max_iter=120,
        max_leaf_nodes=15,
        min_samples_leaf=50,
        l2_regularization=1.0,
        random_state=seed,
    )


def sample_member_year_classifier(frame: pd.DataFrame, year: int, seed: int) -> pd.DataFrame:
    """按冻结年度上限和种子抽取分类训练样本。"""

    part = frame.dropna(subset=FEATURES + [TOP_DECILE_TARGET]).copy()
    if len(part) > 150_000:
        part = part.sample(n=150_000, random_state=seed + year)
    sampled = part[
        FEATURES + [TOP_DECILE_TARGET, "trade_date", "label_exit_date_5d"]
    ].reset_index(drop=True)
    purged = purge_overlapping_label_tail(
        sampled,
        horizon=5,
        prediction_start_date=f"{year + 1}0101",
    )
    return purged[FEATURES + [TOP_DECILE_TARGET]].reset_index(drop=True)


def load_classified_year(year: int) -> pd.DataFrame:
    """读取沪深排名标签并追加前十分位分类目标。"""

    return add_top_decile_target(load_ranked_year(year))


def predict_stock_walkforward() -> tuple[pd.DataFrame, dict]:
    """逐年扩展训练三成员领先股分类器。"""

    member_samples: dict[int, list[pd.DataFrame]] = {seed: [] for seed in SEEDS}
    for year in range(2016, min(PREDICT_YEARS)):
        featured = load_classified_year(year)
        for seed in SEEDS:
            member_samples[seed].append(sample_member_year_classifier(featured, year, seed))

    trades = []
    metadata = {}
    for predict_year in PREDICT_YEARS:
        target = load_classified_year(predict_year).dropna(subset=FEATURES).copy()
        member_predictions = []
        member_rows = []
        for seed in SEEDS:
            train = pd.concat(member_samples[seed], ignore_index=True)
            labels = train[TOP_DECILE_TARGET].astype(int)
            weights = compute_sample_weight(class_weight="balanced", y=labels)
            model = new_top_decile_classifier(seed)
            model.fit(train[FEATURES], labels, sample_weight=weights)
            member_predictions.append(model.predict_proba(target[FEATURES])[:, 1])
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
            member_samples[seed].append(
                sample_member_year_classifier(target, predict_year, seed)
            )
        del target
    return pd.concat(trades, ignore_index=True), metadata


def run() -> dict:
    """运行前十分位分类器六年研究确认。"""

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
        "note": "模型只学习同日沪深未来五日收益前十分位事件，不使用市场 gate。",
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
