"""合成对象只验证传输生命周期，不把伪造 options 视为浏览器政策证明。"""

from types import SimpleNamespace
import asyncio

import pytest

from src.execution.native_video_transport import (prepare_native_video_transport,
    bind_native_video_transport, require_native_video_transport)


class SyntheticContext:
    def __init__(self, options=None):
        self._impl_obj = SimpleNamespace(_options=options or {'serviceWorkers': 'block', 'acceptDownloads': 'deny'},
            _routes=[], _web_socket_routes=[])
        self.pages, self.service_workers, self.ws_handlers, self.http_handlers = [], [], [], []
        self.listeners = {}

    def on(self, event, handler):
        self.listeners[event] = handler

    def route_web_socket(self, pattern, handler):
        self.ws_handlers.append(handler)
        self._impl_obj._web_socket_routes.insert(0, object())

    def route(self, pattern, handler):
        self.http_handlers.append(handler)
        self._impl_obj._routes.insert(0, object())


class SyntheticPage:
    def __init__(self, context):
        self.context = context
        self._impl_obj = SimpleNamespace(_routes=[])
        context.pages.append(self)


class SyntheticSocket:
    def __init__(self):
        self.connections, self.closes = 0, 0
        self._impl_obj = SimpleNamespace(close=self.async_close)

    def connect_to_server(self):
        self.connections += 1

    def close(self, **kwargs):
        self.closes += 1

    async def async_close(self, **kwargs):
        self.closes += 1


@pytest.mark.parametrize('options', [{}, {'serviceWorkers': 'allow', 'acceptDownloads': 'deny'},
    {'serviceWorkers': 'block', 'acceptDownloads': 'accept'}, {'serviceWorkers': 'block'}])
def test_missing_or_allow_policy_refuses_before_install_and_cannot_be_repaired_with_a_map(options):
    context = SyntheticContext()
    context._impl_obj._options = options
    with pytest.raises(RuntimeError, match='POLICY_UNPROVEN'):
        prepare_native_video_transport(context)
    assert not context.ws_handlers and not context.http_handlers
    context._impl_obj._options = {'serviceWorkers': 'block', 'acceptDownloads': 'deny'}
    with pytest.raises(RuntimeError, match='POLICY_UNPROVEN'):
        prepare_native_video_transport(context)


def test_initial_pages_or_existing_workers_refuse_without_installing():
    context = SyntheticContext()
    SyntheticPage(context)
    with pytest.raises(RuntimeError, match='INSTALLED_TOO_LATE'):
        prepare_native_video_transport(context)
    assert not context.ws_handlers
    context = SyntheticContext()
    context.service_workers.append(object())
    with pytest.raises(RuntimeError, match='POLICY_UNPROVEN'):
        prepare_native_video_transport(context)


def test_singleton_scopes_close_new_sockets_without_connect_and_release_ownership(monkeypatch):
    monkeypatch.setattr('src.execution.native_video_transport.AsyncWebSocketRoute', lambda impl: impl)
    context = SyntheticContext()
    transport = prepare_native_video_transport(context)
    page = SyntheticPage(context)
    binding = bind_native_video_transport(page)
    assert prepare_native_video_transport(context) is transport
    assert len(context.ws_handlers) == len(context.http_handlers) == 1
    for _ in range(2):
        issues = []
        transport.activate(page, issues.append, lambda route: None)
        socket = SyntheticSocket()
        asyncio.run(context.ws_handlers[0](socket))
        assert (socket.connections, socket.closes) == (0, 1)
        assert issues == ['WEBSOCKET_BLOCKED']
        transport.deactivate(page)
        assert binding.require_live() is binding
    binding.close()
    binding.close()
    with pytest.raises(RuntimeError, match='NOT_LIVE'):
        binding.require_live()


def test_inactive_socket_connects_without_message_hooks_but_prevents_future_observation():
    context = SyntheticContext()
    transport = prepare_native_video_transport(context)
    page = SyntheticPage(context)
    binding = bind_native_video_transport(page)
    socket = SyntheticSocket()
    asyncio.run(context.ws_handlers[0](socket))
    assert (socket.connections, socket.closes) == (1, 0)
    with pytest.raises(RuntimeError, match='PRIOR_WEBSOCKET'):
        transport.activate(page, lambda reason: None, lambda route: None)
    with pytest.raises(RuntimeError, match='NOT_LIVE'):
        binding.require_live()


def test_new_worker_poisoning_cannot_be_cleared_by_emptying_the_worker_list():
    context = SyntheticContext()
    transport = prepare_native_video_transport(context)
    page = SyntheticPage(context)
    binding = bind_native_video_transport(page)
    issues = []
    transport.activate(page, issues.append, lambda route: None)
    context.listeners['serviceworker'](object())
    assert issues == ['SERVICE_WORKER_UNEXPECTED']
    transport.deactivate(page)
    assert transport.active is None
    with pytest.raises(RuntimeError, match='POLICY_UNPROVEN'):
        binding.require_live()


def test_missing_preparation_and_page_route_precedence_are_not_assumed_safe():
    context = SyntheticContext()
    page = SyntheticPage(context)
    with pytest.raises(RuntimeError, match='NOT_PREPARED'):
        require_native_video_transport(page)
    context = SyntheticContext()
    transport = prepare_native_video_transport(context)
    page = SyntheticPage(context)
    bind_native_video_transport(page)
    page._impl_obj._routes.append(object())
    with pytest.raises(RuntimeError, match='PRECEDENCE_UNPROVEN'):
        transport.activate(page, lambda reason: None, lambda route: None)


@pytest.mark.parametrize('routes', ['_routes', '_web_socket_routes'])
def test_later_context_route_precedence_is_refused_and_close_releases_registry(routes):
    context = SyntheticContext()
    transport = prepare_native_video_transport(context)
    page = SyntheticPage(context)
    binding = bind_native_video_transport(page)
    getattr(context._impl_obj, routes).insert(0, object())
    with pytest.raises(RuntimeError, match='PRECEDENCE_UNPROVEN'):
        binding.require_live()
    context.listeners['close']()
    assert not transport.bindings and transport.active is None and transport.invalid
    with pytest.raises(RuntimeError, match='NOT_PREPARED'):
        require_native_video_transport(page)
