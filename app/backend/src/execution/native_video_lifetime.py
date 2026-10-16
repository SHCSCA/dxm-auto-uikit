"""持有同一受管页面的观察生命周期；对象丢失或文档改变后不允许重建原冻结身份。"""

import uuid
from urllib.parse import parse_qs, urlsplit

from src.execution.native_video_lifetime_script import NATIVE_VIDEO_LIFETIME_SCRIPT, NATIVE_VIDEO_LIFETIME_READ
from src.execution.native_video_script_capture import PassiveNativeVideoScriptCapture
from src.execution.native_video_transport import bind_native_video_transport
from src.services.structured_logging import get_logger, log_exception


class NativeVideoLifetime:
    def __init__(self, page, *, page_url, session_id):
        self.page, self.frame, self.page_url, self.session_id = page, page.main_frame, page_url, session_id
        self.owner_id, self.navigation_count = uuid.uuid4().hex, 0
        self.closed = self.invalid = False
        self.started = self.listener_added = False
        self.origin = None
        self.observation = None
        self.transport_binding = None
        self.profile = PassiveNativeVideoScriptCapture(page, expected_page_url=page_url, expect_navigation=True)

    def start(self):
        try:
            self.transport_binding = bind_native_video_transport(self.page)
            if not getattr(self.page, '_dxm_video_lifetime_script_installed', False):
                self.page.add_init_script(NATIVE_VIDEO_LIFETIME_SCRIPT)
                self.page._dxm_video_lifetime_script_installed = True
            self.listener_added = True
            self.page.on('framenavigated', self._navigated)
            self.profile.start()
            self.started = True
            return self
        except Exception as exc:
            log_exception(get_logger('native_video.lifetime'), 'native_video_lifetime_start_failed', exc)
            self.close()
            raise

    def _navigated(self, frame):
        try:
            if frame is self.frame or frame is self.page.main_frame:
                self.navigation_count += 1
                if self.navigation_count != 1 or frame is not self.frame or str(frame.url) != self.page_url:
                    self.invalid = True
        except Exception as exc:
            self.invalid = True
            log_exception(get_logger('native_video.lifetime'), 'native_video_navigation_observation_failed', exc)

    def _require_document(self):
        if (not self.started or self.closed or self.invalid or self.navigation_count != 1
                or self.page.main_frame is not self.frame or str(self.page.url) != self.page_url):
            raise RuntimeError('VIDEO_OWNER_DOCUMENT_DRIFT')
        self.transport_binding.require_live()

    def read(self):
        self._require_document()
        value = self.page.evaluate(NATIVE_VIDEO_LIFETIME_READ)
        self._require_document()
        if (not isinstance(value, dict) or value.get('schema') != 'dxm.native_video_document_lifetime.v1'
                or value.get('url') != self.page_url or value.get('duplicate_modal_seen') is not False
                or value.get('closed_count') != 0 or value.get('unexpected_interactions') != []):
            raise RuntimeError('VIDEO_OWNER_INTERACTION_OR_LIFETIME_UNPROVEN')
        origin = value.get('document_time_origin')
        if self.origin is None:
            self.origin = origin
        if origin != self.origin:
            raise RuntimeError('VIDEO_OWNER_DOCUMENT_ORIGIN_DRIFT')
        return value

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.profile.close()
        finally:
            try:
                if self.listener_added:
                    try:
                        self.page.remove_listener('framenavigated', self._navigated)
                    except Exception as exc:
                        self.invalid = True
                        log_exception(get_logger('native_video.lifetime'), 'native_video_lifetime_cleanup_failed', exc)
                    self.listener_added = False
            finally:
                if self.transport_binding is not None:
                    self.transport_binding.close()


def begin_native_video_lifetime(flow, page, url):
    parts = urlsplit(url)
    context = getattr(flow, '_execution_evidence_context', None) or {}
    if (context.get('mode') != 'batch_draft_save' or parts.scheme != 'https'
            or parts.netloc != 'www.dianxiaomi.com' or parts.path != '/web/smt/edit'
            or set(parse_qs(parts.query)) != {'id'}):
        return
    close_native_video_lifetime(flow)
    try:
        flow._native_video_lifetime = NativeVideoLifetime(page, page_url=url,
            session_id=flow.browser_session_id()).start()
    except Exception as exc:
        flow._native_video_lifetime = None
        log_exception(get_logger('native_video.lifetime'), 'native_video_page_observation_unavailable', exc)


def close_native_video_lifetime(flow):
    previous = getattr(flow, '_native_video_lifetime', None)
    flow._native_video_lifetime = None
    if previous is not None:
        previous.close()
