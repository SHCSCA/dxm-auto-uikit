"""仅记录手动登录导航清理前的本地事实；不校验、恢复或授权浏览器。"""

import logging
import re

from src.execution.native_video_transport import _TRANSPORTS
from src.services.structured_logging import StructuredLogFormatter, get_logger, log_event


_LOGGER = get_logger('manual_login.navigation')
_FALLBACK = logging.Logger('dxm.manual_login.navigation.fallback')
_FALLBACK.propagate = False
_HANDLER = logging.StreamHandler()
_HANDLER.setFormatter(StructuredLogFormatter())
_HANDLER.handleError = lambda _record: None
_FALLBACK.addHandler(_HANDLER)
_ERROR_CODE = re.compile(r'net::ERR_[A-Z][A-Z0-9_]{0,63}\Z')


def _emit(event, **fields):
    try:
        log_event(_LOGGER, event, level='WARNING', **fields)
    except Exception as exc:
        try:
            _FALLBACK.error('manual_login_navigation_log_failed',
                extra={'event_fields': {'exception_type': _exception_type(exc)}})
        except Exception:
            pass  # 日志出口失效也不能遮蔽原导航错误或阻止原清理。


def _exception_type(exc):
    name = type(exc).__name__
    return name if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', name) else 'Exception'


class ManualLoginNavigation:
    def __init__(self, owner):
        self.owner = owner
        self.browser = self.context = self.page = None
        self._listeners = []
        self._counts = dict.fromkeys(('listener_registration_success_count', 'listener_removal_success_count',
            'read_error_count', 'registration_error_count', 'callback_error_count', 'removal_error_count',
            'requestfailed_count', 'navigation_failure_count', 'main_navigation_failure_count',
            'serviceworker_count', 'context_close_count', 'page_close_count', 'browser_disconnected_count',
            'unclassified_failure_count'), 0)
        self._closed, self._failure_snapshot = False, None
        self._codes = {'request_failure_code': None, 'navigation_failure_code': None,
            'main_navigation_failure_code': None}

    def _increment(self, name):
        self._counts[name] = self._counts.get(name, 0) + 1

    def _error(self, phase, exc):
        self._increment(phase + '_error_count')
        _emit('manual_login_navigation_diagnostic_failed', **{phase + '_failed': True},
            exception_type=_exception_type(exc))

    def _read(self, reader):
        try:
            return reader()
        except Exception as exc:
            self._error('read', exc)
            return None

    def _listen(self, target, event, counter):
        def callback(*args):
            if self._closed:
                return
            try:
                self._increment(counter)
                if event == 'requestfailed':
                    self._request_failed(args[0])
            except Exception as exc:
                self._error('callback', exc)
        # on 可能先登记后抛错，因此必须先记住本次精确 callback。
        self._listeners.append((target, event, callback))
        try:
            target.on(event, callback)
            self._increment('listener_registration_success_count')
        except Exception as exc:
            self._error('registration', exc)

    def bind_browser(self, browser):
        self.browser = browser
        self._listen(browser, 'disconnected', 'browser_disconnected_count')

    def bind_context(self, context):
        self.context = context
        for event, counter in [('requestfailed', 'requestfailed_count'), ('serviceworker', 'serviceworker_count'),
            ('close', 'context_close_count')]:
            self._listen(context, event, counter)

    def bind_page(self, page):
        self.page = page
        self._listen(page, 'close', 'page_close_count')

    def _request_failed(self, request):
        failure = self._read(lambda: request.failure)
        code = failure if type(failure) is str and _ERROR_CODE.fullmatch(failure) else None
        if code is None:
            self._increment('unclassified_failure_count')
        elif self._codes['request_failure_code'] is None:
            self._codes['request_failure_code'] = code
        navigation = self._read(lambda: request.is_navigation_request())
        if navigation is True:
            self._increment('navigation_failure_count')
            if code and self._codes['navigation_failure_code'] is None:
                self._codes['navigation_failure_code'] = code
            main_frame = self._read(lambda: self.page is not None and request.frame is self.page.main_frame)
            if main_frame is True:
                self._increment('main_navigation_failure_count')
                if code and self._codes['main_navigation_failure_code'] is None:
                    self._codes['main_navigation_failure_code'] = code

    def _boolean(self, reader):
        def checked():
            value = reader()
            if type(value) is not bool:
                raise TypeError()
            return value
        return self._read(checked)

    def _route_count(self, target, name):
        def checked():
            routes = getattr(target._impl_obj, name)
            if type(routes) is not list:
                raise TypeError()
            return len(routes)
        return self._read(checked)

    def _snapshot(self):
        lookup = self._read(lambda: (_TRANSPORTS.get(self.context),)) if self.context is not None else (None,)
        transport = lookup[0] if lookup is not None else None
        context_closed = self._boolean(lambda: self.context.is_closed()) if self.context is not None else None
        facts = {'snapshot_complete': True, 'before_cleanup': True, 'tracking_active': not self._closed,
            'context_present': self.context is not None, 'browser_present': self.browser is not None,
            'context_open': not context_closed if context_closed is not None else None,
            'browser_connected': self._boolean(lambda: self.browser.is_connected()) if self.browser is not None else None,
            'transport_present': transport is not None if lookup is not None else None,
            'transport_installed': self._boolean(lambda: transport.installed) if transport is not None else None,
            'transport_invalid': self._boolean(lambda: transport.invalid) if transport is not None else None,
            'transport_active': self._read(lambda: transport.active is not None) if transport is not None else None,
            'serviceworker_present_count': self._read(lambda: len(self.context.service_workers)) if self.context is not None else None,
            'context_http_route_count': self._route_count(self.context, '_routes') if self.context is not None else None,
            'context_ws_route_count': self._route_count(self.context, '_web_socket_routes') if self.context is not None else None,
            'page_http_route_count': self._route_count(self.page, '_routes') if self.page is not None else None,
            'page_ws_route_count': self._route_count(self.page, '_web_socket_routes') if self.page is not None else None,
            'listener_attempt_count': len(self._listeners), 'executionAllowed': False,
            'capabilityCertified': False, 'inputFreezeAllowed': False, **self._codes}
        facts.update(self._counts)
        return facts

    def snapshot_failure(self):
        if self._failure_snapshot is None:
            try:
                facts = self._snapshot()
            except Exception as exc:
                self._error('snapshot', exc)
                facts = {'snapshot_complete': False, 'before_cleanup': True, 'executionAllowed': False,
                    'capabilityCertified': False, 'inputFreezeAllowed': False, **self._counts}
            self._failure_snapshot = dict(facts)
            _emit('managed_manual_login_navigation_failure_before_cleanup', **facts)
        return dict(self._failure_snapshot)

    def close(self):
        if self._closed:
            return
        self._closed = True
        for target, event, callback in self._listeners:
            try:
                target.remove_listener(event, callback)
                self._increment('listener_removal_success_count')
            except Exception as exc:
                self._error('removal', exc)
        self._listeners.clear()
