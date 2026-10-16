"""合成 RPC 回入验证失效范围不能回填 valid；真实重定向另由 Chromium 计数。"""

from types import SimpleNamespace

import pytest

from src.execution.native_video_http_transport import NativeVideoSafeRoute, origin_response_headers


class Request:
    url = 'https://www.dianxiaomi.com/api/picToVideo/getCountInfo.json'


class Response:
    def __init__(self):
        self.status, self.url = 200, Request.url
        self.headers = {'content-length': '2', 'content-type': 'application/json'}
        self.raw = b'{}'
        self.dispose_count = 0
        self.on_body = self.on_dispose = lambda: None

    def body(self):
        self.on_body()
        return self.raw

    def dispose(self):
        self.dispose_count += 1
        self.on_dispose()


class Route:
    def __init__(self, response):
        self.request, self.response = Request(), response
        self.fetch_options = self.fulfilled = None
        self.aborted = 0
        self.on_fetch = self.on_fulfill = lambda: None

    def fetch(self, **kwargs):
        self.fetch_options = kwargs
        self.on_fetch()
        return self.response

    def fulfill(self, **kwargs):
        self.fulfilled = kwargs
        self.on_fulfill()

    def abort(self):
        self.aborted += 1


def make_case():
    response = Response()
    route, issues, state = Route(response), [], SimpleNamespace(live=True)

    def require_live():
        if not state.live:
            raise RuntimeError('SYNTHETIC_OWNER_CLOSED')

    return response, route, issues, state, NativeVideoSafeRoute(route, issues.append, require_live)


def test_proxy_preserves_exact_response_object_and_origin_headers_without_rewriting_encoding():
    response, route, issues, state, safe = make_case()
    response.headers['content-encoding'] = 'gzip'
    safe.continue_()
    assert issues == [] and route.aborted == 0
    assert route.fetch_options == {'max_redirects': 0, 'max_retries': 0, 'timeout': 10000}
    assert route.fulfilled == {'response': response}
    origin = origin_response_headers(route.request)
    assert origin == {'valid': True, 'status': 200, 'url': Request.url, 'headers': response.headers}
    origin['headers']['content-encoding'] = 'identity'
    assert origin_response_headers(route.request)['headers']['content-encoding'] == 'gzip'
    assert origin_response_headers(Request()) is None
    assert response.dispose_count == 1


@pytest.mark.parametrize('phase', ['fetch', 'body', 'fulfill', 'dispose'])
def test_owner_drift_at_each_pumping_rpc_never_creates_a_valid_origin_record(phase):
    response, route, issues, state, safe = make_case()
    target = route if phase in {'fetch', 'fulfill'} else response
    setattr(target, f'on_{phase}', lambda: setattr(state, 'live', False))
    safe.continue_()
    assert origin_response_headers(route.request)['valid'] is False
    assert issues
    if phase in {'fetch', 'body'}:
        assert route.fulfilled is None and route.aborted == 1
    assert response.dispose_count == 1


@pytest.mark.parametrize('status', [301, 302, 303, 307, 308])
def test_all_redirect_response_candidates_abort_before_fulfill(status):
    response, route, issues, state, safe = make_case()
    response.status = status
    safe.continue_()
    assert route.fulfilled is None and route.aborted == 1
    assert issues == ['HTTP_REDIRECT_BLOCKED']
    assert origin_response_headers(route.request)['valid'] is False


@pytest.mark.parametrize('headers', [{}, {'content-length': '-1'}, {'content-length': '99999999'},
    {'content-length': '2', 'content-disposition': 'attachment; filename="private.bin"'}])
def test_missing_or_oversized_response_bounds_and_attachments_do_not_reach_page(headers):
    response, route, issues, state, safe = make_case()
    response.headers = headers
    safe.continue_()
    assert route.fulfilled is None and route.aborted == 1
    assert issues == ['HTTP_RESPONSE_BOUNDS_UNPROVEN']
    assert origin_response_headers(route.request)['valid'] is False


def test_proxy_fetch_failure_is_distinct_from_an_unproxied_request():
    response, route, issues, state, safe = make_case()

    def fail():
        raise RuntimeError('synthetic transport failure')

    route.on_fetch = fail
    safe.continue_()
    assert route.fulfilled is None and route.aborted == 1
    assert origin_response_headers(route.request) == {'valid': False, 'reason': 'PROXY_RESPONSE_INCOMPLETE'}
    assert issues == ['HTTP_READ_PROXY_FAILED']
