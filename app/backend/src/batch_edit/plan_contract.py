from __future__ import annotations

import json
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

    def assert_task_snapshot_binding(
        self,
        task: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Reload and exactly bind an executable task to its stored snapshot."""

        if not isinstance(task, Mapping):
            _reject("BATCH_TASK_INVALID", "batch task must be an object")
        task_id = task.get("id")
        if isinstance(task_id, bool) or not isinstance(task_id, int) or task_id <= 0:
            _reject("BATCH_TASK_INVALID", "batch task id must be positive")
        payload = task.get("payload")
        if not isinstance(payload, Mapping):
            _reject("BATCH_PLAN_SNAPSHOT_REQUIRED", "batch task payload is missing")
        snapshot_id = payload.get("plan_snapshot_id")
        if (
            isinstance(snapshot_id, bool)
            or not isinstance(snapshot_id, int)
            or snapshot_id <= 0
        ):
            _reject(
                "BATCH_PLAN_SNAPSHOT_REQUIRED",
                "batch task requires a stored plan_snapshot id",
            )
        stored = self.get_plan_snapshot(snapshot_id)
        if stored.get("task_id") != task_id:
            _reject(
                "BATCH_PLAN_SNAPSHOT_TASK_MISMATCH",
                "stored plan_snapshot is not atomically bound to this task",
            )
        stored_body = {
            key: _plan_values.clone(value)
            for key, value in stored.items()
            if key not in {"id", "task_id", "created_at"}
        }
        embedded = payload.get("plan_snapshot")
        if not isinstance(embedded, Mapping) or _canonical_json(embedded) != _canonical_json(
            stored_body
        ):
            _reject(
                "BATCH_PLAN_SNAPSHOT_EMBEDDED_DRIFT",
                "embedded task snapshot differs from the stored immutable snapshot",
            )
        if payload.get("plan_snapshot_hash") != stored_body.get("snapshot_hash"):
            _reject(
                "BATCH_PLAN_SNAPSHOT_HASH_MISMATCH",
                "task snapshot hash differs from the stored immutable snapshot",
            )
        if (
            task.get("mode") != "batch_draft_save"
            or payload.get("execution_mode") != "batch_draft_save"
            or payload.get("path") != "A"
            or stored_body.get("path") != "A"
            or payload.get("publish_allowed") is not False
            or stored_body.get("publish_allowed") is not False
        ):
            _reject(
                "BATCH_PLAN_SNAPSHOT_EXECUTION_DRIFT",
                "task mode, Path A, or zero-publish binding has drifted",
            )
        stored_ids = stored_body.get("product_ids")
        if not isinstance(stored_ids, list) or not stored_ids:
            _reject("BATCH_PRODUCT_IDS_REQUIRED", "stored snapshot has no products")
        try:
            exact_product_ids = [
                int(_plan_values.positive_id_text(value, "product_id"))
                for value in stored_ids
            ]
        except PlanContractError:
            raise
        if payload.get("product_ids") != exact_product_ids:
            _reject(
                "BATCH_PRODUCT_ORDER_MISMATCH",
                "task product_ids must exactly preserve stored snapshot order",
            )
        item_snapshots = stored_body.get("item_snapshots")
        if not isinstance(item_snapshots, list) or [
            item.get("product_id") if isinstance(item, Mapping) else None
            for item in item_snapshots
        ] != stored_ids:
            _reject(
                "BATCH_ITEM_ORDER_MISMATCH",
                "stored item_snapshots must exactly preserve product order",
            )
        jobs = task.get("jobs")
        if not isinstance(jobs, list):
            _reject("BATCH_JOB_ORDER_MISMATCH", "batch task jobs are missing")
        job_product_ids = [
            job.get("product_id") if isinstance(job, Mapping) else None
            for job in jobs
        ]
        if job_product_ids != exact_product_ids:
            _reject(
                "BATCH_JOB_ORDER_MISMATCH",
                "batch jobs must exactly preserve stored snapshot order",
            )
        try:
            task_store_id = int(task.get("store_id"))
            snapshot_store_id = int(stored_body.get("shop_scope"))
        except (TypeError, ValueError) as exc:
            raise PlanContractError(
                "BATCH_STORE_SCOPE_MISMATCH",
                "batch task or snapshot store binding is invalid",
            ) from exc
        if task_store_id <= 0 or task_store_id != snapshot_store_id:
            _reject(
                "BATCH_STORE_SCOPE_MISMATCH",
                "batch task store differs from the stored snapshot scope",
            )
        return stored_body

def _public_plan_snapshot(row: Mapping[str, Any]) -> dict[str, Any]:
    public = {
        "id": int(row["id"]),
        **loads(row["snapshot_json"], {}),
        "created_at": row["created_at"],
    }
    if row.get("task_id") is not None:
        public["task_id"] = int(row["task_id"])
    return public


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise PlanContractError(
            "BATCH_PLAN_SNAPSHOT_EMBEDDED_DRIFT",
            "batch snapshot is not canonical JSON",
        ) from exc


def _reject(reason_code: str, detail: str, *, status_code: int = 409) -> None:
    raise PlanContractError(reason_code, detail, status_code=status_code)
