"""纯合成公共投影，仅验证离线合同，不构成真实验收证据。"""

import hashlib
import json


def _digest(value):
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest().upper()


def _canonical_digest(value):
    return _digest(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def public_acceptance_export():
    product_ids = [91001, 91002, 91003]
    receipts, ledger = [], []
    for product_id in product_ids:
        for stage in ("SAVE1", "SAVE2"):
            identity = f"{product_id}-{stage}"
            command_id = f"private-command-{identity}"
            lease_id = f"private-lease-{identity}"
            receipts.append({
                "productId": product_id, "stage": stage,
                "canonicalReceiptSha256": _digest(f"canonical-{identity}"),
                "canonicalSaveReceiptSha256": _digest(f"save-{identity}"),
                "parentCanonicalReceiptSha256": _digest(f"parent-{product_id}"),
                "persisted": True, "commandId": command_id, "leaseId": lease_id,
                "mutationCount": 1, "publishCount": 0, "businessSuccess": True,
                **{key: _digest(f"{key}-{identity}") for key in (
                    "networkRequestSha256", "networkResponseSha256", "screenshotSha256",
                    "readbackSha256", "unpublishedReadbackSha256",
                )},
                "readbackEqual": True, "unpublished": True, "published": False,
            })
            ledger.append({
                "productId": product_id, "stage": stage,
                "commandId": command_id, "leaseId": lease_id,
                "physicalMutationCount": 1, "publishCount": 0, "status": "succeeded",
            })
    discovery_proofs = [_digest(f"discovery-proof-{index}") for index in range(5)]
    predecessor_scope = _digest("discovery-scope")
    discovery_receipt = _digest("discovery-receipt")
    formal_scope = _digest("formal-scope")
    formal_snapshot = _digest("formal-snapshot")
    formal_lineage = {
        "schemaVersion": "real_dxm_path_b_formal_lineage.v1",
        "predecessorScopeSha256": predecessor_scope,
        "discoveryReceiptSha256": discovery_receipt,
        "formalScopeSha256": formal_scope, "formalTaskId": 42,
        "formalSnapshotId": 62, "formalSnapshotSha256": formal_snapshot,
    }
    return {
        "schemaVersion": "real_dxm_path_b_acceptance_export.v1",
        "acceptanceStatus": "REAL_PATH_B_3_ACCEPTED",
        "task": {
            "id": 42, "status": "completed", "mode": "batch_draft_save", "path": "B",
            "orderedProductIds": product_ids, "unknownCount": 0, "autoRetryCount": 0,
        },
        "provenance": {
            "gitHead": "1" * 40, "worktreeClean": True,
            "runtimeInstanceId": "private-runtime-test", "browserRuntimeId": "private-browser-test",
            "browserSessionId": "private-session-test", "scopeSha256": formal_scope,
            "l2EvidenceFingerprint": _digest("l2"), "lineageConsistent": True,
        },
        "campaign": {
            "lineageConsistent": True, "discoveryReceiptValid": True,
            "continuationValid": True, "chronologyValid": True,
            "discoveryCountersValid": True, "formalCountersValid": True,
            "crossPhaseEvidenceDistinct": True, "crossPhaseAuthorityDistinct": True,
            "formalLineageSha256": _canonical_digest(formal_lineage),
            "predecessorScopeSha256": predecessor_scope,
            "discoveryReceiptSha256": discovery_receipt,
            "chronology": {
                "discoverySealedAt": "2026-08-31T00:00:00Z",
                "formalSnapshotCreatedAt": "2026-08-31T00:01:00Z",
                "formalTaskCreatedAt": "2026-08-31T00:02:00Z",
                "formalScopeIssuedAt": "2026-08-31T00:03:00Z",
                "formalScopePreparedAt": "2026-08-31T00:03:00Z",
                "formalApprovalApprovedAt": "2026-08-31T00:04:00Z",
            },
            "discovery": {
                "taskId": 41, "snapshotId": 61, "snapshotSha256": _digest("discovery-snapshot"),
                "scopeSha256": predecessor_scope, "productId": product_ids[0],
                "receiptSha256": discovery_receipt,
                "leafProofSha256s": discovery_proofs,
                "proofSetSha256": _canonical_digest(discovery_proofs),
                "commandRefSha256": _digest("discovery-command"),
                "leaseRefSha256": _digest("discovery-lease"),
                "counters": {
                    "physicalMutation": 1, "save1": 1, "save2": 0,
                    "otherProductMutation": 0, "publishRequest": 0, "unknown": 0,
                },
            },
            "formal": {
                "taskId": 42, "snapshotId": 62, "snapshotSha256": formal_snapshot,
                "scopeSha256": formal_scope,
                "counters": {
                    "physicalMutation": 6, "save1": 3, "save2": 3,
                    "publishRequest": 0, "unknown": 0, "autoRetry": 0,
                },
            },
            "totals": {
                "physicalMutation": 7, "save1": 4, "save2": 3,
                "publishRequest": 0, "unknown": 0, "autoRetry": 0,
            },
        },
        "orderedProducts": [
            {"ordinal": index, "productId": product_id, "jobId": 70 + index, "status": "succeeded"}
            for index, product_id in enumerate(product_ids, 1)
        ],
        "capabilities": {
            name: {"status": "passed", "evidenceSha256": _digest(name)}
            for name in ("video", "wholesale", "translation", "semi_managed", "rollback_preparation")
        },
        "saveReceipts": receipts, "mutationLedger": ledger,
        "publish": {"allowed": False, "requestCount": 0, "published": False, "finalReadbackPublished": False},
        "writerFence": {"shopId": 91, "enforced": True, "conflictCount": 0, "released": True},
        "blockers": [],
    }
