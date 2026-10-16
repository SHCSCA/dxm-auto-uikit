"""手动登录只建立独占会话；API 不接受登录成功自报或接管运行中的执行。"""

from threading import get_ident
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from src import main
from src.execution.browser_agent_worker import BrowserAgentRuntime
from src.execution.browser_agent_protocol import BrowserAgentCommand


@pytest.fixture
def manual_api(monkeypatch):
    calls = []

    class Adapter:
        def browser_session_id(self):
            return None

        def open_managed_manual_login(self):
            calls.append((get_ident(), runtime._session_operation_active))
            if failure[0]:
                raise RuntimeError('包含私有细节的内部失败')
            return {'ok': True, 'stage': 'manual_login_required', 'reason_code': 'MANAGED_MANUAL_LOGIN_REQUIRED',
                'logged_in': False, 'reader_ready': False, 'browser_visible': True}

    adapter = Adapter()
    runtime = BrowserAgentRuntime(adapter)
    failure = [False]
    monkeypatch.setattr(main, 'browser_agent_runtime', runtime)
    monkeypatch.setattr(main, 'workflow_adapter', adapter)
    monkeypatch.setattr(main.agent_console_service, 'status', lambda: {})
    monkeypatch.setattr(main.repo, 'get_active_task_execution', lambda: None)
    monkeypatch.setattr(main.repo, 'get_active_edit_batch_execution', lambda: None)
    yield TestClient(main.app), runtime, calls, failure
    runtime._active_lease = None
    runtime._executor.shutdown(wait=True, cancel_futures=True)


def test_actual_api_opens_on_existing_owner_thread_and_never_claims_login_success(manual_api):
    client, runtime, calls, _failure = manual_api
    requester = get_ident()
    response = client.post('/api/dxm/workflow/manual-login', json={'logged_in': True, 'reader_ready': True})
    assert response.status_code == 200
    assert response.json()['logged_in'] is False and response.json()['reader_ready'] is False
    assert calls == [(runtime._owner_thread_id, True)] and calls[0][0] != requester
    assert runtime.status()['executionLeaseActive'] is False
    assert runtime.status()['sessionOperationActive'] is False


@pytest.mark.parametrize('kind', ['task', 'batch', 'takeover', 'active', 'lease', 'reservation', 'restart', 'session'])
def test_existing_execution_or_takeover_prevents_any_manual_context_operation(manual_api, monkeypatch, kind):
    client, runtime, calls, _failure = manual_api
    if kind == 'task':
        monkeypatch.setattr(main.repo, 'get_active_task_execution', lambda: {'id': 71})
    elif kind == 'batch':
        monkeypatch.setattr(main.repo, 'get_active_edit_batch_execution', lambda: {'id': 72})
    elif kind == 'lease':
        runtime._active_lease = object()
    elif kind == 'reservation':
        runtime._command_reservations['reserved'] = object()
    elif kind == 'session':
        runtime._session_operation_active = True
    else:
        runtime._status[{'takeover': 'manualTakeover', 'active': 'active', 'restart': 'needsRestart'}[kind]] = True
    assert client.post('/api/dxm/workflow/manual-login').status_code == 409
    assert not calls


def test_manual_context_failure_is_logged_and_public_error_contains_no_private_text(manual_api, caplog):
    client, _runtime, calls, failure = manual_api
    failure[0] = True
    response = client.post('/api/dxm/workflow/manual-login')
    assert response.status_code == 409 and len(calls) == 1
    assert response.json()['detail']['reason_code'] == 'MANAGED_MANUAL_LOGIN_FAILED'
    assert '私有' not in response.text
    assert any(record.message == 'managed_manual_login_api_failed' for record in caplog.records)


@pytest.mark.parametrize('field,value', [('logged_in', True), ('reader_ready', True),
    ('reason_code', 'LOGIN_READER_READY'), ('browser_visible', False), ('stage', 'login_success')])
def test_open_window_result_cannot_be_relabelled_authenticated_or_reader_ready(manual_api, monkeypatch, field, value):
    client, runtime, calls, _failure = manual_api
    original = runtime.adapter.open_managed_manual_login

    def changed():
        return {**original(), field: value}

    monkeypatch.setattr(runtime.adapter, 'open_managed_manual_login', changed)
    response = client.post('/api/dxm/workflow/manual-login')
    assert response.status_code == 409 and len(calls) == 1
    assert response.json()['detail']['reason_code'] == 'MANAGED_MANUAL_LOGIN_FAILED'


def test_busy_existing_api_operation_is_not_queued_or_forwarded_to_owner(manual_api):
    client, _runtime, calls, _failure = manual_api
    main.login_flow_api_lock.acquire()
    try:
        response = client.post('/api/dxm/workflow/manual-login')
    finally:
        main.login_flow_api_lock.release()
    assert response.status_code == 409 and calls == []


def test_batch_started_after_http_precheck_is_rechecked_on_owner_before_opening(manual_api, monkeypatch):
    client, _runtime, calls, _failure = manual_api
    reads = []

    def started_later():
        reads.append(True)
        return None if len(reads) == 1 else {'id': 73}

    monkeypatch.setattr(main.repo, 'get_active_edit_batch_execution', started_later)
    assert client.post('/api/dxm/workflow/manual-login').status_code == 409
    assert len(reads) == 2 and not calls


@pytest.mark.parametrize('kind', ['takeover', 'reservation'])
def test_runtime_occupied_after_http_precheck_is_rejected_by_owner(manual_api, monkeypatch, kind):
    client, runtime, calls, _failure = manual_api
    original = main._run_login_flow

    def occupied_later(operation, **kwargs):
        if kind == 'takeover':
            assert runtime.request_manual_takeover()['ok'] is True
        else:
            command = BrowserAgentCommand(command_id='readonly-precheck', idempotency_key='readonly-precheck',
                deadline=(datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat(),
                expected_page='authenticated_dxm', runtime_id=runtime.runtime_id, task_id=1, job_id=1,
                state='PRECHECK_SESSION', action='check_login_state', params={})
            assert runtime.reserve_command(command)['ok'] is True
        return original(operation, **kwargs)

    monkeypatch.setattr(main, '_run_login_flow', occupied_later)
    assert client.post('/api/dxm/workflow/manual-login').status_code == 409
    assert calls == []
