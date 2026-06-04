#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
波段交易诊断工具。

读取 backtest_results/trades_longterm_*.csv，先回答两个问题：
1. longterm_score 是否真能区分赢家和输家；
2. 当前亏损主要来自评分、持有天数还是退出原因。
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

import pandas as pd


NUMERIC_COLUMNS = [
    "profit_pct",
    "profit_after_fee",
    "hold_days",
    "longterm_score",
    "short_score",
]


def load_trades(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="utf-8-sig")
    for col in NUMERIC_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "profit_after_fee" not in df.columns and "profit_pct" in df.columns:
        df["profit_after_fee"] = df["profit_pct"]
    return df


def _fmt_pct(value: float) -> str:
    if pd.isna(value):
        return "-"
    return f"{value:+.2f}%"


def _score_bucket(score: float) -> str:
    if pd.isna(score):
        return "无分数"
    if score >= 80:
        return "80+ 高分"
    if score >= 70:
        return "70-80 准入区"
    if score >= 60:
        return "60-70 中分"
    return "<60 低分"


def _markdown_table(df: pd.DataFrame, columns: Iterable[str], max_rows: int = 10) -> str:
    cols = list(columns)
    if df.empty:
        return "无样本\n"
    view = df.loc[:, [c for c in cols if c in df.columns]].head(max_rows).copy()
    return view.to_markdown(index=False) + "\n"


def build_report(df: pd.DataFrame, title: str = "波段交易诊断") -> str:
    if df.empty:
        return f"# {title}\n\n无交易样本。\n"

    profit_col = "profit_after_fee" if "profit_after_fee" in df.columns else "profit_pct"
    work = df.copy()
    work["is_win"] = work[profit_col] > 0
    work["score_bucket"] = work.get("longterm_score", pd.Series(dtype=float)).apply(_score_bucket)

    total = len(work)
    wins = int(work["is_win"].sum())
    losses = int((work[profit_col] < 0).sum())
    win_rate = wins / total * 100 if total else 0
    avg_profit = work[profit_col].mean()
    total_profit = work[profit_col].sum()
    avg_hold = work["hold_days"].mean() if "hold_days" in work.columns else float("nan")

    score = work["longterm_score"] if "longterm_score" in work.columns else pd.Series(dtype=float)
    score_width = score.max() - score.min() if not score.dropna().empty else float("nan")
    winner_score = work.loc[work["is_win"], "longterm_score"].mean() if "longterm_score" in work.columns else float("nan")
    loser_score = work.loc[work[profit_col] < 0, "longterm_score"].mean() if "longterm_score" in work.columns else float("nan")

    bucket = (
        work.groupby("score_bucket", dropna=False)
        .agg(
            笔数=(profit_col, "size"),
            胜率=("is_win", lambda s: round(float(s.mean()) * 100, 2)),
            平均收益=(profit_col, lambda s: round(float(s.mean()), 2)),
            合计收益=(profit_col, lambda s: round(float(s.sum()), 2)),
        )
        .reset_index()
        .rename(columns={"score_bucket": "分数段"})
    )

    exits = pd.DataFrame()
    if "exit_reason" in work.columns:
        exits = (
            work.groupby("exit_reason", dropna=False)
            .agg(
                笔数=(profit_col, "size"),
                胜率=("is_win", lambda s: round(float(s.mean()) * 100, 2)),
                平均收益=(profit_col, lambda s: round(float(s.mean()), 2)),
                平均持有天数=("hold_days", lambda s: round(float(s.mean()), 1) if len(s.dropna()) else 0),
            )
            .reset_index()
            .rename(columns={"exit_reason": "退出原因"})
            .sort_values(["笔数", "平均收益"], ascending=[False, True])
        )

    high_score_losers = work[(work.get("longterm_score", 0) >= 70) & (work[profit_col] < 0)].sort_values(
        [profit_col, "longterm_score"], ascending=[True, False]
    )
    low_score_winners = work[(work.get("longterm_score", 0) < 70) & (work[profit_col] > 0)].sort_values(
        [profit_col, "longterm_score"], ascending=[False, True]
    )

    lines = [
        f"# {title}\n",
        "## 先看结论\n",
        f"- 总交易 `{total}` 笔，胜率 `{win_rate:.2f}%`，盈 `{wins}` / 亏 `{losses}`。\n",
        f"- 扣费后平均收益 `{_fmt_pct(avg_profit)}`，样本收益简单合计 `{_fmt_pct(total_profit)}`，平均持有 `{avg_hold:.1f}` 天。\n",
        f"- longterm_score 分布：最低 `{score.min():.1f}`，最高 `{score.max():.1f}`，跨度 `{score_width:.1f}`。\n",
        f"- 赢家平均分 `{winner_score:.1f}`，输家平均分 `{loser_score:.1f}`，分差 `{winner_score - loser_score:+.1f}`。\n",
    ]

    if pd.notna(score_width) and score_width < 15:
        lines.append("- 评分跨度偏窄，后续优先检查波段五维评分是否拉不开差距。\n")
    if pd.notna(winner_score) and pd.notna(loser_score) and winner_score <= loser_score:
        lines.append("- 当前分数没有把赢家排到输家前面，下一步应优先做因子归因，而不是直接提高门槛。\n")

    lines.extend(
        [
            "\n## longterm_score 分段表现\n",
            bucket.to_markdown(index=False),
            "\n\n## 退出原因\n",
            _markdown_table(exits, ["退出原因", "笔数", "胜率", "平均收益", "平均持有天数"], max_rows=20),
            "\n## 高分亏损样本\n",
            _markdown_table(
                high_score_losers,
                ["ts_code", "select_date", "buy_date", "sell_date", "longterm_score", profit_col, "hold_days", "exit_reason"],
                max_rows=15,
            ),
            "\n## 低分赚钱样本\n",
            _markdown_table(
                low_score_winners,
                ["ts_code", "select_date", "buy_date", "sell_date", "longterm_score", profit_col, "hold_days", "exit_reason"],
                max_rows=15,
            ),
            "\n## 下一步建议\n",
            "- 如果高分亏损集中在某类退出原因，先检查出场规则或入场时点。\n",
            "- 如果低分赚钱很多，说明当前门槛可能误杀，需要补候选池因子明细继续归因。\n",
            "- 当前交易 CSV 缺少五维因子明细，下一步建议让波段回测输出候选池诊断 CSV。\n",
        ]
    )
    return "".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="生成波段交易诊断 Markdown 报告")
    parser.add_argument("--trades", required=True, help="trades_longterm_*.csv 路径")
    parser.add_argument("--output", required=True, help="输出 Markdown 路径")
    parser.add_argument("--title", default="波段交易诊断", help="报告标题")
    args = parser.parse_args()

    df = load_trades(args.trades)
    report = build_report(df, title=args.title)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"Report written: {out}")
    print("\n".join(report.splitlines()[:8]))


if __name__ == "__main__":
    main()
