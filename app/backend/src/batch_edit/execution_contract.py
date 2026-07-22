from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any

from src.batch_edit.batch_contract import (
    BATCH_SCHEMA,
    BatchContractError,
    freeze_scope_snapshot,
    freeze_template_bundle,
    frozen_batch_policy,
)
from src.batch_edit.scope_contract import canonical_sha256
from src.execution.browser_agent_protocol import build_mutation_scope_id


START_CONTEXT_SCHEMA = "dxm_edit_batch_start_context.v1"
ITEM_GRANT_SCHEMA = "dxm_edit_batch_item_grant.v1"
ITEM_CLAIM_CONTEXT_SCHEMA = "dxm_edit_batch_item_claim_context.v1"
ITEM_EXECUTION_REQUEST_SCHEMA = "dxm_edit_batch_item_execution_request.v1"
ITEM_GRANT_CONSUMPTION_SCHEMA = "dxm_edit_batch_item_grant_consumption.v1"
ITEM_OUTCOME_EVIDENCE_SCHEMA = "dxm_edit_batch_item_outcome_evidence.v1"
ITEM_OUTCOME_DECISION_SCHEMA = "dxm_edit_batch_item_outcome_decision.v1"
ITEM_GRANT_TTL_SECONDS = 60
_TERMINAL_CONTINUE_ITEM_STATUSES = {"succeeded", "isolated_pre_save_no_write"}
PRE_SAVE_VALIDATION_REASON_ALLOWLIST = frozenset(
    {
        "FIELD_VALIDATION_REJECTED",
        "REQUIRED_FIELD_MISSING",
        "INVALID_FIELD_VALUE",
        "READBACK_VALIDATION_FAILED",
    }
)


class BatchExecutionContractError(ValueError):
    def __init__(self, reason_code: str, detail: str) -> None:
        self.reason_code = reason_code
        super().__init__(detail)


