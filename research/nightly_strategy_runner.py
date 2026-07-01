#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""周末/夜间策略研究编排器。

这个脚本只编排 research 报告生成与离线诊断，不修改线上默认策略，
不包含任何自动交易、下单、仓位执行逻辑。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Iterable, Sequence
from zoneinfo import ZoneInfo


BEIJING = ZoneInfo("Asia/Shanghai")
DEFAULT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_ROOT = Path("reports") / "research" / "nightly"


@dataclass(frozen=True)
class ResearchTask:
    name: str
    command: list[str]
    capability: str = "base_research"
    phase: str = "base"


REQUIRED_CAPABILITIES = (
    "data_supplement",
    "short_backtest_ic",
    "longterm_backtest_ic",
    "market_radar",
    "sector_heat",
    "news_concept_ai",
    "ai_explanation",
    "short_diagnostics",
    "longterm_diagnostics",
    "candidate_funnel",
    "official_health",
)


@dataclass(frozen=True)
class TaskResult:
    name: str
    command: list[str]
    returncode: int
    started_at: str
    finished_at: str
    stdout: str
    stderr: str


def parse_until(value: str, now: datetime | None = None) -> datetime:
    """解析北京时间截止时间，支持绝对 ISO 时间或 HH:MM 墙钟时间。"""
    text = value.strip()
    current = now or datetime.now(BEIJING)
    if current.tzinfo is None:
        current = current.replace(tzinfo=BEIJING)

    if "T" in text or "+" in text:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=BEIJING)
        return parsed.astimezone(BEIJING)

    hour_text, minute_text = text.split(":", 1)
    candidate = current.replace(hour=int(hour_text), minute=int(minute_text), second=0, microsecond=0)
    if candidate <= current:
        candidate += timedelta(days=1)
    return candidate


def daily_output_dir(root: Path, now: datetime | None = None) -> Path:
    current = now or datetime.now(BEIJING)
    return root / DEFAULT_REPORT_ROOT / current.strftime("%Y%m%d")


def build_default_tasks(output_dir: Path) -> list[ResearchTask]:
    py = sys.executable
    return [
        ResearchTask(
            "strategy_research_overview",
            [
                py,
                "research/strategy_research_overview.py",
                "--output",
                str(output_dir / "strategy_research_overview.md"),
            ],
            capability="candidate_funnel",
            phase="base_research",
        ),
        ResearchTask(
            "strategy_layer_quality",
            [
                py,
                "research/strategy_layer_quality.py",
                "--output",
                str(output_dir / "strategy_layer_quality.md"),
            ],
            capability="candidate_funnel",
            phase="base_research",
        ),
        ResearchTask(
            "strategy_factor_stability",
            [
                py,
                "research/strategy_factor_stability.py",
                "--output",
                str(output_dir / "strategy_factor_stability.md"),
            ],
            capability="short_diagnostics",
            phase="base_research",
        ),
        ResearchTask(
            "strategy_candidate_simulation",
            [
                py,
                "research/strategy_candidate_simulator.py",
                "--output",
                str(output_dir / "strategy_candidate_simulation.md"),
            ],
            capability="candidate_funnel",
            phase="base_research",
        ),
        ResearchTask(
            "official_strategy_health_check",
            [
                py,
                "research/official_strategy_health_check.py",
                "--output",
                str(output_dir / "official_strategy_health_check.md"),
            ],
            capability="official_health",
            phase="base_research",
        ),
    ]


