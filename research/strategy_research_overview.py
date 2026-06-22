#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""端午策略研究总览。

这个脚本只读取已有回测、审计和信号资产，生成 research 报告；
不修改 main.py 默认策略，不写入交易数据库，不生成任何交易执行动作。
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd


SHORT_BASELINE = "profile_v4_adaptive_quality_v9_sector_quality_guard + baseline exit + Top3"
LONGTERM_RESEARCH = "longterm_quality_lifecycle_v18_market_sync"
DEFAULT_OUTPUT = Path("reports") / "research" / "dragon_boat_research_overview.md"


def build_research_overview(root: str | Path = ".") -> dict:
    """Build a read-only map of existing strategy research evidence."""
    root_path = Path(root)
    short = summarize_short_assets(root_path / "backtest_results")
    longterm = summarize_longterm_assets(root_path / "reports")
    report_assets = summarize_report_assets(root_path / "reports")
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "principles": {
            "short_live_baseline": SHORT_BASELINE,
            "longterm_research_profile": LONGTERM_RESEARCH,
            "live_defaults_changed": False,
            "auto_trading": False,
        },
        "short": short,
        "longterm": longterm,
        "report_assets": report_assets,
        "next_questions": [
            "短线 v9 的 score、资金、板块、形态、回撤因子在不同区间是否稳定正相关？",
            "长线 v18 的问题主要来自股票池过宽、入池时点、市场同步过滤，还是出池规则？",
            "哪些候选策略只在单一区间有效，需要标记为过拟合风险？",
        ],
    }


def summarize_short_assets(backtest_dir: Path) -> dict:
    files = _sorted_files(backtest_dir, "ic_short_*.csv")
    latest = _latest_readable_csv(files)
    summary = {
        "latest_ic_file": latest.name if latest else None,
        "largest_ic_file": None,
        "ic_file_count": len(files),
        "sample_count": 0,
        "largest_sample_count": 0,
        "trade_date_count": 0,
        "avg_score": None,
        "avg_ret_5d": None,
        "win_rate_5d": None,
        "avg_mfe": None,
        "avg_mae": None,
        "factor_columns": [],
        "candidate_files": [path.name for path in files[:8]],
    }
    if latest is None:
        return summary

    largest_path, largest_count = _largest_csv(files)
    summary["largest_ic_file"] = largest_path.name if largest_path else None
    summary["largest_sample_count"] = largest_count
    df = _read_csv(latest)
    if df.empty:
        return summary
    summary["sample_count"] = int(len(df))
    if "select_date" in df.columns:
        summary["trade_date_count"] = int(df["select_date"].nunique())
    summary["avg_score"] = _mean(df, "score")
    summary["avg_ret_5d"] = _mean(df, "ret_5d")
    summary["win_rate_5d"] = _positive_ratio(df, "ret_5d")
    summary["avg_mfe"] = _mean_first_existing(df, ["mfe_pct", "mfe"])
    summary["avg_mae"] = _mean_first_existing(df, ["mae_pct", "mae"])
    summary["factor_columns"] = sorted([col for col in df.columns if str(col).startswith("factor_")])
    return summary