def authorize_batch_start(
    batch: Any,
    *,
    approval_token: str,
    stored_approval_token_hash: str,
    approval_context: Any,
    now: datetime,
    authoritative_facts: Any,
    approval_token_consumed: bool = False,
) -> dict[str, Any]:
    """Validate a one-time batch approval without returning either approval secret."""
    canonical_batch = _batch_object(batch)
    if canonical_batch["schema_version"] != BATCH_SCHEMA:
        _reject("BATCH_SCHEMA_INVALID", "batch schema is not supported")
    if canonical_batch["status"] != "approved":
        _reject("BATCH_NOT_APPROVED", "batch must be approved before execution")
    if approval_token_consumed is not False:
        _reject("APPROVAL_TOKEN_REPLAY", "approval token has already been consumed")

    raw_token = _non_empty_text(approval_token, "approval token")
    stored_hash = _sha256_text(stored_approval_token_hash, "stored approval token hash")
    supplied_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest().upper()
    if not hmac.compare_digest(supplied_hash, stored_hash):
        _reject("APPROVAL_TOKEN_MISMATCH", "approval token does not match the private binding")

    context = _approval_context(approval_context)
    unsigned_context = dict(context)
    fingerprint = unsigned_context.pop("fingerprint")
    if not hmac.compare_digest(fingerprint, canonical_sha256(unsigned_context)):
        _reject("APPROVAL_CONTEXT_FINGERPRINT_INVALID", "approval context fingerprint is invalid")
    current_time = _aware_datetime(now, "now")
    issued_at = _timestamp(context["issued_at"], "approval issued_at")
    expires_at = _timestamp(context["expires_at"], "approval expires_at")
    if issued_at >= expires_at or (expires_at - issued_at).total_seconds() > 5 * 60:
        _reject("APPROVAL_LEASE_INTERVAL_INVALID", "approval lease interval is invalid")
    if current_time < issued_at:
        _reject("APPROVAL_NOT_YET_VALID", "approval lease has not started")
    if current_time >= expires_at:
        _reject("APPROVAL_LEASE_EXPIRED", "approval lease has expired")

    try:
        scope = freeze_scope_snapshot(canonical_batch["scope_snapshot"])
        template = freeze_template_bundle(canonical_batch["template_snapshot"])
    except BatchContractError as exc:
        raise BatchExecutionContractError(exc.reason_code, str(exc)) from exc
    expected_policy = frozen_batch_policy()
    if canonical_batch["scope_snapshot_id"] != scope["id"] or canonical_batch[
        "scope_snapshot_digest"
    ] != scope["digest"]:
        _reject("BATCH_SCOPE_BINDING_DRIFT", "frozen scope binding has drifted")
    if canonical_batch["template_id"] != template.get("id") or canonical_batch[
        "template_snapshot_digest"
    ] != canonical_sha256(template):
        _reject("BATCH_TEMPLATE_BINDING_DRIFT", "frozen template binding has drifted")
    if canonical_batch["policy"] != expected_policy or canonical_batch["policy_digest"] != canonical_sha256(
        expected_policy
    ):
        _reject("BATCH_POLICY_BINDING_DRIFT", "frozen policy binding has drifted")

    batch_id = _positive_int(canonical_batch["id"], "batch.id")
    if context["batch"] != {
        "id": batch_id,
        "schema_version": BATCH_SCHEMA,
        "required_status": "draft",
    }:
        _reject("APPROVAL_BATCH_BINDING_DRIFT", "approval is not bound to this batch")
    if context["scope"] != {
        "snapshot_id": canonical_batch["scope_snapshot_id"],
        "snapshot_digest": canonical_batch["scope_snapshot_digest"],
    }:
        _reject("APPROVAL_SCOPE_BINDING_DRIFT", "approval scope binding has drifted")
    if context["template"] != {
        "id": canonical_batch["template_id"],
        "snapshot_digest": canonical_batch["template_snapshot_digest"],
    }:
        _reject("APPROVAL_TEMPLATE_BINDING_DRIFT", "approval template binding has drifted")
    if context["policy"] != {"digest": canonical_batch["policy_digest"]}:
        _reject("APPROVAL_POLICY_BINDING_DRIFT", "approval policy binding has drifted")
    if context["confirmation"] != "CONFIRM_DXM_BATCH_SAVE_ONLY":
        _reject("APPROVAL_CONFIRMATION_INVALID", "approval confirmation is invalid")

    ordered_targets = _ordered_targets(canonical_batch["items"])
    if context["ordered_targets"] != {
        "items": ordered_targets,
        "digest": canonical_sha256(ordered_targets),
    }:
        _reject("APPROVAL_TARGET_ORDER_DRIFT", "approved target order has drifted")
    attestation = _exact_object(
        context["read_attestation"],
        {
            "kind",
            "status",
            "captured_at",
            "frozen_scope_digest",
            "revalidated_scope_digest",
            "ordered_target_digest",
            "dom_sha256",
            "refs_digest",
            "zero_write_digest",
        },
        "approval read attestation",
    )
    captured_at = _timestamp(attestation["captured_at"], "attestation captured_at")
    for key in (
        "frozen_scope_digest",
        "revalidated_scope_digest",
        "ordered_target_digest",
        "dom_sha256",
        "refs_digest",
        "zero_write_digest",
    ):
        _sha256_text(attestation[key], f"attestation {key}")
    if (
        attestation["kind"] != "scope_revalidation"
        or attestation["status"] != "matched"
        or captured_at > issued_at
        or attestation["frozen_scope_digest"] != canonical_batch["scope_snapshot_digest"]
        or attestation["ordered_target_digest"] != context["ordered_targets"]["digest"]
        or attestation["dom_sha256"] != scope["evidence"].get("dom_sha256")
        or attestation["refs_digest"] != scope["evidence"].get("refs_digest")
        or attestation["zero_write_digest"] != canonical_sha256(scope["zero_write_proof"])
    ):
        _reject("APPROVAL_READ_ATTESTATION_INVALID", "approval read attestation has drifted")
    if any(item["status"] != "pending" for item in canonical_batch["items"]):
        _reject("BATCH_START_ITEM_STATE_INVALID", "a fresh batch start requires all items pending")

    live = _exact_object(
        authoritative_facts,
        {
            "runtime_identity",
            "browser_session_id",
            "git_head",
            "l2_evidence_fingerprint",
            "store_identity",
            "page_identity",
        },
        "authoritative facts",
    )
    if live["runtime_identity"] != context["runtime_identity"] or live["runtime_identity"] != scope[
        "runtime_identity"
    ]:
        _reject("RUNTIME_IDENTITY_DRIFT", "authoritative runtime identity has drifted")
    if live["browser_session_id"] != scope["runtime_identity"].get("browser_session_id"):
        _reject("BROWSER_SESSION_DRIFT", "authoritative browser session has drifted")
    if live["git_head"] != scope["runtime_identity"].get("git_head"):
        _reject("GIT_HEAD_DRIFT", "authoritative git head has drifted")
    if live["l2_evidence_fingerprint"] != context["l2_evidence_fingerprint"]:
        _reject("L2_EVIDENCE_DRIFT", "authoritative L2 evidence has drifted")
    if live["store_identity"] != context["store_identity"] or live["store_identity"] != scope[
        "store_identity"
    ]:
        _reject("STORE_IDENTITY_DRIFT", "authoritative store identity has drifted")
    if live["page_identity"] != scope["page_identity"]:
        _reject("PAGE_IDENTITY_DRIFT", "authoritative page identity has drifted")

    return _canonical_clone(
        {
            "schema_version": START_CONTEXT_SCHEMA,
            "authorization_state": "approval_token_consumed",
            "batch_id": batch_id,
            "approval_lease_id": context["lease_id"],
            "approval_context_fingerprint": fingerprint,
            "approval_expires_at": context["expires_at"],
            "scope_digest": canonical_batch["scope_snapshot_digest"],
            "template_digest": canonical_batch["template_snapshot_digest"],
            "policy_digest": canonical_batch["policy_digest"],
            "ordered_target_digest": context["ordered_targets"]["digest"],
            "runtime_identity": live["runtime_identity"],
            "browser_session_id": live["browser_session_id"],
            "git_head": live["git_head"],
            "l2_evidence_fingerprint": live["l2_evidence_fingerprint"],
            "store_identity": live["store_identity"],
            "page_identity": live["page_identity"],
        }
    )


