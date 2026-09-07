"""比较模型预测目标与实际持有期是否一致，仅运行训练段。"""

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

from research.clean_financial_abstention import (  # noqa: E402
    CANDIDATES,
    TARGET_YEARS,
    daily_top_with_margin,
)
from research.clean_financial_event_hgb import FEATURE_COLUMNS, MODEL_CONFIG, metrics  # noqa: E402
from research.clean_financial_relative_confidence import (  # noqa: E402
    apply_relative_gate,
    enforce_same_stock_cooldown,
    relative_thresholds,
)
from research.no_future_signal_pipeline import (  # noqa: E402
    apply_next_open_execution,
    assert_no_future_features,
)
from research.research_integrity import purge_overlapping_label_tail  # noqa: E402


PREREG = ROOT / "reports" / "research" / "prereg_clean_financial_horizon_alignment_20260808.json"
SUMMARY_OUT = ROOT / "reports" / "research" / "clean_financial_horizon_alignment_training_20260808.csv"
TRADES_OUT = ROOT / "reports" / "research" / "clean_financial_horizon_alignment_training_trades_20260808.csv"
REPORT_OUT = ROOT / "reports" / "research" / "clean_financial_horizon_alignment_training_20260808.md"

CONFIGURATIONS = ((3, 3), (5, 5), (8, 8), (5, 8))
USE_COLUMNS = [
    "ts_code", "name", "industry", "trade_date", "entry_open", "entry_gap_pct",
    "ret_3d", "ret_5d", "ret_8d", "label_exit_date_3d", "label_exit_date_5d",
    "label_exit_date_8d", *FEATURE_COLUMNS,
]


def fit_target_model(
    training: pd.DataFrame,
    target_days: int,
    *,
    prediction_start_date: str,
) -> HistGradientBoostingRegressor:
    training = purge_overlapping_label_tail(
        training,
        horizon=target_days,
        prediction_start_date=prediction_start_date,
    )
    assert_no_future_features(FEATURE_COLUMNS)
    target_column = f"ret_{target_days}d"
    target = pd.to_numeric(training[target_column], errors="coerce") - 0.25
    valid = target.notna()
    train = training.loc[valid]
    y = target.loc[valid].clip(-15.0, 15.0)
    counts = train.groupby("trade_date")["ts_code"].transform("size").clip(lower=1)
    weights = (1.0 / counts).to_numpy()
    weights = weights / weights.mean()
    estimator = HistGradientBoostingRegressor(**MODEL_CONFIG)
    estimator.fit(train[FEATURE_COLUMNS], y, sample_weight=weights)
    return estimator


def _predict_top(estimator, frame: pd.DataFrame) -> pd.DataFrame:
    scored = frame.copy()
    scored["prediction"] = estimator.predict(scored[FEATURE_COLUMNS])
    return daily_top_with_margin(scored)


def build_predictions(frame: pd.DataFrame) -> dict[tuple[int, int], tuple[pd.DataFrame, pd.DataFrame]]:
    years = frame["trade_date"].astype(str).str[:4].astype(int)
    result: dict[tuple[int, int], tuple[pd.DataFrame, pd.DataFrame]] = {}
    for model_days in (3, 5, 8):
        for target_year in TARGET_YEARS:
            training = frame.loc[years.le(target_year - 2)]
            calibration = frame.loc[years.eq(target_year - 1)]
            target = frame.loc[years.eq(target_year)]
            estimator = fit_target_model(
                training,
                model_days,
                prediction_start_date=f"{target_year - 1}0101",
            )
            result[(model_days, target_year)] = (
                _predict_top(estimator, calibration),
                _predict_top(estimator, target),
            )
            print(
                f"model_days={model_days} target_year={target_year} "
                f"train={len(training)} calibration={len(calibration)} target={len(target)}"
            )
    return result


