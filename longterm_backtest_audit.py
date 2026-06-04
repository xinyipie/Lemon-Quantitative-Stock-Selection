#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""波段回测口径审计工具。"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, List

import pandas as pd


def load_trades(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="utf-8-sig")
    for col in ["buy_date", "sell_date", "select_date"]:
        if col in df.columns:
            df[col] = df[col].astype(str)
    for col in ["profit_after_fee", "profit_pct"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _trade_dates(df: pd.DataFrame) -> List[str]:
    dates = set(df["buy_date"].dropna().astype(str)) | set(df["sell_date"].dropna().astype(str))
    return sorted(d for d in dates if d and d != "nan")


def audit_trades(df: pd.DataFrame, top_n: int = 3) -> Dict:
    if df.empty:
        return {
            "total_trades": 0,
            "max_open_positions": 0,
            "max_slot_exposure_pct": 0.0,
            "duplicate_overlap_count": 0,
            "duplicate_overlap_examples": [],
        }

    work = df.copy()
    work["buy_date"] = work["buy_date"].astype(str)
    work["sell_date"] = work["sell_date"].astype(str)
    weight_pct = 100.0 / max(top_n, 1)

    max_open = 0
    max_exposure = 0.0
    exposure_rows = []
    duplicate_examples = []
    duplicate_count = 0

    for date in _trade_dates(work):
        # 买入日含当日，卖出日不再视为隔夜持仓。
        open_df = work[(work["buy_date"] <= date) & (work["sell_date"] > date)]
        open_count = len(open_df)
        exposure = open_count * weight_pct
        max_open = max(max_open, open_count)
        max_exposure = max(max_exposure, exposure)
        exposure_rows.append({"date": date, "open_positions": open_count, "slot_exposure_pct": round(exposure, 2)})

        repeated = open_df["ts_code"].value_counts()
        for ts_code, cnt in repeated[repeated > 1].items():
            duplicate_count += int(cnt - 1)
            if len(duplicate_examples) < 10:
                duplicate_examples.append(f"{date} {ts_code} 同时持有{cnt}笔")

    exits = (
        work.groupby("exit_reason", dropna=False)
        .size()
        .reset_index(name="count")
        .sort_values("count", ascending=False)
        .to_dict("records")
        if "exit_reason" in work.columns
        else []
    )

    return {
        "total_trades": int(len(work)),
        "date_span": f"{work['buy_date'].min()} ~ {work['sell_date'].max()}",
        "top_n": int(top_n),
        "slot_weight_pct": round(weight_pct, 2),
        "max_open_positions": int(max_open),
        "max_slot_exposure_pct": round(max_exposure, 2),
        "days_over_100pct_exposure": int(sum(r["slot_exposure_pct"] > 100 for r in exposure_rows)),
        "days_over_200pct_exposure": int(sum(r["slot_exposure_pct"] > 200 for r in exposure_rows)),
        "duplicate_overlap_count": int(duplicate_count),
        "duplicate_overlap_examples": duplicate_examples,
        "top_exposure_days": sorted(exposure_rows, key=lambda r: r["slot_exposure_pct"], reverse=True)[:15],
        "exit_counts": exits,
    }


def build_report(result: Dict, title: str) -> str:
    lines = [
        f"# {title}\n\n",
        "## 先看结论\n",
        f"- 交易笔数：`{result['total_trades']}`。\n",
        f"- 回测区间：`{result.get('date_span', '-')}`。\n",
        f"- 当前净值口径按 Top{result.get('top_n', 3)} 固定槽位估算，每笔约 `{result.get('slot_weight_pct', 0):.2f}%` 仓位。\n",
        f"- 最大同时持仓：`{result['max_open_positions']}` 笔，估算最大槽位暴露 `{result['max_slot_exposure_pct']:.2f}%`。\n",
        f"- 暴露超过100%的日期：`{result.get('days_over_100pct_exposure', 0)}` 天；超过200%的日期：`{result.get('days_over_200pct_exposure', 0)}` 天。\n",
        f"- 同一股票重叠持仓次数：`{result['duplicate_overlap_count']}`。\n",
    ]
    if result["max_slot_exposure_pct"] > 100:
        lines.append("- 这说明波段回测存在持仓叠加，组合收益/回撤不能按普通满仓策略直接理解。\n")
    if result["duplicate_overlap_count"] > 0:
        lines.append("- 同一股票可能在前一笔未平仓时再次买入，后续需要决定是否允许加仓。\n")

    lines.append("\n## 最大暴露日期\n")
    exposure_df = pd.DataFrame(result.get("top_exposure_days", []))
    lines.append(exposure_df.to_markdown(index=False) if not exposure_df.empty else "无样本")
    lines.append("\n\n## 重叠持仓示例\n")
    examples = result.get("duplicate_overlap_examples", [])
    lines.extend([f"- {x}\n" for x in examples] if examples else ["无\n"])

    lines.append("\n## 退出原因计数\n")
    exits = pd.DataFrame(result.get("exit_counts", []))
    lines.append(exits.to_markdown(index=False) if not exits.empty else "无样本")

    lines.append(
        "\n\n## 审计结论\n"
        "- 在确认是否限制最大同时持仓、是否禁止重复开同一股票之前，不建议继续做波段因子权重实验。\n"
        "- 如果后续要做实盘波段，应先定义组合层规则：最大持仓数、单票是否可加仓、总暴露上限、空仓资金如何处理。\n"
    )
    return "".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="审计波段回测持仓与暴露口径")
    parser.add_argument("--trades", required=True, help="trades_*.csv 路径")
    parser.add_argument("--output", required=True, help="输出 Markdown 路径")
    parser.add_argument("--title", default="波段回测审计", help="报告标题")
    parser.add_argument("--topn", type=int, default=3, help="回测 TopN，用于估算槽位仓位")
    args = parser.parse_args()

    df = load_trades(args.trades)
    result = audit_trades(df, top_n=args.topn)
    report = build_report(result, args.title)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"Report written: {out}")
    print("\n".join(report.splitlines()[:8]))


if __name__ == "__main__":
    main()