def derive_running_item_claim_context(
    batch: Any,
    *,
    start_context: Any,
    allow_stop_requested: bool = False,
) -> dict[str, Any]:
    """Bind the sole claimed item without creating any mutation authority."""

    canonical_batch = _batch_object(batch)
    start = _execution_start_context(start_context)
    allowed_batch_statuses = {"running", "stop_requested"} if allow_stop_requested else {"running"}
    if (
        canonical_batch["schema_version"] != BATCH_SCHEMA
        or canonical_batch["status"] not in allowed_batch_statuses
    ):
        _reject("BATCH_NOT_RUNNING", "an item may be claimed only from a running batch")
    if canonical_batch["id"] != start["batch_id"]:
        _reject("START_BATCH_BINDING_DRIFT", "start context batch binding has drifted")
    for batch_key, start_key in (
        ("scope_snapshot_digest", "scope_digest"),
        ("template_snapshot_digest", "template_digest"),
        ("policy_digest", "policy_digest"),
    ):
        if canonical_batch[batch_key] != start[start_key]:
            _reject("START_FROZEN_BINDING_DRIFT", f"{start_key} has drifted")
    try:
        frozen_scope = freeze_scope_snapshot(canonical_batch["scope_snapshot"])
    except BatchContractError as exc:
        raise BatchExecutionContractError(exc.reason_code, str(exc)) from exc
    scope_runtime = frozen_scope.get("runtime_identity")
    if (
        frozen_scope.get("digest") != start["scope_digest"]
        or start["runtime_identity"] != scope_runtime
        or start["store_identity"] != frozen_scope.get("store_identity")
        or start["page_identity"] != frozen_scope.get("page_identity")
        or not isinstance(scope_runtime, dict)
        or start["browser_session_id"] != scope_runtime.get("browser_session_id")
        or start["git_head"] != scope_runtime.get("git_head")
    ):
        _reject(
            "START_LIVE_BINDING_DRIFT",
            "persisted start context no longer matches the frozen scope",
        )

    items = canonical_batch["items"]
    if not isinstance(items, list) or not items:
        _reject("BATCH_ITEM_BINDING_INVALID", "batch items are missing")
    ordered_targets = _ordered_targets(items)
    if canonical_sha256(ordered_targets) != start["ordered_target_digest"]:
        _reject("START_TARGET_ORDER_DRIFT", "ordered target binding has drifted")

    running: dict[str, Any] | None = None
    seen_running = False
    for expected_ordinal, item in enumerate(items, start=1):
        if not isinstance(item, dict) or item.get("ordinal") != expected_ordinal:
            _reject("BATCH_ITEM_ORDER_INVALID", "batch item order is not contiguous")
        status = item.get("status")
        if status in _TERMINAL_CONTINUE_ITEM_STATUSES and not seen_running:
            continue
        if status == "running" and not seen_running:
            running = item
            seen_running = True
            continue
        if status == "pending" and seen_running:
            continue
        if status == "running":
            _reject("MULTIPLE_BATCH_ITEMS_RUNNING", "more than one batch item is running")
        _reject("BATCH_ITEM_ORDER_INVALID", "claimed item ordering is not strictly serial")
    if running is None:
        _reject("BATCH_ITEM_NOT_CLAIMED", "batch has no claimed running item")

    return _canonical_clone(
        {
            "schema_version": ITEM_CLAIM_CONTEXT_SCHEMA,
            "batch_id": start["batch_id"],
            "item_id": _positive_int(running.get("id"), "batch item id"),
            "ordinal": _positive_int(running.get("ordinal"), "batch item ordinal"),
            "scope_digest": start["scope_digest"],
            "template_digest": start["template_digest"],
            "policy_digest": start["policy_digest"],
            "target_identity_sha256": _sha256_text(
                running.get("target_identity_sha256"), "target identity hash"
            ),
            "store_identity": start["store_identity"],
            "runtime_identity": start["runtime_identity"],
            "browser_session_id": start["browser_session_id"],
            "git_head": start["git_head"],
            "l2_evidence_fingerprint": start["l2_evidence_fingerprint"],
            "page_identity": start["page_identity"],
        }
    )


