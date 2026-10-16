"""代理后的浏览器响应头不能掩盖源站边界；合成来源不作为生产证明。"""

from copy import deepcopy

import pytest

from src.execution import native_video_script_capture as subject
from tests.support.native_video_script_case import make_case, complete, assert_incomplete


def test_reviewed_origin_headers_are_consumed_without_trusting_fulfill_header_rewrites(monkeypatch):
    case = make_case(monkeypatch)
    origins = {request: {'valid': True, 'status': 200, 'url': request.url,
        'headers': deepcopy(request.response_value.headers)} for request in case.requests.values()}
    for request in case.requests.values():
        request.response_value.headers['content-length'] = 'untrusted-fulfill-length'
    monkeypatch.setattr(subject, 'origin_response_headers', lambda request: origins[request])
    case.capture.start(); complete(case); case.capture.close()
    assert case.capture.snapshot()['reviewed_resources_match'] is True
    assert all(request.response_value.reads == 1 for request in case.requests.values())


@pytest.mark.parametrize('fault,reason', [
    ('incomplete', 'PROXY_ORIGIN_UNPROVEN'), ('redirect', 'PROXY_ORIGIN_UNPROVEN'),
    ('url', 'PROXY_ORIGIN_UNPROVEN'), ('gzip', 'BODY_BOUNDS_UNPROVEN'),
    ('length', 'BODY_BOUNDS_UNPROVEN'),
])
def test_good_fulfill_headers_never_rescue_unproven_origin_or_trigger_body_read(monkeypatch, fault, reason):
    case = make_case(monkeypatch)
    request = next(iter(case.requests.values()))
    origin = {'valid': True, 'status': 200, 'url': request.url, 'headers': deepcopy(request.response_value.headers)}
    if fault == 'incomplete':
        origin = {'valid': False, 'reason': 'PROXY_RESPONSE_INCOMPLETE'}
    elif fault == 'redirect':
        origin['status'] = 302
    elif fault == 'url':
        origin['url'] += '?redirected=1'
    elif fault == 'gzip':
        origin['headers']['content-encoding'] = 'gzip'
    else:
        origin['headers'].pop('content-length')
    monkeypatch.setattr(subject, 'origin_response_headers', lambda _request: origin)
    case.capture.start(); complete(case); case.capture.close()
    assert_incomplete(case, reason)
    assert all(item.response_value.reads == 0 for item in case.requests.values())
