"""质量动量浅回调策略：仅横截面排序与领先幅度弃权的六年研究。"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from research.contrarian_candidate_stress import annual_path_metrics, max_drawdown
from research.high_confidence_abstention_audit import overlap_adjusted_portfolio
from research.two_stage_walkforward_research import (
    FEATURE_COLUMNS,
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
SOURCE = REPORT_DIR / "quality_momentum_reentry_sealed_2025_20260808_candidates.csv"
RESEARCH_ID = "quality_momentum_reentry_rank_only_v4_2019_2024_20260808"
BASE_MARGIN = 0.02
NEIGHBOR_MARGINS = (0.01, 0.03)
FORMAL_YEARS = tuple(range(2019, 2025))


def build_oos_top_two(frame: pd.DataFrame, rank_ridge: float = 100.0) -> pd.DataFrame:
    """逐年扩展训练并输出每天样本外 Top2，不使用市场择时门。"""

    model_features = [
        column
        for column in FEATURE_COLUMNS
        if column in frame.columns
        and pd.to_numeric(frame[column], errors="coerce").fillna(0).abs().sum() > 0
    ]
    outputs: list[pd.DataFrame] = []
    maximum_year = min(2024, int(frame["year"].max()))
    for test_year in range(2018, maximum_year + 1):
        train = frame[(frame["year"] < test_year) & frame["relative_target"].notna()]
        test = frame[frame["year"].eq(test_year)].copy()
        if train.empty or test.empty:
            continue
        model = fit_ridge(
            _matrix(train, model_features),
            train["relative_target"].to_numpy(float),
            rank_ridge,
        )
        test["rank_prediction"] = predict_ridge(_matrix(test, model_features), model)
        top_two = (
            test.sort_values(
                ["trade_date", "rank_prediction", "ts_code"],
                ascending=[True, False, True],
                kind="mergesort",
            )
            .groupby("trade_date", group_keys=False)
            .head(2)
            .copy()
        )
        outputs.append(top_two)
    return pd.concat(outputs, ignore_index=True) if outputs else pd.DataFrame()


def select_by_prediction_margin(
    ranked_top_two: pd.DataFrame,
    minimum_margin: float,
    cost: float,
) -> pd.DataFrame:
    """只保留 Top1 明显领先 Top2 的日期；不足两只的日期直接弃权。"""

    ordered = ranked_top_two.sort_values(
        ["trade_date", "rank_prediction", "ts_code"],
        ascending=[True, False, True],
        kind="mergesort",
    ).copy()
    ordered["selected_rank"] = ordered.groupby("trade_date").cumcount() + 1
    if ordered.empty:
        ordered["prediction_margin"] = pd.Series(dtype=float)
        ordered["net_ret"] = pd.Series(dtype=float)
        return ordered
    predictions = ordered.pivot(
        index="trade_date", columns="selected_rank", values="rank_prediction"
    ).reindex(columns=[1, 2])
    predictions["prediction_margin"] = predictions[1] - predictions[2]
    top1 = ordered[ordered["selected_rank"] == 1].merge(
        predictions[["prediction_margin"]],
        left_on="trade_date",
        right_index=True,
        how="left",
        validate="one_to_one",
    )
    selected = top1[top1["prediction_margin"] > minimum_margin].copy()
    selected["net_ret"] = pd.to_numeric(selected["ret_5d"], errors="coerce") - cost
    return selected


def _yearly_metrics(trades: pd.DataFrame) -> pd.DataFrame:
    return (
        trades.groupby(trades["trade_date"].str[:4].astype(int))
        .apply(lambda group: pd.Series(_metrics(group)), include_groups=False)
        .reset_index(names="year")
    )


def _evaluate_margin(ranked: pd.DataFrame, margin: float) -> dict:
    trades = select_by_prediction_margin(ranked, margin, cost=0.25)
    validation = _metrics(_period(trades, 2022, 2024))
    yearly = _yearly_metrics(_period(trades, 2019, 2024))
    return {
        "margin": margin,
        "overall": _metrics(_period(trades, 2019, 2024)),
        "validation": validation,
        "yearly": yearly.to_dict(orient="records"),
        "six_years_positive": bool(len(yearly) == 6 and (yearly["avg_net"] > 0).all()),
        "validation_every_year_positive": bool(
            validation["years"] == validation["positive_years"] == 3
        ),
    }


def run() -> dict:
    """执行主规则、双倍成本与相邻领先幅度压力测试。"""

    frame, _ = _prepare(SOURCE)
    if int(frame["year"].max()) > 2024:
        raise RuntimeError("研究输入意外包含 2025 以后数据")
    ranked = build_oos_top_two(frame)
    base_trades = select_by_prediction_margin(ranked, BASE_MARGIN, cost=0.25)
    stress_trades = select_by_prediction_margin(ranked, BASE_MARGIN, cost=0.50)
    formal_base = _period(base_trades, 2019, 2024)
    formal_stress = _period(stress_trades, 2019, 2024)
    internal = _metrics(_period(formal_base, 2019, 2021))
    validation = _metrics(_period(formal_base, 2022, 2024))
    yearly = _yearly_metrics(formal_base)
    validation_days = _period(
        formal_base.groupby("trade_date", as_index=False)["net_ret"].mean(), 2022, 2024
    )
    ci_low, ci_high, p_nonpositive = _bootstrap_probability(
        validation_days, block=20, repetitions=10000
    )
    base_overlap = overlap_adjusted_portfolio(formal_base, CACHE, cost=0.25)
    stress_overlap = overlap_adjusted_portfolio(formal_stress, CACHE, cost=0.50)
    base_yearly = annual_path_metrics(base_overlap)
    stress_yearly = annual_path_metrics(stress_overlap)
    base_drawdown = max_drawdown(base_overlap["net_ret"]) if not base_overlap.empty else float("nan")
    stress_drawdown = max_drawdown(stress_overlap["net_ret"]) if not stress_overlap.empty else float("nan")
    neighbors = [_evaluate_margin(ranked, margin) for margin in NEIGHBOR_MARGINS]
    checks = {
        "internal_minimum_trades": internal["trades"] >= 100,
        "internal_positive_average": internal["avg_net"] > 0,
        "internal_profit_factor": internal["profit_factor"] > 1.10,
        "internal_every_year_positive": internal["positive_years"] == internal["years"] == 3,
        "validation_minimum_trades": validation["trades"] >= 100,
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
        "neighbor_margin_stability": all(
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
        "neighbor_margin_audit": neighbors,
        "checks": {key: bool(value) for key, value in checks.items()},
        "maximum_built_year": int(frame["year"].max()),
        "holdout_read": False,
        "production_changed": False,
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / f"{RESEARCH_ID}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    formal_base.to_csv(
        REPORT_DIR / f"{RESEARCH_ID}_trades.csv", index=False, encoding="utf-8-sig"
    )
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
