"""质量动量浅回调策略：使用年内在线相对尺度的二阶段门控。"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from research.contrarian_candidate_stress import annual_path_metrics, max_drawdown
from research.high_confidence_abstention_audit import overlap_adjusted_portfolio
from research.quality_momentum_reentry_rank_only_v4_2019_2024 import (
    BASE_MARGIN,
    SOURCE,
    build_oos_top_two,
    select_by_prediction_margin,
)
from research.two_stage_walkforward_research import (
    MARKET_FEATURES,
    _bootstrap_probability,
    _matrix,
    _metrics,
    _period,
    _prepare,
    fit_ridge,
    predict_ridge,
)

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "cache"
REPORT_DIR = ROOT / "reports" / "research"
RESEARCH_ID = "quality_momentum_reentry_online_gate_v5_2019_2024_20260808"
BASE_QUANTILE = 0.80
NEIGHBOR_QUANTILES = (0.75, 0.85)
WARMUP_DAYS = 20


def online_gate_decisions(
    daily_predictions: pd.DataFrame,
    quantile: float,
    warmup_days: int,
) -> pd.DataFrame:
    """用同年度此前门控分形成阈值，当前值绝不进入自己的阈值。"""

    ordered = daily_predictions.sort_values("trade_date", kind="mergesort").copy()
    history: list[float] = []
    thresholds: list[float] = []
    passes: list[bool] = []
    for value in pd.to_numeric(ordered["gate_prediction"], errors="coerce"):
        finite_history = np.asarray([item for item in history if np.isfinite(item)], dtype=float)
        if len(finite_history) < warmup_days or not np.isfinite(value):
            threshold = float("nan")
            passed = False
        else:
            threshold = float(np.quantile(finite_history, quantile))
            passed = bool(value > threshold)
        thresholds.append(threshold)
        passes.append(passed)
        history.append(float(value))
    ordered["online_gate_threshold"] = thresholds
    ordered["online_gate_pass"] = passes
    return ordered


def build_oos_gate_predictions(frame: pd.DataFrame, market: pd.DataFrame) -> pd.DataFrame:
    """生成逐年样本外 Top2 与门控分；门控训练只读取此前年度组合结果。"""

    ranked = build_oos_top_two(frame, rank_ridge=100.0)
    all_days: list[pd.DataFrame] = []
    outputs: list[pd.DataFrame] = []
    for test_year in range(2018, 2025):
        test_top = ranked[ranked["year"].eq(test_year)].copy()
        if test_top.empty:
            continue
        prior_days = pd.concat(all_days, ignore_index=True) if all_days else pd.DataFrame()
        test_market = market[market["year"].eq(test_year)].copy()
        if prior_days.empty:
            test_market["gate_prediction"] = 1.0
        else:
            gate_train = prior_days.merge(
                market.drop(columns="year"), on="trade_date", how="left"
            )
            gate_model = fit_ridge(
                _matrix(gate_train, MARKET_FEATURES),
                pd.to_numeric(gate_train["net_ret"], errors="coerce").to_numpy(float),
                100.0,
            )
            test_market["gate_prediction"] = predict_ridge(
                _matrix(test_market, MARKET_FEATURES), gate_model
            )
        test_top = test_top.merge(
            test_market[["trade_date", "gate_prediction"]], on="trade_date", how="left"
        )
        outputs.append(test_top)
        daily = test_top.groupby("trade_date", as_index=False).agg(
            gross_ret=("ret_5d", "mean"), trades=("ts_code", "size")
        )
        daily["net_ret"] = daily["gross_ret"] - 0.25
        daily["year"] = test_year
        all_days.append(daily)
    return pd.concat(outputs, ignore_index=True) if outputs else pd.DataFrame()


def select_online_gated(
    predicted_top_two: pd.DataFrame,
    quantile: float,
    cost: float,
    warmup_days: int = WARMUP_DAYS,
) -> pd.DataFrame:
    """先按年执行在线门控，再执行冻结的 Top1 领先幅度弃权。"""

    selected_years: list[pd.DataFrame] = []
    for year, group in predicted_top_two.groupby("year", sort=True):
        daily = group[["trade_date", "gate_prediction"]].drop_duplicates("trade_date")
        decisions = online_gate_decisions(daily, quantile, warmup_days)
        passed_dates = set(decisions.loc[decisions["online_gate_pass"], "trade_date"])
        passed = group[group["trade_date"].isin(passed_dates)].copy()
        if passed.empty:
            continue
        selected_years.append(select_by_prediction_margin(passed, BASE_MARGIN, cost))
    return pd.concat(selected_years, ignore_index=True) if selected_years else pd.DataFrame()


def _yearly_metrics(trades: pd.DataFrame) -> pd.DataFrame:
    return (
        trades.groupby(trades["trade_date"].str[:4].astype(int))
        .apply(lambda group: pd.Series(_metrics(group)), include_groups=False)
        .reset_index(names="year")
    )


def _perturbation(predicted: pd.DataFrame, quantile: float) -> dict:
    trades = _period(select_online_gated(predicted, quantile, cost=0.25), 2019, 2024)
    yearly = _yearly_metrics(trades)
    validation = _metrics(_period(trades, 2022, 2024))
    return {
        "quantile": quantile,
        "overall": _metrics(trades),
        "validation": validation,
        "six_years_positive": bool(len(yearly) == 6 and (yearly["avg_net"] > 0).all()),
        "validation_every_year_positive": bool(
            validation["years"] == validation["positive_years"] == 3
        ),
    }


def run() -> dict:
    """运行在线门控主规则和预注册压力测试。"""

    frame, market = _prepare(SOURCE)
    if int(frame["year"].max()) > 2024:
        raise RuntimeError("研究输入意外包含 2025 以后数据")
    predicted = build_oos_gate_predictions(frame, market)
    base = _period(select_online_gated(predicted, BASE_QUANTILE, cost=0.25), 2019, 2024)
    stress = _period(select_online_gated(predicted, BASE_QUANTILE, cost=0.50), 2019, 2024)
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
    neighbors = [_perturbation(predicted, value) for value in NEIGHBOR_QUANTILES]
    checks = {
        "internal_minimum_trades": internal["trades"] >= 60,
        "internal_positive_average": internal["avg_net"] > 0,
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
        "neighbor_quantile_stability": all(
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
        "neighbor_quantile_audit": neighbors,
        "checks": {key: bool(value) for key, value in checks.items()},
        "maximum_built_year": int(frame["year"].max()),
        "production_changed": False,
    }
    (REPORT_DIR / f"{RESEARCH_ID}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    base.to_csv(REPORT_DIR / f"{RESEARCH_ID}_trades.csv", index=False, encoding="utf-8-sig")
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
