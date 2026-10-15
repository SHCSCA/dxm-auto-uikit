from pathlib import Path

import pytest

from src.execution.dxm_login_flow import DxmLoginFlow
from tests.support.network_receipts import complete_save_receipt
from tests.support.semantic_save import SemanticButton, SemanticLocator
from tests.test_login_flow import (
    DummyLiveClient, DummyOpenSemiPage, DummySemiPage, DummySaveOnlyNetworkPage, DummySaveOnlyVerifyPage,
    _arm_editor_action_test, _save_only_kwargs, _legacy_explicit_editor_defaults,
    _complete_save_network_capture, _is_dismiss_blocking_modals_script, _is_visible_blocking_modal_state_script,
)


def test_save_click_revalidates_at_exact_mutation_instant(monkeypatch, tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    _arm_editor_action_test(flow, monkeypatch, tmp_path)
    clicks = []

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/smt/edit'

        def get_by_role(self, role, *, name, exact):
            assert (role, name, exact) == ('button', '保存', True)
            return SemanticLocator([SemanticButton()])

        def evaluate(self, *_args, **_kwargs):
            return {'ok': True, 'rect': {'x': 10, 'y': 20, 'w': 80, 'h': 30}, 'published': False}

        def wait_for_timeout(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(flow, '_is_visible_dxm_editor_page', lambda _page: False)
    monkeypatch.setattr(flow, '_dismiss_blocking_modals', lambda _page: 0)
    monkeypatch.setattr(flow, '_visible_blocking_modal_state', lambda _page: {'visible': False})
    monkeypatch.setattr(flow, '_capture_save_network_events', lambda *_args, **_kwargs: {})
    monkeypatch.setattr(flow, '_finalize_save_network_audit', lambda *_args: _complete_save_network_capture())
    def fake_save_click(_page, **kwargs):
        def operation():
            clicks.append('save')
            return True

        return flow._dispatch_authorized_mutation(
            kwargs['mutation_action'],
            operation,
        )['operation_result']

    monkeypatch.setattr(flow, '_click_exact_save_button', fake_save_click)
    monkeypatch.setattr(flow, '_click_rect_center', lambda *_args, **_kwargs: clicks.append('rect'))
    flow.set_mutation_authorizer(
        lambda _context, _operation: {'ok': False, 'reason_code': 'AUTH_CONTEXT_MISMATCH'},
        {'task_id': 9, 'job_id': 10, 'state': 'SAVE_ONLY', 'mode': 'single_save'},
    )

    with pytest.raises(RuntimeError, match='AUTH_CONTEXT_MISMATCH'):
        flow._save_only_on_page(FakePage(), **_save_only_kwargs())

    assert clicks == []



def test_visible_save_only_requires_network_and_page_success(monkeypatch, tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    _arm_editor_action_test(flow, monkeypatch, tmp_path)
    flow.set_execution_evidence_context({
        'task_id': 3,
        'job_id': 4,
        'state': 'SAVE_ONLY',
        'command_id': f'command-save-proof-{tmp_path.parent.name}-{tmp_path.name}',
    })

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/smt/edit?id=123'

        def wait_for_timeout(self, _timeout):
            return None

        def screenshot(self, *, path, **_kwargs):
            Path(path).write_bytes(b'save-proof')

        def get_by_role(self, role, *, name, exact):
            assert (role, name, exact) == ('button', '保存', True)
            return SemanticLocator([SemanticButton()])

    monkeypatch.setattr(flow, '_capture_scoped_evidence_screenshot', DxmLoginFlow._capture_scoped_evidence_screenshot.__get__(flow))

    monkeypatch.setattr(flow, '_is_visible_dxm_editor_page', lambda _page: True)
    monkeypatch.setattr(flow, '_visible_exact_save_button_state', lambda _page: {
        'ok': True,
        'text': '保存', 'exact_save_count': 1, 'semantic_match_count': 1,
        'locator_index': 0, 'click_method': 'playwright_exact_role',
    })
    monkeypatch.setattr(flow, '_capture_save_network_events', lambda *_args, **_kwargs: {})
    monkeypatch.setattr(flow, '_finalize_save_network_audit', lambda *_args: _complete_save_network_capture())
    monkeypatch.setattr(flow, '_click_point_with_native_window', lambda *_args, **_kwargs: True)
    monkeypatch.setattr(flow, '_structured_save_status_snapshot', lambda *_args, **_kwargs: {'ok': True, 'entries': []})
    monkeypatch.setattr(
        flow,
        '_visible_save_success_state',
        lambda _page, *, baseline=None: {'ok': True, 'success_text': '保存成功'},
    )
    monkeypatch.setattr(flow, '_network_save_result', lambda _events: {'ok': False})

    result = flow._save_only_on_page(FakePage(), **_save_only_kwargs())

    assert result['ok'] is False
    assert result['stage'] == 'save_only_failed'
    assert result['save_result']['page_save_result']['ok'] is True
    assert result['save_result']['network_save_result']['ok'] is False
    assert set(result['evidence_ref']) == {'path', 'sha256', 'size'}
    assert Path(result['evidence_ref']['path']).read_bytes() == b'save-proof'



def test_network_save_result_prefers_real_add_json_over_related_history_calls(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    result = flow._network_save_result([
        complete_save_receipt({
            'url': 'https://www.dianxiaomi.com/api/smtProduct/add.json',
            'method': 'POST',
            'request_observed': True,
            'mutation_kind': 'save_request',
            'status': 200,
            'json': {'code': 0, 'msg': 'Successful', 'data': {'msg': '您的产品编辑成功！', 'code': 0}},
        }),
        {
            'url': 'https://www.dianxiaomi.com/api/smtProduct/addProductBrandHistory.json',
            'method': 'POST',
            'request_observed': True,
            'mutation_kind': 'mutation_request',
            'status': 200,
            'json': {'code': 0, 'msg': 'Successful', 'data': 123},
        },
    ])

    assert result['ok'] is True
    assert result['url'] == 'https://www.dianxiaomi.com/api/smtProduct/add.json'
    assert result['msg'] == '您的产品编辑成功！'



def test_network_save_result_requires_post_2xx_for_real_smt_add_json(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    result = flow._network_save_result([
        {
            'url': 'https://www.dianxiaomi.com/api/smtProduct/add.json',
            'method': 'GET',
            'request_observed': True,
            'mutation_kind': 'save_request',
            'status': 200,
            'json': {'code': 0, 'msg': 'Successful', 'data': {'msg': '您的产品编辑成功！', 'code': 0}},
        },
        {
            'url': 'https://www.dianxiaomi.com/api/smtProduct/add.json',
            'method': 'POST',
            'request_observed': True,
            'mutation_kind': 'save_request',
            'status': 500,
            'json': {'code': 0, 'msg': 'Successful', 'data': {'msg': '您的产品编辑成功！', 'code': 0}},
        },
    ])

    assert result['ok'] is False
    assert result['url'] == 'https://www.dianxiaomi.com/api/smtProduct/add.json'
    assert result['code'] == 0

