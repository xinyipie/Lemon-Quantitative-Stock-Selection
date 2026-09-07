#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""对逆向候选完整参数搜索做 White Reality Check 多重试验校正。"""

from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.contrarian_dynamic_selector import config_grid, config_name  # noqa: E402
from research.two_stage_walkforward_research import _prepare, walk_forward  # noqa: E402


INPUT = ROOT / "reports" / "research" / "full_market_contrarian_top50_20260808.csv"
OUTPUT = ROOT / "reports" / "research" / "contrarian_reality_check_20260808.md"
CANDIDATE_NAME = "top2_gr100_gw99_q0.80_mall"


def block_indices(length: int, block: int, rng: np.random.Generator) -> np.ndarray:
    if length <= 0:
        return np.array([], dtype=int)
    starts = rng.integers(0, length, size=int(np.ceil(length / block)))
    chunks = [(start + np.arange(block)) % length for start in starts]
    return np.concatenate(chunks)[:length]


def reality_check(
    matrix: np.ndarray,
    *,
    candidate_index: int,
    block: int = 20,
    repetitions: int = 5000,
    seed: int = 20260808,
) -> dict[str, float]:
    """同时重采样所有策略，返回候选和全家族的搜索校正 p 值。"""
    values = np.asarray(matrix, dtype=float)
    if values.ndim != 2 or values.shape[0] < 2:
        return {"candidate_t": np.nan, "best_t": np.nan, "candidate_adjusted_p": 1.0, "best_family_p": 1.0}
    means = values.mean(axis=0)
    std = values.std(axis=0, ddof=1)
    scale = np.where(std > 1e-12, std / np.sqrt(values.shape[0]), np.inf)
    observed_t = means / scale
    centered = values - means
    rng = np.random.default_rng(seed)
    bootstrap_max = np.empty(repetitions, dtype=float)
    for index in range(repetitions):
        sampled = centered[block_indices(values.shape[0], block, rng)]
        bootstrap_t = sampled.mean(axis=0) / scale
        bootstrap_max[index] = np.nanmax(bootstrap_t)
    candidate_t = float(observed_t[candidate_index])
    best_t = float(np.nanmax(observed_t))
    return {
        "candidate_t": candidate_t,
        "best_t": best_t,
        "candidate_adjusted_p": float(np.mean(bootstrap_max >= candidate_t)),
        "best_family_p": float(np.mean(bootstrap_max >= best_t)),
    }


def build_matrix(frame: pd.DataFrame, market: pd.DataFrame, start_year: int, end_year: int):
    dates = sorted(
        market[market["year"].between(start_year, end_year)]["trade_date"].astype(str).unique()
    )
    series = {}
    summary = []
    for config in config_grid(cost=0.25):
        name = config_name(config)
        trades, _ = walk_forward(frame, market, **config)
        sample = trades[trades["trade_date"].astype(str).str[:4].astype(int).between(start_year, end_year)]
        daily = sample.groupby("trade_date")["net_ret"].mean().reindex(dates, fill_value=0.0)
        series[name] = daily
        summary.append(
            {
                "name": name,
                "active_days": int((daily != 0).sum()),
                "calendar_mean": float(daily.mean()),
                "calendar_std": float(daily.std(ddof=1)),
            }
        )
    matrix = pd.DataFrame(series, index=dates)
    return matrix, pd.DataFrame(summary)


def run(input_path: Path = INPUT, output: Path = OUTPUT) -> None:
    frame, market = _prepare(input_path)
    validation_matrix, validation_summary = build_matrix(frame, market, 2022, 2024)
    recent_matrix, recent_summary = build_matrix(frame, market, 2025, 2026)
    if CANDIDATE_NAME not in validation_matrix.columns:
        raise RuntimeError(f"候选不存在: {CANDIDATE_NAME}")
    candidate_index = validation_matrix.columns.get_loc(CANDIDATE_NAME)
    validation_result = reality_check(validation_matrix.to_numpy(), candidate_index=candidate_index, block=20, repetitions=5000)
    recent_result = reality_check(recent_matrix.to_numpy(), candidate_index=candidate_index, block=20, repetitions=5000, seed=20260809)

    sleeve_rows = []
    for offset in range(5):
        sleeve = validation_matrix.iloc[offset::5]
        result = reality_check(sleeve.to_numpy(), candidate_index=candidate_index, block=4, repetitions=3000, seed=20260820 + offset)
        sleeve_rows.append({"sleeve": offset, "days": len(sleeve), **result})
    sleeves = pd.DataFrame(sleeve_rows)
    pass_gate = bool(
        validation_result["candidate_adjusted_p"] < 0.05
        and validation_result["best_family_p"] < 0.05
        and recent_result["candidate_adjusted_p"] < 0.10
        and (sleeves["candidate_adjusted_p"] < 0.10).sum() >= 4
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    validation_summary.to_csv(output.with_name(output.stem + "_validation_family.csv"), index=False, encoding="utf-8-sig")
    recent_summary.to_csv(output.with_name(output.stem + "_recent_family.csv"), index=False, encoding="utf-8-sig")
    sleeves.to_csv(output.with_name(output.stem + "_sleeves.csv"), index=False, encoding="utf-8-sig")
    candidate_validation = validation_summary[validation_summary["name"].eq(CANDIDATE_NAME)].iloc[0]
    candidate_recent = recent_summary[recent_summary["name"].eq(CANDIDATE_NAME)].iloc[0]
    lines = [
        "# 全市场逆向参数家族 Reality Check",
        "",
        "## 结论",
        "",
        f"- 搜索偏差校正门槛：{'通过' if pass_gate else '不通过'}。",
        f"- 验证期候选校正 p 值：{validation_result['candidate_adjusted_p']:.4f}；全家族最佳校正 p 值：{validation_result['best_family_p']:.4f}。",
        f"- 近期候选校正 p 值：{recent_result['candidate_adjusted_p']:.4f}；全家族最佳校正 p 值：{recent_result['best_family_p']:.4f}。",
        f"- 候选验证期日历日均收益：{candidate_validation['calendar_mean']:+.4f}%，活跃 {int(candidate_validation['active_days'])} 日。",
        f"- 候选近期日历日均收益：{candidate_recent['calendar_mean']:+.4f}%，活跃 {int(candidate_recent['active_days'])} 日。",
        "",
        "## 五个不重叠袖套的搜索校正",
        "",
        sleeves.to_markdown(index=False, floatfmt=".4f"),
        "",
        "## 方法约束",
        "",
        "- 162组参数使用同一组分块重采样，保留策略间相关性。",
        "- 未交易日期按现金收益0计入，避免只在活跃日统计带来的选择偏差。",
        "- 每个策略先中心化到零均值，再比较全家族最大 t 统计量。",
        "- 该检验用于校正参数搜索偏差，不替代真正前瞻样本。",
        "- 本研究未修改正式策略，也不生成交易执行代码。",
    ]
    output.write_text("\n".join(lines), encoding="utf-8")
    print(f"pass_gate={pass_gate}")
    print(f"validation={validation_result}")
    print(f"recent={recent_result}")
    print(sleeves.to_string(index=False))
    print(f"wrote={output}")


if __name__ == "__main__":
    run()
