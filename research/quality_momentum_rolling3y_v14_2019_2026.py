"""质量动量v14：排序与择时均使用最近三年训练窗口。"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from research import quality_momentum_reentry_sealed_2025 as sealed
from research import quality_momentum_reentry_margin_v3_2019_2024 as metrics_lib
from research import quality_momentum_moneyflow_confirm_v11_2019_2025 as flow_lib


RESEARCH_ID = "quality_momentum_rolling3y_v14_2019_2026_20260808"
ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports" / "research"
INPUT = REPORT_DIR / "quality_momentum_moneyflow_v12_observation_2026_20260808_walkforward_input.csv"


def select_margin_top1(trades: pd.DataFrame, minimum_margin: float = 0.02) -> pd.DataFrame:
    """对每个交易日的门控Top2执行冻结领先幅度规则。"""

    work = trades.copy()
    work["trade_date"] = work["trade_date"].astype(str)
    ordered = work.sort_values(
        ["trade_date", "rank_prediction", "ts_code"],
        ascending=[True, False, True],
        kind="mergesort",
    ).copy()
    ordered["selected_rank"] = ordered.groupby("trade_date").cumcount() + 1
    if ordered.empty:
        ordered["prediction_margin"] = pd.Series(dtype=float)
        return ordered
    predictions = ordered.pivot(
        index="trade_date", columns="selected_rank", values="rank_prediction"
    ).reindex(columns=[1, 2])
    predictions["prediction_margin"] = predictions[1] - predictions[2]
    top1 = ordered[ordered["selected_rank"].eq(1)].merge(
        predictions[["prediction_margin"]],
        left_on="trade_date",
        right_index=True,
        how="left",
        validate="one_to_one",
    )
    return top1[top1["prediction_margin"].gt(minimum_margin)].copy()


def evaluate_windows(
    frame: pd.DataFrame,
    market: pd.DataFrame,
    rank_window_years: int,
    gate_window_years: int,
) -> pd.DataFrame:
    """运行指定滚动窗口并应用不耦合的资金确认层。"""

    config = dict(sealed.FROZEN_CONFIG)
    config["rank_window_years"] = rank_window_years
    config["gate_window_years"] = gate_window_years
    gate_kept, _ = sealed.walk_forward(frame, market, **config)
    margin = select_margin_top1(gate_kept)
    enriched = flow_lib.attach_moneyflow(margin)
    confirmed = flow_lib.apply_confirmation(enriched, "flow_ratio_5d", 0.0)
    confirmed["net_ret"] = pd.to_numeric(confirmed["ret_5d"], errors="coerce") - 0.25
    return confirmed


def _period(frame: pd.DataFrame, start: int, end: int) -> pd.DataFrame:
    years = frame["trade_date"].astype(str).str[:4].astype(int)
    return frame[years.between(start, end) & frame["ret_5d"].notna()].copy()


def _yearly(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    return (
        frame.groupby(frame["trade_date"].astype(str).str[:4].astype(int))
        .apply(lambda group: pd.Series(metrics_lib._metrics(group)), include_groups=False)
        .reset_index(names="year")
    )


def _all_positive(yearly: pd.DataFrame, start: int, end: int) -> bool:
    if yearly.empty:
        return False
    sample = yearly[yearly["year"].between(start, end)]
    return len(sample) == end - start + 1 and sample["avg_net"].gt(0).all()


def _path_all_positive(yearly: pd.DataFrame, start: int, end: int) -> bool:
    sample = yearly[yearly["year"].between(start, end)]
    return len(sample) == end - start + 1 and sample["return_pct"].gt(0).all()


def run() -> dict:
    """执行基准窗口、成本路径、近期观察与窗口扰动审计。"""

    frame, market = sealed._prepare(INPUT)
    base = evaluate_windows(frame, market, 3, 3)
    historical = _period(base, 2019, 2024)
    recent = _period(base, 2025, 2026)
    historical_metrics = metrics_lib._metrics(historical)
    yearly = _yearly(base[base["ret_5d"].notna()].copy())
    stress = base.copy()
    stress["net_ret"] = pd.to_numeric(stress["ret_5d"], errors="coerce") - 0.50
    base_path = metrics_lib.overlap_adjusted_portfolio(base, metrics_lib.CACHE, cost=0.25)
    stress_path = metrics_lib.overlap_adjusted_portfolio(stress, metrics_lib.CACHE, cost=0.50)
    base_path_yearly = metrics_lib.annual_path_metrics(base_path)
    stress_path_yearly = metrics_lib.annual_path_metrics(stress_path)
    base_drawdown = metrics_lib.max_drawdown(base_path["net_ret"])
    stress_drawdown = metrics_lib.max_drawdown(stress_path["net_ret"])

    base_checks = {
        "historical_minimum_trades": historical_metrics["trades"] >= 100,
        "historical_average_net_return": historical_metrics["avg_net"] > 0.50,
        "historical_profit_factor": historical_metrics["profit_factor"] > 1.30,
        "historical_every_year_positive": _all_positive(yearly, 2019, 2024),
        "base_path_every_year_positive": _path_all_positive(base_path_yearly, 2019, 2024),
        "stress_path_every_year_positive": _path_all_positive(stress_path_yearly, 2019, 2024),
        "base_drawdown": base_drawdown > -20.0,
        "stress_drawdown": stress_drawdown > -25.0,
    }
    recent_yearly = yearly[yearly["year"].between(2025, 2026)].copy()
    recent_checks = {
        "recent_years_present": len(recent_yearly) == 2,
        "recent_each_minimum_trades": (
            len(recent_yearly) == 2 and recent_yearly["trades"].ge(5).all()
        ),
        "recent_each_positive": len(recent_yearly) == 2 and recent_yearly["avg_net"].gt(0).all(),
    }
    if not all({**base_checks, **recent_checks}.values()):
        result = {
            "research_id": RESEARCH_ID,
            "status": "base_window_failed",
            "historical_metrics": historical_metrics,
            "recent_metrics": metrics_lib._metrics(recent),
            "yearly_metrics": yearly.to_dict(orient="records"),
            "base_path_yearly": base_path_yearly.to_dict(orient="records"),
            "stress_path_yearly": stress_path_yearly.to_dict(orient="records"),
            "base_max_drawdown_pct": base_drawdown,
            "stress_max_drawdown_pct": stress_drawdown,
            "checks": {key: bool(value) for key, value in {**base_checks, **recent_checks}.items()},
            "perturbations_opened": False,
            "production_changed": False,
        }
        (REPORT_DIR / f"{RESEARCH_ID}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return result

    perturbations = []
    for label, rank_window, gate_window in (
        ("rank_window_2", 2, 3),
        ("rank_window_4", 4, 3),
        ("gate_window_2", 3, 2),
        ("gate_window_4", 3, 4),
    ):
        sample = evaluate_windows(frame, market, rank_window, gate_window)
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
        **base_checks,
        **recent_checks,
        "perturbation_stability": all(
            item["all_historical_years_positive"] for item in perturbations
        ),
    }
    result = {
        "research_id": RESEARCH_ID,
        "status": "rolling_confirmation_pass" if all(checks.values()) else "rolling_confirmation_failed",
        "historical_metrics": historical_metrics,
        "recent_metrics": metrics_lib._metrics(recent),
        "yearly_metrics": yearly.to_dict(orient="records"),
        "base_path_yearly": base_path_yearly.to_dict(orient="records"),
        "stress_path_yearly": stress_path_yearly.to_dict(orient="records"),
        "base_max_drawdown_pct": base_drawdown,
        "stress_max_drawdown_pct": stress_drawdown,
        "perturbations": perturbations,
        "checks": {key: bool(value) for key, value in checks.items()},
        "validation_contaminated_by_prior_research": True,
        "production_changed": False,
    }
    (REPORT_DIR / f"{RESEARCH_ID}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    base.to_csv(REPORT_DIR / f"{RESEARCH_ID}_trades.csv", index=False, encoding="utf-8-sig")
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
