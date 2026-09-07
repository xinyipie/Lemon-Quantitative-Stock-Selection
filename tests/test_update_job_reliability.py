import json
import sys
import subprocess
import threading
from datetime import datetime
from pathlib import Path

from web_app.services import update_service
from web_app.services.update_worker import main


def test_worker_propagates_child_failure(tmp_path):
    status = tmp_path / "status.json"
    result = main([json.dumps([sys.executable, "-c", "raise SystemExit(7)"]), str(status)])
    assert result == 7
    assert json.loads(status.read_text(encoding="utf-8"))["state"] == "failed"


def test_radar_success_does_not_hide_full_failure(tmp_path):
    status = tmp_path / "status.json"
    def run(mode, rc):
        class Result:
            returncode = rc
            stdout = stderr = ""
        update_service.run_update_job(["python", "daily_web_update.py", "--mode", mode], status, runner=lambda *a, **k: Result())
    run("full", 7)
    run("radar", 0)
    assert update_service.needs_full_update_retry(status)
    run("full", 0)
    run("radar", 0)
    assert not update_service.needs_full_update_retry(status)
    assert update_service.needs_full_update_retry(status, now=datetime(2099, 1, 1))


def test_concurrent_modes_do_not_replace_running_job(tmp_path):
    entered = threading.Event()
    release = threading.Event()
    status = tmp_path / "status.json"
    class Result:
        returncode = 0
        stdout = stderr = ""
    def blocking_runner(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return Result()
    worker = threading.Thread(target=update_service.run_update_job, args=(["python", "--mode", "full"], status), kwargs={"runner": blocking_runner})
    worker.start()
    try:
        assert entered.wait(5)
        result = update_service.run_update_job(["python", "--mode", "radar"], status, runner=lambda *a, **k: Result())
        assert result == 75
        assert json.loads(status.read_text(encoding="utf-8"))["mode"] == "full"
        assert json.loads(status.read_text(encoding="utf-8"))["state"] == "running"
    finally:
        release.set()
        worker.join(5)


def test_secure_tushare_url_rejects_cleartext_and_credentials():
    import config
    import pytest
    for url in ("", "http://example.com", "https://user:secret@example.com"):
        with pytest.raises(ValueError):
            config.require_secure_tushare_url(url)
    assert config.require_secure_tushare_url("https://example.com/") == "https://example.com"


def test_running_lock_excludes_a_separate_worker_process(tmp_path):
    status = tmp_path / "status.json"
    script = (
        "import sys; from filelock import FileLock; "
        "lock=FileLock(sys.argv[1]); lock.acquire(timeout=0); "
        "print('ready', flush=True); sys.stdin.readline(); lock.release()"
    )
    holder = subprocess.Popen(
        [sys.executable, "-c", script, str(tmp_path / ".stock-update.run.lock")],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "ready"
        result = main([json.dumps([sys.executable, "-c", "raise SystemExit(0)"]), str(status)])
        assert result == 75
        assert not status.exists()
    finally:
        holder.communicate("release\n", timeout=10)
    assert holder.returncode == 0
