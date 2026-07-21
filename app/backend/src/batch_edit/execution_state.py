from __future__ import annotations

import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

from src.batch_edit.scope_contract import canonical_sha256


BATCH_EXECUTION_STATUSES = frozenset(
    {"draft", "approved", "running", "stop_requested", "completed", "stopped"}
)
ITEM_EXECUTION_STATUSES = frozenset(
    {"pending", "running", "succeeded", "isolated_pre_save_no_write", "stopped_uncertain"}
)
ITEM_CONTINUE_TERMINAL_STATUSES = frozenset({"succeeded", "isolated_pre_save_no_write"})
ITEM_TERMINAL_STATUSES = frozenset(
    {"succeeded", "isolated_pre_save_no_write", "stopped_uncertain"}
)

START_CONTEXT_SCHEMA = "dxm_edit_batch_start_context.v1"
ITEM_GRANT_SCHEMA = "dxm_edit_batch_item_grant.v1"
ITEM_GRANT_CONSUMPTION_SCHEMA = "dxm_edit_batch_item_grant_consumption.v1"
ITEM_OUTCOME_DECISION_SCHEMA = "dxm_edit_batch_item_outcome_decision.v1"
BATCH_ITEM_GRANT_MAX_TTL_SECONDS = 60 * 60

_APPROVAL_CONTEXT_KEYS = {
    "schema_version",
    "batch",
    "scope",
    "template",
    "policy",
    "ordered_targets",
    "store_identity",
    "runtime_identity",
    "read_attestation",
    "approved_by",
    "confirmation",
    "lease_id",
    "issued_at",
    "expires_at",
    "fingerprint",
}

_START_CONTEXT_KEYS = {
    "schema_version",
    "authorization_state",
    "batch_id",
    "approval_lease_id",
    "approval_context_fingerprint",
    "approval_expires_at",
    "scope_digest",
    "template_digest",
    "policy_digest",
    "ordered_target_digest",
    "runtime_identity",
    "browser_session_id",
    "git_head",
    "store_identity",
    "page_identity",
}
_ITEM_GRANT_KEYS = {
    "schema_version",
    "batch_id",
    "item_id",
    "ordinal",
    "approval_lease_id",
    "approval_context_fingerprint",
    "approval_expires_at",
    "scope_digest",
    "template_digest",
    "policy_digest",
    "target_identity_sha256",
    "store_identity",
    "runtime_identity",
    "browser_session_id",
    "git_head",
    "page_identity",
    "mutation_scope_id",
    "grant_lease_id",
    "issued_at",
    "expires_at",
    "nonce_hash",
    "fingerprint",
}
_ITEM_GRANT_CONSUMPTION_KEYS = {
    "schema_version",
    "batch_id",
    "item_id",
    "ordinal",
    "from_status",
    "to_status",
    "grant_lease_id",
    "grant_fingerprint",
    "mutation_scope_id",
    "consumed_nonce_hash",
    "retry_allowed",
}


@dataclass(frozen=True)
class EditBatchExecutionTransitionResult:
    applied: bool
    idempotent: bool
    reason_code: str
    batch: dict[str, Any] | None
    item: dict[str, Any] | None = None


class EditBatchExecutionPersistenceError(ValueError):
    def __init__(self, reason_code: str, detail: str) -> None:
        self.reason_code = reason_code
        super().__init__(detail)


