"""端午候选策略离线模拟。

这个脚本只读取历史候选与审计 CSV，不修改线上策略配置，也不写入业务数据库。
目标是把“看起来可能有用”的小改动放进统一口径里比较，避免凭单一区间收益做判断。
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd


DEFAULT_OUTPUT = Path("reports") / "research" / "dragon_boat_candidate_simulation.md"
SHORT_PROFILE_FILTER = "profile_v9_sector_quality_guard"
SHORT_TARGET = "ret_5d"
LONGTERM_TARGET = "ret_80d"


@dataclass(frozen=True)
class FilterRule:
    column: str
    op: str
    value: float


@dataclass(frozen=True)
class CandidateRule:
    name: str
    label: str
    mode: str
    topn: int
    score_weights: dict[str, float]
    filters: tuple[FilterRule, ...]
    logic: str
    rationale: str


def _short_candidate_rules() -> list[CandidateRule]:
    return [
        CandidateRule(
            name="short_v9_baseline_top3",
            label="短线 v9 基准 Top3",
            mode="short",
            topn=3,
            score_weights={"score": 1.0},
            filters=(),
            logic="按 v9 score 降序，每个选股日取 Top3。",
            rationale="正式短线基准，用来衡量其他研究假设是否真的改善。",
        ),
        CandidateRule(
            name="short_v9_top1_concentration",
            label="短线 v9 Top1 收缩",
            mode="short",
            topn=1,
            score_weights={"score": 1.0},
            filters=(),
            logic="仍按 v9 score 排序，但每个选股日只取 Top1。",
            rationale="分层诊断显示头部候选更强，先测试减少宽度是否提升质量。",
        ),
        CandidateRule(
            name="short_v9_sector_flow_tiebreak_top3",
            label="短线 v9 资金/板块轻重排",
            mode="short",
            topn=3,
            score_weights={
                "score": 1.0,
                "factor_inflow": 0.03,
                "factor_sector": 0.03,
                "factor_volume_ratio": 0.01,
            },
            filters=(),
            logic="在 v9 score 上小幅叠加资金、板块和量能分，每个选股日取 Top3。",
            rationale="只做轻微二次排序，避免把单个因子强行调成主导权重。",
        ),
        CandidateRule(
            name="short_v9_quality_floor_top3",
            label="短线 v9 基础质量地板",
            mode="short",
            topn=3,
            score_weights={"score": 1.0},
            filters=(
                FilterRule("factor_inflow", ">=", 20),
                FilterRule("factor_pattern", ">=", 10),
                FilterRule("factor_volume_ratio", ">=", 15),
            ),
            logic="先要求资金、形态、量能不过低，再按 v9 score 取 Top3。",
            rationale="测试剔除明显短板候选是否能降低失败样本，但可能损失弹性。",
        ),
    ]


def _longterm_candidate_rules() -> list[CandidateRule]:
    return [
        CandidateRule(
            name="long_v18_baseline_top3",
            label="长线 v18 基准 Top3",
            mode="longterm",
            topn=3,
            score_weights={"longterm_score": 1.0},
            filters=(),
            logic="按 v18 longterm_score 降序，每个入池日取 Top3。",
            rationale="当前长线研究基准，用来观察排序是否有效。",
        ),
        CandidateRule(
            name="long_v18_top10_watchlist",
            label="长线 v18 Top10 观察池",
            mode="longterm",
            topn=10,
            score_weights={"longterm_score": 1.0},
            filters=(),
            logic="按 v18 longterm_score 降序，每个入池日保留 Top10。",
            rationale="分层诊断显示长线 Top3 未明显优于全池，先测试是否应弱化精确排序。",
        ),
        CandidateRule(
            name="long_v18_quality_floor_top10",
            label="长线 v18 财务质量地板",
            mode="longterm",
            topn=10,
            score_weights={"longterm_score": 1.0},
            filters=(
                FilterRule("roe", ">=", 5),
                FilterRule("debt_ratio", "<=", 70),
                FilterRule("netprofit_yoy", ">=", 0),
                FilterRule("industry_rs", ">=", -5),
            ),
            logic="先过滤 ROE、负债、利润增速和行业相对强度，再按 v18 score 取 Top10。",
            rationale="长线更依赖基本面和行业周期，先用宽松地板剔除质量明显不合格标的。",
        ),
        CandidateRule(
            name="long_v18_quality_rs_rerank_top10",
            label="长线 v18 质量/行业重排",
            mode="longterm",
            topn=10,
            score_weights={
                "longterm_score": 1.0,
                "industry_rs": 0.8,
                "roe": 0.3,
                "netprofit_yoy": 0.05,
                "debt_ratio": -0.1,
            },
            filters=(FilterRule("debt_ratio", "<=", 80),),
            logic="在 v18 score 上叠加行业 RS、ROE、利润增速，并轻扣高负债，取 Top10。",
            rationale="测试长线排序是否应从交易分数转向行业与财务质量的组合排序。",
        ),
    ]


def build_candidate_simulation(
    root: str | Path = ".",
    output: str | Path | None = None,
    max_short_files: int = 0,
    short_profile_filter: str = SHORT_PROFILE_FILTER,
) -> dict:
    """生成候选策略模拟结果。"""

    root = Path(root)
    short_df = _load_short_candidates(root / "backtest_results", max_short_files, short_profile_filter)
    long_df = _load_longterm_candidates(root / "reports")

    short_result = _evaluate_rule_set(
        short_df,
        rules=_short_candidate_rules(),
        target=SHORT_TARGET,
        mfe_column="mfe_pct",
        mae_column="mae_pct",
        baseline_name="short_v9_baseline_top3",
    )
    long_result = _evaluate_rule_set(
        long_df,
        rules=_longterm_candidate_rules(),
        target=LONGTERM_TARGET,
        mfe_column="mfe_80d",
        mae_column="mae_80d",
        baseline_name="long_v18_baseline_top3",
    )

    return {
        "metadata": {
            "short_profile_filter": short_profile_filter,
            "max_short_files": max_short_files,
            "output": str(output) if output else None,
            "note": "研究模拟结果不等于上线策略；2026 数据仅作参考。",
        },
        "short": short_result,
        "longterm": long_result,
    }


def write_candidate_simulation_report(
    root: str | Path = ".",
    output: str | Path = DEFAULT_OUTPUT,
    max_short_files: int = 0,
    short_profile_filter: str = SHORT_PROFILE_FILTER,
) -> dict:
    """写出候选策略模拟 Markdown 与 JSON 报告。"""

    output = Path(output)
    result = build_candidate_simulation(
        root=root,
        output=output,
        max_short_files=max_short_files,
        short_profile_filter=short_profile_filter,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(_format_markdown(result), encoding="utf-8")
    output.with_suffix(".json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result


def _load_short_candidates(
    backtest_dir: Path,
    max_files: int,
    profile_filter: str,
) -> pd.DataFrame:
    paths = sorted(
        backtest_dir.glob("ic_short_*.csv"),
        key=lambda path: (path.stat().st_mtime, path.stat().st_size),
        reverse=True,
    )
    if max_files > 0:
        paths = paths[:max_files]

    frames: list[pd.DataFrame] = []
    for path in paths:
        try:
            df = pd.read_csv(path, encoding="utf-8-sig")
        except (pd.errors.EmptyDataError, UnicodeDecodeError):
            continue
        if SHORT_TARGET not in df.columns or "score" not in df.columns or "select_date" not in df.columns:
            continue
        if profile_filter and "factor_profile" in df.columns:
            df = df[df["factor_profile"].astype(str).str.contains(profile_filter, na=False)]
        if df.empty:
            continue
        df = df.copy()
        df["source_file"] = path.name
        frames.append(df)

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    combined = _normalize_dates(combined)
    combined = _coerce_numeric(combined)
    dedupe_cols = [col for col in ["select_date", "ts_code", "score", SHORT_TARGET] if col in combined.columns]
    if dedupe_cols:
        combined = combined.drop_duplicates(subset=dedupe_cols)
    return combined


def _load_longterm_candidates(reports_dir: Path) -> pd.DataFrame:
    paths = []
    for path in reports_dir.glob("longterm_pool_quality_*_v18_market_sync_full.csv"):
        name = path.name
        if "_tail_" in name or "_Q1_" in name or "_2026Q1_" in name:
            continue
        paths.append(path)
    paths = sorted(paths, key=lambda path: path.name)

    frames: list[pd.DataFrame] = []
    for path in paths:
        try:
            df = pd.read_csv(path, encoding="utf-8-sig")
        except (pd.errors.EmptyDataError, UnicodeDecodeError):
            continue
        if df.empty or LONGTERM_TARGET not in df.columns or "select_date" not in df.columns:
            continue
        if "longterm_score" not in df.columns:
            continue
        df = df.copy()
        df["source_file"] = path.name
        frames.append(df)

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    combined = _normalize_dates(combined)
    combined = _coerce_numeric(combined)
    dedupe_cols = [col for col in ["select_date", "ts_code", "longterm_score", LONGTERM_TARGET] if col in combined.columns]
    if dedupe_cols:
        combined = combined.drop_duplicates(subset=dedupe_cols)
    return combined


def _evaluate_rule_set(
    df: pd.DataFrame,
    rules: Iterable[CandidateRule],
    target: str,
    mfe_column: str,
    mae_column: str,
    baseline_name: str,
) -> dict:
    rules = list(rules)
    if df.empty:
        return {
            "target": target,
            "sample_count": 0,
            "date_count": 0,
            "candidates": {},
            "rules": [_rule_to_dict(rule) for rule in rules],
        }

    candidates = {}
    baseline_phase_metrics: dict[str, dict] = {}
    baseline_overall: dict | None = None

    for rule in rules:
        selected = _apply_rule(df, rule)
        overall = _metrics(selected, target, mfe_column, mae_column)
        phase_metrics = {
            phase: _metrics(phase_df, target, mfe_column, mae_column)
            for phase, phase_df in selected.groupby(selected["phase"], sort=False)
        }
        candidates[rule.name] = {
            "label": rule.label,
            "topn": rule.topn,
            "logic": rule.logic,
            "rationale": rule.rationale,
            "overall": overall,
            "phases": phase_metrics,
        }
        if rule.name == baseline_name:
            baseline_overall = overall
            baseline_phase_metrics = phase_metrics

    for name, item in candidates.items():
        item["overall"]["edge_vs_baseline"] = _edge(item["overall"], baseline_overall)
        for phase, metrics in item["phases"].items():
            metrics["edge_vs_baseline"] = _edge(metrics, baseline_phase_metrics.get(phase))
        item["classification"] = _classify_candidate(item, baseline_name)

    return {
        "target": target,
        "sample_count": int(len(df)),
        "date_count": int(df["select_date"].nunique()),
        "candidates": candidates,
        "rules": [_rule_to_dict(rule) for rule in rules],
    }


def _apply_rule(df: pd.DataFrame, rule: CandidateRule) -> pd.DataFrame:
    work = df.copy()
    for filter_rule in rule.filters:
        if filter_rule.column not in work.columns:
            continue
        values = pd.to_numeric(work[filter_rule.column], errors="coerce")
        if filter_rule.op == ">=":
            work = work[values >= filter_rule.value]
        elif filter_rule.op == "<=":
            work = work[values <= filter_rule.value]
        elif filter_rule.op == ">":
            work = work[values > filter_rule.value]
        elif filter_rule.op == "<":
            work = work[values < filter_rule.value]
    if work.empty:
        return work.assign(research_score=pd.Series(dtype=float), phase=pd.Series(dtype=str))

    score = pd.Series(0.0, index=work.index)
    for column, weight in rule.score_weights.items():
        if column in work.columns:
            score = score + pd.to_numeric(work[column], errors="coerce").fillna(0) * weight
    work["research_score"] = score
    work["phase"] = work["select_date"].apply(_phase_for_date)
    work = work.sort_values(["select_date", "research_score", "ts_code"], ascending=[True, False, True])
    return work.groupby("select_date", group_keys=False).head(rule.topn).copy()


def _metrics(df: pd.DataFrame, target: str, mfe_column: str, mae_column: str) -> dict:
    if df.empty or target not in df.columns:
        return {
            "sample_count": 0,
            "date_count": 0,
            "avg_ret": None,
            "median_ret": None,
            "win_rate": None,
            "avg_mfe": None,
            "avg_mae": None,
            "risk_reward": None,
        }

    target_values = pd.to_numeric(df[target], errors="coerce").dropna()
    mfe_values = pd.to_numeric(df[mfe_column], errors="coerce").dropna() if mfe_column in df.columns else pd.Series(dtype=float)
    mae_values = pd.to_numeric(df[mae_column], errors="coerce").dropna() if mae_column in df.columns else pd.Series(dtype=float)
    avg_mfe = _round_or_none(mfe_values.mean()) if not mfe_values.empty else None
    avg_mae = _round_or_none(mae_values.mean()) if not mae_values.empty else None
    risk_reward = None
    if avg_mfe is not None and avg_mae not in (None, 0):
        risk_reward = round(avg_mfe / abs(avg_mae), 4)

    return {
        "sample_count": int(len(df)),
        "date_count": int(df["select_date"].nunique()) if "select_date" in df.columns else 0,
        "avg_ret": _round_or_none(target_values.mean()) if not target_values.empty else None,
        "median_ret": _round_or_none(target_values.median()) if not target_values.empty else None,
        "win_rate": _round_or_none((target_values > 0).mean()) if not target_values.empty else None,
        "avg_mfe": avg_mfe,
        "avg_mae": avg_mae,
        "risk_reward": risk_reward,
    }


def _classify_candidate(item: dict, baseline_name: str) -> str:
    if item["overall"]["sample_count"] == 0:
        return "no_sample"
    if item["logic"].startswith("按") and baseline_name in item.get("label", ""):
        return "baseline"

    overall_edge = item["overall"].get("edge_vs_baseline")
    validate_edge = item["phases"].get("validate_2025H2", {}).get("edge_vs_baseline")
    holdout_edge = item["phases"].get("holdout_2024H1", {}).get("edge_vs_baseline")
    sample_count = item["overall"]["sample_count"]
    if sample_count < 10:
        return "too_sparse"
    if overall_edge is None:
        return "needs_more_data"
    if validate_edge is not None and validate_edge >= 0 and (holdout_edge is None or holdout_edge >= -1) and overall_edge > 0:
        return "promising_for_validation"
    if overall_edge < -1:
        return "worse_than_baseline"
    return "mixed"


def _edge(metrics: dict, baseline: dict | None) -> float | None:
    if not baseline:
        return None
    if metrics.get("avg_ret") is None or baseline.get("avg_ret") is None:
        return None
    return round(metrics["avg_ret"] - baseline["avg_ret"], 4)


def _phase_for_date(value: int | str) -> str:
    date = int(value)
    if 20240101 <= date <= 20240630:
        return "holdout_2024H1"
    if 20240701 <= date <= 20250630:
        return "train_2024H2_2025H1"
    if 20250701 <= date <= 20251231:
        return "validate_2025H2"
    if date >= 20260101:
        return "reference_2026"
    return "other"


def _normalize_dates(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["select_date"] = pd.to_numeric(df["select_date"], errors="coerce")
    df = df[df["select_date"].notna()]
    df["select_date"] = df["select_date"].astype(int)
    return df


def _coerce_numeric(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for column in df.columns:
        if column in {"ts_code", "name", "industry", "factor_profile", "longterm_profile", "pool_type", "source_file"}:
            continue
        converted = pd.to_numeric(df[column], errors="coerce")
        if converted.notna().sum() == df[column].notna().sum():
            df[column] = converted
    return df


def _rule_to_dict(rule: CandidateRule) -> dict:
    return {
        "name": rule.name,
        "label": rule.label,
        "mode": rule.mode,
        "topn": rule.topn,
        "score_weights": rule.score_weights,
        "filters": [filter_rule.__dict__ for filter_rule in rule.filters],
        "logic": rule.logic,
        "rationale": rule.rationale,
    }


def _format_markdown(result: dict) -> str:
    lines = [
        "# 端午候选策略离线模拟",
        "",
        "## 先看结论",
        "- 本报告只做 research profile 离线模拟，不改变 `main.py` 默认上线策略。",
        "- 结果按训练、验证、留出、2026参考区间拆开，避免只看单一区间收益。",
        "- 任何候选如果进入下一轮，也只应先进入验证，不直接上线。",
        "",
    ]

    lines.extend(_format_candidate_section("短线 v9 候选", result["short"]))
    lines.extend(_format_candidate_section("长线 v18 候选", result["longterm"]))
    return "\n".join(lines) + "\n"


def _format_candidate_section(title: str, section: dict) -> list[str]:
    lines = [
        f"## {title}",
        f"- 原始样本 `{section['sample_count']}` 行，交易日 `{section['date_count']}` 个，目标收益 `{section['target']}`。",
        "",
        "### 候选规则",
        "| 候选 | 逻辑 | 交易合理性 |",
        "|---|---|---|",
    ]
    for rule in section["rules"]:
        lines.append(f"| `{rule['name']}` | {rule['logic']} | {rule['rationale']} |")

    lines.extend(
        [
            "",
            "### 总览",
            "| 候选 | 样本 | 均值 | 胜率 | MFE | MAE | 机会/风险 | 相对基准 | 结论 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for name, item in section["candidates"].items():
        overall = item["overall"]
        lines.append(
            "| {name} | {sample} | {avg} | {win} | {mfe} | {mae} | {rr} | {edge} | {cls} |".format(
                name=f"`{name}`",
                sample=overall["sample_count"],
                avg=_fmt_pct(overall["avg_ret"]),
                win=_fmt_rate(overall["win_rate"]),
                mfe=_fmt_pct(overall["avg_mfe"]),
                mae=_fmt_pct(overall["avg_mae"]),
                rr=_fmt_num(overall["risk_reward"]),
                edge=_fmt_pct(overall["edge_vs_baseline"]),
                cls=item["classification"],
            )
        )

    lines.extend(
        [
            "",
            "### 分阶段",
            "| 候选 | 阶段 | 样本 | 均值 | 胜率 | 相对基准 |",
            "|---|---|---:|---:|---:|---:|",
        ]
    )
    phase_order = ["holdout_2024H1", "train_2024H2_2025H1", "validate_2025H2", "reference_2026", "other"]
    for name, item in section["candidates"].items():
        for phase in phase_order:
            metrics = item["phases"].get(phase)
            if not metrics:
                continue
            lines.append(
                "| {name} | {phase} | {sample} | {avg} | {win} | {edge} |".format(
                    name=f"`{name}`",
                    phase=phase,
                    sample=metrics["sample_count"],
                    avg=_fmt_pct(metrics["avg_ret"]),
                    win=_fmt_rate(metrics["win_rate"]),
                    edge=_fmt_pct(metrics["edge_vs_baseline"]),
                )
            )
    lines.append("")
    return lines


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "NA"
    return f"{value:+.2f}%"


def _fmt_rate(value: float | None) -> str:
    if value is None:
        return "NA"
    return f"{value * 100:.1f}%"


def _fmt_num(value: float | None) -> str:
    if value is None:
        return "NA"
    return f"{value:.2f}"


def _round_or_none(value: float | None) -> float | None:
    if value is None or pd.isna(value):
        return None
    return round(float(value), 4)


def main() -> None:
    parser = argparse.ArgumentParser(description="端午候选策略离线模拟")
    parser.add_argument("--root", default=".", help="项目根目录")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Markdown 输出路径")
    parser.add_argument("--max-short-files", type=int, default=0, help="短线 IC 文件数量；0 表示读取全部")
    parser.add_argument("--short-profile-filter", default=SHORT_PROFILE_FILTER, help="短线 factor_profile 过滤")
    args = parser.parse_args()

    result = write_candidate_simulation_report(
        root=args.root,
        output=args.output,
        max_short_files=args.max_short_files,
        short_profile_filter=args.short_profile_filter,
    )
    print(f"Report written: {args.output}")
    print(
        "short_candidates={short_count} longterm_candidates={long_count}".format(
            short_count=len(result["short"]["candidates"]),
            long_count=len(result["longterm"]["candidates"]),
        )
    )


if __name__ == "__main__":
    main()
