import pytest

from src.execution.dxm_login_flow import DxmLoginFlow, MutationAuthorizationError
from tests.support.semantic_save import SemanticButton, SemanticSavePage
from tests.test_login_flow import DummyLiveClient


def flow_for(tmp_path):
    return DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')


def test_exact_save_semantics_reject_hidden_disabled_and_dialog_controls(tmp_path):
    flow = flow_for(tmp_path)
    expected = SemanticButton()
    page = SemanticSavePage([SemanticButton(visible=False), SemanticButton(enabled=False),
                             SemanticButton(inside_dialog=True), expected])
    state = flow._visible_exact_save_button_state(page)
    assert state['ok'] is True
    assert state['locator_index'] == 3
    assert state['semantic_match_count'] == 4
    assert state['click_method'] == 'playwright_exact_role'
    assert expected.dispatches == 0
    assert expected.trials == 1


@pytest.mark.parametrize('buttons', [[], [SemanticButton(), SemanticButton()],
    [SemanticButton(trial_error=RuntimeError('covered by dialog'))]])
def test_exact_save_semantics_reject_missing_ambiguous_or_covered_controls(tmp_path, buttons):
    flow = flow_for(tmp_path)
    state = flow._visible_exact_save_button_state(SemanticSavePage(buttons))
    assert state['ok'] is False
    assert state['published'] is None
    assert all(button.dispatches == 0 for button in buttons)


def test_semantic_channel_failure_does_not_fall_back_to_pixels_devtools_or_dom(monkeypatch, tmp_path):
    flow = flow_for(tmp_path)
    page = SemanticSavePage()
    page.get_by_role = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError('semantic channel unavailable'))
    fallback = lambda *_args, **_kwargs: pytest.fail('禁止通过坐标、DOM 或 DevTools 兜底保存')
    monkeypatch.setattr(flow, '_capture_native_dxm_content_snapshot', fallback)
    monkeypatch.setattr(flow, '_evaluate_visible_page_function_via_devtools', fallback)
    page.evaluate_handle = fallback
    state = flow._visible_exact_save_button_state(page)
    assert state['ok'] is False
    assert 'semantic channel unavailable' in state['reason']
    assert page.buttons[0].dispatches == 0


def test_save_dispatch_revalidates_only_inside_authorizer_and_uses_semantic_click(tmp_path):
    flow = flow_for(tmp_path)
    phases = []
    page = SemanticSavePage([SemanticButton(on_click=lambda: phases.append('dispatch'))])

    def authorize(context, operation):
        phases.append('authorize')
        assert context['_pre_dispatch_guard']()['ok'] is True
        assert page.buttons[0].dispatches == 0
        return {'ok': True, 'executed': True, 'operation_result': operation()}

    flow.set_mutation_authorizer(authorize, {'task_id': 3, 'job_id': 4, 'state': 'SAVE_ONLY', 'mode': 'single_save'})
    assert flow._click_exact_save_button(page, mutation_action='save_only_click') is True
    assert phases == ['authorize', 'dispatch']
    assert page.buttons[0].dispatches == 1
    assert page.buttons[0].trials >= 3


def test_save_target_drift_after_authorization_cancels_without_any_click(tmp_path):
    flow = flow_for(tmp_path)
    page = SemanticSavePage()

    def authorize(context, operation):
        assert context['_pre_dispatch_guard']()['ok'] is True
        page.buttons[0].enabled = False
        return {'ok': True, 'executed': True, 'operation_result': operation()}

    flow.set_mutation_authorizer(authorize, {'task_id': 3})
    with pytest.raises(MutationAuthorizationError, match='MUTATION_TARGET_DRIFT'):
        flow._click_exact_save_button(page, mutation_action='save_only_click')
    assert page.buttons[0].dispatches == 0


def test_dispatched_semantic_click_error_is_unknown_and_never_uses_fallback(monkeypatch, tmp_path):
    flow = flow_for(tmp_path)
    page = SemanticSavePage([SemanticButton(dispatch_error=RuntimeError('page disappeared'))])
    fallback = lambda *_args, **_kwargs: pytest.fail('已进入派发后不得尝试第二种点击')
    monkeypatch.setattr(flow, '_click_rect_center', fallback)
    monkeypatch.setattr(flow, '_click_point_with_native_window', fallback)
    page.evaluate_handle = fallback
    flow.set_mutation_authorizer(lambda context, operation: {
        'ok': True, 'executed': True, 'operation_result': operation(),
    }, {'task_id': 3})
    with pytest.raises(MutationAuthorizationError, match='MUTATION_OUTCOME_UNKNOWN|MUTATION_OPERATION_FAILED'):
        flow._click_exact_save_button(page, mutation_action='save_only_click')
    assert page.buttons[0].dispatches == 1


@pytest.mark.parametrize('action', ['save_only_click', 'first_save_intent'])
def test_save_authorization_rejection_never_dispatches_or_retries(tmp_path, action):
    flow = flow_for(tmp_path)
    page = SemanticSavePage()
    calls = []
    flow.set_mutation_authorizer(lambda context, operation: calls.append(context) or {
        'ok': False, 'reason_code': 'AUTH_CONTEXT_MISMATCH',
    }, {'task_id': 3})
    with pytest.raises(MutationAuthorizationError, match='AUTH_CONTEXT_MISMATCH'):
        flow._click_exact_save_button(page, mutation_action=action)
    assert len(calls) == 1
    assert page.buttons[0].dispatches == 0