def derive_next_item_grant(
    batch: Any,
    *,
    start_context: Any,
    now: datetime,
    grant_lease_id: str,
    one_time_nonce: str,
) -> dict[str, Any]:
    """Derive one short-lived grant for the already-claimed running item only."""
    canonical_batch = _batch_object(batch)
    start = _execution_start_context(start_context)
    claim = derive_running_item_claim_context(canonical_batch, start_context=start)
    current_time = _aware_datetime(now, "now")
    # The five-minute approval lease gates the *start* transition only.  Once
    # authorize_batch_start has consumed it and the resulting start context is
    # durably stored, a large strictly-serial batch must not become invalid just
    # because later items take longer than five minutes to reach.  Every item is
    # still protected by its own short-lived, one-use grant below.
    _timestamp(start["approval_expires_at"], "approval expires_at")

    ordinal = claim["ordinal"]
    item_id = claim["item_id"]
    target_hash = claim["target_identity_sha256"]
    nonce = _non_empty_text(one_time_nonce, "one-time grant nonce")
    lease_id = _non_empty_text(grant_lease_id, "grant lease id")
    issued_at = current_time.isoformat()
    expires_at = current_time.timestamp() + ITEM_GRANT_TTL_SECONDS
    expires_text = datetime.fromtimestamp(expires_at, timezone.utc).isoformat()
    mutation_scope_id = build_mutation_scope_id(
        authorization_lease_id=lease_id,
        task_id=start["batch_id"],
        job_id=item_id,
        state="SAVE_ONLY",
        action="save_only",
    )
    grant_body = {
        "schema_version": ITEM_GRANT_SCHEMA,
        "batch_id": start["batch_id"],
        "item_id": item_id,
        "ordinal": ordinal,
        "approval_lease_id": start["approval_lease_id"],
        "approval_context_fingerprint": start["approval_context_fingerprint"],
        "approval_expires_at": start["approval_expires_at"],
        "scope_digest": claim["scope_digest"],
        "template_digest": claim["template_digest"],
        "policy_digest": claim["policy_digest"],
        "target_identity_sha256": target_hash,
        "store_identity": claim["store_identity"],
        "runtime_identity": claim["runtime_identity"],
        "browser_session_id": claim["browser_session_id"],
        "git_head": claim["git_head"],
        "l2_evidence_fingerprint": claim["l2_evidence_fingerprint"],
        "page_identity": claim["page_identity"],
        "mutation_scope_id": mutation_scope_id,
        "grant_lease_id": lease_id,
        "issued_at": issued_at,
        "expires_at": expires_text,
        "nonce_hash": hashlib.sha256(nonce.encode("utf-8")).hexdigest().upper(),
    }
    grant = {**grant_body, "fingerprint": canonical_sha256(grant_body)}
    return {"grant": _canonical_clone(grant), "nonce": nonce}


