from copy import deepcopy

import pytest

from src.execution.dxm_adapter import DxmWorkflowAdapter
from src.execution.action_result_contract import ACTION_RESULT_CONTRACTS, ActionResultContractError, validate_action_result_envelope
from src.execution.native_gate_evidence import join_native_gate_evidence
from tests.support.action_results import _path_a_execution_payload, _valid_save_result
from tests.support.native_gate_inputs import native_gate_case


def _join(handshake, contract):
    return join_native_gate_evidence(handshake, expected_browser_session_id="unit-session",
        reviewed_contracts=(contract,))


def test_gate_join_requires_passive_network_and_closed_save1_same_handshake():
    handshake, contract = native_gate_case()
    joined = _join(handshake, contract)
    assert joined.admitted and joined.reason_code == "OK"
    assert joined.summary == {"gate_outcome": "admitted", "semi_entry_triggered": True,
        "same_handshake": True, "handshake_id": "gate-handshake", "save1_verified": True,
        "exactly_one_save_request": True}


@pytest.mark.parametrize("mutate, reason", [
    (lambda h: h["native_gate_evidence"].update(handshake_id="another"), "NATIVE_GATE_HANDSHAKE_MISMATCH"),
    (lambda h: h["native_gate_evidence"].pop("response"), "NATIVE_GATE_RESPONSE_MISSING"),
    (lambda h: h["native_gate_evidence"].update(replayed=True), "NATIVE_GATE_NOT_PASSIVE"),
    (lambda h: h["native_gate_evidence"].update(browser_session_id="another"), "NATIVE_GATE_SESSION_MISMATCH"),
    (lambda h: h["native_gate_evidence"]["request"].update(url="https://example.invalid/verify"), "NATIVE_GATE_ENDPOINT_INVALID"),
    (lambda h: h["native_gate_evidence"]["response"]["body"].update(synthetic_native_decision="other"), "NATIVE_GATE_BODY_HASH_MISMATCH"),
    (lambda h: h.pop("save1_receipt"), "NATIVE_GATE_SAVE1_NOT_CLOSED"),
    (lambda h: h["save1_receipt"]["proofs"].pop("unpublished_status"), "NATIVE_GATE_SAVE1_NOT_CLOSED"),
    (lambda h: h["save1_receipt"].update(unresolved=True), "NATIVE_GATE_SAVE1_NOT_CLOSED"),
    (lambda h: h["network_save_result"].update(ok=False), "NATIVE_GATE_SAVE1_NOT_CLOSED"),
    (lambda h: h["network_audit"].update(save_request_count=2), "NATIVE_GATE_SAVE1_NOT_CLOSED"),
    (lambda h: h["network_save_result"].update(response_evidence_id="another-save"), "NATIVE_GATE_SAVE1_NETWORK_MISMATCH"),
])
def test_gate_join_rejects_missing_drifted_or_unclosed_facts(mutate, reason):
    handshake, contract = native_gate_case()
    mutate(handshake)
    result = _join(handshake, contract)
    assert result.admitted is False
    assert result.reason_code == reason
    assert result.summary["gate_outcome"] == "unknown"
    assert result.summary["save1_verified"] is False


def test_production_gate_stays_closed_without_reviewed_response_semantics():
    handshake, _contract = native_gate_case()
    result = join_native_gate_evidence(handshake, expected_browser_session_id="unit-session")
    assert result.reason_code == "NATIVE_GATE_RESPONSE_CONTRACT_NOT_REVIEWED"
    assert result.admitted is False


def test_adapter_never_turns_same_handshake_or_navigation_into_native_admission():
    handshake, _contract = native_gate_case()
    handshake.pop("native_gate_evidence")
    flow = type("Flow", (), {"browser_session_id": lambda self: "unit-session"})()
    adapter = DxmWorkflowAdapter(flow)
    normalized = adapter._normalize_published_evidence("first_save_intent",
        {"ok": True, "first_save_intent_handshake": handshake})
    assert normalized["ok"] is False
    assert normalized["published"] is None
    assert normalized["failure_code"] == "UNKNOWN"
    assert normalized["reason_code"] == "NATIVE_GATE_PASSIVE_EVIDENCE_MISSING"
    observations = {}
    adapter._augment_action_observations("first_save_intent",
        {"first_save_intent_handshake": deepcopy(handshake)}, observations)
    assert observations["save_intent_handshake"]["gate_outcome"] == "unknown"


def test_gate_and_save1_can_close_in_either_observed_order():
    from tests.support.native_gate_inputs import _network

    handshake, contract = native_gate_case()
    gate = handshake["native_gate_evidence"]
    request = _network("request", gate["request"]["body"], "2026-08-31T00:00:10.100000Z")
    response = _network("response", gate["response"]["body"], "2026-08-31T00:00:10.200000Z")
    response["request_evidence_id"] = request["evidence_id"]
    gate.update(request=request, response=response)
    assert _join(handshake, contract).admitted is True


def test_code_zero_without_reviewed_business_semantics_cannot_admit():
    from tests.support.native_gate_inputs import _network

    handshake, contract = native_gate_case()
    gate = handshake["native_gate_evidence"]
    response = _network("response", {"code": 0}, "2026-08-31T00:00:16Z")
    response["request_evidence_id"] = gate["request"]["evidence_id"]
    gate["response"] = response
    assert _join(handshake, contract).reason_code == "NATIVE_GATE_RESPONSE_SEMANTICS_UNKNOWN"


def test_action_result_rejects_boolean_native_gate_even_with_all_postconditions_true():
    envelope = _valid_save_result()
    envelope.update(action="first_save_intent", attempted_state="FIRST_SAVE_INTENT")
    contract = ACTION_RESULT_CONTRACTS["first_save_intent"]["FIRST_SAVE_INTENT"]
    envelope["postconditions"] = {name: True for name in contract.required_postconditions}
    envelope["evidence"]["observations"]["first_save_intent_handshake"] = {
        "same_handshake": True, "handshake_id": "forged", "gate_outcome": "admitted"}
    with pytest.raises(ActionResultContractError, match="NATIVE_GATE_PASSIVE_EVIDENCE_MISSING"):
        validate_action_result_envelope(envelope, execution_mode="batch_draft_save",
            expected_execution_payload=_path_a_execution_payload())
