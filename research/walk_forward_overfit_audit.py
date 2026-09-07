from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd

from historical_strategy_audit import load_matrix_files


PERIOD_SETS = {
    "train_2016_2021": ["2016", "2017", "2018", "2019", "2020", "2021"],
    "validation_2022_2024": ["2022", "2023", "2024"],
    "sealed_2025_2026H1": ["2025", "2026H1"],
}


def build_walk_forward_audit(matrix_dir: str | Path = "backtest_results") -> pd.DataFrame:
    matrix = load_matrix_files(matrix_dir)
    if matrix.empty:
        return pd.DataFrame()

    train = _split_summary(matrix, PERIOD_SETS["train_2016_2021"], "train")
    validation = _split_summary(matrix, PERIOD_SETS["validation_2022_2024"], "validation")
    sealed = _split_summary(matrix, PERIOD_SETS["sealed_2025_2026H1"], "sealed")
    combined = train.merge(validation, on="strategy", how="outer").merge(sealed, on="strategy", how="outer")
    combined = combined.fillna(0)
    combined["pre_2025_score"] = _pre_2025_score(combined)
    combined["pre_2025_pass"] = (
        (combined["train_trades"] >= 3)
        & (combined["validation_trades"] >= 1)
        & (combined["validation_loss_years"] == 0)
        & (combined["validation_return_pct"] > 0)
    )
    combined["sealed_pass"] = (
        (combined["sealed_trades"] > 0)
        & (combined["sealed_win_rate"] >= 70.0)
        & (combined["sealed_return_pct"] > 0)
        & (combined["sealed_loss_years"] == 0)
    )
    return combined.sort_values(
        ["pre_2025_pass", "pre_2025_score", "sealed_return_pct"],
        ascending=[False, False, False],
    ).reset_index(drop=True)


def write_walk_forward_audit(
    matrix_dir: str | Path = "backtest_results",
    output: str | Path | None = None,
) -> dict:
    audit = build_walk_forward_audit(matrix_dir)
    if output is None:
        output = Path("reports") / f"walk_forward_overfit_audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    audit.to_csv(output, index=False, encoding="utf-8-sig")
    output.with_suffix(".md").write_text(_format_markdown(audit, output), encoding="utf-8")
    return {
        "output": str(output),
        "rows": int(len(audit)),
        "pre_2025_pass": int(audit["pre_2025_pass"].sum()) if not audit.empty else 0,
        "sealed_pass": int(audit["sealed_pass"].sum()) if not audit.empty else 0,
    }


def _split_summary(matrix: pd.DataFrame, periods: list[str], prefix: str) -> pd.DataFrame:
    scoped = matrix[matrix["period"].astype(str).isin(periods)].copy()
    rows = []
    for strategy, group in scoped.groupby("strategy", sort=False):
        active = group[group["total_trades"].fillna(0) > 0]
        trades = int(active["total_trades"].fillna(0).sum())
        rows.append(
            {
                "strategy": strategy,
                f"{prefix}_trades": trades,
                f"{prefix}_active_years": int(len(active)),
                f"{prefix}_positive_years": int((active["total_return_pct"] > 0).sum()),
                f"{prefix}_loss_years": int((active["total_return_pct"] < 0).sum()),
                f"{prefix}_win_rate": _weighted(active, "win_rate", "total_trades"),
                f"{prefix}_return_pct": round(float(group["total_return_pct"].fillna(0).sum()), 2),
                f"{prefix}_hit3_rate": _weighted(active, "hit_3pct_rate", "total_trades"),
                f"{prefix}_worst_year_return": round(float(active["total_return_pct"].min()) if len(active) else 0.0, 2),
            }
        )
    return pd.DataFrame(rows)


def _weighted(df: pd.DataFrame, value_col: str, weight_col: str) -> float:
    if df.empty:
        return 0.0
    weights = pd.to_numeric(df[weight_col], errors="coerce").fillna(0.0)
    values = pd.to_numeric(df[value_col], errors="coerce").fillna(0.0)
    total = float(weights.sum())
    if total <= 0:
        return 0.0
    return round(float((values * weights).sum() / total), 2)


def _pre_2025_score(df: pd.DataFrame) -> pd.Series:
    return (
        df["train_win_rate"] * 0.55
        + df["train_return_pct"] * 0.25
        + df["train_hit3_rate"] * 0.25
        + df["train_trades"].clip(upper=40) * 0.35
        + df["validation_win_rate"] * 0.75
        + df["validation_return_pct"] * 0.35
        + df["validation_hit3_rate"] * 0.30
        + df["validation_trades"].clip(upper=20) * 0.45
        - df["train_loss_years"] * 45.0
        - df["validation_loss_years"] * 70.0
    ).round(4)


def _format_markdown(audit: pd.DataFrame, output: Path) -> str:
    if audit.empty:
        return "# Walk-forward 防过拟合审计\n\n无可用矩阵数据。\n"

    display_cols = [
        "strategy",
        "train_trades",
        "train_win_rate",
        "train_return_pct",
        "train_loss_years",
        "validation_trades",
        "validation_win_rate",
        "validation_return_pct",
        "validation_loss_years",
        "pre_2025_score",
        "sealed_trades",
        "sealed_win_rate",
        "sealed_return_pct",
        "sealed_loss_years",
        "sealed_pass",
    ]
    passed = audit[audit["pre_2025_pass"]].head(20)
    key = audit[
        audit["strategy"].isin(
            [
                "v35_consensus_cautious_high_pattern_top1_hold3",
                "v35_consensus_cautious_high_pattern_top2_hold3",
                "v39_consensus_strong_rank_top1_hold3",
                "v40_dual_layer_gap_fill_top1_hold3",
                "v40_dual_layer_gap_fill_top2_hold3",
            ]
        )
    ]
    lines = [
        "# Walk-forward 防过拟合审计",
        "",
        f"- CSV: `{output.as_posix()}`",
        "- 训练段：2016-2021",
        "- 验证段：2022-2024",
        "- 封存段：2025 + 2026H1",
        "",
        "## 只用 2025 前数据筛出的候选",
        "",
        passed[display_cols].to_markdown(index=False),
        "",
        "## 关键版本",
        "",
        key[display_cols].to_markdown(index=False),
        "",
        "## 解释",
        "",
        "- `pre_2025_score` 只使用训练段和验证段，不使用封存段。",
        "- `sealed_pass` 是打开 2025/2026H1 后的结果，用来观察是否疑似过拟合。",
        "- 该报告只做研究排序，不改变线上策略。",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build walk-forward anti-overfit audit from ten-year matrices.")
    parser.add_argument("--matrix-dir", default="backtest_results")
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    summary = write_walk_forward_audit(
        matrix_dir=args.matrix_dir,
        output=args.output or None,
    )
    print(summary)


if __name__ == "__main__":
    main()
