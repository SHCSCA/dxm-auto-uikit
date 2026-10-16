"""被动核对页面实际加载的视频静态资源；只输出诊断，不建立执行权威。"""

from copy import deepcopy
from hashlib import sha256

from src.core.config_bus import get_config_bus
from src.services.structured_logging import get_logger, log_event, log_exception


PUBLIC_ASSET_BASE = 'https://s13.dianxiaomi.com/dxm-web/2026-09/assets/'
# 固定版本的公开源码事实不等于当前页面事实；必须观察实际完成的同页加载。
REVIEWED_VIDEO_SCRIPTS = {
    'ImgToVideoModal-Cn4d-6zD.js': (9426, '25D36FFACB573B45F3D94EB031335BABDF5DF7FA1D870F657C2DC1956ACB5FED'),
    'const-BvIXJGkR.js': (5783, '4E5DE1A9D5557DBF1236D54C2CBC97C8E37CDBC03828DD0EC4304361132AED0C'),
    'index-BA-XYm54.js': (5801, 'D0D279941260EACE1E2852E157E84784560350674C5B174B23BBA1B6773031C4'),
    'index-DxrHWTJK.js': (19043, 'F94C2FAC920C0A542960F419C9BF1BFC4ADEDD8C8FFA96218A2F5D23EE3B1637'),
}
_LOGGER = get_logger('native_video.static_capture')


