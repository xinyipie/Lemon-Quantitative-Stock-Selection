"""趋势突破候选的技术基线与资金流增强 Ridge 走步研究。"""

from __future__ import annotations

import json

import pandas as pd

from research.contrarian_candidate_stress import annual_path_metrics, max_drawdown
from research.high_confidence_abstention_audit import overlap_adjusted_portfolio
from research.moneyflow_breakout_factor_audit import (
    FEATURES as FLOW_RAW_FEATURES,
    REPORT_DIR,
    STORE_DIR,
    breakout_candidate_mask,
)
from research.quality_momentum_reentry_online_gate_v5_2019_2024 import CACHE
from research.two_stage_walkforward_research import (
    _bootstrap_probability,
    _matrix,
    _metrics,
    _period,
    fit_ridge,
    predict_ridge,
)

RESEARCH_ID = "moneyflow_breakout_ridge_v9_2019_2024_20260808"
TECHNICAL_RAW_FEATURES = [
    "ret_5", "ret_20", "ret_60", "drawdown_20", "rsi_14", "volatility_20",
    "turnover_rate", "volume_ratio", "industry_rs_20", "entry_gap_pct",
]
ALLOWED_REGIMES = {"BULL_TREND", "BULL_PULLBACK", "BEAR_BOUNCE"}
BASE_RIDGE = 100.0
BASE_CONFIDENCE = 1.5


def load_candidates() -> pd.DataFrame:
    """读取固定技术候选，并构建同日横截面秩特征。"""

    required = [
        "ts_code", "name", "industry", "trade_date", "history_count", "synthetic_close",
        "prior_high_20", "ma_20", "ma_60", "ret_5", "ret_20", "ret_60",
        "drawdown_20", "rsi_14", "volatility_20", "pct_chg", "turnover_rate",
        "volume_ratio", "industry_rs_20", "entry_open", "entry_gap_pct", "ret_5d",
        "regime", *FLOW_RAW_FEATURES,
    ]
    frames = []
    for year in range(2016, 2025):
        frame = pd.read_parquet(STORE_DIR / f"{year}.parquet", columns=required)
        frame = frame.loc[breakout_candidate_mask(frame)].copy()
        frame = frame.dropna(subset=["ret_5d", *FLOW_RAW_FEATURES])
        frame["year"] = year
        frames.append(frame)
    result = pd.concat(frames, ignore_index=True)
    for feature in [*TECHNICAL_RAW_FEATURES, *FLOW_RAW_FEATURES]:
        values = pd.to_numeric(result[feature], errors="coerce")
        result[f"rank_{feature}"] = values.groupby(result["trade_date"]).rank(
            pct=True, method="average"
        )
    result["relative_target"] = pd.to_numeric(result["ret_5d"], errors="coerce") - result.groupby(
        "trade_date"
    )["ret_5d"].transform("mean")
    return result


def select_top1_confident(test: pd.DataFrame, minimum_zscore: float, cost: float) -> pd.DataFrame:
    """按当日预测横截面标准分弃权，再取唯一 Top1。"""

    work = test.copy()
    grouped = work.groupby("trade_date")["rank_prediction"]
    median = grouped.transform("median")
    scale = grouped.transform("std").replace(0, pd.NA)
    work["prediction_zscore"] = (work["rank_prediction"] - median) / scale
    work = work[work["prediction_zscore"].ge(minimum_zscore)].copy()
    selected = (
        work.sort_values(
            ["trade_date", "rank_prediction", "ts_code"],
            ascending=[True, False, True],
            kind="mergesort",
        )
        .groupby("trade_date", group_keys=False)
        .head(1)
        .copy()
    )
    selected["net_ret"] = pd.to_numeric(selected["ret_5d"], errors="coerce") - cost
    return selected


def walk_forward(
    candidates: pd.DataFrame,
    features: list[str],
    ridge: float,
    confidence: float,
    cost: float,
) -> pd.DataFrame:
    """逐年扩展训练，测试年只读取当日可见特征。"""

    outputs = []
    for test_year in range(2019, 2025):
        train = candidates[
            (candidates["year"] < test_year) & candidates["relative_target"].notna()
        ]
        test = candidates[
            candidates["year"].eq(test_year)
            & candidates["regime"].astype(str).isin(ALLOWED_REGIMES)
        ].copy()
        if train.empty or test.empty:
            continue
        model = fit_ridge(
            _matrix(train, features), train["relative_target"].to_numpy(float), ridge
        )
        test["rank_prediction"] = predict_ridge(_matrix(test, features), model)
        outputs.append(select_top1_confident(test, confidence, cost))
    return pd.concat(outputs, ignore_index=True) if outputs else pd.DataFrame()


def _yearly(trades: pd.DataFrame) -> pd.DataFrame:
    return (
        trades.groupby(trades["trade_date"].str[:4].astype(int))
        .apply(lambda group: pd.Series(_metrics(group)), include_groups=False)
        .reset_index(names="year")
    )