def normalize_approval_for_storage(approval: Any) -> dict[str, Any]:
    """Return only the hashed approval material that may cross the DB boundary."""
    if not isinstance(approval, dict):
        _reject("APPROVAL_STORAGE_INVALID", "approval must be an object")
    token_hash = _sha256_text(approval.get("token_hash"), "approval token hash")
    lease_id = _canonical_text(approval.get("lease_id"), "approval lease id")
    context = _exact_object(approval.get("context"), _APPROVAL_CONTEXT_KEYS, "approval context")
    if context["schema_version"] != "dxm_edit_batch_approval_context.v1":
        _reject("APPROVAL_STORAGE_SCHEMA_INVALID", "approval context schema is unsupported")
    if context["confirmation"] != "CONFIRM_DXM_BATCH_SAVE_ONLY":
        _reject("APPROVAL_STORAGE_CONFIRMATION_INVALID", "approval confirmation is invalid")
    if context.get("lease_id") != lease_id:
        _reject("APPROVAL_STORAGE_BINDING_INVALID", "approval lease binding is inconsistent")
    fingerprint = _sha256_text(context.get("fingerprint"), "approval context fingerprint")
    unsigned_context = dict(context)
    unsigned_context.pop("fingerprint", None)
    if not hmac.compare_digest(fingerprint, canonical_sha256(unsigned_context)):
        _reject("APPROVAL_STORAGE_BINDING_INVALID", "approval context fingerprint is invalid")
    _reject_raw_secret_keys(context)
    return {
        "token_hash": token_hash,
        "lease_id": lease_id,
        "context": context,
    }


def normalize_start_context_for_storage(
    start_context: Any,
    *,
    batch_row: Mapping[str, Any],
    approval_context: Mapping[str, Any],
    consumed_at: str,
) -> dict[str, Any]:
    context = _exact_object(start_context, _START_CONTEXT_KEYS, "start context")
    if context["schema_version"] != START_CONTEXT_SCHEMA:
        _reject("START_CONTEXT_SCHEMA_INVALID", "start context schema is unsupported")
    if context["authorization_state"] != "approval_token_consumed":
        _reject("START_CONTEXT_NOT_CONSUMED", "start context did not consume the approval token")
    consumed = _timestamp(consumed_at, "approval consumed_at")
    issued_at = _timestamp(approval_context.get("issued_at"), "approval issued_at")
    expires_at = _timestamp(approval_context.get("expires_at"), "approval expires_at")
    if issued_at >= expires_at or (expires_at - issued_at).total_seconds() > 5 * 60:
        _reject("APPROVAL_STORAGE_INTERVAL_INVALID", "approval lease interval is invalid")
    if consumed < issued_at or consumed >= expires_at:
        _reject("APPROVAL_STORAGE_EXPIRED", "approval must be consumed inside its start window")
    if approval_context.get("batch") != {
        "id": int(batch_row["id"]),
        "schema_version": batch_row["schema_version"],
        "required_status": "draft",
    }:
        _reject("APPROVAL_STORAGE_BINDING_INVALID", "approval context is bound to another batch")
    if approval_context.get("scope") != {
        "snapshot_id": int(batch_row["scope_snapshot_id"]),
        "snapshot_digest": batch_row["scope_snapshot_digest"],
    }:
        _reject("APPROVAL_STORAGE_BINDING_INVALID", "approval scope binding is inconsistent")
    if approval_context.get("template") != {
        "id": int(batch_row["template_id"]),
        "snapshot_digest": batch_row["template_snapshot_digest"],
    }:
        _reject("APPROVAL_STORAGE_BINDING_INVALID", "approval template binding is inconsistent")
    if approval_context.get("policy") != {"digest": batch_row["policy_digest"]}:
        _reject("APPROVAL_STORAGE_BINDING_INVALID", "approval policy binding is inconsistent")
    ordered_targets = approval_context.get("ordered_targets")
    if not isinstance(ordered_targets, dict) or ordered_targets.get("digest") != context.get(
        "ordered_target_digest"
    ):
        _reject("APPROVAL_STORAGE_BINDING_INVALID", "approval target order binding is inconsistent")
    expected = {
        "batch_id": int(batch_row["id"]),
        "approval_lease_id": approval_context.get("lease_id"),
        "approval_context_fingerprint": approval_context.get("fingerprint"),
        "approval_expires_at": approval_context.get("expires_at"),
        "scope_digest": batch_row["scope_snapshot_digest"],
        "template_digest": batch_row["template_snapshot_digest"],
        "policy_digest": batch_row["policy_digest"],
    }
    if any(context.get(key) != value for key, value in expected.items()):
        _reject("START_CONTEXT_BINDING_INVALID", "start context does not match frozen approval facts")
    scope_snapshot = _json_column_object(batch_row.get("scope_snapshot_json"), "scope snapshot")
    scope_runtime = scope_snapshot.get("runtime_identity")
    if (
        context.get("runtime_identity") != approval_context.get("runtime_identity")
        or context.get("runtime_identity") != scope_runtime
        or context.get("store_identity") != approval_context.get("store_identity")
        or context.get("store_identity") != scope_snapshot.get("store_identity")
        or context.get("page_identity") != scope_snapshot.get("page_identity")
        or not isinstance(scope_runtime, dict)
        or context.get("browser_session_id") != scope_runtime.get("browser_session_id")
        or context.get("git_head") != scope_runtime.get("git_head")
    ):
        _reject("START_CONTEXT_LIVE_BINDING_INVALID", "start context live bindings are inconsistent")
    for key in (
        "approval_context_fingerprint",
        "scope_digest",
        "template_digest",
        "policy_digest",
        "ordered_target_digest",
    ):
        _sha256_text(context.get(key), key)
    _reject_raw_secret_keys(context)
    return context


