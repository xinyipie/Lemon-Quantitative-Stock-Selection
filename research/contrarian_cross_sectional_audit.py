#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""固定逆向候选的横截面、行业与极端收益依赖审计。"""

from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.two_stage_walkforward_research import _metrics, _period  # noqa: E402


INPUT = ROOT / "reports" / "research" / "contrarian_candidate_stress_20260808_trades.csv"
OUTPUT = ROOT / "reports" / "research" / "contrarian_cross_sectional_audit_20260808.md"


def add_fixed_partitions(frame: pd.DataFrame) -> pd.DataFrame:
    """按代码末位和交易所构造与收益无关的固定分区。"""
    result = frame.copy()
    symbol = result["ts_code"].astype(str).str.split(".").str[0]
    result["code_parity"] = np.where(pd.to_numeric(symbol.str[-1], errors="coerce").fillna(0).astype(int) % 2 == 0, "even", "odd")
    result["exchange"] = result["ts_code"].astype(str).str.split(".").str[-1]
    return result


def trim_largest_winners(frame: pd.DataFrame, fraction: float) -> pd.DataFrame:
    """只移除正收益尾部，用于检查策略是否依赖少数极端赢家。"""
    result = frame.copy()
    positive = result[pd.to_numeric(result["net_ret"], errors="coerce") > 0]
    remove_count = int(np.ceil(len(positive) * fraction))
    if remove_count <= 0:
        return result
    remove_index = positive.nlargest(remove_count, "net_ret").index
    return result.drop(index=remove_index)


def grouped_metrics(frame: pd.DataFrame, column: str, period: str, start: int, end: int) -> pd.DataFrame:
    rows = []
    sample = _period(frame, start, end)
    for value, group in sample.groupby(column):
        rows.append({"dimension": column, "group": str(value), "period": period, **_metrics(group)})
    return pd.DataFrame(rows)


def every_year_positive(frame: pd.DataFrame, start: int, end: int, minimum_trades: int = 10) -> bool:
    for year in range(start, end + 1):
        sample = _period(frame, year, year)
        metrics = _metrics(sample)
        if metrics["trades"] < minimum_trades or metrics["avg_net"] <= 0 or metrics["profit_factor"] <= 1.0:
            return False
    return True


def run(input_path: Path = INPUT, output: Path = OUTPUT) -> None:
    frame = pd.read_csv(input_path, encoding="utf-8-sig", low_memory=False)
    frame["trade_date"] = frame["trade_date"].astype(str).str.replace("-", "", regex=False).str[:8]
    frame = add_fixed_partitions(frame)

    grouped = pd.concat(
        [
            grouped_metrics(frame, dimension, period, start, end)
            for dimension in ("code_parity", "exchange", "regime")
            for period, start, end in (("validation", 2022, 2024), ("recent", 2025, 2026))
        ],
        ignore_index=True,
    )

    validation = _period(frame, 2022, 2024)
    recent = _period(frame, 2025, 2026)
    trim_rows = []
    for fraction in (0.01, 0.03, 0.05):
        for period, sample in (("validation", validation), ("recent", recent)):
            trim_rows.append({"fraction": fraction, "period": period, **_metrics(trim_largest_winners(sample, fraction))})
    trims = pd.DataFrame(trim_rows)

    industry_contribution = validation.groupby(validation["industry"].fillna("未知行业"))["net_ret"].agg(["count", "sum", "mean"]).reset_index()
    largest_positive_industry = str(industry_contribution.sort_values("sum", ascending=False).iloc[0]["industry"])
    without_largest = validation[validation["industry"].fillna("未知行业").ne(largest_positive_industry)]
    without_largest_metrics = _metrics(without_largest)

    parity_pass = all(
        every_year_positive(frame[frame["code_parity"].eq(value)], 2022, 2024, minimum_trades=15)
        for value in ("even", "odd")
    )
    exchange_pass = all(
        every_year_positive(frame[frame["exchange"].eq(value)], 2022, 2024, minimum_trades=15)
        for value in ("SH", "SZ")
    )
    trimmed_validation = trims[trims["period"].eq("validation")]
    outlier_pass = bool(
        (trimmed_validation["avg_net"] > 0).all()
        and (trimmed_validation["profit_factor"] > 1.05).all()
        and (trimmed_validation["positive_years"] == 3).all()
    )
    industry_pass = bool(
        without_largest_metrics["avg_net"] > 0
        and without_largest_metrics["profit_factor"] > 1.10
        and without_largest_metrics["positive_years"] == without_largest_metrics["years"] == 3
    )
    cross_sectional_pass = bool(parity_pass and exchange_pass and outlier_pass and industry_pass)

    output.parent.mkdir(parents=True, exist_ok=True)
    grouped.to_csv(output.with_name(output.stem + "_groups.csv"), index=False, encoding="utf-8-sig")
    trims.to_csv(output.with_name(output.stem + "_winner_trim.csv"), index=False, encoding="utf-8-sig")
    industry_contribution.sort_values("sum", ascending=False).to_csv(
        output.with_name(output.stem + "_industry.csv"), index=False, encoding="utf-8-sig"
    )
    lines = [
        "# 全市场逆向候选横截面稳健性审计",
        "",
        "## 结论",
        "",
        f"- 横截面稳健性门槛：{'通过' if cross_sectional_pass else '不通过'}。",
        f"- 代码奇偶双分区逐年通过：{'是' if parity_pass else '否'}。",
        f"- 沪深双交易所逐年通过：{'是' if exchange_pass else '否'}。",
        f"- 移除最大 1%/3%/5% 赢家后通过：{'是' if outlier_pass else '否'}。",
        f"- 移除最大正贡献行业 `{largest_positive_industry}` 后通过：{'是' if industry_pass else '否'}。",
        "",
        "## 固定分区指标",
        "",
        grouped.to_markdown(index=False, floatfmt=".4f"),
        "",
        "## 极端赢家移除",
        "",
        trims.to_markdown(index=False, floatfmt=".4f"),
        "",
        "## 验证期行业贡献",
        "",
        industry_contribution.sort_values("sum", ascending=False).head(20).to_markdown(index=False, floatfmt=".4f"),
        "",
        "## 研究约束",
        "",
        "- 分区规则只依赖股票代码或交易所，不读取未来收益。",
        "- 移除赢家而不移除亏损，用更苛刻方式检查尾部依赖。",
        "- 本报告只审计已锁定候选，不重新搜索参数，不修改正式策略。",
    ]
    output.write_text("\n".join(lines), encoding="utf-8")
    print(f"cross_sectional_pass={cross_sectional_pass}")
    print(f"parity_pass={parity_pass} exchange_pass={exchange_pass} outlier_pass={outlier_pass} industry_pass={industry_pass}")
    print(grouped.to_string(index=False))
    print(trims.to_string(index=False))
    print(f"wrote={output}")


if __name__ == "__main__":
    run()
