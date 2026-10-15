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


def test_save_only_fails_when_success_prompt_missing_after_click(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    _arm_editor_action_test(flow, monkeypatch, tmp_path)
    page = DummySaveOnlyVerifyPage({
        'ok': False,
        'clicked': True,
        'reason': '未检测到保存成功提示',
        'success_text': None,
        'published': False,
    })

    state = flow._save_only_on_page(page, **_save_only_kwargs())

    assert page.semantic_save.dispatches == 1
    assert state['stage'] == 'save_only_failed'
    assert state['save_result']['ok'] is False
    assert 'structured_save_success_missing' in state['message']



def test_save_only_fails_when_page_success_has_no_network_success(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    _arm_editor_action_test(flow, monkeypatch, tmp_path)
    page = DummySaveOnlyVerifyPage({
        'ok': True,
        'clicked': True,
        'success_text': '产品编辑成功',
        'published': False,
    })

    state = flow._save_only_on_page(page, **_save_only_kwargs())

    assert page.semantic_save.dispatches == 1
    assert state['stage'] == 'save_only_failed'
    assert state['save_result']['ok'] is False
    assert state['save_result']['page_save_result']['ok'] is True
    assert state['save_result']['network_events'] == []
    assert state['save_result']['network_save_result'] == {
        'ok': False,
        'reason': '未捕获唯一保存接口请求',
        'receipt_count': 0,
        'receipt_complete': False,
    }



def test_save_only_succeeds_only_when_page_and_network_both_succeed(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    _arm_editor_action_test(flow, monkeypatch, tmp_path)
    page = DummySaveOnlyVerifyPage({
        'ok': True,
        'clicked': True,
        'success_text': '产品编辑成功',
        'published': False,
    })
    monkeypatch.setattr(flow, '_network_save_result', lambda _events: {
        'ok': True,
        'message': '您的产品编辑成功！',
        'method': 'POST',
        'code': 0,
    })
    monkeypatch.setattr(flow, '_save_network_audit_complete', lambda *_args: True)

    state = flow._save_only_on_page(page, **_save_only_kwargs())

    assert state['stage'] == 'save_only'
    assert state['save_result']['ok'] is True
    assert state['save_result']['page_save_result']['ok'] is True
    assert state['save_result']['network_save_result']['ok'] is True



def test_save_only_rejects_network_success_without_page_success(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    _arm_editor_action_test(flow, monkeypatch, tmp_path)
    page = DummySaveOnlyNetworkPage()
    monkeypatch.setattr(flow, '_click_point_with_native_window', lambda page, x, y, **_kwargs: False)
    monkeypatch.setattr(flow, '_click_point_with_cdp', lambda page, x, y, **_kwargs: False)

    state = flow._save_only_on_page(page, **_save_only_kwargs())

    assert state['stage'] == 'save_only_failed'
    assert page.clicks == []
    assert state['save_result']['ok'] is False
    assert state['save_result']['save_click_dispatched'] is True
    assert state['save_result']['page_save_success'] is False
    assert state['save_result']['network_save_success'] is True
    assert state['published'] is None

