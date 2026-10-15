from copy import deepcopy
import hashlib
import json

from src.execution.canonical_receipt import FieldReadback, ReceiptPhase, SaveProof, SaveProofKind, SaveReceipt
from src.execution.native_gate_evidence import NATIVE_GATE_URL, ReviewedNativeGateResponse


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode("utf-8")).hexdigest()


def _network(kind, body, at):
    identity = {"kind": kind, "url": NATIVE_GATE_URL, "method": "POST",
        "body_sha256": digest(body), "observed_at": at}
    if kind == "response":
        identity["status"] = 200
    return {**{key: value for key, value in identity.items() if key != "kind"},
        "body": body, "evidence_id": f"dxm-network-{kind}:" + digest(identity)}


def _proof(**fields):
    return SaveProof(**{"file_path": None, "network_url": None, "network_method": None,
        "network_status": None, **fields})


def native_gate_case():
    target = digest({"synthetic_product": "gate-test"})
    proof_fields = {"proven": True, "source": "visible_production_runtime", "target_hash": target}
    save_url = "https://www.dianxiaomi.com/api/smtProduct/add.json"
    proofs = {
        SaveProofKind.NETWORK_REQUEST: _proof(proof_kind=SaveProofKind.NETWORK_REQUEST,
            **proof_fields, network_url=save_url, network_method="POST", body_sha256="a" * 64,
            timestamp="2026-08-31T00:00:11Z", evidence_id="save1-request"),
        SaveProofKind.NETWORK_RESPONSE: _proof(proof_kind=SaveProofKind.NETWORK_RESPONSE,
            **proof_fields, network_url=save_url, network_method="POST", network_status=200,
            body_sha256="b" * 64, timestamp="2026-08-31T00:00:12Z", evidence_id="save1-response",
            business_success=True, business_code=0, business_message="保存成功"),
        SaveProofKind.PAGE_SUCCESS_SCREENSHOT: _proof(proof_kind=SaveProofKind.PAGE_SUCCESS_SCREENSHOT,
            **proof_fields, file_path="/synthetic/gate/save1.png", body_sha256="c" * 64,
            timestamp="2026-08-31T00:00:13Z", evidence_id="save1-page", page_kind="editor", page_success=True),
        SaveProofKind.UNPUBLISHED_STATUS: _proof(proof_kind=SaveProofKind.UNPUBLISHED_STATUS,
            **proof_fields, body_sha256="d" * 64, timestamp="2026-08-31T00:00:14Z",
            evidence_id="save1-unpublished", unpublished=True, independent=True),
    }
    receipt = SaveReceipt(save_phase=ReceiptPhase.PHASE_1_FIRST_SAVE,
        save_lease_id="save1-lease", action_grant_id="save1-grant", mutation_id="save1-mutation",
        ledger_entry_id=1, target_hash=target, dispatched_at="2026-08-31T00:00:10Z",
        completed_at="2026-08-31T00:00:14Z", physical_mutation_count=1, publish_request_count=0,
        published=False, save_result_ok=True, proofs=proofs,
        field_readbacks=[FieldReadback(field_key="title", field_label="标题", source="exact_control",
            before_value="Before", after_value="After", readback_proven=True, timestamp="2026-08-31T00:00:13Z")])
    admitted, rejected = {"synthetic_native_decision": "admitted"}, {"synthetic_native_decision": "rejected"}
    contract = ReviewedNativeGateResponse("synthetic-only-v1", "f" * 64, digest(admitted), digest(rejected))
    request = _network("request", {"synthetic_product": "gate-test"}, "2026-08-31T00:00:15Z")
    response = _network("response", admitted, "2026-08-31T00:00:16Z")
    response["request_evidence_id"] = request["evidence_id"]
    handshake = {"handshake_id": "gate-handshake", "same_handshake": True,
        "physical_mutation_count": 1, "publish_request_count": 0,
        "network_audit": {"save_request_count": 1, "mutation_request_count": 1,
            "other_mutation_request_count": 0, "publish_request_count": 0, "complete": True, "window_closed": True},
        "first_save_intent": {"observed": True, "handshake_id": "gate-handshake", "event_id": "intent",
            "observed_at": "2026-08-31T00:00:10Z"},
        "open_semi_managed_editor": {"observed": True, "handshake_id": "gate-handshake", "event_id": "open-entry",
            "observed_at": "2026-08-31T00:00:20Z", "field_readbacks": [item.to_dict() for item in receipt.field_readbacks]},
        "pre_dispatch_page": {"target_identity_sha256": target}, "post_dispatch_page": {"target_identity_sha256": target},
        "mutation_authorization": {"mutation_id": "save1-mutation", "ok": True, "executed": True,
            "mutation_action": "first_save_intent", "mutation_status": "DISPATCHED"},
        "network_save_result": {"ok": True, "receipt_complete": True, "receipt_count": 1,
            "url": save_url, "method": "POST", "status": 200, "code": 0,
            "request_observed_at": "2026-08-31T00:00:11Z", "response_observed_at": "2026-08-31T00:00:12Z",
            "request_evidence_id": "save1-request", "response_evidence_id": "save1-response",
            "request_body_sha256": "a" * 64, "response_body_sha256": "b" * 64},
        "save1_receipt": receipt.to_persisted_dict(),
        "native_gate_evidence": {"schema": "dxm.native_gate_evidence.v1", "source": "passive_native_network",
            "request_initiator": "native_page", "replayed": False, "causal_action": "OPEN_SEMI_MANAGED_EDITOR",
            "handshake_id": "gate-handshake", "causal_event_id": "open-entry", "browser_session_id": "unit-session",
            "target_identity_sha256": target, "response_contract_id": contract.contract_id,
            "response_contract_source_sha256": contract.source_sha256, "request": request, "response": response}}
    return deepcopy(handshake), contract
