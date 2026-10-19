"""合成 Reader 失败只验证投影与原 pin，不提供真实登录或读取能力证据。"""

import json
from datetime import datetime, timezone

import pytest

from src.execution import live_session_state as module
from src.execution import reader_http_observation as diagnostic
from tests.support.manual_login_case import make_case


@pytest.fixture
def case(monkeypatch, tmp_path):
    current = make_case(monkeypatch, tmp_path)
    current.flow.open_managed_manual_login()
    monkeypatch.setattr(current.flow, '_page_looks_logged_in', lambda page: page is current.flow._page)
    return current


def seed_stale_state(case, **changes):
    state = {**case.flow._default_state(), 'ok': True, 'stage': 'login_failed',
        'reason_code': 'STALE_READER_FAILURE', 'logged_in': True, 'reader_ready': False,
        'account_ref': 'synthetic-old-reader-account', 'browser_session_id': 'synthetic-old-reader-session',
        'reader_checked_at': '2020-01-01T00:00:00Z', 'executionAllowed': True,
        'capabilityCertified': True, 'inputFreezeAllowed': True, **changes}
    case.flow._write_state(state)
    return state


@pytest.mark.parametrize('previous_login', [False, True])
def test_fresh_reader_failure_replaces_stale_reason_and_clears_reader_claims(monkeypatch, case, previous_login):
    flow = case.flow
    seed_stale_state(case, logged_in=previous_login)
    original = (flow._managed_manual_login, flow._context, flow._page, flow.browser_session_id())
    checked_at = '2026-10-19T04:05:06Z'
    monkeypatch.setattr(flow, '_visible_reader_session_status', lambda: {
        'reader_ready': False, 'reason_code': 'DXM_READ_HTTP_FAILED', 'checked_at': checked_at,
        'logged_in': False, 'account_ref': 'untrusted-status-account', 'browser_session_id': 'wrong-status-session',
        'executionAllowed': True, 'capabilityCertified': True, 'inputFreezeAllowed': True,
        'message': 'SECRET_URL https://example.invalid/private', 'next_action': 'reopen_browser'})

    result = flow.get_live_state()

    assert result['reason_code'] == 'DXM_READ_HTTP_FAILED'
    assert result['ok'] is result['reader_ready'] is False and result['logged_in'] is True
    assert result['stage'] == 'login_success' and result['reader_checked_at'] == checked_at
    assert result['account_ref'] is result['browser_session_id'] is None
    assert all(result[key] is False for key in ('executionAllowed', 'capabilityCertified', 'inputFreezeAllowed'))
    assert result['requires_user_action'] is True and '保留当前' in result['next_action']
    assert 'SECRET' not in json.dumps(result) and 'reopen_browser' not in json.dumps(result)
    assert json.loads(flow.state_file.read_text(encoding='utf-8')) == result
    assert (flow._managed_manual_login, flow._context, flow._page, flow.browser_session_id()) == original
    assert not original[0].stopped and not original[1].closed


@pytest.mark.parametrize('supplied', [None, '', 'not-a-time', False, {'private': 'SECRET'}])
def test_missing_or_invalid_reader_time_uses_local_utc_clock(monkeypatch, case, supplied):
    seed_stale_state(case)
    local_now = '2026-10-19T05:06:07Z'
    status = {'reader_ready': False, 'reason_code': 'DXM_READ_HTTP_FAILED'}
    if supplied is not None:
        status['checked_at'] = supplied
    monkeypatch.setattr(module, 'now_iso', lambda: local_now)
    monkeypatch.setattr(case.flow, '_visible_reader_session_status', lambda: status)

    result = case.flow.get_live_state()

    assert result['reader_checked_at'] == local_now and result['updated_at'] == local_now
    assert datetime.fromisoformat(result['reader_checked_at']).utcoffset() == timezone.utc.utcoffset(None)
    assert result['reason_code'] == 'DXM_READ_HTTP_FAILED'


def test_pin_rechecked_after_reader_false_before_new_negative_is_persisted(monkeypatch, case):
    flow = case.flow
    seed_stale_state(case)
    context, pin, original_session = flow._context, flow._managed_manual_login, flow.browser_session_id()
    writes, write = [], flow._write_state
    def record_write(state):
        writes.append(dict(state))
        write(state)
    def reader_false_after_drift():
        flow._clear_browser_context_generation()
        assert flow._bind_browser_context_generation(context) != original_session
        return {'reader_ready': False, 'reason_code': 'DXM_READ_HTTP_FAILED'}
    monkeypatch.setattr(flow, '_write_state', record_write)
    monkeypatch.setattr(flow, '_visible_reader_session_status', reader_false_after_drift)

    result = flow.get_live_state()

    assert result['reason_code'] == 'MANAGED_MANUAL_LOGIN_STOPPED'
    assert result['logged_in'] is result['reader_ready'] is False
    assert all(state['reason_code'] != 'DXM_READ_HTTP_FAILED' for state in writes)
    assert pin.stopped and flow._managed_manual_login is pin and flow._context is context
    assert flow.browser_session_id() is None and pin.session_id == original_session