def normalize_item_grant_for_storage(
    grant: Any,
    *,
    batch_row: Mapping[str, Any],
    item_row: Mapping[str, Any],
    start_context: Mapping[str, Any],
) -> dict[str, Any]:
    value = _exact_object(grant, _ITEM_GRANT_KEYS, "item grant")
    if value["schema_version"] != ITEM_GRANT_SCHEMA:
        _reject("ITEM_GRANT_SCHEMA_INVALID", "item grant schema is unsupported")
    unsigned = dict(value)
    fingerprint = _sha256_text(unsigned.pop("fingerprint"), "grant fingerprint")
    if not hmac.compare_digest(fingerprint, canonical_sha256(unsigned)):
        _reject("ITEM_GRANT_FINGERPRINT_INVALID", "item grant fingerprint is invalid")
    expected = {
        "batch_id": int(batch_row["id"]),
        "item_id": int(item_row["id"]),
        "ordinal": int(item_row["ordinal"]),
        "approval_lease_id": start_context.get("approval_lease_id"),
        "approval_context_fingerprint": start_context.get("approval_context_fingerprint"),
        "approval_expires_at": start_context.get("approval_expires_at"),
        "scope_digest": batch_row["scope_snapshot_digest"],
        "template_digest": batch_row["template_snapshot_digest"],
        "policy_digest": batch_row["policy_digest"],
        "target_identity_sha256": item_row["target_identity_sha256"],
        "store_identity": start_context.get("store_identity"),
        "runtime_identity": start_context.get("runtime_identity"),
        "browser_session_id": start_context.get("browser_session_id"),
        "git_head": start_context.get("git_head"),
        "page_identity": start_context.get("page_identity"),
    }
    if any(value.get(key) != expected_value for key, expected_value in expected.items()):
        _reject("ITEM_GRANT_BINDING_INVALID", "item grant does not match persisted execution facts")
    issued_at = _timestamp(value.get("issued_at"), "grant issued_at")
    expires_at = _timestamp(value.get("expires_at"), "grant expires_at")
    if (
        issued_at >= expires_at
        or (expires_at - issued_at).total_seconds() > BATCH_ITEM_GRANT_MAX_TTL_SECONDS
    ):
        _reject("ITEM_GRANT_INTERVAL_INVALID", "item grant interval is invalid")
    _sha256_text(value.get("nonce_hash"), "grant nonce hash")
    _sha256_text(value.get("mutation_scope_id"), "mutation scope id")
    _canonical_text(value.get("grant_lease_id"), "grant lease id")
    _reject_raw_secret_keys(value)
    return value


