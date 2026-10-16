import hashlib
import json
import logging
from dataclasses import replace

import pytest

from src.core.config_bus import configuration_scope
from src.execution.native_gate_capture import NativeGateCaptureError, canonical_digest
from src.execution.native_gate_evidence import REVIEWED_NATIVE_GATE_RESPONSES
from tests.support.native_gate_capture_inputs import (
    SyntheticPage, SyntheticRequest, SyntheticResponse, capture_case, emit_pair,
)


def test_complete_passive_pair_exports_only_hashes_and_unbound_unknown_facts():
    case = capture_case()
    with case["capture"] as capture:
        open_snapshot = capture.snapshot()
        assert not open_snapshot["capture_complete"]
        emit_pair(case)
    result = capture.snapshot()
    assert result["capture_complete"]
    assert result["schema"] == "dxm.native_gate_capture.v1"
    assert result["causal_binding"] == "unbound" and result["causal_action"] is None
    assert result["gate_outcome"] == "unknown" and result["response_semantics"] == "unreviewed"
    assert result["authorization_produced"] is False and REVIEWED_NATIVE_GATE_RESPONSES == ()
    request, response = result["events"]
    assert response["request_event_id"] == request["event_id"]
    assert request["wire_body_sha256"] == hashlib.sha256(case["request"].raw).hexdigest()
    assert response["canonical_body_sha256"] == canonical_digest(json.loads(case["response"].raw))
    assert response["wire_body_sha256"] != response["canonical_body_sha256"]
    assert request["monotonic_offset_seconds"] == 1 and response["monotonic_offset_seconds"] == 2
    assert result["scope"]["entry_handshake_id"] == case["scope"].entry_handshake_id
    assert result["window"]["registered_listener_count"] == result["window"]["removed_listener_count"] == 4
    assert all(not values for values in case["page"].listeners.values())
    assert "private-" not in json.dumps(result)
    assert result["capture_sha256"] == canonical_digest({key: value for key, value in result.items() if key != "capture_sha256"})
    result["events"][0]["kind"] = "caller-change"
    assert capture.snapshot()["events"][0]["kind"] == "request"


def test_events_outside_the_registered_window_are_not_read_or_added():
    case = capture_case()
    capture = case["capture"]
    capture._on_request(case["request"])
    with capture:
        emit_pair(case)
    before = capture.snapshot()
    capture._on_response(case["response"])
    assert capture.snapshot() == before
    assert case["request"].read_count == case["response"].read_count == 1


@pytest.mark.parametrize("mutation", ["same_request", "second_request", "same_response", "orphan_response", "request_failed"])
def test_duplicate_or_unmatched_network_objects_never_form_a_complete_pair(mutation):
    case = capture_case()
    page = case["page"]
    with case["capture"] as capture:
        page.emit("request", case["request"])
        if mutation == "same_request":
            page.emit("request", case["request"])
        elif mutation == "second_request":
            page.emit("request", SyntheticRequest(page))
        if mutation == "orphan_response":
            page.emit("response", SyntheticResponse(SyntheticRequest(page)))
        else:
            page.emit("response", case["response"])
        if mutation == "same_response":
            page.emit("response", case["response"])
        if mutation == "request_failed":
            page.emit("requestfailed", case["request"])
    result = capture.snapshot()
    assert not result["capture_complete"] and result["gate_outcome"] == "unknown"
    assert all(not values for values in page.listeners.values())


@pytest.mark.parametrize("field,value", [("browser_session_id", "another-session"),
    ("entry_handshake_id", "another-handshake"), ("first_save_command_id", "another-command"),
    ("target_identity_sha256", "d" * 64), ("snapshot_sha256", "e" * 64), ("scope_sha256", "f" * 64)])
def test_scope_is_rechecked_during_observation_and_at_close(field, value):
    case = capture_case()
    with case["capture"] as capture:
        case["page"].emit("request", case["request"])
        case["current"][0] = replace(case["scope"], **{field: value})
        case["page"].emit("response", case["response"])
    assert "NATIVE_GATE_CAPTURE_SCOPE_DRIFT" in capture.snapshot()["issues"]
    assert case["response"].read_count == 0 and not capture.snapshot()["capture_complete"]


@pytest.mark.parametrize("change", ["wrong_page", "wrong_method", "wrong_resource", "foreign_url"])
def test_wrong_request_scope_is_not_accepted_or_read(change):
    case = capture_case()
    request = case["request"]
    if change == "wrong_page":
        request.frame = SyntheticPage(case["scope"].source_page_url).main_frame
    elif change == "wrong_method":
        request.method = "GET"
    elif change == "wrong_resource":
        request.resource_type = "document"
    else:
        request.url = request.url.replace("www.dianxiaomi.com", "example.invalid")
    with case["capture"] as capture:
        emit_pair(case)
    assert not capture.snapshot()["capture_complete"] and request.read_count == 0


