"""真实离线浏览器验证正常导航与标签替换不撤销 pin；不证明登录或可见性。"""

import threading

import pytest
from playwright.sync_api import BrowserContext, sync_playwright

from src.execution.browser_agent_worker import BrowserAgentRuntime
from src.execution.dxm_login_flow import DxmLoginFlow
from src.execution.native_video_transport import require_native_video_transport
from tests.support.manual_login_case import NoCookieClient
from tests.support.native_video_guard_browser import local_video_server


HOME = 'https://www.dianxiaomi.com/web/home'


@pytest.mark.parametrize('mode', ['navigation', 'tab_replacement'])
def test_normal_document_changes_preserve_the_original_managed_pin(monkeypatch, tmp_path, mode):
    owned = {}
    runtime = BrowserAgentRuntime()

    def forbidden_cookie(*args, **kwargs):
        pytest.fail('隔离检查不允许读取、迁移或导出 Cookie')

    monkeypatch.setattr(BrowserContext, 'cookies', forbidden_cookie)
    monkeypatch.setattr(BrowserContext, 'add_cookies', forbidden_cookie)
    monkeypatch.setattr(BrowserContext, 'storage_state', forbidden_cookie)
    with local_video_server() as (base, hits):
        monkeypatch.setattr('src.execution.manual_login_context.LOGIN_URL', base + '/')

        def verify_owned():
            playwright = sync_playwright().start()
            owned['playwright'] = playwright
            browser = playwright.chromium.launch(headless=True,
                proxy={'server': base, 'bypass': '127.0.0.1,localhost'},
                args=['--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1'])
            owned['browser'] = browser
            initial_context = browser.new_context()
            initial_page = initial_context.new_page()
            flow = DxmLoginFlow(NoCookieClient(), state_file=tmp_path / 'synthetic-state.json')
            flow._is_headless = lambda: False
            flow._browser, flow._context, flow._page = browser, initial_context, initial_page
            flow._browser_session_thread_id = threading.get_ident()
            flow._bind_browser_context_generation(initial_context)
            opened = flow.open_managed_manual_login()
            pin, context, old_page = flow._managed_manual_login, flow._context, flow._page
            page = old_page if mode == 'navigation' else context.new_page()
            page.route(HOME, lambda route: route.fulfill(status=200,
                content_type='text/html', body='<html><body>synthetic home</body></html>'))
            page.goto(HOME, wait_until='domcontentloaded')
            page.unroute(HOME)
            if mode == 'tab_replacement':
                old_page.close()
            assert flow._promote_dxm_page_from_connected_browser() is page
            page.title()
            assert pin.require_context(flow) is context
            assert flow._managed_manual_login is pin and not pin.stopped
            assert flow._context is context and flow._browser is browser
            assert flow.browser_session_id() == opened['browser_session_id'] == pin.session_id
            assert require_native_video_transport(page).installed is True
            assert opened['logged_in'] is opened['reader_ready'] is False
            assert initial_context.is_closed() is False

        def close_owned():
            if owned.get('browser') is not None:
                owned['browser'].close()
            if owned.get('playwright') is not None:
                owned['playwright'].stop()

        try:
            runtime.run_session_operation(verify_owned)
        finally:
            try:
                runtime.run_session_operation(close_owned)
            finally:
                runtime.shutdown()
        assert all('dianxiaomi' not in path for _, path, _ in hits)
