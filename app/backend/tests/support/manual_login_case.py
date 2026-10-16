"""合成浏览器只验证 owner 与生存期；prepare 替身不充当原生政策证明。"""

from types import SimpleNamespace
import threading

from src.execution.dxm_login_flow import DxmLoginFlow


class NoCookieClient:
    def has_cookie_session(self):
        raise AssertionError('不能检查历史 Cookie')

    def load_cookies(self):
        raise AssertionError('不能恢复历史 Cookie')


class Page:
    def __init__(self, context, events, *, old=False):
        self.context, self.events, self.old = context, events, old
        self.url, self.closed = ('https://www.dianxiaomi.com/web/home' if old else 'about:blank'), False

    def is_closed(self):
        return self.closed

    def goto(self, url, **kwargs):
        assert not self.old
        self.events.append(('goto', threading.get_ident()))
        self.url = url

    def bring_to_front(self):
        assert not self.old
        self.events.append(('focus', threading.get_ident()))

    def evaluate(self, *_args):
        raise AssertionError('不能读取页面业务值')


class Context:
    def __init__(self, events, *, old=False):
        self.events, self.old, self.closed = events, old, False
        self.pages, self.listeners = [], {}
        if old:
            self.pages.append(Page(self, events, old=True))
        self.request = object()

    def is_closed(self):
        return self.closed

    def on(self, event, handler):
        self.listeners.setdefault(event, []).append(handler)

    def new_page(self):
        assert not self.old
        self.events.append(('new_page', threading.get_ident()))
        page = Page(self, self.events)
        self.pages.append(page)
        return page

    def close(self):
        assert not self.old
        self.closed = True
        self.events.append(('new_context_close', threading.get_ident()))
        for handler in self.listeners.get('close', []):
            handler()

    def cookies(self):
        raise AssertionError('不能导出 Cookie')

    def add_cookies(self, *_args):
        raise AssertionError('不能复制 Cookie')


class Browser:
    def __init__(self, events, old):
        self.events, self.contexts, self.connected = events, [old], True
        self.options = None

    def is_connected(self):
        return self.connected

    def on(self, *_args):
        pass

    def new_context(self, **kwargs):
        self.options = kwargs
        self.events.append(('new_context', threading.get_ident()))
        context = Context(self.events)
        self.contexts.append(context)
        return context

    def close(self):
        raise AssertionError('不能关闭既有 Chrome')


def make_case(monkeypatch, tmp_path, *, cold=False):
    events = []
    old = Context(events, old=True)
    browser = Browser(events, old)
    flow = DxmLoginFlow(NoCookieClient(), state_file=tmp_path / 'manual-state.json')
    flow._is_headless = lambda: False
    flow._remote_debugging_port, flow._external_browser_process = 8123, object()

    def prepare(context):
        assert context.pages == []
        events.append(('prepare_spy', threading.get_ident()))

    monkeypatch.setattr('src.execution.managed_browser_context.prepare_native_video_transport', prepare)

    def bootstrap():
        events.append(('bootstrap', threading.get_ident()))
        flow._browser, flow._context, flow._page = browser, old, old.pages[0]
        flow._browser_session_thread_id = threading.get_ident()
        flow._bind_browser_context_generation(old)
        return flow._page

    if cold:
        flow._ensure_page = bootstrap
    else:
        bootstrap()
        events.clear()
    return SimpleNamespace(flow=flow, events=events, old=old, browser=browser)
