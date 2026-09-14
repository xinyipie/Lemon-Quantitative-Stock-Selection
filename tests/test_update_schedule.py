import json
from datetime import datetime

from web_app.services.update_schedule import read_update_schedule


def test_missing_schedule_does_not_invent_next_update(tmp_path):
    assert read_update_schedule(tmp_path / 'missing.json') == []


def test_verified_weekday_schedule_skips_weekend_and_elapsed_slot(tmp_path):
    path = tmp_path / 'schedule.json'
    path.write_text(json.dumps({'timezone': 'Asia/Shanghai', 'verified_at': '2026-09-14',
        'entries': [{'label': '雷达', 'weekdays': [0, 1, 2, 3, 4], 'hour': 7, 'minute': 30}]}), encoding='utf-8')
    schedule = read_update_schedule(path, now=datetime(2026, 9, 11, 8))
    assert schedule[0]['next_run'] == '2026-09-14 07:30'
