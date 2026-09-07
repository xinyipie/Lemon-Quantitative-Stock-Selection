"""袋装保守下界模型的2022-2024独立验证。"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from research.research_integrity import purge_overlapping_label_tail

from research.clean_walkforward_excess_bagged3 import SEEDS
from research.clean_walkforward_excess_bagged_lcb import conservative_score
from research.clean_walkforward_technical_hgb_excess_target import (
    EXCESS_TARGET,
    FEATURES,
    RAW_COLUMNS,
    REPORT_DIR,
    STORE,
    TARGET,
    account_metrics,
    add_excess_target,
    build_features,
    execute_daily_top3,
    new_model,
    simulate_portfolio,
    tradable_universe,
)

TRAIN_START_YEAR = 2016
VALIDATION_YEARS = (2022, 2023, 2024)
RESEARCH_ID = "validation_clean_walkforward_excess_bagged_lcb_20260808"


def load_featured_year(year: int) -> pd.DataFrame:
    """按年读取修复尺度后的研究库并构造T日特征。"""

    raw = pd.read_parquet(STORE / f"{year}.parquet", columns=RAW_COLUMNS)
    return add_excess_target(tradable_universe(build_features(raw)))


def sample_member_year(frame: pd.DataFrame, year: int, seed: int) -> pd.DataFrame:
    """按内部确认完全相同的年度上限和种子抽样。"""

    part = frame.dropna(subset=FEATURES + [EXCESS_TARGET]).copy()
    if len(part) > 150_000:
        part = part.sample(n=150_000, random_state=seed + year)
    sampled = part[
        FEATURES + [EXCESS_TARGET, "trade_date", "label_exit_date_5d"]
    ].reset_index(drop=True)
    purged = purge_overlapping_label_tail(
        sampled,
        horizon=5,
        prediction_start_date=f"{year + 1}0101",
    )
    return purged[FEATURES + [EXCESS_TARGET]].reset_index(drop=True)


def predict_validation() -> tuple[pd.DataFrame, pd.Series, dict]:
    """扩展训练到每个验证年前一年，验证数据不参与当年训练。"""

    member_samples: dict[int, list[pd.DataFrame]] = {seed: [] for seed in SEEDS}
    for year in range(TRAIN_START_YEAR, min(VALIDATION_YEARS)):
        featured = load_featured_year(year)
        for seed in SEEDS:
            member_samples[seed].append(sample_member_year(featured, year, seed))

    trade_parts = []
    benchmark_parts = []
    metadata = {}
    for predict_year in VALIDATION_YEARS:
        target = load_featured_year(predict_year).dropna(subset=FEATURES).copy()
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
        target["prediction"] = lower_bound
        target["prediction_rank"] = target.groupby("trade_date")["prediction"].rank(pct=True)
        target["train_end_year"] = predict_year - 1
        trade_parts.append(execute_daily_top3(target))
        benchmark_parts.append(target.groupby("trade_date")[TARGET].mean().sub(0.25))
        metadata[str(predict_year)] = {
            "train_years": list(range(TRAIN_START_YEAR, predict_year)),
            "member_training_rows": member_rows,
            "prediction_rows": int(len(target)),
            "seeds": list(SEEDS),
        }
        for seed in SEEDS:
            member_samples[seed].append(sample_member_year(target, predict_year, seed))
        del target

    return pd.concat(trade_parts, ignore_index=True), pd.concat(benchmark_parts), metadata


def summarize_cohorts(trades: pd.DataFrame, benchmark: pd.Series) -> dict:
    """按验证期每日Top3批次统计固定五日净收益。"""

    cohorts = trades.groupby("trade_date", as_index=False).agg(
        net_return=("net_return", "mean"), members=("ts_code", "size")
    )
    cohorts["year"] = cohorts["trade_date"].str[:4].astype(int)
    values = cohorts["net_return"]
    gains = float(values[values > 0].sum())
    losses = float(-values[values < 0].sum())
    ordered = values.sort_values().reset_index(drop=True)
    trim = int(len(ordered) * 0.05)
    trimmed = ordered.iloc[trim:-trim] if trim and len(ordered) > trim * 2 else ordered
    same_day_benchmark = cohorts["trade_date"].map(benchmark)
    yearly = {}
    for year in VALIDATION_YEARS:
        part = cohorts.loc[cohorts["year"] == year, "net_return"]
        year_gains = float(part[part > 0].sum())
        year_losses = float(-part[part < 0].sum())
        yearly[str(year)] = {
            "cohorts": int(len(part)),
            "average_net_return_pct": float(part.mean()) if len(part) else None,
            "profit_factor": year_gains / year_losses if year_losses > 0 else None,
        }
    stock_share = trades["ts_code"].value_counts(normalize=True)
    industry_share = trades["industry"].fillna("未知").value_counts(normalize=True)
    return {
        "cohorts": int(len(cohorts)),
        "stock_trades": int(len(trades)),
        "average_members": float(cohorts["members"].mean()),
        "average_cohort_net_return_pct": float(values.mean()),
        "cohort_profit_factor": gains / losses if losses > 0 else None,
        "win_rate": float((values > 0).mean()),
        "trimmed_mean_pct": float(trimmed.mean()),
        "double_cost_stress_mean_pct": float(values.mean() - 0.25),
        "same_day_universe_benchmark_pct": float(same_day_benchmark.mean()),
        "edge_vs_same_day_universe_pct": float(values.mean() - same_day_benchmark.mean()),
        "maximum_single_stock_share": float(stock_share.iloc[0]),
        "maximum_single_industry_share": float(industry_share.iloc[0]),
        "yearly": yearly,
    }


def evaluate(cohort: dict, base_account: dict, stress_account: dict) -> dict:
    """执行与内部确认相同的独立验证门槛。"""

    yearly_values = [base_account["yearly_returns_pct"].get(str(year), -999.0) for year in VALIDATION_YEARS]
    checks = {
        "minimum_daily_cohorts": cohort["cohorts"] >= 600,
        "minimum_cohorts_each_year": all(
            cohort["yearly"][str(year)]["cohorts"] >= 200 for year in VALIDATION_YEARS
        ),
        "minimum_average_net_return_pct": cohort["average_cohort_net_return_pct"] >= 0.50,
        "minimum_profit_factor": (cohort["cohort_profit_factor"] or 0) >= 1.25,
        "required_positive_years": all(
            (cohort["yearly"][str(year)]["average_net_return_pct"] or -999) > 0
            for year in VALIDATION_YEARS
        ),
        "minimum_edge_vs_same_day_universe_pct": cohort["edge_vs_same_day_universe_pct"] >= 0.30,
        "minimum_trimmed_mean_pct": cohort["trimmed_mean_pct"] > 0,
        "minimum_double_cost_stress_mean_pct": cohort["double_cost_stress_mean_pct"] > 0,
        "minimum_annualized_return_pct": (base_account["annualized_return_pct"] or -999) >= 12.0,
        "maximum_drawdown_pct": (base_account["max_drawdown_pct"] or -999) >= -20.0,
        "minimum_sharpe": (base_account["sharpe"] or -999) >= 0.80,
        "required_positive_account_years": all(value > 0 for value in yearly_values),
        "minimum_worst_year_return_pct": min(yearly_values) >= 3.0,
        "minimum_double_cost_annualized_return_pct": (
            stress_account["annualized_return_pct"] or -999
        ) >= 8.0,
        "maximum_double_cost_drawdown_pct": (
            stress_account["max_drawdown_pct"] or -999
        ) >= -25.0,
    }
    return {"passed": all(checks.values()), "checks": checks}


def run() -> dict:
    """运行首次解封的2022-2024独立验证。"""

    trades, benchmark, model_meta = predict_validation()
    cohort = summarize_cohorts(trades, benchmark)
    base_curve = simulate_portfolio(trades, slots=15, cost_pct=0.25, holding_days=5)
    stress_curve = simulate_portfolio(trades, slots=15, cost_pct=0.50, holding_days=5)
    base_account = account_metrics(base_curve)
    stress_account = account_metrics(stress_curve)
    decision = evaluate(cohort, base_account, stress_account)
    result = {
        "research_id": RESEARCH_ID,
        "status": "validation_pass" if decision["passed"] else "validation_failed",
        "model_meta": model_meta,
        "cohort_summary": cohort,
        "base_cost_account": base_account,
        "double_cost_account": stress_account,
        "decision": decision,
        "external_years_opened": True,
        "recent_years_opened": False,
        "note": "验证失败时不使用2022-2024调参；通过后才执行扰动与近期观察。",
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
