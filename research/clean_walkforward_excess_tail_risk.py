"""截面超额收益模型叠加独立个股大跌风险分类器。"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score

from research.clean_broad_cross_sectional_rank import simulate_portfolio
from research.clean_walkforward_technical_hgb import (
    ALL_YEARS,
    FEATURES,
    PREDICT_YEARS,
    RANDOM_STATE,
    RAW_COLUMNS,
    REPORT_DIR,
    STORE,
    TARGET,
    build_features,
    new_model,
    tradable_universe,
    walkforward_splits,
)
from research.clean_walkforward_technical_hgb_daily_top3 import summarize_cohorts
from research.clean_walkforward_technical_hgb_daily_top3_account import account_metrics
from research.clean_walkforward_technical_hgb_excess_target import EXCESS_TARGET, add_excess_target, sample_training_rows


TAIL_TARGET = "large_loss_5d"


def new_risk_model() -> HistGradientBoostingClassifier:
    """构造与收益模型容量相当的独立尾部分类器。"""

    return HistGradientBoostingClassifier(
        learning_rate=0.05,
        max_iter=100,
        max_leaf_nodes=15,
        min_samples_leaf=100,
        l2_regularization=1.0,
        random_state=RANDOM_STATE,
    )


def class_balanced_weights(labels: pd.Series) -> np.ndarray:
    """让大跌与非大跌两类在训练损失中总权重相同。"""

    positive_rate = float(labels.mean())
    if positive_rate <= 0 or positive_rate >= 1:
        return np.ones(len(labels), dtype=float)
    return np.where(labels.to_numpy() == 1, 0.5 / positive_rate, 0.5 / (1.0 - positive_rate))


def predict_walkforward_dual(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """逐年训练收益回归头和大跌风险分类头。"""

    predictions = []
    metadata = {}
    for train_years, predict_year in walkforward_splits():
        train = sample_training_rows(
            frame,
            train_years,
            prediction_start_date=f"{predict_year}0101",
        ).copy()
        target = frame[frame["year"] == predict_year].dropna(subset=FEATURES).copy()
        return_model = new_model()
        risk_model = new_risk_model()
        return_model.fit(train[FEATURES], train[EXCESS_TARGET].clip(-15.0, 15.0))
        labels = train[TAIL_TARGET].astype(int)
        risk_model.fit(train[FEATURES], labels, sample_weight=class_balanced_weights(labels))
        target["prediction"] = return_model.predict(target[FEATURES])
        target["large_loss_probability"] = risk_model.predict_proba(target[FEATURES])[:, 1]
        target["risk_rank"] = target.groupby("trade_date")["large_loss_probability"].rank(pct=True)
        target["train_end_year"] = max(train_years)
        valid_auc = target[target[TAIL_TARGET].notna()]
        auc = roc_auc_score(valid_auc[TAIL_TARGET], valid_auc["large_loss_probability"])
        predictions.append(target)
        metadata[str(predict_year)] = {
            "train_years": list(train_years),
            "training_rows": int(len(train)),
            "prediction_rows": int(len(target)),
            "large_loss_rate": float(valid_auc[TAIL_TARGET].mean()),
            "risk_roc_auc": float(auc),
        }
    return pd.concat(predictions, ignore_index=True), metadata


def execute_low_risk_top3(predictions: pd.DataFrame) -> pd.DataFrame:
    """先保留日内较低风险一半，再按超额预测锁定Top3。"""

    candidates = predictions[predictions["risk_rank"] <= 0.50].copy()
    locked = (
        candidates.sort_values(
            ["trade_date", "prediction", "ts_code"],
            ascending=[True, False, True],
            kind="mergesort",
        )
        .groupby("trade_date", group_keys=False)
        .head(3)
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


def evaluate(model_meta: dict, cohort: dict, base: dict, stress: dict) -> dict:
    """执行风险模型、批次与账户三重门槛。"""

    years = PREDICT_YEARS
    yearly_values = [base["yearly_returns_pct"].get(str(year), -999.0) for year in years]
    checks = {
        "minimum_risk_roc_auc_each_year": all(model_meta[str(year)]["risk_roc_auc"] >= 0.55 for year in years),
        "minimum_daily_cohorts": cohort["cohorts"] >= 600,
        "minimum_cohorts_each_year": all(cohort["yearly"][str(year)]["cohorts"] >= 200 for year in years),
        "minimum_average_net_return_pct": (cohort["average_cohort_net_return_pct"] or -999) >= 0.50,
        "minimum_profit_factor": (cohort["cohort_profit_factor"] or 0) >= 1.30,
        "required_positive_cohort_years": all(
            (cohort["yearly"][str(year)]["average_net_return_pct"] or -999) > 0 for year in years
        ),
        "minimum_edge_vs_same_day_universe_pct": (cohort["edge_vs_same_day_universe_pct"] or -999) >= 0.30,
        "minimum_trimmed_mean_pct": (cohort["trimmed_mean_pct"] or -999) > 0,
        "minimum_double_cost_stress_mean_pct": (cohort["double_cost_stress_mean_pct"] or -999) > 0,
        "minimum_annualized_return_pct": (base["annualized_return_pct"] or -999) >= 12.0,
        "maximum_drawdown_pct": (base["max_drawdown_pct"] or -999) >= -20.0,
        "minimum_sharpe": (base["sharpe"] or -999) >= 0.80,
        "required_positive_account_years": all(value > 0 for value in yearly_values),
        "minimum_worst_year_return_pct": min(yearly_values) >= 3.0,
        "minimum_double_cost_annualized_return_pct": (stress["annualized_return_pct"] or -999) >= 8.0,
        "maximum_double_cost_drawdown_pct": (stress["max_drawdown_pct"] or -999) >= -25.0,
    }
    return {"passed": all(checks.values()), "checks": checks}


def run() -> dict:
    """运行双头模型的内部批次与账户确认。"""

    frames = [pd.read_parquet(STORE / f"{year}.parquet", columns=RAW_COLUMNS) for year in ALL_YEARS]
    featured = add_excess_target(tradable_universe(build_features(pd.concat(frames, ignore_index=True))))
    featured[TAIL_TARGET] = np.where(featured[TARGET].notna(), (featured[TARGET] <= -7.0).astype(float), np.nan)
    predictions, model_meta = predict_walkforward_dual(featured)
    trades = execute_low_risk_top3(predictions)
    cohort = summarize_cohorts(trades, predictions)
    base_curve = simulate_portfolio(trades, slots=15, cost_pct=0.25, holding_days=5)
    stress_curve = simulate_portfolio(trades, slots=15, cost_pct=0.50, holding_days=5)
    base = account_metrics(base_curve)
    stress = account_metrics(stress_curve)
    decision = evaluate(model_meta, cohort, base, stress)
    result = {
        "research_id": "clean_walkforward_excess_tail_risk_20260808",
        "status": "internal_confirmation_pass" if decision["passed"] else "internal_confirmation_failed",
        "model_meta": model_meta,
        "cohort_summary": cohort,
        "base_cost_account": base,
        "double_cost_account": stress,
        "decision": decision,
        "external_years_opened": False,
        "note": "风险分类仅过滤，不参与收益排序；失败时不打开2022-2024。",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "clean_walkforward_excess_tail_risk_20260808.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    trades.to_csv(
        REPORT_DIR / "clean_walkforward_excess_tail_risk_trades_20260808.csv",
        index=False,
        encoding="utf-8-sig",
    )
    base_curve.to_csv(
        REPORT_DIR / "clean_walkforward_excess_tail_risk_account_curve_20260808.csv",
        index=False,
        encoding="utf-8-sig",
    )
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