def summarize_longterm_assets(reports_dir: Path) -> dict:
    files = _sorted_files(reports_dir, "longterm_pool_quality_*_v18_market_sync_full.csv")
    period_rows = []
    combined = []
    for path in files:
        df = _read_csv(path)
        period = _period_from_longterm_file(path)
        if df.empty:
            period_rows.append(_empty_period(period, path))
            continue
        row = {
            "period": period,
            "file": path.name,
            "sample_count": int(len(df)),
            "avg_score": _mean_first_existing(df, ["longterm_score", "score"]),
            "avg_ret_10d": _mean(df, "ret_10d"),
            "avg_ret_40d": _mean(df, "ret_40d"),
            "avg_ret_80d": _mean(df, "ret_80d"),
            "win_rate_80d": _positive_ratio(df, "ret_80d"),
            "outperform_80d": _positive_ratio(df, "outperform_80d"),
            "avg_mae_80d": _mean(df, "mae_80d"),
            "avg_mfe_80d": _mean(df, "mfe_80d"),
        }
        period_rows.append(row)
        combined.append(df)

    all_df = pd.concat(combined, ignore_index=True) if combined else pd.DataFrame()
    return {
        "profile": LONGTERM_RESEARCH,
        "file_count": len(files),
        "period_count": len([row for row in period_rows if row.get("sample_count", 0) > 0]),
        "sample_count": int(len(all_df)),
        "avg_ret_80d": _mean(all_df, "ret_80d"),
        "win_rate_80d": _positive_ratio(all_df, "ret_80d"),
        "outperform_80d": _positive_ratio(all_df, "outperform_80d"),
        "periods": sorted(period_rows, key=lambda item: str(item.get("period") or "")),
    }


def summarize_report_assets(reports_dir: Path) -> dict:
    if not reports_dir.exists():
        return {"candidate_rank_reports": [], "factor_stability_reports": [], "longterm_research_reports": []}
    return {
        "candidate_rank_reports": _report_names(reports_dir, "candidate_rank_diagnostics_*"),
        "factor_stability_reports": _report_names(reports_dir, "longterm_factor_stability*"),
        "longterm_research_reports": _report_names(reports_dir, "longterm_pool_*v18_market_sync*"),
    }


def write_research_overview(root: str | Path = ".", output: str | Path = DEFAULT_OUTPUT) -> dict:
    overview = build_research_overview(root=root)
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_format_markdown(overview), encoding="utf-8")
    output_path.with_suffix(".json").write_text(json.dumps(overview, ensure_ascii=False, indent=2), encoding="utf-8")
    return overview


