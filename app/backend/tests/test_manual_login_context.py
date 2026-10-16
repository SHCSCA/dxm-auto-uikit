"""手动登录只证明新窗口建立；不证明登录成功、输入冻结或执行授权。"""

import json
import threading
from types import SimpleNamespace

import pytest

from src.execution.browser_agent_worker import BrowserAgentRuntime
from src.execution.dxm_adapter import DxmWorkflowAdapter
from src.execution.dxm_login_flow import DxmLoginFlow
from tests.support.manual_login_case import Page, make_case


def test_cold_start_uses_owner_bootstrap_then_prepares_new_context_before_page_without_cookies(monkeypatch, tmp_path):
    case = make_case(monkeypatch, tmp_path, cold=True)
    result = DxmWorkflowAdapter(case.flow).open_managed_manual_login()
    assert result['ok'] is True and result['stage'] == 'manual_login_required'
    assert result['logged_in'] is result['reader_ready'] is False
    assert result['browser_session_id'] == case.flow.browser_session_id()
    assert [event for event, _ in case.events] == ['bootstrap', 'new_context', 'prepare_spy', 'new_page', 'goto', 'focus']
    assert case.browser.options['service_workers'] == 'block' and case.browser.options['accept_downloads'] is False
    assert case.flow._context is not case.old and case.old.closed is False
    assert case.old.pages[0].url == 'https://www.dianxiaomi.com/web/home'


def test_new_page_failure_closes_only_new_context_and_never_repromotes_old_home(monkeypatch, tmp_path):
    case = make_case(monkeypatch, tmp_path)
    previous_state = {'stage': 'login_success', 'logged_in': True, 'reader_ready': True}
    case.flow._write_state(previous_state)
    original_new_context = case.browser.new_context

    def fail_new_page(**kwargs):
        context = original_new_context(**kwargs)
        context.new_page = lambda: (_ for _ in ()).throw(RuntimeError('synthetic page failure'))
        return context

    monkeypatch.setattr(case.browser, 'new_context', fail_new_page)
    with pytest.raises(RuntimeError, match='MANAGED_MANUAL_LOGIN_OPEN_FAILED'):
        case.flow.open_managed_manual_login()
    assert case.browser.contexts[-1].closed is True and case.old.closed is False
    assert case.flow._page is case.flow._context is None
    assert case.flow.browser_session_id() is None
    with pytest.raises(RuntimeError, match='MANAGED_MANUAL_LOGIN_STOPPED'):
        case.flow._promote_dxm_page_from_connected_browser()


def test_pin_preserves_chrome_and_old_page_but_rotates_generation_and_never_exports_cookies(monkeypatch, tmp_path):
    case = make_case(monkeypatch, tmp_path)
    flow = case.flow
    old_session, port, process = flow.browser_session_id(), flow._remote_debugging_port, flow._external_browser_process
    flow.set_mutation_authorizer(lambda *args: None, {'command_id': 'old-command'})
    adapter = DxmWorkflowAdapter(flow)
    adapter.set_execution_evidence_context({'command_id': 'old-command'})
    result = adapter.open_managed_manual_login()
    assert flow.browser_session_id() != old_session and flow.browser_session_id() == result['browser_session_id']
    assert flow._browser is case.browser and flow._remote_debugging_port == port
    assert flow._external_browser_process is process
    assert flow._mutation_authorizer is flow._execution_evidence_context is None
    assert adapter._execution_evidence_context == {}
    assert flow._ensure_page_with_cookies() is flow._page
    assert flow._persist_visible_browser_cookies() is None
    assert case.old.closed is False
    assert flow._promote_dxm_page_from_connected_browser() is flow._page
    assert flow._context is case.browser.contexts[-1]


def test_login_popup_promotion_and_reader_stay_in_the_fresh_context(monkeypatch, tmp_path):
    case = make_case(monkeypatch, tmp_path)
    case.flow.open_managed_manual_login()
    context = case.flow._context
    home = Page(context, case.events)
    home.url = 'https://www.dianxiaomi.com/web/home'
    context.pages.append(home)
    assert case.flow._promote_dxm_page_from_connected_browser() is home
    assert case.flow._page is not case.old.pages[0]
    monkeypatch.setattr(case.flow, '_page_looks_like_login', lambda page: False)
    page, reader_context, session = case.flow._draft_reader_session()
    assert page is home and reader_context is context and session == case.flow.browser_session_id()


@pytest.mark.parametrize('kind,reason', [('headless', 'VISIBLE_BROWSER_REQUIRED'),
    ('foreign_owner', 'OWNER_THREAD_MISMATCH'), ('disconnected', 'BROWSER_UNAVAILABLE')])
def test_existing_invalid_browser_is_not_recycled_or_touched(monkeypatch, tmp_path, kind, reason):
    case = make_case(monkeypatch, tmp_path)
    previous_state = {'stage': 'login_success', 'logged_in': True, 'reader_ready': True}
    case.flow._write_state(previous_state)
    if kind == 'headless':
        case.flow._is_headless = lambda: True
    elif kind == 'foreign_owner':
        case.flow._browser_session_thread_id += 1
    else:
        case.browser.connected = False
    monkeypatch.setattr(case.flow, '_ensure_page', lambda: pytest.fail('不能回收已有浏览器'))
    with pytest.raises(RuntimeError, match=reason):
        case.flow.open_managed_manual_login()
    assert case.events == [] and len(case.browser.contexts) == 1
    assert case.flow._context is case.old and case.old.closed is False
    assert json.loads(case.flow.state_file.read_text(encoding='utf-8')) == previous_state


