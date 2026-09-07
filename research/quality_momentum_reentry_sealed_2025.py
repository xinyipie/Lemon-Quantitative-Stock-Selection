"""质量动量浅回调策略的 2025 封存版研究执行器。"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from research.all_market_multi_engine_research import (
    _available_dates,
    _build_regimes,
    _load_stock_info,
    build_year_panel,
)
from research.contrarian_candidate_stress import annual_path_metrics, max_drawdown
from research.high_confidence_abstention_audit import overlap_adjusted_portfolio
from research.quality_momentum_reentry import FROZEN_CONFIG, build_candidates
from research.two_stage_walkforward_research import (
    _bootstrap_probability,
    _metrics,
    _period,
    _prepare,
    walk_forward,
)

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "cache"
REPORT_DIR = ROOT / "reports" / "research"
RESEARCH_ID = "quality_momentum_reentry_sealed_2025_20260808"
INTERNAL_PANEL_YEARS = tuple(range(2016, 2022))
RESEARCH_VALIDATION_YEARS = (2022, 2023, 2024)
SEALED_HOLDOUT_YEAR = 2025


def internal_gate(metrics: dict) -> bool:
    """执行原预注册的 2019-2021 内部 OOS 门槛。"""

    return bool(
        metrics["trades"] >= 100
        and metrics["avg_net"] > 0
        and metrics["profit_factor"] > 1.10
        and metrics["positive_years"] == metrics["years"] == 3
    )


def build_candidate_years(
    years: tuple[int, ...],
    dates: list[str],
    regimes: pd.DataFrame,
    stock_info: pd.DataFrame,
) -> list[pd.DataFrame]:
    """按冻结规则构建指定年份候选，不读取未授权年份。"""

    frames = []
    for year in years:
        panel = build_year_panel(
            CACHE,
            stock_info,
            regimes,
            dates,
            year,
            f"{year}0101",
            f"{year}1231",
        )
        candidates = build_candidates(panel)
        print(f"year={year} panel={len(panel)} candidates={len(candidates)}")
        frames.append(candidates)
    return frames


def evaluate_candidates(path: Path, cost: float) -> pd.DataFrame:
    """使用原冻结两阶段模型评估候选。"""

    frame, market = _prepare(path)
    config = dict(FROZEN_CONFIG)
    config["cost"] = cost
    trades, _ = walk_forward(frame, market, **config)
    return trades


def run() -> dict:
    """先过内部门槛，再打开 2022-2024；始终封存 2025。"""

    dates = _available_dates(CACHE, "20160101", "20241231")
    regimes = _build_regimes(CACHE, dates)
    stock_info = _load_stock_info(CACHE)
    frames = build_candidate_years(INTERNAL_PANEL_YEARS, dates, regimes, stock_info)
    internal_path = REPORT_DIR / f"{RESEARCH_ID}_internal_candidates.csv"
    pd.concat(frames, ignore_index=True).to_csv(
        internal_path, index=False, encoding="utf-8-sig"
    )
    internal_trades = evaluate_candidates(internal_path, cost=0.25)
    internal_metrics = _metrics(_period(internal_trades, 2019, 2021))
    passed_internal = internal_gate(internal_metrics)
    if not passed_internal:
        result = {
            "research_id": RESEARCH_ID,
            "status": "internal_gate_failed",
            "internal_metrics": internal_metrics,
            "research_validation_opened": False,
            "sealed_holdout_opened": False,
        }
        (REPORT_DIR / f"{RESEARCH_ID}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return result

    frames.extend(
        build_candidate_years(RESEARCH_VALIDATION_YEARS, dates, regimes, stock_info)
    )
    all_path = REPORT_DIR / f"{RESEARCH_ID}_candidates.csv"
    pd.concat(frames, ignore_index=True).to_csv(all_path, index=False, encoding="utf-8-sig")
    base_trades = evaluate_candidates(all_path, cost=0.25)
    stress_trades = evaluate_candidates(all_path, cost=0.50)
    validation = _metrics(_period(base_trades, 2022, 2024))
    validation_days = _period(
        base_trades.groupby("trade_date", as_index=False)["net_ret"].mean(), 2022, 2024
    )
    ci_low, ci_high, p_nonpositive = _bootstrap_probability(
        validation_days, block=20, repetitions=10000
    )
    base_overlap = overlap_adjusted_portfolio(base_trades, CACHE, cost=0.25)
    stress_overlap = overlap_adjusted_portfolio(stress_trades, CACHE, cost=0.50)
    base_path_yearly = annual_path_metrics(base_overlap)
    stress_path_yearly = annual_path_metrics(stress_overlap)
    base_drawdown = max_drawdown(base_overlap["net_ret"]) if not base_overlap.empty else float("nan")
    stress_drawdown = (
        max_drawdown(stress_overlap["net_ret"]) if not stress_overlap.empty else float("nan")
    )
    base_validation_years = base_path_yearly[base_path_yearly["year"].between(2022, 2024)]
    stress_validation_years = stress_path_yearly[
        stress_path_yearly["year"].between(2022, 2024)
    ]
    checks = {
        "internal_gate": passed_internal,
        "validation_minimum_trades": validation["trades"] >= 100,
        "validation_positive_mean": validation["avg_net"] > 0,
        "validation_profit_factor": validation["profit_factor"] > 1.10,
        "validation_every_year_positive": validation["positive_years"] == validation["years"] == 3,
        "bootstrap_lower_bound_positive": ci_low > 0,
        "bootstrap_nonpositive_probability": p_nonpositive < 0.05,
        "base_overlap_every_year_positive": (
            len(base_validation_years) == 3
            and (base_validation_years["return_pct"] > 0).all()
        ),
        "base_overlap_drawdown": base_drawdown > -20.0,
        "stress_overlap_every_year_positive": (
            len(stress_validation_years) == 3
            and (stress_validation_years["return_pct"] > 0).all()
        ),
        "stress_overlap_drawdown": stress_drawdown > -25.0,
    }
    result = {
        "research_id": RESEARCH_ID,
        "status": "six_year_confirmation_pass" if all(checks.values()) else "six_year_confirmation_failed",
        "internal_metrics": internal_metrics,
        "validation_metrics": validation,
        "bootstrap": {
            "ci_low": ci_low,
            "ci_high": ci_high,
            "p_nonpositive": p_nonpositive,
        },
        "base_overlap_yearly": base_path_yearly.to_dict(orient="records"),
        "stress_overlap_yearly": stress_path_yearly.to_dict(orient="records"),
        "base_overlap_max_drawdown_pct": base_drawdown,
        "stress_overlap_max_drawdown_pct": stress_drawdown,
        "checks": {key: bool(value) for key, value in checks.items()},
        "research_validation_opened": True,
        "sealed_holdout_opened": False,
        "maximum_built_year": max(RESEARCH_VALIDATION_YEARS),
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
