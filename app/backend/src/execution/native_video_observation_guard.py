"""视频输入观察窗口只允许已审只读请求；其它请求和页面副作用均停止采集。"""

import hashlib
from pathlib import Path
from urllib.parse import urlsplit

from src.execution.editor_readonly_inspection import make_editor_readonly_guard
from src.execution.native_video_read_contract import is_native_video_read, NATIVE_VIDEO_READ_BODIES
from src.execution.native_video_transport import require_native_video_transport
from src.execution.native_video_http_transport import NativeVideoSafeRoute
from src.services.structured_logging import get_logger, log_exception


class NativeVideoObservationGuard:
    def __init__(self, page):
        from src.execution.dxm_login_flow import DXM_E2_PLAN_READ_ALLOWLIST
        root = Path(__file__).resolve().parents[4]
        self.guard = make_editor_readonly_guard(root / 'tools/probes/l2_readonly_probe.py',
            root / 'config/l2_readonly_allowlist.json', DXM_E2_PLAN_READ_ALLOWLIST)
        self.page, self.read_apis = page, DXM_E2_PLAN_READ_ALLOWLIST
        self.requests, self.unexpected, self.listeners = [], [], []
        self.handler = self._route
        self.transport = None
        self.scope_active = False
        self.scope_token = None
        self.frame, self.page_url = page.main_frame, str(page.url)

    def _reject(self, reason):
        self.unexpected.append(reason)

    def _require_live(self):
        if (not self.scope_active or self.transport.invalid or self.transport.active is not self.scope_token
                or self.page not in self.transport.bindings or self.page.context is not self.transport.context
                or self.page.main_frame is not self.frame or str(self.page.url) != self.page_url):
            raise RuntimeError('VIDEO_OBSERVATION_TRANSPORT_SCOPE_DRIFT')
        self.transport._policy()

    def _route(self, route):
        safe = NativeVideoSafeRoute(route, self._reject, self._require_live)
        try:
            if not self.scope_active or self.transport.invalid:
                self._reject('INACTIVE_OR_INVALID_TRANSPORT')
                safe.abort()
                return
            request = route.request
            if (request.frame is not self.page.main_frame or request.frame.page is not self.page
                    or request.redirected_from is not None):
                self._reject('FOREIGN_PAGE_OR_REDIRECT_REQUEST')
                safe.abort()
                return
            endpoint = (request.method, request.url.split('?', 1)[0])
            native = is_native_video_read(request, self.page)
            if native:
                safe.continue_()
                self.requests.append({'method': request.method, 'path': urlsplit(request.url).path,
                    'request_sha256': hashlib.sha256(request.post_data.encode()).hexdigest().upper(), 'allowed': True})
                return
            if urlsplit(request.url).path in NATIVE_VIDEO_READ_BODIES:
                self.unexpected.append('NATIVE_VIDEO_READ_SHAPE_INVALID')
                safe.abort()
                return
            count = len(self.guard.blocked_requests)
            self.guard._route(safe)
            blocked = len(self.guard.blocked_requests) != count
            if blocked:
                self.unexpected.append('UNAPPROVED_REQUEST')
            if endpoint in self.read_apis:
                self.requests.append({'method': request.method, 'path': urlsplit(request.url).path,
                    'request_sha256': hashlib.sha256((request.post_data or '').encode()).hexdigest().upper(),
                    'allowed': not blocked})
        except Exception as exc:
            self.unexpected.append('REQUEST_GUARD_FAILED')
            log_exception(get_logger('native_video.observation'), 'native_video_read_guard_failed', exc)
            safe.abort()

    def _dialog(self, dialog):
        self._reject('dialog')
        try:
            dialog.dismiss()
        except Exception as exc:
            self._reject('DIALOG_DISMISS_FAILED')
            log_exception(get_logger('native_video.observation'), 'native_video_dialog_dismiss_failed', exc)

    def __enter__(self):
        try:
            self.transport = require_native_video_transport(self.page)
            self.scope_token = self.transport.activate(self.page, self._reject, self.handler)
            self.scope_active = True
            for event in ('popup', 'download', 'dialog', 'framenavigated', 'websocket', 'pageerror'):
                callback = self._dialog if event == 'dialog' else lambda *args, event=event: self.unexpected.append(event)
                self.listeners.append((event, callback))
                self.page.on(event, callback)
            return self
        except Exception as exc:
            log_exception(get_logger('native_video.observation'), 'native_video_read_guard_start_failed', exc)
            if self.transport is not None:
                self.transport.invalid = True
            self._cleanup()
            raise

    def facts(self):
        if self.unexpected:
            raise RuntimeError('VIDEO_INPUT_OBSERVATION_UNEXPECTED_EFFECT')
        self.transport._policy()
        return {'request_facts': list(self.requests), 'unexpected_effects': []}

    def __exit__(self, *args):
        if self.transport is not None and (args[0] is not None or self.unexpected):
            self.transport.invalid = True
        self._cleanup()
        self.facts()

    def _cleanup(self):
        failures = []
        operations = [('listener', event, callback) for event, callback in self.listeners]
        self.listeners.clear()
        for kind, event, callback in operations:
            try:
                self.page.remove_listener(event, callback)
            except Exception as exc:
                failures.append(exc)
                log_exception(get_logger('native_video.observation'), 'native_video_guard_cleanup_failed', exc, resource=kind)
        if self.scope_active:
            if self.unexpected:
                self.transport.invalid = True
            try:
                self.transport.deactivate(self.page)
            except Exception as exc:
                failures.append(exc)
                self._reject('TRANSPORT_SCOPE_CLEANUP_FAILED')
                log_exception(get_logger('native_video.observation'), 'native_video_scope_cleanup_failed', exc)
            finally:
                self.scope_active = False
        if failures:
            self.transport.invalid = True
            raise RuntimeError('VIDEO_INPUT_OBSERVATION_CLEANUP_FAILED') from failures[0]
