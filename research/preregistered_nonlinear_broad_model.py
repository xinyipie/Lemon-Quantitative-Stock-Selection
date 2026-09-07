#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""预注册的宽候选池非线性横截面模型及首次独立验证。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.all_market_multi_engine_research import (  # noqa: E402
    _available_dates,
    _build_regimes,
    _load_stock_info,
    build_year_panel,
)
from research.contrarian_candidate_stress import annual_path_metrics, max_drawdown  # noqa: E402
from research.high_confidence_abstention_audit import overlap_adjusted_portfolio  # noqa: E402
from research.two_stage_walkforward_research import _bootstrap_probability, _metrics, _period  # noqa: E402


CACHE = ROOT / "data" / "cache"
PREREG = ROOT / "reports" / "research" / "prereg_nonlinear_broad_model_20260808.json"
CANDIDATES = ROOT / "reports" / "research" / "nonlinear_broad_candidates_20260808.csv"
REPORT = ROOT / "reports" / "research" / "nonlinear_broad_validation_20260808.md"
FEATURE_COLUMNS = {
    "pct_chg",
    "ret_5",
    "ret_10",
    "ret_20",
    "ret_60",
    "drawdown_20",
    "rsi_14",
    "volatility_20",
    "turnover_rate",
    "volume_ratio",
    "industry_rs_20",
    "entry_gap_pct",
}
FORBIDDEN_COLUMNS = {"ret_3d", "ret_5d", "ret_8d", "mfe_8d", "mae_8d", "opportunity_score", "opportunity_rank"}
REGIMES = ("BULL_TREND", "BULL_PULLBACK", "BEAR_BOUNCE", "BEAR_TREND")


def build_broad_candidates(panel: pd.DataFrame, topn: int = 120, per_industry: int = 4) -> pd.DataFrame:
    """只按流动性构造宽候选池，收益标签不参与候选筛选。"""
    work = panel.copy()
    for column in ("history_count", "pct_chg", "turnover_rate", "volume_ratio", "entry_gap_pct", "amount"):
        work[column] = pd.to_numeric(work[column], errors="coerce")
    work["industry_bucket"] = work.get("industry", pd.Series(index=work.index, dtype=object)).fillna("未知行业").astype(str)
    mask = (
        work["tradeable"].astype(str).str.lower().isin(["true", "1"])
        & (work["history_count"] >= 120)
        & work["pct_chg"].between(-6.0, 8.0)
        & work["turnover_rate"].between(0.5, 15.0)
        & work["volume_ratio"].between(0.3, 3.0)
        & work["entry_gap_pct"].between(-5.0, 5.0)
        & work["amount"].gt(0)
        & work["industry_bucket"].ne("未知行业")
    )
    work = work[mask].copy()
    if work.empty:
        return work
    diversified = (
        work.sort_values(["trade_date", "industry_bucket", "amount", "ts_code"], ascending=[True, True, False, True])
        .groupby(["trade_date", "industry_bucket"], group_keys=False)
        .head(per_industry)
    )
    selected = (
        diversified.sort_values(["trade_date", "amount", "ts_code"], ascending=[True, False, True])
        .groupby("trade_date", group_keys=False)
        .head(topn)
        .drop_duplicates(["trade_date", "ts_code"])
        .copy()
    )
    return selected


def feature_frame(frame: pd.DataFrame, medians: pd.Series | None = None) -> tuple[pd.DataFrame, pd.Series]:
    columns = sorted(FEATURE_COLUMNS)
    numeric = frame.reindex(columns=columns).apply(pd.to_numeric, errors="coerce")
    if medians is None:
        medians = numeric.median().fillna(0.0)
    numeric = numeric.fillna(medians).fillna(0.0)
    regime = frame.get("regime", pd.Series("", index=frame.index)).astype(str)
    for value in REGIMES:
        numeric[f"regime_{value}"] = regime.eq(value).astype(float)
    return numeric, medians


