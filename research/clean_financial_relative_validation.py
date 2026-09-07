"""冻结横截面置信候选的2022-2024首次独立验证。"""

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
from research.audit_clean_financial_relative_candidate import (  # noqa: E402
    max_drawdown,
    simulate_portfolio,
)
from research.clean_financial_abstention import (  # noqa: E402
    CANDIDATES,
    daily_top_with_margin,
)
from research.clean_financial_event_hgb import (  # noqa: E402
    FEATURE_COLUMNS,
    FINANCIAL_CACHE,
    _bootstrap_probability,
    build_universe,
    fit_model,
    metrics,
)
from research.clean_financial_relative_confidence import (  # noqa: E402
    apply_relative_gate,
    enforce_same_stock_cooldown,
    relative_thresholds,
)
from research.no_future_signal_pipeline import apply_next_open_execution  # noqa: E402
from research.point_in_time_financials import prepare_financial_events  # noqa: E402


PREREG = ROOT / "reports" / "research" / "prereg_clean_financial_relative_validation_20260808.json"
VALIDATION_UNIVERSE = ROOT / "data" / "research" / "clean_financial_relative_validation_2022_2024.parquet"
TRADES_OUT = ROOT / "reports" / "research" / "clean_financial_relative_validation_trades_20260808.csv"
PORTFOLIO_OUT = ROOT / "reports" / "research" / "clean_financial_relative_validation_portfolio_20260808.csv"
REPORT_OUT = ROOT / "reports" / "research" / "clean_financial_relative_validation_20260808.md"
CACHE = ROOT / "data" / "cache"
TARGET_YEARS = (2022, 2023, 2024)

SLIM_COLUMNS = [
    "ts_code", "name", "industry", "trade_date", "entry_open", "entry_gap_pct", "ret_5d", "ret_8d",
    "label_exit_date_5d", "label_exit_date_8d",
    *FEATURE_COLUMNS,
]


def split_walk_forward(frame: pd.DataFrame, target_year: int) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    years = frame["trade_date"].astype(str).str[:4].astype(int)
    return (
        frame.loc[years.le(target_year - 2)].copy(),
        frame.loc[years.eq(target_year - 1)].copy(),
        frame.loc[years.eq(target_year)].copy(),
    )


def _slim(frame: pd.DataFrame) -> pd.DataFrame:
    missing = [column for column in SLIM_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"验证候选缺少字段: {missing}")
    return frame[SLIM_COLUMNS].copy()


def build_validation_universe() -> pd.DataFrame:
    financial_events = prepare_financial_events(
        pd.read_parquet(FINANCIAL_CACHE), require_versioned_history=True
    )
    dates = _available_dates(CACHE, "20210101", "20250131")
    regimes = _build_regimes(CACHE, dates)
    stock_info = _load_stock_info(CACHE)
    frames: list[pd.DataFrame] = []
    for year in TARGET_YEARS:
        panel = build_year_panel(CACHE, stock_info, regimes, dates, year, f"{year}0101", f"{year}1231")
        universe = _slim(build_universe(panel, financial_events))
        frames.append(universe)
        print(f"validation_universe_year={year} panel={len(panel)} universe={len(universe)}")
    combined = pd.concat(frames, ignore_index=True)
    VALIDATION_UNIVERSE.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(VALIDATION_UNIVERSE, index=False)
    return combined


def _predict_top(estimator, frame: pd.DataFrame) -> pd.DataFrame:
    scored = frame.copy()
    scored["prediction"] = estimator.predict(scored[FEATURE_COLUMNS])
    return daily_top_with_margin(scored)


def walk_forward_validate(frame: pd.DataFrame) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for target_year in TARGET_YEARS:
        training, calibration, target = split_walk_forward(frame, target_year)
        estimator = fit_model(
            training,
            prediction_start_date=f"{target_year - 1}0101",
        )
        calibration_top = _predict_top(estimator, calibration)
        target_top = _predict_top(estimator, target)
        score_threshold, margin_threshold = relative_thresholds(calibration_top, 0.50, 0.0)
        gated = apply_relative_gate(target_top, score_threshold, margin_threshold)
        locked = enforce_same_stock_cooldown(
            gated,
            target_top["trade_date"].astype(str).unique().tolist(),
            cooldown_days=8,
        )
        trades = apply_next_open_execution(locked, cost=0.25, outcome_column="ret_8d")
        trades["year"] = target_year
        frames.append(trades)
        print(
            f"validation_year={target_year} train={len(training)} calibration={len(calibration)} "
            f"target={len(target)} locked={len(locked)} trades={len(trades)} threshold={score_threshold:.6f}"
        )
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _profit_factor(values: pd.Series) -> float:
    gains = float(values.loc[values.gt(0)].sum())
    losses = float(-values.loc[values.lt(0)].sum())
    return gains / losses if losses > 0 else float("inf")


