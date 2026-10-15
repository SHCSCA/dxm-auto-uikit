from src.execution.dxm_login_flow import DxmLoginFlow
from tests.test_login_flow import DummyLiveClient, DummySaveOnlyNetworkPage, _arm_editor_action_test, _save_only_kwargs


def visible_save_case(monkeypatch, tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    _arm_editor_action_test(flow, monkeypatch, tmp_path)
    page = DummySaveOnlyNetworkPage()
    page.url = 'https://www.dianxiaomi.com/web/smt/edit?id=123'
    monkeypatch.setattr(flow, '_is_visible_dxm_editor_page', lambda _page: True)
    monkeypatch.setattr(flow, '_structured_save_status_snapshot', lambda *_args, **_kwargs: {'ok': True, 'entries': []})
    return flow, page


def test_visible_editor_save_binds_semantic_click_network_body_and_post_save_fields(monkeypatch, tmp_path):
    flow, page = visible_save_case(monkeypatch, tmp_path)
    monkeypatch.setattr(flow, '_visible_save_success_state', lambda *_args, **_kwargs: {
        'ok': True, 'success_text': '保存成功',
    })
    state = flow._save_only_on_page(page, **_save_only_kwargs())
    result = state['save_result']
    assert state['stage'] == 'save_only'
    assert page.semantic_save.dispatches == 1
    assert page.clicks == []
    assert result['click_method'] == 'playwright_exact_role'
    assert result['mutation_authorization']['executed'] is True
    assert result['network_save_result']['receipt_complete'] is True
    assert result['network_save_result']['request_body_sha256'] != result['network_save_result']['response_body_sha256']
    assert len(result['save_field_readbacks']) == 1
    assert result['save_field_readbacks'][0]['readback_proven'] is True
    assert result['network_audit']['publish_request_count'] == 0


def test_visible_editor_save_cancelled_before_dispatch_never_claims_saved(monkeypatch, tmp_path):
    flow, page = visible_save_case(monkeypatch, tmp_path)
    monkeypatch.setattr(flow, '_click_exact_save_button', lambda *_args, **_kwargs: False)
    state = flow._save_only_on_page(page, **_save_only_kwargs())
    assert state['stage'] == 'save_only_failed'
    assert state['published'] is None
    assert state['save_result']['reason'] == 'playwright_exact_role_save_click_failed'
    assert state['save_result']['zero_click_proven'] is True
    assert page.semantic_save.dispatches == 0
    assert state['save_result']['network_audit']['mutation_request_count'] == 0
