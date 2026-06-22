#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Background update runner for the local Web dashboard."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable


DEFAULT_STATUS_PATH = Path("data") / "web_update_status.json"
VALID_MODES = {"daily", "full"}


def build_update_command(end: str | None = None, mode: str = "daily", full_history: bool = False) -> list[str]:
    update_mode = mode if mode in VALID_MODES else "daily"
    command = [sys.executable, "daily_web_update.py", "--mode", update_mode]
    if end:
        command.extend(["--end", str(end).replace("-", "")[:8]])
    if full_history:
        command.append("--full-history")
    return command


def read_update_status(status_path: str | Path = DEFAULT_STATUS_PATH) -> dict:
    path = Path(status_path)
    if not path.exists():
        return {"state": "idle", "running": False, "message": "尚未运行一键更新。"}
    try:
        status = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"state": "unknown", "running": False, "message": "更新状态文件读取失败。"}
    status["running"] = status.get("state") == "running"
    return status


def decorate_update_status_with_freshness(status: dict | None, freshness: dict | None) -> dict:
    """Combine task execution status with actual data freshness for display."""
    decorated = dict(status or {})
    decorated.setdefault("state", "idle")
    decorated.setdefault("running", decorated.get("state") == "running")

    warnings = list((freshness or {}).get("warnings") or [])
    status_label = str((freshness or {}).get("status_label") or "").strip()
    if decorated.get("state") == "finished":
        if warnings:
            decorated["aligned"] = False
            decorated["alignment_state"] = "warn"
            suffix = f"：{status_label}" if status_label else ""
            decorated["display_message"] = f"同步任务已完成，但数据未对齐{suffix}。"
        else:
            decorated["aligned"] = True
            decorated["alignment_state"] = "ok"
            decorated["display_message"] = "同步完成，数据已对齐。"
    else:
        decorated["aligned"] = not warnings
        decorated["alignment_state"] = "warn" if warnings else "unknown"
        decorated["display_message"] = decorated.get("message") or "尚未运行一键更新。"
    return decorated


def start_web_update(
    end: str | None = None,
    mode: str = "daily",
    full_history: bool = False,
    status_path: str | Path = DEFAULT_STATUS_PATH,
) -> dict:
    status = read_update_status(status_path)
    if status.get("running"):
        status["started"] = False
        status["message"] = "已有同步任务正在运行。"
        return status

    update_mode = mode if mode in VALID_MODES else "daily"
    command = build_update_command(end=end, mode=update_mode, full_history=full_history)
    mode_label = "日常轻量同步" if update_mode == "daily" else "完整同步"
    _write_status(
        status_path,
        {
            "state": "running",
            "running": True,
            "started": True,
            "mode": update_mode,
            "command": command,
            "started_at": _now(),
            "message": f"{mode_label}已开始，完成前请不要重复点击。",
        },
    )
    thread = threading.Thread(target=run_update_job, args=(command, Path(status_path)), daemon=True)
    thread.start()
    return read_update_status(status_path)


def run_update_job(
    command: list[str],
    status_path: str | Path = DEFAULT_STATUS_PATH,
    runner: Callable | None = None,
) -> None:
    runner = runner or subprocess.run
    path = Path(status_path)
    _write_status(
        path,
        {
            "state": "running",
            "running": True,
            "mode": _extract_mode(command),
            "command": command,
            "started_at": _now(),
            "message": _running_message(command),
        },
    )
    try:
        result = runner(command, cwd=Path.cwd(), text=True, capture_output=True, check=False)
        state = "finished" if int(result.returncode or 0) == 0 else "failed"
        _write_status(
            path,
            {
                "state": state,
                "running": False,
                "mode": _extract_mode(command),
                "command": command,
                "returncode": int(result.returncode or 0),
                "started_at": read_update_status(path).get("started_at"),
                "finished_at": _now(),
                "stdout_tail": _tail(getattr(result, "stdout", "")),
                "stderr_tail": _tail(getattr(result, "stderr", "")),
                "message": "同步完成。" if state == "finished" else "同步失败，请查看错误摘要。",
            },
        )
    except Exception as exc:  # pragma: no cover - fallback status for unexpected runner errors
        _write_status(
            path,
            {
                "state": "failed",
                "running": False,
                "mode": _extract_mode(command),
                "command": command,
                "returncode": -1,
                "finished_at": _now(),
                "stderr_tail": str(exc),
                "message": "同步任务异常退出。",
            },
        )


def _write_status(status_path: str | Path, status: dict) -> None:
    path = Path(status_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")


def _tail(text: str, limit: int = 4000) -> str:
    value = str(text or "")
    return value[-limit:]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _extract_mode(command: list[str]) -> str:
    if "--mode" in command:
        idx = command.index("--mode")
        if idx + 1 < len(command):
            return command[idx + 1]
    return "daily"


def _running_message(command: list[str]) -> str:
    if _extract_mode(command) == "full":
        return "正在完整同步：行情、实盘、短线复盘、长线审计和市场上下文。"
    return "正在日常同步：更新行情、市场上下文并运行 main.py。"