def build_weekend_tasks(
    output_dir: Path,
    allow_data_download: bool = True,
    start: str = "20240101",
    end: str | None = None,
) -> list[ResearchTask]:
    """构建覆盖全部研究能力的周末任务集。

    数据补充任务使用非 force 模式，优先补缺，不覆盖历史资产。
    """
    py = sys.executable
    end_date = end or datetime.now(BEIJING).strftime("%Y%m%d")
    tasks: list[ResearchTask] = []

    if allow_data_download:
        tasks.extend(
            [
                ResearchTask(
                    "data_core_missing",
                    [py, "data_downloader.py", "--start", start, "--end", end_date, "--core-only"],
                    capability="data_supplement",
                    phase="data",
                ),
                ResearchTask(
                    "data_aux_recent_missing",
                    [py, "data_downloader.py", "--start", start, "--end", end_date],
                    capability="data_supplement",
                    phase="data",
                ),
                ResearchTask(
                    "supplement_longterm_data",
                    [
                        py,
                        "supplement_longterm_data.py",
                        "--financial-start-year",
                        "2021",
                        "--financial-end-year",
                        end_date[:4],
                        "--daily-basic-start",
                        start,
                        "--daily-basic-end",
                        end_date,
                        "--sleep",
                        "0.35",
                    ],
                    capability="data_supplement",
                    phase="data",
                ),
            ]
        )

    tasks.extend(
        [
            ResearchTask(
                "batch_backtest_short_ic",
                [py, "batch_backtest.py", "--mode", "short", "--forward", "5", "10", "20"],
                capability="short_backtest_ic",
                phase="experiment",
            ),
            ResearchTask(
                "batch_backtest_longterm_ic",
                [py, "batch_backtest.py", "--mode", "longterm", "--forward", "10", "20", "30"],
                capability="longterm_backtest_ic",
                phase="experiment",
            ),
            ResearchTask(
                "ic_analysis_batch",
                [py, "ic_analysis.py", "--batch", "--forward", "5", "10", "20", "30"],
                capability="short_backtest_ic",
                phase="experiment",
            ),
            ResearchTask(
                "market_context_snapshot",
                [py, "market_context_snapshot.py", "--date", end_date],
                capability="market_radar",
                phase="radar",
            ),
            ResearchTask(
                "sector_heat_diagnostics",
                [
                    py,
                    "sector_heat_diagnostics.py",
                    "--output",
                    str(output_dir / "sector_heat_diagnostics.md"),
                    "--csv-output",
                    str(output_dir / "sector_heat_diagnostics.csv"),
                    "--stocks-output",
                    str(output_dir / "sector_heat_stock_candidates.csv"),
                ],
                capability="sector_heat",
                phase="radar",
            ),
            ResearchTask(
                "daily_ai_brief",
                [py, "daily_ai_brief.py", "--date", end_date],
                capability="news_concept_ai",
                phase="radar",
            ),
            ResearchTask(
                "backfill_short_signal_explanations",
                [
                    py,
                    "backfill_signal_explanations.py",
                    "--start",
                    start,
                    "--end",
                    end_date,
                    "--mode",
                    "short",
                    "--limit",
                    "30",
                ],
                capability="ai_explanation",
                phase="ai",
            ),
            ResearchTask(
                "backfill_longterm_signal_explanations",
                [
                    py,
                    "backfill_signal_explanations.py",
                    "--start",
                    start,
                    "--end",
                    end_date,
                    "--mode",
                    "longterm",
                    "--limit",
                    "30",
                ],
                capability="ai_explanation",
                phase="ai",
            ),
            ResearchTask(
                "candidate_rank_diagnostics",
                [py, "candidate_rank_diagnostics.py", "--output", str(output_dir / "candidate_rank_diagnostics.md")],
                capability="short_diagnostics",
                phase="diagnostics",
            ),
            ResearchTask(
                "trade_diagnostics",
                [py, "trade_diagnostics.py", "--output", str(output_dir / "trade_diagnostics.md")],
                capability="short_diagnostics",
                phase="diagnostics",
            ),
            ResearchTask(
                "longterm_pool_quality_audit",
                [
                    py,
                    "longterm_pool_quality_audit.py",
                    "--start",
                    start,
                    "--end",
                    end_date,
                    "--sample-step",
                    "10",
                    "--output",
                    str(output_dir / "longterm_pool_quality_audit.md"),
                    "--csv-output",
                    str(output_dir / "longterm_pool_quality_audit.csv"),
                    "--quiet",
                ],
                capability="longterm_diagnostics",
                phase="diagnostics",
            ),
            ResearchTask(
                "longterm_market_winner_profile_audit",
                [
                    py,
                    "longterm_market_winner_profile_audit.py",
                    "--start",
                    start,
                    "--end",
                    end_date,
                    "--sample-step",
                    "10",
                    "--output",
                    str(output_dir / "longterm_market_winner_profile_audit.md"),
                    "--csv-output",
                    str(output_dir / "longterm_market_winner_profile_audit.csv"),
                ],
                capability="longterm_diagnostics",
                phase="diagnostics",
            ),
            ResearchTask(
                "longterm_value_quality_diagnostics",
                [
                    py,
                    "longterm_value_quality_diagnostics.py",
                    "--asof-date",
                    end_date,
                    "--start",
                    start,
                    "--end",
                    end_date,
                    "--output",
                    str(output_dir / "longterm_value_quality_diagnostics.md"),
                ],
                capability="longterm_diagnostics",
                phase="diagnostics",
            ),
        ]
    )
    tasks.extend(build_default_tasks(output_dir))
    return tasks