def test_latest_failed_observation_is_replaced_on_each_explicit_status_check(monkeypatch, case):
    seed_stale_state(case)
    statuses = iter([
        {'reader_ready': False, 'reason_code': 'DXM_READ_HTTP_FAILED', 'checked_at': '2026-10-19T05:06:07Z'},
        {'reader_ready': False, 'reason_code': 'DXM_RESPONSE_SCHEMA_INVALID', 'checked_at': '2026-10-19T05:06:08Z'},
    ])
    monkeypatch.setattr(case.flow, '_visible_reader_session_status', lambda: next(statuses))

    first, second = case.flow.get_live_state(), case.flow.get_live_state()

    assert first['reason_code'] == 'DXM_READ_HTTP_FAILED'
    assert second['reason_code'] == 'DXM_RESPONSE_SCHEMA_INVALID'
    assert second['reader_checked_at'] == '2026-10-19T05:06:08Z'
    assert json.loads(case.flow.state_file.read_text(encoding='utf-8')) == second


def test_page_without_current_logged_in_evidence_does_not_create_new_login_claim(monkeypatch, case):
    previous = seed_stale_state(case, ok=False, logged_in=False, account_ref=None, browser_session_id=None)
    monkeypatch.setattr(case.flow, '_page_looks_logged_in', lambda page: False)
    monkeypatch.setattr(case.flow, '_visible_reader_session_status', lambda: pytest.fail('不能绕过页面证据'))

    assert case.flow.get_live_state() == previous


def test_recovery_replaces_failed_label_and_uses_this_reader_check_time(monkeypatch, case):
    flow = case.flow
    seed_stale_state(case)
    current_pin, current_session = flow._managed_manual_login, flow.browser_session_id()
    statuses = iter([
        {'reader_ready': False, 'reason_code': 'DXM_READ_HTTP_FAILED', 'checked_at': '2026-10-19T05:06:07Z'},
        {'reader_ready': True, 'reason_code': 'LOGIN_READER_READY', 'checked_at': '2026-10-19T13:06:08+08:00',
            'browser_session_id': current_session, 'account_ref': 'b' * 32},
    ])
    monkeypatch.setattr(flow, '_visible_reader_session_status', lambda: next(statuses))

    failed, recovered = flow.get_live_state(), flow.get_live_state()

    assert failed['reader_ready'] is False and '未就绪' in failed['label']
    assert recovered['reader_ready'] is True and recovered['logged_in'] is True
    assert recovered['label'] == '已登录'
    assert recovered['reason_code'] == 'LOGIN_READER_READY'
    assert recovered['reader_checked_at'] == '2026-10-19T05:06:08Z'
    assert recovered['browser_session_id'] == current_session and recovered['account_ref'] == 'b' * 32
    assert flow._managed_manual_login is current_pin and not current_pin.stopped
    assert json.loads(flow.state_file.read_text(encoding='utf-8')) == recovered
    assert all(recovered[key] is False for key in ('executionAllowed', 'capabilityCertified', 'inputFreezeAllowed'))


def fail_all_diagnostic_sinks(monkeypatch):
    def fail(*_args, **_kwargs):
        raise RuntimeError('synthetic-private-log-sink-failure')
    monkeypatch.setattr(module, 'log_event', fail)
    monkeypatch.setattr(diagnostic, 'log_event', fail)
    monkeypatch.setattr(diagnostic._FALLBACK, 'warning', fail)


@pytest.mark.parametrize('checked_at', ['2026-10-19T05:06:07Z', 'invalid-private-check-time'])
def test_all_log_sinks_failing_cannot_prevent_fresh_negative_projection(monkeypatch, case, checked_at):
    seed_stale_state(case)
    fail_all_diagnostic_sinks(monkeypatch)
    local_now = '2026-10-19T05:06:08Z'
    monkeypatch.setattr(module, 'now_iso', lambda: local_now)
    monkeypatch.setattr(case.flow, '_visible_reader_session_status', lambda: {
        'reader_ready': False, 'reason_code': 'DXM_READ_HTTP_FAILED', 'checked_at': checked_at})

    result = case.flow.get_live_state()

    assert result['reason_code'] == 'DXM_READ_HTTP_FAILED' and result['reader_ready'] is False
    assert result['reader_checked_at'] == (local_now if checked_at.startswith('invalid') else checked_at)
    assert json.loads(case.flow.state_file.read_text(encoding='utf-8')) == result
    assert 'private' not in json.dumps(result)


def test_all_log_sinks_failing_preserve_original_state_write_error(monkeypatch, case):
    seed_stale_state(case)
    fail_all_diagnostic_sinks(monkeypatch)
    original = OSError('synthetic-private-original-state-write-error')
    monkeypatch.setattr(case.flow, '_visible_reader_session_status', lambda: {
        'reader_ready': False, 'reason_code': 'DXM_READ_HTTP_FAILED', 'checked_at': '2026-10-19T05:06:07Z'})
    def fail_write(_state):
        raise original
    monkeypatch.setattr(case.flow, '_write_state', fail_write)

    with pytest.raises(OSError) as caught:
        case.flow.get_live_state()

    assert caught.value is original
