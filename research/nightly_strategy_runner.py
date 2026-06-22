#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""夜间策略研究编排器。

这个脚本只运行 research 目录下的只读诊断脚本，输出夜间研究报告。
它不会修改 main.py 默认策略，不会写入交易执行逻辑，也不会自动上线新 profile。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable


RESEARCH_BRANCH = "codex/strategy-research"
DEFAULT_REPORT_ROOT = Path("reports") / "research" / "nightly"
TASK_TIMEOUT_SECONDS = 60 * 30

ResearchRunner = Callable[..., subprocess.CompletedProcess]


RESEARCH_TASKS = (
    {
        "name": "research_overview",
        "title": "研究资产总览",
        "script": "research/strategy_research_overview.py",
        "output": "strategy_research_overview.md",
    },
    {
        "name": "layer_quality",
        "title": "分层质量诊断",
        "script": "research/strategy_layer_quality.py",
        "output": "strategy_layer_quality.md",
    },
    {
        "name": "factor_stability",
        "title": "因子稳定性诊断",
        "script": "research/strategy_factor_stability.py",
        "output": "strategy_factor_stability.md",
    },
    {
        "name": "candidate_simulation",
        "title": "候选策略离线模拟",
        "script": "research/strategy_candidate_simulator.py",
        "output": "strategy_candidate_simulation.md",
    },
    {
        "name": "official_health_check",
        "title": "定板策略健康检查",
        "script": "research/official_strategy_health_check.py",
        "output": "official_strategy_health_check.md",
    },
)


def run_nightly_research(
    root: str | Path = ".",
    until: str = "08:00",
    runner: ResearchRunner | None = None,
    now_text: str | None = None,
    allow_any_branch: bool = False,
) -> dict:
    """Run one nightly research sweep and write a summary report."""
    root_path = Path(root).resolve()
    run = runner or subprocess.run
    now = _parse_now(now_text)

    branch = _current_branch(root_path, run)
    if not allow_any_branch and branch != RESEARCH_BRANCH:
        return {
            "ok": False,
            "message": f"当前分支是 {branch or 'unknown'}，夜间研究必须在 {RESEARCH_BRANCH} 上运行。",
            "branch": branch,
            "tasks": [],
            "report": None,
        }

    output_dir = root_path / DEFAULT_REPORT_ROOT / now.strftime("%Y%m%d")
    output_dir.mkdir(parents=True, exist_ok=True)
    tasks = []
    for task in RESEARCH_TASKS:
        tasks.append(_run_task(root_path, output_dir, task, run))

    report_path = output_dir / f"nightly_strategy_research_{now.strftime('%Y%m%d')}.md"
    ok = all(task["returncode"] == 0 for task in tasks)
    message = "夜间研究巡检完成。" if ok else "夜间研究巡检存在失败任务，请先看报告。"
    report_path.write_text(
        _format_report(
            now=now,
            until=until,
            branch=branch,
            ok=ok,
            message=message,
            tasks=tasks,
        ),
        encoding="utf-8",
    )
    return {
        "ok": ok,
        "message": message,
        "branch": branch,
        "tasks": tasks,
        "report": str(report_path),
    }


def _parse_now(now_text: str | None) -> datetime:
    if not now_text:
        return datetime.now()
    return datetime.strptime(now_text, "%Y-%m-%d %H:%M:%S")


def _current_branch(root: Path, runner: ResearchRunner) -> str:
    result = runner(
        ["git", "branch", "--show-current"],
        cwd=root,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        return ""
    return (result.stdout or "").strip()


def _run_task(root: Path, output_dir: Path, task: dict, runner: ResearchRunner) -> dict:
    output_path = output_dir / task["output"]
    command = [
        sys.executable,
        task["script"],
        "--root",
        str(root),
        "--output",
        str(output_path),
    ]
    try:
        result = runner(
            command,
            cwd=root,
            text=True,
            capture_output=True,
            timeout=TASK_TIMEOUT_SECONDS,
            check=False,
        )
        return {
            "name": task["name"],
            "title": task["title"],
            "command": command,
            "output": str(output_path),
            "returncode": result.returncode,
            "stdout": _trim(result.stdout),
            "stderr": _trim(result.stderr),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "name": task["name"],
            "title": task["title"],
            "command": command,
            "output": str(output_path),
            "returncode": 124,
            "stdout": _trim(exc.stdout),
            "stderr": f"任务超过 {TASK_TIMEOUT_SECONDS} 秒未完成，已跳过。",
        }


def _trim(text: str | bytes | None, limit: int = 2000) -> str:
    if text is None:
        return ""
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...<trimmed>"


def _format_report(
    now: datetime,
    until: str,
    branch: str,
    ok: bool,
    message: str,
    tasks: list[dict],
) -> str:
    lines = [
        "# 夜间策略研究运行报告",
        "",
        "## 运行摘要",
        f"- 开始时间：`{now.strftime('%Y-%m-%d %H:%M:%S')}`",
        f"- 目标截止：`{until}`",
        f"- 分支：`{branch}`",
        f"- 状态：`{'完成' if ok else '有失败任务'}`",
        f"- 结论：{message}",
        "",
        "## 无人值守规则",
        "- 只在 `codex/strategy-research` 研究分支运行。",
        "- 不修改 `main.py` 默认上线策略，不生成自动交易或下单代码。",
        "- 遇到需要确认的高风险动作时跳过并写入报告，不等待用户回复。",
        "- 候选策略只进入研究报告，成熟后也只建议进入下一轮验证。",
        "",
        "## 任务结果",
        "| 任务 | 状态 | 输出 |",
        "|---|---:|---|",
    ]
    for task in tasks:
        status = "通过" if task["returncode"] == 0 else f"失败({task['returncode']})"
        lines.append(f"| {task['title']} | {status} | `{task['output']}` |")

    lines.extend(["", "## 失败详情"])
    failed = [task for task in tasks if task["returncode"] != 0]
    if not failed:
        lines.append("无。")
    for task in failed:
        lines.extend(
            [
                f"### {task['title']}",
                f"- 命令：`{' '.join(task['command'])}`",
                "```text",
                task["stderr"] or task["stdout"] or "无输出",
                "```",
            ]
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="运行夜间策略研究巡检并生成总报告。")
    parser.add_argument("--root", default=".", help="项目根目录")
    parser.add_argument("--until", default="08:00", help="研究目标截止时间，仅写入报告")
    parser.add_argument("--allow-any-branch", action="store_true", help="调试用：允许非研究分支运行")
    args = parser.parse_args()

    result = run_nightly_research(
        root=args.root,
        until=args.until,
        allow_any_branch=args.allow_any_branch,
    )
    if result["report"]:
        print(f"Report written: {result['report']}")
    print(result["message"])
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
