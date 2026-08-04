from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from src.batch_edit.local_plan_store import (
    LocalPlanTemplateStore,
)
from src.batch_edit.plan_value_contract import PlanValueContract
from src.batch_edit.plan_reference_store import (
    DxmTemplateReferenceStore,
)
from src.batch_edit.plan_snapshot_compiler import (
    PlanSnapshotCompiler,
)
from src.batch_edit.plan_snapshot_store import (
    PlanSnapshotStore,
    PlanSnapshotStoreError,
)
from src.db import loads


class PlanContractError(ValueError):
    def __init__(self, reason_code: str, detail: str, *, status_code: int = 409) -> None:
        self.reason_code = reason_code
        self.status_code = status_code
        super().__init__(detail)


_plan_values = PlanValueContract(PlanContractError)
_sha256_text = _plan_values.sha256_text
_non_empty_text = _plan_values.non_empty_text
_reference_store = DxmTemplateReferenceStore(PlanContractError)
_local_plan_store = LocalPlanTemplateStore(
    PlanContractError,
    reference_store=_reference_store,
)
_snapshot_compiler = PlanSnapshotCompiler(
    PlanContractError,
    local_plan_store=_local_plan_store,
)


class E2PlanService:
    def sync_dxm_template_refs(
        self,
        records: list[dict[str, Any]],
        *,
        shop_id: str,
        category_ids: list[str],
    ) -> list[dict[str, Any]]:
        return _reference_store.sync(
            records,
            shop_id=shop_id,
            category_ids=category_ids,
        )

    def list_dxm_template_refs(self) -> list[dict[str, Any]]:
        return _reference_store.list()

    def create_local_plan(
        self,
        payload: dict[str, Any],
        *,
        supersedes_id: int | None = None,
    ) -> dict[str, Any]:
        return _local_plan_store.create(
            payload,
            supersedes_id=supersedes_id,
        )

    def list_local_plans(self) -> list[dict[str, Any]]:
        return _local_plan_store.list()

    def get_local_plan(self, plan_id: int) -> dict[str, Any]:
        return _local_plan_store.get(plan_id)

    def archive_local_plan(self, plan_id: int) -> dict[str, Any]:
        return _local_plan_store.archive(plan_id)

    def build_plan_snapshot(self, request: dict[str, Any]) -> dict[str, Any]:
        return _snapshot_compiler.compile(request)

    def freeze_plan_snapshot(
        self,
        request: dict[str, Any],
        *,
        expected_snapshot_hash: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        snapshot = self.build_plan_snapshot(request)
        expected = _sha256_text(
            expected_snapshot_hash,
            "expected_snapshot_hash",
        )
        if expected != snapshot["snapshot_hash"]:
            _reject(
                "PLAN_SNAPSHOT_PREVIEW_DRIFT",
                "方案、模板、商品身份或类目 Schema 在预览后发生变化",
            )
        normalized_idempotency_key = _non_empty_text(
            idempotency_key,
            "idempotency_key",
        )
        if (
            not 8 <= len(normalized_idempotency_key) <= 128
            or re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9._:-]*",
                normalized_idempotency_key,
            )
            is None
        ):
            _reject(
                "PLAN_SNAPSHOT_IDEMPOTENCY_INVALID",
                "idempotency_key format is invalid",
            )
        try:
            row = PlanSnapshotStore().freeze_with_task(
                snapshot,
                idempotency_key=normalized_idempotency_key,
            )
        except PlanSnapshotStoreError as exc:
            _reject(exc.reason_code, str(exc))
        return _public_plan_snapshot(row)

    def get_plan_snapshot(self, snapshot_id: int) -> dict[str, Any]:
        row = PlanSnapshotStore().get(snapshot_id)
        if not row:
            _reject("PLAN_SNAPSHOT_NOT_FOUND", "plan snapshot does not exist", status_code=404)
        snapshot = _public_plan_snapshot(row)
        _snapshot_compiler.assert_hash(snapshot)
        return snapshot

    def create_task_from_snapshot(self, snapshot_id: int, repository: Any) -> dict[str, Any]:
        stored = self.get_plan_snapshot(snapshot_id)
        task_id = stored.get("task_id")
        if not isinstance(task_id, int) or task_id <= 0:
            _reject(
                "PLAN_SNAPSHOT_TASK_NOT_ATOMIC",
                "snapshot was not frozen atomically with its task",
            )
        task = repository.get_task(task_id)
        if task is None:
            _reject(
                "PLAN_SNAPSHOT_TASK_NOT_ATOMIC",
                "snapshot task is missing",
            )
        return task

def _public_plan_snapshot(row: Mapping[str, Any]) -> dict[str, Any]:
    public = {
        "id": int(row["id"]),
        **loads(row["snapshot_json"], {}),
        "created_at": row["created_at"],
    }
    if row.get("task_id") is not None:
        public["task_id"] = int(row["task_id"])
    return public


def _reject(reason_code: str, detail: str, *, status_code: int = 409) -> None:
    raise PlanContractError(reason_code, detail, status_code=status_code)
