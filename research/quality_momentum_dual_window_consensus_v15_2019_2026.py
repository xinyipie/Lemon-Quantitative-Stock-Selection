"""质量动量v15：扩展与滚动窗口的个股排序共识。"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from research import quality_momentum_reentry_sealed_2025 as sealed
from research import quality_momentum_reentry_margin_v3_2019_2024 as metrics_lib
from research import quality_momentum_moneyflow_confirm_v11_2019_2025 as flow_lib
from research.quality_momentum_rolling3y_v14_2019_2026 import select_margin_top1


RESEARCH_ID = "quality_momentum_dual_window_consensus_v15_2019_2026_20260808"
ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports" / "research"
INPUT = REPORT_DIR / "quality_momentum_moneyflow_v12_observation_2026_20260808_walkforward_input.csv"


def model_outputs(
    frame: pd.DataFrame,
    market: pd.DataFrame,
    rank_window: int,
    gate_window: int,
) -> tuple[pd.DataFrame, set[str]]:
    """分别生成近似无门控的排序Top1和原q80市场门开启日期。"""

    rank_config = dict(sealed.FROZEN_CONFIG)
    rank_config.update(
        rank_window_years=rank_window,
        gate_window_years=gate_window,
        gate_quantile=0.0,
    )
    rank_top2, _ = sealed.walk_forward(frame, market, **rank_config)
    rank_top1 = select_margin_top1(rank_top2)

    gate_config = dict(sealed.FROZEN_CONFIG)
    gate_config.update(
        rank_window_years=rank_window,
        gate_window_years=gate_window,
        gate_quantile=0.8,
    )
    gate_kept, _ = sealed.walk_forward(frame, market, **gate_config)
    open_dates = set(gate_kept["trade_date"].astype(str).tolist())
    return rank_top1, open_dates


def build_consensus(
    expanding: pd.DataFrame,
    rolling: pd.DataFrame,
    open_dates: set[str],
) -> pd.DataFrame:
    """仅保留同日同股排序共识，市场门使用预注册的逻辑或。"""

    left = expanding.copy()
    right = rolling[["trade_date", "ts_code"]].drop_duplicates().copy()
    left["trade_date"] = left["trade_date"].astype(str)
    right["trade_date"] = right["trade_date"].astype(str)
    consensus = left.merge(
        right, on=["trade_date", "ts_code"], how="inner", validate="one_to_one"
    )
    return consensus[consensus["trade_date"].isin(open_dates)].copy()


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
    frame, market = sealed._prepare(INPUT)
    expanding, expanding_open = model_outputs(frame, market, 0, 99)
    rolling, rolling_open = model_outputs(frame, market, 3, 3)
    consensus = build_consensus(expanding, rolling, expanding_open | rolling_open)
    enriched = flow_lib.attach_moneyflow(consensus)
    confirmed = flow_lib.apply_confirmation(enriched, "flow_ratio_5d", 0.0)
    confirmed["net_ret"] = pd.to_numeric(confirmed["ret_5d"], errors="coerce") - 0.25
    completed = confirmed[confirmed["ret_5d"].notna()].copy()
    historical = _period(completed, 2019, 2024)
    recent = _period(completed, 2025, 2026)
    historical_metrics = metrics_lib._metrics(historical)
    yearly = _yearly(completed)
    stress = confirmed.copy()
    stress["net_ret"] = pd.to_numeric(stress["ret_5d"], errors="coerce") - 0.50
    base_path = metrics_lib.overlap_adjusted_portfolio(confirmed, metrics_lib.CACHE, cost=0.25)
    stress_path = metrics_lib.overlap_adjusted_portfolio(stress, metrics_lib.CACHE, cost=0.50)
    base_path_yearly = metrics_lib.annual_path_metrics(base_path)
    stress_path_yearly = metrics_lib.annual_path_metrics(stress_path)
    base_drawdown = metrics_lib.max_drawdown(base_path["net_ret"])
    stress_drawdown = metrics_lib.max_drawdown(stress_path["net_ret"])
    recent_yearly = yearly[yearly["year"].between(2025, 2026)] if not yearly.empty else yearly
    checks = {
        "historical_minimum_trades": historical_metrics["trades"] >= 80,
        "historical_average_net_return": historical_metrics["avg_net"] > 0.75,
        "historical_profit_factor": historical_metrics["profit_factor"] > 1.40,
        "historical_every_year_positive": _all_positive(yearly, 2019, 2024),
        "base_path_every_year_positive": _path_positive(base_path_yearly, 2019, 2024),
        "stress_path_every_year_positive": _path_positive(stress_path_yearly, 2019, 2024),
        "base_drawdown": base_drawdown > -20.0,
        "stress_drawdown": stress_drawdown > -25.0,
        "recent_years_present": len(recent_yearly) == 2,
        "recent_each_minimum_trades": len(recent_yearly) == 2 and recent_yearly["trades"].ge(5).all(),
        "recent_each_positive": len(recent_yearly) == 2 and recent_yearly["avg_net"].gt(0).all(),
    }
    result = {
        "research_id": RESEARCH_ID,
        "status": "consensus_confirmation_pass" if all(checks.values()) else "consensus_confirmation_failed",
        "historical_metrics": historical_metrics,
        "recent_metrics": metrics_lib._metrics(recent),
        "yearly_metrics": yearly.to_dict(orient="records"),
        "base_path_yearly": base_path_yearly.to_dict(orient="records"),
        "stress_path_yearly": stress_path_yearly.to_dict(orient="records"),
        "base_max_drawdown_pct": base_drawdown,
        "stress_max_drawdown_pct": stress_drawdown,
        "expanding_rank_signals": int(len(expanding)),
        "rolling_rank_signals": int(len(rolling)),
        "consensus_before_flow": int(len(consensus)),
        "confirmed_signals": int(len(confirmed)),
        "checks": {key: bool(value) for key, value in checks.items()},
        "validation_contaminated_by_prior_research": True,
        "production_changed": False,
    }
    (REPORT_DIR / f"{RESEARCH_ID}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    confirmed.to_csv(REPORT_DIR / f"{RESEARCH_ID}_trades.csv", index=False, encoding="utf-8-sig")
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
