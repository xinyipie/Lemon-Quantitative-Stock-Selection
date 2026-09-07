"""横截面标准化置信度与同股冷却研究，仅运行训练段。"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.clean_financial_abstention import (  # noqa: E402
    CANDIDATES,
    TARGET_YEARS,
    build_walk_forward_predictions,
)
from research.clean_financial_event_hgb import metrics  # noqa: E402
from research.no_future_signal_pipeline import apply_next_open_execution  # noqa: E402


PREREG = ROOT / "reports" / "research" / "prereg_clean_financial_relative_confidence_20260808.json"
SUMMARY_OUT = ROOT / "reports" / "research" / "clean_financial_relative_confidence_training_20260808.csv"
TRADES_OUT = ROOT / "reports" / "research" / "clean_financial_relative_confidence_training_trades_20260808.csv"
REPORT_OUT = ROOT / "reports" / "research" / "clean_financial_relative_confidence_training_20260808.md"

SCORE_Z_QUANTILES = (0.50, 0.75)
MARGIN_Z_QUANTILES = (0.0, 0.50)
COOLDOWN_DAYS = 8


def relative_thresholds(
    calibration_top: pd.DataFrame,
    score_quantile: float,
    margin_quantile: float,
) -> tuple[float, float]:
    score_threshold = float(calibration_top["prediction_z"].dropna().quantile(score_quantile))
    if margin_quantile <= 0:
        return score_threshold, float("-inf")
    margin_threshold = float(calibration_top["prediction_margin_z"].dropna().quantile(margin_quantile))
    return score_threshold, margin_threshold


def apply_relative_gate(
    target_top: pd.DataFrame,
    score_threshold: float,
    margin_threshold: float,
) -> pd.DataFrame:
    return target_top.loc[
        target_top["prediction_z"].ge(score_threshold)
        & target_top["prediction_margin_z"].fillna(float("-inf")).ge(margin_threshold)
    ].copy()


def enforce_same_stock_cooldown(
    selected: pd.DataFrame,
    all_signal_dates: list[str],
    cooldown_days: int = COOLDOWN_DAYS,
) -> pd.DataFrame:
    """同一股票持有窗口内不重复建仓，被拦截时不递补。"""
    if selected.empty:
        return selected.copy()
    date_position = {str(date): index for index, date in enumerate(sorted(map(str, all_signal_dates)))}
    last_position: dict[str, int] = {}
    kept_indices: list[int] = []
    for index, row in selected.sort_values(["trade_date", "ts_code"]).iterrows():
        position = date_position[str(row["trade_date"])]
        code = str(row["ts_code"])
        previous = last_position.get(code)
        if previous is not None and position - previous < cooldown_days:
            continue
        kept_indices.append(index)
        last_position[code] = position
    return selected.loc[kept_indices].sort_values("trade_date").reset_index(drop=True)


def _profit_factor(values: pd.Series) -> float:
    gains = float(values.loc[values.gt(0)].sum())
    losses = float(-values.loc[values.lt(0)].sum())
    return gains / losses if losses > 0 else float("inf")


def _year_metrics(trades: pd.DataFrame) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    for year, group in trades.groupby("year"):
        result[str(int(year))] = {
            "trades": int(len(group)),
            "avg_net": float(group["net_ret"].mean()),
            "profit_factor": float(_profit_factor(group["net_ret"])),
        }
    return result


def _trimmed_average(trades: pd.DataFrame) -> float:
    if trades.empty:
        return 0.0
    cutoff = float(trades["net_ret"].quantile(0.99))
    return float(trades.loc[trades["net_ret"].le(cutoff), "net_ret"].mean())


def _maximum_share(trades: pd.DataFrame, column: str) -> float:
    if trades.empty:
        return 1.0
    return float(trades[column].value_counts(normalize=True).max())


def _gate(row: dict[str, object], yearly: dict[str, dict[str, float]]) -> bool:
    return bool(
        row["trades"] >= 120
        and len(yearly) == len(TARGET_YEARS)
        and min(item["trades"] for item in yearly.values()) >= 30
        and row["avg_net"] >= 0.45
        and row["profit_factor"] >= 1.20
        and min(item["avg_net"] for item in yearly.values()) >= 0.10
        and row["trimmed_avg"] > 0
        and row["stress_avg"] > 0
        and row["max_stock_share"] <= 0.10
        and row["max_industry_share"] <= 0.25
    )


def evaluate(predictions: dict[int, tuple[pd.DataFrame, pd.DataFrame]]) -> tuple[pd.DataFrame, pd.DataFrame]:
    summary_rows: list[dict[str, object]] = []
    trade_frames: list[pd.DataFrame] = []
    for score_quantile in SCORE_Z_QUANTILES:
        for margin_quantile in MARGIN_Z_QUANTILES:
            config = f"score_zq{int(score_quantile * 100)}_margin_zq{int(margin_quantile * 100)}"
            config_trades: list[pd.DataFrame] = []
            thresholds: dict[str, dict[str, float]] = {}
            for year, (calibration_top, target_top) in predictions.items():
                score_threshold, margin_threshold = relative_thresholds(
                    calibration_top,
                    score_quantile,
                    margin_quantile,
                )
                gated = apply_relative_gate(target_top, score_threshold, margin_threshold)
                locked = enforce_same_stock_cooldown(
                    gated,
                    target_top["trade_date"].astype(str).unique().tolist(),
                )
                trades = apply_next_open_execution(locked, cost=0.25, outcome_column="ret_8d")
                trades["year"] = year
                trades["config"] = config
                config_trades.append(trades)
                thresholds[str(year)] = {"score_z": score_threshold, "margin_z": margin_threshold}
            combined = pd.concat(config_trades, ignore_index=True) if config_trades else pd.DataFrame()
            base = metrics(combined)
            yearly = _year_metrics(combined)
            row: dict[str, object] = {
                "config": config,
                **base,
                "trimmed_avg": _trimmed_average(combined),
                "stress_avg": float((combined["ret_8d"] - 0.50).mean()) if not combined.empty else 0.0,
                "max_stock_share": _maximum_share(combined, "ts_code"),
                "max_industry_share": _maximum_share(combined, "industry"),
                "year_metrics": json.dumps(yearly, ensure_ascii=False, sort_keys=True),
                "thresholds": json.dumps(thresholds, ensure_ascii=False, sort_keys=True),
            }
            row["training_gate"] = _gate(row, yearly)
            summary_rows.append(row)
            trade_frames.append(combined)
    return pd.DataFrame(summary_rows), pd.concat(trade_frames, ignore_index=True)


def _write_report(summary: pd.DataFrame) -> None:
    ordered = summary.sort_values(["training_gate", "avg_net", "profit_factor"], ascending=False)
    lines = [
        "# 横截面标准化置信度与同股冷却研究",
        "",
        "- 仅使用 2016-2021 训练段；未读取独立验证与近期观察段。",
        "- 每日先锁定第一名；置信不足或同股8个信号日冷却时空仓，不递补。",
        "- 每年最少30笔，并限制单股与单行业集中度。",
        "",
        ordered.to_markdown(index=False),
        "",
        f"- 通过训练门槛的配置数：{int(ordered['training_gate'].sum())}",
    ]
    REPORT_OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run() -> None:
    print(f"prereg_sha256={hashlib.sha256(PREREG.read_bytes()).hexdigest()}")
    candidates = pd.read_csv(CANDIDATES, low_memory=False)
    predictions = build_walk_forward_predictions(candidates)
    summary, trades = evaluate(predictions)
    summary.to_csv(SUMMARY_OUT, index=False, encoding="utf-8-sig")
    trades.to_csv(TRADES_OUT, index=False, encoding="utf-8-sig")
    _write_report(summary)
    print(summary.sort_values(["training_gate", "avg_net"], ascending=False).to_string(index=False))
    print(f"selected={summary.loc[summary['training_gate'], 'config'].tolist()}")


if __name__ == "__main__":
    run()