def validate_and_consume_item_grant(
    grant: Any,
    *,
    raw_nonce: str,
    now: datetime,
    request: Any,
    consumed_nonce_hashes: Any,
) -> dict[str, Any]:
    """Validate a grant and return the atomic state transition inputs for its one use."""
    grant_keys = {
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
        "l2_evidence_fingerprint",
        "page_identity",
        "mutation_scope_id",
        "grant_lease_id",
        "issued_at",
        "expires_at",
        "nonce_hash",
        "fingerprint",
    }
    canonical_grant = _exact_object(grant, grant_keys, "item grant")
    if canonical_grant["schema_version"] != ITEM_GRANT_SCHEMA:
        _reject("GRANT_SCHEMA_INVALID", "item grant schema is not supported")
    unsigned_grant = dict(canonical_grant)
    fingerprint = _sha256_text(unsigned_grant.pop("fingerprint"), "grant fingerprint")
    if not hmac.compare_digest(fingerprint, canonical_sha256(unsigned_grant)):
        _reject("GRANT_FINGERPRINT_INVALID", "item grant fingerprint is invalid")

    current_time = _aware_datetime(now, "now")
    # Approval expiry is checked while creating the persisted start context.
    # Mutation dispatch is instead bounded by the per-item grant expiry so an
    # already-started batch can progress without silently extending approval
    # token validity or forcing unsafe re-approval mid-run.
    _timestamp(canonical_grant["approval_expires_at"], "approval expires_at")
    issued_at = _timestamp(canonical_grant["issued_at"], "grant issued_at")
    expires_at = _timestamp(canonical_grant["expires_at"], "grant expires_at")
    if issued_at >= expires_at or (expires_at - issued_at).total_seconds() != ITEM_GRANT_TTL_SECONDS:
        _reject("GRANT_INTERVAL_INVALID", "item grant interval is invalid")
    if current_time < issued_at:
        _reject("GRANT_NOT_YET_VALID", "item grant has not started")
    if current_time >= expires_at:
        _reject("GRANT_EXPIRED", "item grant has expired")
    expected_nonce_hash = _sha256_text(canonical_grant["nonce_hash"], "grant nonce hash")
    supplied_nonce_hash = hashlib.sha256(
        _non_empty_text(raw_nonce, "grant nonce").encode("utf-8")
    ).hexdigest().upper()
    if not hmac.compare_digest(supplied_nonce_hash, expected_nonce_hash):
        _reject("GRANT_NONCE_MISMATCH", "grant nonce does not match")
    if not isinstance(consumed_nonce_hashes, (set, frozenset, list, tuple)):
        _reject("CONSUMED_NONCE_SET_INVALID", "consumed nonce hashes are invalid")
    normalized_consumed = {
        _sha256_text(value, "consumed nonce hash") for value in consumed_nonce_hashes
    }
    if expected_nonce_hash in normalized_consumed:
        _reject("GRANT_REPLAY_FORBIDDEN", "item grant has already been consumed")

    binding_keys = (
        "batch_id",
        "item_id",
        "ordinal",
        "approval_lease_id",
        "approval_context_fingerprint",
        "scope_digest",
        "template_digest",
        "policy_digest",
        "target_identity_sha256",
        "store_identity",
        "runtime_identity",
        "browser_session_id",
        "git_head",
        "l2_evidence_fingerprint",
        "page_identity",
        "mutation_scope_id",
        "grant_lease_id",
    )
    request_keys = {"schema_version", "action", "mode", "grant_fingerprint", *binding_keys}
    canonical_request = _exact_object(request, request_keys, "execution request")
    if canonical_request["schema_version"] != ITEM_EXECUTION_REQUEST_SCHEMA:
        _reject("ITEM_REQUEST_SCHEMA_INVALID", "execution request schema is not supported")
    if canonical_request["action"] != "SAVE_ONLY":
        _reject("ITEM_ACTION_FORBIDDEN", "only SAVE_ONLY is authorized")
    if canonical_request["mode"] != "batch_single_save":
        _reject("ITEM_MODE_FORBIDDEN", "only batch_single_save mode is authorized")
    if canonical_request["grant_fingerprint"] != fingerprint or any(
        canonical_request[key] != canonical_grant[key] for key in binding_keys
    ):
        _reject("GRANT_REQUEST_BINDING_DRIFT", "execution request does not exactly match its grant")

    return {
        "schema_version": ITEM_GRANT_CONSUMPTION_SCHEMA,
        "batch_id": canonical_grant["batch_id"],
        "item_id": canonical_grant["item_id"],
        "ordinal": canonical_grant["ordinal"],
        "from_status": "running",
        "to_status": "running",
        "grant_lease_id": canonical_grant["grant_lease_id"],
        "grant_fingerprint": fingerprint,
        "mutation_scope_id": canonical_grant["mutation_scope_id"],
        "consumed_nonce_hash": expected_nonce_hash,
        "retry_allowed": False,
    }


def classify_pre_save_no_write_outcome(claim_context: Any, outcome: Any) -> dict[str, Any]:
    """Classify a pre-save failure that never possessed mutation authority."""

    claim = _exact_object(
        claim_context,
        {
            "schema_version",
            "batch_id",
            "item_id",
            "ordinal",
            "scope_digest",
            "template_digest",
            "policy_digest",
            "target_identity_sha256",
            "store_identity",
            "runtime_identity",
            "browser_session_id",
            "git_head",
            "l2_evidence_fingerprint",
            "page_identity",
        },
        "item claim context",
    )
    if claim["schema_version"] != ITEM_CLAIM_CONTEXT_SCHEMA:
        return _stop_decision(claim, "CLAIM_CONTEXT_SCHEMA_INVALID")
    try:
        evidence = _exact_object(
            outcome,
            {
                "schema_version",
                "ok",
                "error_code",
                "validation_reason",
                "ledger_status",
                "network_audit",
                "publish_signal",
                "save_proven",
                "runtime_identity",
                "browser_session_id",
                "git_head",
                "l2_evidence_fingerprint",
                "store_identity",
                "scope_page_identity",
                "action_page_identity",
                "save_page_identity",
                "verification_page_identity",
                "target_identity_sha256",
                "mutation_scope_id",
            },
            "item outcome evidence",
        )
        network = _exact_object(
            evidence["network_audit"],
            {"complete", "mutation_request_count", "publish_request_count"},
            "network audit",
        )
        publish = _exact_object(
            evidence["publish_signal"], {"detected", "kind"}, "publish signal"
        )
        mutation_count = _non_negative_count(network["mutation_request_count"])
        publish_count = _non_negative_count(network["publish_request_count"])
    except BatchExecutionContractError:
        return _stop_decision(claim, "EVIDENCE_MISSING")

    stable_keys = (
        "runtime_identity",
        "browser_session_id",
        "git_head",
        "l2_evidence_fingerprint",
        "store_identity",
        "target_identity_sha256",
    )
    if any(evidence[key] != claim[key] for key in stable_keys):
        return _stop_decision(claim, "OUTCOME_IDENTITY_DRIFT")
    if evidence["scope_page_identity"] != claim["page_identity"]:
        return _stop_decision(claim, "OUTCOME_IDENTITY_DRIFT")
    try:
        action_page = _execution_page_identity(
            evidence["action_page_identity"], "pre-save action page identity"
        )
    except BatchExecutionContractError:
        return _stop_decision(claim, "EVIDENCE_MISSING")
    runtime_identity = claim.get("runtime_identity")
    if (
        not isinstance(runtime_identity, dict)
        or action_page["runtime_id"] != runtime_identity.get("browser_runtime_id")
        or action_page["browser_session_id"] != claim["browser_session_id"]
        or evidence["save_page_identity"] is not None
        or evidence["verification_page_identity"] is not None
    ):
        return _stop_decision(claim, "OUTCOME_IDENTITY_DRIFT")
    if (
        evidence["schema_version"] != ITEM_OUTCOME_EVIDENCE_SCHEMA
        or evidence["ok"] is not False
        or evidence["error_code"] != "PRE_SAVE_VALIDATION_NO_WRITE"
        or evidence["validation_reason"] not in PRE_SAVE_VALIDATION_REASON_ALLOWLIST
        or evidence["ledger_status"] is not None
        or evidence["mutation_scope_id"] is not None
        or network["complete"] is not True
        or mutation_count != 0
        or publish_count != 0
        or publish["detected"] is not False
        or not isinstance(publish.get("kind"), str)
        or not publish["kind"].strip()
        or evidence["save_proven"] is not False
    ):
        return _stop_decision(claim, "ZERO_WRITE_PROOF_FALSE")
    return _continue_decision(
        claim,
        "ISOLATED_PRE_SAVE_NO_WRITE",
        "PRE_SAVE_VALIDATION_ISOLATED",
    )


