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


def build_update_command(end: str | None = None, full_history: bool = False) -> list[str]:
    command = [sys.executable, "daily_web_update.py"]
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


def start_web_update(
    end: str | None = None,
    full_history: bool = False,
    status_path: str | Path = DEFAULT_STATUS_PATH,
) -> dict:
    status = read_update_status(status_path)
    if status.get("running"):
        status["started"] = False
        status["message"] = "已有更新任务正在运行。"
        return status

    command = build_update_command(end=end, full_history=full_history)
    _write_status(
        status_path,
        {
            "state": "running",
            "running": True,
            "started": True,
            "command": command,
            "started_at": _now(),
            "message": "一键更新已开始，完成前请不要重复点击。",
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
            "command": command,
            "started_at": _now(),
            "message": "正在更新行情、实盘信号、历史复盘和市场上下文。",
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
                "command": command,
                "returncode": int(result.returncode or 0),
                "started_at": read_update_status(path).get("started_at"),
                "finished_at": _now(),
                "stdout_tail": _tail(getattr(result, "stdout", "")),
                "stderr_tail": _tail(getattr(result, "stderr", "")),
                "message": "更新完成。" if state == "finished" else "更新失败，请查看错误摘要。",
            },
        )
    except Exception as exc:  # pragma: no cover - 兜底状态，具体异常由日志/状态文件展示
        _write_status(
            path,
            {
                "state": "failed",
                "running": False,
                "command": command,
                "returncode": -1,
                "finished_at": _now(),
                "stderr_tail": str(exc),
                "message": "更新任务异常退出。",
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