def _format_markdown(overview: dict) -> str:
    short = overview["short"]
    longterm = overview["longterm"]
    lines = [
        "# 端午策略研究总览",
        "",
        "## 研究边界",
        f"- 短线正式版保持：`{overview['principles']['short_live_baseline']}`。",
        f"- 长线当前研究版保持：`{overview['principles']['longterm_research_profile']}`。",
        "- 本报告只做只读研究总览，不改变 `main.py` 默认策略，不包含任何自动交易。",
        "",
        "## 短线 v9 证据地图",
        f"- 最新 IC 候选文件：`{short.get('latest_ic_file') or 'NA'}`。",
        f"- 最大样本 IC 文件：`{short.get('largest_ic_file') or 'NA'}`；样本数：`{short.get('largest_sample_count', 0)}`。",
        f"- 可用 `ic_short_*.csv` 文件数：`{short.get('ic_file_count', 0)}`。",
        f"- 最新样本数：`{short.get('sample_count', 0)}`；选股日数：`{short.get('trade_date_count', 0)}`。",
        f"- 5日均收益：`{_pct(short.get('avg_ret_5d'))}`；5日胜率：`{_pct(short.get('win_rate_5d'), ratio=True)}`。",
        f"- 平均 MFE/MAE：`{_pct(short.get('avg_mfe'))}` / `{_pct(short.get('avg_mae'))}`。",
        f"- 可审计因子列：`{', '.join(short.get('factor_columns') or []) or 'NA'}`。",
        "",
        "## 长线 v18 证据地图",
        f"- 半年度质量审计文件数：`{longterm.get('file_count', 0)}`；有效阶段数：`{longterm.get('period_count', 0)}`。",
        f"- 样本总数：`{longterm.get('sample_count', 0)}`。",
        f"- 80日均收益：`{_pct(longterm.get('avg_ret_80d'))}`；80日胜率：`{_pct(longterm.get('win_rate_80d'), ratio=True)}`；跑赢比例：`{_pct(longterm.get('outperform_80d'), ratio=True)}`。",
        "",
        "| 阶段 | 样本 | 80日均收益 | 80日胜率 | 跑赢比例 | 80日MAE | 文件 |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in longterm.get("periods") or []:
        lines.append(
            "| {period} | {sample_count} | {ret} | {win} | {beat} | {mae} | `{file}` |".format(
                period=row.get("period") or "NA",
                sample_count=row.get("sample_count", 0),
                ret=_pct(row.get("avg_ret_80d")),
                win=_pct(row.get("win_rate_80d"), ratio=True),
                beat=_pct(row.get("outperform_80d"), ratio=True),
                mae=_pct(row.get("avg_mae_80d")),
                file=row.get("file") or "NA",
            )
        )

    lines.extend(
        [
            "",
            "## 下一步问题",
        ]
    )
    for question in overview.get("next_questions") or []:
        lines.append(f"- {question}")
    lines.extend(
        [
            "",
            "## 初步研究动作",
            "- 先做短线因子稳定性，不直接尝试改权重。",
            "- 长线先诊断分数和 10/40/80 日收益是否同向，再决定是否需要新的 research profile。",
            "- 任何候选策略只标记为“进入验证”，不直接上线。",
        ]
    )
    return "\n".join(lines) + "\n"


def _sorted_files(directory: Path, pattern: str) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(directory.glob(pattern), key=lambda path: path.name, reverse=True)


def _latest_readable_csv(files: Iterable[Path]) -> Path | None:
    for path in files:
        if not _read_csv(path).empty:
            return path
    return None


def _largest_csv(files: Iterable[Path]) -> tuple[Path | None, int]:
    best_path = None
    best_count = 0
    for path in files:
        df = _read_csv(path)
        count = int(len(df))
        if count > best_count:
            best_path = path
            best_count = count
    return best_path, best_count


def _read_csv(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path, encoding="utf-8-sig")
    except (pd.errors.EmptyDataError, FileNotFoundError, OSError, UnicodeDecodeError):
        return pd.DataFrame()


def _report_names(directory: Path, pattern: str) -> list[str]:
    return [path.name for path in sorted(directory.glob(pattern), key=lambda item: item.stat().st_mtime, reverse=True)[:12]]


def _period_from_longterm_file(path: Path) -> str:
    match = re.search(r"longterm_pool_quality_(.+?)_v18_market_sync_full", path.stem)
    return match.group(1) if match else path.stem


def _empty_period(period: str, path: Path) -> dict:
    return {
        "period": period,
        "file": path.name,
        "sample_count": 0,
        "avg_score": None,
        "avg_ret_10d": None,
        "avg_ret_40d": None,
        "avg_ret_80d": None,
        "win_rate_80d": None,
        "outperform_80d": None,
        "avg_mae_80d": None,
        "avg_mfe_80d": None,
    }


def _mean(df: pd.DataFrame, column: str) -> float | None:
    if df.empty or column not in df.columns:
        return None
    values = pd.to_numeric(df[column], errors="coerce").dropna()
    return round(float(values.mean()), 4) if not values.empty else None


def _mean_first_existing(df: pd.DataFrame, columns: list[str]) -> float | None:
    for column in columns:
        value = _mean(df, column)
        if value is not None:
            return value
    return None


def _positive_ratio(df: pd.DataFrame, column: str) -> float | None:
    if df.empty or column not in df.columns:
        return None
    values = pd.to_numeric(df[column], errors="coerce").dropna()
    if values.empty:
        return None
    return round(float((values > 0).mean()), 4)


def _pct(value, ratio: bool = False) -> str:
    if value is None:
        return "NA"
    number = float(value) * 100 if ratio else float(value)
    return f"{number:+.2f}%"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成端午策略研究总览，不改变线上策略。")
    parser.add_argument("--root", type=Path, default=Path("."), help="项目根目录，默认当前目录")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Markdown 输出路径")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    overview = write_research_overview(root=args.root, output=args.output)
    print(f"Report written: {args.output}")
    print(f"short_samples={overview['short']['sample_count']} longterm_samples={overview['longterm']['sample_count']}")


if __name__ == "__main__":
    main()