def classify_item_outcome(grant: Any, outcome: Any) -> dict[str, Any]:
    """Classify item evidence. Every uncertain path stops and is never retryable."""
    grant_keys = {
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
        "l2_evidence_fingerprint",
        "page_identity",
        "mutation_scope_id",
        "grant_lease_id",
        "issued_at",
        "expires_at",
        "nonce_hash",
        "fingerprint",
    }
    canonical_grant = _exact_object(grant, grant_keys, "item grant")
    unsigned_grant = dict(canonical_grant)
    grant_fingerprint = _sha256_text(
        unsigned_grant.pop("fingerprint"), "grant fingerprint"
    )
    if not hmac.compare_digest(grant_fingerprint, canonical_sha256(unsigned_grant)):
        _reject("GRANT_FINGERPRINT_INVALID", "item grant fingerprint is invalid")
    try:
        evidence = _exact_object(
            outcome,
            {
                "schema_version",
                "ok",
                "error_code",
                "validation_reason",
                "ledger_status",
                "network_audit",
                "publish_signal",
                "save_proven",
                "runtime_identity",
                "browser_session_id",
                "git_head",
                "l2_evidence_fingerprint",
                "store_identity",
                "scope_page_identity",
                "action_page_identity",
                "save_page_identity",
                "verification_page_identity",
                "target_identity_sha256",
                "mutation_scope_id",
            },
            "item outcome evidence",
        )
        if evidence["schema_version"] != ITEM_OUTCOME_EVIDENCE_SCHEMA:
            return _stop_decision(canonical_grant, "EVIDENCE_SCHEMA_INVALID")
        network = _exact_object(
            evidence["network_audit"],
            {"complete", "mutation_request_count", "publish_request_count"},
            "network audit",
        )
        publish = _exact_object(
            evidence["publish_signal"], {"detected", "kind"}, "publish signal"
        )
    except BatchExecutionContractError:
        return _stop_decision(canonical_grant, "EVIDENCE_MISSING")

    try:
        publish_count = _non_negative_count(network["publish_request_count"])
        mutation_count = _non_negative_count(network["mutation_request_count"])
    except BatchExecutionContractError:
        return _stop_decision(canonical_grant, "EVIDENCE_MISSING")
    if publish["detected"] is not False or publish_count > 0:
        return _stop_decision(canonical_grant, "PUBLISH_RISK_DETECTED")
    if network["complete"] is not True:
        return _stop_decision(canonical_grant, "EVIDENCE_MISSING")
    if not isinstance(publish.get("kind"), str) or not publish["kind"].strip():
        return _stop_decision(canonical_grant, "EVIDENCE_MISSING")
    stable_keys = (
        "runtime_identity",
        "browser_session_id",
        "git_head",
        "l2_evidence_fingerprint",
        "store_identity",
        "target_identity_sha256",
        "mutation_scope_id",
    )
    if any(evidence[key] != canonical_grant[key] for key in stable_keys):
        return _stop_decision(canonical_grant, "OUTCOME_IDENTITY_DRIFT")
    if evidence["scope_page_identity"] != canonical_grant["page_identity"]:
        return _stop_decision(canonical_grant, "OUTCOME_IDENTITY_DRIFT")
    actual_pages: dict[str, dict[str, Any]] = {}
    try:
        for page_key in (
            "action_page_identity",
            "save_page_identity",
            "verification_page_identity",
        ):
            page_value = evidence[page_key]
            if page_value is not None:
                actual_pages[page_key] = _execution_page_identity(page_value, page_key)
    except BatchExecutionContractError:
        return _stop_decision(canonical_grant, "EVIDENCE_MISSING")
    runtime_identity = canonical_grant.get("runtime_identity")
    if not isinstance(runtime_identity, dict) or any(
        page["runtime_id"] != runtime_identity.get("browser_runtime_id")
        or page["browser_session_id"] != canonical_grant["browser_session_id"]
        for page in actual_pages.values()
    ):
        return _stop_decision(canonical_grant, "OUTCOME_IDENTITY_DRIFT")

    if evidence["ok"] is True:
        save_page = actual_pages.get("save_page_identity")
        verification_page = actual_pages.get("verification_page_identity")
        if (
            evidence["error_code"] is None
            and evidence["validation_reason"] is None
            and evidence["ledger_status"] == "DISPATCHED"
            and evidence["save_proven"] is True
            and mutation_count >= 1
            and evidence["action_page_identity"] is None
            and isinstance(save_page, dict)
            and save_page == verification_page
            and save_page.get("kind") == "semi_managed"
        ):
            return _continue_decision(canonical_grant, "SUCCEEDED", "ITEM_SAVE_PROVEN")
        return _stop_decision(canonical_grant, "SUCCESS_EVIDENCE_UNCERTAIN")

    if evidence["ledger_status"] not in (None, "RESERVED"):
        return _stop_decision(canonical_grant, "MUTATION_OUTCOME_UNCERTAIN")
    if mutation_count != 0:
        return _stop_decision(canonical_grant, "ZERO_WRITE_PROOF_FALSE")
    # Once a grant exists, the item has crossed the mutation-authority boundary.
    # Even zero-write-looking evidence can no longer be isolated automatically;
    # the persisted grant and ledger reservation require manual reconciliation.
    if evidence["error_code"] == "PRE_SAVE_VALIDATION_NO_WRITE":
        return _stop_decision(canonical_grant, "POST_GRANT_FAILURE_REQUIRES_REVIEW")
    return _stop_decision(canonical_grant, "UNCLASSIFIED_ITEM_FAILURE")


