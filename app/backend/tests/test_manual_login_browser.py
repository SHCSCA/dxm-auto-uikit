"""真实离线 Chromium 验证隔离上下文与 owner；隔离 headed 检查，不证明窗口可见性或登录成功。"""

import threading

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import Browser, BrowserContext, sync_playwright

from src import main
from src.execution import managed_browser_context
from src.execution.browser_agent_worker import BrowserAgentRuntime
from src.execution.dxm_adapter import DxmWorkflowAdapter
from src.execution.dxm_login_flow import DxmLoginFlow
from src.execution.native_video_transport import require_native_video_transport, bind_native_video_transport
from tests.support.manual_login_case import NoCookieClient
from tests.support.native_video_guard_browser import local_video_server


OLD_HOME = 'https://www.dianxiaomi.com/web/home'


@pytest.mark.parametrize('entry', ['adapter', 'api_owner'])
def test_native_manual_lifecycle_is_prepared_without_cookie_transfer_or_old_home_takeover(monkeypatch, tmp_path, entry):
    """headless 仅替代显示条件；API、Worker、factory、原生 context/session 均运行实际实现。"""
    owned, prepared, created, cookie_calls, calls = {}, {}, {}, [], []
    real_prepare = managed_browser_context.prepare_native_video_transport
    real_new_context, real_new_page = Browser.new_context, BrowserContext.new_page

    def forbidden_cookie_api(*args, **kwargs):
        cookie_calls.append(threading.get_ident())
        raise AssertionError('本测试不允许读取、迁移或导出 Cookie')

    def observe_prepare(context):
        assert context.pages == []
        transport = real_prepare(context)
        assert transport.installed is True
        prepared[context] = transport
        calls.append(('actual_prepare', threading.get_ident()))
        return transport

    def observe_new_context(browser, **kwargs):
        context = real_new_context(browser, **kwargs)
        if kwargs.get('service_workers') == 'block':
            assert set(kwargs) == {'ignore_https_errors', 'viewport', 'service_workers', 'accept_downloads'}
            assert kwargs['accept_downloads'] is False
            created[context] = dict(kwargs)
        return context

    def observe_new_page(context):
        if context in created:
            # 不在此补装路由；factory 漏掉 prepare 时必须在创建 Page 之前失败。
            assert context in prepared and context.pages == []
            calls.append(('new_page_after_prepare', threading.get_ident()))
        return real_new_page(context)

    monkeypatch.setattr(BrowserContext, 'cookies', forbidden_cookie_api)
    monkeypatch.setattr(BrowserContext, 'add_cookies', forbidden_cookie_api)
    monkeypatch.setattr(BrowserContext, 'storage_state', forbidden_cookie_api)
    monkeypatch.setattr(managed_browser_context, 'prepare_native_video_transport', observe_prepare)
    monkeypatch.setattr(Browser, 'new_context', observe_new_context)
    monkeypatch.setattr(BrowserContext, 'new_page', observe_new_page)

    with local_video_server() as (base, hits):
        monkeypatch.setattr('src.execution.manual_login_context.LOGIN_URL', base + '/')

        def setup():
            playwright = sync_playwright().start()
            owned['playwright'] = playwright
            # 所有非 loopback HTTP 都进入不会转发的本机合成服务器；域名另行禁止解析。
            browser = playwright.chromium.launch(headless=True,
                proxy={'server': base, 'bypass': '127.0.0.1,localhost'},
                args=['--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1'])
            owned['browser'] = browser
            old_context = browser.new_context()
            old_context.route('**/*', lambda route: route.fulfill(status=200,
                content_type='text/html', body='<html><body>synthetic old home</body></html>')
                if route.request.url == OLD_HOME else route.abort())
            old_page = old_context.new_page()
            old_page.goto(OLD_HOME, wait_until='domcontentloaded')
            flow = DxmLoginFlow(NoCookieClient(), state_file=tmp_path / 'offline-manual-state.json')
            # 此隔离仅绕过显示条件，不能作为真实可见浏览器的验收证据。
            flow._is_headless = lambda: False
            flow._browser, flow._context, flow._page = browser, old_context, old_page
            flow._browser_session_thread_id = threading.get_ident()
            old_session = flow._bind_browser_context_generation(old_context)
            adapter = DxmWorkflowAdapter(flow)
            owned.update(flow=flow, adapter=adapter, old_context=old_context, old_page=old_page,
                old_session=old_session, owner=threading.get_ident())
            if entry == 'api_owner':
                runtime.set_adapter(adapter)

        def inspect_after(result):
            flow, browser = owned['flow'], owned['browser']
            context, page = flow._context, flow._page
            assert browser.is_connected() and flow._browser is browser
            assert owned['old_context'].is_closed() is False
            assert owned['old_page'].url == OLD_HOME and owned['old_page'].is_closed() is False
            assert context is not owned['old_context'] and context in created and context in prepared
            assert page.context is context and str(page.url) == base + '/'
            assert flow.browser_session_id() != owned['old_session']
            assert flow.browser_session_id() == result['browser_session_id']
            assert context._impl_obj._options['serviceWorkers'] == 'block'
            assert context._impl_obj._options['acceptDownloads'] == 'deny'
            assert require_native_video_transport(page) is prepared[context]
            binding = bind_native_video_transport(page)
            try:
                assert binding.require_live() is binding
            finally:
                binding.close()
            assert flow._promote_dxm_page_from_connected_browser() is page
            assert flow._ensure_page_with_cookies() is page
            assert flow._persist_visible_browser_cookies() is None
            assert flow._context is context and cookie_calls == []
            assert [event for event, _ in calls] == ['actual_prepare', 'new_page_after_prepare']
            assert {owner for _, owner in calls} == {owned['owner']} == {threading.get_ident()}

        def close_owned():
            if owned.get('browser') is not None:
                owned['browser'].close()
            if owned.get('playwright') is not None:
                owned['playwright'].stop()

        if entry == 'adapter':
            try:
                setup()
                result = owned['adapter'].open_managed_manual_login()
                inspect_after(result)
            finally:
                close_owned()
        else:
            runtime = BrowserAgentRuntime()
            try:
                runtime.run_session_operation(setup)
                monkeypatch.setattr(main, 'browser_agent_runtime', runtime)
                monkeypatch.setattr(main, 'workflow_adapter', owned['adapter'])
                monkeypatch.setattr(main.agent_console_service, 'status', lambda: {})
                monkeypatch.setattr(main.repo, 'get_active_task_execution', lambda: None)
                monkeypatch.setattr(main.repo, 'get_active_edit_batch_execution', lambda: None)
                response = TestClient(main.app).post('/api/dxm/workflow/manual-login')
                assert response.status_code == 200, response.text
                result = response.json()
                runtime.run_session_operation(inspect_after, result)
                assert owned['owner'] == runtime._owner_thread_id != threading.get_ident()
                assert runtime.status()['sessionOperationActive'] is False
            finally:
                try:
                    runtime.run_session_operation(close_owned)
                finally:
                    runtime.set_adapter(None)
                    runtime.shutdown()
        assert result['stage'] == 'manual_login_required'
        assert result['logged_in'] is result['reader_ready'] is result['executionAllowed'] is False
        assert cookie_calls == []
        assert all('dianxiaomi' not in path for _, path, _ in hits)
