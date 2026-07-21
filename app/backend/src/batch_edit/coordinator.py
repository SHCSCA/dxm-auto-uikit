from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.batch_edit.batch_contract import (
    BATCH_SCHEMA,
    BatchContractError,
    freeze_scope_snapshot,
    freeze_template_bundle,
    frozen_batch_policy,
)
from src.batch_edit.approval_contract import (
    BatchApprovalContractError,
    issue_batch_approval,
    revalidate_frozen_scope,
    validate_batch_for_approval,
)
from src.batch_edit.scope_contract import (
    ScopeContractError,
    canonical_sha256,
    normalize_scope_capture,
)
from src.batch_edit.execution_contract import (
    BatchExecutionContractError,
    authorize_batch_start,
)
from src.repository import Repository


class BatchEditContractError(ValueError):
    def __init__(self, reason_code: str, detail: str) -> None:
        self.reason_code = reason_code
        super().__init__(detail)


class BatchEditCoordinator:
    """Freeze read-only DXM scope facts behind a deliberately small interface."""

    def __init__(self, repository: Repository) -> None:
        self._repository = repository

    def persist_scope_capture(
        self,
        capture: dict[str, Any],
        *,
        requested_max_items: int,
        runtime_context: dict[str, Any],
        expected_browser_session_id: str,
    ) -> dict[str, Any]:
        try:
            frozen = normalize_scope_capture(
                capture,
                requested_max_items=requested_max_items,
                runtime_context=runtime_context,
                expected_browser_session_id=expected_browser_session_id,
            )
        except ScopeContractError as exc:
            raise BatchEditContractError(exc.reason_code, str(exc)) from exc
        return self._repository.create_draft_box_scope_snapshot(frozen)

    def create_draft_batch(
        self,
        *,
        scope_snapshot_id: int,
        template_id: int,
    ) -> dict[str, Any]:
        try:
            scope_snapshot = freeze_scope_snapshot(
                self._repository.get_draft_box_scope_snapshot(scope_snapshot_id)
            )
            template_snapshot = freeze_template_bundle(self._repository.get_template(template_id))
        except BatchContractError as exc:
            raise BatchEditContractError(exc.reason_code, str(exc)) from exc

        bundle_binding = template_snapshot["payload"]["binding"]
        if bundle_binding["store_name"] != scope_snapshot["store_identity"]["store_name"]:
            raise BatchEditContractError(
                "TEMPLATE_SCOPE_STORE_MISMATCH",
                "edit batch bundle store does not match the frozen DXM scope store",
            )

        policy = frozen_batch_policy()
        return self._repository.create_edit_batch(
            {
                "schema_version": BATCH_SCHEMA,
                "status": "draft",
                "scope_snapshot_id": scope_snapshot_id,
                "scope_snapshot_digest": scope_snapshot["digest"],
                "scope_snapshot": scope_snapshot,
                "template_id": template_id,
                "template_snapshot_digest": canonical_sha256(template_snapshot),
                "template_snapshot": template_snapshot,
                "policy_digest": canonical_sha256(policy),
                "policy": policy,
                "items": list(scope_snapshot["items"]),
            }
        )

    def approve_batch(
        self,
        batch: dict[str, Any],
        capture: dict[str, Any],
        *,
        runtime_context: dict[str, Any],
        expected_browser_session_id: str,
        approved_by: str,
        confirmation: str,
    ) -> dict[str, Any]:
        approval = self.prepare_approval(
            batch,
            capture,
            runtime_context=runtime_context,
            expected_browser_session_id=expected_browser_session_id,
            approved_by=approved_by,
            confirmation=confirmation,
        )
        result = self._repository.approve_edit_batch(int(batch["id"]), approval)
        if not result.applied:
            detail = (
                "edit batch does not exist"
                if result.reason_code == "BATCH_NOT_FOUND"
                else "edit batch is no longer a draft and cannot be approved again"
            )
            raise BatchEditContractError(result.reason_code, detail)
        return {
            "ok": True,
            "batchId": int(batch["id"]),
            "approvalToken": approval["token"],
            "confirmation": approval["confirmation"],
            "approvedBy": approval["approved_by"],
            "issuedAt": approval["issued_at"],
            "expiresAt": approval["expires_at"],
            "scopeRevalidation": approval["scope_revalidation"],
        }

    def prepare_approval(
        self,
        batch: dict[str, Any],
        capture: dict[str, Any],
        *,
        runtime_context: dict[str, Any],
        expected_browser_session_id: str,
        approved_by: str,
        confirmation: str,
    ) -> dict[str, Any]:
        """Create private approval facts without mutating repository state."""

        try:
            current_scope, scope_revalidation = revalidate_frozen_scope(
                batch,
                capture,
                runtime_context=runtime_context,
                expected_browser_session_id=expected_browser_session_id,
            )
            approval = issue_batch_approval(
                batch,
                current_scope,
                scope_revalidation,
                approved_by=approved_by,
                confirmation=confirmation,
            )
        except BatchApprovalContractError as exc:
            raise BatchEditContractError(exc.reason_code, str(exc)) from exc
        return approval

    def approve_and_start_batch(
        self,
        batch: dict[str, Any],
        capture: dict[str, Any],
        *,
        runtime_context: dict[str, Any],
        expected_browser_session_id: str,
        authoritative_facts: dict[str, Any],
        approved_by: str,
        confirmation: str,
    ) -> dict[str, Any]:
        """Atomically consume one approval into a durable running batch."""

        approval = self.prepare_approval(
            batch,
            capture,
            runtime_context=runtime_context,
            expected_browser_session_id=expected_browser_session_id,
            approved_by=approved_by,
            confirmation=confirmation,
        )
        contract_keys = {
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
        approved_batch = {key: batch[key] for key in contract_keys}
        approved_batch["status"] = "approved"
        now = datetime.now(timezone.utc)
        try:
            start_context = authorize_batch_start(
                approved_batch,
                approval_token=approval["token"],
                stored_approval_token_hash=approval["token_hash"],
                approval_context=approval["context"],
                now=now,
                authoritative_facts=authoritative_facts,
            )
        except BatchExecutionContractError as exc:
            raise BatchEditContractError(exc.reason_code, str(exc)) from exc
        starter = getattr(self._repository, "approve_and_start_edit_batch", None)
        if not callable(starter):
            raise BatchEditContractError(
                "BATCH_START_UNAVAILABLE",
                "edit batch approval/start persistence is unavailable",
            )
        result = starter(
            int(batch["id"]),
            approval,
            start_context,
            consumed_at=now.isoformat(),
        )
        applied = bool(
            result is True
            or getattr(result, "applied", False)
            or (isinstance(result, dict) and (result.get("ok") is True or result.get("applied") is True))
        )
        if not applied:
            reason_code = (
                result.get("reason_code")
                if isinstance(result, dict)
                else getattr(result, "reason_code", None)
            ) or "BATCH_START_CONFLICT"
            raise BatchEditContractError(str(reason_code), "edit batch could not enter running state")
        started = self._repository.get_edit_batch(int(batch["id"]))
        if not isinstance(started, dict):
            raise BatchEditContractError("BATCH_START_RESULT_MISSING", "started edit batch could not be read")
        return started

    def approval_capture_max_items(self, batch: dict[str, Any]) -> int:
        try:
            return validate_batch_for_approval(batch)
        except BatchApprovalContractError as exc:
            raise BatchEditContractError(exc.reason_code, str(exc)) from exc
