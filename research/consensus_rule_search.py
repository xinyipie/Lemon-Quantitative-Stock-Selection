"""Search simple consensus snapshot rules before expensive full backtests."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


DEFAULT_SNAPSHOT = Path("reports") / "consensus_snapshot_v19_v25_v27_20260703.csv"
DEFAULT_OUTPUT = Path("reports") / "consensus_rule_search_20260703.csv"
RECENT_PERIODS = {"2025", "2026H1"}
BAD_PERIODS = {"2016", "2022", "2023"}


@dataclass(frozen=True)
class SearchRule:
    name: str
    topn: int
    min_votes: int
    min_heat: int | None = None
    max_change: float | None = None
    max_volume_ratio: float | None = None
    max_drawdown: float | None = None
    exclude_mid_breadth: bool = False
    mid_breadth_penalty: float = 0.0
    filter_cautious_down_friction: bool = False
    min_cautious_friction_pattern: float | None = None
    nonmid_bonus: float = 0.0
    sector_low_bonus: float = 0.0
    pattern_low_bonus: float = 0.0


def run_consensus_rule_search(snapshot: pd.DataFrame, min_trades: int = 10) -> pd.DataFrame:
    """Evaluate a compact grid of observable rules on the reusable snapshot."""
    if snapshot.empty:
        return pd.DataFrame()
    work = _coerce_numeric(snapshot)
    rows = []
    for rule in _generate_rules():
        selected = _apply_rule(work, rule)
        if len(selected) < min_trades:
            continue
        rows.append(_metrics_for_rule(rule, selected))
    if not rows:
        return pd.DataFrame()
    result = pd.DataFrame(rows)
    return result.sort_values(
        ["score", "recent_win_rate", "bad_year_return", "total_trades"],
        ascending=[False, False, False, False],
    ).reset_index(drop=True)


def write_consensus_rule_search(
    snapshot_path: str | Path = DEFAULT_SNAPSHOT,
    output: str | Path = DEFAULT_OUTPUT,
    min_trades: int = 10,
) -> dict:
    snapshot_path = Path(snapshot_path)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    snapshot = pd.read_csv(snapshot_path, encoding="utf-8-sig")
    result = run_consensus_rule_search(snapshot, min_trades=min_trades)
    result.to_csv(output, index=False, encoding="utf-8-sig")
    summary = _summary(result, snapshot_path=snapshot_path, output=output)
    output.with_suffix(".json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    output.with_suffix(".md").write_text(_format_markdown(result, summary), encoding="utf-8")
    return summary


def _generate_rules() -> list[SearchRule]:
    rules = []
    for topn in (1, 2):
        for min_votes in (2, 3):
            for min_heat in (None, 40, 50, 60, 70, 80):
                for max_change in (None, 4.5, 5.0):
                    for max_volume_ratio in (None, 2.5, 2.8, 3.0):
                        for exclude_mid in (False, True):
                            for mid_penalty in ((0.0, 25.0, 35.0) if not exclude_mid else (0.0,)):
                                for filter_friction, min_friction_pattern in (
                                    (False, None),
                                    (True, None),
                                    (True, 60.0),
                                    (True, 65.0),
                                ):
                                    name = _rule_name(
                                        topn=topn,
                                        min_votes=min_votes,
                                        min_heat=min_heat,
                                        max_change=max_change,
                                        max_volume_ratio=max_volume_ratio,
                                        exclude_mid_breadth=exclude_mid,
                                        mid_breadth_penalty=mid_penalty,
                                        filter_cautious_down_friction=filter_friction,
                                        min_cautious_friction_pattern=min_friction_pattern,
                                    )
                                    rules.append(
                                        SearchRule(
                                            name=name,
                                            topn=topn,
                                            min_votes=min_votes,
                                            min_heat=min_heat,
                                            max_change=max_change,
                                            max_volume_ratio=max_volume_ratio,
                                            exclude_mid_breadth=exclude_mid,
                                            mid_breadth_penalty=mid_penalty,
                                            filter_cautious_down_friction=filter_friction,
                                            min_cautious_friction_pattern=min_friction_pattern,
                                        )
                                    )
    return rules


def _apply_rule(df: pd.DataFrame, rule: SearchRule) -> pd.DataFrame:
    work = df[df["consensus_votes"] >= rule.min_votes].copy()
    if rule.min_heat is not None:
        work = work[work["limit_up_count"] >= rule.min_heat]
    if rule.max_change is not None:
        work = work[work["change"] <= rule.max_change]
    if rule.max_volume_ratio is not None:
        work = work[work["volume_ratio"] <= rule.max_volume_ratio]
    if rule.max_drawdown is not None:
        work = work[work["drawdown_from_high"] <= rule.max_drawdown]
    if rule.exclude_mid_breadth:
        work = work[~work["sector_ma10_ratio"].between(46, 70, inclusive="both")]
    if rule.filter_cautious_down_friction:
        macro = work["macro_mode"].astype(str).str.lower() if "macro_mode" in work.columns else pd.Series("", index=work.index)
        limit_down = work["limit_down_count"] if "limit_down_count" in work.columns else pd.Series(999.0, index=work.index)
        friction = macro.eq("cautious") & limit_down.between(5, 19, inclusive="both")
        if rule.min_cautious_friction_pattern is None:
            work = work[~friction]
        else:
            pattern = work["factor_pattern"] if "factor_pattern" in work.columns else pd.Series(0.0, index=work.index)
            work = work[~friction | (pattern >= rule.min_cautious_friction_pattern)]
    if work.empty:
        return work

    score = work["consensus_score"].copy()
    neutral_breadth = work["sector_ma10_ratio"].between(46, 70, inclusive="both")
    score = score - neutral_breadth.astype(float) * rule.mid_breadth_penalty
    score = score + (~neutral_breadth).astype(float) * rule.nonmid_bonus
    if "factor_sector" in work.columns:
        score = score + (work["factor_sector"] <= 45).astype(float) * rule.sector_low_bonus
    if "factor_pattern" in work.columns:
        score = score + (work["factor_pattern"] <= 40).astype(float) * rule.pattern_low_bonus
    work["rule_score"] = score
    work = work.sort_values(["select_date", "rule_score", "ts_code"], ascending=[True, False, True])
    return work.groupby("select_date", group_keys=False).head(rule.topn).copy()


def _metrics_for_rule(rule: SearchRule, selected: pd.DataFrame) -> dict:
    ret = selected["ret_5d"]
    recent = selected[selected["period"].astype(str).isin(RECENT_PERIODS)]
    bad = selected[selected["period"].astype(str).isin(BAD_PERIODS)]
    by_period = selected.groupby(selected["period"].astype(str)).agg(
        n=("ts_code", "size"),
        total=("ret_5d", "sum"),
        win=("ret_5d", lambda x: float((x > 0).mean()) if len(x) else 0.0),
    )
    recent_win = _win_rate(recent)
    total_return = float(ret.sum())
    bad_return = float(bad["ret_5d"].sum()) if not bad.empty else 0.0
    avg_mae = float(selected["mae_pct"].mean()) if "mae_pct" in selected.columns else 0.0
    score = _score_rule(
        total_trades=len(selected),
        win_rate=_win_rate(selected),
        recent_win_rate=recent_win,
        total_return=total_return,
        bad_year_return=bad_return,
        avg_mae=avg_mae,
        active_years=int(by_period.shape[0]),
    )
    return {
        "rule_name": rule.name,
        "topn": rule.topn,
        "min_votes": rule.min_votes,
        "min_heat": rule.min_heat if rule.min_heat is not None else "",
        "max_change": rule.max_change if rule.max_change is not None else "",
        "max_volume_ratio": rule.max_volume_ratio if rule.max_volume_ratio is not None else "",
        "exclude_mid_breadth": rule.exclude_mid_breadth,
        "mid_breadth_penalty": rule.mid_breadth_penalty,
        "filter_cautious_down_friction": rule.filter_cautious_down_friction,
        "min_cautious_friction_pattern": rule.min_cautious_friction_pattern if rule.min_cautious_friction_pattern is not None else "",
        "total_trades": int(len(selected)),
        "date_count": int(selected["select_date"].nunique()),
        "active_years": int(by_period.shape[0]),
        "positive_years": int((by_period["total"] > 0).sum()),
        "win_rate": round(_win_rate(selected), 2),
        "recent_trades": int(len(recent)),
        "recent_win_rate": round(recent_win, 2),
        "recent_return": round(float(recent["ret_5d"].sum()) if not recent.empty else 0.0, 2),
        "bad_year_trades": int(len(bad)),
        "bad_year_return": round(bad_return, 2),
        "total_return": round(total_return, 2),
        "avg_mfe": round(float(selected["mfe_pct"].mean()) if "mfe_pct" in selected.columns else 0.0, 2),
        "avg_mae": round(avg_mae, 2),
        "score": round(score, 4),
    }


def _score_rule(
    total_trades: int,
    win_rate: float,
    recent_win_rate: float,
    total_return: float,
    bad_year_return: float,
    avg_mae: float,
    active_years: int,
) -> float:
    trade_penalty = max(0, 35 - total_trades) * 1.2
    bad_penalty = abs(min(0.0, bad_year_return)) * 2.0
    mae_penalty = abs(min(0.0, avg_mae)) * 3.0
    return (
        recent_win_rate * 1.2
        + win_rate * 0.7
        + total_return * 0.12
        + active_years * 2.0
        + min(total_trades, 80) * 0.25
        - trade_penalty
        - bad_penalty
        - mae_penalty
    )


def _win_rate(df: pd.DataFrame) -> float:
    if df.empty or "ret_5d" not in df.columns:
        return 0.0
    return float((df["ret_5d"] > 0).mean() * 100.0)


def _coerce_numeric(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in (
        "consensus_votes",
        "consensus_score",
        "limit_up_count",
        "limit_down_count",
        "sector_ma10_ratio",
        "change",
        "volume_ratio",
        "drawdown_from_high",
        "factor_sector",
        "factor_pattern",
        "ret_5d",
        "mfe_pct",
        "mae_pct",
    ):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out.fillna({"ret_5d": 0.0, "mfe_pct": 0.0, "mae_pct": 0.0})


def _rule_name(**parts) -> str:
    items = [f"top{parts['topn']}", f"votes>={parts['min_votes']}"]
    if parts["min_heat"] is not None:
        items.append(f"heat>={parts['min_heat']}")
    if parts["max_change"] is not None:
        items.append(f"chg<={parts['max_change']}")
    if parts["max_volume_ratio"] is not None:
        items.append(f"vol<={parts['max_volume_ratio']}")
    if parts["exclude_mid_breadth"]:
        items.append("no_mid_breadth")
    elif parts["mid_breadth_penalty"]:
        items.append(f"mid_penalty={int(parts['mid_breadth_penalty'])}")
    if parts.get("filter_cautious_down_friction"):
        items.append("no_cautious_friction")
        if parts.get("min_cautious_friction_pattern") is not None:
            items.append(f"friction_pattern>={int(parts['min_cautious_friction_pattern'])}")
    return "|".join(items)


def _summary(result: pd.DataFrame, snapshot_path: Path, output: Path) -> dict:
    top_rule = result.iloc[0].to_dict() if not result.empty else {}
    return {
        "snapshot": str(snapshot_path),
        "output": str(output),
        "rules_evaluated": int(len(result)),
        "top_rule": top_rule,
    }


def _format_markdown(result: pd.DataFrame, summary: dict) -> str:
    lines = [
        "# 共识快照规则搜索",
        "",
        "## 摘要",
        f"- 快照：`{summary['snapshot']}`",
        f"- 输出：`{summary['output']}`",
        f"- 有效规则数：{summary['rules_evaluated']}",
        "",
        "## Top 20",
        "",
    ]
    if result.empty:
        lines.append("无有效规则。")
        return "\n".join(lines) + "\n"
    cols = [
        "rule_name",
        "total_trades",
        "win_rate",
        "recent_win_rate",
        "recent_return",
        "bad_year_return",
        "total_return",
        "avg_mae",
        "score",
    ]
    top = result[cols].head(20)
    lines.append("| 规则 | 交易数 | 胜率 | 近期胜率 | 近期收益 | 坏年收益 | 总收益 | MAE | 分数 |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for _, row in top.iterrows():
        lines.append(
            "| {rule} | {trades} | {win:.2f}% | {recent:.2f}% | {recent_ret:+.2f}% | {bad:+.2f}% | {total:+.2f}% | {mae:+.2f}% | {score:.2f} |".format(
                rule=row["rule_name"],
                trades=int(row["total_trades"]),
                win=float(row["win_rate"]),
                recent=float(row["recent_win_rate"]),
                recent_ret=float(row["recent_return"]),
                bad=float(row["bad_year_return"]),
                total=float(row["total_return"]),
                mae=float(row["avg_mae"]),
                score=float(row["score"]),
            )
        )
    lines.extend(
        [
            "",
            "## 说明",
            "- 本搜索使用固定 5 日收益、MFE、MAE 评估，只做候选筛选，不替代正式回测。",
            "- 进入 Top 的规则仍需接入 `consensus_profile` 后跑完整 `backtest_v2.py` 矩阵。",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Search rules on consensus snapshot before full backtests.")
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--min-trades", type=int, default=10)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = write_consensus_rule_search(args.snapshot, args.output, min_trades=args.min_trades)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
