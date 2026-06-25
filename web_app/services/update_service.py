#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Background update runner for the local Web dashboard."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from collections import deque
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


def read_update_status(
    status_path: str | Path = DEFAULT_STATUS_PATH,
    stale_after_seconds: int | None = None,
    now: datetime | None = None,
) -> dict:
    path = Path(status_path)
    if not path.exists():
        return {"state": "idle", "running": False, "message": "尚未运行一键更新。"}
    try:
        status = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"state": "unknown", "running": False, "message": "更新状态文件读取失败。"}
    if status.get("state") == "running" and _is_stale_status(status, stale_after_seconds, now=now):
        status.update(
            {
                "state": "failed",
                "running": False,
                "finished_at": _now(),
                "message": "同步任务超时未更新，已自动解除运行锁。请重新点击同步。",
            }
        )
        _write_status(path, status)
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
            "updated_at": _now(),
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
    path = Path(status_path)
    _write_status(
        path,
        {
            "state": "running",
            "running": True,
            "mode": _extract_mode(command),
            "command": command,
            "started_at": _now(),
            "updated_at": _now(),
            "message": _running_message(command),
        },
    )
    try:
        result = (
            runner(command, cwd=Path.cwd(), text=True, capture_output=True, check=False)
            if runner is not None
            else _run_streaming_process(command, path)
        )
        state = "finished" if int(result.returncode or 0) == 0 else "failed"
        _write_status(
            path,
            {
                "state": state,
                "running": False,
                "mode": _extract_mode(command),
                "command": command,
                "returncode": int(result.returncode or 0),
                "started_at": read_update_status(path, stale_after_seconds=None).get("started_at"),
                "updated_at": _now(),
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
                "updated_at": _now(),
                "finished_at": _now(),
                "stderr_tail": str(exc),
                "message": "同步任务异常退出。",
            },
        )


class _ProcessResult:
    def __init__(self, returncode: int, stdout: str, stderr: str):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _run_streaming_process(command: list[str], status_path: Path) -> _ProcessResult:
    process = subprocess.Popen(
        command,
        cwd=Path.cwd(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=1,
    )
    stdout_lines: deque[str] = deque(maxlen=120)
    stderr_lines: deque[str] = deque(maxlen=80)
    lock = threading.Lock()

    _merge_status(status_path, {"pid": process.pid, "updated_at": _now()})

    def read_pipe(pipe, key: str, lines: deque[str]) -> None:
        if pipe is None:
            return
        for line in iter(pipe.readline, ""):
            with lock:
                lines.append(line)
                patch = {
                    "state": "running",
                    "running": True,
                    "updated_at": _now(),
                    key: _tail("".join(lines)),
                    "message": _summarize_progress_line(line) or _running_message(command),
                }
                if stdout_lines:
                    patch["stdout_tail"] = _tail("".join(stdout_lines))
                if stderr_lines:
                    patch["stderr_tail"] = _tail("".join(stderr_lines))
                _merge_status(status_path, patch)
        pipe.close()

    stdout_thread = threading.Thread(target=read_pipe, args=(process.stdout, "stdout_tail", stdout_lines), daemon=True)
    stderr_thread = threading.Thread(target=read_pipe, args=(process.stderr, "stderr_tail", stderr_lines), daemon=True)
    stdout_thread.start()
    stderr_thread.start()
    returncode = process.wait()
    stdout_thread.join(timeout=2)
    stderr_thread.join(timeout=2)
    return _ProcessResult(returncode, "".join(stdout_lines), "".join(stderr_lines))


def _write_status(status_path: str | Path, status: dict) -> None:
    path = Path(status_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")


def _merge_status(status_path: str | Path, patch: dict) -> None:
    path = Path(status_path)
    try:
        current = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, json.JSONDecodeError):
        current = {}
    current.update(patch)
    _write_status(path, current)


def _tail(text: str, limit: int = 4000) -> str:
    value = str(text or "")
    return value[-limit:]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _is_stale_status(status: dict, stale_after_seconds: int | None, now: datetime | None = None) -> bool:
    threshold = stale_after_seconds if stale_after_seconds is not None else _default_stale_seconds(status)
    if not threshold:
        return False
    timestamp = status.get("updated_at") or status.get("started_at")
    if not timestamp:
        return False
    try:
        last_update = datetime.strptime(str(timestamp), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return False
    current = now or datetime.now()
    return (current - last_update).total_seconds() > threshold


def _default_stale_seconds(status: dict) -> int:
    mode = str(status.get("mode") or "daily")
    if mode == "full":
        return 90 * 60
    return 20 * 60


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


def _summarize_progress_line(line: str) -> str:
    text = str(line or "").strip()
    if not text:
        return ""
    if text.startswith("> "):
        return f"正在执行：{text[2:]}"
    return text[-180:]
