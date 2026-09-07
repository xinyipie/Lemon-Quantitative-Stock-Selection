#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""显式无未来字段的财务公告横截面模型。"""

from __future__ import annotations

import hashlib
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.all_market_multi_engine_research import _available_dates, _build_regimes, _load_stock_info, build_year_panel  # noqa: E402
from research.contrarian_candidate_stress import annual_path_metrics, max_drawdown  # noqa: E402
from research.high_confidence_abstention_audit import overlap_adjusted_portfolio  # noqa: E402
from research.no_future_signal_pipeline import (  # noqa: E402
    apply_next_open_execution,
    assert_no_future_features,
    lock_daily_topn,
    signal_eligible_mask,
)
from research.point_in_time_financials import merge_point_in_time, prepare_financial_events  # noqa: E402
from research.two_stage_walkforward_research import _bootstrap_probability  # noqa: E402


CACHE = ROOT / "data" / "cache"
FINANCIAL_CACHE = CACHE / "fina_indicator_history.parquet"
PREREG = ROOT / "reports" / "research" / "prereg_clean_financial_event_hgb_20260808.json"
CANDIDATES = ROOT / "reports" / "research" / "clean_financial_event_hgb_candidates_20260808.csv"
REPORT = ROOT / "reports" / "research" / "clean_financial_event_hgb_validation_20260808.md"
FEATURE_COLUMNS = [
    "pct_chg", "ret_5", "ret_10", "ret_20", "ret_60", "drawdown_20", "rsi_14", "volatility_20",
    "turnover_rate", "volume_ratio", "industry_rs_20", "roe", "debt_to_assets", "netprofit_yoy",
    "previous_netprofit_yoy", "profit_growth_delta", "days_since_announcement", "price_vs_ma20",
    "price_vs_ma60", "log_circ_mv", "report_quarter", "regime_code",
]
MODEL_CONFIG = {
    "learning_rate": 0.04,
    "max_iter": 120,
    "max_leaf_nodes": 15,
    "max_depth": 3,
    "min_samples_leaf": 100,
    "l2_regularization": 10.0,
    "max_bins": 128,
    "early_stopping": False,
    "random_state": 20260808,
}
REGIME_CODES = {"BEAR_TREND": 0, "BEAR_BOUNCE": 1, "BULL_PULLBACK": 2, "BULL_TREND": 3}


def build_universe(panel: pd.DataFrame, financial_events: pd.DataFrame) -> pd.DataFrame:
    work = merge_point_in_time(panel, financial_events)
    numeric = set(FEATURE_COLUMNS) | {
        "history_count", "close", "ma_20", "ma_60", "circ_mv", "entry_open", "entry_gap_pct", "ret_5d"
    }
    derived = {"price_vs_ma20", "price_vs_ma60", "log_circ_mv", "report_quarter", "regime_code"}
    for column in numeric - derived:
        if column not in work.columns:
            work[column] = np.nan
        work[column] = pd.to_numeric(work[column], errors="coerce")
    mask = (
        signal_eligible_mask(work, min_history=120)
        & work["days_since_announcement"].between(1, 45)
        & work["roe"].between(0.0, 80.0)
        & work["netprofit_yoy"].between(-100.0, 500.0)
        & work["debt_to_assets"].between(0.0, 100.0)
        & work["turnover_rate"].between(0.2, 25.0)
        & work["volume_ratio"].between(0.2, 5.0)
        & work["close"].ge(2.0)
    )
    work = work[mask].copy()
    work["price_vs_ma20"] = (work["close"] / work["ma_20"].replace(0, np.nan) - 1.0) * 100
    work["price_vs_ma60"] = (work["close"] / work["ma_60"].replace(0, np.nan) - 1.0) * 100
    work["log_circ_mv"] = np.log1p(work["circ_mv"].clip(lower=0))
    suffix = work["end_date"].astype(str).str[4:]
    work["report_quarter"] = suffix.map({"0331": 1, "0630": 2, "0930": 3, "1231": 4})
    work["regime_code"] = work["regime"].map(REGIME_CODES).fillna(-1)
    assert_no_future_features(FEATURE_COLUMNS)
    return work.sort_values(["trade_date", "ts_code"]).reset_index(drop=True)


def _model() -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(**MODEL_CONFIG)


