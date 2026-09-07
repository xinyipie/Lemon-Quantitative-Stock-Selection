from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

import pandas as pd


MATRIX_PATTERN = "ten_year_strategy_matrix_*.csv"
RECENT_PERIODS = ("2025", "2026H1")
DISPLAY_COLUMNS = [
    "rank",
    "tier",
    "strategy",
    "total_trades",
    "active_years",
    "positive_years",
    "loss_years",
    "weighted_win_rate",
    "active_avg_win_rate",
    "total_return_pct",
    "recent_win_rate",
    "recent_return_pct",
    "avg_hit_3pct_rate",
    "avg_hit_5pct_rate",
    "avg_mae_pct",
    "worst_year_return_pct",
    "robust_score",
]


def load_matrix_files(matrix_dir: str | Path, pattern: str = MATRIX_PATTERN) -> pd.DataFrame:
    matrix_dir = Path(matrix_dir)
    frames = []
    for path in sorted(matrix_dir.glob(pattern), key=_matrix_sort_key):
        df = pd.read_csv(path, encoding="utf-8-sig")
        if df.empty:
            continue
        df = df.copy()
        df["source_file"] = path.name
        df["source_stamp"] = _matrix_stamp(path)
        frames.append(df)
    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    combined = _coerce_matrix(combined)
    combined = combined.sort_values(["strategy", "period", "source_stamp", "source_file"])
    return combined.drop_duplicates(["strategy", "period"], keep="last").reset_index(drop=True)


def build_strategy_audit(
    matrix: pd.DataFrame,
    min_main_trades: int = 20,
    min_confidence_trades: int = 10,
) -> pd.DataFrame:
    if matrix.empty:
        return pd.DataFrame(columns=DISPLAY_COLUMNS)

    work = _coerce_matrix(matrix)
    rows = []
    for strategy, group in work.groupby("strategy", sort=False):
        rows.append(_summarize_strategy(strategy, group, min_main_trades, min_confidence_trades))

    result = pd.DataFrame(rows)
    result = result.sort_values(
        ["tier_order", "robust_score", "total_return_pct", "total_trades"],
        ascending=[True, False, False, False],
    ).reset_index(drop=True)
    result["rank"] = range(1, len(result) + 1)
    return result[DISPLAY_COLUMNS + ["source_files"]]


