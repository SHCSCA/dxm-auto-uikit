"""合成事件逐项拒绝丢失绑定、提前读体、时序漂移和监听残留。"""

from dataclasses import replace
import json

import pytest

from src.core.config_bus import configuration_scope
from src.execution.native_video_wire import NativeVideoWireError
from tests.support.native_video_network_case import (
    GENERATION_BODY, MEDIA, UUID, Request, assert_no_authority, change_scope, exchange, make_case,
)


def assert_incomplete(case, reason=None):
    result = case.capture.private_facts()
    assert result['wire_complete'] is False
    assert_no_authority(result)
    if reason:
        assert 'NATIVE_VIDEO_WIRE_' + reason in result['issues']
    return result


def test_no_response_body_read_before_finished_event_and_exact_object_is_bound():
    case = make_case(); case.capture.start()
    request = Request(case.page)
    case.page.emit('request', request)
    case.page.emit('response', request.response_value)
    assert request.response_reads == request.response_value.reads == 0
    assert_incomplete(case, 'WINDOW_OPEN')
    case.page.emit('requestfinished', request)
    assert request.response_reads == request.response_value.reads == 0
    case.capture.close()
    assert request.response_reads == request.response_value.reads == 1
    assert case.capture.private_facts()['wire_complete'] is True
    assert case.page.registered == case.page.removed
    assert not any(case.page.listeners.values())


@pytest.mark.parametrize('phase', ['request', 'response', 'finished'])
@pytest.mark.parametrize('field,value', [('method', 'GET'), ('resource_type', 'script'),
    ('frame', object()), ('redirected_from', object()), ('redirected_to', object())])
def test_each_event_rechecks_exact_request_scope_before_body_read(phase, field, value):
    case = make_case(); case.capture.start(); request = Request(case.page)
    if phase != 'request':
        case.page.emit('request', request)
    if phase == 'finished':
        case.page.emit('response', request.response_value)
    setattr(request, field, value)
    case.page.emit({'request': 'request', 'response': 'response', 'finished': 'requestfinished'}[phase],
                   request.response_value if phase == 'response' else request)
    case.capture.close()
    assert_incomplete(case, 'REQUEST_SCOPE_INVALID')
    assert request.response_value.reads == 0


@pytest.mark.parametrize('kind', ['orphan_response', 'other_response', 'duplicate_response', 'duplicate_finish'])
def test_another_or_duplicate_object_cannot_supply_completed_body(kind):
    case = make_case(); case.capture.start(); request = Request(case.page)
    if kind != 'orphan_response':
        case.page.emit('request', request)
    case.page.emit('response', request.response_value)
    if kind == 'other_response':
        original = request.response_value
        request.response_value = Request(case.page).response_value
        case.page.emit('requestfinished', request)
        assert original.reads == 0
    elif kind == 'duplicate_response':
        case.page.emit('response', request.response_value)
    elif kind == 'duplicate_finish':
        case.page.emit('requestfinished', request)
        case.page.emit('requestfinished', request)
        assert request.response_value.reads == 0
    case.capture.close()
    if kind == 'duplicate_finish':
        assert request.response_value.reads == 1
    assert_incomplete(case)


@pytest.mark.parametrize('change', ['headers_missing', 'compressed', 'oversized', 'length_changed',
    'wrong_type', 'non_200', 'body_error', 'duplicate_json', 'unknown_process'])
def test_unbounded_unfinished_malformed_or_failed_responses_never_form_complete_wire(change):
    case = make_case(); case.capture.start(); request = Request(case.page)
    response = request.response_value
    if change == 'headers_missing':
        response.headers.pop('content-length')
    elif change == 'compressed':
        response.headers['content-encoding'] = 'gzip'
    elif change == 'oversized':
        response.headers['content-length'] = '1048577'
    elif change == 'length_changed':
        response.headers['content-length'] = str(len(response.raw) + 1)
    elif change == 'wrong_type':
        response.headers['content-type'] = 'text/html'
    elif change == 'non_200':
        response.status = 302
    elif change == 'body_error':
        response.error = RuntimeError('synthetic body unavailable')
    elif change == 'duplicate_json':
        response.update(b'{"code":0,"code":0,"data":"synthetic-native-uuid"}')
    else:
        request = Request(case.page, 'progress', response={'code': 0, 'data': {'processMsg': {'code': '1'}}})
        exchange(case, Request(case.page))
        response = request.response_value
    exchange(case, request); case.capture.close()
    assert_incomplete(case)
    if change in {'headers_missing', 'compressed', 'oversized', 'wrong_type', 'non_200'}:
        assert response.reads == 0


@pytest.mark.parametrize('kind', ['poll_before_generation', 'wrong_uuid', 'second_generation', 'after_terminal', 'input_drift'])
def test_exact_generation_to_uuid_to_progress_causality_is_required(kind):
    case = make_case(); case.capture.start()
    if kind == 'poll_before_generation':
        request = Request(case.page, 'progress')
    elif kind == 'input_drift':
        request = Request(case.page, raw=GENERATION_BODY.replace(b'transition=4', b'transition=0'))
    else:
        exchange(case, Request(case.page))
        if kind == 'wrong_uuid':
            request = Request(case.page, 'progress', raw=b'uuid=other-uuid')
        elif kind == 'second_generation':
            request = Request(case.page)
        else:
            exchange(case, Request(case.page, 'progress'))
            request = Request(case.page, 'progress')
    exchange(case, request); case.capture.close()
    assert request.response_value.reads == 0
    assert_incomplete(case)


