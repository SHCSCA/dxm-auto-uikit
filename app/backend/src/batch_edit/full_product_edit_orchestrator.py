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

from dataclasses import dataclass, field
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

    MAIN_SECTIONS = frozenset(
        {
            "product_info",
            "basic_info",
            "sale_info",
            "media_assets",
            "additional_info",
            "compliance",
            "logistics",
            "video",
            "wholesale",
        }
    )

    SEMI_SECTIONS = frozenset(
        {
            "semi_countries",
            "semi_goods",
            "semi_variants",
        }
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
                "sections": sorted(self.MAIN_SECTIONS),
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
                "sections": sorted(self.SEMI_SECTIONS),
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
        executed = []
        failed = []
        for section in sorted(self.MAIN_SECTIONS):
            if section in section_results:
                result = section_results[section]
                if result.get("success"):
                    executed.append(section)
                else:
                    failed.append(section)
            else:
                executed.append(section)
        if failed:
            return {
                "status": "blocked",
                "executed_sections": executed,
                "failed_sections": failed,
                "error": f"Main edit sections failed: {failed}",
            }
        return {
            "status": "success",
            "executed_sections": executed,
            "section_count": len(executed),
        }

    def _execute_save_modal(
        self,
        section_results: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute save modal phase."""
        modal_result = section_results.get("save_modal", {})
        if modal_result.get("semi_entry_triggered"):
            return {
                "status": "success",
                "semi_entry_triggered": True,
                "handshake_id": modal_result.get("handshake_id"),
            }
        elif modal_result.get("save_completed"):
            return {
                "status": "success",
                "semi_entry_triggered": False,
                "save_completed": True,
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
        executed = []
        failed = []
        for section in sorted(self.SEMI_SECTIONS):
            if section in section_results:
                result = section_results[section]
                if result.get("success"):
                    executed.append(section)
                else:
                    failed.append(section)
            else:
                executed.append(section)
        if failed:
            return {
                "status": "blocked",
                "executed_sections": executed,
                "failed_sections": failed,
                "error": f"Semi-managed sections failed: {failed}",
            }
        return {
            "status": "success",
            "executed_sections": executed,
            "section_count": len(executed),
        }
