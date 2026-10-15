"""原生门只消费同握手的被动网络事实，不发请求、不推断资格。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.execution.canonical_receipt import ReceiptPhase, ReceiptValidationError, SaveProofKind, SaveReceipt
from src.services.structured_logging import get_logger, log_event


_LOGGER = get_logger("native_gate.evidence")

NATIVE_GATE_URL = "https://www.dianxiaomi.com/api/smtProduct/verifyPopChoiceShop.json"


@dataclass(frozen=True)
class ReviewedNativeGateResponse:
    contract_id: str
    source_sha256: str
    admitted_response_sha256: str
    rejected_response_sha256: str


# 尚无已审阅的真实响应语义；HTTP 200、code=0 和页面跳转均不能补齐此合同。
REVIEWED_NATIVE_GATE_RESPONSES: tuple[ReviewedNativeGateResponse, ...] = ()


@dataclass(frozen=True)
class NativeGateJoin:
    admitted: bool
    reason_code: str
    summary: dict[str, Any]


class NativeGateEvidenceError(ValueError):
    pass


def _sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise NativeGateEvidenceError(reason)


def _timestamp(value: Any) -> datetime:
    _require(isinstance(value, str), "NATIVE_GATE_TIMESTAMP_INVALID")
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    _require(stamp.utcoffset() is not None, "NATIVE_GATE_TIMESTAMP_INVALID")
    return stamp


def _network_event(raw: Any, kind: str) -> dict[str, Any]:
    _require(isinstance(raw, Mapping), "NATIVE_GATE_RESPONSE_MISSING")
    event = dict(raw)
    _require(event.get("url") == NATIVE_GATE_URL and event.get("method") == "POST",
        "NATIVE_GATE_ENDPOINT_INVALID")
    _require(isinstance(event.get("body"), Mapping), "NATIVE_GATE_RESPONSE_MISSING")
    digest = _sha(event["body"])
    _require(event.get("body_sha256") == digest, "NATIVE_GATE_BODY_HASH_MISMATCH")
    identity = {"kind": kind, "url": event["url"], "method": event["method"],
        "body_sha256": digest, "observed_at": event.get("observed_at")}
    if kind == "response":
        _require(type(event.get("status")) is int and 200 <= event["status"] < 300,
            "NATIVE_GATE_HTTP_REJECTED")
        identity["status"] = event["status"]
    _timestamp(event.get("observed_at"))
    _require(event.get("evidence_id") == f"dxm-network-{kind}:" + _sha(identity),
        "NATIVE_GATE_NETWORK_IDENTITY_MISMATCH")
    return event


def _verified_save1(handshake: Mapping[str, Any], target_sha: str) -> None:
    raw = handshake.get("save1_receipt")
    _require(isinstance(raw, Mapping) and bool(raw.get("canonical_save_receipt_sha256")),
        "NATIVE_GATE_SAVE1_NOT_CLOSED")
    try:
        receipt = SaveReceipt.from_dict(raw)
    except (ReceiptValidationError, ValueError, TypeError, KeyError) as exc:
        raise NativeGateEvidenceError("NATIVE_GATE_SAVE1_NOT_CLOSED") from exc
    authorization = handshake.get("mutation_authorization", {})
    _require(isinstance(authorization, Mapping) and authorization.get("ok") is True
        and authorization.get("executed") is True and authorization.get("mutation_action") == "first_save_intent"
        and authorization.get("mutation_status") == "DISPATCHED", "NATIVE_GATE_SAVE1_NOT_CLOSED")
    _require(receipt.save_phase == ReceiptPhase.PHASE_1_FIRST_SAVE
        and str(receipt.target_hash).casefold() == target_sha.casefold()
        and receipt.mutation_id == authorization.get("mutation_id"),
        "NATIVE_GATE_SAVE1_IDENTITY_MISMATCH")
    network = handshake.get("network_save_result")
    audit = handshake.get("network_audit", {})
    _require(isinstance(network, Mapping) and network.get("ok") is True
        and network.get("receipt_complete") is True and type(network.get("receipt_count")) is int
        and network["receipt_count"] == 1 and network.get("code") in (0, "0")
        and isinstance(audit, Mapping) and audit.get("complete") is True and audit.get("window_closed") is True
        and all(type(audit.get(key)) is int and audit[key] == expected for key, expected in (
            ("save_request_count", 1), ("mutation_request_count", 1),
            ("other_mutation_request_count", 0), ("publish_request_count", 0)))
        and type(handshake.get("physical_mutation_count")) is int and handshake["physical_mutation_count"] == 1
        and type(handshake.get("publish_request_count")) is int and handshake["publish_request_count"] == 0,
        "NATIVE_GATE_SAVE1_NOT_CLOSED")
    for kind, prefix in ((SaveProofKind.NETWORK_REQUEST, "request"),
            (SaveProofKind.NETWORK_RESPONSE, "response")):
        proof = receipt.proofs[kind]
        _require(proof.evidence_id == network.get(f"{prefix}_evidence_id")
            and str(proof.body_sha256).casefold() == str(network.get(f"{prefix}_body_sha256")).casefold()
            and proof.network_url == network.get("url") and proof.network_method == network.get("method")
            and proof.timestamp == network.get(f"{prefix}_observed_at"),
            "NATIVE_GATE_SAVE1_NETWORK_MISMATCH")
    _require(receipt.proofs[SaveProofKind.NETWORK_RESPONSE].network_status == network.get("status"),
        "NATIVE_GATE_SAVE1_NETWORK_MISMATCH")


def _validate(handshake: Mapping[str, Any], expected_browser_session_id: str | None,
        contracts: tuple[ReviewedNativeGateResponse, ...]) -> str:
    gate = handshake.get("native_gate_evidence")
    _require(isinstance(gate, Mapping), "NATIVE_GATE_PASSIVE_EVIDENCE_MISSING")
    opened = handshake.get("open_semi_managed_editor", {})
    intent = handshake.get("first_save_intent", {})
    handshake_id = handshake.get("handshake_id")
    _require(bool(handshake_id) and handshake.get("same_handshake") is True
        and opened.get("observed") is True and intent.get("observed") is True
        and opened.get("handshake_id") == intent.get("handshake_id") == handshake_id
        and gate.get("handshake_id") == handshake_id
        and bool(opened.get("event_id")) and gate.get("causal_event_id") == opened["event_id"],
        "NATIVE_GATE_HANDSHAKE_MISMATCH")
    _require(gate.get("schema") == "dxm.native_gate_evidence.v1"
        and gate.get("source") == "passive_native_network"
        and gate.get("request_initiator") == "native_page"
        and gate.get("causal_action") == "OPEN_SEMI_MANAGED_EDITOR"
        and gate.get("replayed") is False, "NATIVE_GATE_NOT_PASSIVE")
    _require(bool(expected_browser_session_id)
        and gate.get("browser_session_id") == expected_browser_session_id,
        "NATIVE_GATE_SESSION_MISMATCH")
    pre_page, post_page = handshake.get("pre_dispatch_page", {}), handshake.get("post_dispatch_page", {})
    target_sha = pre_page.get("target_identity_sha256")
    _require(isinstance(target_sha, str) and len(target_sha) == 64
        and post_page.get("target_identity_sha256") == gate.get("target_identity_sha256") == target_sha,
        "NATIVE_GATE_TARGET_MISMATCH")
    request, response = _network_event(gate.get("request"), "request"), _network_event(gate.get("response"), "response")
    _require(response.get("request_evidence_id") == request["evidence_id"]
        and _timestamp(request["observed_at"]) <= _timestamp(response["observed_at"]),
        "NATIVE_GATE_NETWORK_CAUSALITY_INVALID")
    _require(_timestamp(intent.get("observed_at")) <= _timestamp(request["observed_at"])
        <= _timestamp(response["observed_at"]) <= _timestamp(opened.get("observed_at")),
        "NATIVE_GATE_OUTSIDE_HANDSHAKE")
    reviewed = [contract for contract in contracts if isinstance(contract, ReviewedNativeGateResponse)
        and contract.contract_id == gate.get("response_contract_id")
        and contract.source_sha256 == gate.get("response_contract_source_sha256")]
    _require(len(reviewed) == 1 and len(reviewed[0].source_sha256) == 64,
        "NATIVE_GATE_RESPONSE_CONTRACT_NOT_REVIEWED")
    body_hash, contract = _sha(response["body"]), reviewed[0]
    _require(contract.admitted_response_sha256 != contract.rejected_response_sha256,
        "NATIVE_GATE_RESPONSE_CONTRACT_INVALID")
    if body_hash == contract.rejected_response_sha256:
        return "rejected"
    _require(body_hash == contract.admitted_response_sha256, "NATIVE_GATE_RESPONSE_SEMANTICS_UNKNOWN")
    _verified_save1(handshake, target_sha)
    return "admitted"


def join_native_gate_evidence(handshake: Mapping[str, Any], *, expected_browser_session_id: str | None,
        reviewed_contracts: tuple[ReviewedNativeGateResponse, ...] = REVIEWED_NATIVE_GATE_RESPONSES) -> NativeGateJoin:
    opened = handshake.get("open_semi_managed_editor")
    opened = opened if isinstance(opened, Mapping) else {}
    audit = handshake.get("network_audit")
    audit = audit if isinstance(audit, Mapping) else {}
    summary = {"gate_outcome": "unknown", "semi_entry_triggered": opened.get("observed") is True,
        "same_handshake": False, "handshake_id": handshake.get("handshake_id"),
        "save1_verified": False, "exactly_one_save_request":
        type(handshake.get("physical_mutation_count")) is int and handshake["physical_mutation_count"] == 1
        and type(audit.get("save_request_count")) is int and audit["save_request_count"] == 1}
    try:
        outcome = _validate(handshake, expected_browser_session_id, reviewed_contracts)
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        reason = str(exc) if isinstance(exc, NativeGateEvidenceError) else "NATIVE_GATE_EVIDENCE_INVALID"
        log_event(_LOGGER, "native_gate_evidence_rejected", level="WARNING", reason_code=reason)
        return NativeGateJoin(False, reason, summary)
    summary.update(gate_outcome=outcome, same_handshake=True, save1_verified=outcome == "admitted")
    return NativeGateJoin(outcome == "admitted", "OK" if outcome == "admitted" else "NATIVE_GATE_REJECTED", summary)
