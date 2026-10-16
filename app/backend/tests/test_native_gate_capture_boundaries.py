import json
from dataclasses import replace
from datetime import datetime

import pytest

from src.core.config_bus import configuration_scope
from src.execution.native_gate_capture import NativeGateCaptureError, NativeGateCaptureStamp
from tests.support.native_gate_capture_inputs import capture_case, emit_pair


@pytest.mark.parametrize("raw,content_type,reason", [
    (b"not-json", "application/json", "JSON_INVALID"),
    (b'{"x":1,"x":2}', "application/json", "JSON_DUPLICATE_KEY"),
    (b'{"x":NaN}', "application/json", "JSON_INVALID"),
    (b'{"x":Infinity}', "application/json", "JSON_INVALID"),
    (b'{"x":"\xff"}', "application/json", "JSON_INVALID"),
    (b"[]", "application/json", "BODY_FORMAT_UNREVIEWED"),
    (b"x=private-body", "application/x-www-form-urlencoded", "BODY_FORMAT_UNREVIEWED"),
    (b'{"x":1}', "text/plain", "BODY_FORMAT_UNREVIEWED"),
])
def test_unknown_or_ambiguous_body_preserves_only_raw_hash_and_stays_incomplete(raw, content_type, reason):
    case = capture_case()
    case["response"].raw = raw
    case["response"].headers = {"content-type": content_type, "content-length": str(len(raw))}
    with case["capture"] as capture:
        emit_pair(case)
    result = capture.snapshot()
    assert not result["capture_complete"]
    assert "NATIVE_GATE_CAPTURE_" + reason in result["issues"]
    assert result["events"][1]["raw_body_sha256"]
    assert result["events"][1]["canonical_body_sha256"] is None
    assert "private-body" not in json.dumps(result)


def test_compressed_response_is_not_misrepresented_as_wire_bytes():
    case = capture_case()
    case["response"].headers["content-encoding"] = "gzip"
    with case["capture"] as capture:
        emit_pair(case)
    result = capture.snapshot()
    assert not result["capture_complete"] and "NATIVE_GATE_CAPTURE_WIRE_BODY_UNPROVEN" in result["issues"]
    response = result["events"][1]
    assert response["raw_body_sha256"] is response["canonical_body_sha256"] is response["wire_body_sha256"] is None
    assert case["response"].read_count == 0


def test_unknown_response_length_does_not_trigger_an_unbounded_body_read():
    case = capture_case()
    del case["response"].headers["content-length"]
    with case["capture"] as capture:
        emit_pair(case)
    assert not capture.snapshot()["capture_complete"] and case["response"].read_count == 0
    assert "NATIVE_GATE_CAPTURE_BODY_LENGTH_UNPROVEN" in capture.snapshot()["issues"]


@pytest.mark.parametrize("declared,raw,read_count,reason", [
    ("129", b"{}", 0, "BODY_SIZE_INVALID"),
    ("-1", b"{}", 0, "BODY_SIZE_INVALID"),
    ("wrong", b"{}", 0, "BODY_SIZE_INVALID"),
    ("2", b"x" * 129, 1, "BODY_TOO_LARGE"),
])
def test_declared_and_actual_body_size_are_checked_before_accepting_evidence(declared, raw, read_count, reason):
    with configuration_scope({"DXM_NATIVE_GATE_CAPTURE_MAX_BODY_BYTES": "128"}):
        case = capture_case()
    case["response"].headers["content-length"] = declared
    case["response"].raw = raw
    with case["capture"] as capture:
        emit_pair(case)
    assert not capture.snapshot()["capture_complete"]
    assert "NATIVE_GATE_CAPTURE_" + reason in capture.snapshot()["issues"]
    assert case["response"].read_count == read_count


@pytest.mark.parametrize("kind", ["monotonic_regression", "wall_regression", "expired"])
def test_clock_regression_or_expired_window_never_produces_complete_evidence(kind):
    with configuration_scope({"DXM_NATIVE_GATE_CAPTURE_MAX_WINDOW_SECONDS": "2"}):
        case = capture_case()
    with case["capture"] as capture:
        case["clock"].seconds = 1
        case["page"].emit("request", case["request"])
        if kind == "monotonic_regression":
            case["clock"].seconds = 0.5
        elif kind == "wall_regression":
            case["clock"].wall_shift = -1
        else:
            case["clock"].seconds = 3
        case["page"].emit("response", case["response"])
    assert not capture.snapshot()["capture_complete"]
    expected = "WINDOW_EXPIRED" if kind == "expired" else "TIME_REGRESSION"
    assert "NATIVE_GATE_CAPTURE_" + expected in capture.snapshot()["issues"]
    assert all(not values for values in case["page"].listeners.values())