def _continue_decision(grant: dict[str, Any], classification: str, reason_code: str) -> dict[str, Any]:
    return {
        "schema_version": ITEM_OUTCOME_DECISION_SCHEMA,
        "classification": classification,
        "continue_batch": True,
        "retry_allowed": False,
        "reason_code": reason_code,
        "item_transition": {
            "batch_id": grant["batch_id"],
            "item_id": grant["item_id"],
            "ordinal": grant["ordinal"],
            "from_status": "running",
            "to_status": classification.lower(),
        },
        "batch_transition": None,
    }


def _stop_decision(grant: dict[str, Any], reason_code: str) -> dict[str, Any]:
    return {
        "schema_version": ITEM_OUTCOME_DECISION_SCHEMA,
        "classification": "STOPPED_UNCERTAIN",
        "continue_batch": False,
        "retry_allowed": False,
        "reason_code": reason_code,
        "item_transition": {
            "batch_id": grant["batch_id"],
            "item_id": grant["item_id"],
            "ordinal": grant["ordinal"],
            "from_status": "running",
            "to_status": "stopped_uncertain",
        },
        "batch_transition": {"from_status": "running", "to_status": "stopped"},
    }


def _non_negative_count(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _reject("COUNT_INVALID", "audit counts must be non-negative integers")
    return value


def _execution_page_identity(value: Any, label: str) -> dict[str, Any]:
    page = _exact_object(
        value,
        {"kind", "url", "runtime_id", "browser_session_id"},
        label,
    )
    for key in ("kind", "url", "runtime_id", "browser_session_id"):
        _non_empty_text(page[key], f"{label}.{key}")
    if not str(page["url"]).lower().startswith(("http://", "https://")):
        _reject("PAGE_IDENTITY_INVALID", f"{label}.url must be an absolute HTTP URL")
    return page


def _batch_object(value: Any) -> dict[str, Any]:
    base_keys = {
        "id",
        "schema_version",
        "status",
        "scope_snapshot_id",
        "scope_snapshot_digest",
        "scope_snapshot",
        "template_id",
        "template_snapshot_digest",
        "template_snapshot",
        "policy_digest",
        "policy",
        "created_at",
        "updated_at",
        "items",
    }
    if not isinstance(value, dict) or set(value) not in (base_keys, base_keys | {"approval"}):
        _reject("EXACT_OBJECT_REQUIRED", "batch has an unexpected shape")
    canonical = _canonical_clone(value)
    if "approval" in canonical:
        _exact_object(
            canonical["approval"],
            {
                "approved",
                "approved_by",
                "approved_at",
            },
            "public approval summary",
        )
    return canonical


def _approval_context(value: Any) -> dict[str, Any]:
    context = _exact_object(
        value,
        {
            "schema_version",
            "batch",
            "scope",
            "template",
            "policy",
            "ordered_targets",
            "store_identity",
            "runtime_identity",
            "l2_evidence_fingerprint",
            "read_attestation",
            "approved_by",
            "confirmation",
            "lease_id",
            "issued_at",
            "expires_at",
            "fingerprint",
        },
        "approval context",
    )
    if context["schema_version"] != "dxm_edit_batch_approval_context.v1":
        _reject("APPROVAL_CONTEXT_SCHEMA_INVALID", "approval context schema is not supported")
    for key in ("batch", "scope", "template", "policy", "ordered_targets"):
        if not isinstance(context[key], dict):
            _reject("APPROVAL_CONTEXT_INVALID", f"approval context {key} is invalid")
    _sha256_text(context["fingerprint"], "approval context fingerprint")
    _sha256_text(
        context["l2_evidence_fingerprint"],
        "approval L2 evidence fingerprint",
    )
    _non_empty_text(context["lease_id"], "approval lease id")
    _timestamp(context["issued_at"], "approval issued_at")
    _timestamp(context["expires_at"], "approval expires_at")
    return context


def _execution_start_context(value: Any) -> dict[str, Any]:
    start = _exact_object(
        value,
        {
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
            "l2_evidence_fingerprint",
            "store_identity",
            "page_identity",
        },
        "start context",
    )
    if start["schema_version"] != START_CONTEXT_SCHEMA:
        _reject("START_CONTEXT_SCHEMA_INVALID", "start context schema is not supported")
    if start["authorization_state"] != "approval_token_consumed":
        _reject("START_AUTHORIZATION_NOT_CONSUMED", "approval token was not consumed")
    _positive_int(start["batch_id"], "start context batch id")
    for key in (
        "approval_context_fingerprint",
        "scope_digest",
        "template_digest",
        "policy_digest",
        "ordered_target_digest",
        "l2_evidence_fingerprint",
    ):
        _sha256_text(start[key], key)
    _non_empty_text(start["approval_lease_id"], "approval lease id")
    _timestamp(start["approval_expires_at"], "approval expires_at")
    return start


def _ordered_targets(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list) or not items:
        _reject("BATCH_ITEM_BINDING_INVALID", "batch items are missing")
    result: list[dict[str, Any]] = []
    for ordinal, item in enumerate(items, start=1):
        if not isinstance(item, dict) or item.get("ordinal") != ordinal:
            _reject("BATCH_ITEM_ORDER_INVALID", "batch item order is not contiguous")
        snapshot = item.get("item_snapshot")
        if not isinstance(snapshot, dict) or snapshot.get("ordinal") != ordinal:
            _reject("BATCH_ITEM_BINDING_INVALID", "batch item snapshot is invalid")
        target = snapshot.get("target_identity")
        target_hash = snapshot.get("target_identity_sha256")
        if not isinstance(target, dict) or target_hash != canonical_sha256(target):
            _reject("BATCH_TARGET_BINDING_DRIFT", "batch target identity has drifted")
        if item.get("target_identity_sha256") != target_hash:
            _reject("BATCH_TARGET_BINDING_DRIFT", "batch item target hash has drifted")
        result.append(
            {
                "ordinal": ordinal,
                "target_identity": target,
                "target_identity_sha256": target_hash,
            }
        )
    return result


def _exact_object(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        _reject("EXACT_OBJECT_REQUIRED", f"{label} must contain exactly {sorted(keys)}")
    return _canonical_clone(value)


def _canonical_clone(value: Any) -> Any:
    try:
        return json.loads(
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        )
    except (TypeError, ValueError) as exc:
        raise BatchExecutionContractError(
            "FACTS_NOT_CANONICAL_JSON", "execution facts are not canonical JSON"
        ) from exc


def _timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        _reject("TIMESTAMP_INVALID", f"{label} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BatchExecutionContractError("TIMESTAMP_INVALID", f"{label} is invalid") from exc
    return _aware_datetime(parsed, label)


def _aware_datetime(value: Any, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        _reject("TIMESTAMP_INVALID", f"{label} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _non_empty_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        _reject("TEXT_INVALID", f"{label} must be non-empty canonical text")
    return value


def _sha256_text(value: Any, label: str) -> str:
    text = _non_empty_text(value, label).upper()
    if len(text) != 64 or any(char not in "0123456789ABCDEF" for char in text):
        _reject("SHA256_INVALID", f"{label} must be a SHA-256 hex digest")
    return text


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        _reject("INTEGER_INVALID", f"{label} must be a positive integer")
    return value


def _reject(reason_code: str, detail: str) -> None:
    raise BatchExecutionContractError(reason_code, detail)