def test_duplicate_call_does_not_navigate_or_replace_manual_input_page(monkeypatch, tmp_path):
    case = make_case(monkeypatch, tmp_path)
    case.flow.open_managed_manual_login()
    page, context, session = case.flow._page, case.flow._context, case.flow.browser_session_id()
    before = list(case.events)
    before_state = case.flow.state_file.read_text(encoding='utf-8')
    with pytest.raises(RuntimeError, match='ALREADY_OPEN'):
        case.flow.open_managed_manual_login()
    assert case.events == before and case.flow._page is page and case.flow._context is context
    assert case.flow.browser_session_id() == session
    assert case.flow.state_file.read_text(encoding='utf-8') == before_state


@pytest.mark.parametrize('phase', ['factory', 'goto', 'focus', 'state_write'])
def test_failure_at_each_new_context_boundary_stops_without_old_context_fallback(monkeypatch, tmp_path, phase, caplog):
    case = make_case(monkeypatch, tmp_path)

    def fail(*args, **kwargs):
        raise RuntimeError('synthetic boundary failure')

    if phase == 'factory':
        monkeypatch.setattr(case.browser, 'new_context', fail)
    elif phase == 'goto':
        monkeypatch.setattr(Page, 'goto', fail)
    elif phase == 'focus':
        monkeypatch.setattr('src.execution.manual_login_context.bring_controlled_page_to_front', lambda page: False)
    else:
        monkeypatch.setattr(case.flow, '_write_state', fail)
    with pytest.raises(RuntimeError, match='OPEN_FAILED'):
        case.flow.open_managed_manual_login()
    assert case.old.closed is False and case.flow._browser is case.browser
    assert case.flow._page is case.flow._context is case.flow.browser_session_id() is None
    if phase not in {'factory', 'state_write'}:
        assert case.browser.contexts[-1].closed is True
    else:
        assert len(case.browser.contexts) == 1
    if phase != 'state_write':
        state = json.loads(case.flow.state_file.read_text(encoding='utf-8'))
        assert state['stage'] == 'manual_login_stopped' and state['logged_in'] is state['reader_ready'] is False
    with pytest.raises(RuntimeError, match='STOPPED'):
        case.flow._ensure_page()
    assert 'managed_manual_login_open_failed' in caplog.text


@pytest.mark.parametrize('drift', ['page', 'session', 'closed'])
def test_pinned_owner_drift_stops_cookie_helpers_and_cannot_reclaim_old_home(monkeypatch, tmp_path, drift):
    case = make_case(monkeypatch, tmp_path)
    case.flow.open_managed_manual_login()
    if drift == 'page':
        case.flow._page = case.old.pages[0]
    elif drift == 'session':
        case.flow._browser_session_generation = 'caller-replaced-generation'
    else:
        case.flow._context.close()
    with pytest.raises(RuntimeError, match='STOPPED'):
        case.flow._ensure_page_with_cookies()
    with pytest.raises(RuntimeError, match='STOPPED'):
        case.flow._persist_visible_browser_cookies()
    assert case.old.closed is False


def test_manual_window_and_reader_use_the_existing_browser_agent_owner_executor(monkeypatch, tmp_path):
    case = make_case(monkeypatch, tmp_path, cold=True)
    runtime = BrowserAgentRuntime()
    monkeypatch.setattr(case.flow, '_page_looks_like_login', lambda page: False)
    try:
        result = runtime.run_session_operation(case.flow.open_managed_manual_login)
        reader = runtime.run_session_operation(case.flow._draft_reader_session)
        assert reader[1] is case.flow._context and reader[2] == result['browser_session_id']
        owners = {owner for _, owner in case.events}
        assert owners == {case.flow._browser_session_thread_id} and threading.get_ident() not in owners
    finally:
        runtime.shutdown()


def test_actual_ensure_page_cold_branch_only_bootstraps_chrome_before_new_manual_context(monkeypatch, tmp_path):
    case = make_case(monkeypatch, tmp_path, cold=True)
    case.flow._ensure_page = DxmLoginFlow._ensure_page.__get__(case.flow)
    case.flow._latest_live_hud = {'old_task': 'must-not-touch-old-page'}
    monkeypatch.setattr('src.execution.dxm_login_flow.sync_playwright',
        lambda: SimpleNamespace(start=lambda: SimpleNamespace()))
    monkeypatch.setattr('src.execution.dxm_login_flow.chrome_launch_options',
        lambda headless: {'headless': headless, 'executable_path': 'synthetic-chrome'})
    monkeypatch.setattr(case.flow, '_use_persistent_visible_profile', lambda: True)
    monkeypatch.setattr(case.flow, '_workflow_browser_profile_dir', lambda: tmp_path / 'synthetic-profile')
    monkeypatch.setattr(case.flow, '_ensure_visible_remote_debugging_port', lambda: 8123)

    def external_attach(_profile_dir, _launch_kwargs):
        case.events.append(('external_attach_spy', threading.get_ident()))
        case.flow._browser, case.flow._context = case.browser, case.old
        case.flow._bind_browser_context_generation(case.old)
        return case.old.pages[0]

    monkeypatch.setattr(case.flow, '_launch_visible_persistent_context_over_cdp', external_attach)
    result = case.flow.open_managed_manual_login()
    assert result['reason_code'] == 'MANAGED_MANUAL_LOGIN_REQUIRED'
    assert [event for event, _ in case.events] == ['external_attach_spy', 'new_context', 'prepare_spy', 'new_page', 'goto', 'focus']
    assert case.flow._context is not case.old and case.old.closed is False
    assert case.flow._latest_live_hud == {'old_task': 'must-not-touch-old-page'}
