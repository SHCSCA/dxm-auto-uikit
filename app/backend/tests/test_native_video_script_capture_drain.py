"""owner 栈复读与离线并发脚本回归；合成字节不等于已审生产资源。"""

import pytest

from tests.support.native_video_script_case import (
    EDITOR_URL, assert_incomplete, assert_no_authority, local_chromium_case, make_case,
)


def test_finished_body_read_can_pump_more_finished_events_without_callback_rpc(monkeypatch):
    case = make_case(monkeypatch)
    first, second = case.requests.values()
    original = first.response_value.body

    def pump_more_events():
        assert not case.page.in_callback
        case.page.emit('request', second)
        case.page.emit('requestfinished', second)
        assert second.response_reads == second.response_value.reads == 0
        return original()

    monkeypatch.setattr(first.response_value, 'body', pump_more_events)
    case.capture.start()
    case.page.emit('request', first); case.page.emit('requestfinished', first)
    assert first.response_reads == first.response_value.reads == 0
    result = case.capture.snapshot()
    assert result['reviewed_resources_match'] and result['body_read_count'] == 2
    assert not case.capture.finished_bodies and not case.capture.requests
    assert all(request.response_reads == request.response_value.reads == 1 for request in (first, second))
    case.capture.close()
    assert_no_authority(result)


@pytest.mark.parametrize('url', [EDITOR_URL, EDITOR_URL.replace('70001', '70002')])
def test_navigation_before_owner_drain_never_reads_a_previous_document_body(monkeypatch, url):
    case = make_case(monkeypatch)
    request = next(iter(case.requests.values()))
    case.capture.start()
    case.page.emit('request', request); case.page.emit('requestfinished', request)
    assert request.response_reads == request.response_value.reads == 0
    case.page.url = case.page.main_frame.url = url
    case.page.emit('framenavigated', case.page.main_frame)
    case.capture.close()
    assert_incomplete(case, 'DOCUMENT_CHANGED')
    assert request.response_reads == request.response_value.reads == 0


def test_navigation_pumped_during_response_rpc_stops_before_body_rpc(monkeypatch):
    case = make_case(monkeypatch)
    request = next(iter(case.requests.values()))
    original = request.response

    def response_then_navigation():
        response = original()
        case.page.emit('framenavigated', case.page.main_frame)
        return response

    monkeypatch.setattr(request, 'response', response_then_navigation)
    case.capture.start()
    case.page.emit('request', request); case.page.emit('requestfinished', request)
    case.capture.close()
    assert_incomplete(case, 'DOCUMENT_CHANGED')
    assert request.response_reads == 1 and request.response_value.reads == 0


def test_actual_offline_concurrent_scripts_are_queued_until_close_and_drained_once(monkeypatch):
    with local_chromium_case(monkeypatch, script_count=4) as case:
        result = case.capture.snapshot()
        assert case.reads_before_close == (0, 0) and case.queued_before_close == 4
        assert len(case.response_reads) == len(case.body_reads) == result['body_read_count'] == 4
        assert result['reviewed_resources_match'] and result['window_closed']
        assert not case.capture.finished_bodies and not case.capture.requests
        assert case.page.evaluate('window.syntheticConcurrent3') == 3
        assert len(set(case.routed)) == 5 and all(url.startswith(case.origin) for url in case.routed)
        assert_no_authority(result)