@pytest.mark.parametrize('drift', ['session', 'command_params', 'page_url', 'frame', 'same_url_reload', 'deadline', 'window', 'time_regression'])
def test_live_scope_time_and_document_are_rechecked_before_reading_response(drift):
    case = make_case(); case.capture.start(); request = Request(case.page)
    case.page.emit('request', request); case.page.emit('response', request.response_value)
    if drift == 'session':
        change_scope(case, browser_session_id='other-session')
    elif drift == 'command_params':
        case.command.params['extra'] = 'drift'
    elif drift == 'page_url':
        case.page.url += '&drift=true'
    elif drift == 'frame':
        case.page.main_frame = object()
    elif drift == 'same_url_reload':
        case.page.emit('framenavigated', case.page.main_frame)
    elif drift == 'deadline':
        case.capture.command = replace(case.command, deadline='2026-10-15T23:00:00Z')
    else:
        case.clock.advance(301 if drift == 'window' else -1)
    case.page.emit('requestfinished', request); case.capture.close()
    assert_incomplete(case)
    assert request.response_value.reads == 0


@pytest.mark.parametrize('phase', ['registration', 'cleanup', 'cleanup_navigation'])
def test_partial_listener_registration_and_cleanup_attempt_all_and_never_leave_complete(phase):
    case = make_case()
    if phase == 'registration':
        case.page.registration_failure = 'response'
        with pytest.raises(RuntimeError, match='registration unavailable'):
            case.capture.start()
    else:
        case.capture.start(); exchange(case, Request(case.page))
        if phase == 'cleanup':
            case.page.cleanup_failure = 'request'
        else:
            case.page.cleanup_effect = lambda page, event: page.emit('framenavigated', page.main_frame) if event == 'request' else None
        case.capture.close()
    assert case.page.registered == case.page.removed
    assert_incomplete(case)
    if phase != 'cleanup':
        assert not any(case.page.listeners.values())


def test_failed_requests_limits_and_reuse_are_explicit_and_do_not_export_body(caplog):
    with configuration_scope({'DXM_VIDEO_NETWORK_MAX_EVENTS': '3'}):
        case = make_case()
    case.capture.start(); exchange(case, Request(case.page))
    request = Request(case.page, 'progress')
    case.page.emit('request', request); case.page.emit('requestfailed', request)
    case.capture.close()
    assert_incomplete(case, 'EVENT_LIMIT')
    assert request.response_value.reads == 0
    with pytest.raises(NativeVideoWireError, match='WINDOW_REUSED'):
        case.capture.start()
    assert all(raw not in json.dumps(case.capture.summary()) + caplog.text for raw in (MEDIA, UUID, 'private-a.png'))


def test_scope_dictionary_cannot_replace_bound_scope_before_registration():
    case = make_case(); case.capture.scope = case.scope.validate()
    with pytest.raises(NativeVideoWireError, match='SCOPE_DRIFT'):
        case.capture.start()
    assert case.page.registered == []


@pytest.mark.parametrize('wrong_uuid', [False, True])
def test_delayed_finished_events_are_drained_on_owner_thread_in_uuid_order(wrong_uuid):
    case = make_case(); case.capture.start()
    generation = Request(case.page)
    progress = Request(case.page, 'progress', raw=b'uuid=other-uuid' if wrong_uuid else None)
    case.page.emit('request', generation); case.page.emit('response', generation.response_value)
    exchange(case, progress)
    case.page.emit('requestfinished', generation)
    assert generation.response_value.reads == progress.response_value.reads == 0
    case.capture.close()
    assert generation.response_value.reads == 1
    assert progress.response_value.reads == (0 if wrong_uuid else 1)
    assert case.capture.private_facts()['wire_complete'] is (not wrong_uuid)


@pytest.mark.parametrize('change', ['missing', 'negative_end', 'nonfinite', 'start_regression'])
def test_actual_browser_resource_time_is_required_without_observer_timestamp_fallback(change):
    case = make_case(); case.capture.start()
    generation = exchange(case, Request(case.page))
    progress = Request(case.page, 'progress')
    if change == 'missing':
        progress.timing = {}
    elif change == 'negative_end':
        progress.timing['responseEnd'] = -1
    elif change == 'nonfinite':
        progress.timing['startTime'] = float('nan')
    else:
        progress.timing['startTime'] = generation.timing['startTime'] - 1
    exchange(case, progress); case.capture.close()
    assert_incomplete(case)


def test_navigation_pumped_during_owner_body_read_invalidates_all_consumption():
    case = make_case(); case.capture.start()
    request = exchange(case, Request(case.page))
    body = request.response_value.body
    def navigating_body():
        case.page.emit('framenavigated', case.page.main_frame)
        return body()
    request.response_value.body = navigating_body
    case.capture.close()
    assert_incomplete(case, 'DOCUMENT_CHANGED')
