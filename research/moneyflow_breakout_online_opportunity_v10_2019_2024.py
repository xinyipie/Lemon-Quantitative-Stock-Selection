"""资金流突破策略v10：用完全在线的历史机会分位控制出手频率。"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from research import moneyflow_breakout_ridge_v9_2019_2024 as v9


RESEARCH_ID = "moneyflow_breakout_online_opportunity_v10_2019_2024_20260808"
ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports" / "research"
BASE_QUANTILE = 0.80
BASE_ZSCORE = 1.00
BASE_RIDGE = 100.0
LOOKBACK_DAYS = 252
MIN_HISTORY_DAYS = 126


def apply_online_opportunity_gate(
    daily_top: pd.DataFrame,
    quantile: float,
    lookback_days: int = LOOKBACK_DAYS,
    min_history_days: int = MIN_HISTORY_DAYS,
) -> pd.DataFrame:
    """只用当前交易日之前的最高预测分计算在线机会门。"""

    if daily_top.empty:
        return daily_top.copy()
    ordered = daily_top.sort_values("trade_date").copy()
    prior_prediction = pd.to_numeric(ordered["rank_prediction"], errors="coerce").shift(1)
    ordered["opportunity_threshold"] = prior_prediction.rolling(
        lookback_days, min_periods=min_history_days
    ).quantile(quantile)
    return ordered[
        ordered["opportunity_threshold"].notna()
        & ordered["rank_prediction"].ge(ordered["opportunity_threshold"])
    ].copy()


def predict_daily_top(
    candidates: pd.DataFrame,
    features: list[str],
    ridge: float,
    minimum_zscore: float,
) -> pd.DataFrame:
    """逐年扩展训练，每日先保留预测最高的一只股票。"""

    outputs = []
    for test_year in range(2019, 2025):
        train = candidates[
            (candidates["year"] < test_year) & candidates["relative_target"].notna()
        ]
        test = candidates[
            candidates["year"].eq(test_year)
            & candidates["regime"].astype(str).isin(v9.ALLOWED_REGIMES)
        ].copy()
        if train.empty or test.empty:
            continue
        model = v9.fit_ridge(
            v9._matrix(train, features), train["relative_target"].to_numpy(float), ridge
        )
        test["rank_prediction"] = v9.predict_ridge(v9._matrix(test, features), model)
        grouped = test.groupby("trade_date")["rank_prediction"]
        mean = grouped.transform("mean")
        scale = grouped.transform("std")
        test["prediction_zscore"] = (test["rank_prediction"] - mean) / scale.mask(scale.eq(0))
        top_index = test.groupby("trade_date")["rank_prediction"].idxmax()
        top = test.loc[top_index].copy()
        outputs.append(top[top["prediction_zscore"].ge(minimum_zscore)])
    return pd.concat(outputs, ignore_index=True) if outputs else pd.DataFrame()


def walk_forward_online(
    candidates: pd.DataFrame,
    features: list[str],
    ridge: float,
    minimum_zscore: float,
    opportunity_quantile: float,
    cost: float,
) -> pd.DataFrame:
    """生成在线低频信号，并扣除单笔往返成本。"""

    daily_top = predict_daily_top(candidates, features, ridge, minimum_zscore)
    selected = apply_online_opportunity_gate(daily_top, opportunity_quantile)
    selected["net_ret"] = pd.to_numeric(selected["ret_5d"], errors="coerce") - cost
    return selected.reset_index(drop=True)


def _all_six_years_positive(yearly: pd.DataFrame) -> bool:
    return (
        len(yearly) == 6
        and set(yearly["year"].astype(int)) == set(range(2019, 2025))
        and yearly["avg_net"].gt(0).all()
    )


def _path_all_six_years_positive(yearly: pd.DataFrame) -> bool:
    return (
        len(yearly) == 6
        and set(yearly["year"].astype(int)) == set(range(2019, 2025))
        and yearly["return_pct"].gt(0).all()
    )


def evaluate(
    candidates: pd.DataFrame,
    features: list[str],
    ridge: float,
    minimum_zscore: float,
    opportunity_quantile: float,
) -> tuple[pd.DataFrame, dict]:
    """评估单一预注册参数组合。"""

    trades = walk_forward_online(
        candidates, features, ridge, minimum_zscore, opportunity_quantile, 0.25
    )
    summary = v9._summary(trades)
    return trades, summary


def run() -> dict:
    """执行技术基线、资金流增强、路径和参数扰动审计。"""

    candidates = v9.load_candidates()
    technical = [f"rank_{name}" for name in v9.TECHNICAL_RAW_FEATURES]
    enhanced = [*technical, *[f"rank_{name}" for name in v9.FLOW_RAW_FEATURES]]
    baseline_trades, baseline = evaluate(
        candidates, technical, BASE_RIDGE, BASE_ZSCORE, BASE_QUANTILE
    )
    base, enhanced_summary = evaluate(
        candidates, enhanced, BASE_RIDGE, BASE_ZSCORE, BASE_QUANTILE
    )
    stress = base.copy()
    stress["net_ret"] = pd.to_numeric(stress["ret_5d"], errors="coerce") - 0.50
    yearly = pd.DataFrame(enhanced_summary["yearly"])
    validation = enhanced_summary["validation"]
    validation_days = v9._period(
        base.groupby("trade_date", as_index=False)["net_ret"].mean(), 2022, 2024
    )
    ci_low, ci_high, p_nonpositive = v9._bootstrap_probability(
        validation_days, block=20, repetitions=10000
    )
    base_path = v9.overlap_adjusted_portfolio(base, v9.CACHE, cost=0.25)
    stress_path = v9.overlap_adjusted_portfolio(stress, v9.CACHE, cost=0.50)
    base_path_yearly = v9.annual_path_metrics(base_path)
    stress_path_yearly = v9.annual_path_metrics(stress_path)
    base_path_yearly = base_path_yearly[base_path_yearly["year"].between(2019, 2024)]
    stress_path_yearly = stress_path_yearly[stress_path_yearly["year"].between(2019, 2024)]
    base_drawdown = v9.max_drawdown(base_path["net_ret"]) if not base_path.empty else float("nan")
    stress_drawdown = (
        v9.max_drawdown(stress_path["net_ret"]) if not stress_path.empty else float("nan")
    )
    perturbations = []
    for label, ridge, zscore, quantile in (
        ("quantile_0_75", BASE_RIDGE, BASE_ZSCORE, 0.75),
        ("quantile_0_85", BASE_RIDGE, BASE_ZSCORE, 0.85),
        ("zscore_0_75", BASE_RIDGE, 0.75, BASE_QUANTILE),
        ("zscore_1_25", BASE_RIDGE, 1.25, BASE_QUANTILE),
        ("ridge_50", 50.0, BASE_ZSCORE, BASE_QUANTILE),
        ("ridge_200", 200.0, BASE_ZSCORE, BASE_QUANTILE),
    ):
        _, summary = evaluate(candidates, enhanced, ridge, zscore, quantile)
        perturbations.append({"label": label, **summary})
    checks = {
        "validation_minimum_trades": validation["trades"] >= 75,
        "validation_average_net_return": validation["avg_net"] > 0.35,
        "validation_profit_factor": validation["profit_factor"] > 1.20,
        "validation_every_year_positive": validation["positive_years"] == 3,
        "six_years_positive": _all_six_years_positive(yearly),
        "bootstrap_lower_bound_positive": ci_low > 0,
        "bootstrap_nonpositive_probability": p_nonpositive < 0.05,
        "base_path_every_year_positive": _path_all_six_years_positive(base_path_yearly),
        "stress_path_every_year_positive": _path_all_six_years_positive(stress_path_yearly),
        "base_drawdown": base_drawdown > -20.0,
        "stress_drawdown": stress_drawdown > -25.0,
        "moneyflow_average_edge": (
            validation["avg_net"] >= baseline["validation"]["avg_net"] + 0.05
        ),
        "moneyflow_profit_factor_edge": (
            validation["profit_factor"] >= baseline["validation"]["profit_factor"]
        ),
        "perturbation_stability": all(
            item["validation"]["positive_years"] == 3
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
        "base_path_yearly": base_path_yearly.to_dict(orient="records"),
        "stress_path_yearly": stress_path_yearly.to_dict(orient="records"),
        "base_max_drawdown_pct": base_drawdown,
        "stress_max_drawdown_pct": stress_drawdown,
        "perturbations": perturbations,
        "checks": {key: bool(value) for key, value in checks.items()},
        "production_changed": False,
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / f"{RESEARCH_ID}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    base.to_csv(REPORT_DIR / f"{RESEARCH_ID}_trades.csv", index=False, encoding="utf-8-sig")
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
