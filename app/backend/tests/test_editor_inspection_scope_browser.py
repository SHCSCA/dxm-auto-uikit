"""实际浏览器验证局部请求窗口；合成回复不作为站点来源或依赖证书。"""

import pytest
from playwright.sync_api import Error as PlaywrightError

from src.execution.editor_inspection_flow import _cleanup
from src.execution.editor_inspection_owner import EditorInspectionOwner
from src.execution.editor_inspection_scope import EditorInspectionScope
from tests.test_editor_inspection_browser import browser
from tests.support.editor_inspection_browser_case import URL, inspection_browser_case


def close_owned(owner, page):
    _cleanup(owner, page, failed=True)


@pytest.mark.parametrize('path,body,content_type', [
    ('/api/picToVideo/backMusicList.json', '{"extra":1}', 'application/json'),
    ('/api/picToVideo/getCountInfo.json', '{} ', 'application/json'),
    ('/api/midou/valueService/balanceView.json', 'types=17&extra=1', 'application/x-www-form-urlencoded'),
])
def test_native_reads_reject_extra_fields_or_nonexact_body(browser, tmp_path, monkeypatch, path, body, content_type):
    with inspection_browser_case(browser, tmp_path, monkeypatch) as case:
        page = case.context.new_page()
        owner = EditorInspectionOwner(case.flow, page, URL, video=True).start()
        scope = EditorInspectionScope(owner, case.guard)
        try:
            with pytest.raises(RuntimeError):
                with scope:
                    owner.rpc(page.goto, URL)
                    scope.open_video_window()
                    owner.rpc(page.evaluate, "p=>fetch(p.path,{method:'POST',headers:{'Content-Type':p.type},body:p.body}).catch(()=>null)",
                        {'path': path, 'body': body, 'type': content_type})
            assert not any(url.endswith(path) for _, url, _ in case.delivered)
            assert case.transport.invalid and case.transport.active is None and scope.listeners == []
        finally:
            close_owned(owner, page)
        assert case.transport.bindings == set()


@pytest.mark.parametrize('fault', ['repeat_navigation', 'foreign_navigation', 'popup', 'websocket'])
def test_repeated_navigation_foreign_page_and_websocket_fail_closed(browser, tmp_path, monkeypatch, fault):
    with inspection_browser_case(browser, tmp_path, monkeypatch) as case:
        page = case.context.new_page()
        owner = EditorInspectionOwner(case.flow, page, URL).start()
        scope = EditorInspectionScope(owner, case.guard)
        try:
            with pytest.raises((RuntimeError, PlaywrightError)):
                with scope:
                    owner.rpc(page.goto, URL)
                    if fault == 'repeat_navigation':
                        owner.rpc(page.reload)
                    elif fault == 'foreign_navigation':
                        owner.rpc(page.goto, URL + '&other=1')
                    elif fault == 'popup':
                        with page.expect_popup() as opened:
                            owner.rpc(page.evaluate, "window.open('/unknown-popup')")
                        opened.value.wait_for_load_state('domcontentloaded')
                    else:
                        owner.rpc(page.evaluate, "window.ws=new WebSocket('wss://www.dianxiaomi.com/unknown-ws')")
                        owner.rpc(page.wait_for_function, 'window.ws.readyState===3', timeout=3000)
            assert sum(url == URL for _, url, _ in case.delivered) == 1
            assert not any('unknown-popup' in url or 'unknown-ws' in url or '&other=1' in url for _, url, _ in case.delivered)
            assert case.transport.invalid and case.transport.active is None and scope.listeners == []
        finally:
            close_owned(owner, page)
        assert case.transport.bindings == set()


@pytest.mark.parametrize('fault', ['primary_reload', 'post_creation_drift', 'creation_failed'])
def test_primary_watch_precedes_new_page_rpc_and_failed_start_closes_owned_page(browser, tmp_path, monkeypatch, fault):
    with inspection_browser_case(browser, tmp_path, monkeypatch) as case:
        case.primary.goto('about:blank')
        original = case.context.new_page
        created = []

        def new_page():
            if fault == 'creation_failed':
                raise RuntimeError('synthetic new_page RPC failure')
            page = original()
            created.append(page)
            if fault == 'primary_reload':
                case.primary.reload()
            else:
                case.flow._browser_session_generation = 'changed-after-creation'
            return page

        monkeypatch.setattr(case.context, 'new_page', new_page)
        owner = EditorInspectionOwner(case.flow, None, URL, video=True)
        try:
            with pytest.raises(RuntimeError):
                owner.start()
        finally:
            close_owned(owner, owner.page)
        assert all(page.is_closed() for page in created)
        assert case.context.pages == [case.primary] and owner.primary_listeners == []
        assert case.transport.bindings == set() and case.transport.active is None


def test_cleanup_listener_failure_is_reported_without_masking_primary_error(browser, tmp_path, monkeypatch):
    with inspection_browser_case(browser, tmp_path, monkeypatch) as case:
        page = case.context.new_page()
        owner = EditorInspectionOwner(case.flow, page, URL).start()
        scope = EditorInspectionScope(owner, case.guard)
        original = page.remove_listener

        def failed(event, callback):
            original(event, callback)
            if event == 'download':
                raise RuntimeError('synthetic listener cleanup failure')

        monkeypatch.setattr(page, 'remove_listener', failed)
        try:
            with pytest.raises(RuntimeError, match='primary failure'):
                with scope:
                    owner.rpc(page.goto, URL)
                    raise RuntimeError('primary failure')
            assert case.transport.active is None and scope.listeners == [] and case.transport.invalid
        finally:
            close_owned(owner, page)
