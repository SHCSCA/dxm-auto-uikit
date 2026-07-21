from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from src.batch_edit.scope_contract import (
    ScopeContractError,
    canonical_sha256,
    normalize_scope_capture,
)
from src.batch_edit.batch_contract import (
    BATCH_SCHEMA,
    BatchContractError,
    freeze_scope_snapshot,
    freeze_template_bundle,
    frozen_batch_policy,
)


BATCH_APPROVAL_CONFIRMATION = "CONFIRM_DXM_BATCH_SAVE_ONLY"
BATCH_APPROVAL_CONTEXT_SCHEMA = "dxm_edit_batch_approval_context.v1"
BATCH_APPROVAL_TTL_SECONDS = 5 * 60


class BatchApprovalContractError(ValueError):
    def __init__(self, reason_code: str, detail: str) -> None:
        self.reason_code = reason_code
        super().__init__(detail)


def validate_batch_for_approval(batch: Any) -> int:
    if not isinstance(batch, dict) or batch.get("schema_version") != BATCH_SCHEMA:
        _reject("BATCH_FROZEN_FACTS_INVALID", "edit batch schema is invalid")
    if batch.get("status") != "draft":
        _reject("BATCH_NOT_DRAFT", "edit batch is no longer a draft")

    try:
        scope = freeze_scope_snapshot(batch.get("scope_snapshot"))
        template = freeze_template_bundle(batch.get("template_snapshot"))
    except BatchContractError as exc:
        raise BatchApprovalContractError(exc.reason_code, str(exc)) from exc
    if (
        batch.get("scope_snapshot_id") != scope.get("id")
        or batch.get("scope_snapshot_digest") != scope.get("digest")
    ):
        _reject("BATCH_SCOPE_SNAPSHOT_DRIFT", "frozen scope snapshot binding has drifted")
    if (
        batch.get("template_id") != template.get("id")
        or canonical_sha256(template) != batch.get("template_snapshot_digest")
    ):
        _reject("BATCH_TEMPLATE_SNAPSHOT_DRIFT", "frozen template digest has drifted")

    expected_policy = frozen_batch_policy()
    if (
        batch.get("policy") != expected_policy
        or batch.get("policy_digest") != canonical_sha256(expected_policy)
    ):
        _reject("BATCH_POLICY_DRIFT", "frozen batch policy has drifted")

    scope_items = scope.get("items")
    batch_items = batch.get("items")
    if not isinstance(scope_items, list) or not isinstance(batch_items, list):
        _reject("BATCH_ITEM_DRIFT", "frozen batch item list is invalid")
    if len(scope_items) != len(batch_items):
        _reject("BATCH_ITEM_DRIFT", "frozen batch item count has drifted")
    for ordinal, (scope_item, batch_item) in enumerate(zip(scope_items, batch_items), start=1):
        if (
            not isinstance(batch_item, dict)
            or batch_item.get("ordinal") != ordinal
            or batch_item.get("status") != "pending"
            or batch_item.get("target_identity_sha256") != scope_item.get("target_identity_sha256")
            or batch_item.get("item_snapshot") != scope_item
        ):
            _reject("BATCH_ITEM_DRIFT", "frozen batch item order or identity has drifted")

    page_state = scope.get("page_state")
    max_items = page_state.get("max_items") if isinstance(page_state, dict) else None
    if isinstance(max_items, bool) or not isinstance(max_items, int) or not 1 <= max_items <= 100:
        _reject("BATCH_SCOPE_SNAPSHOT_DRIFT", "frozen scope max_items is outside 1..100")
    if page_state.get("captured_count") != len(scope_items):
        _reject("BATCH_SCOPE_SNAPSHOT_DRIFT", "frozen captured_count conflicts with batch items")
    return max_items


