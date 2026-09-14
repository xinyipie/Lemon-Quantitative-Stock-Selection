import json
from datetime import datetime
from types import SimpleNamespace

from web_app.services import update_service as service


def run(path, mode, code):
    return service.run_update_job(
        ["python", "daily_web_update.py", "--mode", mode], path,
        runner=lambda *args, **kwargs: SimpleNamespace(returncode=code, stdout="done", stderr="error" if code else ""),
    )


def test_mode_status_keeps_full_failure_after_radar_success(tmp_path):
    path = tmp_path / "status.json"
    run(path, "full", 7)
    run(path, "radar", 0)
    status = service.read_update_status(path)
    assert status["state"] == "finished"
    assert status["mode_statuses"]["full"]["state"] == "failed"
    assert status["mode_statuses"]["radar"]["status_label"] == "成功"
    assert status["mode_statuses"]["daily"]["status_label"] == "未记录"
    assert service.needs_full_update_retry(path)


def test_history_preserves_distinct_retries_and_filters(tmp_path):
    path = tmp_path / "status.json"
    run(path, "full", 7)
    run(path, "full", 0)
    run(path, "radar", 0)
    history = service.read_update_history(path)
    assert [(row["mode"], row["state"]) for row in history] == [
        ("radar", "finished"), ("full", "finished"), ("full", "failed")]
    assert len({row["run_id"] for row in history}) == 3
    assert len(service.read_update_history(path, mode="full", limit=1)) == 1
    assert not service.needs_full_update_retry(path)


def test_legacy_success_is_visible_without_history(tmp_path):
    path = tmp_path / "status.json"
    path.write_text(json.dumps({"mode": "full", "state": "finished", "returncode": 0,
                                "started_at": "2026-09-14 02:00:00"}), encoding="utf-8")
    assert service.read_update_status(path)["mode_statuses"]["full"]["state"] == "finished"
    assert not service.needs_full_update_retry(path, now=datetime(2026, 9, 14, 6))
    run(path, "radar", 0)
    assert service.read_update_status(path)["mode_statuses"]["full"]["state"] == "finished"
    assert not service.needs_full_update_retry(path, now=datetime(2026, 9, 14, 6))


def test_missing_status_exposes_unrun_modes(tmp_path):
    status = service.read_update_status(tmp_path / "missing.json")
    assert status["mode_statuses"]["full"]["state"] == "idle"
    assert status["history"] == []


def test_stale_full_mode_is_archived_without_replacing_radar(tmp_path):
    path = tmp_path / "status.json"
    service._write_status(path, {"mode": "full", "state": "running", "running": True,
                                 "pid": 123, "started_at": "2020-01-01 02:00:00",
                                 "updated_at": "2020-01-01 02:00:00"})
    run(path, "radar", 0)
    for _ in range(2):
        status = service.read_update_status(path)
        assert status["mode"] == "radar"
        assert status["state"] == "finished"
        assert status["mode_statuses"]["full"]["state"] == "failed"
    history = service.read_update_history(path, mode="full")
    assert len(history) == 1
    assert history[0]["state"] == "failed"
    assert json.loads(path.read_text(encoding="utf-8"))["mode"] == "radar"
