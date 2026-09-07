"""质量动量v11：冻结v3信号后叠加独立的五日资金流确认。"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from research import quality_momentum_reentry_margin_v3_2019_2024 as v3


RESEARCH_ID = "quality_momentum_moneyflow_confirm_v11_2019_2025_20260808"
ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports" / "research"
FLOW_DIR = ROOT / "data" / "research" / "clean_moneyflow"
BASE_2019_2024 = REPORT_DIR / "quality_momentum_reentry_margin_v3_2019_2024_20260808_trades.csv"
RECENT_2025 = REPORT_DIR / "quality_momentum_reentry_margin_v3_holdout_2025_20260808_trades.csv"


def attach_moneyflow(trades: pd.DataFrame) -> pd.DataFrame:
    """按信号日和股票连接只使用当日及此前数据构造的资金流特征。"""

    work = trades.copy()
    work["trade_date"] = work["trade_date"].astype(str)
    work["year"] = work["trade_date"].str[:4].astype(int)
    pieces = []
    for year, group in work.groupby("year"):
        path = FLOW_DIR / f"{year}.parquet"
        flow = pd.read_parquet(
            path,
            columns=[
                "trade_date",
                "ts_code",
                "flow_ratio_5d",
                "flow_positive_days_5d",
            ],
        )
        flow["trade_date"] = flow["trade_date"].astype(str)
        pieces.append(
            group.merge(flow, on=["trade_date", "ts_code"], how="left", validate="many_to_one")
        )
    return pd.concat(pieces, ignore_index=True) if pieces else work


def apply_confirmation(trades: pd.DataFrame, rule: str, threshold: float) -> pd.DataFrame:
    """应用预注册的单一资金流确认规则。"""

    if rule == "flow_ratio_5d":
        mask = pd.to_numeric(trades[rule], errors="coerce").gt(threshold)
    elif rule == "flow_positive_days_5d":
        mask = pd.to_numeric(trades[rule], errors="coerce").ge(threshold)
    else:
        raise ValueError(f"未知确认规则: {rule}")
    return trades.loc[mask].copy()


def _period(frame: pd.DataFrame, start: int, end: int) -> pd.DataFrame:
    years = frame["trade_date"].astype(str).str[:4].astype(int)
    return frame[years.between(start, end)].copy()


def _yearly(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["year", "trades", "avg_net", "win_rate", "profit_factor"])
    return (
        frame.groupby(frame["trade_date"].astype(str).str[:4].astype(int))
        .apply(lambda group: pd.Series(v3._metrics(group)), include_groups=False)
        .reset_index(names="year")
    )


def _all_years_positive(yearly: pd.DataFrame, start: int, end: int) -> bool:
    target = yearly[yearly["year"].between(start, end)]
    return len(target) == end - start + 1 and target["avg_net"].gt(0).all()


def _path_years_positive(yearly: pd.DataFrame, start: int, end: int) -> bool:
    target = yearly[yearly["year"].between(start, end)]
    return len(target) == end - start + 1 and target["return_pct"].gt(0).all()


def run() -> dict:
    """执行历史、验证、近期观察、成本和参数扰动审计。"""

    historical_base = pd.read_csv(BASE_2019_2024, dtype={"trade_date": str})
    recent_base = pd.read_csv(RECENT_2025, dtype={"trade_date": str})
    all_base = pd.concat([historical_base, recent_base], ignore_index=True)
    enriched = attach_moneyflow(all_base)
    confirmed = apply_confirmation(enriched, "flow_ratio_5d", 0.0)
    confirmed["net_ret"] = pd.to_numeric(confirmed["ret_5d"], errors="coerce") - 0.25
    stress = confirmed.copy()
    stress["net_ret"] = pd.to_numeric(stress["ret_5d"], errors="coerce") - 0.50

    historical = _period(confirmed, 2019, 2024)
    validation = _period(confirmed, 2022, 2024)
    recent = _period(confirmed, 2025, 2025)
    yearly = _yearly(confirmed)
    historical_metrics = v3._metrics(historical)
    baseline_historical_metrics = v3._metrics(_period(enriched, 2019, 2024))
    validation_metrics = v3._metrics(validation)
    recent_metrics = v3._metrics(recent)
    validation_days = validation.groupby("trade_date", as_index=False)["net_ret"].mean()
    ci_low, ci_high, p_nonpositive = v3._bootstrap_probability(
        validation_days, block=20, repetitions=10000
    )

    base_path = v3.overlap_adjusted_portfolio(confirmed, v3.CACHE, cost=0.25)
    stress_path = v3.overlap_adjusted_portfolio(stress, v3.CACHE, cost=0.50)
    base_path_yearly = v3.annual_path_metrics(base_path)
    stress_path_yearly = v3.annual_path_metrics(stress_path)
    base_drawdown = v3.max_drawdown(base_path["net_ret"]) if not base_path.empty else float("nan")
    stress_drawdown = (
        v3.max_drawdown(stress_path["net_ret"]) if not stress_path.empty else float("nan")
    )

    perturbations = []
    for label, rule, threshold in (
        ("flow_ratio_minus_0_02", "flow_ratio_5d", -0.02),
        ("flow_ratio_plus_0_02", "flow_ratio_5d", 0.02),
        ("flow_positive_days_3", "flow_positive_days_5d", 3),
        ("flow_positive_days_4", "flow_positive_days_5d", 4),
    ):
        sample = apply_confirmation(enriched, rule, threshold)
        sample["net_ret"] = pd.to_numeric(sample["ret_5d"], errors="coerce") - 0.25
        sample_yearly = _yearly(sample)
        perturbations.append(
            {
                "label": label,
                "historical": v3._metrics(_period(sample, 2019, 2024)),
                "recent_2025": v3._metrics(_period(sample, 2025, 2025)),
                "yearly": sample_yearly.to_dict(orient="records"),
                "historical_years_positive": bool(
                    _all_years_positive(sample_yearly, 2019, 2024)
                ),
            }
        )

    recent_base_path = base_path[base_path["trade_date"].astype(str).str[:4].eq("2025")]
    recent_stress_path = stress_path[stress_path["trade_date"].astype(str).str[:4].eq("2025")]
    checks = {
        "historical_minimum_trades": historical_metrics["trades"] >= 100,
        "historical_every_year_positive": _all_years_positive(yearly, 2019, 2024),
        "validation_minimum_trades": validation_metrics["trades"] >= 50,
        "validation_average_net_return": validation_metrics["avg_net"] > 0.50,
        "validation_profit_factor": validation_metrics["profit_factor"] > 1.30,
        "validation_bootstrap_lower_bound_positive": ci_low > 0,
        "validation_bootstrap_nonpositive_probability": p_nonpositive < 0.05,
        "base_path_2019_2024_positive": _path_years_positive(base_path_yearly, 2019, 2024),
        "stress_path_2019_2024_positive": _path_years_positive(stress_path_yearly, 2019, 2024),
        "base_drawdown": base_drawdown > -20.0,
        "stress_drawdown": stress_drawdown > -25.0,
        "moneyflow_average_edge": (
            historical_metrics["avg_net"] >= baseline_historical_metrics["avg_net"] + 0.25
        ),
        "moneyflow_profit_factor_edge": (
            historical_metrics["profit_factor"] >= baseline_historical_metrics["profit_factor"]
        ),
        "recent_2025_minimum_trades": recent_metrics["trades"] >= 5,
        "recent_2025_average_positive": recent_metrics["avg_net"] > 0,
        "recent_2025_base_path_positive": recent_base_path["net_ret"].sum() > 0,
        "recent_2025_stress_path_positive": recent_stress_path["net_ret"].sum() > 0,
        "perturbation_stability": all(
            item["historical_years_positive"]
            and item["recent_2025"]["trades"] >= 5
            and item["recent_2025"]["avg_net"] > 0
            for item in perturbations
        ),
    }
    result = {
        "research_id": RESEARCH_ID,
        "status": "confirmation_pass" if all(checks.values()) else "confirmation_failed",
        "baseline_historical_metrics": baseline_historical_metrics,
        "confirmed_historical_metrics": historical_metrics,
        "validation_metrics": validation_metrics,
        "recent_2025_metrics": recent_metrics,
        "yearly_metrics": yearly.to_dict(orient="records"),
        "bootstrap": {"ci_low": ci_low, "ci_high": ci_high, "p_nonpositive": p_nonpositive},
        "base_path_yearly": base_path_yearly.to_dict(orient="records"),
        "stress_path_yearly": stress_path_yearly.to_dict(orient="records"),
        "base_max_drawdown_pct": base_drawdown,
        "stress_max_drawdown_pct": stress_drawdown,
        "perturbations": perturbations,
        "checks": {key: bool(value) for key, value in checks.items()},
        "recent_observation_is_not_formal_validation": True,
        "production_changed": False,
    }
    (REPORT_DIR / f"{RESEARCH_ID}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    confirmed.to_csv(REPORT_DIR / f"{RESEARCH_ID}_trades.csv", index=False, encoding="utf-8-sig")
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
