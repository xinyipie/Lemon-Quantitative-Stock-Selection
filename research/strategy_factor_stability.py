#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Research-only factor stability audit for short v9 and long v18.

This module reads existing CSV outputs and writes reports under reports/research.
It must not change live strategy defaults or generate trading instructions.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

import pandas as pd


DEFAULT_OUTPUT = Path("reports") / "research" / "dragon_boat_factor_stability.md"
SHORT_TARGET = "ret_5d"
LONGTERM_TARGET = "ret_80d"
SHORT_PROFILE_FILTER = "profile_v9_sector_quality_guard"
SHORT_FACTOR_PREFIXES = ("factor_",)
LONGTERM_FACTOR_COLUMNS = (
    "longterm_score",
    "score_momentum",
    "quality_rank_score",
    "pool_rank_score",
    "score_flow",
    "score_rs",
    "score_fin",
    "score_entry",
    "trend_strength",
    "industry_rs",
    "roe",
    "debt_ratio",
    "netprofit_yoy",
    "profit_growth_accel",
    "price_vs_ma60",
    "drawdown_from_high",
    "volume_ratio",
    "turnover",
    "total_mv",
    "circ_mv",
    "pe_ttm",
    "pb",
    "dv_ratio",
    "volatility",
)


def build_factor_stability(
    root: str | Path = ".",
    min_periods: int = 2,
    min_abs_corr: float = 0.08,
    max_short_files: int = 12,
    short_profile_filter: str = SHORT_PROFILE_FILTER,
) -> dict:
    root_path = Path(root)
    short_frames = _load_short_frames(
        root_path / "backtest_results",
        max_files=max_short_files,
        profile_filter=short_profile_filter,
    )
    long_frames = _load_longterm_frames(root_path / "reports")
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "rules": {
            "min_periods": min_periods,
            "min_abs_corr": min_abs_corr,
            "short_max_files": max_short_files,
            "short_profile_filter": short_profile_filter,
            "note": "classification is correlation-based research evidence, not a trading signal",
        },
        "short": _analyze_frames(
            frames=short_frames,
            target=SHORT_TARGET,
            factor_columns=_short_factor_columns(short_frames),
            min_periods=min_periods,
            min_abs_corr=min_abs_corr,
        ),
        "longterm": _analyze_frames(
            frames=long_frames,
            target=LONGTERM_TARGET,
            factor_columns=list(LONGTERM_FACTOR_COLUMNS),
            min_periods=min_periods,
            min_abs_corr=min_abs_corr,
        ),
    }


