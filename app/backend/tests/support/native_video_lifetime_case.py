"""生命周期替身只验证接线；来源规格由 spy 生成，不证明现场加载过真实资源。"""

from copy import deepcopy
from types import SimpleNamespace

from src.execution import native_video_lifetime as lifetime_module
from tests.support.native_video_observation_case import make_observation


URL = 'https://www.dianxiaomi.com/web/smt/edit?id=10001'


def profile_snapshot():
    return make_observation(payload={'payload_hash': 'A' * 64, 'product_id': '10001'},
        target_identity={}, context={'browser_session_id': 'session-1'}, shop_id='91',
        evidence_ref={'path': 'fixture.png', 'sha256': 'B' * 64, 'size': 1})['source_profile']


class ProfileSpy:
    def __init__(self, page, *, expected_page_url, expect_navigation):
        self.page, self.expected_url, self.expect_navigation = page, expected_page_url, expect_navigation
        self.started = self.closed = False
        self.value = profile_snapshot()
        self.start_error = self.close_error = None

    def start(self):
        self.started = True
        if self.start_error:
            raise self.start_error
        return self

    def close(self):
        self.closed = True
        if self.close_error:
            raise self.close_error

    def snapshot(self):
        return deepcopy(self.value)


def install_profile_spy(monkeypatch):
    monkeypatch.setattr(lifetime_module, 'PassiveNativeVideoScriptCapture', ProfileSpy)
    # 生命周期用例显式隔离传输；真实浏览器传输证明由独立套件负责。
    monkeypatch.setattr(lifetime_module, 'bind_native_video_transport', SyntheticBindingSpy)


class SyntheticContext:
    def __init__(self):
        self.routes, self.events = [], []
        self.cleanup_error = None

    def route(self, pattern, handler):
        self.events.append('route_start')
        self.routes.append((pattern, handler))

    def unroute(self, pattern, handler):
        self.events.append('route_close')
        self.routes.remove((pattern, handler))
        if self.cleanup_error:
            raise self.cleanup_error


class SyntheticTransportSpy:
    """仅模拟 scope 登记与回收，不提供浏览器配置、网络或传输可信证明。"""
    def __init__(self, page):
        self.page, self.context = page, page.context
        self.invalid, self.active, self.bindings = False, None, set()
        self.handler = self.reject = None

    def _policy(self):
        """刻意空验证；这个 spy 只隔离接线，不声明任何传输可信能力。"""

    def activate(self, page, reject, handler):
        assert page is self.page and page.context is self.context and self.active is None and page in self.bindings
        self.handler, self.reject = handler, reject
        self.context.route('**/*', handler)
        self.active = (page, reject, handler)
        return self.active

    def deactivate(self, page):
        assert page is self.page and self.active is not None and self.active[0] is page
        try:
            self.context.unroute('**/*', self.handler)
        finally:
            self.active = None
            self.handler = self.reject = None


class SyntheticBindingSpy:
    """只复现同页面绑定生存期，不认证真实 context 配置或网络策略。"""
    def __init__(self, page):
        self.page, self.context, self.closed = page, page.context, False
        self.transport = getattr(self.context, '_synthetic_transport', None)
        if self.transport is not None:
            self.transport.bindings.add(page)

    def require_live(self):
        if self.closed or self.page.context is not self.context or self.transport is not None and self.transport.invalid:
            raise RuntimeError('SYNTHETIC_TRANSPORT_BINDING_NOT_LIVE')
        return self

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.transport is not None and self.transport.active and self.transport.reject is not None:
            self.transport.reject('TRANSPORT_OWNER_CLOSED_DURING_SCOPE')
        if self.transport is not None:
            self.transport.bindings.discard(self.page)


def install_transport_spy(monkeypatch, page):
    from src.execution import native_video_observation_guard as guard_module
    transport = SyntheticTransportSpy(page)
    page.context._synthetic_transport = transport

    def require_transport(actual_page):
        assert actual_page is page
        return transport

    monkeypatch.setattr(guard_module, 'require_native_video_transport', require_transport)
    return transport


class FakePage:
    def __init__(self):
        self.url, self.handlers, self.events = 'about:blank', {}, []
        self.main_frame = SimpleNamespace(url=self.url, page=self)
        self.context = SyntheticContext()
        # 旧断言只观察这个测试别名，实际 scope 路由登记在合成 context。
        self.routes = self.context.routes
        self.on_error = self.cleanup_error = None
        self.value = {'schema': 'dxm.native_video_document_lifetime.v1', 'document_time_origin': 1000.0,
            'url': URL, 'reveal_count': 0, 'entry_click_count': 0, 'visible_count': 0, 'closed_count': 0,
            'duplicate_modal_seen': False, 'unexpected_interactions': []}

    def add_init_script(self, script):
        self.events.append(('init_script', script))

    def on(self, event, handler):
        self.handlers.setdefault(event, []).append(handler)
        self.events.append(('on', event))
        if self.on_error:
            raise self.on_error

    def remove_listener(self, event, handler):
        self.events.append(('remove', event))
        if self.cleanup_error:
            raise self.cleanup_error
        if handler in self.handlers.get(event, []):
            self.handlers[event].remove(handler)

    def navigate(self, url=URL):
        self.events.append(('goto', url))
        self.url = self.main_frame.url = url
        for handler in list(self.handlers.get('framenavigated', [])):
            handler(self.main_frame)

    def evaluate(self, _script):
        return deepcopy(self.value)


def started_owner(monkeypatch):
    install_profile_spy(monkeypatch)
    page = FakePage()
    owner = lifetime_module.NativeVideoLifetime(page, page_url=URL, session_id='session-1').start()
    page.navigate()
    return page, owner