def _trimmed_average(trades: pd.DataFrame) -> float:
    cutoff = float(trades["net_ret"].quantile(0.99))
    return float(trades.loc[trades["net_ret"].le(cutoff), "net_ret"].mean())


def summarize(trades: pd.DataFrame, portfolio: pd.DataFrame) -> dict[str, object]:
    base = metrics(trades)
    yearly: dict[str, dict[str, float]] = {}
    for year, group in trades.groupby("year"):
        yearly[str(int(year))] = {
            "trades": int(len(group)),
            "avg_net": float(group["net_ret"].mean()),
            "profit_factor": float(_profit_factor(group["net_ret"])),
        }
    daily = trades.groupby("trade_date", as_index=False)["net_ret"].mean()
    ci_low, ci_high, p_nonpositive = _bootstrap_probability(daily, block=20, repetitions=10000)
    portfolio_dd = max_drawdown(portfolio["nav"])
    portfolio_return = float((portfolio["nav"].iloc[-1] - 1.0) * 100.0)
    result: dict[str, object] = {
        **base,
        "trimmed_avg": _trimmed_average(trades),
        "stress_avg": float((trades["ret_8d"] - 0.50).mean()),
        "max_stock_share": float(trades["ts_code"].value_counts(normalize=True).max()),
        "max_industry_share": float(trades["industry"].value_counts(normalize=True).max()),
        "bootstrap_ci_low": ci_low,
        "bootstrap_ci_high": ci_high,
        "p_nonpositive": p_nonpositive,
        "portfolio_return": portfolio_return,
        "portfolio_max_drawdown": portfolio_dd,
        "year_metrics": yearly,
    }
    result["strict_pass"] = bool(
        result["trades"] >= 120
        and len(yearly) == 3
        and min(item["trades"] for item in yearly.values()) >= 30
        and result["avg_net"] >= 0.45
        and result["profit_factor"] >= 1.20
        and min(item["avg_net"] for item in yearly.values()) >= 0.10
        and result["trimmed_avg"] > 0
        and result["stress_avg"] > 0
        and result["max_stock_share"] <= 0.10
        and result["max_industry_share"] <= 0.25
        and result["bootstrap_ci_low"] > 0
        and result["p_nonpositive"] < 0.05
        and result["portfolio_return"] > 0
        and result["portfolio_max_drawdown"] >= -20.0
    )
    return result


def run() -> None:
    prereg_hash = hashlib.sha256(PREREG.read_bytes()).hexdigest()
    print(f"prereg_sha256={prereg_hash}")
    training = pd.read_csv(CANDIDATES, usecols=SLIM_COLUMNS, low_memory=False)
    validation = build_validation_universe()
    combined = pd.concat([training, validation], ignore_index=True)
    trades = walk_forward_validate(combined)
    portfolio = simulate_portfolio(trades)
    result = summarize(trades, portfolio)
    trades.to_csv(TRADES_OUT, index=False, encoding="utf-8-sig")
    portfolio.to_csv(PORTFOLIO_OUT, index=False, encoding="utf-8-sig")
    lines = [
        "# 横截面标准化置信候选首次独立验证",
        "",
        f"- 预注册 SHA-256：`{prereg_hash}`",
        "- 参数在读取2022-2024结果前冻结；验证失败后不得修改参数重测同一区间。",
        "- 验证前勘误：模型预测5日净收益，冻结持有期为8日；勘误时尚未生成任何验证预测或收益。",
        f"- 严格验证：`{'通过' if result['strict_pass'] else '不通过'}`",
        "",
        "```json",
        json.dumps(result, ensure_ascii=False, indent=2),
        "```",
    ]
    REPORT_OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    run()
