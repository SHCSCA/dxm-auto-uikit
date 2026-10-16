"""持久旧绿只是未受信声明；实际 Worker/API 必须撤销已漂移的受管会话。"""

import pytest
from fastapi.testclient import TestClient

from src import main
from src.execution.browser_agent_worker import BrowserAgentRuntime
from tests.support.manual_login_case import make_case


@pytest.mark.parametrize('cached_green', [False, True], ids=['initial_false', 'old_green'])
def test_live_status_revokes_drifted_manual_pin_without_rebinding(monkeypatch, tmp_path, cached_green):
    runtime = BrowserAgentRuntime()
    try:
        case = runtime.run_session_operation(lambda: make_case(monkeypatch, tmp_path))
        opened = runtime.run_session_operation(case.flow.open_managed_manual_login)
        pin = case.flow._managed_manual_login
        context, browser = case.flow._context, case.flow._browser
        original_session = pin.session_id

        def drift_generation():
            state = dict(opened)
            if cached_green:
                # 这里只种入不可信缓存，绝不签发真实账号、Reader 或业务成功来源。
                state.update(ok=True, logged_in=True, reader_ready=True,
                    stage='login_success', reason_code='LOGIN_READER_READY', account_ref='synthetic-stale-claim')
            case.flow._write_state(state)
            case.flow._clear_browser_context_generation()
            changed = case.flow._bind_browser_context_generation(context)
            assert changed != original_session

        runtime.run_session_operation(drift_generation)
        monkeypatch.setattr(main, 'login_flow', case.flow)
        monkeypatch.setattr(main, 'browser_agent_runtime', runtime)
        monkeypatch.setattr(main, '_assert_batch_browser_available', lambda: None)
        response = TestClient(main.app, raise_server_exceptions=False).get('/api/dxm/live-status')

        assert response.status_code == 200, response.text
        result = response.json()
        assert result['logged_in'] is False and result['reader_ready'] is False
        assert result['reason_code'] == 'MANAGED_MANUAL_LOGIN_STOPPED'
        assert result['browser_session_id'] is None and result['account_ref'] is None
        assert case.flow.get_state()['logged_in'] is False
        assert case.flow.get_state()['reader_ready'] is False

        def require_permanent_stop():
            assert pin.stopped is True
            with pytest.raises(RuntimeError, match='MANAGED_MANUAL_LOGIN_STOPPED'):
                pin.require_context(case.flow)
            assert case.flow._managed_manual_login is pin
            assert case.flow._context is context and case.flow._browser is browser
            assert pin.session_id == original_session
            assert case.flow.browser_session_id() is None

        runtime.run_session_operation(require_permanent_stop)
    finally:
        runtime.shutdown()


def test_live_status_rechecks_pin_when_reader_returns_false_after_generation_drift(monkeypatch, tmp_path):
    runtime = BrowserAgentRuntime()
    reader_calls = []
    try:
        case = runtime.run_session_operation(lambda: make_case(monkeypatch, tmp_path))
        runtime.run_session_operation(case.flow.open_managed_manual_login)
        pin = case.flow._managed_manual_login
        context, browser = case.flow._context, case.flow._browser
        original_session = pin.session_id

        def reader_false_with_drift():
            # 仅进入 Reader 失败分支；没有业务回包、身份成功或登录资格。
            reader_calls.append(True)
            case.flow._clear_browser_context_generation()
            changed = case.flow._bind_browser_context_generation(context)
            assert changed != original_session
            return {'reader_ready': False, 'reason_code': 'BROWSER_SESSION_UNAVAILABLE'}

        monkeypatch.setattr(case.flow, '_page_looks_logged_in', lambda page: True)
        monkeypatch.setattr(case.flow, '_visible_reader_session_status', reader_false_with_drift)
        monkeypatch.setattr(main, 'login_flow', case.flow)
        monkeypatch.setattr(main, 'browser_agent_runtime', runtime)
        monkeypatch.setattr(main, '_assert_batch_browser_available', lambda: None)
        response = TestClient(main.app, raise_server_exceptions=False).get('/api/dxm/live-status')

        assert response.status_code == 200, response.text
        result = response.json()
        assert reader_calls == [True]
        assert result['reason_code'] == 'MANAGED_MANUAL_LOGIN_STOPPED'
        assert result['logged_in'] is False and result['reader_ready'] is False
        assert result['browser_session_id'] is None and result['account_ref'] is None
        assert pin.stopped and case.flow._managed_manual_login is pin
        assert case.flow._context is context and case.flow._browser is browser
        assert pin.session_id == original_session
        assert case.flow.browser_session_id() is None
    finally:
        runtime.shutdown()