def coverage_by_capability(tasks: Iterable[ResearchTask]) -> dict[str, list[str]]:
    coverage = {capability: [] for capability in REQUIRED_CAPABILITIES}
    for task in tasks:
        if task.capability in coverage:
            coverage[task.capability].append(task.name)
    return coverage


def build_cycle_tasks(
    output_dir: Path,
    cycle_index: int,
    full_cycle_interval: int = 4,
    allow_data_download: bool = True,
) -> list[ResearchTask]:
    """按轮次生成任务，避免每 30 分钟重复跑完整下载和大回测。"""
    should_run_full = cycle_index == 0 or (
        full_cycle_interval > 0 and cycle_index % full_cycle_interval == 0
    )
    if should_run_full:
        return build_weekend_tasks(output_dir, allow_data_download=allow_data_download)
    return build_light_refresh_tasks(output_dir)


def build_light_refresh_tasks(output_dir: Path) -> list[ResearchTask]:
    py = sys.executable
    end_date = datetime.now(BEIJING).strftime("%Y%m%d")
    return [
        ResearchTask(
            "market_context_snapshot",
            [py, "market_context_snapshot.py", "--date", end_date],
            capability="market_radar",
            phase="light_refresh",
        ),
        ResearchTask(
            "sector_heat_diagnostics",
            [
                py,
                "sector_heat_diagnostics.py",
                "--output",
                str(output_dir / "sector_heat_diagnostics.md"),
                "--csv-output",
                str(output_dir / "sector_heat_diagnostics.csv"),
                "--stocks-output",
                str(output_dir / "sector_heat_stock_candidates.csv"),
            ],
            capability="sector_heat",
            phase="light_refresh",
        ),
        *build_default_tasks(output_dir),
    ]