def test_existing_unrelated_listeners_survive_cleanup():
    case = capture_case()
    unrelated = []
    case["page"].on("request", lambda request: unrelated.append(request))
    with case["capture"] as capture:
        emit_pair(case)
    assert capture.snapshot()["capture_complete"] and unrelated == [case["request"]]
    assert len(case["page"].listeners["request"]) == 1


@pytest.mark.parametrize("save_first", [True, False])
def test_observer_neither_orders_nor_classifies_the_separate_save_branch(save_first):
    case = capture_case()
    save_request = SyntheticRequest(case["page"])
    save_request.url = "https://www.dianxiaomi.com/api/smtProduct/add.json"
    save_response = SyntheticResponse(save_request)
    with case["capture"] as capture:
        if save_first:
            case["page"].emit("request", save_request)
            case["page"].emit("response", save_response)
        emit_pair(case)
        if not save_first:
            case["page"].emit("request", save_request)
            case["page"].emit("response", save_response)
    result = capture.snapshot()
    assert result["capture_complete"] and result["gate_outcome"] == "unknown"
    assert save_request.read_count == save_response.read_count == 0
    assert result["counts"]["requests"] == result["counts"]["responses"] == 1
    assert "save_request_count" not in json.dumps(result)


def test_capture_cannot_be_substituted_for_reviewed_causal_gate_evidence():
    from src.execution.native_gate_evidence import join_native_gate_evidence
    from tests.support.native_gate_inputs import native_gate_case

    case = capture_case()
    with case["capture"] as capture:
        emit_pair(case)
    handshake, contract = native_gate_case()
    handshake["native_gate_evidence"] = capture.snapshot()
    result = join_native_gate_evidence(handshake, expected_browser_session_id="unit-session",
                                       reviewed_contracts=(contract,))
    assert result.admitted is False and result.summary["gate_outcome"] == "unknown"


def test_http_failure_is_recorded_without_a_complete_or_admitted_result():
    case = capture_case()
    case["response"].status = 403
    with case["capture"] as capture:
        emit_pair(case)
    result = capture.snapshot()
    assert not result["capture_complete"] and result["events"][1]["status"] == 403
    assert result["gate_outcome"] == "unknown"


@pytest.mark.parametrize("error_type", [RuntimeError, NativeGateCaptureError])
def test_observation_exception_logs_only_fixed_reason_and_counts(caplog, error_type):
    case = capture_case()
    case["request"].error = error_type("private-observation-body")
    with caplog.at_level(logging.WARNING, logger="dxm.native_gate.capture"):
        with case["capture"] as capture:
            emit_pair(case)
    assert not capture.snapshot()["capture_complete"]
    assert caplog.records
    for record in caplog.records:
        assert record.exc_info is None
        assert set(record.event_fields) == {"reason_code", "observed_event_count", "request_count", "response_count"}
        assert "private-" not in json.dumps(record.event_fields)


def test_configuration_is_frozen_from_the_bus_and_invalid_limits_fail_before_listening():
    with configuration_scope({"DXM_NATIVE_GATE_CAPTURE_MAX_BODY_BYTES": "128"}):
        case = capture_case()
    assert case["capture"].limits.max_body_bytes == 128
    with configuration_scope({"DXM_NATIVE_GATE_CAPTURE_MAX_EVENTS": "0"}):
        with pytest.raises(NativeGateCaptureError, match="CONFIGURATION_INVALID"):
            capture_case()


def test_response_body_is_read_only_after_the_same_request_finishes():
    case = capture_case()
    with case["capture"] as capture:
        case["page"].emit("request", case["request"])
        case["page"].emit("response", case["response"])
        assert case["response"].read_count == 0
        assert not capture.snapshot()["capture_complete"]
        case["page"].emit("requestfinished", case["request"])
    assert capture.snapshot()["capture_complete"] and case["response"].read_count == 1


@pytest.mark.parametrize("other_request", [False, True])
def test_duplicate_or_unassociated_request_finished_is_rejected(other_request):
    case = capture_case()
    with case["capture"] as capture:
        emit_pair(case)
        request = SyntheticRequest(case["page"]) if other_request else case["request"]
        case["page"].emit("requestfinished", request)
    assert not capture.snapshot()["capture_complete"] and case["response"].read_count == 1


def test_open_window_scope_cannot_be_replaced_along_with_its_reader():
    case = capture_case()
    with case["capture"] as capture:
        emit_pair(case)
        capture.scope = replace(case["scope"], entry_handshake_id="replacement")
        case["current"][0] = capture.scope
    result = capture.snapshot()
    assert not result["capture_complete"] and "NATIVE_GATE_CAPTURE_SCOPE_DRIFT" in result["issues"]
    assert result["scope"]["entry_handshake_id"] == case["scope"].entry_handshake_id
