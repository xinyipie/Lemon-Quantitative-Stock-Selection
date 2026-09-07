"""固定横截面置信候选的参数扰动与账户级逐日盯市审计。"""

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

from research.clean_financial_abstention import (  # noqa: E402
    CANDIDATES,
    build_walk_forward_predictions,
)
from research.clean_financial_event_hgb import metrics  # noqa: E402
from research.clean_financial_relative_confidence import (  # noqa: E402
    apply_relative_gate,
    enforce_same_stock_cooldown,
    relative_thresholds,
)
from research.no_future_signal_pipeline import apply_next_open_execution  # noqa: E402


PREREG = ROOT / "reports" / "research" / "prereg_clean_financial_relative_stress_20260808.json"
SUMMARY_OUT = ROOT / "reports" / "research" / "clean_financial_relative_stress_20260808.csv"
PORTFOLIO_OUT = ROOT / "reports" / "research" / "clean_financial_relative_portfolio_20260808.csv"
REPORT_OUT = ROOT / "reports" / "research" / "clean_financial_relative_stress_20260808.md"
CACHE = ROOT / "data" / "cache"

SCORE_QUANTILES = (0.40, 0.50, 0.60)
COOLDOWNS = (6, 8, 10)


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
        trades = apply_next_open_execution(locked, cost=0.25, outcome_column="ret_8d")
        trades["year"] = year
        frames.append(trades)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def perturbation_summary(trades: pd.DataFrame, score_quantile: float, cooldown_days: int) -> dict[str, object]:
    base = metrics(trades)
    yearly_average = trades.groupby("year")["net_ret"].mean().to_dict() if not trades.empty else {}
    passed = bool(
        base["trades"] >= 100
        and base["avg_net"] >= 0.20
        and base["profit_factor"] >= 1.05
        and len(yearly_average) == 3
        and min(yearly_average.values()) > 0
    )
    return {
        "score_quantile": score_quantile,
        "cooldown_days": cooldown_days,
        **base,
        "yearly_average": json.dumps({str(k): float(v) for k, v in yearly_average.items()}, sort_keys=True),
        "passed": passed,
    }


def max_drawdown(nav: pd.Series) -> float:
    if nav.empty:
        return 0.0
    return float((nav / nav.cummax() - 1.0).min() * 100.0)


def _daily_rows(path: Path, codes: set[str]) -> pd.DataFrame:
    if not path.exists() or not codes:
        return pd.DataFrame()
    frame = pd.read_parquet(path, columns=["ts_code", "open", "close", "pct_chg"])
    return frame.loc[frame["ts_code"].astype(str).isin(codes)].set_index("ts_code")


def simulate_portfolio(
    trades: pd.DataFrame,
    cache_dir: Path = CACHE,
    slots: int = 8,
    cost_pct: float = 0.25,
    holding_days: int = 8,
) -> pd.DataFrame:
    """最多每日一笔、固定槽位、逐日盯市，不把重叠交易当独立资金。"""
    if trades.empty:
        return pd.DataFrame(columns=["trade_date", "nav", "cash", "positions"])
    all_dates = sorted(path.stem for path in (cache_dir / "daily").glob("*.parquet"))
    date_position = {date: index for index, date in enumerate(all_dates)}
    entries: dict[str, list[dict[str, str]]] = {}
    last_exit_position = 0
    for row in trades.sort_values("trade_date").itertuples(index=False):
        signal_position = date_position[str(row.trade_date)]
        future_dates = all_dates[signal_position + 1 : signal_position + 1 + holding_days]
        if len(future_dates) < holding_days:
            continue
        entries.setdefault(future_dates[0], []).append(
            {"ts_code": str(row.ts_code), "exit_date": future_dates[-1]}
        )
        last_exit_position = max(last_exit_position, date_position[future_dates[-1]])

    first_entry = min(entries)
    simulation_dates = all_dates[date_position[first_entry] : last_exit_position + 1]
    cash = 1.0
    positions: list[dict[str, object]] = []
    rows: list[dict[str, object]] = []

    for date in simulation_dates:
        entering = entries.get(date, [])
        codes = {str(position["ts_code"]) for position in positions}
        codes.update(item["ts_code"] for item in entering)
        daily = _daily_rows(cache_dir / "daily" / f"{date}.parquet", codes)

        for position in positions:
            code = str(position["ts_code"])
            if code in daily.index:
                position["value"] = float(position["value"]) * (
                    1.0 + float(daily.loc[code, "pct_chg"]) / 100.0
                )

        nav_before_entry = cash + sum(float(position["value"]) for position in positions)
        for item in entering:
            code = item["ts_code"]
            if code not in daily.index:
                continue
            allocation = min(cash, nav_before_entry / slots)
            if allocation <= 0:
                continue
            cash -= allocation
            entry_factor = float(daily.loc[code, "close"]) / float(daily.loc[code, "open"])
            positions.append(
                {
                    "ts_code": code,
                    "exit_date": item["exit_date"],
                    "value": allocation * (1.0 - cost_pct / 100.0) * entry_factor,
                }
            )

        remaining: list[dict[str, object]] = []
        for position in positions:
            if str(position["exit_date"]) == date:
                cash += float(position["value"])
            else:
                remaining.append(position)
        positions = remaining
        nav = cash + sum(float(position["value"]) for position in positions)
        rows.append({"trade_date": date, "nav": nav, "cash": cash, "positions": len(positions)})
    return pd.DataFrame(rows)


def run() -> None:
    print(f"prereg_sha256={hashlib.sha256(PREREG.read_bytes()).hexdigest()}")
    candidates = pd.read_csv(CANDIDATES, low_memory=False)
    predictions = build_walk_forward_predictions(candidates)

    summaries: list[dict[str, object]] = []
    base_trades = pd.DataFrame()
    for score_quantile in SCORE_QUANTILES:
        for cooldown_days in COOLDOWNS:
            trades = select_trades(predictions, score_quantile, cooldown_days)
            summaries.append(perturbation_summary(trades, score_quantile, cooldown_days))
            if score_quantile == 0.50 and cooldown_days == 8:
                base_trades = trades

    summary = pd.DataFrame(summaries)
    portfolio = simulate_portfolio(base_trades)
    portfolio_dd = max_drawdown(portfolio["nav"])
    total_return = float((portfolio["nav"].iloc[-1] - 1.0) * 100.0) if not portfolio.empty else 0.0
    stress_pass = bool(summary["passed"].all() and portfolio_dd >= -20.0 and total_return > 0)

    summary.to_csv(SUMMARY_OUT, index=False, encoding="utf-8-sig")
    portfolio.to_csv(PORTFOLIO_OUT, index=False, encoding="utf-8-sig")
    lines = [
        "# 横截面置信候选压力测试",
        "",
        f"- 预注册 SHA-256：`{hashlib.sha256(PREREG.read_bytes()).hexdigest()}`",
        f"- 九组参数扰动全部通过：`{bool(summary['passed'].all())}`",
        f"- 8槽逐日盯市总收益：`{total_return:+.2f}%`",
        f"- 8槽逐日盯市最大回撤：`{portfolio_dd:.2f}%`",
        f"- 压力测试总门槛：`{stress_pass}`",
        "",
        summary.to_markdown(index=False),
    ]
    REPORT_OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(summary.to_string(index=False))
    print(f"portfolio_total_return={total_return:.4f} max_drawdown={portfolio_dd:.4f} stress_pass={stress_pass}")


if __name__ == "__main__":
    run()
