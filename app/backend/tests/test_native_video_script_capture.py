"""合成事件和本机 Chromium 只验证诊断采集边界，不提供产品 READY 证据。"""

import json
from types import SimpleNamespace

import pytest

from src.core.config_bus import ConfigurationError, configuration_scope
from src.execution import native_video_script_capture as subject
from tests.support.native_video_script_case import (
    EDITOR_URL, SCRIPTS, ScriptRequest, assert_incomplete, assert_no_authority, complete,
    local_chromium_case, make_case,
)


@pytest.mark.parametrize('drain', ['snapshot', 'close'])
def test_exact_finished_request_resources_match_without_authority_or_raw_body(monkeypatch, drain):
    case = make_case(monkeypatch)
    case.capture.start()
    for request in case.requests.values():
        case.page.emit("request", request)
        assert request.response_reads == request.response_value.reads == 0
        case.page.emit("requestfinished", request)
        assert request.response_reads == request.response_value.reads == 0
    if drain == 'snapshot':
        pending = case.capture.snapshot()
        assert pending['reviewed_resources_match'] and not pending['window_closed']
    case.capture.close()
    result = case.capture.snapshot()
    assert result["window_closed"] and result["reviewed_resources_match"]
    assert result["body_read_count"] == 2 and not result["issues"]
    assert all(request.response_reads == request.response_value.reads == 1 for request in case.requests.values())
    assert all(resource["request_finished"] and resource["matches_reviewed"] for resource in result["resources"])
    assert_no_authority(result)
    assert not any(body.decode() in json.dumps(result) for body in SCRIPTS.values())
    result["resources"][0]["matches_reviewed"] = False
    assert case.capture.snapshot()["reviewed_resources_match"]
    assert all(not items for items in case.page.listeners.values())


@pytest.mark.parametrize("phase", ["request", "finished"])
@pytest.mark.parametrize("field,value", [("method", "POST"), ("resource_type", "xhr"),
    ("frame", object()), ("redirected_from", object())])
def test_request_scope_is_exact_before_any_body_read(monkeypatch, phase, field, value):
    case = make_case(monkeypatch); request = next(iter(case.requests.values()))
    case.capture.start()
    if phase == "finished":
        case.page.emit("request", request)
    setattr(request, field, value)
    case.page.emit("request" if phase == "request" else "requestfinished", request)
    case.capture.close()
    assert_incomplete(case, "REQUEST_SCOPE_INVALID" if phase == "request" else "FINISHED_SCOPE_DRIFT")
    assert request.response_reads == request.response_value.reads == 0


@pytest.mark.parametrize("kind", ["different_request", "different_response_request", "redirected_to", "new_main_frame"])
def test_finished_event_requires_original_request_response_and_frame(monkeypatch, kind):
    case = make_case(monkeypatch); name, request = next(iter(case.requests.items()))
    case.capture.start(); case.page.emit("request", request)
    finished = request
    if kind == "different_request":
        finished = ScriptRequest(case.page, name)
    elif kind == "different_response_request":
        request.response_value.request = ScriptRequest(case.page, name)
    elif kind == "redirected_to":
        request.redirected_to = object()
    else:
        case.page.main_frame = object()
    case.page.emit("requestfinished", finished); case.capture.close()
    reason = {"different_request": "FINISH_UNBOUND", "different_response_request": "RESPONSE_INVALID",
              "new_main_frame": "DOCUMENT_UNBOUND"}.get(kind, "FINISHED_SCOPE_DRIFT")
    assert_incomplete(case, reason)
    assert request.response_value.reads == 0


@pytest.mark.parametrize("headers", [{}, {"content-type": "text/plain"},
    {"content-type": "application/javascript", "content-length": "999999999"},
    {"content-type": "application/javascript", "content-length": "-1"},
    {"content-type": "application/javascript", "content-length": "22", "content-encoding": "gzip"}])
