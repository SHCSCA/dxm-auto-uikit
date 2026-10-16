"""真实状态 API 并发轮询必须见到撤销；Browser 引导替身不提供业务或显示证明。"""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src import main
from src.execution.browser_agent_worker import BrowserAgentRuntime
from src.execution.dxm_adapter import DxmWorkflowAdapter
from tests.support.manual_login_case import Page, make_case


@pytest.mark.parametrize('phase', ['bootstrap', 'goto', 'focus'])
def test_runtime_status_and_flow_state_never_reapply_old_reader_ready_while_manual_open_waits(monkeypatch, tmp_path, phase):
    runtime, entered, release = BrowserAgentRuntime(), Event(), Event()
    owned = {}

    def setup():
        case = make_case(monkeypatch, tmp_path, cold=phase == 'bootstrap')
        flow = case.flow
        old_session = flow.browser_session_id() or 'previous-process-session'
        flow._write_state({'ok': True, 'stage': 'login_success', 'reason_code': 'LOGIN_READER_READY',
            'logged_in': True, 'reader_ready': True, 'browser_visible': True,
            'browser_session_id': old_session, 'account_ref': 'synthetic-old-account'})
        adapter = DxmWorkflowAdapter(flow)
        runtime.set_adapter(adapter)
        owned.update(flow=flow, adapter=adapter, old_session=old_session)
        if phase == 'bootstrap':
            bootstrap = flow._ensure_page

            def paused_bootstrap():
                page = bootstrap()
                wait_at_boundary()
                return page

            flow._ensure_page = paused_bootstrap

    def wait_at_boundary():
        entered.set()
        assert release.wait(timeout=10), '合成 barrier 超时'

    if phase == 'goto':
        goto = Page.goto

        def paused_goto(page, *args, **kwargs):
            wait_at_boundary()
            return goto(page, *args, **kwargs)

        monkeypatch.setattr(Page, 'goto', paused_goto)
    elif phase == 'focus':
        from src.execution.manual_login_context import bring_controlled_page_to_front

        def paused_focus(page):
            wait_at_boundary()
            return bring_controlled_page_to_front(page)

        monkeypatch.setattr('src.execution.manual_login_context.bring_controlled_page_to_front', paused_focus)

    try:
        runtime.run_session_operation(setup)
        monkeypatch.setattr(main, 'login_flow', owned['flow'])
        monkeypatch.setattr(main, 'workflow_adapter', owned['adapter'])
        monkeypatch.setattr(main, 'browser_agent_runtime', runtime)
        monkeypatch.setattr(main.agent_console_service, 'status', lambda: {})
        monkeypatch.setattr(main.repo, 'get_active_task_execution', lambda: None)
        monkeypatch.setattr(main.repo, 'get_active_edit_batch_execution', lambda: None)
        monkeypatch.setattr(main, '_runtime_http_service_status', lambda *args: {})
        monkeypatch.setattr(main, 'get_audit_service', lambda: SimpleNamespace(verify_chain=lambda: {}))
        monkeypatch.setattr(main, '_l2_probe_lock_status', lambda: {})
        monkeypatch.setattr(main, '_l2_readonly_probe_dependency_status', lambda: {})
        client = TestClient(main.app)
        with ThreadPoolExecutor(max_workers=1) as requests:
            pending = requests.submit(client.post, '/api/dxm/workflow/manual-login')
            try:
                assert entered.wait(timeout=10)
                assert owned['flow'].browser_session_id() not in {None, owned['old_session']}
                snapshot = owned['flow'].get_state()
                response = client.get('/api/runtime/status')
                assert response.status_code == 200
                public = response.json()['dxmLogin']
                assert public['loggedIn'] is public['readerReady'] is public['browserVisible'] is False
                assert public['status'] == 'manual_login_opening'
                assert snapshot['logged_in'] is snapshot['reader_ready'] is snapshot['browser_visible'] is False
                assert snapshot['stage'] == 'manual_login_opening' and snapshot['browser_session_id'] is None
                assert snapshot.get('account_ref') is None
            finally:
                release.set()
                result = pending.result(timeout=10)
            assert result.status_code == 200 and result.json()['reader_ready'] is False
    finally:
        release.set()
        runtime.set_adapter(None)
        runtime.shutdown()
