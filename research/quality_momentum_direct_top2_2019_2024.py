"""预注册质量动量候选直接 Top2 的六年研究确认。"""

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
SOURCE = REPORT_DIR / "quality_momentum_reentry_sealed_2025_20260808_candidates.csv"
RESEARCH_ID = "quality_momentum_direct_top2_2019_2024_20260808"
RESEARCH_YEARS = (2019, 2020, 2021, 2022, 2023, 2024)


def select_daily_top2(candidates: pd.DataFrame, cost: float) -> pd.DataFrame:
    """按冻结质量动量分直接锁定每日 Top2。"""

    work = candidates.copy()
    work["trade_date"] = work["trade_date"].astype(str)
    work = work[work["trade_date"].str[:4].astype(int).isin(RESEARCH_YEARS)].copy()
    selected = (
        work.sort_values(
            ["trade_date", "quality_momentum_score", "ts_code"],
            ascending=[True, False, True],
            kind="mergesort",
        )
        .groupby("trade_date", group_keys=False)
        .head(2)
        .copy()
    )
    selected["net_ret"] = pd.to_numeric(selected["ret_5d"], errors="coerce") - cost
    selected["test_year"] = selected["trade_date"].str[:4].astype(int)
    selected["rank_prediction"] = selected["quality_momentum_score"]
    selected["gate_prediction"] = 1.0
    return selected.dropna(subset=["net_ret"])


def run() -> dict:
    """运行确定性质量动量 Top2 六年确认。"""

    candidates = pd.read_csv(SOURCE, dtype={"trade_date": str})
    base_trades = select_daily_top2(candidates, cost=0.25)
    stress_trades = select_daily_top2(candidates, cost=0.50)
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
        "minimum_trades": overall["trades"] >= 500,
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
        "maximum_source_year": int(base_trades["test_year"].max()),
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
