"""Diagnose stock-picking quality from backtest trade CSV files.

Usage:
  python trade_diagnostics.py
  python trade_diagnostics.py --trades backtest_results/trades_YYYYMMDD_HHMMSS.csv
  python trade_diagnostics.py --output reports/trade_diagnostics.md
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd


RETURN_CANDIDATES = ["profit_after_fee", "profit_pct", "return_pct", "pnl_pct", "profit"]
SCORE_CANDIDATES = ["original_score", "score_base", "short_score", "longterm_score"]
FACTOR_LABELS = {
    "score": "重排短线分",
    "experiment_score": "实验重排分",
    "original_score": "原始总分",
    "score_base": "基础总分",
    "short_score": "短线分数",
    "longterm_score": "波段分数",
    "factor_volume_ratio": "量能质量",
    "factor_drawdown": "回撤位置得分",
    "factor_inflow": "资金流强度",
    "factor_turnover": "换手活跃度",
    "factor_sector": "板块位置/热度",
    "factor_pattern": "形态质量",
    "factor_counter_trend": "反趋势确认",
    "factor_wyckoff": "Wyckoff结构",
    "factor_accel": "加速度信号",
    "change": "当日涨跌幅",
    "volume_ratio": "量比",
    "drawdown_from_high": "距高点回撤",
    "turnover": "换手率",
    "mfe_pct": "持仓期最大浮盈",
    "mae_pct": "持仓期最大浮亏",
    "best_close_pct": "窗口最好收盘收益",
    "worst_close_pct": "窗口最差收盘收益",
    "window_end_pct": "窗口结束收益",
}
FACTOR_COLUMNS = [
    "original_score",
    "score_base",
    "short_score",
    "longterm_score",
    "factor_volume_ratio",
    "factor_drawdown",
    "factor_inflow",
    "factor_turnover",
    "factor_sector",
    "factor_pattern",
    "factor_counter_trend",
    "factor_wyckoff",
    "factor_accel",
    "change",
    "volume_ratio",
    "drawdown_from_high",
    "turnover",
    "mfe_pct",
    "mae_pct",
    "best_close_pct",
    "worst_close_pct",
    "window_end_pct",
]
SHOW_COLUMNS = [
    "ts_code",
    "name",
    "buy_date",
    "sell_date",
    "profit_after_fee",
    "profit_pct",
    "original_score",
    "score_base",
    "short_score",
    "exit_reason",
    "market_style",
    "macro_mode",
    "hold_days",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a stock-picking diagnostics report from trades CSV.")
    parser.add_argument("--trades", default=None, help="Path to a trades_*.csv file. Defaults to latest.")
    parser.add_argument("--results-dir", default="backtest_results", help="Directory containing trades_*.csv files.")
    parser.add_argument("--output", default=None, help="Markdown report path. Defaults to reports/trade_diagnostics_*.md.")
    parser.add_argument("--top", type=int, default=10, help="Rows to show in example sections.")
    return parser.parse_args()


def find_latest_trades(results_dir: str | Path = "backtest_results") -> Path:
    files = sorted(Path(results_dir).glob("trades_*.csv"), key=lambda p: p.stat().st_mtime)
    if not files:
        raise FileNotFoundError(f"No trades_*.csv files found under {results_dir}")
    return files[-1]


def pick_return_col(df: pd.DataFrame) -> str:
    for col in RETURN_CANDIDATES:
        if col in df.columns:
            return col
    raise ValueError(f"No return column found. Expected one of: {', '.join(RETURN_CANDIDATES)}")


def pick_score_col(df: pd.DataFrame) -> str | None:
    return next((col for col in SCORE_CANDIDATES if col in df.columns), None)


def factor_label(field: str) -> str:
    return FACTOR_LABELS.get(field, field)


def load_trades_csv(path: str | Path) -> pd.DataFrame:
    return load_trades_frame(pd.read_csv(path, encoding="utf-8-sig"))


def load_trades_frame(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in set(RETURN_CANDIDATES + SCORE_CANDIDATES + FACTOR_COLUMNS + ["hold_days"]):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return_col = pick_return_col(df)
    df["_return_pct"] = df[return_col]
    df["_is_win"] = df["_return_pct"] > 0

    score_col = pick_score_col(df)
    if score_col:
        df["score_bucket"] = make_score_bucket(df[score_col])
    if "hold_days" in df.columns:
        df["hold_bucket"] = pd.cut(
            df["hold_days"],
            bins=[-1, 3, 5, 8, float("inf")],
            labels=["<=3d", "4-5d", "6-8d", ">8d"],
        ).astype("object")
    return df


def make_score_bucket(values: pd.Series) -> pd.Series:
    valid = values.dropna()
    result = pd.Series(pd.NA, index=values.index, dtype="object")
    if valid.empty:
        return result

    bucket_count = min(4, valid.nunique())
    if bucket_count <= 1:
        result.loc[valid.index] = "single"
        return result

    labels = ["Q1_low", "Q2_mid_low", "Q3_mid_high", "Q4_high"][:bucket_count]
    ranked = valid.rank(method="first")
    result.loc[valid.index] = pd.qcut(ranked, q=bucket_count, labels=labels).astype("object")
    return result


def summarize_overall(df: pd.DataFrame) -> dict[str, float | int]:
    trades = load_trades_frame(df)
    wins = trades[trades["_is_win"]]
    losses = trades[~trades["_is_win"]]
    avg_loss = float(losses["_return_pct"].mean()) if not losses.empty else 0.0
    avg_win = float(wins["_return_pct"].mean()) if not wins.empty else 0.0
    payoff_ratio = abs(avg_win / avg_loss) if avg_loss else 0.0

    return {
        "trade_count": int(len(trades)),
        "win_count": int(len(wins)),
        "loss_count": int(len(losses)),
        "win_rate_pct": round(float(trades["_is_win"].mean() * 100), 2) if len(trades) else 0.0,
        "total_return_pct": round(float(trades["_return_pct"].sum()), 2) if len(trades) else 0.0,
        "avg_return_pct": round(float(trades["_return_pct"].mean()), 2) if len(trades) else 0.0,
        "avg_win_pct": round(avg_win, 2),
        "avg_loss_pct": round(avg_loss, 2),
        "payoff_ratio": round(payoff_ratio, 2),
    }


def compare_winners_losers(df: pd.DataFrame, fields: Iterable[str] | None = None) -> pd.DataFrame:
    trades = load_trades_frame(df)
    fields = list(fields or FACTOR_COLUMNS)
    winners = trades[trades["_is_win"]]
    losers = trades[~trades["_is_win"]]
    rows = []

    for field in fields:
        if field not in trades.columns:
            continue
        winner_avg = winners[field].mean()
        loser_avg = losers[field].mean()
        if pd.isna(winner_avg) or pd.isna(loser_avg):
            continue
        rows.append(
            {
                "field": field,
                "meaning": factor_label(field),
                "winner_avg": round(float(winner_avg), 2),
                "loser_avg": round(float(loser_avg), 2),
                "diff": round(float(winner_avg - loser_avg), 2),
            }
        )

    if not rows:
        return pd.DataFrame(columns=["field", "meaning", "winner_avg", "loser_avg", "diff"])
    return pd.DataFrame(rows).sort_values("diff", key=lambda s: s.abs(), ascending=False).reset_index(drop=True)


def group_summary(df: pd.DataFrame, group_col: str) -> pd.DataFrame:
    trades = load_trades_frame(df)
    if group_col not in trades.columns or trades.empty:
        return pd.DataFrame(columns=["group", "trades", "win_rate_pct", "avg_return_pct", "total_return_pct"])

    rows = []
    for group, part in trades.groupby(group_col, dropna=False):
        rows.append(
            {
                "group": "NA" if pd.isna(group) else str(group),
                "trades": int(len(part)),
                "win_rate_pct": round(float(part["_is_win"].mean() * 100), 2),
                "avg_return_pct": round(float(part["_return_pct"].mean()), 2),
                "total_return_pct": round(float(part["_return_pct"].sum()), 2),
            }
        )
    return pd.DataFrame(rows).sort_values(["trades", "total_return_pct"], ascending=[False, False]).reset_index(drop=True)


def top_high_score_losers(df: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
    trades = load_trades_frame(df)
    score_col = pick_score_col(trades)
    if not score_col:
        return pd.DataFrame()
    cols = [col for col in SHOW_COLUMNS if col in trades.columns]
    return trades[~trades["_is_win"]].sort_values(score_col, ascending=False).head(top_n)[cols]


def low_score_winners(df: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
    trades = load_trades_frame(df)
    score_col = pick_score_col(trades)
    if not score_col:
        return pd.DataFrame()
    cols = [col for col in SHOW_COLUMNS if col in trades.columns]
    return trades[trades["_is_win"]].sort_values(score_col, ascending=True).head(top_n)[cols]


def table_to_markdown(df: pd.DataFrame, max_rows: int = 20) -> str:
    if df.empty:
        return "_No data._"
    return df.head(max_rows).to_markdown(index=False)


def format_overall(summary: dict[str, float | int]) -> str:
    lines = [
        f"- Trades: {summary['trade_count']}",
        f"- Win rate: {summary['win_rate_pct']}%",
        f"- Total return sum: {summary['total_return_pct']}%",
        f"- Avg return: {summary['avg_return_pct']}%",
        f"- Avg win / avg loss: {summary['avg_win_pct']}% / {summary['avg_loss_pct']}%",
        f"- Payoff ratio: {summary['payoff_ratio']}",
    ]
    return "\n".join(lines)


def explain_in_plain_chinese(df: pd.DataFrame) -> str:
    trades = load_trades_frame(df)
    summary = summarize_overall(trades)
    factor_gap = compare_winners_losers(trades)
    score_group = group_summary(trades, "score_bucket")
    market_group = group_summary(trades, "market_style")

    lines = [
        "这份报告想回答一个问题：现在的选股规则，到底是在选更容易赚钱的股票，还是只是把股票排了个名？",
        f"本次一共看了 {summary['trade_count']} 笔交易，胜率 {summary['win_rate_pct']}%，平均每笔 {summary['avg_return_pct']}%，盈亏比 {summary['payoff_ratio']}。",
    ]

    if not score_group.empty:
        best_score = score_group.sort_values("avg_return_pct", ascending=False).iloc[0]
        lines.append(
            f"按评分分组看，表现最好的是 {best_score['group']}，平均每笔 {best_score['avg_return_pct']}%。"
            "如果最高分组不是最好，说明总分排序还不够准，下一步不要盲目加大总分权重。"
        )

    if not factor_gap.empty:
        useful = factor_gap[~factor_gap["field"].isin(["mfe_pct", "mae_pct", "best_close_pct", "worst_close_pct", "window_end_pct"])]
        if not useful.empty:
            top = useful.iloc[0]
            direction = "赢家更高" if top["diff"] > 0 else "输家更高"
            lines.append(
                f"赢家和输家差异最大的可调字段是 {top['field']}，差值 {top['diff']}，表现为{direction}。"
                "这类字段优先进入下一轮因子实验。"
            )

    if not market_group.empty and len(market_group) > 1:
        best_market = market_group.sort_values("avg_return_pct", ascending=False).iloc[0]
        worst_market = market_group.sort_values("avg_return_pct", ascending=True).iloc[0]
        lines.append(
            f"按市场状态看，{best_market['group']} 更顺手，平均每笔 {best_market['avg_return_pct']}%；"
            f"{worst_market['group']} 更拖累，平均每笔 {worst_market['avg_return_pct']}%。"
        )

    lines.append("下一步建议：先调选股因子和市场状态过滤，不急着改卖点；重点减少“高分但亏钱”的票。")
    return "\n".join(f"- {line}" for line in lines)


def build_markdown_report(df: pd.DataFrame, source: str = "", top_n: int = 10) -> str:
    trades = load_trades_frame(df)
    sections = [
        "# Trade Diagnostics",
        "",
        f"- Source: {source or 'in-memory dataframe'}",
        f"- Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 先看结论",
        explain_in_plain_chinese(trades),
        "",
        "## Overall",
        format_overall(summarize_overall(trades)),
        "",
        "## Winners vs Losers",
        table_to_markdown(compare_winners_losers(trades), max_rows=20),
    ]

    for group_col, title in [
        ("exit_reason", "By Exit Reason"),
        ("market_style", "By Market Style"),
        ("macro_mode", "By Macro Mode"),
        ("score_bucket", "By Score Bucket"),
        ("hold_bucket", "By Hold Bucket"),
    ]:
        sections.extend(["", f"## {title}", table_to_markdown(group_summary(trades, group_col), max_rows=20)])

    sections.extend(
        [
            "",
            "## High Score Losers",
            table_to_markdown(top_high_score_losers(trades, top_n=top_n), max_rows=top_n),
            "",
            "## Low Score Winners",
            table_to_markdown(low_score_winners(trades, top_n=top_n), max_rows=top_n),
            "",
            "## Next Checks",
            "- If high-score losers cluster in one market_style or macro_mode, add a market-aware penalty before changing factor weights globally.",
            "- If winners consistently have stronger factor gaps, prioritize those factors in the next scoring experiment.",
            "- If low-score winners are common, inspect whether the current score is missing an important event or momentum feature.",
        ]
    )
    return "\n".join(sections) + "\n"


def default_output_path(trades_path: Path) -> Path:
    stem = trades_path.stem.replace("trades_", "trade_diagnostics_")
    return Path("reports") / f"{stem}.md"


def main() -> None:
    args = parse_args()
    trades_path = Path(args.trades) if args.trades else find_latest_trades(args.results_dir)
    df = load_trades_csv(trades_path)
    report = build_markdown_report(df, source=str(trades_path), top_n=args.top)

    output_path = Path(args.output) if args.output else default_output_path(trades_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")

    print(f"Report written: {output_path}")
    print(format_overall(summarize_overall(df)))


if __name__ == "__main__":
    main()
