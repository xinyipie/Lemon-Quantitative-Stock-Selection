"""质量动量两阶段模型高置信领先 Top1 的六年研究确认。"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from research.contrarian_candidate_stress import annual_path_metrics, max_drawdown
from research.high_confidence_abstention_audit import overlap_adjusted_portfolio
from research.two_stage_walkforward_research import _bootstrap_probability, _metrics, _period

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "cache"
REPORT_DIR = ROOT / "reports" / "research"
SOURCE = REPORT_DIR / "quality_momentum_reentry_sealed_2025_20260808_trades.csv"
RESEARCH_ID = "quality_momentum_reentry_margin_v3_2019_2024_20260808"
RESEARCH_YEARS = (2019, 2020, 2021, 2022, 2023, 2024)
MINIMUM_PREDICTION_MARGIN = 0.02


def select_high_confidence_top1(trades: pd.DataFrame) -> pd.DataFrame:
    """仅保留第一名相对第二名预测领先超过两个百分点的信号。"""

    work = trades.copy()
    work["trade_date"] = work["trade_date"].astype(str)
    work = work[work["trade_date"].str[:4].astype(int).isin(RESEARCH_YEARS)].copy()
    ordered = work.sort_values(
        ["trade_date", "rank_prediction", "ts_code"],
        ascending=[True, False, True],
        kind="mergesort",
    ).copy()
    ordered["selected_rank"] = ordered.groupby("trade_date").cumcount() + 1
    predictions = ordered.pivot(
        index="trade_date", columns="selected_rank", values="rank_prediction"
    )
    predictions["prediction_margin"] = predictions[1] - predictions[2]
    top1 = ordered[ordered["selected_rank"] == 1].merge(
        predictions[["prediction_margin"]],
        left_on="trade_date",
        right_index=True,
        how="left",
        validate="one_to_one",
    )
    return top1[top1["prediction_margin"] > MINIMUM_PREDICTION_MARGIN].copy()


def run() -> dict:
    """运行高置信领先 Top1 六年确认。"""

    source = pd.read_csv(SOURCE, dtype={"trade_date": str})
    base_trades = select_high_confidence_top1(source)
    stress_trades = base_trades.copy()
    stress_trades["net_ret"] = stress_trades["net_ret"] - 0.25
    overall = _metrics(base_trades)
    validation = _metrics(_period(base_trades, 2022, 2024))
    yearly = (
        base_trades.groupby(base_trades["trade_date"].str[:4].astype(int))
        .apply(lambda group: pd.Series(_metrics(group)), include_groups=False)
        .reset_index(names="year")
    )
    validation_days = _period(
        base_trades.groupby("trade_date", as_index=False)["net_ret"].mean(), 2022, 2024
    )
    ci_low, ci_high, p_nonpositive = _bootstrap_probability(
        validation_days, block=20, repetitions=10000
    )
    base_overlap = overlap_adjusted_portfolio(base_trades, CACHE, cost=0.25)
    stress_overlap = overlap_adjusted_portfolio(stress_trades, CACHE, cost=0.50)
    base_yearly = annual_path_metrics(base_overlap)
    stress_yearly = annual_path_metrics(stress_overlap)
    base_drawdown = max_drawdown(base_overlap["net_ret"]) if not base_overlap.empty else float("nan")
    stress_drawdown = (
        max_drawdown(stress_overlap["net_ret"]) if not stress_overlap.empty else float("nan")
    )
    base_research_years = base_yearly[base_yearly["year"].isin(RESEARCH_YEARS)]
    stress_research_years = stress_yearly[stress_yearly["year"].isin(RESEARCH_YEARS)]
    checks = {
        "minimum_total_trades": overall["trades"] >= 200,
        "minimum_validation_trades": validation["trades"] >= 100,
        "positive_mean": overall["avg_net"] > 0,
        "profit_factor": overall["profit_factor"] > 1.10,
        "every_year_positive": overall["positive_years"] == overall["years"] == 6,
        "validation_bootstrap_lower_bound_positive": ci_low > 0,
        "validation_nonpositive_probability": p_nonpositive < 0.05,
        "base_overlap_every_year_positive": (
            len(base_research_years) == 6 and (base_research_years["return_pct"] > 0).all()
        ),
        "base_overlap_drawdown": base_drawdown > -20.0,
        "stress_overlap_every_year_positive": (
            len(stress_research_years) == 6
            and (stress_research_years["return_pct"] > 0).all()
        ),
        "stress_overlap_drawdown": stress_drawdown > -25.0,
    }
    result = {
        "research_id": RESEARCH_ID,
        "status": "six_year_confirmation_pass" if all(checks.values()) else "six_year_confirmation_failed",
        "overall_metrics": overall,
        "validation_metrics": validation,
        "yearly_metrics": yearly.to_dict(orient="records"),
        "bootstrap": {
            "ci_low": ci_low,
            "ci_high": ci_high,
            "p_nonpositive": p_nonpositive,
        },
        "base_overlap_yearly": base_yearly.to_dict(orient="records"),
        "stress_overlap_yearly": stress_yearly.to_dict(orient="records"),
        "base_overlap_max_drawdown_pct": base_drawdown,
        "stress_overlap_max_drawdown_pct": stress_drawdown,
        "checks": {key: bool(value) for key, value in checks.items()},
        "sealed_holdout_opened": False,
    }
    (REPORT_DIR / f"{RESEARCH_ID}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    base_trades.to_csv(
        REPORT_DIR / f"{RESEARCH_ID}_trades.csv", index=False, encoding="utf-8-sig"
    )
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