def normalize_item_grant_consumption_for_storage(
    consumption: Any,
    *,
    batch_row: Mapping[str, Any],
    item_row: Mapping[str, Any],
    stored_grant: Mapping[str, Any],
) -> dict[str, Any]:
    value = _exact_object(consumption, _ITEM_GRANT_CONSUMPTION_KEYS, "grant consumption")
    if value["schema_version"] != ITEM_GRANT_CONSUMPTION_SCHEMA:
        _reject("ITEM_GRANT_CONSUMPTION_SCHEMA_INVALID", "grant consumption schema is unsupported")
    if value["from_status"] != "pending" or value["to_status"] != "running":
        _reject("ITEM_GRANT_CONSUMPTION_TRANSITION_INVALID", "grant consumption transition is invalid")
    if value["retry_allowed"] is not False:
        _reject("ITEM_GRANT_RETRY_FORBIDDEN", "batch item grants cannot be retried")
    expected = {
        "batch_id": int(batch_row["id"]),
        "item_id": int(item_row["id"]),
        "ordinal": int(item_row["ordinal"]),
        "grant_lease_id": stored_grant.get("grant_lease_id"),
        "grant_fingerprint": stored_grant.get("fingerprint"),
        "mutation_scope_id": stored_grant.get("mutation_scope_id"),
        "consumed_nonce_hash": stored_grant.get("nonce_hash"),
    }
    if any(value.get(key) != expected_value for key, expected_value in expected.items()):
        _reject("ITEM_GRANT_CONSUMPTION_BINDING_INVALID", "grant consumption does not match stored grant")
    _reject_raw_secret_keys(value)
    return value


def derive_execution_item_grant(
    batch: Any,
    *,
    start_context: Any,
    now: datetime,
    grant_lease_id: str,
    one_time_nonce: str,
    ttl_seconds: int,
) -> dict[str, Any]:
    """Derive a per-item grant after start; approval expiry remains historical binding only."""
    from src.batch_edit.execution_contract import derive_next_item_grant

    current = _aware_datetime(now, "grant now")
    if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int):
        _reject("ITEM_GRANT_TTL_INVALID", "item grant TTL must be an integer")
    if ttl_seconds < 60 or ttl_seconds > BATCH_ITEM_GRANT_MAX_TTL_SECONDS:
        _reject("ITEM_GRANT_TTL_INVALID", "item grant TTL is outside the supported interval")
    if not isinstance(start_context, dict):
        _reject("START_CONTEXT_INVALID", "start context is missing")
    _timestamp(start_context.get("approval_expires_at"), "approval expires_at")
    issued = derive_next_item_grant(
        batch,
        start_context=start_context,
        now=current,
        grant_lease_id=grant_lease_id,
        one_time_nonce=one_time_nonce,
    )
    grant = _exact_object(issued.get("grant"), _ITEM_GRANT_KEYS, "item grant")
    grant["issued_at"] = current.isoformat()
    grant["expires_at"] = (current + timedelta(seconds=ttl_seconds)).isoformat()
    unsigned = dict(grant)
    unsigned.pop("fingerprint", None)
    grant["fingerprint"] = canonical_sha256(unsigned)
    return {"grant": grant, "nonce": issued.get("nonce")}


def validate_execution_item_grant_consumption(
    grant: Any,
    *,
    raw_nonce: str,
    now: datetime,
    request: Any,
    consumed_nonce_hashes: Any,
) -> dict[str, Any]:
    """Validate the live item lease without reusing the expired start-only approval window."""
    from src.batch_edit.execution_contract import validate_and_consume_item_grant

    canonical_grant = _exact_object(grant, _ITEM_GRANT_KEYS, "item grant")
    current = _aware_datetime(now, "grant consumption now")
    issued_at = _timestamp(canonical_grant.get("issued_at"), "grant issued_at")
    expires_at = _timestamp(canonical_grant.get("expires_at"), "grant expires_at")
    if issued_at >= expires_at:
        _reject("ITEM_GRANT_INTERVAL_INVALID", "item grant interval is invalid")
    if current < issued_at:
        _reject("ITEM_GRANT_NOT_YET_VALID", "item grant is not yet valid")
    if current >= expires_at:
        _reject("ITEM_GRANT_EXPIRED", "item grant has expired")
    if (expires_at - issued_at).total_seconds() > BATCH_ITEM_GRANT_MAX_TTL_SECONDS:
        _reject("ITEM_GRANT_INTERVAL_INVALID", "item grant interval is invalid")
    _timestamp(canonical_grant.get("approval_expires_at"), "approval expires_at")
    return validate_and_consume_item_grant(
        canonical_grant,
        raw_nonce=raw_nonce,
        now=current,
        request=request,
        consumed_nonce_hashes=consumed_nonce_hashes,
    )