def fit_model(training: pd.DataFrame) -> HistGradientBoostingRegressor:
    target = pd.to_numeric(training["ret_5d"], errors="coerce") - 0.25
    valid = target.notna()
    train = training.loc[valid].copy()
    y = target.loc[valid].clip(-15.0, 15.0)
    counts = train.groupby("trade_date")["ts_code"].transform("size").clip(lower=1)
    weights = (1.0 / counts).to_numpy()
    weights = weights / weights.mean()
    estimator = _model()
    estimator.fit(train[FEATURE_COLUMNS], y, sample_weight=weights)
    return estimator


def predict_and_execute(estimator: HistGradientBoostingRegressor, frame: pd.DataFrame, topn: int = 2, cost: float = 0.25) -> tuple[pd.DataFrame, pd.DataFrame]:
    scored = frame.copy()
    scored["prediction"] = estimator.predict(scored[FEATURE_COLUMNS])
    locked = lock_daily_topn(scored, "prediction", topn=topn)
    execution = apply_next_open_execution(locked, cost=cost, max_gap_pct=9.5)
    execution["net_ret"] = pd.to_numeric(execution["net_ret"], errors="coerce")
    trades = execution[execution["executed"]].copy()
    return trades, execution


def metrics(trades: pd.DataFrame) -> dict:
    if trades.empty:
        return {"trades": 0, "avg_net": 0.0, "win_rate": 0.0, "profit_factor": 0.0, "positive_years": 0, "years": 0}
    returns = pd.to_numeric(trades["net_ret"], errors="coerce").dropna()
    gains = float(returns[returns > 0].sum())
    losses = float(-returns[returns < 0].sum())
    years = trades["trade_date"].astype(str).str[:4]
    yearly = trades.assign(_year=years).groupby("_year")["net_ret"].mean()
    return {
        "trades": int(len(returns)),
        "avg_net": float(returns.mean()),
        "win_rate": float((returns > 0).mean()),
        "profit_factor": gains / losses if losses > 0 else float("inf"),
        "positive_years": int((yearly > 0).sum()),
        "years": int(len(yearly)),
    }


