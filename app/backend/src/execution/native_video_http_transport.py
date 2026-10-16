"""只代理页面已发起且已获只读批准的首请求；绝不跟随重定向。"""

from copy import deepcopy
from weakref import WeakKeyDictionary

from src.core.config_bus import get_config_bus
from src.services.structured_logging import get_logger, log_exception


_ORIGINS = WeakKeyDictionary()


def origin_response_headers(request):
    """None 表示未代理；invalid 记录不能退回使用 fulfill 后的浏览器头。"""
    record = _ORIGINS.get(request)
    return deepcopy(record) if record is not None else None


class NativeVideoSafeRoute:
    def __init__(self, route, reject, require_live):
        self.route, self.request, self.reject = route, route.request, reject
        self.require_live = require_live
        self.handled = False
        bus = get_config_bus()
        self.timeout = bus.integer('DXM_VIDEO_READ_ROUTE_TIMEOUT_MS', 10000, minimum=100, maximum=30000)
        self.max_bytes = bus.integer('DXM_VIDEO_READ_RESPONSE_MAX_BYTES', 4 * 1024 * 1024,
            minimum=1024, maximum=16 * 1024 * 1024)

    def abort(self):
        if not self.handled:
            self.handled = True
            self.route.abort()

    def continue_(self):
        response = None
        _ORIGINS[self.request] = {'valid': False, 'reason': 'PROXY_RESPONSE_INCOMPLETE'}
        record = _ORIGINS[self.request]
        complete = False
        try:
            self.require_live()
            response = self.route.fetch(max_redirects=0, max_retries=0, timeout=self.timeout)
            self.require_live()
            headers = dict(response.headers)
            record = {'valid': False, 'status': response.status, 'url': response.url, 'headers': headers}
            _ORIGINS[self.request] = record
            if 300 <= response.status < 400 or response.url != self.request.url:
                self.reject('HTTP_REDIRECT_BLOCKED')
                self.abort()
                return
            length = headers.get('content-length', '')
            if ('attachment' in headers.get('content-disposition', '').lower()
                    or not length.isdecimal() or not 0 <= int(length) <= self.max_bytes):
                self.reject('HTTP_RESPONSE_BOUNDS_UNPROVEN')
                self.abort()
                return
            body_size = len(response.body())
            self.require_live()
            if body_size > self.max_bytes:
                self.reject('HTTP_RESPONSE_BODY_TOO_LARGE')
                self.abort()
                return
            # 保留 fetch 的原始头与对象；不补写 length/encoding，也不替换正文。
            self.route.fulfill(response=response)
            self.handled = True
            self.require_live()
            complete = True
        except Exception as exc:
            self.reject('HTTP_READ_PROXY_FAILED')
            log_exception(get_logger('native_video.transport'), 'native_video_read_proxy_failed', exc)
            self.abort()
        finally:
            if response is not None:
                try:
                    response.dispose()
                except Exception as exc:
                    complete = False
                    self.reject('HTTP_READ_PROXY_CLEANUP_FAILED')
                    log_exception(get_logger('native_video.transport'), 'native_video_proxy_cleanup_failed', exc)
            if complete:
                try:
                    self.require_live()
                    record['valid'] = True
                except Exception as exc:
                    self.reject('HTTP_READ_PROXY_SCOPE_DRIFT')
                    log_exception(get_logger('native_video.transport'), 'native_video_proxy_scope_drift', exc)