def test_unknown_or_unbounded_headers_never_read_body(monkeypatch, headers):
    case = make_case(monkeypatch); request = next(iter(case.requests.values()))
    request.response_value.headers = headers
    case.capture.start(); complete(case); case.capture.close()
    assert_incomplete(case, "BODY_BOUNDS_UNPROVEN")
    assert request.response_value.reads == 0


@pytest.mark.parametrize("kind", ["missing_response", "wrong_status", "body_error", "same_length_changed_sha", "changed_size"])
def test_response_or_source_failure_never_matches(monkeypatch, kind, caplog):
    case = make_case(monkeypatch); request = next(iter(case.requests.values())); response = request.response_value
    if kind == "missing_response":
        request.response_value = None
    elif kind == "wrong_status":
        response.status = 206
    elif kind == "body_error":
        response.body_error = RuntimeError("synthetic body read failed")
    else:
        response.raw = b"x" * len(response.raw) if kind == "same_length_changed_sha" else b"x"
    case.capture.start(); complete(case); case.capture.close()
    reason = "RESPONSE_INVALID" if kind in {"missing_response", "wrong_status"} else (
        "RESPONSE_OBSERVATION_FAILED" if kind == "body_error" else "SOURCE_DRIFT")
    assert_incomplete(case, reason)
    if kind == "body_error":
        assert "native_video_static_body_observation_failed" in caplog.text


@pytest.mark.parametrize("kind", ["missing", "pending", "failed", "duplicate", "duplicate_finish"])
def test_missing_unfinished_failed_and_duplicate_resources_are_incomplete(monkeypatch, kind):
    case = make_case(monkeypatch); request = next(iter(case.requests.values()))
    case.capture.start()
    if kind == "pending":
        case.page.emit("request", request)
    elif kind == "failed":
        case.page.emit("request", request); case.page.emit("requestfailed", request)
    elif kind.startswith("duplicate"):
        complete(case)
        case.page.emit("requestfinished" if kind == "duplicate_finish" else "request", request)
    case.capture.close()
    assert_incomplete(case)
    if kind in {"missing", "pending", "failed"}:
        assert request.response_reads == request.response_value.reads == 0


@pytest.mark.parametrize("suffix", ["?cache=1", "#fragment", "/extra"])
def test_external_or_nonexact_resource_is_ignored_without_reading(monkeypatch, suffix):
    case = make_case(monkeypatch); request = next(iter(case.requests.values()))
    foreign = ScriptRequest(case.page, next(iter(SCRIPTS))); foreign.url = "https://example.invalid/private.js"
    request.url += suffix
    case.capture.start()
    for item in (request, foreign):
        for event in ("request", "requestfinished", "requestfailed"):
            case.page.emit(event, item)
        assert item.response_reads == item.response_value.reads == 0
    case.capture.close()
    assert assert_incomplete(case)["resources"] == []


@pytest.mark.parametrize("phase", ["register", "cleanup"])
def test_listener_failures_attempt_every_registered_cleanup_and_disable_capture(monkeypatch, phase, caplog):
    case = make_case(monkeypatch)
    if phase == "register":
        case.page.registration_failure = "requestfinished"
        with pytest.raises(RuntimeError, match="registration failed"):
            case.capture.start()
        assert case.page.removals == case.page.registrations
    else:
        case.capture.start(); complete(case); case.page.removal_failure = "request"
        case.capture.close()
        assert case.page.removals == case.page.registrations
    assert_incomplete(case, "CAPTURE_START_FAILED" if phase == "register" else "CLEANUP_FAILED")
    before = case.capture.snapshot()
    case.page.emit("request", next(iter(case.requests.values())))
    assert case.capture.snapshot() == before
    assert "native_video_static_capture_" in caplog.text


def test_configuration_bus_freezes_budget_and_limit_stops_further_reads(monkeypatch):
    with configuration_scope({"DXM_VIDEO_SOURCE_MAX_EVENTS": "4"}):
        case = make_case(monkeypatch)
    assert case.capture.max_events == 4
    case.capture.start(); complete(case)
    assert case.capture.snapshot()['body_read_count'] == 2
    request = next(iter(case.requests.values())); case.page.emit("requestfinished", request)
    case.capture.close()
    assert_incomplete(case, "EVENT_LIMIT")
    assert request.response_value.reads == 1
    with pytest.raises(RuntimeError, match="CAPTURE_REUSED"):
        case.capture.start()


