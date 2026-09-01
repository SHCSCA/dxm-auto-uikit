from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


EXPORT_SCHEMA = "real_dxm_path_b_acceptance_export.v1"
RECORD_SCHEMA = "real_dxm_path_b_acceptance_record.v1"
ACCEPTED_VERDICT = "REAL_PATH_B_3_ACCEPTED"
BLOCKED_VERDICT = "INTERNAL_NON_READY"
REQUIRED_CAPABILITIES = (
    "video",
    "wholesale",
    "translation",
    "semi_managed",
    "rollback_preparation",
)
SAVE_STAGES = ("SAVE1", "SAVE2")
TERMINAL_SUCCESS = frozenset({"completed", "succeeded", "passed", "verified", "success"})
SHA256_RE = re.compile(r"^[0-9A-F]{64}$")
GIT_HEAD_RE = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
BLOCKER_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,119}$")


class AcceptanceInputError(ValueError):
    """The supplied file is not a public, redacted acceptance export."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def _canonical_sha256(value: Any) -> str:
    return _sha256_bytes(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    )


def _opaque_ref(label: str, value: Any) -> str | None:
    if value is None:
        return None
    return _sha256_bytes(f"{label}:{value}".encode("utf-8"))


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and SHA256_RE.fullmatch(value) is not None


def _is_non_empty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value == value.strip()


def _is_positive_int(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value > 0


def _utc_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return []


def _safe_blocker(value: Any) -> dict[str, str]:
    if isinstance(value, Mapping):
        code = value.get("code") or value.get("reasonCode") or value.get("reason_code")
        status = value.get("status") or "blocked"
        normalized_code = str(code or "")
        return {
            "code": (
                normalized_code
                if BLOCKER_CODE_RE.fullmatch(normalized_code)
                else "INVALID_BLOCKER_CODE"
            ),
            "status": (
                str(status)
                if str(status) in {"blocked", "non_ready"}
                else "blocked"
            ),
        }
    normalized_code = str(value or "")
    return {
        "code": (
            normalized_code
            if BLOCKER_CODE_RE.fullmatch(normalized_code)
            else "INVALID_BLOCKER_CODE"
        ),
        "status": "blocked",
    }


def _capability_map(value: Any) -> dict[str, dict[str, Any]]:
    if isinstance(value, Mapping):
        return {str(name): _mapping(details) for name, details in value.items()}
    result: dict[str, dict[str, Any]] = {}
    for item in _sequence(value):
        details = _mapping(item)
        name = details.get("name") or details.get("capability")
        if _is_non_empty_text(name):
            result[str(name)] = details
    return result


def _receipt_summary(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "productRefSha256": _opaque_ref("product", value.get("productId")),
        "stage": value.get("stage"),
        "canonicalReceiptSha256": value.get("canonicalReceiptSha256"),
        "canonicalSaveReceiptSha256": value.get("canonicalSaveReceiptSha256"),
        "parentCanonicalReceiptSha256": value.get("parentCanonicalReceiptSha256"),
        "persisted": value.get("persisted"),
        "commandRefSha256": _opaque_ref("command", value.get("commandId")),
        "leaseRefSha256": _opaque_ref("lease", value.get("leaseId")),
        "mutationCount": value.get("mutationCount"),
        "publishCount": value.get("publishCount"),
        "networkRequestSha256": value.get("networkRequestSha256"),
        "networkResponseSha256": value.get("networkResponseSha256"),
        "businessSuccess": value.get("businessSuccess"),
        "screenshotSha256": value.get("screenshotSha256"),
        "readbackSha256": value.get("readbackSha256"),
        "unpublishedReadbackSha256": value.get("unpublishedReadbackSha256"),
        "readbackEqual": value.get("readbackEqual"),
        "unpublished": value.get("unpublished"),
        "published": value.get("published"),
    }


def _ledger_summary(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "productRefSha256": _opaque_ref("product", value.get("productId")),
        "stage": value.get("stage"),
        "commandRefSha256": _opaque_ref("command", value.get("commandId")),
        "leaseRefSha256": _opaque_ref("lease", value.get("leaseId")),
        "physicalMutationCount": value.get("physicalMutationCount"),
        "publishCount": value.get("publishCount"),
        "status": value.get("status"),
    }


def _check(checks: list[dict[str, Any]], code: str, passed: bool, detail: str) -> bool:
    checks.append({"code": code, "passed": bool(passed), "detail": detail})
    return bool(passed)


def build_acceptance_record(
    exported: Mapping[str, Any],
    *,
    source_bytes: bytes,
    source_name: str,
) -> dict[str, Any]:
    """Build a fail-closed record from one normalized public API export.

    No SQLite, screenshot, browser, or private adapter access is permitted.
    The service-side authority gates must already be true; this offline step
    then recomputes the redacted export's hash, cardinality, chronology, and
    cross-phase consistency instead of treating its final verdict as proof.
    """

    root = _mapping(exported)
    if not root:
        raise AcceptanceInputError("acceptance export must be a JSON object")

    checks: list[dict[str, Any]] = []
    task = _mapping(root.get("task"))
    provenance = _mapping(root.get("provenance"))
    campaign = _mapping(root.get("campaign"))
    products = [_mapping(item) for item in _sequence(root.get("orderedProducts"))]
    capabilities = _capability_map(root.get("capabilities"))
    receipts = [_mapping(item) for item in _sequence(root.get("saveReceipts"))]
    ledger = [_mapping(item) for item in _sequence(root.get("mutationLedger"))]
    publish = _mapping(root.get("publish"))
    writer_fence = _mapping(root.get("writerFence"))
    raw_blockers = _sequence(root.get("blockers"))
    blockers = [_safe_blocker(item) for item in raw_blockers]

    required_sections = (
        "task",
        "provenance",
        "campaign",
        "orderedProducts",
        "capabilities",
        "saveReceipts",
        "mutationLedger",
        "publish",
        "writerFence",
        "blockers",
    )
    _check(
        checks,
        "EXPORT_SCHEMA",
        root.get("schemaVersion") == EXPORT_SCHEMA,
        f"schemaVersion must be {EXPORT_SCHEMA}",
    )
    _check(
        checks,
        "EXPORT_SECTIONS_COMPLETE",
        all(name in root for name in required_sections),
        "all normalized public acceptance sections must be present",
    )

    task_product_ids = _sequence(task.get("orderedProductIds"))
    _check(
        checks,
        "TASK_CONTRACT",
        _is_positive_int(task.get("id"))
        and task.get("mode") == "batch_draft_save"
        and task.get("path") == "B"
        and str(task.get("status") or "").lower() in TERMINAL_SUCCESS,
        "task must be one successful terminal batch_draft_save Path B task",
    )
    _check(checks, "TASK_NO_UNKNOWN", task.get("unknownCount") == 0, "UNKNOWN count must be exactly zero")
    _check(checks, "TASK_NO_AUTO_RETRY", task.get("autoRetryCount") == 0, "automatic retry count must be exactly zero")

    product_ids = [item.get("productId") for item in products]
    product_order_ok = (
        len(products) == 3
        and [item.get("ordinal") for item in products] == [1, 2, 3]
        and all(_is_positive_int(value) for value in product_ids)
        and len(set(product_ids)) == 3
        and product_ids == task_product_ids
        and all(
            _is_positive_int(item.get("jobId"))
            and str(item.get("status") or "").lower() in TERMINAL_SUCCESS
            for item in products
        )
    )
    _check(
        checks,
        "THREE_PRODUCTS_ORDERED",
        product_order_ok,
        "exactly three unique jobs must succeed in frozen product order",
    )

    discovery_campaign = _mapping(campaign.get("discovery"))
    discovery_counters = _mapping(discovery_campaign.get("counters"))
    formal_campaign = _mapping(campaign.get("formal"))
    formal_counters = _mapping(formal_campaign.get("counters"))
    campaign_totals = _mapping(campaign.get("totals"))
    chronology = _mapping(campaign.get("chronology"))
    discovery_leaf_proofs = _sequence(
        discovery_campaign.get("leafProofSha256s")
    )
    formal_leaf_proofs = [
        receipt.get(key)
        for receipt in receipts
        for key in (
            "networkRequestSha256",
            "networkResponseSha256",
            "screenshotSha256",
            "readbackSha256",
            "unpublishedReadbackSha256",
        )
    ]
    discovery_proof_set_ok = bool(
        len(discovery_leaf_proofs) == 5
        and all(_is_sha256(value) for value in discovery_leaf_proofs)
        and len(set(discovery_leaf_proofs)) == 5
        and _is_sha256(discovery_campaign.get("proofSetSha256"))
        and discovery_campaign.get("proofSetSha256")
        == _canonical_sha256(discovery_leaf_proofs)
    )
    cross_phase_evidence_ok = bool(
        discovery_proof_set_ok
        and len(formal_leaf_proofs) == 30
        and all(_is_sha256(value) for value in formal_leaf_proofs)
        and len(set(formal_leaf_proofs)) == 30
        and set(discovery_leaf_proofs).isdisjoint(formal_leaf_proofs)
    )
    discovery_command_ref = discovery_campaign.get("commandRefSha256")
    discovery_lease_ref = discovery_campaign.get("leaseRefSha256")
    formal_command_refs = [
        _opaque_ref("command", receipt.get("commandId")) for receipt in receipts
    ]
    formal_lease_refs = [
        _opaque_ref("lease", receipt.get("leaseId")) for receipt in receipts
    ]
    cross_phase_authority_ok = bool(
        _is_sha256(discovery_command_ref)
        and _is_sha256(discovery_lease_ref)
        and len(formal_command_refs) == 6
        and len(formal_lease_refs) == 6
        and all(_is_sha256(value) for value in formal_command_refs)
        and all(_is_sha256(value) for value in formal_lease_refs)
        and len(set(formal_command_refs)) == 6
        and len(set(formal_lease_refs)) == 6
        and discovery_command_ref not in formal_command_refs
        and discovery_lease_ref not in formal_lease_refs
    )
    chronology_times = {
        key: _utc_time(chronology.get(key))
        for key in (
            "discoverySealedAt",
            "formalSnapshotCreatedAt",
            "formalTaskCreatedAt",
            "formalScopeIssuedAt",
            "formalScopePreparedAt",
            "formalApprovalApprovedAt",
        )
    }
    chronology_ok = all(value is not None for value in chronology_times.values())
    if chronology_ok:
        discovery_sealed_at = chronology_times["discoverySealedAt"]
        formal_snapshot_created_at = chronology_times["formalSnapshotCreatedAt"]
        formal_task_created_at = chronology_times["formalTaskCreatedAt"]
        formal_scope_issued_at = chronology_times["formalScopeIssuedAt"]
        formal_scope_prepared_at = chronology_times["formalScopePreparedAt"]
        formal_approval_approved_at = chronology_times["formalApprovalApprovedAt"]
        chronology_ok = bool(
            all(
                value > discovery_sealed_at
                for key, value in chronology_times.items()
                if key != "discoverySealedAt"
            )
            and formal_snapshot_created_at <= formal_task_created_at
            and formal_task_created_at
            <= min(formal_scope_issued_at, formal_scope_prepared_at)
            and not (
                formal_scope_prepared_at < formal_scope_issued_at
                and formal_scope_issued_at - formal_scope_prepared_at
                >= timedelta(seconds=1)
            )
            and max(formal_scope_issued_at, formal_scope_prepared_at)
            <= formal_approval_approved_at
            and formal_approval_approved_at <= datetime.now(timezone.utc)
        )
    expected_formal_lineage_sha256 = _canonical_sha256(
        {
            "schemaVersion": "real_dxm_path_b_formal_lineage.v1",
            "predecessorScopeSha256": campaign.get("predecessorScopeSha256"),
            "discoveryReceiptSha256": campaign.get("discoveryReceiptSha256"),
            "formalScopeSha256": formal_campaign.get("scopeSha256"),
            "formalTaskId": formal_campaign.get("taskId"),
            "formalSnapshotId": formal_campaign.get("snapshotId"),
            "formalSnapshotSha256": formal_campaign.get("snapshotSha256"),
        }
    )
    discovery_formal_ok = bool(
        campaign.get("lineageConsistent") is True
        and campaign.get("discoveryReceiptValid") is True
        and campaign.get("continuationValid") is True
        and campaign.get("chronologyValid") is True
        and chronology_ok
        and campaign.get("discoveryCountersValid") is True
        and campaign.get("formalCountersValid") is True
        and campaign.get("crossPhaseEvidenceDistinct") is True
        and cross_phase_evidence_ok
        and campaign.get("crossPhaseAuthorityDistinct") is True
        and cross_phase_authority_ok
        and _is_sha256(campaign.get("formalLineageSha256"))
        and campaign.get("formalLineageSha256")
        == expected_formal_lineage_sha256
        and _is_sha256(campaign.get("predecessorScopeSha256"))
        and _is_sha256(campaign.get("discoveryReceiptSha256"))
        and _is_positive_int(discovery_campaign.get("taskId"))
        and _is_positive_int(discovery_campaign.get("snapshotId"))
        and _is_sha256(discovery_campaign.get("snapshotSha256"))
        and _is_sha256(discovery_campaign.get("scopeSha256"))
        and discovery_campaign.get("scopeSha256")
        == campaign.get("predecessorScopeSha256")
        and _is_positive_int(discovery_campaign.get("productId"))
        and discovery_campaign.get("productId") == (
            product_ids[0] if product_ids else None
        )
        and discovery_campaign.get("receiptSha256")
        == campaign.get("discoveryReceiptSha256")
        and discovery_proof_set_ok
        and discovery_counters
        == {
            "physicalMutation": 1,
            "save1": 1,
            "save2": 0,
            "otherProductMutation": 0,
            "publishRequest": 0,
            "unknown": 0,
        }
        and formal_campaign.get("taskId") == task.get("id")
        and _is_positive_int(formal_campaign.get("snapshotId"))
        and _is_sha256(formal_campaign.get("snapshotSha256"))
        and formal_campaign.get("scopeSha256") == provenance.get("scopeSha256")
        and formal_counters
        == {
            "physicalMutation": 6,
            "save1": 3,
            "save2": 3,
            "publishRequest": 0,
            "unknown": 0,
            "autoRetry": 0,
        }
        and campaign_totals
        == {
            "physicalMutation": 7,
            "save1": 4,
            "save2": 3,
            "publishRequest": 0,
            "unknown": 0,
            "autoRetry": 0,
        }
        and discovery_campaign.get("taskId") != formal_campaign.get("taskId")
        and discovery_campaign.get("snapshotId")
        != formal_campaign.get("snapshotId")
        and discovery_campaign.get("snapshotSha256")
        != formal_campaign.get("snapshotSha256")
        and discovery_campaign.get("scopeSha256")
        != formal_campaign.get("scopeSha256")
    )
    _check(
        checks,
        "DISCOVERY_FORMAL_CAMPAIGN_BOUND",
        discovery_formal_ok,
        "one sealed first-product Discovery SAVE1 must causally bind a fresh exact-three-product Formal run without authority or proof reuse",
    )

    capability_rows: dict[str, dict[str, Any]] = {}
    capabilities_ok = set(capabilities) == set(REQUIRED_CAPABILITIES)
    for name in REQUIRED_CAPABILITIES:
        details = capabilities.get(name, {})
        capability_rows[name] = {
            "status": details.get("status"),
            "evidenceSha256": details.get("evidenceSha256"),
        }
        capabilities_ok = capabilities_ok and (
            str(details.get("status") or "").lower() in TERMINAL_SUCCESS
            and _is_sha256(details.get("evidenceSha256"))
        )
    _check(
        checks,
        "FIVE_CAPABILITIES_VERIFIED",
        capabilities_ok,
        "all five mandatory capabilities need successful, hash-bound evidence",
    )

    expected_pairs = {
        (product_id, stage)
        for product_id in product_ids
        for stage in SAVE_STAGES
        if _is_positive_int(product_id)
    }
    receipt_pairs: set[tuple[Any, Any]] = set()
    command_ids: list[Any] = []
    lease_ids: list[Any] = []
    canonical_stage_hashes: list[Any] = []
    canonical_save_hashes: list[Any] = []
    parent_receipt_hashes: list[Any] = []
    parent_hashes_by_product: dict[Any, set[Any]] = {}
    proof_hashes: list[Any] = []
    receipts_ok = len(receipts) == 6
    for receipt in receipts:
        pair = (receipt.get("productId"), receipt.get("stage"))
        receipt_pairs.add(pair)
        command_ids.append(receipt.get("commandId"))
        lease_ids.append(receipt.get("leaseId"))
        canonical_stage_hashes.append(receipt.get("canonicalReceiptSha256"))
        canonical_save_hashes.append(receipt.get("canonicalSaveReceiptSha256"))
        parent_receipt_hashes.append(receipt.get("parentCanonicalReceiptSha256"))
        parent_hashes_by_product.setdefault(receipt.get("productId"), set()).add(
            receipt.get("parentCanonicalReceiptSha256")
        )
        receipt_proofs = [
            receipt.get("networkRequestSha256"),
            receipt.get("networkResponseSha256"),
            receipt.get("screenshotSha256"),
            receipt.get("readbackSha256"),
            receipt.get("unpublishedReadbackSha256"),
        ]
        proof_hashes.extend(receipt_proofs)
        receipts_ok = receipts_ok and (
            pair in expected_pairs
            and receipt.get("persisted") is True
            and _is_sha256(receipt.get("canonicalReceiptSha256"))
            and _is_sha256(receipt.get("canonicalSaveReceiptSha256"))
            and _is_sha256(receipt.get("parentCanonicalReceiptSha256"))
            and _is_non_empty_text(receipt.get("commandId"))
            and _is_non_empty_text(receipt.get("leaseId"))
            and receipt.get("mutationCount") == 1
            and receipt.get("publishCount") == 0
            and receipt.get("businessSuccess") is True
            and all(_is_sha256(value) for value in receipt_proofs)
            and receipt.get("readbackEqual") is True
            and receipt.get("unpublished") is True
            and receipt.get("published") is False
        )
    receipts_ok = receipts_ok and receipt_pairs == expected_pairs
    receipts_ok = receipts_ok and len(set(command_ids)) == 6 and len(set(lease_ids)) == 6
    receipts_ok = receipts_ok and len(set(canonical_stage_hashes)) == 6
    receipts_ok = receipts_ok and len(set(canonical_save_hashes)) == 6
    receipts_ok = receipts_ok and set(parent_hashes_by_product) == set(product_ids)
    receipts_ok = receipts_ok and all(
        len(parent_hashes_by_product.get(product_id, set())) == 1
        for product_id in product_ids
    )
    receipts_ok = receipts_ok and len(
        {
            next(iter(parent_hashes_by_product[product_id]))
            for product_id in product_ids
            if len(parent_hashes_by_product.get(product_id, set())) == 1
        }
    ) == 3
    receipts_ok = receipts_ok and all(
        parent_receipt_hashes.count(value) == 2
        for value in set(parent_receipt_hashes)
    )
    receipts_ok = receipts_ok and len(proof_hashes) == 30 and len(set(proof_hashes)) == 30
    _check(
        checks,
        "SIX_CANONICAL_RECEIPTS",
        receipts_ok,
        "SAVE1/SAVE2 require six independently persisted canonical receipts, commands, leases and complete non-reused proofs",
    )

    ledger_pairs: set[tuple[Any, Any]] = set()
    ledger_by_pair: dict[tuple[Any, Any], dict[str, Any]] = {}
    ledger_ok = len(ledger) == 6
    for entry in ledger:
        pair = (entry.get("productId"), entry.get("stage"))
        ledger_pairs.add(pair)
        ledger_by_pair[pair] = entry
        ledger_ok = ledger_ok and (
            pair in expected_pairs
            and _is_non_empty_text(entry.get("commandId"))
            and _is_non_empty_text(entry.get("leaseId"))
            and entry.get("physicalMutationCount") == 1
            and entry.get("publishCount") == 0
            and str(entry.get("status") or "").lower() in TERMINAL_SUCCESS
        )
    ledger_ok = ledger_ok and ledger_pairs == expected_pairs
    for receipt in receipts:
        pair = (receipt.get("productId"), receipt.get("stage"))
        entry = ledger_by_pair.get(pair, {})
        ledger_ok = ledger_ok and (
            entry.get("commandId") == receipt.get("commandId")
            and entry.get("leaseId") == receipt.get("leaseId")
        )
    _check(
        checks,
        "MUTATION_LEDGER_EXACT",
        ledger_ok,
        "ledger must contain exactly one successful physical mutation for each SAVE receipt",
    )

    publish_ok = (
        publish.get("allowed") is False
        and publish.get("requestCount") == 0
        and publish.get("published") is False
        and publish.get("finalReadbackPublished") is False
    )
    _check(
        checks,
        "ZERO_PUBLISH",
        publish_ok,
        "publish intent, requests and final readback must all remain false/zero",
    )

    writer_fence_ok = (
        _is_positive_int(writer_fence.get("shopId"))
        and writer_fence.get("enforced") is True
        and writer_fence.get("conflictCount") == 0
        and writer_fence.get("released") is True
    )
    _check(
        checks,
        "WRITER_FENCE_CLOSED",
        writer_fence_ok,
        "the single-shop writer fence must be enforced, conflict-free and released",
    )

    provenance_ok = (
        isinstance(provenance.get("gitHead"), str)
        and GIT_HEAD_RE.fullmatch(provenance.get("gitHead")) is not None
        and provenance.get("worktreeClean") is True
        and _is_non_empty_text(provenance.get("runtimeInstanceId"))
        and _is_non_empty_text(provenance.get("browserRuntimeId"))
        and _is_non_empty_text(provenance.get("browserSessionId"))
        and _is_sha256(provenance.get("scopeSha256"))
        and _is_sha256(provenance.get("l2EvidenceFingerprint"))
        and provenance.get("lineageConsistent") is True
    )
    _check(
        checks,
        "PROVENANCE_BOUND",
        provenance_ok,
        "clean Git, runtime, browser session, scope and fresh L2 must share one lineage",
    )
    _check(
        checks,
        "NO_BLOCKERS",
        "blockers" in root and len(raw_blockers) == 0,
        "the public export must contain an explicit empty blockers list",
    )

    accepted = all(item["passed"] is True for item in checks)
    failed_codes = [item["code"] for item in checks if item["passed"] is not True]
    if failed_codes:
        blockers.extend({"code": code, "status": "blocked"} for code in failed_codes)

    return {
        "schemaVersion": RECORD_SCHEMA,
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "verdict": ACCEPTED_VERDICT if accepted else BLOCKED_VERDICT,
        "ready": accepted,
        "sourceManifest": {
            "sourceKind": "public_api_export_json",
            "sizeBytes": len(source_bytes),
            "sha256": _sha256_bytes(source_bytes),
            "apiSchemaVersion": root.get("schemaVersion"),
        },
        "task": {
            "taskRefSha256": _opaque_ref("task", task.get("id")),
            "status": task.get("status"),
            "mode": task.get("mode"),
            "path": task.get("path"),
            "unknownCount": task.get("unknownCount"),
            "autoRetryCount": task.get("autoRetryCount"),
        },
        "provenance": {
            "gitHead": provenance.get("gitHead"),
            "worktreeClean": provenance.get("worktreeClean"),
            "runtimeInstanceRefSha256": _opaque_ref("runtime", provenance.get("runtimeInstanceId")),
            "browserRuntimeRefSha256": _opaque_ref("browser-runtime", provenance.get("browserRuntimeId")),
            "browserSessionRefSha256": _opaque_ref("browser-session", provenance.get("browserSessionId")),
            "scopeSha256": provenance.get("scopeSha256"),
            "l2EvidenceFingerprint": provenance.get("l2EvidenceFingerprint"),
            "lineageConsistent": provenance.get("lineageConsistent"),
        },
        "campaign": {
            "lineageConsistent": campaign.get("lineageConsistent"),
            "chronologyValid": campaign.get("chronologyValid"),
            "formalLineageSha256": campaign.get("formalLineageSha256"),
            "predecessorScopeSha256": campaign.get("predecessorScopeSha256"),
            "discoveryReceiptSha256": campaign.get("discoveryReceiptSha256"),
            "chronology": chronology,
            "discovery": {
                "taskRefSha256": _opaque_ref(
                    "task", discovery_campaign.get("taskId")
                ),
                "snapshotRefSha256": _opaque_ref(
                    "snapshot", discovery_campaign.get("snapshotId")
                ),
                "snapshotSha256": discovery_campaign.get("snapshotSha256"),
                "scopeSha256": discovery_campaign.get("scopeSha256"),
                "productRefSha256": _opaque_ref(
                    "product", discovery_campaign.get("productId")
                ),
                "receiptSha256": discovery_campaign.get("receiptSha256"),
                "proofSetSha256": discovery_campaign.get("proofSetSha256"),
                "leafProofCount": len(discovery_leaf_proofs),
                "commandRefSha256": discovery_command_ref,
                "leaseRefSha256": discovery_lease_ref,
                "counters": discovery_counters,
            },
            "formal": {
                "taskRefSha256": _opaque_ref("task", formal_campaign.get("taskId")),
                "snapshotRefSha256": _opaque_ref(
                    "snapshot", formal_campaign.get("snapshotId")
                ),
                "snapshotSha256": formal_campaign.get("snapshotSha256"),
                "scopeSha256": formal_campaign.get("scopeSha256"),
                "counters": formal_counters,
            },
            "totals": campaign_totals,
            "crossPhaseEvidenceDistinct": campaign.get(
                "crossPhaseEvidenceDistinct"
            ),
            "crossPhaseAuthorityDistinct": campaign.get(
                "crossPhaseAuthorityDistinct"
            ),
        },
        "orderedProducts": [
            {
                "ordinal": item.get("ordinal"),
                "productRefSha256": _opaque_ref("product", item.get("productId")),
                "jobRefSha256": _opaque_ref("job", item.get("jobId")),
                "status": item.get("status"),
            }
            for item in products
        ],
        "capabilities": capability_rows,
        "saveReceipts": [_receipt_summary(item) for item in receipts],
        "mutationLedger": [_ledger_summary(item) for item in ledger],
        "zeroPublish": {
            "allowed": publish.get("allowed"),
            "requestCount": publish.get("requestCount"),
            "published": publish.get("published"),
            "finalReadbackPublished": publish.get("finalReadbackPublished"),
        },
        "writerFence": {
            "shopRefSha256": _opaque_ref("shop", writer_fence.get("shopId")),
            "enforced": writer_fence.get("enforced"),
            "conflictCount": writer_fence.get("conflictCount"),
            "released": writer_fence.get("released"),
        },
        "checks": checks,
        "blockers": blockers,
    }


def load_public_export(path: str | Path) -> tuple[dict[str, Any], bytes, str]:
    if str(path) == "-":
        source_bytes = sys.stdin.buffer.read()
        source_name = "stdin-acceptance-export.json"
    else:
        input_path = Path(path)
        source_bytes = input_path.read_bytes()
        source_name = input_path.name
    if not source_bytes:
        raise AcceptanceInputError("acceptance export is empty")
    try:
        decoded = json.loads(source_bytes.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AcceptanceInputError("acceptance export must be valid UTF-8 JSON") from exc
    if not isinstance(decoded, dict):
        raise AcceptanceInputError("acceptance export must be a JSON object")
    return decoded, source_bytes, source_name


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build a fail-closed Path B v1 acceptance record from the redacted "
            "GET /api/tasks/{id}/acceptance-export response."
        )
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Public API export JSON file, or '-' for stdin. SQLite is not supported.",
    )
    parser.add_argument(
        "--output",
        help="Optional JSON record path. The record is printed to stdout when omitted.",
    )
    args = parser.parse_args()

    try:
        exported, source_bytes, source_name = load_public_export(args.input)
        record = build_acceptance_record(
            exported,
            source_bytes=source_bytes,
            source_name=source_name,
        )
    except (AcceptanceInputError, OSError, TypeError, ValueError) as exc:
        print(f"ACCEPTANCE_INPUT_REJECTED: {exc}", file=sys.stderr)
        return 2

    rendered = json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(rendered)

    if record["ready"] is not True:
        print(
            "INTERNAL_NON_READY: public acceptance evidence is incomplete or inconsistent",
            file=sys.stderr,
        )
        return 2
    print(ACCEPTED_VERDICT, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
