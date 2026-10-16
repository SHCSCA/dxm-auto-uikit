"""显式重开才可替换已停止的 pin；普通恢复仍拒绝，合成引导不证明真实窗口。"""

from types import SimpleNamespace

import pytest

from src.execution.dxm_login_flow import DxmLoginFlow
from tests.support.manual_login_case import Browser, Context, make_case


@pytest.fixture
def reopen_case(monkeypatch, tmp_path):
    case = make_case(monkeypatch, tmp_path, cold=True)
    flow, launches = case.flow, []
    flow._ensure_page = DxmLoginFlow._ensure_page.__get__(flow)
    flow._external_browser_process = None
    monkeypatch.setattr('src.execution.dxm_login_flow.sync_playwright',
        lambda: SimpleNamespace(start=lambda: SimpleNamespace(stop=lambda: None)))
    monkeypatch.setattr('src.execution.dxm_login_flow.chrome_launch_options',
        lambda headless: {'headless': headless, 'executable_path': 'synthetic-chrome'})
    monkeypatch.setattr(flow, '_use_persistent_visible_profile', lambda: True)
    monkeypatch.setattr(flow, '_workflow_browser_profile_dir', lambda: tmp_path / 'synthetic-profile')
    monkeypatch.setattr(flow, '_ensure_visible_remote_debugging_port', lambda: 8123)

    def attach(_profile_dir, _launch_kwargs):
        context = Context(case.events, old=True)
        browser = Browser(case.events, context)
        browser.close = lambda: setattr(browser, 'connected', False)
        launches.append(browser)
        flow._browser, flow._context = browser, context
        flow._bind_browser_context_generation(context)
        return context.pages[0]

    monkeypatch.setattr(flow, '_launch_visible_persistent_context_over_cdp', attach)
    return flow, launches


def test_closed_manual_lifecycle_requires_explicit_reopen_and_receives_a_new_generation(reopen_case):
    flow, launches = reopen_case
    first = flow.open_managed_manual_login()
    previous_pin, previous_context = flow._managed_manual_login, flow._context
    flow._close_browser_session()
    assert flow._browser is None and previous_pin.stopped and previous_context.closed
    with pytest.raises(RuntimeError, match='MANAGED_MANUAL_LOGIN_STOPPED'):
        flow._ensure_page()
    assert len(launches) == 1
    second = flow.open_managed_manual_login()
    assert second['reason_code'] == 'MANAGED_MANUAL_LOGIN_REQUIRED'
    assert first['browser_session_id'] != second['browser_session_id'] == flow.browser_session_id()
    assert len(launches) == 2 and flow._managed_manual_login is not previous_pin
    assert flow._context is not previous_context and previous_context.closed
    assert flow._ensure_page_with_cookies() is flow._page
    flow._persist_visible_browser_cookies()


def test_failed_explicit_reopen_restores_stopped_pin_instead_of_enabling_ordinary_recovery(reopen_case, monkeypatch):
    flow, launches = reopen_case
    flow.open_managed_manual_login()
    previous_pin = flow._managed_manual_login
    flow._close_browser_session()
    calls = []

    def fail_bootstrap(*args):
        calls.append(True)
        raise RuntimeError('synthetic explicit bootstrap failure')

    monkeypatch.setattr(flow, '_launch_visible_persistent_context_over_cdp', fail_bootstrap)
    with pytest.raises(RuntimeError, match='MANAGED_MANUAL_LOGIN_OPEN_FAILED') as failure:
        flow.open_managed_manual_login()
    assert str(failure.value.__cause__) == 'synthetic explicit bootstrap failure'
    assert calls == [True]
    assert flow._managed_manual_login is previous_pin and previous_pin.stopped
    assert len(launches) == 1 and flow.browser_session_id() is None
    with pytest.raises(RuntimeError, match='MANAGED_MANUAL_LOGIN_STOPPED'):
        flow._ensure_page()
    with pytest.raises(RuntimeError, match='MANAGED_MANUAL_LOGIN_STOPPED'):
        flow._promote_dxm_page_from_connected_browser()
    assert calls == [True]
