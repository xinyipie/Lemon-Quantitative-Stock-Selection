#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Analyze longterm stop-loss path signatures for the next strategy iteration."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


FACTOR_COLUMNS = [
    "longterm_score",
    "industry_rs",
    "score_rs",
    "score_fin",
    "score_entry",
    "score_risk_penalty",
    "price_vs_ma60",
    "turnover",
    "volume_ratio",
    "ma20_slope",
    "drawdown_from_high",
    "main_net_inflow",
    "mfe_pct",
    "mae_pct",
    "window_end_pct",
]
GOOD_EXIT_REASONS = {"trailing_stop", "weak_close_exit", "take_profit", "take_profit_next_open"}
SAMPLE_COLUMNS = [
    "source_label",
    "ts_code",
    "name",
    "buy_date",
    "sell_date",
    "profit_pct",
    "exit_reason",
    "mfe_pct",
    "mae_pct",
    "longterm_score",
    "price_vs_ma60",
    "turnover",
    "industry_rs",
]


def load_trades(path: str | Path, label: str | None = None) -> pd.DataFrame:
    trade_path = Path(path)
    df = pd.read_csv(trade_path, encoding="utf-8-sig")
    return normalize_trades(df, label or trade_path.stem)


def normalize_trades(df: pd.DataFrame, label: str = "data") -> pd.DataFrame:
    work = df.copy()
    work["source_label"] = label
    for col in set(FACTOR_COLUMNS + ["profit_pct", "profit_after_fee", "hold_days"]):
        if col in work.columns:
            work[col] = pd.to_numeric(work[col], errors="coerce")
    if "profit_pct" not in work.columns and "profit_after_fee" in work.columns:
        work["profit_pct"] = work["profit_after_fee"]
    if "profit_pct" not in work.columns:
        work["profit_pct"] = 0.0
    if "exit_reason" not in work.columns:
        work["exit_reason"] = "unknown"
    work["exit_reason"] = work["exit_reason"].fillna("unknown").astype(str)
    work["_is_stop_loss"] = work["exit_reason"].eq("stop_loss")
    work["_is_good_exit"] = work["exit_reason"].isin(GOOD_EXIT_REASONS)
    work["_is_loss"] = work["profit_pct"] <= 0
    work["_is_big_path_loss"] = work.get("mae_pct", pd.Series(0.0, index=work.index)).fillna(0) <= -12
    return work


def compare_path_groups(df: pd.DataFrame, factors: list[str] | None = None) -> pd.DataFrame:
    factors = [col for col in (factors or FACTOR_COLUMNS) if col in df.columns]
    stop_loss = df[df["_is_stop_loss"]]
    good_exit = df[df["_is_good_exit"]]
    losers = df[df["_is_loss"]]
    rows = []
    for factor in factors:
        stop_avg = stop_loss[factor].mean()
        good_avg = good_exit[factor].mean()
        loser_avg = losers[factor].mean()
        all_avg = df[factor].mean()
        if pd.isna(stop_avg) or pd.isna(good_avg):
            continue
        rows.append(
            {
                "factor": factor,
                "stop_loss_avg": round(float(stop_avg), 3),
                "good_exit_avg": round(float(good_avg), 3),
                "stop_minus_good": round(float(stop_avg - good_avg), 3),
                "loser_avg": round(float(loser_avg), 3) if not pd.isna(loser_avg) else None,
                "all_avg": round(float(all_avg), 3) if not pd.isna(all_avg) else None,
            }
        )
    if not rows:
        return pd.DataFrame(columns=["factor", "stop_loss_avg", "good_exit_avg", "stop_minus_good", "loser_avg", "all_avg"])
    result = pd.DataFrame(rows)
    return result.sort_values("stop_minus_good", key=lambda s: s.abs(), ascending=False).reset_index(drop=True)


def exit_summary(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df.groupby(["source_label", "exit_reason"], dropna=False)
        .agg(
            笔数=("profit_pct", "size"),
            平均收益=("profit_pct", "mean"),
            胜率=("profit_pct", lambda s: (s > 0).mean() * 100),
            平均MFE=("mfe_pct", "mean"),
            平均MAE=("mae_pct", "mean"),
        )
        .reset_index()
        .round(2)
        .sort_values(["source_label", "笔数"], ascending=[True, False])
    )


def overall_summary(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df.groupby("source_label", dropna=False)
        .agg(
            笔数=("profit_pct", "size"),
            总收益=("profit_pct", "sum"),
            平均收益=("profit_pct", "mean"),
            胜率=("profit_pct", lambda s: (s > 0).mean() * 100),
            止损数=("_is_stop_loss", "sum"),
            好出场数=("_is_good_exit", "sum"),
            大路径亏损数=("_is_big_path_loss", "sum"),
        )
        .reset_index()
        .round(2)
    )