def _summary(trades: pd.DataFrame) -> dict:
    validation = _metrics(_period(trades, 2022, 2024))
    yearly = _yearly(trades)
    return {
        "internal": _metrics(_period(trades, 2019, 2021)),
        "validation": validation,
        "yearly": yearly.to_dict(orient="records"),
        "six_years_positive": bool(len(yearly) == 6 and (yearly["avg_net"] > 0).all()),
    }


def run() -> dict:
    """执行资金流增量、成本、路径与参数扰动审计。"""

    candidates = load_candidates()
    technical = [f"rank_{name}" for name in TECHNICAL_RAW_FEATURES]
    enhanced = [*technical, *[f"rank_{name}" for name in FLOW_RAW_FEATURES]]
    baseline_trades = walk_forward(candidates, technical, BASE_RIDGE, BASE_CONFIDENCE, 0.25)
    base = walk_forward(candidates, enhanced, BASE_RIDGE, BASE_CONFIDENCE, 0.25)
    stress = base.copy()
    stress["net_ret"] = pd.to_numeric(stress["ret_5d"], errors="coerce") - 0.50
    baseline = _summary(baseline_trades)
    enhanced_summary = _summary(base)
    validation = enhanced_summary["validation"]
    yearly = pd.DataFrame(enhanced_summary["yearly"])
    days = _period(base.groupby("trade_date", as_index=False)["net_ret"].mean(), 2022, 2024)
    ci_low, ci_high, p_nonpositive = _bootstrap_probability(days, block=20, repetitions=10000)
    base_overlap = overlap_adjusted_portfolio(base, CACHE, cost=0.25)
    stress_overlap = overlap_adjusted_portfolio(stress, CACHE, cost=0.50)
    base_yearly = annual_path_metrics(base_overlap)
    stress_yearly = annual_path_metrics(stress_overlap)
    base_yearly = base_yearly[base_yearly["year"].between(2019, 2024)].copy()
    stress_yearly = stress_yearly[stress_yearly["year"].between(2019, 2024)].copy()
    base_drawdown = max_drawdown(base_overlap["net_ret"]) if not base_overlap.empty else float("nan")
    stress_drawdown = max_drawdown(stress_overlap["net_ret"]) if not stress_overlap.empty else float("nan")
    perturbations = []
    for label, ridge, confidence in (
        ("ridge_50", 50.0, BASE_CONFIDENCE),
        ("ridge_200", 200.0, BASE_CONFIDENCE),
        ("confidence_1_25", BASE_RIDGE, 1.25),
        ("confidence_1_75", BASE_RIDGE, 1.75),
    ):
        trades = walk_forward(candidates, enhanced, ridge, confidence, 0.25)
        summary = _summary(trades)
        perturbations.append({"label": label, **summary})
    checks = {
        "validation_minimum_trades": validation["trades"] >= 120,
        "validation_average_net_return": validation["avg_net"] > 0.25,
        "validation_profit_factor": validation["profit_factor"] > 1.15,
        "validation_every_year_positive": validation["positive_years"] == validation["years"] == 3,
        "six_years_positive": enhanced_summary["six_years_positive"],
        "bootstrap_lower_bound_positive": ci_low > 0,
        "bootstrap_nonpositive_probability": p_nonpositive < 0.05,
        "base_overlap_every_year_positive": len(base_yearly) == 6 and (base_yearly["return_pct"] > 0).all(),
        "stress_overlap_every_year_positive": len(stress_yearly) == 6 and (stress_yearly["return_pct"] > 0).all(),
        "base_overlap_drawdown": base_drawdown > -20.0,
        "stress_overlap_drawdown": stress_drawdown > -25.0,
        "moneyflow_average_edge": validation["avg_net"] >= baseline["validation"]["avg_net"] + 0.10,
        "moneyflow_profit_factor_edge": validation["profit_factor"] >= baseline["validation"]["profit_factor"],
        "perturbation_stability": all(
            item["validation"]["positive_years"] == item["validation"]["years"] == 3
            and item["validation"]["avg_net"] > 0
            for item in perturbations
        ),
    }
    result = {
        "research_id": RESEARCH_ID,
        "status": "six_year_confirmation_pass" if all(checks.values()) else "six_year_confirmation_failed",
        "candidate_rows": int(len(candidates)),
        "technical_baseline": baseline,
        "moneyflow_enhanced": enhanced_summary,
        "bootstrap": {"ci_low": ci_low, "ci_high": ci_high, "p_nonpositive": p_nonpositive},
        "base_overlap_yearly": base_yearly.to_dict(orient="records"),
        "stress_overlap_yearly": stress_yearly.to_dict(orient="records"),
        "base_overlap_max_drawdown_pct": base_drawdown,
        "stress_overlap_max_drawdown_pct": stress_drawdown,
        "perturbations": perturbations,
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