def revalidate_frozen_scope(
    batch: dict[str, Any],
    capture: dict[str, Any],
    *,
    runtime_context: dict[str, Any],
    expected_browser_session_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    requested_max_items = validate_batch_for_approval(batch)
    frozen = batch.get("scope_snapshot")
    items = batch.get("items")
    if not isinstance(frozen, dict) or not isinstance(items, list) or not items:
        _reject("BATCH_SCOPE_INVALID", "edit batch has no frozen ordered scope")
    try:
        current = normalize_scope_capture(
            capture,
            requested_max_items=requested_max_items,
            runtime_context=runtime_context,
            expected_browser_session_id=expected_browser_session_id,
        )
    except ScopeContractError as exc:
        raise BatchApprovalContractError(exc.reason_code, str(exc)) from exc

    comparisons = (
        ("runtime_identity", "BATCH_RUNTIME_DRIFT", "runtime identity"),
        ("page_identity", "BATCH_PAGE_DRIFT", "draft-box page identity"),
        ("store_identity", "BATCH_STORE_DRIFT", "store identity"),
        ("filter_state", "BATCH_FILTER_DRIFT", "filter state"),
        ("sort_state", "BATCH_SORT_DRIFT", "sort state"),
        ("page_state", "BATCH_PAGE_STATE_DRIFT", "page state"),
        ("zero_write_proof", "BATCH_ZERO_WRITE_DRIFT", "zero-write proof"),
    )
    for key, reason_code, label in comparisons:
        if current.get(key) != frozen.get(key):
            _reject(reason_code, f"{label} changed after the batch scope was frozen")

    frozen_targets = _ordered_targets(frozen.get("items"))
    current_targets = _ordered_targets(current.get("items"))
    if current_targets != frozen_targets:
        _reject(
            "BATCH_TARGET_ORDER_DRIFT",
            "ordered target identities changed after the batch scope was frozen",
        )

    frozen_evidence = frozen.get("evidence")
    current_evidence = current.get("evidence")
    if not isinstance(frozen_evidence, dict) or not isinstance(current_evidence, dict):
        _reject("BATCH_DOM_DRIFT", "DOM evidence is missing from the frozen or current scope")
    frozen_dom = {
        "dom_sha256": frozen_evidence.get("dom_sha256"),
        "refs_digest": frozen_evidence.get("refs_digest"),
    }
    current_dom = {
        "dom_sha256": current_evidence.get("dom_sha256"),
        "refs_digest": current_evidence.get("refs_digest"),
    }
    if current_dom != frozen_dom:
        _reject("BATCH_DOM_DRIFT", "DOM double digest changed after the batch scope was frozen")

    ordered_target_digest = canonical_sha256(frozen_targets)
    attestation = {
        "kind": "scope_revalidation",
        "status": "matched",
        "captured_at": current.get("observed_at"),
        "frozen_scope_digest": batch.get("scope_snapshot_digest"),
        "revalidated_scope_digest": current.get("digest"),
        "ordered_target_digest": ordered_target_digest,
        "dom_sha256": current_dom["dom_sha256"],
        "refs_digest": current_dom["refs_digest"],
        "zero_write_digest": canonical_sha256(current["zero_write_proof"]),
    }
    return current, attestation


def issue_batch_approval(
    batch: dict[str, Any],
    current_scope: dict[str, Any],
    scope_revalidation: dict[str, Any],
    *,
    approved_by: str,
    confirmation: str,
    issued_at: datetime | None = None,
) -> dict[str, Any]:
    approver = str(approved_by or "").strip()
    if not approver:
        _reject("BATCH_APPROVER_REQUIRED", "approved_by must identify the approving operator")
    if confirmation != BATCH_APPROVAL_CONFIRMATION:
        _reject(
            "BATCH_CONFIRMATION_INVALID",
            f"confirmation must exactly equal {BATCH_APPROVAL_CONFIRMATION}",
        )

    issued = issued_at or datetime.now(timezone.utc)
    if issued.tzinfo is None:
        issued = issued.replace(tzinfo=timezone.utc)
    expires = issued + timedelta(seconds=BATCH_APPROVAL_TTL_SECONDS)
    issued_text = issued.isoformat()
    expires_text = expires.isoformat()
    lease_id = uuid.uuid4().hex
    token = secrets.token_urlsafe(32)
    ordered_targets = _ordered_targets(current_scope.get("items"))
    context = {
        "schema_version": BATCH_APPROVAL_CONTEXT_SCHEMA,
        "batch": {
            "id": batch.get("id"),
            "schema_version": batch.get("schema_version"),
            "required_status": "draft",
        },
        "scope": {
            "snapshot_id": batch.get("scope_snapshot_id"),
            "snapshot_digest": batch.get("scope_snapshot_digest"),
        },
        "template": {
            "id": batch.get("template_id"),
            "snapshot_digest": batch.get("template_snapshot_digest"),
        },
        "policy": {"digest": batch.get("policy_digest")},
        "ordered_targets": {
            "items": ordered_targets,
            "digest": canonical_sha256(ordered_targets),
        },
        "store_identity": current_scope.get("store_identity"),
        "runtime_identity": current_scope.get("runtime_identity"),
        "read_attestation": scope_revalidation,
        "approved_by": approver,
        "confirmation": confirmation,
        "lease_id": lease_id,
        "issued_at": issued_text,
        "expires_at": expires_text,
    }
    context_fingerprint = canonical_sha256(context)
    return {
        "token": token,
        "token_hash": hashlib.sha256(token.encode("utf-8")).hexdigest().upper(),
        "lease_id": lease_id,
        "context": {**context, "fingerprint": context_fingerprint},
        "approved_by": approver,
        "confirmation": confirmation,
        "issued_at": issued_text,
        "expires_at": expires_text,
        "scope_revalidation": scope_revalidation,
    }


def _ordered_targets(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        _reject("BATCH_SCOPE_INVALID", "ordered target list is missing")
    ordered: list[dict[str, Any]] = []
    for expected_ordinal, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            _reject("BATCH_SCOPE_INVALID", "ordered target item is invalid")
        item_snapshot = item.get("item_snapshot")
        source = item_snapshot if isinstance(item_snapshot, dict) else item
        ordinal = source.get("ordinal")
        target = source.get("target_identity")
        target_digest = source.get("target_identity_sha256")
        if ordinal != expected_ordinal or not isinstance(target, dict) or not isinstance(target_digest, str):
            _reject("BATCH_SCOPE_INVALID", "ordered target identity is incomplete")
        if not hmac.compare_digest(target_digest, canonical_sha256(target)):
            _reject("BATCH_SCOPE_INVALID", "ordered target identity digest is invalid")
        ordered.append(
            {
                "ordinal": expected_ordinal,
                "target_identity": target,
                "target_identity_sha256": target_digest,
            }
        )
    return ordered


def _reject(reason_code: str, detail: str) -> None:
    raise BatchApprovalContractError(reason_code, detail)
