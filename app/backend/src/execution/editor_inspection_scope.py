"""复用唯一 context 传输的检查窗口；导航、弹窗读取和业务写入权限分离。"""

import hashlib
from urllib.parse import urlsplit

from src.execution.native_video_http_transport import NativeVideoSafeRoute
from src.execution.native_video_read_contract import NATIVE_VIDEO_READ_BODIES, is_native_video_read
from src.services.structured_logging import get_logger, log_event, log_exception


class EditorInspectionScope:
    def __init__(self, owner, guard):
        self.owner, self.page, self.guard = owner, owner.page, guard
        self.transport = owner.binding.transport
        self.token, self.listeners = None, []
        self.unexpected, self.native_reads = [], []
        self.navigation_requested = 0
        self.video_window = False

    def reject(self, reason):
        if reason not in self.unexpected:
            self.unexpected.append(reason)
            log_event(get_logger('editor.inspection'), 'editor_inspection_effect_rejected', level='WARNING', reason_code=reason)
        self.transport.invalid = True

    def require_live(self):
        self.owner.require_live()
        if self.transport.active is not self.token or self.token is None or self.unexpected:
            raise RuntimeError('EDITOR_INSPECTION_SCOPE_DRIFT')

    def open_video_window(self):
        self.owner.require_document()
        self.require_live()
        if not self.owner.video or self.video_window:
            raise RuntimeError('EDITOR_INSPECTION_VIDEO_WINDOW_INVALID')
        initial = self.owner.rpc(self.owner.lifetime.read)
        if any(initial[key] != 0 for key in ('reveal_count', 'entry_click_count', 'visible_count')):
            raise RuntimeError('EDITOR_INSPECTION_VIDEO_NOT_INITIAL')
        self.video_window = True
        return initial

    def _route(self, route):
        safe = NativeVideoSafeRoute(route, self.reject, self.require_live)
        try:
            self.require_live()
            request = route.request
            if (request.frame is not self.owner.frame or request.frame.page is not self.page
                    or request.redirected_from is not None):
                raise RuntimeError('EDITOR_INSPECTION_FOREIGN_OR_REDIRECT_REQUEST')
            if request.is_navigation_request():
                if (request.method != 'GET' or request.resource_type != 'document'
                        or request.url != self.owner.url or self.navigation_requested != 0
                        or self.owner.navigations != 0):
                    raise RuntimeError('EDITOR_INSPECTION_NAVIGATION_FORBIDDEN')
                self.navigation_requested += 1
                safe.continue_()
                return
            path = urlsplit(request.url).path
            if path in NATIVE_VIDEO_READ_BODIES:
                if not self.video_window or not is_native_video_read(request, self.page):
                    raise RuntimeError('EDITOR_INSPECTION_NATIVE_READ_FORBIDDEN')
                safe.continue_()
                self.native_reads.append({'method': request.method, 'path': path,
                    'request_sha256': hashlib.sha256(request.post_data.encode()).hexdigest().upper()})
                return
            count = len(self.guard.blocked_requests)
            self.guard._route(safe)
            if len(self.guard.blocked_requests) != count:
                self.reject('EDITOR_INSPECTION_UNAPPROVED_REQUEST')
        except Exception as exc:
            self.reject('EDITOR_INSPECTION_REQUEST_REJECTED')
            log_exception(get_logger('editor.inspection'), 'editor_inspection_request_rejected', exc)
            safe.abort()

    def _dialog(self, dialog):
        self.reject('dialog')
        try:
            dialog.dismiss()
        except Exception as exc:
            log_exception(get_logger('editor.inspection'), 'editor_inspection_dialog_dismiss_failed', exc)

    def __enter__(self):
        try:
            self.owner.require_live()
            self.token = self.transport.activate(self.page, self.reject, self._route)
            callbacks = [('response', self.guard._on_response), ('requestfailed', self.guard._on_request_failed),
                ('dialog', self._dialog), *[(event, lambda *args, event=event: self.reject(event))
                    for event in ('popup', 'download', 'websocket', 'pageerror', 'close', 'crash')]]
            for event, callback in callbacks:
                self.listeners.append((event, callback))
                self.owner.rpc(self.page.on, event, callback)
            return self
        except Exception as exc:
            self.reject('EDITOR_INSPECTION_SCOPE_START_FAILED')
            log_exception(get_logger('editor.inspection'), 'editor_inspection_scope_start_failed', exc)
            try:
                self._cleanup()
            except Exception as cleanup_exc:
                log_exception(get_logger('editor.inspection'), 'editor_inspection_failed_scope_cleanup_failed', cleanup_exc)
            raise

    def summary(self):
        summary = self.guard.summary()
        # 原生弹窗读取独立记账，不冒充全局 L2 批准项。
        summary.update(native_read_request_count=len(self.native_reads), native_read_facts=list(self.native_reads),
            initial_navigation_count=self.navigation_requested, unexpected_effects=list(self.unexpected))
        return summary

    def _cleanup(self):
        failures, listeners = [], self.listeners
        self.listeners = []
        for event, callback in listeners:
            try:
                self.page.remove_listener(event, callback)
            except Exception as exc:
                failures.append(exc)
                self.reject('EDITOR_INSPECTION_LISTENER_CLEANUP_FAILED')
                log_exception(get_logger('editor.inspection'), 'editor_inspection_listener_cleanup_failed', exc)
        if self.token is not None:
            try:
                self.owner.require_document()
            except Exception as exc:
                failures.append(exc)
                self.reject('EDITOR_INSPECTION_FINAL_OWNER_UNPROVEN')
                log_exception(get_logger('editor.inspection'), 'editor_inspection_final_owner_failed', exc)
            try:
                self.transport.deactivate(self.page)
            except Exception as exc:
                failures.append(exc)
                self.reject('EDITOR_INSPECTION_TRANSPORT_CLEANUP_FAILED')
                log_exception(get_logger('editor.inspection'), 'editor_inspection_transport_cleanup_failed', exc)
            self.token = None
        if failures:
            raise RuntimeError('EDITOR_INSPECTION_SCOPE_CLEANUP_FAILED') from failures[0]

    def __exit__(self, kind, error, traceback):
        failure = None
        if kind is not None:
            self.reject('EDITOR_INSPECTION_FAILED')
        try:
            if kind is None:
                self.require_live()
        except Exception as exc:
            failure = exc
            self.reject('EDITOR_INSPECTION_CLEANUP_UNPROVEN')
            log_exception(get_logger('editor.inspection'), 'editor_inspection_scope_cleanup_failed', exc)
        finally:
            try:
                self._cleanup()
            except Exception as exc:
                failure = failure or exc
                self.reject('EDITOR_INSPECTION_CLEANUP_UNPROVEN')
                log_exception(get_logger('editor.inspection'), 'editor_inspection_scope_cleanup_failed', exc)
        if kind is None and failure is not None:
            raise failure
        if kind is None and self.unexpected:
            raise RuntimeError('EDITOR_INSPECTION_UNEXPECTED_EFFECT')
        return False
