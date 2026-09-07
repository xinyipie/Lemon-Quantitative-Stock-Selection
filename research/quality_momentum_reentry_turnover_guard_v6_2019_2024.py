"""质量动量浅回调策略：在线门控后的横截面换手护栏。"""

from __future__ import annotations

import json

import pandas as pd

from research.contrarian_candidate_stress import annual_path_metrics, max_drawdown
from research.high_confidence_abstention_audit import overlap_adjusted_portfolio
from research.quality_momentum_reentry_online_gate_v5_2019_2024 import (
    BASE_QUANTILE,
    CACHE,
    REPORT_DIR,
    SOURCE,
    build_oos_gate_predictions,
    select_online_gated,
)
from research.two_stage_walkforward_research import (
    _bootstrap_probability,
    _metrics,
    _period,
    _prepare,
)

RESEARCH_ID = "quality_momentum_reentry_turnover_guard_v6_2019_2024_20260808"
BASE_MAX_TURNOVER_RANK = 0.50
NEIGHBOR_MAX_TURNOVER_RANKS = (0.40, 0.60)


def apply_turnover_guard(trades: pd.DataFrame, maximum_rank: float) -> pd.DataFrame:
    """只保留候选池横截面换手率排名不高于冻结上限的股票。"""

    rank = pd.to_numeric(trades["rank_turnover_rate"], errors="coerce")
    return trades[rank.le(maximum_rank)].copy()


def _select(predicted: pd.DataFrame, cost: float, maximum_rank: float) -> pd.DataFrame:
    parent = select_online_gated(predicted, BASE_QUANTILE, cost=cost)
    return _period(apply_turnover_guard(parent, maximum_rank), 2019, 2024)


def _yearly_metrics(trades: pd.DataFrame) -> pd.DataFrame:
    return (
        trades.groupby(trades["trade_date"].str[:4].astype(int))
        .apply(lambda group: pd.Series(_metrics(group)), include_groups=False)
        .reset_index(names="year")
    )


def _neighbor(predicted: pd.DataFrame, maximum_rank: float) -> dict:
    trades = _select(predicted, cost=0.25, maximum_rank=maximum_rank)
    yearly = _yearly_metrics(trades)
    validation = _metrics(_period(trades, 2022, 2024))
    return {
        "maximum_rank": maximum_rank,
        "metrics": _metrics(trades),
        "validation": validation,
        "yearly": yearly.to_dict(orient="records"),
        "six_years_positive": bool(len(yearly) == 6 and (yearly["avg_net"] > 0).all()),
        "validation_every_year_positive": bool(
            validation["years"] == validation["positive_years"] == 3
        ),
    }


def run() -> dict:
    """执行换手护栏主规则、成本压力和相邻阈值审计。"""

    frame, market = _prepare(SOURCE)
    predicted = build_oos_gate_predictions(frame, market)
    base = _select(predicted, cost=0.25, maximum_rank=BASE_MAX_TURNOVER_RANK)
    stress = _select(predicted, cost=0.50, maximum_rank=BASE_MAX_TURNOVER_RANK)
    internal = _metrics(_period(base, 2019, 2021))
    validation = _metrics(_period(base, 2022, 2024))
    yearly = _yearly_metrics(base)
    validation_days = _period(
        base.groupby("trade_date", as_index=False)["net_ret"].mean(), 2022, 2024
    )
    ci_low, ci_high, p_nonpositive = _bootstrap_probability(
        validation_days, block=20, repetitions=10000
    )
    base_overlap = overlap_adjusted_portfolio(base, CACHE, cost=0.25)
    stress_overlap = overlap_adjusted_portfolio(stress, CACHE, cost=0.50)
    base_yearly_all = annual_path_metrics(base_overlap)
    stress_yearly_all = annual_path_metrics(stress_overlap)
    base_yearly = base_yearly_all[base_yearly_all["year"].between(2019, 2024)].copy()
    stress_yearly = stress_yearly_all[stress_yearly_all["year"].between(2019, 2024)].copy()
    base_drawdown = max_drawdown(base_overlap["net_ret"]) if not base_overlap.empty else float("nan")
    stress_drawdown = max_drawdown(stress_overlap["net_ret"]) if not stress_overlap.empty else float("nan")
    neighbors = [_neighbor(predicted, value) for value in NEIGHBOR_MAX_TURNOVER_RANKS]
    checks = {
        "internal_minimum_trades": internal["trades"] >= 60,
        "internal_profit_factor": internal["profit_factor"] > 1.10,
        "internal_every_year_positive": internal["positive_years"] == internal["years"] == 3,
        "validation_minimum_trades": validation["trades"] >= 60,
        "validation_average_net_return": validation["avg_net"] > 0.25,
        "validation_profit_factor": validation["profit_factor"] > 1.15,
        "validation_every_year_positive": validation["positive_years"] == validation["years"] == 3,
        "six_years_positive": len(yearly) == 6 and (yearly["avg_net"] > 0).all(),
        "bootstrap_lower_bound_positive": ci_low > 0,
        "bootstrap_nonpositive_probability": p_nonpositive < 0.05,
        "base_overlap_every_year_positive": len(base_yearly) == 6 and (base_yearly["return_pct"] > 0).all(),
        "stress_overlap_every_year_positive": len(stress_yearly) == 6 and (stress_yearly["return_pct"] > 0).all(),
        "base_overlap_drawdown": base_drawdown > -20.0,
        "stress_overlap_drawdown": stress_drawdown > -25.0,
        "neighbor_stability": all(
            item["six_years_positive"] and item["validation_every_year_positive"]
            for item in neighbors
        ),
    }
    result = {
        "research_id": RESEARCH_ID,
        "status": "six_year_confirmation_pass" if all(checks.values()) else "six_year_confirmation_failed",
        "internal_metrics": internal,
        "validation_metrics": validation,
        "yearly_metrics": yearly.to_dict(orient="records"),
        "bootstrap": {"ci_low": ci_low, "ci_high": ci_high, "p_nonpositive": p_nonpositive},
        "base_overlap_yearly": base_yearly.to_dict(orient="records"),
        "stress_overlap_yearly": stress_yearly.to_dict(orient="records"),
        "base_overlap_max_drawdown_pct": base_drawdown,
        "stress_overlap_max_drawdown_pct": stress_drawdown,
        "neighbor_audit": neighbors,
        "checks": {key: bool(value) for key, value in checks.items()},
        "production_changed": False,
    }
    (REPORT_DIR / f"{RESEARCH_ID}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    base.to_csv(REPORT_DIR / f"{RESEARCH_ID}_trades.csv", index=False, encoding="utf-8-sig")
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
