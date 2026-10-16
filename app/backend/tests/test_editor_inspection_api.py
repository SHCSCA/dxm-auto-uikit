"""实际公开路由消费稳定的只读失败，不向客户端暴露内部页面或字段。"""

import threading

import pytest
from fastapi.testclient import TestClient

from src import main
from src.execution import editor_inspection_flow as subject
from src.execution.browser_agent_worker import BrowserAgentRuntime
from src.services.dxm_draft_reader import DxmDraftReaderError


@pytest.mark.parametrize('kind', ['transport', 'reader'])
def test_actual_api_returns_conflict_for_unverified_inspection_and_preserves_reader_reason(monkeypatch, caplog, kind):
    calls = []

    def failed(*_args, **_kwargs):
        if kind == 'reader':
            raise DxmDraftReaderError('DXM_PLAN_SESSION_MISMATCH', '只读检查会话已变化。')
        raise RuntimeError('private https://fixture.invalid/secret-field=value')

    class Adapter:
        def inspect_editor_readonly(self, **kwargs):
            calls.append(threading.get_ident())
            return subject.inspect_editor_readonly(object(), **kwargs)

    runtime = BrowserAgentRuntime(Adapter())
    monkeypatch.setattr(subject, '_inspect', failed)
    monkeypatch.setattr(main, 'browser_agent_runtime', runtime)
    monkeypatch.setattr(main, 'workflow_adapter', runtime.adapter)
    monkeypatch.setattr(main.agent_console_service, 'status', lambda: {})
    monkeypatch.setattr(main.repo, 'get_active_task_execution', lambda: None)
    monkeypatch.setattr(main.repo, 'get_active_edit_batch_execution', lambda: None)
    try:
        response = TestClient(main.app).post('/api/dxm/draft-reader/editor-inspection', json={
            'shop_id': '91', 'product_id': '8101', 'session_ref': 'a'*16, 'observe_dialog': 'video'})
        assert response.status_code == 409
        reason = 'EDITOR_INSPECTION_UNVERIFIED' if kind == 'transport' else 'DXM_PLAN_SESSION_MISMATCH'
        assert response.json()['detail']['reason_code'] == reason
        assert 'private' not in response.text and 'secret-field' not in response.text and 'fixture.invalid' not in response.text
        assert calls == [runtime._owner_thread_id] and calls[0] != threading.get_ident()
        assert runtime.status()['sessionOperationActive'] is False
        assert 'editor_readonly_inspection_failed' in caplog.text
    finally:
        runtime._executor.shutdown(wait=True)
