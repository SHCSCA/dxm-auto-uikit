"""真实 Runtime 锁边界反例；会话操作不能被接管或迟到预约穿透。"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event

import pytest

from src.execution.browser_agent_protocol import BrowserAgentCommand
from src.execution.browser_agent_worker import BrowserAgentRuntime


@pytest.mark.parametrize('control', ['takeover', 'shutdown', 'resume'])
def test_session_owner_prevents_lifecycle_controls_until_operation_finishes(control):
    runtime = BrowserAgentRuntime()
    entered, release = Event(), Event()

    def operation():
        entered.set()
        assert release.wait(5)
        return 'finished'

    try:
        with ThreadPoolExecutor(max_workers=1) as caller:
            pending = caller.submit(runtime.run_session_operation, operation)
            try:
                assert entered.wait(5)
                result = (runtime.request_manual_takeover(timeout_seconds=0) if control == 'takeover'
                    else runtime.shutdown(timeout_seconds=0) if control == 'shutdown'
                    else runtime.release_manual_takeover())
                assert result['ok'] is False
                assert result['reasonCode'] == 'BROWSER_AGENT_SESSION_BUSY'
                assert runtime.status()['manualTakeover'] is False
            finally:
                release.set()
            assert pending.result(timeout=5) == 'finished'
        assert runtime.request_manual_takeover()['ok'] is True
    finally:
        release.set()
        runtime._executor.shutdown(wait=True, cancel_futures=True)


def test_reservation_second_lock_rejects_session_started_during_ledger_call(monkeypatch):
    runtime = BrowserAgentRuntime()
    reservation_entered, reservation_release = Event(), Event()
    session_entered, session_release = Event(), Event()
    command = BrowserAgentCommand(command_id='readonly-race', idempotency_key='readonly-race',
        deadline=(datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat(),
        expected_page='authenticated_dxm', runtime_id=runtime.runtime_id, task_id=1, job_id=1,
        state='PRECHECK_SESSION', action='check_login_state', params={})
    original = runtime._reserve_command_in_ledger

    def held_ledger(*args):
        result = original(*args)
        reservation_entered.set()
        assert reservation_release.wait(5)
        return result

    def session():
        session_entered.set()
        assert session_release.wait(5)

    monkeypatch.setattr(runtime, '_reserve_command_in_ledger', held_ledger)
    try:
        with ThreadPoolExecutor(max_workers=2) as callers:
            reservation = callers.submit(runtime.reserve_command, command)
            try:
                assert reservation_entered.wait(5)
                active_session = callers.submit(runtime.run_session_operation, session)
                assert session_entered.wait(5)
                reservation_release.set()
                result = reservation.result(timeout=5)
                assert result['ok'] is False
                assert result['reasonCode'] == 'BROWSER_AGENT_SESSION_BUSY'
                assert runtime.status()['reservedCommandCount'] == 0
            finally:
                reservation_release.set()
                session_release.set()
            active_session.result(timeout=5)
    finally:
        reservation_release.set()
        session_release.set()
        runtime._executor.shutdown(wait=True, cancel_futures=True)