def fit_model(train: pd.DataFrame) -> tuple[HistGradientBoostingRegressor, pd.Series]:
    x, medians = feature_frame(train)
    raw = pd.to_numeric(train["ret_5d"], errors="coerce").clip(-15.0, 15.0)
    target = raw - raw.groupby(train["trade_date"]).transform("mean")
    valid = target.notna()
    model = HistGradientBoostingRegressor(
        loss="absolute_error",
        learning_rate=0.05,
        max_iter=80,
        max_leaf_nodes=7,
        min_samples_leaf=100,
        l2_regularization=10.0,
        random_state=20260808,
    )
    model.fit(x.loc[valid], target.loc[valid])
    return model, medians


def predict(frame: pd.DataFrame, model: HistGradientBoostingRegressor, medians: pd.Series) -> pd.DataFrame:
    result = frame.copy()
    x, _ = feature_frame(result, medians)
    result["prediction"] = model.predict(x)
    return result


def confidence_topn(frame: pd.DataFrame, topn: int = 2) -> pd.DataFrame:
    rows = []
    for _, group in frame.groupby("trade_date"):
        prediction = pd.to_numeric(group["prediction"], errors="coerce")
        spread = float(prediction.std(ddof=0))
        median = float(prediction.median())
        selected = group.assign(prediction=prediction).sort_values(["prediction", "ts_code"], ascending=[False, True]).head(topn).copy()
        selected["confidence"] = (float(selected["prediction"].mean()) - median) / (spread if spread > 1e-12 else 1.0)
        rows.append(selected)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def internal_oos(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for test_year in (2019, 2020, 2021):
        train = frame[frame["year"] < test_year]
        test = frame[frame["year"].eq(test_year)]
        if train.empty or test.empty:
            continue
        model, medians = fit_model(train)
        rows.append(confidence_topn(predict(test, model, medians), topn=2))
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def prereg_hash() -> str:
    return hashlib.sha256(PREREG.read_bytes()).hexdigest()


def evaluate(frame: pd.DataFrame) -> None:
    work = frame.copy()
    work["trade_date"] = work["trade_date"].astype(str).str.replace("-", "", regex=False).str[:8]
    work["year"] = work["trade_date"].str[:4].astype(int)
    calibration = internal_oos(work[work["year"] <= 2021])
    threshold = float(calibration["confidence"].quantile(0.80))
    calibration_selected = calibration[calibration["confidence"] >= threshold].copy()
    calibration_selected["net_ret"] = pd.to_numeric(calibration_selected["ret_5d"], errors="coerce") - 0.25

    train = work[work["year"] <= 2021]
    future = work[work["year"] >= 2022]
    model, medians = fit_model(train)
    future_ranked = confidence_topn(predict(future, model, medians), topn=2)
    future_selected = future_ranked[future_ranked["confidence"] >= threshold].copy()
    future_selected["net_ret"] = pd.to_numeric(future_selected["ret_5d"], errors="coerce") - 0.25
    selected = pd.concat([calibration_selected, future_selected], ignore_index=True)

    train_metrics = _metrics(_period(selected, 2019, 2021))
    validation_metrics = _metrics(_period(selected, 2022, 2024))
    recent_metrics = _metrics(_period(selected, 2025, 2026))
    yearly = selected.groupby(selected["trade_date"].astype(str).str[:4].astype(int)).apply(
        lambda group: pd.Series(_metrics(group)), include_groups=False
    ).reset_index(names="year")
    validation_days = _period(selected.groupby("trade_date", as_index=False)["net_ret"].mean(), 2022, 2024)
    ci_low, ci_high, p_nonpositive = _bootstrap_probability(validation_days, block=20, repetitions=10000)
    overlap = overlap_adjusted_portfolio(selected, CACHE, cost=0.25)
    path_yearly = annual_path_metrics(overlap)
    path_drawdown = max_drawdown(overlap["net_ret"]) if not overlap.empty else float("nan")
    validation_path = path_yearly[path_yearly["year"].between(2022, 2024)]
    strict_pass = bool(
        validation_metrics["trades"] >= 100
        and validation_metrics["avg_net"] > 0
        and validation_metrics["profit_factor"] > 1.10
        and validation_metrics["positive_years"] == validation_metrics["years"] == 3
        and recent_metrics["trades"] >= 40
        and recent_metrics["avg_net"] > 0
        and recent_metrics["profit_factor"] > 1.10
        and recent_metrics["positive_years"] == recent_metrics["years"] == 2
        and ci_low > 0
        and p_nonpositive < 0.05
        and len(validation_path) == 3
        and (validation_path["return_pct"] > 0).all()
        and path_drawdown > -20.0
    )
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    selected.to_csv(REPORT.with_name(REPORT.stem + "_trades.csv"), index=False, encoding="utf-8-sig")
    overlap.to_csv(REPORT.with_name(REPORT.stem + "_portfolio_path.csv"), index=False, encoding="utf-8-sig")
    lines = [
        "# 预注册宽候选池非线性模型首次验证",
        "",
        f"- 预注册 SHA256：`{prereg_hash()}`。",
        f"- 内部OOS置信阈值：{threshold:.6f}。",
        f"- 严格首次验证：{'通过' if strict_pass else '不通过'}。",
        f"- 验证期 Bootstrap 95% 区间：{ci_low:+.4f}% 至 {ci_high:+.4f}%，均值不大于0概率 {p_nonpositive:.2%}。",
        f"- 真实重叠持仓最大回撤：{path_drawdown:.2f}%。",
        "",
        "## 分期结果",
        "",
        pd.DataFrame([{"period": "train_oos", **train_metrics}, {"period": "validation", **validation_metrics}, {"period": "recent", **recent_metrics}]).to_markdown(index=False, floatfmt=".4f"),
        "",
        "## 逐年结果",
        "",
        yearly.to_markdown(index=False, floatfmt=".4f"),
        "",
        "## 重叠持仓路径",
        "",
        path_yearly.to_markdown(index=False, floatfmt=".4f"),
        "",
        "- 最终模型只拟合2016-2021，2022-2026统一预测且不再训练。",
        "- v1首次验证后不得改参，失败结果必须原样保留。",
        "- 本研究未修改正式策略，也不生成交易执行代码。",
    ]
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"prereg_sha256={prereg_hash()} threshold={threshold:.6f} strict_pass={strict_pass}")
    print(pd.DataFrame([{"period": "train_oos", **train_metrics}, {"period": "validation", **validation_metrics}, {"period": "recent", **recent_metrics}]).to_string(index=False))
    print(yearly.to_string(index=False))
    print(f"bootstrap=({ci_low:.4f},{ci_high:.4f}) p_nonpositive={p_nonpositive:.4f} path_drawdown={path_drawdown:.2f}")
    print(f"wrote={REPORT}")


def run() -> None:
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    if not prereg.get("registered_before_validation"):
        raise RuntimeError("预注册文件无效")
    dates = _available_dates(CACHE, "20160101", "20260630")
    regimes = _build_regimes(CACHE, dates)
    stock_info = _load_stock_info(CACHE)
    frames = []
    for year in range(2016, 2027):
        panel = build_year_panel(CACHE, stock_info, regimes, dates, year, f"{year}0101", "20260630" if year == 2026 else f"{year}1231")
        candidates = build_broad_candidates(panel)
        frames.append(candidates)
        print(f"year={year} panel={len(panel)} candidates={len(candidates)}")
    result = pd.concat(frames, ignore_index=True)
    CANDIDATES.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(CANDIDATES, index=False, encoding="utf-8-sig")
    print(f"rows={len(result)} dates={result['trade_date'].nunique()} wrote={CANDIDATES}")
    evaluate(result)


if __name__ == "__main__":
    run()