class PassiveNativeVideoScriptCapture:
    def __init__(self, page, *, expected_page_url):
        self.page, self.frame = page, page.main_frame
        self.expected_page_url = expected_page_url
        self.document_bound = False
        self.document_invalid = False
        self.listeners, self.requests, self.resources, self.issues = [], {}, {}, set()
        self.active = self.closed = False
        self.event_count = self.body_read_count = 0
        try:
            self.max_events = get_config_bus().integer('DXM_VIDEO_SOURCE_MAX_EVENTS', 32, minimum=4, maximum=128)
        except Exception as exc:
            log_exception(_LOGGER, 'native_video_static_configuration_failed', exc)
            raise

    def _issue(self, reason):
        if reason not in self.issues:
            self.issues.add(reason)
            log_event(_LOGGER, 'native_video_static_capture_incomplete', level='WARNING', reason_code=reason)

    def start(self):
        if self.active or self.closed:
            raise RuntimeError('NATIVE_VIDEO_STATIC_CAPTURE_REUSED')
        try:
            self.document_bound = str(self.page.url) == self.expected_page_url
            for event, handler in (('request', self._request), ('requestfinished', self._finished),
                                   ('requestfailed', self._failed), ('framenavigated', self._navigated)):
                self.listeners.append((event, handler))
                self.page.on(event, handler)
            self.active = True
        except Exception as exc:
            log_exception(_LOGGER, 'native_video_static_capture_start_failed', exc)
            self._issue('NATIVE_VIDEO_STATIC_CAPTURE_START_FAILED')
            self.close()
            raise
        return self

    def _navigated(self, frame):
        try:
            if not self.active or (frame is not self.frame and frame is not self.page.main_frame):
                return
            if self.document_bound or frame is not self.frame or str(frame.url) != self.expected_page_url:
                self.document_invalid = True
                self._issue('NATIVE_VIDEO_STATIC_DOCUMENT_CHANGED')
            else:
                self.document_bound = True
        except Exception as exc:
            self.document_invalid = True
            log_exception(_LOGGER, 'native_video_static_navigation_observation_failed', exc)
            self._issue('NATIVE_VIDEO_STATIC_DOCUMENT_OBSERVATION_FAILED')

    def _candidate(self, request):
        if not self.active:
            return None
        name = next((name for name in REVIEWED_VIDEO_SCRIPTS if request.url == PUBLIC_ASSET_BASE + name), None)
        if name is None:
            return None
        self.event_count += 1
        if self.event_count > self.max_events:
            self._issue('NATIVE_VIDEO_STATIC_EVENT_LIMIT')
            return None
        if (not self.document_bound or self.document_invalid or self.page.main_frame is not self.frame
                or str(self.page.url) != self.expected_page_url):
            self._issue('NATIVE_VIDEO_STATIC_DOCUMENT_UNBOUND')
            return None
        return name

    def _request(self, request):
        try:
            name = self._candidate(request)
            if name is None:
                return
            if (request.method != 'GET' or request.resource_type != 'script' or request.frame is not self.frame
                    or request.redirected_from is not None):
                self._issue('NATIVE_VIDEO_STATIC_REQUEST_SCOPE_INVALID')
                return
            if name in self.resources:
                self._issue('NATIVE_VIDEO_STATIC_DUPLICATE_RESOURCE')
                return
            self.resources[name] = {'name': name, 'request_finished': False, 'sha256': None, 'matches_reviewed': False}
            self.requests[id(request)] = (request, name)
        except Exception as exc:
            log_exception(_LOGGER, 'native_video_static_request_failed', exc)
            self._issue('NATIVE_VIDEO_STATIC_REQUEST_OBSERVATION_FAILED')

    def _finished(self, request):
        try:
            name = self._candidate(request)
            if name is None:
                return
            source = self.requests.pop(id(request), None)
            if source is None or source[0] is not request:
                self._issue('NATIVE_VIDEO_STATIC_FINISH_UNBOUND')
                return
            if (request.frame is not self.frame or self.page.main_frame is not self.frame
                    or request.method != 'GET' or request.resource_type != 'script'
                    or request.redirected_from is not None or request.redirected_to is not None):
                self._issue('NATIVE_VIDEO_STATIC_FINISHED_SCOPE_DRIFT')
                return
            resource = self.resources[name]
            resource['request_finished'] = True
            response = request.response()
            size, expected_hash = REVIEWED_VIDEO_SCRIPTS[name]
            if response is None or response.request is not request or response.status != 200:
                self._issue('NATIVE_VIDEO_STATIC_RESPONSE_INVALID')
                return
            headers = {key.lower(): value for key, value in response.headers.items()}
            if (headers.get('content-type', '').split(';')[0].strip().lower()
                    not in {'application/javascript', 'text/javascript'}
                    or headers.get('content-encoding', 'identity').lower() != 'identity'
                    or headers.get('content-length') != str(size)):
                self._issue('NATIVE_VIDEO_STATIC_BODY_BOUNDS_UNPROVEN')
                return
            self.body_read_count += 1
            body = response.body()
            actual_hash = sha256(body).hexdigest().upper()
            resource.update({'size': len(body), 'sha256': actual_hash,
                             'matches_reviewed': len(body) == size and actual_hash == expected_hash})
            if not resource['matches_reviewed']:
                self._issue('NATIVE_VIDEO_STATIC_SOURCE_DRIFT')
        except Exception as exc:
            log_exception(_LOGGER, 'native_video_static_body_observation_failed', exc)
            self._issue('NATIVE_VIDEO_STATIC_RESPONSE_OBSERVATION_FAILED')

    def _failed(self, request):
        try:
            if self._candidate(request) is not None:
                self.requests.pop(id(request), None)
                self._issue('NATIVE_VIDEO_STATIC_REQUEST_FAILED')
        except Exception as exc:
            log_exception(_LOGGER, 'native_video_static_failure_observation_failed', exc)
            self._issue('NATIVE_VIDEO_STATIC_FAILURE_OBSERVATION_FAILED')

    def snapshot(self):
        missing = sorted(set(REVIEWED_VIDEO_SCRIPTS) - set(self.resources))
        complete = (self.document_bound and not self.document_invalid
                    and not missing and not self.requests and not self.issues
                    and all(item['matches_reviewed'] for item in self.resources.values()))
        return deepcopy({'schema': 'dxm.native_video_static_capture.v1',
            'profile': 'dxm.public_video.2026-09.v1', 'window_closed': self.closed,
            'document_bound': self.document_bound, 'document_invalid': self.document_invalid,
            'reviewed_resources_match': complete, 'missing_resources': missing,
            'resources': list(self.resources.values()), 'issues': sorted(self.issues),
            'body_read_count': self.body_read_count, 'executionAllowed': False,
            'capabilityCertified': False, 'inputFreezeAllowed': False})

    def close(self):
        if self.closed:
            return
        self.closed = True
        operations, self.listeners = self.listeners, []
        for event, handler in operations:
            try:
                self.page.remove_listener(event, handler)
            except Exception as exc:
                log_exception(_LOGGER, 'native_video_static_capture_cleanup_failed', exc, observed_event=event)
                self._issue('NATIVE_VIDEO_STATIC_CLEANUP_FAILED')
        try:
            if self.document_bound and (self.page.main_frame is not self.frame
                    or str(self.page.url) != self.expected_page_url):
                self.document_invalid = True
                self._issue('NATIVE_VIDEO_STATIC_DOCUMENT_CHANGED')
        except Exception as exc:
            self.document_invalid = True
            log_exception(_LOGGER, 'native_video_static_final_identity_failed', exc)
            self._issue('NATIVE_VIDEO_STATIC_DOCUMENT_OBSERVATION_FAILED')
        self.active = False
