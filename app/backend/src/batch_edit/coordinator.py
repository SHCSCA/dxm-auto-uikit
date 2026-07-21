from __future__ import annotations

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

    def approval_capture_max_items(self, batch: dict[str, Any]) -> int:
        try:
            return validate_batch_for_approval(batch)
        except BatchApprovalContractError as exc:
            raise BatchEditContractError(exc.reason_code, str(exc)) from exc