def _table(df: pd.DataFrame, cols: list[str] | None = None, max_rows: int = 20) -> str:
    if df.empty:
        return "无样本\n"
    view = df.copy()
    if cols:
        view = view[[col for col in cols if col in view.columns]]
    return view.head(max_rows).to_markdown(index=False) + "\n"


def _plain_suggestions(diff: pd.DataFrame) -> list[str]:
    suggestions = []
    by_factor = {row.factor: row for row in diff.itertuples()}
    price = by_factor.get("price_vs_ma60")
    turnover = by_factor.get("turnover")
    mae = by_factor.get("mae_pct")
    if price is not None and price.stop_minus_good > 3:
        suggestions.append("- `price_vs_ma60`：止损票明显更远离MA60，v7可测试 `>18` 降权、`>22` 强降权。")
    if turnover is not None and turnover.stop_minus_good > 2:
        suggestions.append("- `turnover`：止损票换手更高，v7可测试 `>10` 降权、`>13` 强降权。")
    if mae is not None and mae.stop_loss_avg < -12:
        suggestions.append("- `mae_pct`：止损票入场后路径下杀很深，优先做入场保护，而不是继续调综合分。")
    if not suggestions:
        suggestions.append("- 暂未发现单一强特征，下一步应按月份/市场状态拆分止损票。")
    return suggestions


def build_report(df: pd.DataFrame, title: str = "波段止损路径诊断") -> str:
    if df.empty:
        return f"# {title}\n\n无交易样本。\n"
    diff = compare_path_groups(df)
    exits = exit_summary(df)
    overall = overall_summary(df)
    stop_samples = df[df["_is_stop_loss"]].sort_values(["mae_pct", "profit_pct"], ascending=[True, True])
    good_samples = df[df["_is_good_exit"]].sort_values("profit_pct", ascending=False)
    high_mfe_losses = df[(df["profit_pct"] <= 0) & (df.get("mfe_pct", 0) >= 10)].sort_values("mfe_pct", ascending=False)

    stop_count = int(df["_is_stop_loss"].sum())
    good_count = int(df["_is_good_exit"].sum())
    big_path = int(df["_is_big_path_loss"].sum())
    lines = [
        f"# {title}\n\n",
        "## 先看结论\n",
        f"- 共分析 `{len(df)}` 笔交易，止损票 `{stop_count}` 笔，好出场票 `{good_count}` 笔，大路径亏损 `{big_path}` 笔。\n",
    ]
    if not diff.empty:
        top = diff.head(5)
        signal_text = "、".join(f"`{r.factor}` 止损组-好出场组 {r.stop_minus_good:+.2f}" for r in top.itertuples())
        lines.append(f"- 止损票最突出的路径差异：{signal_text}。\n")
    lines.extend(_plain_suggestions(diff))
    lines.extend(
        [
            "\n## 总体表现\n",
            _table(overall, max_rows=30),
            "\n## 退出原因\n",
            _table(exits, max_rows=40),
            "\n## 止损票 vs 好出场票：因子差异\n",
            _table(diff, max_rows=30),
            "\n## 高MFE但亏损的回吐样本\n",
            _table(high_mfe_losses, SAMPLE_COLUMNS, max_rows=20),
            "\n## 最差止损样本\n",
            _table(stop_samples, SAMPLE_COLUMNS, max_rows=20),
            "\n## 最好出场样本\n",
            _table(good_samples, SAMPLE_COLUMNS, max_rows=20),
            "\n## v7候选规则\n",
            "- 先不要改综合评分主结构，优先把稳定出现在止损票里的路径风险做成入场保护。\n",
            "- 候选规则要先用小窗口验证，再跑 2024H2 / 2025 / 2026YTD 三段。\n",
        ]
    )
    return "".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze longterm stop-loss path signatures.")
    parser.add_argument("--trades", nargs="+", required=True, help="One or more trades_*.csv files.")
    parser.add_argument("--labels", default=None, help="Comma separated labels, e.g. 2024H2,2025,2026YTD.")
    parser.add_argument("--output", required=True, help="Markdown report path.")
    parser.add_argument("--title", default="波段止损路径诊断", help="Report title.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    labels = args.labels.split(",") if args.labels else [None] * len(args.trades)
    if len(labels) != len(args.trades):
        raise SystemExit("--labels 数量必须与 --trades 文件数量一致")
    frames = [load_trades(path, label) for path, label in zip(args.trades, labels)]
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    report = build_report(df, title=args.title)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"Report written: {out}")
    print("\n".join(report.splitlines()[:8]))


if __name__ == "__main__":
    main()
