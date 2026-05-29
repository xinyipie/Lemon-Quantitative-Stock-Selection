"""Diagnose whether a candidate filtering rule can affect real trades.

Usage:
  python rule_hit_diagnostics.py --candidates backtest_results/ic_short_xxx.csv --trades backtest_results/trades_xxx.csv
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd


RULE_DESCRIPTIONS = {
    "high_score_drawdown_risk": "高分 + 形态弱 + 回撤深 + 板块/量能偏风险",
    "rerank_low_base_weak_pattern": "重排高分 + 基础分偏低 + 形态弱",
    "hot_sector_weak_pattern": "板块偏热 + 形态弱 + 回撤偏深",
    "high_volume_weak_pattern": "量能偏冲 + 形态弱 + 回撤偏深",
}
NUMERIC_COLUMNS = [
    "select_date",
    "score",
    "original_score",
    "score_base",
    "profit_after_fee",
    "ret_5d",
    "factor_pattern",
    "factor_drawdown",
    "factor_sector",
    "drawdown_from_high",
    "volume_ratio",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze rule hits on candidate and trade CSV files.")
    parser.add_argument("--candidates", required=True, help="Path to ic_short_*.csv candidate file.")
    parser.add_argument("--trades", required=True, help="Path to trades_*.csv file from the same run.")
    parser.add_argument(
        "--rule",
        default="high_score_drawdown_risk",
        help="Rule name, or 'all' to compare every built-in rule.",
    )
    parser.add_argument("--output", default=None, help="Markdown report path.")
    parser.add_argument("--top", type=int, default=20, help="Rows to show in example tables.")
    return parser.parse_args()


def load_csv(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="utf-8-sig")
    return normalize_frame(df)


def normalize_frame(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "select_date" in df.columns:
        df["select_date"] = df["select_date"].astype(str)
    if "ts_code" in df.columns:
        df["ts_code"] = df["ts_code"].astype(str)
    for col in NUMERIC_COLUMNS:
        if col in df.columns and col != "select_date":
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def add_candidate_rank(candidates: pd.DataFrame, score_col: str = "score") -> pd.DataFrame:
    df = normalize_frame(candidates)
    if score_col not in df.columns:
        raise ValueError(f"Missing score column: {score_col}")
    df["candidate_rank"] = df.groupby("select_date")[score_col].rank(method="first", ascending=False).astype(int)
    df["candidate_top3"] = df["candidate_rank"] <= 3
    return df


def evaluate_rule(candidates: pd.DataFrame, rule_name: str) -> pd.DataFrame:
    df = normalize_frame(candidates)
    if rule_name not in RULE_DESCRIPTIONS:
        raise ValueError(f"Unknown rule: {rule_name}")

    score = _num(df, "score")
    original_score = _num(df, "original_score", _num(df, "score_base", 0.0))
    pattern = _num(df, "factor_pattern")
    drawdown_score = _num(df, "factor_drawdown")
    sector = _num(df, "factor_sector")
    drawdown_from_high = _num(df, "drawdown_from_high")
    volume_ratio = _num(df, "volume_ratio")

    if rule_name == "high_score_drawdown_risk":
        hit = (
            (score >= 70.0)
            & (pattern < 55.0)
            & (drawdown_from_high >= 8.0)
            & ((drawdown_score >= 88.0) | (sector >= 55.0) | (volume_ratio >= 3.2))
        )
    elif rule_name == "rerank_low_base_weak_pattern":
        hit = (score >= 70.0) & (original_score <= 60.0) & (pattern < 55.0)
    elif rule_name == "hot_sector_weak_pattern":
        hit = (score >= 65.0) & (sector >= 55.0) & (pattern < 55.0) & (drawdown_from_high >= 6.0)
    elif rule_name == "high_volume_weak_pattern":
        hit = (score >= 65.0) & (volume_ratio >= 3.0) & (pattern < 55.0) & (drawdown_from_high >= 6.0)
    else:
        raise ValueError(f"Unknown rule: {rule_name}")

    df["_rule_hit"] = hit
    return df


def _num(df: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if col not in df.columns:
        return pd.Series(default, index=df.index, dtype="float64")
    return pd.to_numeric(df[col], errors="coerce").fillna(default)


def summarize_rule_hits(candidates: pd.DataFrame, trades: pd.DataFrame) -> dict[str, float | int]:
    candidates = normalize_frame(candidates)
    trades = normalize_frame(trades)
    if "_rule_hit" not in candidates.columns:
        raise ValueError("Candidates must contain _rule_hit. Call evaluate_rule first.")

    candidate_hits = candidates[candidates["_rule_hit"]]
    top3_hits = candidate_hits[candidate_hits.get("candidate_top3", False)]

    joined = trades.merge(
        candidates[["select_date", "ts_code", "_rule_hit", "candidate_rank", "candidate_top3"]],
        on=["select_date", "ts_code"],
        how="left",
    )
    joined["_rule_hit"] = joined["_rule_hit"].fillna(False).astype(bool)
    hit_trades = joined[joined["_rule_hit"]]
    non_hit_trades = joined[~joined["_rule_hit"]]

    return {
        "candidate_count": int(len(candidates)),
        "candidate_hit_count": int(len(candidate_hits)),
        "candidate_top3_hit_count": int(len(top3_hits)),
        "selected_trade_count": int(len(joined)),
        "selected_hit_count": int(len(hit_trades)),
        "selected_non_hit_count": int(len(non_hit_trades)),
        "selected_hit_win_rate_pct": _win_rate(hit_trades),
        "selected_non_hit_win_rate_pct": _win_rate(non_hit_trades),
        "selected_hit_total_return_pct": _sum_return(hit_trades),
        "selected_non_hit_total_return_pct": _sum_return(non_hit_trades),
        "selected_hit_avg_return_pct": _avg_return(hit_trades),
        "selected_non_hit_avg_return_pct": _avg_return(non_hit_trades),
    }


def summarize_many_rules(candidates: pd.DataFrame, trades: pd.DataFrame, rule_names: list[str] | None = None) -> pd.DataFrame:
    rule_names = rule_names or sorted(RULE_DESCRIPTIONS)
    rows = []
    for rule_name in rule_names:
        ruled = evaluate_rule(candidates, rule_name)
        summary = summarize_rule_hits(ruled, trades)
        rows.append({"rule": rule_name, "meaning": RULE_DESCRIPTIONS[rule_name], **summary})
    if not rows:
        return pd.DataFrame()
    return (
        pd.DataFrame(rows)
        .sort_values(["selected_hit_total_return_pct", "selected_hit_count"], ascending=[True, False])
        .reset_index(drop=True)
    )


def _sum_return(df: pd.DataFrame) -> float:
    if df.empty or "profit_after_fee" not in df.columns:
        return 0.0
    return round(float(pd.to_numeric(df["profit_after_fee"], errors="coerce").fillna(0).sum()), 2)


def _avg_return(df: pd.DataFrame) -> float:
    if df.empty or "profit_after_fee" not in df.columns:
        return 0.0
    return round(float(pd.to_numeric(df["profit_after_fee"], errors="coerce").mean()), 2)


def _win_rate(df: pd.DataFrame) -> float:
    if df.empty or "profit_after_fee" not in df.columns:
        return 0.0
    returns = pd.to_numeric(df["profit_after_fee"], errors="coerce").fillna(0)
    return round(float((returns > 0).mean() * 100), 2)


def build_markdown_report(candidates: pd.DataFrame, trades: pd.DataFrame, rule_name: str, top: int = 20) -> str:
    candidates = normalize_frame(candidates)
    trades = normalize_frame(trades)
    summary = summarize_rule_hits(candidates, trades)
    hit_examples = candidates[candidates["_rule_hit"]].copy()
    show_cols = [
        col
        for col in [
            "select_date",
            "ts_code",
            "score",
            "candidate_rank",
            "candidate_top3",
            "factor_pattern",
            "factor_drawdown",
            "factor_sector",
            "drawdown_from_high",
            "volume_ratio",
            "ret_5d",
        ]
        if col in hit_examples.columns
    ]

    lines = [
        "# Rule Hit Diagnostics",
        "",
        f"- Rule: `{rule_name}`",
        f"- Meaning: {RULE_DESCRIPTIONS.get(rule_name, rule_name)}",
        f"- Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 先看结论",
        f"- 候选池共有 {summary['candidate_count']} 条，规则命中 {summary['candidate_hit_count']} 条。",
        f"- 命中候选里，按候选分数进入 Top3 的有 {summary['candidate_top3_hit_count']} 条。",
        f"- 命中实际买入 {summary['selected_hit_count']} 笔，合计收益 {summary['selected_hit_total_return_pct']}%。",
        f"- 未命中实际买入 {summary['selected_non_hit_count']} 笔，合计收益 {summary['selected_non_hit_total_return_pct']}%。",
        "",
        "## Summary",
        pd.DataFrame([summary]).to_markdown(index=False),
        "",
        "## Hit Examples",
        hit_examples.sort_values(["select_date", "candidate_rank"]).head(top)[show_cols].to_markdown(index=False)
        if not hit_examples.empty
        else "_No rule hits._",
        "",
    ]
    return "\n".join(lines) + "\n"


def default_output_path(candidates_path: Path, rule_name: str) -> Path:
    stem = candidates_path.stem.replace("ic_short_", f"rule_hits_{rule_name}_")
    return Path("reports") / f"{stem}.md"


def main() -> None:
    args = parse_args()
    candidates_path = Path(args.candidates)
    candidates = add_candidate_rank(load_csv(candidates_path))
    trades = load_csv(args.trades)
    if args.rule == "all":
        summary = summarize_many_rules(candidates, trades)
        report = "\n".join(
            [
                "# Rule Hit Diagnostics",
                "",
                f"- Rule: `all`",
                f"- Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                "",
                "## 先看结论",
                "- 下表按“命中实际买入后的合计收益”从差到好排序，越靠前越值得进一步研究。",
                "",
                "## Rule Comparison",
                summary.to_markdown(index=False),
                "",
            ]
        )
    else:
        candidates = evaluate_rule(candidates, args.rule)
        report = build_markdown_report(candidates, trades, rule_name=args.rule, top=args.top)

    output_path = Path(args.output) if args.output else default_output_path(candidates_path, args.rule)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    print(f"Report written: {output_path}")
    print("\n".join(report.splitlines()[6:11]))


if __name__ == "__main__":
    main()
