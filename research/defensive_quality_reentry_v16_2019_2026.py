"""防御型质量回踩v16：仅在非BULL_TREND状态使用冻结v3+资金确认。"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from research import quality_momentum_reentry_margin_v3_2019_2024 as metrics_lib


RESEARCH_ID = "defensive_quality_reentry_v16_2019_2026_20260808"
ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports" / "research"
HISTORICAL = REPORT_DIR / "quality_momentum_moneyflow_confirm_v11_2019_2025_20260808_trades.csv"
RECENT_2026 = REPORT_DIR / "quality_momentum_moneyflow_v12_observation_2026_20260808_trades.csv"
ALLOWED_REGIMES = {"BEAR_BOUNCE", "BEAR_TREND", "BULL_PULLBACK"}


def apply_defensive_boundary(trades: pd.DataFrame, flow_threshold: float = 0.0) -> pd.DataFrame:
    """应用预注册的状态边界与五日累计资金确认。"""

    flow = pd.to_numeric(trades["flow_ratio_5d"], errors="coerce")
    return trades[
        trades["regime"].astype(str).isin(ALLOWED_REGIMES) & flow.gt(flow_threshold)
    ].copy()


def _period(frame: pd.DataFrame, start: int, end: int) -> pd.DataFrame:
    years = frame["trade_date"].astype(str).str[:4].astype(int)
    return frame[years.between(start, end) & frame["ret_5d"].notna()].copy()


def _yearly(frame: pd.DataFrame) -> pd.DataFrame:
    return (
        frame.groupby(frame["trade_date"].astype(str).str[:4].astype(int))
        .apply(lambda group: pd.Series(metrics_lib._metrics(group)), include_groups=False)
        .reset_index(names="year")
        if not frame.empty
        else pd.DataFrame()
    )


def _all_positive(yearly: pd.DataFrame, start: int, end: int) -> bool:
    if yearly.empty:
        return False
    sample = yearly[yearly["year"].between(start, end)]
    return len(sample) == end - start + 1 and sample["avg_net"].gt(0).all()


def _path_positive(yearly: pd.DataFrame, start: int, end: int) -> bool:
    sample = yearly[yearly["year"].between(start, end)]
    return len(sample) == end - start + 1 and sample["return_pct"].gt(0).all()


def run() -> dict:
    historical_source = pd.read_csv(HISTORICAL, dtype={"trade_date": str})
    recent_source = pd.read_csv(RECENT_2026, dtype={"trade_date": str})
    source = pd.concat([historical_source, recent_source], ignore_index=True)
    base = apply_defensive_boundary(source)
    base["net_ret"] = pd.to_numeric(base["ret_5d"], errors="coerce") - 0.25
    completed = base[base["ret_5d"].notna()].copy()
    historical = _period(completed, 2019, 2024)
    validation = _period(completed, 2022, 2024)
    recent = _period(completed, 2025, 2026)
    yearly = _yearly(completed)
    historical_metrics = metrics_lib._metrics(historical)
    validation_metrics = metrics_lib._metrics(validation)
    validation_days = validation.groupby("trade_date", as_index=False)["net_ret"].mean()
    ci_low, ci_high, p_nonpositive = metrics_lib._bootstrap_probability(
        validation_days, block=20, repetitions=10000
    )
    stress = base.copy()
    stress["net_ret"] = pd.to_numeric(stress["ret_5d"], errors="coerce") - 0.50
    base_path = metrics_lib.overlap_adjusted_portfolio(base, metrics_lib.CACHE, cost=0.25)
    stress_path = metrics_lib.overlap_adjusted_portfolio(stress, metrics_lib.CACHE, cost=0.50)
    base_path_yearly = metrics_lib.annual_path_metrics(base_path)
    stress_path_yearly = metrics_lib.annual_path_metrics(stress_path)
    base_drawdown = metrics_lib.max_drawdown(base_path["net_ret"])
    stress_drawdown = metrics_lib.max_drawdown(stress_path["net_ret"])
    stock_share = historical["ts_code"].value_counts(normalize=True)
    industry_share = historical["industry"].value_counts(normalize=True)
    maximum_stock_share = float(stock_share.max()) if not stock_share.empty else 1.0
    maximum_industry_share = float(industry_share.max()) if not industry_share.empty else 1.0
    recent_yearly = yearly[yearly["year"].between(2025, 2026)] if not yearly.empty else yearly

    perturbations = []
    for label, threshold in (
        ("flow_threshold_minus_0_02", -0.02),
        ("flow_threshold_plus_0_02", 0.02),
    ):
        sample = apply_defensive_boundary(source, threshold)
        sample["net_ret"] = pd.to_numeric(sample["ret_5d"], errors="coerce") - 0.25
        sample_yearly = _yearly(_period(sample, 2019, 2024))
        perturbations.append(
            {
                "label": label,
                "metrics": metrics_lib._metrics(_period(sample, 2019, 2024)),
                "yearly": sample_yearly.to_dict(orient="records"),
                "all_historical_years_positive": bool(_all_positive(sample_yearly, 2019, 2024)),
            }
        )

    checks = {
        "historical_minimum_trades": historical_metrics["trades"] >= 90,
        "historical_average_net_return": historical_metrics["avg_net"] > 1.0,
        "historical_profit_factor": historical_metrics["profit_factor"] > 1.50,
        "historical_every_year_positive": _all_positive(yearly, 2019, 2024),
        "validation_minimum_trades": validation_metrics["trades"] >= 40,
        "validation_every_year_positive": _all_positive(yearly, 2022, 2024),
        "validation_bootstrap_lower_bound_positive": ci_low > 0,
        "validation_bootstrap_nonpositive_probability": p_nonpositive < 0.05,
        "base_path_every_year_positive": _path_positive(base_path_yearly, 2019, 2024),
        "stress_path_every_year_positive": _path_positive(stress_path_yearly, 2019, 2024),
        "base_drawdown": base_drawdown > -20.0,
        "stress_drawdown": stress_drawdown > -25.0,
        "maximum_single_stock_share": maximum_stock_share < 0.06,
        "maximum_single_industry_share": maximum_industry_share < 0.20,
        "recent_years_present": len(recent_yearly) == 2,
        "recent_each_has_signal": len(recent_yearly) == 2 and recent_yearly["trades"].ge(1).all(),
        "recent_each_positive": len(recent_yearly) == 2 and recent_yearly["avg_net"].gt(0).all(),
        "flow_threshold_perturbation_stability": all(
            item["all_historical_years_positive"] for item in perturbations
        ),
    }
    result = {
        "research_id": RESEARCH_ID,
        "status": "defensive_confirmation_pass" if all(checks.values()) else "defensive_confirmation_failed",
        "historical_metrics": historical_metrics,
        "validation_metrics": validation_metrics,
        "recent_metrics": metrics_lib._metrics(recent),
        "yearly_metrics": yearly.to_dict(orient="records"),
        "bootstrap": {"ci_low": ci_low, "ci_high": ci_high, "p_nonpositive": p_nonpositive},
        "base_path_yearly": base_path_yearly.to_dict(orient="records"),
        "stress_path_yearly": stress_path_yearly.to_dict(orient="records"),
        "base_max_drawdown_pct": base_drawdown,
        "stress_max_drawdown_pct": stress_drawdown,
        "maximum_single_stock_share": maximum_stock_share,
        "maximum_single_industry_share": maximum_industry_share,
        "perturbations": perturbations,
        "checks": {key: bool(value) for key, value in checks.items()},
        "recent_validation_contaminated": True,
        "production_changed": False,
    }
    (REPORT_DIR / f"{RESEARCH_ID}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    base.to_csv(REPORT_DIR / f"{RESEARCH_ID}_trades.csv", index=False, encoding="utf-8-sig")
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