def write_factor_stability_report(
    root: str | Path = ".",
    output: str | Path = DEFAULT_OUTPUT,
    min_periods: int = 2,
    min_abs_corr: float = 0.08,
    max_short_files: int = 12,
    short_profile_filter: str = SHORT_PROFILE_FILTER,
) -> dict:
    result = build_factor_stability(
        root=root,
        min_periods=min_periods,
        min_abs_corr=min_abs_corr,
        max_short_files=max_short_files,
        short_profile_filter=short_profile_filter,
    )
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_format_markdown(result), encoding="utf-8")
    output_path.with_suffix(".json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def _load_short_frames(backtest_dir: Path, max_files: int, profile_filter: str) -> list[dict]:
    frames = []
    files = sorted(backtest_dir.glob("ic_short_*.csv"), key=lambda path: path.stat().st_size, reverse=True) if backtest_dir.exists() else []
    for path in files:
        df = _read_csv(path)
        if df.empty or SHORT_TARGET not in df.columns:
            continue
        if not _matches_profile(df, profile_filter):
            continue
        frames.append({"period": _short_period(path), "file": path.name, "df": df})
        if len(frames) >= max_files:
            break
    return frames


def _matches_profile(df: pd.DataFrame, profile_filter: str) -> bool:
    if not profile_filter or "factor_profile" not in df.columns:
        return True
    profiles = set(df["factor_profile"].dropna().astype(str).unique())
    return bool(profiles and profile_filter in profiles)


def _load_longterm_frames(reports_dir: Path) -> list[dict]:
    frames = []
    files = sorted(reports_dir.glob("longterm_pool_quality_*_v18_market_sync_full.csv"), key=lambda path: path.name) if reports_dir.exists() else []
    for path in files:
        df = _read_csv(path)
        if df.empty or LONGTERM_TARGET not in df.columns:
            continue
        frames.append({"period": _longterm_period(path), "file": path.name, "df": df})
    return frames


def _short_factor_columns(frames: list[dict]) -> list[str]:
    columns = set()
    for item in frames:
        df = item["df"]
        for column in df.columns:
            text = str(column)
            if text in {"score", "original_score", "score_base"} or any(text.startswith(prefix) for prefix in SHORT_FACTOR_PREFIXES):
                columns.add(text)
    return sorted(columns)


def _analyze_frames(
    frames: list[dict],
    target: str,
    factor_columns: list[str],
    min_periods: int,
    min_abs_corr: float,
) -> dict:
    factor_rows = []
    for factor in factor_columns:
        period_stats = []
        for item in frames:
            df = item["df"]
            corr = _corr(df, factor, target)
            if corr is None:
                continue
            period_stats.append(
                {
                    "period": item["period"],
                    "file": item["file"],
                    "sample_count": int(len(df[[factor, target]].dropna())),
                    "corr": corr,
                }
            )
        if not period_stats:
            continue
        factor_rows.append(_summarize_factor(factor, period_stats, min_periods=min_periods, min_abs_corr=min_abs_corr))

    factor_rows.sort(key=lambda row: (row["classification_rank"], abs(row["avg_corr"]), row["period_count"]), reverse=True)
    return {
        "target": target,
        "period_count": len(frames),
        "files": [item["file"] for item in frames],
        "factors": factor_rows,
        "stable_positive": [row for row in factor_rows if row["classification"] == "stable_positive"],
        "stable_negative": [row for row in factor_rows if row["classification"] == "stable_negative"],
        "unstable": [row for row in factor_rows if row["classification"] == "unstable"],
        "weak": [row for row in factor_rows if row["classification"] == "weak"],
    }


def _summarize_factor(factor: str, period_stats: list[dict], min_periods: int, min_abs_corr: float) -> dict:
    corrs = [float(item["corr"]) for item in period_stats]
    avg_corr = round(sum(corrs) / len(corrs), 4)
    positive = [value for value in corrs if value >= min_abs_corr]
    negative = [value for value in corrs if value <= -min_abs_corr]
    classification = "weak"
    if len(corrs) >= min_periods and positive and negative:
        classification = "unstable"
    elif len(corrs) >= min_periods and len(positive) == len(corrs) and avg_corr >= min_abs_corr:
        classification = "stable_positive"
    elif len(corrs) >= min_periods and len(negative) == len(corrs) and avg_corr <= -min_abs_corr:
        classification = "stable_negative"
    return {
        "factor": factor,
        "classification": classification,
        "classification_text": _classification_text(classification),
        "classification_rank": {"stable_positive": 4, "stable_negative": 3, "unstable": 2, "weak": 1}.get(classification, 0),
        "period_count": len(corrs),
        "avg_corr": avg_corr,
        "min_corr": round(min(corrs), 4),
        "max_corr": round(max(corrs), 4),
        "positive_periods": len(positive),
        "negative_periods": len(negative),
        "periods": period_stats,
    }


def _corr(df: pd.DataFrame, factor: str, target: str) -> float | None:
    if factor not in df.columns or target not in df.columns:
        return None
    pair = df[[factor, target]].apply(pd.to_numeric, errors="coerce").dropna()
    if len(pair) < 4:
        return None
    if pair[factor].nunique() < 2 or pair[target].nunique() < 2:
        return None
    value = pair[factor].corr(pair[target], method="spearman")
    if pd.isna(value):
        return None
    return round(float(value), 4)


def _format_markdown(result: dict) -> str:
    lines = [
        "# 因子稳定性研究",
        "",
        "## 研究边界",
        "- 本报告只分析历史 CSV 中因子与收益的相关性，不改变线上策略。",
        "- 分类基于跨文件/跨阶段 Spearman 相关，不代表可直接交易。",
        f"- 稳定阈值：至少 `{result['rules']['min_periods']}` 个区间，相关绝对值不低于 `{result['rules']['min_abs_corr']}`。",
        "",
    ]
    lines.extend(_section_markdown("短线 v9", result["short"]))
    lines.extend(_section_markdown("长线 v18", result["longterm"]))
    lines.extend(
        [
            "## 研究解释",
            "- `稳定正相关`：可进入下一轮候选，但仍需跨区间收益验证。",
            "- `稳定负相关`：可能是反向约束或惩罚因子，需要结合交易逻辑解释。",
            "- `不稳定`：不同区间方向翻转，优先视为过拟合风险。",
            "- `弱相关`：当前证据不足，不建议单独作为调权依据。",
        ]
    )
    return "\n".join(lines) + "\n"


def _section_markdown(title: str, section: dict) -> list[str]:
    lines = [
        f"## {title}",
        f"- 目标列：`{section.get('target')}`；有效区间/文件数：`{section.get('period_count', 0)}`。",
        f"- 稳定正相关：`{len(section.get('stable_positive') or [])}` 个；稳定负相关：`{len(section.get('stable_negative') or [])}` 个；不稳定：`{len(section.get('unstable') or [])}` 个。",
        "",
    ]
    for label, key in [("稳定正相关", "stable_positive"), ("稳定负相关", "stable_negative"), ("不稳定", "unstable")]:
        rows = section.get(key) or []
        lines.append(f"### {label}")
        if not rows:
            lines.append("- 暂无")
        else:
            for row in rows[:12]:
                lines.append(
                    f"- `{row['factor']}`：avg_corr `{row['avg_corr']:+.3f}`，"
                    f"range `{row['min_corr']:+.3f}`~`{row['max_corr']:+.3f}`，"
                    f"periods `{row['period_count']}`"
                )
        lines.append("")
    return lines


def _classification_text(classification: str) -> str:
    return {
        "stable_positive": "稳定正相关",
        "stable_negative": "稳定负相关",
        "unstable": "不稳定/方向翻转",
        "weak": "弱相关/证据不足",
    }.get(classification, classification)


def _read_csv(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path, encoding="utf-8-sig")
    except (pd.errors.EmptyDataError, FileNotFoundError, OSError, UnicodeDecodeError):
        return pd.DataFrame()


def _short_period(path: Path) -> str:
    match = re.search(r"ic_short_(\d{8})", path.stem)
    return match.group(1) if match else path.stem


def _longterm_period(path: Path) -> str:
    match = re.search(r"longterm_pool_quality_(.+?)_v18_market_sync_full", path.stem)
    return match.group(1) if match else path.stem


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成端午策略研究的短线/长线因子稳定性报告。")
    parser.add_argument("--root", type=Path, default=Path("."), help="项目根目录")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Markdown 输出路径")
    parser.add_argument("--min-periods", type=int, default=2)
    parser.add_argument("--min-abs-corr", type=float, default=0.08)
    parser.add_argument("--max-short-files", type=int, default=12)
    parser.add_argument("--short-profile-filter", default=SHORT_PROFILE_FILTER)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = write_factor_stability_report(
        root=args.root,
        output=args.output,
        min_periods=args.min_periods,
        min_abs_corr=args.min_abs_corr,
        max_short_files=args.max_short_files,
        short_profile_filter=args.short_profile_filter,
    )
    print(f"Report written: {args.output}")
    print(
        f"short_factors={len(result['short']['factors'])} "
        f"longterm_factors={len(result['longterm']['factors'])}"
    )


if __name__ == "__main__":
    main()