def run_once(
    tasks: Iterable[ResearchTask | tuple[str, Sequence[str]]],
    root: str | Path,
    output_dir: str | Path,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> list[TaskResult]:
    root_path = Path(root)
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    log_path = out_path / "runner.log"
    results: list[TaskResult] = []

    for raw_task in tasks:
        task = _normalize_task(raw_task)
        started = datetime.now(BEIJING)
        try:
            completed = runner(
                task.command,
                cwd=root_path,
                text=True,
                capture_output=True,
                check=False,
            )
            returncode = int(completed.returncode)
            stdout = completed.stdout or ""
            stderr = completed.stderr or ""
        except Exception as exc:  # pragma: no cover - 兜底记录未知运行时错误
            returncode = 99
            stdout = ""
            stderr = repr(exc)
        finished = datetime.now(BEIJING)
        result = TaskResult(
            name=task.name,
            command=task.command,
            returncode=returncode,
            started_at=started.isoformat(timespec="seconds"),
            finished_at=finished.isoformat(timespec="seconds"),
            stdout=stdout[-4000:],
            stderr=stderr[-4000:],
        )
        results.append(result)
        _append_log(log_path, result)
        _write_state(out_path / "runner_state.json", results)

    return results


def write_final_summary(
    output_dir: str | Path,
    started_at: datetime,
    until: datetime,
    cycles: list[list[TaskResult]],
    skipped_reasons: list[str] | None = None,
    planned_tasks: list[ResearchTask] | None = None,
) -> Path:
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    summary_path = out_path / f"nightly_strategy_research_{started_at.strftime('%Y%m%d')}.md"
    flat = [result for cycle in cycles for result in cycle]
    failed = [result for result in flat if result.returncode != 0]
    succeeded = [result for result in flat if result.returncode == 0]
    report_files = sorted(path.name for path in out_path.glob("*.md") if path.name != summary_path.name)
    reasons = skipped_reasons or []
    coverage = coverage_by_capability(planned_tasks or build_weekend_tasks(out_path))

    lines = [
        "# 周末策略研究总结",
        "",
        "## 运行边界",
        f"- 启动时间：`{started_at.isoformat(timespec='seconds')}`",
        f"- 目标截止：`{until.isoformat(timespec='seconds')}`",
        "- 本任务只做 research 诊断与离线报告，不包含自动交易、自动下单或仓位执行代码。",
        "- 若外部接口、网络、权限或 Git 状态不可用，任务记录原因并继续低风险研究。",
        "",
        "## 执行概况",
        f"- 循环轮次：`{len(cycles)}`",
        f"- 成功任务：`{len(succeeded)}`",
        f"- 失败任务：`{len(failed)}`",
        "",
        "## 报告产物",
    ]
    if report_files:
        lines.extend(f"- `{name}`" for name in report_files)
    else:
        lines.append("- 暂无 Markdown 子报告产物。")

    lines.extend(["", "## 失败与跳过"])
    if failed:
        for result in failed:
            lines.append(f"- `{result.name}` exit `{result.returncode}`：{_first_line(result.stderr) or _first_line(result.stdout) or '无输出'}")
    if reasons:
        lines.extend(f"- {reason}" for reason in reasons)
    if not failed and not reasons:
        lines.append("- 暂无失败或跳过项。")

    lines.extend(["", "## 能力覆盖"])
    for capability in REQUIRED_CAPABILITIES:
        names = coverage.get(capability) or []
        status = "已覆盖" if names else "未覆盖"
        lines.append(f"- `{capability}`：{status}；任务：{', '.join(names) if names else 'NA'}")

    lines.extend(
        [
            "",
            "## 下一步",
            "- 先阅读本目录下的分层质量、因子稳定性、候选策略模拟与健康检查报告。",
            "- 只把跨区间稳定且金融逻辑清楚的候选策略推进到下一轮验证。",
            "- 不把本报告作为直接买入或自动交易指令。",
        ]
    )
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary_path


def run_until(
    until: datetime,
    root: str | Path = DEFAULT_ROOT,
    cycle_seconds: int = 1800,
    max_cycles: int | None = None,
    once: bool = False,
    basic_only: bool = False,
    allow_data_download: bool = True,
    full_cycle_interval: int = 4,
) -> Path:
    root_path = Path(root)
    started_at = datetime.now(BEIJING)
    out_path = daily_output_dir(root_path, now=started_at)
    cycles: list[list[TaskResult]] = []
    skipped: list[str] = []

    if not (root_path / "research").exists():
        skipped.append(f"research 目录不存在：{root_path / 'research'}")

    while datetime.now(BEIJING) < until:
        tasks = (
            build_default_tasks(out_path)
            if basic_only
            else build_cycle_tasks(
                out_path,
                cycle_index=len(cycles),
                full_cycle_interval=full_cycle_interval,
                allow_data_download=allow_data_download,
            )
        )
        cycles.append(run_once(tasks=tasks, root=root_path, output_dir=out_path))
        if once:
            break
        if max_cycles is not None and len(cycles) >= max_cycles:
            break
        remaining = (until - datetime.now(BEIJING)).total_seconds()
        if remaining <= 0:
            break
        time.sleep(max(1, min(cycle_seconds, int(remaining))))

    return write_final_summary(
        output_dir=out_path,
        started_at=started_at,
        until=until,
        cycles=cycles,
        skipped_reasons=skipped,
        planned_tasks=tasks if cycles else None,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="无人值守策略研究编排器")
    parser.add_argument("--until", required=True, help="北京时间截止时间，支持 20:00 或 2026-06-28T20:00:00+08:00")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="项目根目录")
    parser.add_argument("--cycle-seconds", type=int, default=1800, help="每轮研究之间的等待秒数")
    parser.add_argument("--max-cycles", type=int, default=None, help="最多执行轮数")
    parser.add_argument("--once", action="store_true", help="只执行一轮，用于验证")
    parser.add_argument("--basic-only", action="store_true", help="只跑基础五项研究报告")
    parser.add_argument("--no-data-download", action="store_true", help="跳过历史数据自发补缺任务")
    parser.add_argument("--full-cycle-interval", type=int, default=4, help="每隔多少轮执行一次全量实验任务")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    until = parse_until(args.until)
    summary = run_until(
        until=until,
        root=args.root,
        cycle_seconds=args.cycle_seconds,
        max_cycles=args.max_cycles,
        once=args.once,
        basic_only=args.basic_only,
        allow_data_download=not args.no_data_download,
        full_cycle_interval=args.full_cycle_interval,
    )
    print(f"Summary written: {summary}")


def _normalize_task(raw_task: ResearchTask | tuple[str, Sequence[str]]) -> ResearchTask:
    if isinstance(raw_task, ResearchTask):
        return raw_task
    name, command = raw_task
    return ResearchTask(str(name), [str(part) for part in command])


def _append_log(log_path: Path, result: TaskResult) -> None:
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(result), ensure_ascii=False) + "\n")


def _write_state(path: Path, results: list[TaskResult]) -> None:
    payload = {
        "updated_at": datetime.now(BEIJING).isoformat(timespec="seconds"),
        "results": [asdict(result) for result in results],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _first_line(value: str) -> str:
    for line in value.splitlines():
        text = line.strip()
        if text:
            return text[:240]
    return ""


if __name__ == "__main__":
    main()
