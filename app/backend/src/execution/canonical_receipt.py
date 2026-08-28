"""
CanonicalReceipt Module — R5 · DXM Path B

Unified evidence producer/consumer contract for the V1 execution pipeline.

Replaces the shallow in-memory EvidenceCollector in services/evidence_collector.py
with a durable, structured receipt that covers:
  - producer field readback (before/after values at each section)
  - two-stage SAVE verification (first_save / second_save)
  - three-proof chain per save (screenshot, network, unpublished status)
  - persistent evidence (files in job_evidences table)
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class ReceiptPhase(StrEnum):
    """Receipt phase identifiers matching the two-stage state machine."""

    PHASE_1_FIRST_SAVE = "phase_1_first_save"
    PHASE_2_SECOND_SAVE = "phase_2_second_save"
    CONTENT_FINALIZE_WHOLESALE = "content_finalize_wholesale"
    CONTENT_FINALIZE_VIDEO = "content_finalize_video"
    CONTENT_FINALIZE_TRANSLATION = "content_finalize_translation"
    SEMI_MANAGED_ENTRY = "semi_managed_entry"
    ROLLBACK_PREPARATION = "rollback_preparation"


class SaveProofKind(StrEnum):
    """One of the three proofs required for each SAVE."""

    SCREENSHOT = "screenshot"      # Visual confirmation of save success modal
    NETWORK_REQUEST = "network_request"  # HTTP save API request
    NETWORK_RESPONSE = "network_response"  # HTTP save API response
    UNPUBLISHED_STATUS = "unpublished_status"  # Store readback showing unpublished state


@dataclass
class FieldReadback:
    """Before/after readback for a single field."""

    field_key: str           # e.g. "title", "price", "wholesale_tier_1_quantity"
    field_label: str         # Chinese display name
    source: str              # fixed / fill / dxm_template_ref / current_value
    before_value: Any | None
    after_value: Any | None
    readback_proven: bool    # True if after_value was read back from store
    timestamp: str | None     # ISO-8601 when readback was captured


@dataclass
class SaveProof:
    """One of three proofs for a SAVE operation."""

    proof_kind: SaveProofKind
    file_path: str | None    # Path to persisted evidence file (may be None for network)
    network_url: str | None
    network_method: str | None
    network_status: int | None
    body_sha256: str | None  # SHA-256 of request/response body for integrity
    timestamp: str | None
    proven: bool = False      # True when evidence has been verified


@dataclass
class SaveReceipt:
    """Complete receipt for one SAVE operation (first_save or second_save)."""

    save_phase: ReceiptPhase
    save_lease_id: str       # From ControlledMutationDispatch
    action_grant_id: str      # From ControlledMutationDispatch
    proofs: dict[SaveProofKind, SaveProof] = field(default_factory=dict)
    field_readbacks: list[FieldReadback] = field(default_factory=list)
    save_result_ok: bool | None = None
    error_code: str | None = None
    error_detail: str | None = None
    unresolved: bool = False   # True when dispatch result is uncertain → UNKNOWN
    canonical_save_receipt_sha256: str | None = None

    def _serialize_proofs(self) -> dict[str, Any]:
        return {
            kind.value: {
                "file_path": p.file_path,
                "network_url": p.network_url,
                "network_method": p.network_method,
                "network_status": p.network_status,
                "body_sha256": p.body_sha256,
                "timestamp": p.timestamp,
                "proven": p.proven,
            }
            for kind, p in self.proofs.items()
        }

    def compute_sha256(self) -> str:
        """Deterministic SHA-256 of this save receipt."""
        canonical = {
            "save_phase": self.save_phase.value,
            "save_lease_id": self.save_lease_id,
            "action_grant_id": self.action_grant_id,
            "save_result_ok": self.save_result_ok,
            "error_code": self.error_code,
            "unresolved": self.unresolved,
            "proofs": self._serialize_proofs(),
            "field_readbacks": [
                {
                    "field_key": fr.field_key,
                    "source": fr.source,
                    "readback_proven": fr.readback_proven,
                }
                for fr in self.field_readbacks
            ],
        }
        canonical_json = json.dumps(canonical, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

    def finalize(self) -> str:
        """Freeze the receipt and return its canonical SHA-256."""
        if self.canonical_save_receipt_sha256 is None:
            self.canonical_save_receipt_sha256 = self.compute_sha256()
        return self.canonical_save_receipt_sha256


@dataclass
class ContentFinalizeReceipt:
    """Receipt for one ContentFinalize step (wholesale / video / translation)."""

    phase: ReceiptPhase
    action_grant_id: str
    result_ok: bool | None = None
    error_code: str | None = None
    error_detail: str | None = None
    unresolved: bool = False
    field_readbacks: list[FieldReadback] = field(default_factory=list)
    media_identity: str | None = None  # For video: final media ID
    canonical_sha256: str | None = None

    def compute_sha256(self) -> str:
        canonical = {
            "phase": self.phase.value,
            "action_grant_id": self.action_grant_id,
            "result_ok": self.result_ok,
            "error_code": self.error_code,
            "unresolved": self.unresolved,
            "media_identity": self.media_identity,
        }
        canonical_json = json.dumps(canonical, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

    def finalize(self) -> str:
        if self.canonical_sha256 is None:
            self.canonical_sha256 = self.compute_sha256()
        return self.canonical_sha256


@dataclass
class CanonicalReceipt:
    """
    Unified receipt for the full execution of one product (one job).

    This replaces the shallow in-memory EvidenceCollector with a durable,
    structured contract that covers all five mandatory capabilities, two-stage
    SAVE with three-proof chain, and persistent evidence.

    Flow:
      1. Runner creates CanonicalReceipt at job start
      2. Each ContentFinalize step appends a ContentFinalizeReceipt
      3. Each SAVE appends a SaveReceipt with three proofs
      4. On job completion, receipt is finalized (SHA-256 frozen)
      5. Receipt is persisted via Repository.add_receipt() / add_evidence()
    """

    task_id: int
    job_id: int
    product_id: int | None

    # Execution metadata
    mode: str
    claim_mark: str
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: str | None = None
    canonical_receipt_sha256: str | None = None

    # Five mandatory capability results (video / translation / wholesale /
    # semiManaged / rollbackPreparation)
    content_finalize_receipts: list[ContentFinalizeReceipt] = field(default_factory=list)
    save_receipts: list[SaveReceipt] = field(default_factory=list)

    # Per-field readback across all phases
    all_field_readbacks: list[FieldReadback] = field(default_factory=list)

    # Rollback
    rollback_prepared: bool = False
    rollback_preimage_sha256: str | None = None
    rollback_performed: bool = False
    rollback_success: bool | None = None
    rollback_reason: str | None = None

    # Terminal state
    job_status: str | None = None          # succeeded / failed / unknown
    error_code: str | None = None
    error_detail: str | None = None
    needs_manual_review: bool = False

    def add_content_finalize_receipt(self, receipt: ContentFinalizeReceipt) -> None:
        self.content_finalize_receipts.append(receipt)
        if receipt.field_readbacks:
            self.all_field_readbacks.extend(receipt.field_readbacks)

    def add_save_receipt(self, receipt: SaveReceipt) -> None:
        self.save_receipts.append(receipt)
        if receipt.field_readbacks:
            self.all_field_readbacks.extend(receipt.field_readbacks)

    def mark_rollback_prepared(self, preimage_sha256: str) -> None:
        self.rollback_prepared = True
        self.rollback_preimage_sha256 = preimage_sha256

    def mark_rollback_performed(self, success: bool, reason: str) -> None:
        self.rollback_performed = True
        self.rollback_success = success
        self.rollback_reason = reason

    def mark_unknown(self, error_code: str, error_detail: str) -> None:
        """Mark the entire job as UNKNOWN — no auto-retry permitted."""
        self.job_status = "unknown"
        self.error_code = error_code
        self.error_detail = error_detail
        self.needs_manual_review = True

    def mark_failed(self, error_code: str, error_detail: str) -> None:
        self.job_status = "failed"
        self.error_code = error_code
        self.error_detail = error_detail

    def mark_succeeded(self) -> None:
        self.job_status = "succeeded"

    def _serialize(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "job_id": self.job_id,
            "product_id": self.product_id,
            "mode": self.mode,
            "claim_mark": self.claim_mark,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "job_status": self.job_status,
            "error_code": self.error_code,
            "error_detail": self.error_detail,
            "needs_manual_review": self.needs_manual_review,
            "content_finalize_receipts": [
                {
                    "phase": r.phase.value,
                    "action_grant_id": r.action_grant_id,
                    "result_ok": r.result_ok,
                    "error_code": r.error_code,
                    "unresolved": r.unresolved,
                    "media_identity": r.media_identity,
                    "canonical_sha256": r.canonical_sha256,
                    "field_readbacks": [
                        {
                            "field_key": fr.field_key,
                            "field_label": fr.field_label,
                            "source": fr.source,
                            "before_value": fr.before_value,
                            "after_value": fr.after_value,
                            "readback_proven": fr.readback_proven,
                            "timestamp": fr.timestamp,
                        }
                        for fr in r.field_readbacks
                    ],
                }
                for r in self.content_finalize_receipts
            ],
            "save_receipts": [
                {
                    "save_phase": r.save_phase.value,
                    "save_lease_id": r.save_lease_id,
                    "action_grant_id": r.action_grant_id,
                    "save_result_ok": r.save_result_ok,
                    "error_code": r.error_code,
                    "unresolved": r.unresolved,
                    "canonical_save_receipt_sha256": r.canonical_save_receipt_sha256,
                    "proofs": {
                        kind.value: {
                            "file_path": p.file_path,
                            "network_url": p.network_url,
                            "network_method": p.network_method,
                            "network_status": p.network_status,
                            "body_sha256": p.body_sha256,
                            "timestamp": p.timestamp,
                            "proven": p.proven,
                        }
                        for kind, p in r.proofs.items()
                    },
                    "field_readbacks": [
                        {
                            "field_key": fr.field_key,
                            "field_label": fr.field_label,
                            "source": fr.source,
                            "before_value": fr.before_value,
                            "after_value": fr.after_value,
                            "readback_proven": fr.readback_proven,
                            "timestamp": fr.timestamp,
                        }
                        for fr in r.field_readbacks
                    ],
                }
                for r in self.save_receipts
            ],
            "rollback": {
                "prepared": self.rollback_prepared,
                "preimage_sha256": self.rollback_preimage_sha256,
                "performed": self.rollback_performed,
                "success": self.rollback_success,
                "reason": self.rollback_reason,
            },
            "all_field_readbacks": [
                {
                    "field_key": fr.field_key,
                    "field_label": fr.field_label,
                    "source": fr.source,
                    "before_value": fr.before_value,
                    "after_value": fr.after_value,
                    "readback_proven": fr.readback_proven,
                    "timestamp": fr.timestamp,
                }
                for fr in self.all_field_readbacks
            ],
        }

    def compute_sha256(self) -> str:
        """Deterministic SHA-256 covering the entire execution receipt."""
        # Exclude canonical_receipt_sha256 from hash input (it is the output)
        canonical = self._serialize()
        canonical_json = json.dumps(canonical, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

    def finalize(self) -> str:
        """
        Freeze the receipt: compute canonical SHA-256, set completed_at,
        and return the frozen hash.
        """
        if self.completed_at is None:
            self.completed_at = datetime.now(timezone.utc).isoformat()
        if self.canonical_receipt_sha256 is None:
            self.canonical_receipt_sha256 = self.compute_sha256()
        return self.canonical_receipt_sha256

    def to_dict(self) -> dict[str, Any]:
        """Full serialised receipt for storage / API response."""
        return self._serialize() | {
            "canonical_receipt_sha256": self.canonical_receipt_sha256,
        }


# ---------------------------------------------------------------------------
# Helper: create FieldReadback from before/after values
# ---------------------------------------------------------------------------

def make_field_readback(
    field_key: str,
    field_label: str,
    source: str,
    before_value: Any,
    after_value: Any,
    readback_proven: bool,
    timestamp: str | None = None,
) -> FieldReadback:
    if timestamp is None:
        timestamp = datetime.now(timezone.utc).isoformat()
    return FieldReadback(
        field_key=field_key,
        field_label=field_label,
        source=source,
        before_value=before_value,
        after_value=after_value,
        readback_proven=readback_proven,
        timestamp=timestamp,
    )


# ---------------------------------------------------------------------------
# Evidence type constants for repository.add_evidence() alignment
# ---------------------------------------------------------------------------

RECEIPT_EVIDENCE_TYPE = "canonical_receipt"
SAVE_PROOF_EVIDENCE_TYPE = "save_proof"
CONTENT_FINALIZE_EVIDENCE_TYPE = "content_finalize_receipt"
