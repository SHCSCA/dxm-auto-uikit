"""
FullProductEditOrchestrator — coordinates per-product page stages in Path B.

This orchestrator does NOT own task scheduling power.
It only handles internal phase coordination:
  - PHASE_MAIN_EDIT: 11 main editor sections
  - PHASE_SAVE_MODAL: save intent modal / semi-managed entry
  - PHASE_SEMI_EDIT: editFromSmt (S1-S3)

Each phase has enter_phase / execute_phase / exit_phase with receipts.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class EditPhase(Enum):
    """Product edit phases in Path B."""

    PHASE_MAIN_EDIT = "main_edit"
    PHASE_SAVE_MODAL = "save_modal"
    PHASE_SEMI_EDIT = "semi_edit"
    PHASE_UNKNOWN = "unknown"


class PhaseStatus(Enum):
    """Status of a phase execution."""

    NOT_ENTERED = "not_entered"
    ENTERED = "entered"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass
class PhaseReceipt:
    """Receipt from a phase execution."""

    phase: EditPhase
    status: PhaseStatus
    enter_receipt: dict[str, Any] | None = None
    execute_receipt: dict[str, Any] | None = None
    exit_receipt: dict[str, Any] | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_success(self) -> bool:
        return self.status == PhaseStatus.COMPLETED and self.error is None

    def is_terminal(self) -> bool:
        return self.status in {PhaseStatus.COMPLETED, PhaseStatus.FAILED}


@dataclass
class ProductEditContext:
    """Execution context for a single product edit."""

    product_id: str
    shop_id: str
    current_phase: EditPhase = EditPhase.PHASE_MAIN_EDIT
    phase_history: list[PhaseReceipt] = field(default_factory=list)
    session_context: dict[str, Any] = field(default_factory=dict)
    snapshot_id: str | None = None
    snapshot_hash: str | None = None
    execution_state: str = "pending"
    metadata: dict[str, Any] = field(default_factory=dict)


class FullProductEditOrchestrator:
    """Orchestrates per-product edit phases in Path B.

    Does NOT own task scheduling power — only internal phase coordination.

    Phase sequence:
      1. PHASE_MAIN_EDIT: execute 11 main editor sections
      2. PHASE_SAVE_MODAL: trigger save intent modal, observe semi-managed entry
      3. PHASE_SEMI_EDIT: execute editFromSmt (S1-S3)
    """

    MAIN_SECTIONS = (
        "basic_info",
        "dxm_info",
        "attribute_info",
        "product_info",
        "regional_pricing",
        "description_info",
        "packaging_info",
        "template_main",
        "template_tax",
        "compliance_info",
        "other_info",
    )

    CONTENT_FINALIZE_CAPABILITIES = (
        "video",
        "wholesale",
        "translation",
        "rollbackPreparation",
    )

    SEMI_SECTIONS = (
        "semi_countries",
        "semi_goods",
        "semi_variants",
    )

    def __init__(
        self,
        section_registry: Any | None = None,
        binding_registry: Any | None = None,
    ) -> None:
        self._section_registry = section_registry
        self._binding_registry = binding_registry

    def create_context(
        self,
        product_id: str,
        shop_id: str,
        snapshot_id: str | None = None,
        snapshot_hash: str | None = None,
        session_context: dict[str, Any] | None = None,
    ) -> ProductEditContext:
        """Create a new product edit context."""
        return ProductEditContext(
            product_id=product_id,
            shop_id=shop_id,
            current_phase=EditPhase.PHASE_MAIN_EDIT,
            snapshot_id=snapshot_id,
            snapshot_hash=snapshot_hash,
            session_context=dict(session_context or {}),
        )

    def get_next_phase(
        self,
        current_phase: EditPhase,
    ) -> EditPhase | None:
        """Determine the next phase after the current one."""
        phase_order = [
            EditPhase.PHASE_MAIN_EDIT,
            EditPhase.PHASE_SAVE_MODAL,
            EditPhase.PHASE_SEMI_EDIT,
        ]
        try:
            idx = phase_order.index(current_phase)
            return phase_order[idx + 1] if idx + 1 < len(phase_order) else None
        except ValueError:
            return None

    def enter_phase(
        self,
        ctx: ProductEditContext,
        phase: EditPhase,
    ) -> PhaseReceipt:
        """Enter a phase and return an enter_receipt."""
        receipt = PhaseReceipt(
            phase=phase,
            status=PhaseStatus.ENTERED,
            metadata={
                "product_id": ctx.product_id,
                "shop_id": ctx.shop_id,
                "snapshot_id": ctx.snapshot_id,
            },
        )
        ctx.phase_history.append(receipt)
        ctx.current_phase = phase
        if phase == EditPhase.PHASE_MAIN_EDIT:
            receipt.enter_receipt = {
                "phase": phase.value,
                "sections": list(self.MAIN_SECTIONS),
                "section_count": len(self.MAIN_SECTIONS),
            }
        elif phase == EditPhase.PHASE_SAVE_MODAL:
            receipt.enter_receipt = {
                "phase": phase.value,
                "modal_type": "save_intent",
                "requires_semi_check": True,
            }
        elif phase == EditPhase.PHASE_SEMI_EDIT:
            receipt.enter_receipt = {
                "phase": phase.value,
                "sections": list(self.SEMI_SECTIONS),
                "section_count": len(self.SEMI_SECTIONS),
            }
        else:
            receipt.enter_receipt = {"phase": phase.value}
        return receipt

    def execute_phase(
        self,
        ctx: ProductEditContext,
        phase: EditPhase,
        section_results: dict[str, Any] | None = None,
    ) -> PhaseReceipt:
        """Execute a phase and return an execute_receipt."""
        if not ctx.phase_history or ctx.phase_history[-1].phase != phase:
            receipt = self.enter_phase(ctx, phase)
        else:
            receipt = ctx.phase_history[-1]

        if receipt.status == PhaseStatus.BLOCKED:
            return receipt

        receipt.status = PhaseStatus.EXECUTING
        section_results = section_results or {}

        if phase == EditPhase.PHASE_MAIN_EDIT:
            receipt.execute_receipt = self._execute_main_edit(section_results)
        elif phase == EditPhase.PHASE_SAVE_MODAL:
            receipt.execute_receipt = self._execute_save_modal(section_results)
        elif phase == EditPhase.PHASE_SEMI_EDIT:
            receipt.execute_receipt = self._execute_semi_edit(section_results)
        else:
            receipt.execute_receipt = {"status": "unknown_phase"}

        if receipt.execute_receipt.get("status") == "success":
            receipt.status = PhaseStatus.COMPLETED
        elif receipt.execute_receipt.get("status") == "blocked":
            receipt.status = PhaseStatus.BLOCKED
        else:
            receipt.status = PhaseStatus.FAILED
            receipt.error = receipt.execute_receipt.get("error", "unknown error")

        return receipt

    def exit_phase(
        self,
        ctx: ProductEditContext,
        phase: EditPhase,
        exit_data: dict[str, Any] | None = None,
    ) -> PhaseReceipt:
        """Exit a phase and return an exit_receipt."""
        if not ctx.phase_history or ctx.phase_history[-1].phase != phase:
            receipt = PhaseReceipt(
                phase=phase,
                status=PhaseStatus.NOT_ENTERED,
            )
            return receipt

        receipt = ctx.phase_history[-1]
        receipt.exit_receipt = dict(exit_data or {})
        receipt.exit_receipt["phase"] = phase.value
        return receipt

    def advance_phase(
        self,
        ctx: ProductEditContext,
        section_results: dict[str, Any] | None = None,
    ) -> PhaseReceipt | None:
        """Advance to the next phase from the current phase."""
        current_phase = ctx.current_phase
        next_phase = self.get_next_phase(current_phase)

        if next_phase is None:
            return None

        self.enter_phase(ctx, next_phase)
        return self.execute_phase(ctx, next_phase, section_results)

    def get_context_summary(
        self,
        ctx: ProductEditContext,
    ) -> dict[str, Any]:
        """Get a summary of the current execution context."""
        phases_completed = [
            r.phase for r in ctx.phase_history if r.status == PhaseStatus.COMPLETED
        ]
        phases_failed = [
            r.phase for r in ctx.phase_history if r.status == PhaseStatus.FAILED
        ]
        return {
            "product_id": ctx.product_id,
            "shop_id": ctx.shop_id,
            "current_phase": ctx.current_phase.value,
            "phases_completed": [p.value for p in phases_completed],
            "phases_failed": [p.value for p in phases_failed],
            "phase_count": len(ctx.phase_history),
            "execution_state": ctx.execution_state,
            "snapshot_hash": ctx.snapshot_hash,
        }

    def _execute_main_edit(
        self,
        section_results: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute main edit phase (11 sections excluding semi)."""
        required = (*self.MAIN_SECTIONS, *self.CONTENT_FINALIZE_CAPABILITIES)
        missing = [section for section in required if section not in section_results]
        invalid = [
            section
            for section in self.MAIN_SECTIONS
            if section in section_results
            and not self._verified_section_result(section, section_results[section])
        ] + [
            capability
            for capability in self.CONTENT_FINALIZE_CAPABILITIES
            if capability in section_results
            and not self._verified_capability_result(
                capability, section_results[capability]
            )
        ]
        if missing or invalid:
            return {
                "status": "blocked",
                "executed_sections": [
                    section
                    for section in required
                    if section not in missing and section not in invalid
                ],
                "missing_sections": missing,
                "failed_sections": invalid,
                "error": (
                    "Main edit receipts incomplete: "
                    f"missing={missing}, invalid={invalid}"
                ),
            }
        return {
            "status": "success",
            "executed_sections": list(required),
            "section_count": len(required),
        }

    def _execute_save_modal(
        self,
        section_results: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute save modal phase."""
        modal_result = section_results.get("save_modal", {})
        if (
            modal_result.get("save1_verified") is True
            and modal_result.get("gate_outcome") == "admitted"
            and modal_result.get("semi_entry_triggered") is True
            and isinstance(modal_result.get("handshake_id"), str)
            and bool(modal_result["handshake_id"].strip())
            and modal_result.get("same_handshake") is True
        ):
            return {
                "status": "success",
                "semi_entry_triggered": True,
                "handshake_id": modal_result.get("handshake_id"),
            }
        elif modal_result.get("blocked"):
            return {
                "status": "blocked",
                "blocked_reason": modal_result.get("blocked_reason", "unknown"),
            }
        else:
            return {
                "status": "blocked",
                "error": "save modal outcome unknown",
            }

    def _execute_semi_edit(
        self,
        section_results: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute semi-managed edit phase (S1-S3)."""
        missing = [section for section in self.SEMI_SECTIONS if section not in section_results]
        invalid = [
            section
            for section in self.SEMI_SECTIONS
            if section in section_results
            and not self._verified_section_result(section, section_results[section])
        ]
        if missing or invalid:
            return {
                "status": "blocked",
                "executed_sections": [
                    section
                    for section in self.SEMI_SECTIONS
                    if section not in missing and section not in invalid
                ],
                "missing_sections": missing,
                "failed_sections": invalid,
                "error": (
                    "Semi-managed receipts incomplete: "
                    f"missing={missing}, invalid={invalid}"
                ),
            }
        return {
            "status": "success",
            "executed_sections": list(self.SEMI_SECTIONS),
            "section_count": len(self.SEMI_SECTIONS),
        }

    @staticmethod
    def _canonical_sha256(value: Any) -> str | None:
        try:
            encoded = json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError):
            return None
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _verified_readbacks(value: Any, *, require_nonempty: bool) -> bool:
        expected_keys = {
            "field_key",
            "field_label",
            "source",
            "before_value",
            "after_value",
            "readback_proven",
            "timestamp",
        }
        if not isinstance(value, list) or (require_nonempty and not value):
            return False
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, dict) or set(item) != expected_keys:
                return False
            field_key = item.get("field_key")
            if (
                not isinstance(field_key, str)
                or not field_key.strip()
                or field_key != field_key.strip()
                or field_key in seen
                or not isinstance(item.get("field_label"), str)
                or not item["field_label"].strip()
                or not isinstance(item.get("source"), str)
                or not item["source"].strip()
                or item.get("readback_proven") is not True
                or not isinstance(item.get("timestamp"), str)
            ):
                return False
            try:
                observed_at = datetime.fromisoformat(
                    item["timestamp"].replace("Z", "+00:00")
                )
            except ValueError:
                return False
            if observed_at.tzinfo is None or observed_at.utcoffset() is None:
                return False
            seen.add(field_key)
        return True

    @staticmethod
    def _verified_interval(started_at: Any, completed_at: Any) -> bool:
        if not isinstance(started_at, str) or not isinstance(completed_at, str):
            return False
        try:
            started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            completed = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
        except ValueError:
            return False
        return bool(
            started.tzinfo is not None
            and started.utcoffset() is not None
            and completed.tzinfo is not None
            and completed.utcoffset() is not None
            and completed >= started
        )

    @classmethod
    def _verified_section_result(cls, section: str, value: Any) -> bool:
        """Validate one exact, independently hashed section receipt."""

        expected_keys = {
            "schema_version",
            "section",
            "action_grant_id",
            "success",
            "readback_proven",
            "field_readbacks",
            "started_at",
            "completed_at",
            "receipt_sha256",
        }
        if not isinstance(value, dict) or set(value) != expected_keys:
            return False
        receipt_sha256 = value.get("receipt_sha256")
        if (
            value.get("schema_version") != "dxm.path-b.section-receipt.v1"
            or value.get("section") != section
            or value.get("success") is not True
            or value.get("readback_proven") is not True
            or not isinstance(value.get("action_grant_id"), str)
            or not value["action_grant_id"].strip()
            or not cls._verified_interval(
                value.get("started_at"), value.get("completed_at")
            )
            or not isinstance(value.get("field_readbacks"), list)
            or not cls._verified_readbacks(
                value.get("field_readbacks"), require_nonempty=True
            )
            or not isinstance(receipt_sha256, str)
            or len(receipt_sha256) != 64
        ):
            return False
        digest = cls._canonical_sha256(
            {key: item for key, item in value.items() if key != "receipt_sha256"}
        )
        return digest is not None and digest.casefold() == receipt_sha256.casefold()

    @classmethod
    def _verified_capability_result(cls, capability: str, value: Any) -> bool:
        """Validate the canonical wrapper for one mandatory capability."""

        phase_by_capability = {
            "video": "content_finalize_video",
            "wholesale": "content_finalize_wholesale",
            "translation": "content_finalize_translation",
            "semiManaged": "semi_managed_entry",
            "rollbackPreparation": "rollback_preparation",
        }
        raw_keys = {
            "phase",
            "action_grant_id",
            "result_ok",
            "error_code",
            "error_detail",
            "unresolved",
            "media_identity",
            "started_at",
            "completed_at",
            "field_readbacks",
            "canonical_sha256",
        }
        if capability == "rollbackPreparation":
            raw_keys.add("preimage_sha256")
        if not isinstance(value, dict) or set(value) != {
            "canonical_receipt",
            "receipt_sha256",
        }:
            return False
        raw = value.get("canonical_receipt")
        wrapper_sha256 = value.get("receipt_sha256")
        if not isinstance(raw, dict) or set(raw) != raw_keys:
            return False
        canonical_sha256 = raw.get("canonical_sha256")
        if (
            raw.get("phase") != phase_by_capability.get(capability)
            or raw.get("result_ok") is not True
            or raw.get("unresolved") is not False
            or raw.get("error_code") is not None
            or raw.get("error_detail") is not None
            or not isinstance(raw.get("action_grant_id"), str)
            or not raw["action_grant_id"].strip()
            or not cls._verified_interval(
                raw.get("started_at"), raw.get("completed_at")
            )
            or not cls._verified_readbacks(
                raw.get("field_readbacks"), require_nonempty=False
            )
            or not isinstance(canonical_sha256, str)
            or len(canonical_sha256) != 64
            or not isinstance(wrapper_sha256, str)
            or len(wrapper_sha256) != 64
        ):
            return False
        if capability == "video" and not str(raw.get("media_identity") or "").strip():
            return False
        if capability == "rollbackPreparation":
            preimage_sha256 = str(raw.get("preimage_sha256") or "")
            if len(preimage_sha256) != 64 or any(
                character not in "0123456789abcdefABCDEF"
                for character in preimage_sha256
            ):
                return False
        canonical_body = {
            key: item
            for key, item in raw.items()
            if key not in {"canonical_sha256", "preimage_sha256"}
        }
        digest = cls._canonical_sha256(canonical_body)
        return bool(
            digest is not None
            and digest.casefold() == canonical_sha256.casefold()
            and digest.casefold() == wrapper_sha256.casefold()
        )