def write_strategy_audit(
    matrix_dir: str | Path = "backtest_results",
    output: str | Path | None = None,
    min_main_trades: int = 20,
    min_confidence_trades: int = 10,
) -> dict:
    matrix = load_matrix_files(matrix_dir)
    audit = build_strategy_audit(
        matrix,
        min_main_trades=min_main_trades,
        min_confidence_trades=min_confidence_trades,
    )
    if output is None:
        output = Path("reports") / f"historical_strategy_audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    audit.to_csv(output, index=False, encoding="utf-8-sig")

    summary = _summary(audit, matrix, output)
    output.with_suffix(".json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    output.with_suffix(".md").write_text(_format_markdown(audit, summary), encoding="utf-8")
    return summary


def _summarize_strategy(
    strategy: str,
    group: pd.DataFrame,
    min_main_trades: int,
    min_confidence_trades: int,
) -> dict:
    trades = group["total_trades"].clip(lower=0)
    active = group[trades > 0]
    total_trades = int(trades.sum())
    total_return = float(group["total_return_pct"].sum())
    positive_years = int((active["total_return_pct"] > 0).sum())
    loss_years = int((active["total_return_pct"] < 0).sum())
    active_years = int(len(active))
    weighted_win = _weighted_average(active, "win_rate", "total_trades")
    active_avg_win = float(active["win_rate"].mean()) if active_years else 0.0
    recent = group[group["period"].astype(str).isin(RECENT_PERIODS)]
    recent_active = recent[recent["total_trades"] > 0]
    recent_trades = int(recent["total_trades"].clip(lower=0).sum())
    recent_win = _weighted_average(recent_active, "win_rate", "total_trades")
    recent_return = float(recent["total_return_pct"].sum()) if not recent.empty else 0.0
    avg_hit_3 = _weighted_average(active, "hit_3pct_rate", "total_trades")
    avg_hit_5 = _weighted_average(active, "hit_5pct_rate", "total_trades")
    avg_mae = _weighted_average(active, "avg_mae_pct", "total_trades")
    worst_year_return = float(active["total_return_pct"].min()) if active_years else 0.0
    score = _robust_score(
        total_trades=total_trades,
        active_years=active_years,
        positive_years=positive_years,
        loss_years=loss_years,
        weighted_win=weighted_win,
        active_avg_win=active_avg_win,
        total_return=total_return,
        recent_trades=recent_trades,
        recent_win=recent_win,
        recent_return=recent_return,
        avg_hit_3=avg_hit_3,
        avg_hit_5=avg_hit_5,
        avg_mae=avg_mae,
        worst_year_return=worst_year_return,
        min_main_trades=min_main_trades,
    )
    tier, tier_order = _classify_tier(
        total_trades=total_trades,
        active_years=active_years,
        recent_trades=recent_trades,
        loss_years=loss_years,
        total_return=total_return,
        recent_return=recent_return,
        recent_win=recent_win,
        avg_hit_3=avg_hit_3,
        min_main_trades=min_main_trades,
        min_confidence_trades=min_confidence_trades,
    )
    return {
        "tier": tier,
        "tier_order": tier_order,
        "strategy": strategy,
        "total_trades": total_trades,
        "active_years": active_years,
        "positive_years": positive_years,
        "loss_years": loss_years,
        "weighted_win_rate": round(weighted_win, 2),
        "active_avg_win_rate": round(active_avg_win, 2),
        "total_return_pct": round(total_return, 2),
        "recent_trades": recent_trades,
        "recent_win_rate": round(recent_win, 2),
        "recent_return_pct": round(recent_return, 2),
        "avg_hit_3pct_rate": round(avg_hit_3, 2),
        "avg_hit_5pct_rate": round(avg_hit_5, 2),
        "avg_mae_pct": round(avg_mae, 2),
        "worst_year_return_pct": round(worst_year_return, 2),
        "robust_score": round(score, 4),
        "source_files": ";".join(sorted(group["source_file"].dropna().astype(str).unique())),
    }


def _classify_tier(
    *,
    total_trades: int,
    active_years: int,
    recent_trades: int,
    loss_years: int,
    total_return: float,
    recent_return: float,
    recent_win: float,
    avg_hit_3: float,
    min_main_trades: int,
    min_confidence_trades: int,
) -> tuple[str, int]:
    clean_profit = loss_years == 0 and total_return > 0 and recent_return > 0
    recent_clean = recent_trades > 0 and recent_win >= 70.0 and avg_hit_3 >= 70.0
    if total_trades >= min_main_trades and clean_profit and recent_clean:
        return "main_candidate", 0
    if total_trades >= min_confidence_trades and active_years >= 4 and clean_profit and recent_clean:
        return "high_confidence", 1
    if total_return > 0 and recent_return > 0:
        return "watch_only", 2
    return "reject", 3


def _robust_score(
    *,
    total_trades: int,
    active_years: int,
    positive_years: int,
    loss_years: int,
    weighted_win: float,
    active_avg_win: float,
    total_return: float,
    recent_trades: int,
    recent_win: float,
    recent_return: float,
    avg_hit_3: float,
    avg_hit_5: float,
    avg_mae: float,
    worst_year_return: float,
    min_main_trades: int,
) -> float:
    trade_penalty = max(0, min_main_trades - total_trades) * 3.0
    recent_penalty = 35.0 if recent_trades == 0 else max(0.0, 70.0 - recent_win) * 1.2
    loss_penalty = loss_years * 35.0 + abs(min(0.0, worst_year_return)) * 2.5
    mae_penalty = abs(min(0.0, avg_mae)) * 2.0
    return (
        weighted_win * 0.75
        + active_avg_win * 0.45
        + min(total_return, 220.0) * 0.28
        + recent_win * 0.6
        + min(recent_return, 160.0) * 0.25
        + avg_hit_3 * 0.35
        + avg_hit_5 * 0.15
        + min(total_trades, 80) * 0.45
        + active_years * 5.0
        + positive_years * 5.0
        - trade_penalty
        - recent_penalty
        - loss_penalty
        - mae_penalty
    )


def _weighted_average(df: pd.DataFrame, value_col: str, weight_col: str) -> float:
    if df.empty or value_col not in df.columns or weight_col not in df.columns:
        return 0.0
    weights = pd.to_numeric(df[weight_col], errors="coerce").fillna(0.0).clip(lower=0.0)
    values = pd.to_numeric(df[value_col], errors="coerce").fillna(0.0)
    total = float(weights.sum())
    if total <= 0:
        return 0.0
    return float((values * weights).sum() / total)


def _coerce_matrix(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    numeric_cols = [
        "returncode",
        "total_trades",
        "win_rate",
        "total_return_pct",
        "max_drawdown_pct",
        "avg_profit_after_fee",
        "max_consecutive_loss",
        "avg_mfe_pct",
        "avg_mae_pct",
        "hit_3pct_rate",
        "hit_5pct_rate",
    ]
    for col in numeric_cols:
        if col not in out.columns:
            out[col] = 0.0
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)
    for col in ("strategy", "period", "source_file"):
        if col not in out.columns:
            out[col] = ""
        out[col] = out[col].fillna("").astype(str)
    if "source_stamp" not in out.columns:
        out["source_stamp"] = ""
    return out


def _summary(audit: pd.DataFrame, matrix: pd.DataFrame, output: Path) -> dict:
    top = audit.iloc[0].to_dict() if not audit.empty else {}
    tier_counts = audit["tier"].value_counts().to_dict() if "tier" in audit.columns else {}
    return {
        "output": str(output),
        "matrix_rows": int(len(matrix)),
        "strategy_count": int(audit["strategy"].nunique()) if "strategy" in audit.columns else 0,
        "tier_counts": {str(k): int(v) for k, v in tier_counts.items()},
        "top_strategy": top.get("strategy", ""),
        "top_tier": top.get("tier", ""),
        "top_score": top.get("robust_score", 0),
    }


def _format_markdown(audit: pd.DataFrame, summary: dict) -> str:
    lines = [
        "# 十年历史策略第一档审计",
        "",
        "## 摘要",
        f"- 输出：`{summary['output']}`",
        f"- 策略数：{summary['strategy_count']}",
        f"- 第一名：`{summary['top_strategy']}`（{summary['top_tier']}，分数 {summary['top_score']}）",
        "",
        "## 第一档榜单",
        "",
    ]
    if audit.empty:
        lines.append("没有可审计的策略矩阵。")
        return "\n".join(lines) + "\n"

    cols = DISPLAY_COLUMNS[:]
    top = audit[cols].head(20)
    lines.append("| 排名 | 档位 | 策略 | 交易数 | 活跃年 | 正收益年 | 亏损年 | 加权胜率 | 活跃均胜率 | 总收益 | 近端胜率 | 近端收益 | 3%命中 | 5%命中 | MAE | 最差年 | 分数 |")
    lines.append("|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for _, row in top.iterrows():
        lines.append(
            "| {rank} | {tier} | `{strategy}` | {trades} | {active} | {positive} | {loss} | {win:.2f}% | {active_win:.2f}% | {ret:+.2f}% | {recent_win:.2f}% | {recent_ret:+.2f}% | {hit3:.2f}% | {hit5:.2f}% | {mae:+.2f}% | {worst:+.2f}% | {score:.2f} |".format(
                rank=int(row["rank"]),
                tier=row["tier"],
                strategy=row["strategy"],
                trades=int(row["total_trades"]),
                active=int(row["active_years"]),
                positive=int(row["positive_years"]),
                loss=int(row["loss_years"]),
                win=float(row["weighted_win_rate"]),
                active_win=float(row["active_avg_win_rate"]),
                ret=float(row["total_return_pct"]),
                recent_win=float(row["recent_win_rate"]),
                recent_ret=float(row["recent_return_pct"]),
                hit3=float(row["avg_hit_3pct_rate"]),
                hit5=float(row["avg_hit_5pct_rate"]),
                mae=float(row["avg_mae_pct"]),
                worst=float(row["worst_year_return_pct"]),
                score=float(row["robust_score"]),
            )
        )
    lines.extend(
        [
            "",
            "## 档位规则",
            "- `main_candidate`：交易数达到主线门槛、无亏损活跃年份、十年与近端收益为正，且近端胜率和 3% 命中率不低于 70%。",
            "- `high_confidence`：交易数低于主线但达到高置信门槛，收益与近端质量干净。",
            "- `watch_only`：收益为正但样本、胜率或年份稳定性不足，只能观察。",
            "- `reject`：总收益或近端收益为负，或防守年份亏损明显。",
        ]
    )
    return "\n".join(lines) + "\n"


def _matrix_sort_key(path: Path) -> tuple[str, str]:
    return (_matrix_stamp(path), path.name)


def _matrix_stamp(path: Path) -> str:
    match = re.search(r"ten_year_strategy_matrix_(\d{8}_\d{6})", path.name)
    if match:
        return match.group(1)
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y%m%d_%H%M%S")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit all ten-year strategy matrix files into robust tiers.")
    parser.add_argument("--matrix-dir", type=Path, default=Path("backtest_results"))
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--min-main-trades", type=int, default=20)
    parser.add_argument("--min-confidence-trades", type=int, default=10)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = write_strategy_audit(
        matrix_dir=args.matrix_dir,
        output=args.output,
        min_main_trades=args.min_main_trades,
        min_confidence_trades=args.min_confidence_trades,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
