"""全市场横截面相对收益排名模型，仅运行2016-2021训练走步。"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.audit_clean_financial_relative_candidate import max_drawdown, simulate_portfolio  # noqa: E402
from research.clean_financial_abstention import daily_top_with_margin  # noqa: E402
from research.clean_financial_event_hgb import MODEL_CONFIG, metrics  # noqa: E402
from research.clean_financial_relative_confidence import enforce_same_stock_cooldown  # noqa: E402
from research.no_future_signal_pipeline import (  # noqa: E402
    apply_next_open_execution,
    assert_no_future_features,
)


PREREG = ROOT / "reports" / "research" / "prereg_clean_broad_cross_sectional_rank_20260808.json"
CLEAN_DIR = ROOT / "data" / "research" / "clean_all_market"
UNIVERSE_OUT = ROOT / "data" / "research" / "clean_broad_cross_sectional_rank_training.parquet"
SUMMARY_OUT = ROOT / "reports" / "research" / "clean_broad_cross_sectional_rank_training_20260808.csv"
TRADES_OUT = ROOT / "reports" / "research" / "clean_broad_cross_sectional_rank_training_trades_20260808.csv"
PORTFOLIO_OUT = ROOT / "reports" / "research" / "clean_broad_cross_sectional_rank_training_portfolio_20260808.csv"
REPORT_OUT = ROOT / "reports" / "research" / "clean_broad_cross_sectional_rank_training_20260808.md"

BASE_COLUMNS = [
    "ts_code", "name", "industry", "trade_date", "close", "amount", "history_count",
    "pct_chg", "ret_5", "ret_10", "ret_20", "ret_60", "ma_20", "ma_60", "drawdown_20",
    "rsi_14", "volatility_20", "turnover_rate", "volume_ratio", "industry_rs_20", "regime",
    "entry_open", "entry_gap_pct", "ret_5d",
]
RANK_SOURCES = [
    "pct_chg", "ret_5", "ret_10", "ret_20", "ret_60", "drawdown_20", "rsi_14",
    "volatility_20", "turnover_rate", "volume_ratio", "industry_rs_20", "amount",
    "price_vs_ma20", "price_vs_ma60",
]
FEATURE_COLUMNS = [f"rank_{column}" for column in RANK_SOURCES] + ["regime_code"]
REGIME_CODES = {"BEAR_TREND": 0, "BEAR_BOUNCE": 1, "BULL_PULLBACK": 2, "BULL_TREND": 3}
ALLOWED_REGIMES = {"BULL_TREND", "BULL_PULLBACK"}
TARGET_YEARS = (2018, 2019, 2020, 2021)


def prepare_year(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()
    numeric = set(BASE_COLUMNS) - {"ts_code", "name", "industry", "trade_date", "regime"}
    for column in numeric:
        work[column] = pd.to_numeric(work[column], errors="coerce")
    work = work.loc[
        work["history_count"].ge(120)
        & work["close"].ge(2.0)
        & work["amount"].gt(0)
        & work["turnover_rate"].between(0.2, 25.0)
        & work["volume_ratio"].between(0.2, 5.0)
    ].copy()
    work["price_vs_ma20"] = (work["close"] / work["ma_20"].replace(0, np.nan) - 1.0) * 100.0
    work["price_vs_ma60"] = (work["close"] / work["ma_60"].replace(0, np.nan) - 1.0) * 100.0
    grouped = work.groupby("trade_date")
    for column in RANK_SOURCES:
        work[f"rank_{column}"] = grouped[column].rank(method="average", pct=True)
    work["target_rank_5d"] = grouped["ret_5d"].rank(method="average", pct=True)
    work["regime_code"] = work["regime"].map(REGIME_CODES).fillna(-1)
    assert_no_future_features(FEATURE_COLUMNS)
    return work[
        [
            "ts_code", "name", "industry", "trade_date", "regime", "entry_open", "entry_gap_pct",
            "ret_5d", "target_rank_5d", *FEATURE_COLUMNS,
        ]
    ].dropna(subset=["target_rank_5d", *FEATURE_COLUMNS]).reset_index(drop=True)


def build_training_universe() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for year in range(2016, 2022):
        frame = pd.read_parquet(CLEAN_DIR / f"{year}.parquet", columns=BASE_COLUMNS)
        prepared = prepare_year(frame)
        frames.append(prepared)
        print(f"year={year} raw={len(frame)} prepared={len(prepared)}")
    combined = pd.concat(frames, ignore_index=True)
    combined.to_parquet(UNIVERSE_OUT, index=False)
    return combined


def fit_rank_model(training: pd.DataFrame) -> HistGradientBoostingRegressor:
    counts = training.groupby("trade_date")["ts_code"].transform("size").clip(lower=1)
    weights = (1.0 / counts).to_numpy()
    weights = weights / weights.mean()
    estimator = HistGradientBoostingRegressor(**MODEL_CONFIG)
    estimator.fit(training[FEATURE_COLUMNS], training["target_rank_5d"], sample_weight=weights)
    return estimator


def walk_forward(frame: pd.DataFrame) -> pd.DataFrame:
    years = frame["trade_date"].astype(str).str[:4].astype(int)
    frames: list[pd.DataFrame] = []
    for target_year in TARGET_YEARS:
        training = frame.loc[years.lt(target_year)]
        target = frame.loc[years.eq(target_year) & frame["regime"].isin(ALLOWED_REGIMES)].copy()
        estimator = fit_rank_model(training)
        target["prediction"] = estimator.predict(target[FEATURE_COLUMNS])
        top = daily_top_with_margin(target)
        locked = enforce_same_stock_cooldown(
            top,
            target["trade_date"].astype(str).unique().tolist(),
            cooldown_days=5,
        )
        trades = apply_next_open_execution(locked, cost=0.25, outcome_column="ret_5d")
        trades["year"] = target_year
        frames.append(trades)
        print(
            f"target_year={target_year} train={len(training)} eligible_days={target['trade_date'].nunique()} "
            f"locked={len(locked)} trades={len(trades)}"
        )
    return pd.concat(frames, ignore_index=True)


def _profit_factor(values: pd.Series) -> float:
    gains = float(values.loc[values.gt(0)].sum())
    losses = float(-values.loc[values.lt(0)].sum())
    return gains / losses if losses > 0 else float("inf")


def summarize(trades: pd.DataFrame, portfolio: pd.DataFrame) -> dict[str, object]:
    base = metrics(trades)
    yearly = {
        str(int(year)): {
            "trades": int(len(group)),
            "avg_net": float(group["net_ret"].mean()),
            "profit_factor": float(_profit_factor(group["net_ret"])),
        }
        for year, group in trades.groupby("year")
    }
    cutoff = float(trades["net_ret"].quantile(0.99))
    result: dict[str, object] = {
        **base,
        "trimmed_avg": float(trades.loc[trades["net_ret"].le(cutoff), "net_ret"].mean()),
        "stress_avg": float((trades["ret_5d"] - 0.50).mean()),
        "portfolio_return": float((portfolio["nav"].iloc[-1] - 1.0) * 100.0),
        "portfolio_max_drawdown": max_drawdown(portfolio["nav"]),
        "year_metrics": yearly,
    }
    result["training_gate"] = bool(
        result["trades"] >= 300
        and len(yearly) == len(TARGET_YEARS)
        and min(item["trades"] for item in yearly.values()) >= 20
        and result["avg_net"] >= 0.35
        and result["profit_factor"] >= 1.15
        and min(item["avg_net"] for item in yearly.values()) > 0
        and result["trimmed_avg"] > 0
        and result["stress_avg"] > 0
        and result["portfolio_return"] > 0
        and result["portfolio_max_drawdown"] >= -20.0
    )
    return result


def run() -> None:
    prereg_hash = hashlib.sha256(PREREG.read_bytes()).hexdigest()
    print(f"prereg_sha256={prereg_hash}")
    universe = build_training_universe()
    trades = walk_forward(universe)
    portfolio = simulate_portfolio(trades, slots=5, cost_pct=0.25, holding_days=5)
    result = summarize(trades, portfolio)
    SUMMARY_OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    trades.to_csv(TRADES_OUT, index=False, encoding="utf-8-sig")
    portfolio.to_csv(PORTFOLIO_OUT, index=False, encoding="utf-8-sig")
    REPORT_OUT.write_text(
        "# 全市场横截面相对收益排名训练走步\n\n"
        f"- 预注册 SHA-256：`{prereg_hash}`\n"
        f"- 训练门槛：`{'通过' if result['training_gate'] else '不通过'}`\n\n"
        "```json\n"
        + json.dumps(result, ensure_ascii=False, indent=2)
        + "\n```\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    run()
