"""点时财务横截面模型的高置信弃权研究，仅运行训练段。"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.clean_financial_event_hgb import FEATURE_COLUMNS, fit_model, metrics
from research.no_future_signal_pipeline import apply_next_open_execution, assert_no_future_features


PREREG = ROOT / "reports" / "research" / "prereg_clean_financial_abstention_20260808.json"
CANDIDATES = ROOT / "reports" / "research" / "clean_financial_event_hgb_candidates_20260808_training_only.csv"
SUMMARY_OUT = ROOT / "reports" / "research" / "clean_financial_abstention_training_20260808.csv"
TRADES_OUT = ROOT / "reports" / "research" / "clean_financial_abstention_training_trades_20260808.csv"
REPORT_OUT = ROOT / "reports" / "research" / "clean_financial_abstention_training_20260808.md"

SCORE_QUANTILES = (0.75, 0.90)
MARGIN_QUANTILES = (0.0, 0.50)
TARGET_YEARS = (2019, 2020, 2021)


def daily_top_with_margin(frame: pd.DataFrame, score_column: str = "prediction") -> pd.DataFrame:
    """每天先锁定第一名，并记录第一名相对第二名的预测优势。"""
    if frame.empty:
        return frame.copy()
    ordered = frame.sort_values(
        ["trade_date", score_column, "ts_code"],
        ascending=[True, False, True],
    ).copy()
    ordered["daily_rank"] = ordered.groupby("trade_date").cumcount() + 1
    grouped_score = ordered.groupby("trade_date")[score_column]
    ordered["daily_prediction_mean"] = grouped_score.transform("mean")
    ordered["daily_prediction_std"] = grouped_score.transform("std").replace(0, np.nan)
    ordered["prediction_z"] = (
        (ordered[score_column] - ordered["daily_prediction_mean"]) / ordered["daily_prediction_std"]
    )
    second = (
        ordered.loc[ordered["daily_rank"].eq(2), ["trade_date", score_column]]
        .rename(columns={score_column: "second_prediction"})
    )
    top = ordered.loc[ordered["daily_rank"].eq(1)].merge(second, on="trade_date", how="left")
    top["prediction_margin"] = top[score_column] - top["second_prediction"]
    top["prediction_margin_z"] = top["prediction_margin"] / top["daily_prediction_std"]
    return top.reset_index(drop=True)


def calibration_thresholds(
    calibration_top: pd.DataFrame,
    score_quantile: float,
    margin_quantile: float,
) -> tuple[float, float]:
    """阈值只由目标年前一年的逐日第一名分布产生。"""
    score_threshold = float(calibration_top["prediction"].quantile(score_quantile))
    if margin_quantile <= 0:
        return score_threshold, float("-inf")
    margin_threshold = float(calibration_top["prediction_margin"].dropna().quantile(margin_quantile))
    return score_threshold, margin_threshold


def apply_confidence_gate(
    target_top: pd.DataFrame,
    score_threshold: float,
    margin_threshold: float,
) -> pd.DataFrame:
    """只过滤已经锁定的第一名，不允许低排名股票递补。"""
    return target_top.loc[
        target_top["prediction"].ge(score_threshold)
        & target_top["prediction_margin"].fillna(float("-inf")).ge(margin_threshold)
    ].copy()


def _predict(estimator, frame: pd.DataFrame) -> pd.DataFrame:
    scored = frame.copy()
    scored["prediction"] = estimator.predict(scored[FEATURE_COLUMNS])
    return scored


def build_walk_forward_predictions(frame: pd.DataFrame) -> dict[int, tuple[pd.DataFrame, pd.DataFrame]]:
    assert_no_future_features(FEATURE_COLUMNS)
    work = frame.copy()
    work["year"] = work["trade_date"].astype(str).str[:4].astype(int)
    result: dict[int, tuple[pd.DataFrame, pd.DataFrame]] = {}
    for target_year in TARGET_YEARS:
        calibration_year = target_year - 1
        training = work.loc[work["year"].le(target_year - 2)].copy()
        calibration = work.loc[work["year"].eq(calibration_year)].copy()
        target = work.loc[work["year"].eq(target_year)].copy()
        estimator = fit_model(
            training,
            prediction_start_date=f"{calibration_year}0101",
        )
        result[target_year] = (
            daily_top_with_margin(_predict(estimator, calibration)),
            daily_top_with_margin(_predict(estimator, target)),
        )
        print(
            f"target={target_year} train={len(training)} "
            f"calibration_days={calibration['trade_date'].nunique()} target_days={target['trade_date'].nunique()}"
        )
    return result


def _trimmed_average(trades: pd.DataFrame) -> float:
    if trades.empty:
        return 0.0
    cutoff = float(trades["net_ret"].quantile(0.99))
    return float(trades.loc[trades["net_ret"].le(cutoff), "net_ret"].mean())


def _gate(row: dict[str, object]) -> bool:
    return bool(
        row["trades"] >= 150
        and row["avg_net"] >= 0.45
        and row["profit_factor"] >= 1.20
        and row["positive_years"] == 3
        and row["trimmed_avg"] > 0
        and row["stress_avg"] > 0
    )


def evaluate(predictions: dict[int, tuple[pd.DataFrame, pd.DataFrame]]) -> tuple[pd.DataFrame, pd.DataFrame]:
    summary_rows: list[dict[str, object]] = []
    trade_frames: list[pd.DataFrame] = []
    for score_quantile in SCORE_QUANTILES:
        for margin_quantile in MARGIN_QUANTILES:
            config = f"score_q{int(score_quantile * 100)}_margin_q{int(margin_quantile * 100)}"
            config_trades: list[pd.DataFrame] = []
            thresholds: dict[str, dict[str, float]] = {}
            for year, (calibration_top, target_top) in predictions.items():
                score_threshold, margin_threshold = calibration_thresholds(
                    calibration_top,
                    score_quantile,
                    margin_quantile,
                )
                locked = apply_confidence_gate(target_top, score_threshold, margin_threshold)
                trades = apply_next_open_execution(locked, cost=0.25, outcome_column="ret_8d")
                trades["year"] = year
                trades["config"] = config
                config_trades.append(trades)
                thresholds[str(year)] = {
                    "score": score_threshold,
                    "margin": margin_threshold,
                }
            combined = pd.concat(config_trades, ignore_index=True) if config_trades else pd.DataFrame()
            base = metrics(combined)
            stress_avg = float((combined["ret_8d"] - 0.50).mean()) if not combined.empty else 0.0
            row: dict[str, object] = {
                "config": config,
                **base,
                "trimmed_avg": _trimmed_average(combined),
                "stress_avg": stress_avg,
                "thresholds": json.dumps(thresholds, ensure_ascii=False, sort_keys=True),
            }
            row["training_gate"] = _gate(row)
            summary_rows.append(row)
            trade_frames.append(combined)
    return pd.DataFrame(summary_rows), pd.concat(trade_frames, ignore_index=True)


def _write_report(summary: pd.DataFrame) -> None:
    ordered = summary.sort_values(["training_gate", "avg_net", "profit_factor"], ascending=False)
    lines = [
        "# 点时财务模型高置信弃权研究",
        "",
        "- 仅使用 2016-2021 训练段；未读取独立验证与近期观察段。",
        "- 每个目标年的模型只拟合到前两年，前一年仅校准分数与领先幅度阈值。",
        "- 每日先锁定第一名，再执行置信过滤；T+1 不可成交时不递补。",
        "",
        ordered.to_markdown(index=False),
        "",
        f"- 通过训练门槛的配置数：{int(ordered['training_gate'].sum())}",
    ]
    REPORT_OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run() -> None:
    prereg_hash = hashlib.sha256(PREREG.read_bytes()).hexdigest()
    print(f"prereg_sha256={prereg_hash}")
    candidates = pd.read_csv(CANDIDATES, low_memory=False)
    predictions = build_walk_forward_predictions(candidates)
    summary, trades = evaluate(predictions)
    SUMMARY_OUT.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(SUMMARY_OUT, index=False, encoding="utf-8-sig")
    trades.to_csv(TRADES_OUT, index=False, encoding="utf-8-sig")
    _write_report(summary)
    print(summary.sort_values(["training_gate", "avg_net"], ascending=False).to_string(index=False))
    print(f"selected={summary.loc[summary['training_gate'], 'config'].tolist()}")


if __name__ == "__main__":
    run()
