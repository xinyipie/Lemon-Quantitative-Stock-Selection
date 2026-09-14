from signal_store import SignalStore
from web_app.services.signal_service import get_longterm_runs
from contextlib import ExitStack
from unittest.mock import patch

from fastapi.testclient import TestClient
from web_app.app import app


def test_run_history_pages_beyond_twelve_and_filters_dates(tmp_path):
    db = tmp_path / 'signals.db'
    store = SignalStore(db)
    try:
        for day in range(1, 21):
            store.record_run(f'202608{day:02}', mode='longterm', profile='watch', source='test')
        latest = store.record_run('20260810', mode='longterm', profile='watch', source='retry')
    finally:
        store.close()
    rows = get_longterm_runs(db, limit=5, start='20260801', end='20260815', offset=5)
    assert [row['trade_date'] for row in rows] == [f'202608{day:02}' for day in range(10, 5, -1)]
    assert rows[0]['run_id'] == latest
    assert len(get_longterm_runs(db, limit=30)) == 20


def test_zero_record_is_not_claimed_successful_scan(tmp_path):
    db = tmp_path / 'signals.db'
    store = SignalStore(db)
    try:
        store.record_run('20260810', mode='longterm', profile='watch', source='test')
    finally:
        store.close()
    assert get_longterm_runs(db)[0]['status_label'] == '未写入候选（扫描状态见诊断）'


def test_page_separates_history_and_run_filters():
    with ExitStack() as stack:
        for name, value in {
            'get_active_longterm_pool': [], 'get_longterm_events': [],
            'get_longterm_audit_summary': {'runs': []}, 'get_longterm_audit_samples': [],
            'read_update_status': {},
        }.items():
            stack.enter_context(patch(f'web_app.app.{name}', return_value=value))
        stack.enter_context(patch('longterm_scan.get_latest_longterm_scan', return_value={
            'status': 'failed', 'reason': '扫描失败测试', 'trade_date': '20260901',
        }))
        runs = stack.enter_context(patch('web_app.app.get_longterm_runs', return_value=[]))
        response = TestClient(app).get('/longterm?view=all&start=20260101&run_start=20260801&run_end=20260820&run_page=2')
    assert response.status_code == 200
    assert runs.call_args.kwargs == {'limit': 21, 'offset': 20, 'start': '20260801', 'end': '20260820'}
    assert '全部历史样本' in response.text
    assert '默认读取最新100条' in response.text
    assert '最多读取1000条' in response.text
    assert '实时观察跟踪 · 进行中' in response.text
    assert '扫描失败测试' in response.text
    assert '查看完整运行日志' not in response.text
    assert '基础候选' not in response.text
