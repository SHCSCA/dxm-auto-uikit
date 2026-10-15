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


def test_save_only_rejects_publish_buttons(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    _arm_editor_action_test(flow, monkeypatch, tmp_path)
    page = DummySemiPage({'ok': False, 'reason': '命中发布按钮：保存并发布', 'published': False})

    state = flow._save_only_on_page(page, **_save_only_kwargs())

    assert state['stage'] == 'save_only_failed'
    assert state['published'] is None
    assert state['save_result']['exact_save_count'] == 0
    assert page.semantic_save.dispatches == 0



def test_save_only_dismisses_blocking_modals_before_locating_save(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    _arm_editor_action_test(flow, monkeypatch, tmp_path)
    page = DummySaveOnlyNetworkPage()
    calls = []

    monkeypatch.setattr(flow, '_is_headless', lambda: True)
    monkeypatch.setattr(flow, '_dismiss_blocking_modals', lambda target_page: calls.append('dismiss') or 1)

    state = flow._save_only_on_page(page, **_save_only_kwargs())

    assert state['stage'] == 'save_only_failed'
    assert state['save_result']['network_save_result']['ok'] is True
    assert state['save_result']['page_save_result']['ok'] is False
    assert calls == ['dismiss']
    assert page.semantic_save.dispatches == 1
    assert page.snapshot_calls == 2



@pytest.mark.parametrize(
    ('baseline_entries', 'current_entries', 'expected_stage', 'expected_reason'),
    [
        ([], [], 'save_only_failed', 'structured_save_success_missing'),
        (
            [{'id': 'old-toast', 'text': '已保存', 'status': '', 'source': 'role-status'}],
            [{'id': 'old-toast', 'text': '已保存', 'status': '', 'source': 'role-status'}],
            'save_only_failed',
            'stale_save_success_status',
        ),
        (
            [],
            [{'id': 'new-toast', 'text': '产品编辑成功', 'status': '', 'source': 'ant-notification-notice'}],
            'save_only',
            None,
        ),
    ],
    ids=['body-text-only', 'unchanged-old-toast', 'new-toast'],
)
def test_other_save_only_requires_new_structured_status_transition(
    monkeypatch,
    tmp_path,
    baseline_entries,
    current_entries,
    expected_stage,
    expected_reason,
):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    _arm_editor_action_test(flow, monkeypatch, tmp_path)

    class StructuredSavePage:
        url = 'https://www.dianxiaomi.com/web/smt/edit?id=123'

        def __init__(self):
            self.snapshot_calls = 0
            self.action_calls = 0
            self.button = SemanticButton()

        def get_by_role(self, role, *, name, exact):
            assert (role, name, exact) == ('button', '保存', True)
            return SemanticLocator([self.button])

        def evaluate(self, script, arg=None):
            if _is_dismiss_blocking_modals_script(script):
                return {'visible': False}
            if _is_visible_blocking_modal_state_script(script):
                return {'visible': False}
            if '__DXM_STRUCTURED_SAVE_STATUS_SNAPSHOT__' in script:
                entries = baseline_entries if self.snapshot_calls == 0 else current_entries
                self.snapshot_calls += 1
                return {'ok': True, 'entries': entries}
            self.action_calls += 1
            if self.action_calls == 1:
                return {
                    'ok': True,
                    'rect': {'x': 10, 'y': 20, 'w': 30, 'h': 40},
                    'message': '已定位保存按钮',
                    'published': False,
                }
            return {'ok': True, 'success_text': '已保存', 'published': False}

        def wait_for_timeout(self, _timeout):
            return None

        def title(self):
            return '店小秘编辑页'

    page = StructuredSavePage()
    monkeypatch.setattr(flow, '_is_headless', lambda: True)
    monkeypatch.setattr(flow, '_capture_save_network_events', lambda *_args, **_kwargs: {})
    monkeypatch.setattr(flow, '_finalize_save_network_audit', lambda *_args: _complete_save_network_capture())
    monkeypatch.setattr(flow, '_network_save_result', lambda _events: {'ok': True, 'method': 'POST', 'code': 0})

    state = flow._save_only_on_page(page, **_save_only_kwargs())

    assert state['stage'] == expected_stage
    assert state['save_result']['page_save_result'].get('reason') == expected_reason
    assert state['save_result']['network_save_result']['ok'] is True



def test_save_only_stops_when_blocking_modal_remains_after_dismiss(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    _arm_editor_action_test(flow, monkeypatch, tmp_path)
    page = DummySaveOnlyNetworkPage()
    flow._last_dismiss_blocking_modals_trace = [{'clicked': 'modal-close'}]

    monkeypatch.setattr(flow, '_dismiss_blocking_modals', lambda target_page: 10)
    monkeypatch.setattr(
        flow,
        '_visible_blocking_modal_state',
        lambda target_page: {'visible': True, 'text': '距离活动结束仅剩 我知道了'},
    )

    state = flow._save_only_on_page(page, **_save_only_kwargs())

    assert state['stage'] == 'save_only_failed'
    assert page.clicks == []
    assert state['save_result']['reason'] == '保存前弹窗未能关闭'
    assert state['save_result']['blocking_modal']['visible'] is True