def normalize_item_outcome_for_storage(
    decision: Any,
    evidence: Any,
    *,
    batch_id: int,
    item_id: int,
    ordinal: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    value = _canonical_object(decision, "item outcome decision")
    if value.get("schema_version") != ITEM_OUTCOME_DECISION_SCHEMA:
        _reject("ITEM_OUTCOME_DECISION_SCHEMA_INVALID", "outcome decision schema is unsupported")
    transition = value.get("item_transition")
    if not isinstance(transition, dict) or transition != {
        "batch_id": batch_id,
        "item_id": item_id,
        "ordinal": ordinal,
        "from_status": "running",
        "to_status": transition.get("to_status") if isinstance(transition, dict) else None,
    }:
        _reject("ITEM_OUTCOME_TRANSITION_INVALID", "outcome transition does not match the running item")
    classification = value.get("classification")
    mapping = {
        "SUCCEEDED": ("succeeded", True, False),
        "ISOLATED_PRE_SAVE_NO_WRITE": ("isolated_pre_save_no_write", True, False),
        "STOPPED_UNCERTAIN": ("stopped_uncertain", False, True),
    }
    expected = mapping.get(classification)
    if expected is None:
        _reject("ITEM_OUTCOME_CLASSIFICATION_INVALID", "outcome classification is unsupported")
    target_status, expected_continue, requires_stop = expected
    if (
        transition.get("to_status") != target_status
        or value.get("continue_batch") is not expected_continue
        or value.get("retry_allowed") is not False
    ):
        _reject("ITEM_OUTCOME_TRANSITION_INVALID", "outcome decision transition is inconsistent")
    batch_transition = value.get("batch_transition")
    if requires_stop:
        if batch_transition != {"from_status": "running", "to_status": "stopped"}:
            _reject("ITEM_OUTCOME_TRANSITION_INVALID", "uncertain outcome must stop the batch")
    elif batch_transition is not None:
        _reject("ITEM_OUTCOME_TRANSITION_INVALID", "safe item outcome cannot force a batch transition")
    reason_code = _canonical_text(value.get("reason_code"), "outcome reason code")
    canonical_evidence = _canonical_object(evidence, "item outcome evidence")
    _reject_raw_secret_keys(value)
    _reject_raw_secret_keys(canonical_evidence)
    return value, canonical_evidence


def normalize_action_results_for_storage(action_results: Any) -> list[dict[str, Any]]:
    if not isinstance(action_results, list):
        _reject("ACTION_RESULTS_INVALID", "action results must be a list")
    try:
        cloned = json.loads(
            json.dumps(
                action_results,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        )
    except (TypeError, ValueError) as exc:
        raise EditBatchExecutionPersistenceError(
            "CANONICAL_JSON_REQUIRED", "action results must be canonical JSON"
        ) from exc
    if any(not isinstance(item, dict) for item in cloned):
        _reject("ACTION_RESULTS_INVALID", "each action result must be an object")
    _reject_raw_secret_keys(cloned)
    return cloned


def normalize_execution_evidence_for_storage(evidence: Any) -> dict[str, Any]:
    value = _canonical_object(evidence, "execution evidence")
    _reject_raw_secret_keys(value)
    return value


def build_public_progress(items: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = list(items)
    counts = {status: 0 for status in ITEM_EXECUTION_STATUSES}
    current_ordinal: int | None = None
    for item in rows:
        status = str(item.get("status") or "")
        if status in counts:
            counts[status] += 1
        if status == "running" and current_ordinal is None:
            current_ordinal = int(item["ordinal"])
    total = len(rows)
    finished = counts["succeeded"] + counts["isolated_pre_save_no_write"] + counts["stopped_uncertain"]
    return {
        "total": total,
        "completed": finished,
        "succeeded": counts["succeeded"],
        "isolated": counts["isolated_pre_save_no_write"],
        "pending": counts["pending"],
        "running": counts["running"],
        "stopped": counts["stopped_uncertain"],
        "current_ordinal": current_ordinal,
        "percent": int((finished * 100) / total) if total else 0,
    }


def build_public_execution(batch_row: Mapping[str, Any]) -> dict[str, Any]:
    state = str(batch_row.get("status") or "")
    return {
        "state": state,
        "started_at": batch_row.get("started_at"),
        "stop_requested_at": batch_row.get("stop_requested_at"),
        "stopped_at": batch_row.get("stopped_at"),
        "completed_at": batch_row.get("completed_at"),
        "manual_review_required": bool(batch_row.get("manual_review_required")),
        "reason_code": batch_row.get("execution_reason_code"),
    }


def build_public_item_outcome(item_row: Mapping[str, Any]) -> dict[str, Any] | None:
    classification = item_row.get("outcome_classification")
    if not classification:
        return None
    return {
        "classification": classification,
        "reason_code": item_row.get("outcome_reason_code"),
        "finished_at": item_row.get("finished_at"),
        "manual_review_required": bool(item_row.get("manual_review_required")),
    }


def _exact_object(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        _reject("EXACT_OBJECT_REQUIRED", f"{label} has an unexpected shape")
    return _canonical_object(value, label)


def _canonical_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _reject("CANONICAL_OBJECT_REQUIRED", f"{label} must be an object")
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        cloned = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise EditBatchExecutionPersistenceError(
            "CANONICAL_JSON_REQUIRED", f"{label} must be canonical JSON"
        ) from exc
    if not isinstance(cloned, dict):
        _reject("CANONICAL_OBJECT_REQUIRED", f"{label} must be an object")
    return cloned


def _canonical_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        _reject("CANONICAL_TEXT_REQUIRED", f"{label} must be non-empty canonical text")
    return value


def _sha256_text(value: Any, label: str) -> str:
    text = _canonical_text(value, label).upper()
    if len(text) != 64 or any(char not in "0123456789ABCDEF" for char in text):
        _reject("SHA256_REQUIRED", f"{label} must be a SHA-256 digest")
    return text


def _timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        _reject("TIMESTAMP_INVALID", f"{label} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EditBatchExecutionPersistenceError(
            "TIMESTAMP_INVALID", f"{label} is invalid"
        ) from exc
    return _aware_datetime(parsed, label)


def _aware_datetime(value: Any, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        _reject("TIMESTAMP_INVALID", f"{label} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _json_column_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, str) or not value:
        _reject("PERSISTED_JSON_INVALID", f"{label} is missing")
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError) as exc:
        raise EditBatchExecutionPersistenceError(
            "PERSISTED_JSON_INVALID", f"{label} is invalid"
        ) from exc
    if not isinstance(decoded, dict):
        _reject("PERSISTED_JSON_INVALID", f"{label} must be an object")
    return decoded


def _reject_raw_secret_keys(value: Any) -> None:
    if isinstance(value, dict):
        forbidden = {"token", "approval_token", "nonce", "raw_nonce", "one_time_nonce"}
        for key, child in value.items():
            if str(key).lower() in forbidden:
                _reject("RAW_AUTHORIZATION_SECRET_FORBIDDEN", "raw authorization secrets cannot be persisted")
            _reject_raw_secret_keys(child)
    elif isinstance(value, list):
        for child in value:
            _reject_raw_secret_keys(child)


def _reject(reason_code: str, detail: str) -> None:
    raise EditBatchExecutionPersistenceError(reason_code, detail)