def _profit_factor(values: pd.Series) -> float:
    gains = float(values.loc[values.gt(0)].sum())
    losses = float(-values.loc[values.lt(0)].sum())
    return gains / losses if losses > 0 else float("inf")


def _trimmed_average(trades: pd.DataFrame) -> float:
    cutoff = float(trades["net_ret"].quantile(0.99))
    return float(trades.loc[trades["net_ret"].le(cutoff), "net_ret"].mean())


def evaluate_configuration(
    predictions: dict[tuple[int, int], tuple[pd.DataFrame, pd.DataFrame]],
    model_days: int,
    hold_days: int,
) -> tuple[dict[str, object], pd.DataFrame]:
    frames: list[pd.DataFrame] = []
    for year in TARGET_YEARS:
        calibration_top, target_top = predictions[(model_days, year)]
        score_threshold, margin_threshold = relative_thresholds(calibration_top, 0.50, 0.0)
        gated = apply_relative_gate(target_top, score_threshold, margin_threshold)
        locked = enforce_same_stock_cooldown(
            gated,
            target_top["trade_date"].astype(str).unique().tolist(),
            cooldown_days=hold_days,
        )
        trades = apply_next_open_execution(
            locked,
            cost=0.25,
            outcome_column=f"ret_{hold_days}d",
        )
        trades["year"] = year
        frames.append(trades)
    combined = pd.concat(frames, ignore_index=True)
    base = metrics(combined)
    yearly = {
        str(int(year)): {
            "trades": int(len(group)),
            "avg_net": float(group["net_ret"].mean()),
            "profit_factor": float(_profit_factor(group["net_ret"])),
        }
        for year, group in combined.groupby("year")
    }
    row: dict[str, object] = {
        "config": f"model{model_days}_hold{hold_days}",
        "model_target_days": model_days,
        "holding_days": hold_days,
        **base,
        "trimmed_avg": _trimmed_average(combined),
        "stress_avg": float((combined[f"ret_{hold_days}d"] - 0.50).mean()),
        "year_metrics": json.dumps(yearly, ensure_ascii=False, sort_keys=True),
    }
    row["training_gate"] = bool(
        row["trades"] >= 120
        and len(yearly) == 3
        and min(item["trades"] for item in yearly.values()) >= 30
        and row["avg_net"] >= 0.45
        and row["profit_factor"] >= 1.20
        and min(item["avg_net"] for item in yearly.values()) >= 0.10
        and row["trimmed_avg"] > 0
        and row["stress_avg"] > 0
    )
    combined["config"] = row["config"]
    return row, combined


def run() -> None:
    print(f"prereg_sha256={hashlib.sha256(PREREG.read_bytes()).hexdigest()}")
    frame = pd.read_csv(CANDIDATES, usecols=USE_COLUMNS, low_memory=False)
    predictions = build_predictions(frame)
    rows: list[dict[str, object]] = []
    trades: list[pd.DataFrame] = []
    for model_days, hold_days in CONFIGURATIONS:
        row, config_trades = evaluate_configuration(predictions, model_days, hold_days)
        rows.append(row)
        trades.append(config_trades)
    summary = pd.DataFrame(rows).sort_values(["training_gate", "avg_net"], ascending=False)
    all_trades = pd.concat(trades, ignore_index=True)
    summary.to_csv(SUMMARY_OUT, index=False, encoding="utf-8-sig")
    all_trades.to_csv(TRADES_OUT, index=False, encoding="utf-8-sig")
    REPORT_OUT.write_text(
        "# 模型目标与持有期一致性研究\n\n"
        "- 仅使用2016-2021训练段，不读取新验证或近期结果。\n\n"
        + summary.to_markdown(index=False)
        + f"\n\n- 通过训练门槛：{summary.loc[summary['training_gate'], 'config'].tolist()}\n",
        encoding="utf-8",
    )
    print(summary.to_string(index=False))


if __name__ == "__main__":
    run()