def test_naive_clock_cannot_open_a_recording_window_and_listeners_are_removed():
    case = capture_case()
    case["capture"].clock = lambda: NativeGateCaptureStamp(datetime(2026, 10, 16), 0)
    with pytest.raises(NativeGateCaptureError, match="TIME_INVALID"):
        with case["capture"]:
            pytest.fail("无效时钟不能进入采集窗口")
    assert not case["capture"].snapshot()["capture_complete"]
    assert all(not values for values in case["page"].listeners.values())


@pytest.mark.parametrize("field,value", [("product_id", "0"), ("task_id", True),
    ("target_identity_sha256", "invalid"), ("entry_handshake_id", ""),
    ("source_page_url", "https://www.dianxiaomi.com/web/smt/edit?id=70001&token=private-value")])
def test_invalid_scope_never_registers_listeners(field, value):
    case = capture_case()
    scope = replace(case["scope"], **{field: value})
    case["capture"].scope, case["current"][0] = scope, scope
    with pytest.raises(NativeGateCaptureError):
        with case["capture"]:
            pytest.fail("无效范围不能进入采集窗口")
    assert not case["page"].listeners and not case["capture"].snapshot()["capture_complete"]


def test_request_budget_prevents_unbounded_events_or_body_reads():
    with configuration_scope({"DXM_NATIVE_GATE_CAPTURE_MAX_EVENTS": "3"}):
        case = capture_case()
    with case["capture"] as capture:
        emit_pair(case)
        for _ in range(5):
            case["page"].emit("response", case["response"])
    assert len(capture.snapshot()["events"]) == 2 and not capture.snapshot()["capture_complete"]
    assert case["response"].read_count == 1
    assert "NATIVE_GATE_CAPTURE_EVENT_LIMIT" in capture.snapshot()["issues"]


def test_partial_registration_is_fully_removed_even_if_on_attaches_then_raises():
    case = capture_case()
    case["page"].registration_failure = "response"
    with pytest.raises(NativeGateCaptureError, match="START_FAILED"):
        with case["capture"]:
            pytest.fail("监听注册失败不能进入窗口")
    assert case["page"].removal_attempts == ["request", "response"]
    assert all(not values for values in case["page"].listeners.values())
    assert not case["capture"].snapshot()["capture_complete"]


def test_cleanup_failure_attempts_every_listener_and_never_claims_complete():
    case = capture_case()
    case["page"].removal_failure = "request"
    with case["capture"] as capture:
        emit_pair(case)
    before = capture.snapshot()
    case["page"].emit("request", case["request"])
    capture.close()
    assert capture.snapshot() == before and capture.requests == {}
    assert not before["capture_complete"] and before["window"]["removed_listener_count"] == 3
    assert case["page"].removal_attempts == ["request", "response", "requestfinished", "requestfailed"]


def test_caller_exception_propagates_while_capture_is_closed_and_marked_incomplete():
    case = capture_case()
    error = RuntimeError("private-caller-value")
    with pytest.raises(RuntimeError) as failure:
        with case["capture"] as capture:
            emit_pair(case)
            raise error
    assert failure.value is error and not capture.snapshot()["capture_complete"]
    assert all(not values for values in case["page"].listeners.values())


def test_closed_capture_cannot_be_reused():
    case = capture_case()
    with case["capture"] as capture:
        emit_pair(case)
    with pytest.raises(NativeGateCaptureError, match="WINDOW_REUSED"):
        with capture:
            pytest.fail("已结束的采集不得被复用")
    assert len(capture.snapshot()["events"]) == 2


@pytest.mark.parametrize("phase", ["before_start", "before_response", "before_close"])
def test_page_navigation_without_reviewed_binding_invalidates_the_capture(phase):
    case = capture_case()
    if phase == "before_start":
        case["page"].url = "https://example.invalid/"
        with pytest.raises(NativeGateCaptureError, match="PAGE_DRIFT"):
            with case["capture"]:
                pytest.fail("页面范围失配不能开启窗口")
    else:
        with case["capture"]:
            case["page"].emit("request", case["request"])
            if phase == "before_response":
                case["page"].url = "https://example.invalid/"
            case["page"].emit("response", case["response"])
            case["page"].url = "https://www.dianxiaomi.com/web/smt/editFromSmt?id=70001"
    assert not case["capture"].snapshot()["capture_complete"]
    assert "NATIVE_GATE_CAPTURE_PAGE_DRIFT" in case["capture"].snapshot()["issues"]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, -1])
def test_non_finite_or_boolean_monotonic_clock_cannot_open_the_window(value):
    case = capture_case()
    stamp = case["clock"]()
    case["capture"].clock = lambda: NativeGateCaptureStamp(stamp.wall_time, value)
    with pytest.raises(NativeGateCaptureError, match="TIME_INVALID"):
        with case["capture"]:
            pytest.fail("非有限单调时钟不能开启窗口")
    assert all(not values for values in case["page"].listeners.values())
