"""质量动量浅回调策略：只用内部 OOS 冻结 3/5/8 日持有期。"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from research.contrarian_candidate_stress import annual_path_metrics, max_drawdown
from research.quality_momentum_reentry_online_gate_v5_2019_2024 import CACHE, REPORT_DIR
from research.two_stage_walkforward_research import _bootstrap_probability, _metrics, _period

RESEARCH_ID = "quality_momentum_reentry_horizon_v8_2019_2024_20260808"
SOURCE = REPORT_DIR / "quality_momentum_reentry_online_gate_v5_2019_2024_20260808_trades.csv"
HORIZONS = (3, 5, 8)


def metrics_for_horizon(trades: pd.DataFrame, horizon: int, cost: float) -> pd.DataFrame:
    """把已冻结选择映射到指定持有期的真实终点收益。"""

    result = trades.copy()
    result["holding_days"] = horizon
    result["net_ret"] = pd.to_numeric(result[f"ret_{horizon}d"], errors="coerce") - cost
    return result[result["net_ret"].notna()].copy()


def horizon_internal_summary(trades: pd.DataFrame, horizon: int) -> dict:
    """只使用 2019-2021 形成持有期选择统计。"""

    scoped = _period(metrics_for_horizon(trades, horizon, cost=0.25), 2019, 2021)
    yearly = scoped.groupby(scoped["trade_date"].str[:4].astype(int))["net_ret"].mean()
    metrics = _metrics(scoped)
    return {
        "horizon": horizon,
        **metrics,
        "worst_year_avg_net": float(yearly.min()) if len(yearly) else float("nan"),
        "eligible": bool(
            metrics["trades"] >= 60
            and metrics["positive_years"] == metrics["years"] == 3
            and metrics["profit_factor"] > 1.10
        ),
    }


def choose_horizon(summaries: list[dict]) -> int:
    """按预注册内部指标排序，绝不读取验证期字段。"""

    eligible = [item for item in summaries if item["eligible"]]
    if not eligible:
        raise RuntimeError("没有持有期通过内部 OOS 资格门槛")
    chosen = sorted(
        eligible,
        key=lambda item: (
            -item["worst_year_avg_net"],
            -item["avg_net"],
            -item["profit_factor"],
            item["horizon"],
        ),
    )[0]
    return int(chosen["horizon"])


def overlap_portfolio_horizon(
    trades: pd.DataFrame,
    cache_dir: Path,
    holding_days: int,
    cost: float,
) -> pd.DataFrame:
    """按指定交易日数展开重叠持仓路径，并在首尾各扣一半成本。"""

    daily_dir = cache_dir / "daily"
    calendar = sorted(path.stem for path in daily_dir.glob("*.parquet"))
    position = {date: index for index, date in enumerate(calendar)}
    contributions: dict[str, float] = {}
    frame_cache: dict[str, pd.Series] = {}
    for signal_date, cohort in trades.groupby("trade_date"):
        start = position.get(str(signal_date))
        if start is None:
            continue
        holding_dates = calendar[start + 1 : start + 1 + holding_days]
        if len(holding_dates) < holding_days:
            continue
        cohort = cohort.drop_duplicates("ts_code")
        previous = {
            str(row.ts_code): float(row.entry_open)
            for row in cohort.itertuples(index=False)
            if pd.notna(row.entry_open) and float(row.entry_open) > 0
        }
        for day_index, date in enumerate(holding_dates):
            if date not in frame_cache:
                try:
                    daily = pd.read_parquet(
                        daily_dir / f"{date}.parquet", columns=["ts_code", "close"]
                    )
                    frame_cache[date] = daily.set_index("ts_code")["close"]
                except Exception:
                    frame_cache[date] = pd.Series(dtype=float)
            close_map = frame_cache[date]
            stock_returns = []
            for code, prior_close in list(previous.items()):
                close = pd.to_numeric(
                    pd.Series([close_map.get(code)]), errors="coerce"
                ).iloc[0]
                if pd.isna(close) or prior_close <= 0:
                    continue
                daily_return = (float(close) / prior_close - 1) * 100
                if day_index in (0, holding_days - 1):
                    daily_return -= cost / 2
                stock_returns.append(daily_return)
                previous[code] = float(close)
            if stock_returns:
                contributions[date] = contributions.get(date, 0.0) + float(
                    np.mean(stock_returns)
                ) / holding_days
    result = pd.DataFrame(sorted(contributions.items()), columns=["trade_date", "net_ret"])
    if not result.empty:
        result["year"] = result["trade_date"].str[:4].astype(int)
    return result


def _yearly(trades: pd.DataFrame) -> pd.DataFrame:
    return (
        trades.groupby(trades["trade_date"].str[:4].astype(int))
        .apply(lambda group: pd.Series(_metrics(group)), include_groups=False)
        .reset_index(names="year")
    )


def run() -> dict:
    """冻结持有期后才评估验证期与组合压力。"""

    source = pd.read_csv(SOURCE, dtype={"trade_date": str})
    summaries = [horizon_internal_summary(source, horizon) for horizon in HORIZONS]
    chosen_horizon = choose_horizon(summaries)
    base = _period(metrics_for_horizon(source, chosen_horizon, cost=0.25), 2019, 2024)
    stress = _period(metrics_for_horizon(source, chosen_horizon, cost=0.50), 2019, 2024)
    validation = _metrics(_period(base, 2022, 2024))
    yearly = _yearly(base)
    days = _period(base.groupby("trade_date", as_index=False)["net_ret"].mean(), 2022, 2024)
    ci_low, ci_high, p_nonpositive = _bootstrap_probability(days, block=20, repetitions=10000)
    base_overlap = overlap_portfolio_horizon(base, CACHE, chosen_horizon, cost=0.25)
    stress_overlap = overlap_portfolio_horizon(stress, CACHE, chosen_horizon, cost=0.50)
    base_yearly = annual_path_metrics(base_overlap)
    stress_yearly = annual_path_metrics(stress_overlap)
    base_yearly = base_yearly[base_yearly["year"].between(2019, 2024)].copy()
    stress_yearly = stress_yearly[stress_yearly["year"].between(2019, 2024)].copy()
    base_drawdown = max_drawdown(base_overlap["net_ret"]) if not base_overlap.empty else float("nan")
    stress_drawdown = max_drawdown(stress_overlap["net_ret"]) if not stress_overlap.empty else float("nan")
    checks = {
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
    }
    result = {
        "research_id": RESEARCH_ID,
        "status": "six_year_confirmation_pass" if all(checks.values()) else "six_year_confirmation_failed",
        "internal_horizon_summaries": summaries,
        "chosen_horizon": chosen_horizon,
        "validation_metrics": validation,
        "yearly_metrics": yearly.to_dict(orient="records"),
        "bootstrap": {"ci_low": ci_low, "ci_high": ci_high, "p_nonpositive": p_nonpositive},
        "base_overlap_yearly": base_yearly.to_dict(orient="records"),
        "stress_overlap_yearly": stress_yearly.to_dict(orient="records"),
        "base_overlap_max_drawdown_pct": base_drawdown,
        "stress_overlap_max_drawdown_pct": stress_drawdown,
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
