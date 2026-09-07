"""5日目标与5日持有候选的训练段参数扰动和账户压力测试。"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.audit_clean_financial_relative_candidate import (  # noqa: E402
    max_drawdown,
    simulate_portfolio,
)
from research.clean_financial_abstention import CANDIDATES, TARGET_YEARS, daily_top_with_margin  # noqa: E402
from research.clean_financial_event_hgb import FEATURE_COLUMNS, metrics  # noqa: E402
from research.clean_financial_horizon_alignment import fit_target_model  # noqa: E402
from research.clean_financial_relative_confidence import (  # noqa: E402
    apply_relative_gate,
    enforce_same_stock_cooldown,
    relative_thresholds,
)
from research.no_future_signal_pipeline import apply_next_open_execution  # noqa: E402


PREREG = ROOT / "reports" / "research" / "prereg_clean_financial_aligned5_stress_20260808.json"
SUMMARY_OUT = ROOT / "reports" / "research" / "clean_financial_aligned5_stress_20260808.csv"
PORTFOLIO_OUT = ROOT / "reports" / "research" / "clean_financial_aligned5_portfolio_20260808.csv"
REPORT_OUT = ROOT / "reports" / "research" / "clean_financial_aligned5_stress_20260808.md"
SCORE_QUANTILES = (0.40, 0.50, 0.60)
COOLDOWNS = (4, 5, 6)
USE_COLUMNS = [
    "ts_code", "name", "industry", "trade_date", "entry_open", "entry_gap_pct", "ret_5d",
    *FEATURE_COLUMNS,
]


def build_predictions(frame: pd.DataFrame) -> dict[int, tuple[pd.DataFrame, pd.DataFrame]]:
    years = frame["trade_date"].astype(str).str[:4].astype(int)
    result: dict[int, tuple[pd.DataFrame, pd.DataFrame]] = {}
    for target_year in TARGET_YEARS:
        training = frame.loc[years.le(target_year - 2)]
        calibration = frame.loc[years.eq(target_year - 1)].copy()
        target = frame.loc[years.eq(target_year)].copy()
        estimator = fit_target_model(training, 5)
        calibration["prediction"] = estimator.predict(calibration[FEATURE_COLUMNS])
        target["prediction"] = estimator.predict(target[FEATURE_COLUMNS])
        result[target_year] = (daily_top_with_margin(calibration), daily_top_with_margin(target))
    return result


def select_trades(
    predictions: dict[int, tuple[pd.DataFrame, pd.DataFrame]],
    score_quantile: float,
    cooldown_days: int,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for year, (calibration_top, target_top) in predictions.items():
        score_threshold, margin_threshold = relative_thresholds(calibration_top, score_quantile, 0.0)
        gated = apply_relative_gate(target_top, score_threshold, margin_threshold)
        locked = enforce_same_stock_cooldown(
            gated,
            target_top["trade_date"].astype(str).unique().tolist(),
            cooldown_days=cooldown_days,
        )
        trades = apply_next_open_execution(locked, cost=0.25, outcome_column="ret_5d")
        trades["year"] = year
        frames.append(trades)
    return pd.concat(frames, ignore_index=True)


def _summary(trades: pd.DataFrame, score_quantile: float, cooldown_days: int) -> dict[str, object]:
    base = metrics(trades)
    yearly = trades.groupby("year")["net_ret"].mean().to_dict()
    passed = bool(
        base["trades"] >= 120
        and base["avg_net"] >= 0.20
        and base["profit_factor"] >= 1.05
        and len(yearly) == 3
        and min(yearly.values()) > 0
    )
    return {
        "score_quantile": score_quantile,
        "cooldown_days": cooldown_days,
        **base,
        "yearly_average": json.dumps({str(k): float(v) for k, v in yearly.items()}, sort_keys=True),
        "passed": passed,
    }


def run() -> None:
    prereg_hash = hashlib.sha256(PREREG.read_bytes()).hexdigest()
    print(f"prereg_sha256={prereg_hash}")
    frame = pd.read_csv(CANDIDATES, usecols=USE_COLUMNS, low_memory=False)
    predictions = build_predictions(frame)
    rows: list[dict[str, object]] = []
    base_trades = pd.DataFrame()
    for score_quantile in SCORE_QUANTILES:
        for cooldown_days in COOLDOWNS:
            trades = select_trades(predictions, score_quantile, cooldown_days)
            rows.append(_summary(trades, score_quantile, cooldown_days))
            if score_quantile == 0.50 and cooldown_days == 5:
                base_trades = trades
    summary = pd.DataFrame(rows)
    portfolio = simulate_portfolio(base_trades, slots=5, cost_pct=0.25, holding_days=5)
    portfolio_return = float((portfolio["nav"].iloc[-1] - 1.0) * 100.0)
    portfolio_dd = max_drawdown(portfolio["nav"])
    strict_pass = bool(summary["passed"].all() and portfolio_return > 0 and portfolio_dd >= -20.0)
    summary.to_csv(SUMMARY_OUT, index=False, encoding="utf-8-sig")
    portfolio.to_csv(PORTFOLIO_OUT, index=False, encoding="utf-8-sig")
    REPORT_OUT.write_text(
        "# 5日对齐候选训练压力测试\n\n"
        f"- 预注册 SHA-256：`{prereg_hash}`\n"
        f"- 九组参数扰动全部通过：`{bool(summary['passed'].all())}`\n"
        f"- 5槽账户总收益：`{portfolio_return:+.2f}%`\n"
        f"- 5槽账户最大回撤：`{portfolio_dd:.2f}%`\n"
        f"- 严格压力门槛：`{strict_pass}`\n\n"
        + summary.to_markdown(index=False)
        + "\n",
        encoding="utf-8",
    )
    print(summary.to_string(index=False))
    print(f"portfolio_return={portfolio_return:.4f} max_drawdown={portfolio_dd:.4f} strict_pass={strict_pass}")


if __name__ == "__main__":
    run()
