"""真实离线 Chromium 反例验证前置阻断；合成读取白名单不证明业务接口资格。"""

import pytest
from playwright.sync_api import sync_playwright

from src.execution.native_video_observation_guard import NativeVideoObservationGuard
from src.execution.managed_browser_context import create_managed_browser_context
from src.execution.native_video_transport import prepare_native_video_transport, bind_native_video_transport
from tests.support.native_video_guard_browser import local_video_server


@pytest.fixture
def local_browser():
    with local_video_server() as (base, hits), sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True,
            args=['--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1'])
        context = create_managed_browser_context(browser)
        transport = prepare_native_video_transport(context)
        page = context.new_page()
        binding = bind_native_video_transport(page)
        page.goto(base, wait_until='networkidle')
        hits.clear()
        try:
            yield page, transport, base, hits
        finally:
            binding.close()
            browser.close()


def local_guard(page):
    guard = NativeVideoObservationGuard(page)
    # 仅用本机合成读取隔离验证真实传输；生产 allowlist 完全不改。
    guard.guard._route = lambda route: route.continue_()
    return guard


@pytest.mark.parametrize('status', [307, 308])
def test_native_post_redirect_follow_control_reaches_second_hop_but_guard_never_does(local_browser, status):
    page, transport, base, hits = local_browser
    script = """path => fetch(path,{method:'POST',body:'original-native-body'}).then(r=>r.text()).catch(()=>null)"""
    assert page.evaluate(script, f'/redirect/{status}') == 'ok'
    assert hits == [('POST', f'/redirect/{status}', b'original-native-body'),
                    ('POST', '/second-hop', b'original-native-body')]
    hits.clear()
    guard = local_guard(page)
    with pytest.raises(RuntimeError, match='UNEXPECTED_EFFECT'):
        with guard:
            assert page.evaluate(script, f'/redirect/{status}') is None
    assert hits == [('POST', f'/redirect/{status}', b'original-native-body')]
    assert 'HTTP_REDIRECT_BLOCKED' in guard.unexpected
    assert transport.active is None


def test_context_guard_blocks_popup_first_http_request_and_dismisses_owner_dialog(local_browser):
    page, transport, base, hits = local_browser
    guard = local_guard(page)
    with pytest.raises(RuntimeError, match='UNEXPECTED_EFFECT'):
        with guard:
            with page.expect_popup() as opened:
                page.evaluate("window.open('/unreviewed-popup')")
            opened.value.wait_for_load_state('domcontentloaded')
            page.evaluate("alert('synthetic'); window.dialogReturned=true")
            assert page.evaluate('window.dialogReturned') is True
    assert all(path != '/unreviewed-popup' for _, path, _ in hits)
    assert any(reason in guard.unexpected for reason in ('FOREIGN_PAGE_OR_REDIRECT_REQUEST', 'REQUEST_GUARD_FAILED'))
    assert 'dialog' in guard.unexpected


def test_active_websocket_never_handshakes_and_failed_window_never_resumes_unrestricted_http(local_browser):
    page, transport, base, hits = local_browser
    ws = base.replace('http:', 'ws:') + '/ws'
    for _ in range(2):
        with local_guard(page):
            assert page.evaluate('1+1') == 2
    guard = local_guard(page)
    with pytest.raises(RuntimeError, match='UNEXPECTED_EFFECT'):
        with guard:
            page.evaluate("url=>{window.syntheticSocket=new WebSocket(url)}", ws)
            page.wait_for_function('window.syntheticSocket.readyState===3', timeout=3000)
    assert not any(path == '/ws' for _, path, _ in hits)
    assert transport.invalid is True and transport.active is None
    assert page.evaluate("fetch('/after-failed-window').then(()=>true).catch(()=>false)") is False
    assert not any(path == '/after-failed-window' for _, path, _ in hits)


def test_inactive_connection_remains_native_but_prevents_future_observation(local_browser):
    page, transport, base, hits = local_browser
    ws = base.replace('http:', 'ws:') + '/ws'
    page.evaluate("url=>{const ws=new WebSocket(url);ws.onmessage=e=>{window.syntheticMessage=e.data;ws.close()}}", ws)
    page.wait_for_function("window.syntheticMessage==='ok'", timeout=3000)
    assert sum(path == '/ws' for _, path, _ in hits) == 1
    assert transport.connected_before_scope is True
    with pytest.raises(RuntimeError, match='PRIOR_WEBSOCKET'):
        local_guard(page).__enter__()


def test_real_native_context_policy_is_required_before_page_creation():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for options in ({}, {'service_workers': 'allow', 'accept_downloads': False},
                            {'service_workers': 'block', 'accept_downloads': True}):
                context = browser.new_context(**options)
                with pytest.raises(RuntimeError, match='POLICY_UNPROVEN'):
                    prepare_native_video_transport(context)
                context.close()
            context = browser.new_context(service_workers='block', accept_downloads=False)
            context.new_page()
            with pytest.raises(RuntimeError, match='INSTALLED_TOO_LATE'):
                prepare_native_video_transport(context)
        finally:
            browser.close()
