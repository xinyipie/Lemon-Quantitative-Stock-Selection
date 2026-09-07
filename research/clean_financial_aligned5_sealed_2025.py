"""5日对齐候选在2025完整年度的一次性封存验证。"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.all_market_multi_engine_research import (  # noqa: E402
    _available_dates,
    _build_regimes,
    _load_stock_info,
    build_year_panel,
)
from research.audit_clean_financial_relative_candidate import max_drawdown, simulate_portfolio  # noqa: E402
from research.clean_financial_abstention import CANDIDATES, daily_top_with_margin  # noqa: E402
from research.clean_financial_event_hgb import (  # noqa: E402
    FEATURE_COLUMNS,
    FINANCIAL_CACHE,
    _bootstrap_probability,
    build_universe,
    metrics,
)
from research.clean_financial_horizon_alignment import fit_target_model  # noqa: E402
from research.clean_financial_relative_confidence import (  # noqa: E402
    apply_relative_gate,
    enforce_same_stock_cooldown,
    relative_thresholds,
)
from research.clean_financial_relative_validation import SLIM_COLUMNS, VALIDATION_UNIVERSE, _slim  # noqa: E402
from research.no_future_signal_pipeline import apply_next_open_execution  # noqa: E402
from research.point_in_time_financials import prepare_financial_events  # noqa: E402


PREREG = ROOT / "reports" / "research" / "prereg_clean_financial_aligned5_sealed_2025_20260808.json"
UNIVERSE_OUT = ROOT / "data" / "research" / "clean_financial_aligned5_sealed_2025.parquet"
TRADES_OUT = ROOT / "reports" / "research" / "clean_financial_aligned5_sealed_2025_trades_20260808.csv"
PORTFOLIO_OUT = ROOT / "reports" / "research" / "clean_financial_aligned5_sealed_2025_portfolio_20260808.csv"
REPORT_OUT = ROOT / "reports" / "research" / "clean_financial_aligned5_sealed_2025_20260808.md"
CACHE = ROOT / "data" / "cache"


def build_2025_universe() -> pd.DataFrame:
    events = prepare_financial_events(
        pd.read_parquet(FINANCIAL_CACHE), require_versioned_history=True
    )
    dates = _available_dates(CACHE, "20240101", "20260228")
    regimes = _build_regimes(CACHE, dates)
    stock_info = _load_stock_info(CACHE)
    panel = build_year_panel(CACHE, stock_info, regimes, dates, 2025, "20250101", "20251231")
    universe = _slim(build_universe(panel, events))
    UNIVERSE_OUT.parent.mkdir(parents=True, exist_ok=True)
    universe.to_parquet(UNIVERSE_OUT, index=False)
    print(f"sealed_2025_panel={len(panel)} universe={len(universe)}")
    return universe


def _profit_factor(values: pd.Series) -> float:
    gains = float(values.loc[values.gt(0)].sum())
    losses = float(-values.loc[values.lt(0)].sum())
    return gains / losses if losses > 0 else float("inf")


def run() -> None:
    prereg_hash = hashlib.sha256(PREREG.read_bytes()).hexdigest()
    print(f"prereg_sha256={prereg_hash}")
    training = pd.read_csv(CANDIDATES, usecols=SLIM_COLUMNS, low_memory=False)
    prior_validation = pd.read_parquet(VALIDATION_UNIVERSE, columns=SLIM_COLUMNS)
    target = build_2025_universe()
    history = pd.concat([training, prior_validation], ignore_index=True)
    years = history["trade_date"].astype(str).str[:4].astype(int)
    model_training = history.loc[years.le(2023)]
    calibration = history.loc[years.eq(2024)].copy()
    estimator = fit_target_model(
        model_training,
        5,
        prediction_start_date="20240101",
    )
    calibration["prediction"] = estimator.predict(calibration[FEATURE_COLUMNS])
    target["prediction"] = estimator.predict(target[FEATURE_COLUMNS])
    calibration_top = daily_top_with_margin(calibration)
    target_top = daily_top_with_margin(target)
    score_threshold, margin_threshold = relative_thresholds(calibration_top, 0.50, 0.0)
    gated = apply_relative_gate(target_top, score_threshold, margin_threshold)
    locked = enforce_same_stock_cooldown(
        gated,
        target_top["trade_date"].astype(str).unique().tolist(),
        cooldown_days=5,
    )
    trades = apply_next_open_execution(locked, cost=0.25, outcome_column="ret_5d")
    portfolio = simulate_portfolio(trades, slots=5, cost_pct=0.25, holding_days=5)

    base = metrics(trades)
    cutoff = float(trades["net_ret"].quantile(0.99))
    trimmed_average = float(trades.loc[trades["net_ret"].le(cutoff), "net_ret"].mean())
    daily = trades.groupby("trade_date", as_index=False)["net_ret"].mean()
    ci_low, ci_high, p_nonpositive = _bootstrap_probability(daily, block=20, repetitions=10000)
    portfolio_return = float((portfolio["nav"].iloc[-1] - 1.0) * 100.0)
    portfolio_dd = max_drawdown(portfolio["nav"])
    result: dict[str, object] = {
        **base,
        "trimmed_avg": trimmed_average,
        "stress_avg": float((trades["ret_5d"] - 0.50).mean()),
        "max_stock_share": float(trades["ts_code"].value_counts(normalize=True).max()),
        "max_industry_share": float(trades["industry"].value_counts(normalize=True).max()),
        "bootstrap_ci_low": ci_low,
        "bootstrap_ci_high": ci_high,
        "p_nonpositive": p_nonpositive,
        "portfolio_return": portfolio_return,
        "portfolio_max_drawdown": portfolio_dd,
        "score_threshold": score_threshold,
    }
    result["strict_pass"] = bool(
        result["trades"] >= 40
        and result["avg_net"] >= 0.45
        and result["profit_factor"] >= 1.20
        and result["trimmed_avg"] > 0
        and result["stress_avg"] > 0
        and result["max_stock_share"] <= 0.10
        and result["max_industry_share"] <= 0.25
        and result["bootstrap_ci_low"] > 0
        and result["p_nonpositive"] < 0.05
        and result["portfolio_return"] > 0
        and result["portfolio_max_drawdown"] >= -20.0
    )

    trades.to_csv(TRADES_OUT, index=False, encoding="utf-8-sig")
    portfolio.to_csv(PORTFOLIO_OUT, index=False, encoding="utf-8-sig")
    REPORT_OUT.write_text(
        "# 5日对齐候选 2025 封存验证\n\n"
        f"- 预注册 SHA-256：`{prereg_hash}`\n"
        "- 2025结果只打开一次；严格门槛失败后不得调参重测。\n"
        f"- 严格封存验证：`{'通过' if result['strict_pass'] else '不通过'}`\n\n"
        "```json\n"
        + json.dumps(result, ensure_ascii=False, indent=2)
        + "\n```\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    run()
