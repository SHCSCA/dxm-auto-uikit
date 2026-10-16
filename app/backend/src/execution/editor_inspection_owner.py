"""公开只读检查的局部页面所有者；不替换生产页面、命令或视频来源。"""

import threading

from src.execution.native_video_lifetime import NativeVideoLifetime
from src.execution.native_video_transport import bind_native_video_transport
from src.services.structured_logging import get_logger, log_event, log_exception


class EditorInspectionOwner:
    def __init__(self, flow, page, url, *, video=False):
        self.flow, self.page, self.url = flow, page, url
        self.context, self.browser, self.primary = flow._context, flow._browser, flow._page
        self.primary_frame, self.primary_url = self.primary.main_frame, str(self.primary.url)
        self.thread, self.session = threading.get_ident(), flow.browser_session_id()
        self.frame, self.navigations = page.main_frame if page is not None else None, 0
        self.binding = self.lifetime = None
        self.closed = self.invalid = False
        self.listener = False
        self.primary_listeners = []
        self.video = video

    def require_owner(self):
        flow = self.flow
        if (self.closed or self.invalid or threading.get_ident() != self.thread
                or flow._browser_session_thread_id != self.thread or flow._context is not self.context
                or flow._browser is not self.browser or flow._page is not self.primary
                or self.primary.context is not self.context or self.primary.is_closed()
                or self.primary.main_frame is not self.primary_frame or str(self.primary.url) != self.primary_url
                or flow.browser_session_id() != self.session or not self.session
                or self.page is not None and (self.page.context is not self.context
                    or self.page.main_frame is not self.frame or self.page.is_closed())
                or flow._is_playwright_object_closed(self.context)
                or not flow._is_browser_connected(self.browser)):
            raise RuntimeError('EDITOR_INSPECTION_OWNER_DRIFT')
        pinned = getattr(flow, '_managed_manual_login', None)
        if pinned is not None:
            pinned.require_context(flow)

    def require_live(self):
        self.require_owner()
        self.binding.require_live()
        if self.navigations not in (0, 1) or str(self.page.url) not in ('about:blank', self.url):
            raise RuntimeError('EDITOR_INSPECTION_DOCUMENT_DRIFT')

    def require_document(self):
        self.require_live()
        if self.navigations != 1 or str(self.page.url) != self.url:
            raise RuntimeError('EDITOR_INSPECTION_DOCUMENT_UNBOUND')

    def rpc(self, method, *args, **kwargs):
        self.require_live()
        result = method(*args, **kwargs)
        self.require_live()
        return result

    def _navigated(self, frame):
        try:
            if frame is self.frame or frame is self.page.main_frame:
                self.navigations += 1
                if self.navigations != 1 or frame is not self.frame or str(frame.url) != self.url:
                    self.invalid = True
        except Exception as exc:
            self.invalid = True
            log_exception(get_logger('editor.inspection'), 'editor_inspection_navigation_failed', exc)

    def _primary_changed(self, *_args):
        self.invalid = True
        log_event(get_logger('editor.inspection'), 'editor_inspection_primary_changed', level='WARNING')
        if self.binding is not None:
            self.binding.transport.invalid = True

    def start(self):
        try:
            self.require_owner()
            for event in ('framenavigated', 'close', 'crash'):
                self.primary_listeners.append((event, self._primary_changed))
                self.primary.on(event, self._primary_changed)
                self.require_owner()
            if self.page is None:
                self.page = self.context.new_page()
                self.frame = self.page.main_frame
                self.require_owner()
            if str(self.page.url) != 'about:blank':
                raise RuntimeError('EDITOR_INSPECTION_NEW_DOCUMENT_REQUIRED')
            self.listener = True
            self.page.on('framenavigated', self._navigated)
            if self.video:
                self.lifetime = NativeVideoLifetime(self.page, page_url=self.url, session_id=self.session).start()
                self.binding = self.lifetime.transport_binding
            else:
                self.binding = bind_native_video_transport(self.page)
            self.require_live()
            return self
        except Exception as exc:
            log_exception(get_logger('editor.inspection'), 'editor_inspection_owner_start_failed', exc)
            self.invalid = True
            try:
                self.close()
            except Exception as cleanup_exc:
                log_exception(get_logger('editor.inspection'), 'editor_inspection_failed_start_cleanup_failed', cleanup_exc)
            raise

    def seal_profile(self):
        if self.lifetime is None:
            return None
        self.rpc(self.lifetime.profile.close)
        profile = self.rpc(self.lifetime.profile.snapshot)
        if 'NATIVE_VIDEO_STATIC_CLEANUP_FAILED' in profile['issues']:
            raise RuntimeError('EDITOR_INSPECTION_PROFILE_CLEANUP_FAILED')
        return profile

    def close(self):
        if self.closed:
            return
        failures = []
        for operation in ([self.lifetime.close] if self.lifetime else [self.binding.close] if self.binding else []):
            try:
                operation()
            except Exception as exc:
                failures.append(exc)
                log_exception(get_logger('editor.inspection'), 'editor_inspection_owner_cleanup_failed', exc)
        if self.lifetime is not None and self.lifetime.invalid:
            failures.append(RuntimeError('EDITOR_INSPECTION_LIFETIME_CLEANUP_UNPROVEN'))
        if self.listener:
            try:
                self.page.remove_listener('framenavigated', self._navigated)
            except Exception as exc:
                failures.append(exc)
                log_exception(get_logger('editor.inspection'), 'editor_inspection_navigation_cleanup_failed', exc)
            self.listener = False
        listeners, self.primary_listeners = self.primary_listeners, []
        for event, callback in listeners:
            try:
                self.primary.remove_listener(event, callback)
            except Exception as exc:
                failures.append(exc)
                log_exception(get_logger('editor.inspection'), 'editor_inspection_primary_cleanup_failed', exc)
        try:
            self.require_owner()
        except Exception as exc:
            failures.append(exc)
            log_exception(get_logger('editor.inspection'), 'editor_inspection_final_primary_unproven', exc)
        self.closed = True
        if failures:
            self.invalid = True
            if self.binding is not None:
                self.binding.transport.invalid = True
            raise RuntimeError('EDITOR_INSPECTION_OWNER_CLEANUP_FAILED') from failures[0]
