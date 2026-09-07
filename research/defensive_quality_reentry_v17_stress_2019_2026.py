"""防御型质量回踩v17：对v16做参数、持有期和三倍成本压力审计。"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from research import quality_momentum_reentry_sealed_2025 as sealed
from research import quality_momentum_reentry_margin_v3_2019_2024 as metrics_lib
from research import quality_momentum_moneyflow_confirm_v11_2019_2025 as flow_lib
from research.defensive_quality_reentry_v16_2019_2026 import apply_defensive_boundary
from research.quality_momentum_rolling3y_v14_2019_2026 import select_margin_top1


RESEARCH_ID = "defensive_quality_reentry_v17_stress_2019_2026_20260808"
ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports" / "research"
INPUT = REPORT_DIR / "quality_momentum_moneyflow_v12_observation_2026_20260808_walkforward_input.csv"


def build_variant(
    frame: pd.DataFrame,
    market: pd.DataFrame,
    gate_quantile: float,
    prediction_margin: float,
) -> pd.DataFrame:
    """只改变单个预注册扰动参数，其他规则保持v16不变。"""

    config = dict(sealed.FROZEN_CONFIG)
    config["gate_quantile"] = gate_quantile
    gate_kept, _ = sealed.walk_forward(frame, market, **config)
    margin = select_margin_top1(gate_kept, minimum_margin=prediction_margin)
    enriched = flow_lib.attach_moneyflow(margin)
    defensive = apply_defensive_boundary(enriched)
    defensive["net_ret"] = pd.to_numeric(defensive["ret_5d"], errors="coerce") - 0.25
    return defensive


def _period(frame: pd.DataFrame, start: int, end: int, target: str = "ret_5d") -> pd.DataFrame:
    years = frame["trade_date"].astype(str).str[:4].astype(int)
    return frame[years.between(start, end) & frame[target].notna()].copy()


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
    frame, market = sealed._prepare(INPUT)
    base = build_variant(frame, market, 0.80, 0.02)
    parameter_variants = []
    for label, gate_quantile, margin in (
        ("gate_quantile_0_75", 0.75, 0.02),
        ("gate_quantile_0_85", 0.85, 0.02),
        ("prediction_margin_0_01", 0.80, 0.01),
        ("prediction_margin_0_03", 0.80, 0.03),
    ):
        sample = build_variant(frame, market, gate_quantile, margin)
        historical = _period(sample, 2019, 2024)
        yearly = _yearly(historical)
        parameter_variants.append(
            {
                "label": label,
                "metrics": metrics_lib._metrics(historical),
                "yearly": yearly.to_dict(orient="records"),
                "all_historical_years_positive": bool(_all_positive(yearly, 2019, 2024)),
            }
        )

    horizon_results = []
    for days, target in ((3, "ret_3d"), (5, "ret_5d"), (8, "ret_8d")):
        sample = _period(base, 2019, 2024, target=target)
        sample["net_ret"] = pd.to_numeric(sample[target], errors="coerce") - 0.25
        yearly = _yearly(sample)
        metrics = metrics_lib._metrics(sample)
        horizon_results.append(
            {
                "holding_days": days,
                "target": target,
                "metrics": metrics,
                "yearly": yearly.to_dict(orient="records"),
                "all_historical_years_positive": bool(_all_positive(yearly, 2019, 2024)),
            }
        )

    cost_paths = []
    for cost in (0.25, 0.50, 0.75):
        sample = base.copy()
        sample["net_ret"] = pd.to_numeric(sample["ret_5d"], errors="coerce") - cost
        path = metrics_lib.overlap_adjusted_portfolio(sample, metrics_lib.CACHE, cost=cost)
        yearly = metrics_lib.annual_path_metrics(path)
        drawdown = metrics_lib.max_drawdown(path["net_ret"])
        cost_paths.append(
            {
                "cost_pct": cost,
                "yearly": yearly.to_dict(orient="records"),
                "all_historical_years_positive": bool(_path_positive(yearly, 2019, 2024)),
                "max_drawdown_pct": drawdown,
            }
        )

    base_yearly = _yearly(base[base["ret_5d"].notna()].copy())
    recent = base_yearly[base_yearly["year"].between(2025, 2026)]
    checks = {
        "parameter_perturbation_stability": all(
            item["all_historical_years_positive"] for item in parameter_variants
        ),
        "all_horizons_average_positive": all(
            item["metrics"]["avg_net"] > 0 for item in horizon_results
        ),
        "at_least_two_horizons_all_years_positive": sum(
            item["all_historical_years_positive"] for item in horizon_results
        ) >= 2,
        "triple_cost_path_all_years_positive": cost_paths[-1]["all_historical_years_positive"],
        "triple_cost_drawdown": cost_paths[-1]["max_drawdown_pct"] > -30.0,
        "recent_years_present": len(recent) == 2,
        "recent_each_positive": len(recent) == 2 and recent["avg_net"].gt(0).all(),
    }
    result = {
        "research_id": RESEARCH_ID,
        "status": "stress_confirmation_pass" if all(checks.values()) else "stress_confirmation_failed",
        "base_metrics": metrics_lib._metrics(_period(base, 2019, 2024)),
        "base_yearly": base_yearly.to_dict(orient="records"),
        "parameter_variants": parameter_variants,
        "horizon_results": horizon_results,
        "cost_paths": cost_paths,
        "checks": {key: bool(value) for key, value in checks.items()},
        "recent_validation_contaminated": True,
        "production_changed": False,
    }
    (REPORT_DIR / f"{RESEARCH_ID}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
