#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""固定逆向候选相对沪深300的同日期增量价值审计。"""

from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.contrarian_candidate_stress import max_drawdown  # noqa: E402
from research.two_stage_walkforward_research import _bootstrap_probability, _metrics, _period  # noqa: E402


INPUT = ROOT / "reports" / "research" / "contrarian_candidate_stress_20260808_trades.csv"
OUTPUT = ROOT / "reports" / "research" / "contrarian_incremental_alpha_20260808.md"
INDEX_DIR = ROOT / "data" / "cache" / "index_daily"


def holding_return(entry_open: float, exit_close: float) -> float | None:
    if entry_open is None or exit_close is None or entry_open <= 0:
        return None
    return (float(exit_close) / float(entry_open) - 1.0) * 100.0


def load_csi300_holding_returns(signal_dates: list[str], index_dir: Path = INDEX_DIR) -> pd.DataFrame:
    calendar = sorted(path.stem for path in index_dir.glob("*.parquet"))
    positions = {date: index for index, date in enumerate(calendar)}
    cache: dict[str, tuple[float | None, float | None]] = {}

    def prices(date: str) -> tuple[float | None, float | None]:
        if date in cache:
            return cache[date]
        try:
            frame = pd.read_parquet(index_dir / f"{date}.parquet", columns=["ts_code", "open", "close"])
            row = frame[frame["ts_code"].astype(str).eq("000300.SH")]
            if row.empty:
                cache[date] = (None, None)
            else:
                cache[date] = (float(row.iloc[0]["open"]), float(row.iloc[0]["close"]))
        except Exception:
            cache[date] = (None, None)
        return cache[date]

    rows = []
    for signal_date in sorted(set(str(date)[:8] for date in signal_dates)):
        start = positions.get(signal_date)
        if start is None or start + 5 >= len(calendar):
            continue
        entry_date = calendar[start + 1]
        exit_date = calendar[start + 5]
        entry_open, _ = prices(entry_date)
        _, exit_close = prices(exit_date)
        result = holding_return(entry_open, exit_close)
        if result is not None:
            rows.append(
                {
                    "trade_date": signal_date,
                    "benchmark_entry_date": entry_date,
                    "benchmark_exit_date": exit_date,
                    "benchmark_ret": result,
                }
            )
    return pd.DataFrame(rows)


def run(input_path: Path = INPUT, output: Path = OUTPUT) -> None:
    trades = pd.read_csv(input_path, encoding="utf-8-sig", low_memory=False)
    trades["trade_date"] = trades["trade_date"].astype(str).str.replace("-", "", regex=False).str[:8]
    strategy_days = trades.groupby("trade_date", as_index=False)["net_ret"].mean().rename(columns={"net_ret": "strategy_net_ret"})
    benchmark = load_csi300_holding_returns(strategy_days["trade_date"].tolist())
    days = strategy_days.merge(benchmark, on="trade_date", how="inner")
    days["net_ret"] = days["strategy_net_ret"] - days["benchmark_ret"]
    days["year"] = days["trade_date"].str[:4].astype(int)

    yearly = days.groupby("year").apply(lambda group: pd.Series(_metrics(group)), include_groups=False).reset_index()
    validation = _period(days, 2022, 2024)
    recent = _period(days, 2025, 2026)
    validation_metrics = _metrics(validation)
    recent_metrics = _metrics(recent)
    ci_low, ci_high, p_nonpositive = _bootstrap_probability(validation[["trade_date", "net_ret"]], block=20, repetitions=10000)
    alpha_drawdown = max_drawdown(days["net_ret"])
    correlation = float(days[["strategy_net_ret", "benchmark_ret"]].corr().iloc[0, 1]) if len(days) > 1 else np.nan
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
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    days.to_csv(output.with_name(output.stem + "_daily.csv"), index=False, encoding="utf-8-sig")
    lines = [
        "# 全市场逆向候选相对沪深300增量价值",
        "",
        "## 结论",
        "",
        f"- 同日期超额收益门槛：{'通过' if strict_pass else '不通过'}。",
        f"- 验证期 Bootstrap 95% 区间：{ci_low:+.4f}% 至 {ci_high:+.4f}%，均值不大于 0 的概率 {p_nonpositive:.2%}。",
        f"- 策略收益与沪深300同期收益相关系数：{correlation:.4f}；超额收益路径最大回撤：{alpha_drawdown:.2f}%。",
        "",
        "## 逐年超额收益",
        "",
        yearly.to_markdown(index=False, floatfmt=".4f"),
        "",
        "## 方法约束",
        "",
        "- 只比较策略实际发出信号的日期。",
        "- 策略收益已扣除 0.25% 成本，沪深300收益未扣成本，因此口径对策略更苛刻。",
        "- 沪深300同样使用 T+1 开盘到第5个交易日收盘，不使用信号日收盘偷换入场价。",
        "- 本审计没有修改正式策略或生成交易执行代码。",
    ]
    output.write_text("\n".join(lines), encoding="utf-8")
    print(f"strict_pass={strict_pass}")
    print(yearly.to_string(index=False))
    print(f"bootstrap=({ci_low:.4f},{ci_high:.4f}) p_nonpositive={p_nonpositive:.4f}")
    print(f"correlation={correlation:.4f} alpha_drawdown={alpha_drawdown:.2f}")
    print(f"wrote={output}")


if __name__ == "__main__":
    run()