def training_walk_forward(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    trades = []
    executions = []
    years = frame["trade_date"].astype(str).str[:4].astype(int)
    for test_year in (2019, 2020, 2021):
        training = frame[(years >= 2016) & (years < test_year)]
        testing = frame[years == test_year]
        estimator = fit_model(training)
        year_trades, year_execution = predict_and_execute(estimator, testing)
        trades.append(year_trades)
        executions.append(year_execution)
        print(f"train_oos_year={test_year} train_rows={len(training)} signals={len(year_execution)} trades={len(year_trades)} metrics={metrics(year_trades)}")
    return pd.concat(trades, ignore_index=True), pd.concat(executions, ignore_index=True)


def _path_stats(trades: pd.DataFrame) -> tuple[pd.DataFrame, float]:
    overlap = overlap_adjusted_portfolio(trades, CACHE, cost=0.25)
    yearly = annual_path_metrics(overlap)
    drawdown = max_drawdown(overlap["net_ret"]) if not overlap.empty else float("nan")
    return yearly, drawdown


def run() -> None:
    prereg_hash = hashlib.sha256(PREREG.read_bytes()).hexdigest()
    print(f"prereg_sha256={prereg_hash}")
    assert_no_future_features(FEATURE_COLUMNS)
    financial_events = prepare_financial_events(pd.read_parquet(FINANCIAL_CACHE))
    dates = _available_dates(CACHE, "20160101", "20260807")
    regimes = _build_regimes(CACHE, dates)
    stock_info = _load_stock_info(CACHE)
    training_frames = []
    for year in range(2016, 2022):
        panel = build_year_panel(CACHE, stock_info, regimes, dates, year, f"{year}0101", f"{year}1231")
        universe = build_universe(panel, financial_events)
        training_frames.append(universe)
        print(f"training_year={year} panel={len(panel)} universe={len(universe)}")
    training = pd.concat(training_frames, ignore_index=True)
    training_path = CANDIDATES.with_name(CANDIDATES.stem + "_training_only.csv")
    training.to_csv(training_path, index=False, encoding="utf-8-sig")
    train_trades, train_execution = training_walk_forward(training)
    train = metrics(train_trades)
    train_path, train_drawdown = _path_stats(train_trades)
    train_pass = bool(
        train["trades"] >= 500 and train["avg_net"] > 0 and train["profit_factor"] > 1.10
        and train["positive_years"] == train["years"] == 3 and train_drawdown > -20.0
    )
    print(f"training_gate={train_pass} metrics={train} path_drawdown={train_drawdown:.2f}")
    if not train_pass:
        REPORT.write_text(
            f"# 干净财务公告横截面模型\n\n- 预注册 SHA256：`{prereg_hash}`。\n"
            f"- 训练期走步门槛未通过：`{train}`，重叠路径最大回撤 `{train_drawdown:.2f}%`。\n"
            "- 按预注册规则未生成或读取2022-2026候选收益。\n",
            encoding="utf-8",
        )
        train_trades.to_csv(REPORT.with_name(REPORT.stem + "_training_trades.csv"), index=False, encoding="utf-8-sig")
        print(f"training_failed wrote={REPORT}")
        return

    validation_frames = []
    for year in range(2022, 2027):
        end_date = "20260807" if year == 2026 else f"{year}1231"
        panel = build_year_panel(CACHE, stock_info, regimes, dates, year, f"{year}0101", end_date)
        universe = build_universe(panel, financial_events)
        validation_frames.append(universe)
        print(f"validation_year={year} panel={len(panel)} universe={len(universe)}")
    validation_all = pd.concat(validation_frames, ignore_index=True)
    all_candidates = pd.concat([training, validation_all], ignore_index=True)
    all_candidates.to_csv(CANDIDATES, index=False, encoding="utf-8-sig")
    frozen_model = fit_model(training)
    forward_trades, forward_execution = predict_and_execute(frozen_model, validation_all)
    forward_trades.to_csv(REPORT.with_name(REPORT.stem + "_trades.csv"), index=False, encoding="utf-8-sig")
    forward_execution.to_csv(REPORT.with_name(REPORT.stem + "_locked_signals.csv"), index=False, encoding="utf-8-sig")
    years = forward_trades["trade_date"].astype(str).str[:4].astype(int)
    validation_trades = forward_trades[years.between(2022, 2024)]
    recent_trades = forward_trades[years.between(2025, 2026)]
    validation = metrics(validation_trades)
    recent = metrics(recent_trades)
    validation_days = validation_trades.groupby("trade_date", as_index=False)["net_ret"].mean()
    ci_low, ci_high, p_nonpositive = _bootstrap_probability(validation_days, block=20, repetitions=10000)
    path_yearly, path_drawdown = _path_stats(forward_trades)
    validation_path = path_yearly[path_yearly["year"].between(2022, 2024)]
    strict_pass = bool(
        validation["trades"] >= 500 and validation["avg_net"] > 0 and validation["profit_factor"] > 1.10
        and validation["positive_years"] == validation["years"] == 3
        and recent["trades"] >= 200 and recent["avg_net"] > 0 and recent["profit_factor"] > 1.10
        and recent["positive_years"] == recent["years"] == 2
        and ci_low > 0 and p_nonpositive < 0.05 and len(validation_path) == 3
        and (validation_path["return_pct"] > 0).all() and path_drawdown > -20.0
    )
    yearly_rows = []
    for year, group in forward_trades.groupby(years):
        yearly_rows.append({"year": int(year), **metrics(group)})
    yearly = pd.DataFrame(yearly_rows)
    summary = pd.DataFrame([{"period": "train_oos", **train}, {"period": "validation", **validation}, {"period": "recent", **recent}])
    lines = [
        "# 干净财务公告横截面模型首次验证", "",
        f"- 预注册 SHA256：`{prereg_hash}`。", f"- 严格首次验证：{'通过' if strict_pass else '不通过'}。",
        "- 信号特征显式排除T+1开盘、跳空、tradeable和所有未来收益；Top2先锁定再判断成交，未成交不补位。",
        f"- 验证期 Bootstrap 95% 区间：{ci_low:+.4f}% 至 {ci_high:+.4f}%，均值不大于0概率 {p_nonpositive:.2%}。",
        f"- 2022-2026重叠路径最大回撤：{path_drawdown:.2f}%。", "",
        summary.to_markdown(index=False, floatfmt=".4f"), "", yearly.to_markdown(index=False, floatfmt=".4f"), "",
        path_yearly.to_markdown(index=False, floatfmt=".4f"), "",
        "- 首次验证后不得修改本模型参数重新测试同一验证期。", "- 未修改正式策略，不生成交易执行代码。",
    ]
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"strict_pass={strict_pass} validation={validation} recent={recent}")
    print(yearly.to_string(index=False))
    print(f"bootstrap=({ci_low:.4f},{ci_high:.4f}) p_nonpositive={p_nonpositive:.4f} path_drawdown={path_drawdown:.2f}")


if __name__ == "__main__":
    run()
