"""在空的原生上下文建立唯一传输所有权；不追认安装前的连接或工作线程。"""

from weakref import WeakKeyDictionary

from playwright.async_api import WebSocketRoute as AsyncWebSocketRoute

from src.services.structured_logging import get_logger, log_exception


_TRANSPORTS = WeakKeyDictionary()


class NativeVideoTransport:
    def __init__(self, context):
        self.context = context
        self.bindings = set()
        self.active = None
        self.connected_before_scope = False
        self.invalid = False
        self.installed = False
        self.ws_handler = self._websocket
        self.http_handler = self._http
        self.worker_handler = self._worker
        self.http_route = self.ws_route = None

    def _options(self):
        return getattr(getattr(self.context, '_impl_obj', None), '_options', {})

    def _policy(self):
        current = self._options()
        if (current.get('serviceWorkers') != 'block' or current.get('acceptDownloads') != 'deny'
                or self.context.service_workers or self.invalid):
            raise RuntimeError('VIDEO_OBSERVATION_TRANSPORT_POLICY_UNPROVEN')
        if self.installed:
            impl = self.context._impl_obj
            if (impl._routes != [self.http_route] or impl._web_socket_routes != [self.ws_route]):
                self.invalid = True
                raise RuntimeError('VIDEO_OBSERVATION_CONTEXT_ROUTE_PRECEDENCE_UNPROVEN')

    def install(self):
        self._policy()
        if self.context.pages:
            raise RuntimeError('VIDEO_OBSERVATION_TRANSPORT_INSTALLED_TOO_LATE')
        if self.context._impl_obj._routes or self.context._impl_obj._web_socket_routes:
            raise RuntimeError('VIDEO_OBSERVATION_CONTEXT_ROUTE_PRECEDENCE_UNPROVEN')
        try:
            self.context.on('serviceworker', self.worker_handler)
            self.context.route_web_socket('**/*', self.ws_handler)
            self.context.route('**/*', self.http_handler)
            self.http_route = self.context._impl_obj._routes[0]
            self.ws_route = self.context._impl_obj._web_socket_routes[0]
            self.installed = True
        except Exception as exc:
            self.invalid = True
            log_exception(get_logger('native_video.transport'), 'native_video_transport_install_failed', exc)
            raise
        return self

    def _closed(self, *_args):
        self.invalid = True
        if self.active is not None:
            self.active[1]('TRANSPORT_CONTEXT_CLOSED')
        self.active = None
        self.bindings.clear()
        _TRANSPORTS.pop(self.context, None)

    def _http(self, route):
        try:
            if self.invalid:
                route.abort()
            elif self.active is not None:
                self.active[2](route)
            else:
                route.continue_()
        except Exception as exc:
            self.invalid = True
            if self.active is not None:
                self.active[1]('HTTP_TRANSPORT_FAILED')
            log_exception(get_logger('native_video.transport'), 'native_video_http_transport_failed', exc)
            try:
                route.abort()
            except Exception as cleanup_exc:
                log_exception(get_logger('native_video.transport'), 'native_video_http_abort_failed', cleanup_exc)

    def _worker(self, *_args):
        self.invalid = True
        if self.active is not None:
            self.active[1]('SERVICE_WORKER_UNEXPECTED')

    async def _websocket(self, route):
        try:
            if self.active is not None or self.invalid:
                if self.active is not None:
                    self.active[1]('WEBSOCKET_BLOCKED')
                # WS 回调位于 dispatcher 协程；同原对象的异步包装避免同步 RPC 自等待。
                await AsyncWebSocketRoute(route._impl_obj).close(code=1008, reason='Observation window')
            else:
                # 不读写消息、不更改关闭转发；历史连接使后续观察保守拒绝。
                self.connected_before_scope = True
                route.connect_to_server()
        except Exception as exc:
            self.invalid = True
            if self.active is not None:
                self.active[1]('WEBSOCKET_GUARD_FAILED')
            log_exception(get_logger('native_video.transport'), 'native_video_websocket_guard_failed', exc)
            try:
                await AsyncWebSocketRoute(route._impl_obj).close(code=1011, reason='Transport unavailable')
            except Exception as cleanup_exc:
                log_exception(get_logger('native_video.transport'), 'native_video_websocket_close_failed', cleanup_exc)

    def activate(self, page, reject, handler):
        self._policy()
        if page not in self.bindings or page.context is not self.context or self.active is not None:
            raise RuntimeError('VIDEO_OBSERVATION_TRANSPORT_OWNER_UNBOUND')
        if self.connected_before_scope:
            raise RuntimeError('VIDEO_OBSERVATION_PRIOR_WEBSOCKET_UNPROVEN')
        if any(getattr(getattr(item, '_impl_obj', None), '_routes', []) for item in self.context.pages):
            raise RuntimeError('VIDEO_OBSERVATION_PAGE_ROUTE_PRECEDENCE_UNPROVEN')
        self.active = (page, reject, handler)
        return self.active

    def deactivate(self, page):
        if self.active is None or self.active[0] is not page:
            raise RuntimeError('VIDEO_OBSERVATION_TRANSPORT_SCOPE_DRIFT')
        try:
            if not self.invalid:
                self._policy()
        except Exception:
            self.invalid = True
            raise
        finally:
            self.active = None


class NativeVideoTransportBinding:
    def __init__(self, transport, page):
        self.transport, self.page, self.closed = transport, page, False
        if page in transport.bindings:
            raise RuntimeError('VIDEO_OBSERVATION_TRANSPORT_DUPLICATE_BINDING')
        transport.bindings.add(page)

    def require_live(self):
        self.transport._policy()
        if (self.closed or self.page not in self.transport.bindings
                or self.page.context is not self.transport.context or not self.transport.installed
                or self.transport.connected_before_scope
                or (self.transport.active is not None and self.transport.active[0] is not self.page)):
            raise RuntimeError('VIDEO_OBSERVATION_TRANSPORT_BINDING_NOT_LIVE')
        return self

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.transport.active is not None and self.transport.active[0] is self.page:
            self.transport.active[1]('TRANSPORT_OWNER_CLOSED_DURING_SCOPE')
        self.transport.bindings.discard(self.page)


def prepare_native_video_transport(context):
    """只在 new_context 后、new_page 前安装；不卸载不可撤销的 WebSocket 路由。"""
    try:
        if context in _TRANSPORTS:
            result = _TRANSPORTS[context]
            result._policy()
            if not result.installed:
                raise RuntimeError('VIDEO_OBSERVATION_TRANSPORT_NOT_PREPARED')
            return result
        transport = NativeVideoTransport(context)
        # 安装中途失败也保留失效对象，禁止叠加不可撤销的路由后重试。
        _TRANSPORTS[context] = transport
        context.on('close', transport._closed)
        return transport.install()
    except Exception as exc:
        if context in _TRANSPORTS:
            _TRANSPORTS[context].invalid = True
        log_exception(get_logger('native_video.transport'), 'native_video_transport_prepare_refused', exc)
        raise


def bind_native_video_transport(page):
    transport = require_native_video_transport(page)
    return NativeVideoTransportBinding(transport, page)


def require_native_video_transport(page):
    transport = _TRANSPORTS.get(page.context)
    if transport is None or not transport.installed:
        raise RuntimeError('VIDEO_OBSERVATION_TRANSPORT_NOT_PREPARED')
    transport._policy()
    return transport