@pytest.mark.parametrize("value", ["3", "129", "04", "NaN"])
def test_invalid_configuration_rejects_before_listener_registration(monkeypatch, value):
    with configuration_scope({"DXM_VIDEO_SOURCE_MAX_EVENTS": value}), pytest.raises(ConfigurationError):
        make_case(monkeypatch)


@pytest.mark.parametrize("next_url", [EDITOR_URL, EDITOR_URL.replace("70001", "70002")])
def test_main_document_reload_or_navigation_cannot_stitch_resources_across_documents(monkeypatch, next_url):
    case = make_case(monkeypatch); first, second = case.requests.values()
    case.capture.start()
    case.page.emit("request", first); case.page.emit("requestfinished", first)
    assert case.capture.snapshot()['body_read_count'] == 1
    case.page.url = case.page.main_frame.url = next_url
    case.page.emit("framenavigated", case.page.main_frame)
    case.page.emit("request", second); case.page.emit("requestfinished", second)
    case.capture.close()
    assert_incomplete(case, "DOCUMENT_CHANGED")
    assert first.response_value.reads == 1 and second.response_value.reads == 0


def test_subframe_navigation_does_not_replace_the_controlled_document(monkeypatch):
    case = make_case(monkeypatch)
    case.capture.start()
    case.page.emit("framenavigated", SimpleNamespace(page=case.page, url="https://example.invalid/frame"))
    complete(case); case.capture.close()
    assert case.capture.snapshot()["reviewed_resources_match"]
    assert_no_authority(case.capture.snapshot())


def test_initial_document_must_bind_by_exact_mainframe_navigation_before_script_reads(monkeypatch):
    case = make_case(monkeypatch, page_url="about:blank")
    case.capture.start()
    assert not case.capture.snapshot()["document_bound"]
    case.page.url = case.page.main_frame.url = EDITOR_URL
    case.page.emit("framenavigated", case.page.main_frame)
    complete(case); case.capture.close()
    assert case.capture.snapshot()["document_bound"] and case.capture.snapshot()["reviewed_resources_match"]
    assert_no_authority(case.capture.snapshot())


def test_cleanup_navigation_cannot_leave_a_complete_resource_profile(monkeypatch):
    case = make_case(monkeypatch)
    original = case.page.remove_listener
    def remove(event, handler):
        if event == "request":
            case.page.emit("framenavigated", case.page.main_frame)
        original(event, handler)
    monkeypatch.setattr(case.page, "remove_listener", remove)
    case.capture.start(); complete(case); case.capture.close()
    assert_incomplete(case)
    assert case.capture.snapshot()["document_invalid"]
    assert all(not listeners for listeners in case.page.listeners.values())


def test_double_close_does_not_reobserve_a_later_document_or_repeat_cleanup(monkeypatch):
    case = make_case(monkeypatch)
    case.capture.start(); complete(case); case.capture.close()
    before, removals = case.capture.snapshot(), list(case.page.removals)
    case.page.url = "https://www.dianxiaomi.com/web/smt/edit?id=70002"
    case.page.main_frame = object()
    case.capture.close()
    assert case.capture.snapshot() == before
    assert case.page.removals == removals


def test_real_chromium_reads_local_synthetic_script_only_after_actual_requestfinished(monkeypatch):
    with local_chromium_case(monkeypatch) as case:
        result = case.capture.snapshot()
        assert case.page.evaluate("window.syntheticVideoCapture") == 17
        assert result["reviewed_resources_match"] and result["window_closed"]
        assert len(case.body_reads) == result["body_read_count"] == 1
        assert all(url.startswith(case.origin) for url in case.routed)
        assert_no_authority(result)
