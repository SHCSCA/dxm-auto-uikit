from __future__ import annotations

from collections.abc import Mapping

from src.batch_edit.scope_contract import canonical_sha256
from src.db import loads


def load_current_authority_facts(conn, authority, *, allowed_steps):
    """复核持久化身份；调用方必须独立限定其可消费的当前步骤。"""
    from src.execution.batch_dispatch_authority import (
        _load_task_by_id, _reject, _task_authority_projection, _validated_authority,
    )

    canonical = _validated_authority(authority)
    expected_task = canonical["task_authority"]
    task = _load_task_by_id(conn, expected_task.get("task_id"))
    if canonical_sha256(_task_authority_projection(task)) != canonical_sha256(expected_task):
        _reject("AUTH_CURRENT_TASK_DRIFT")
    snapshot_id = canonical["snapshot"]["plan_snapshot_id"]
    row = conn.execute("SELECT * FROM plan_snapshots WHERE id=?", (snapshot_id,)).fetchone()
    current_snapshot = loads(row["snapshot_json"], {}) if row is not None else None
    row_binding = ({key: row[key] for key in (
        "id", "task_id", "snapshot_hash", "local_plan_template_id", "idempotency_key", "created_at",
    )} if row is not None else None)
    if (row_binding != canonical["snapshot"].get("row_binding")
            or canonical_sha256(current_snapshot) != canonical_sha256(canonical["snapshot"]["plan_snapshot"])):
        _reject("AUTH_CURRENT_TASK_DRIFT")
    provenance = conn.execute(
        "SELECT snapshot_id, snapshot_hash FROM plan_snapshot_idempotency_keys WHERE idempotency_key=?",
        (canonical["snapshot"]["row_binding"]["idempotency_key"],),
    ).fetchone()
    if (provenance is None or provenance["snapshot_id"] != snapshot_id
            or provenance["snapshot_hash"] != canonical["snapshot"]["plan_snapshot_hash"]):
        _reject("AUTH_CURRENT_TASK_DRIFT")
    validate_current_queue(task, canonical["queue"], allowed_steps=allowed_steps)
    return canonical, task


def validate_current_queue(task, frozen_queue, *, allowed_steps):
    """保留队列顺序、单个运行项和进度约束，不赋予任何派发权。"""
    from src.execution.batch_dispatch_authority import _reject

    if not isinstance(frozen_queue, Mapping):
        _reject("AUTH_CURRENT_QUEUE_DRIFT")
    frozen_jobs, current_jobs = frozen_queue.get("ordered_jobs"), task.get("jobs")
    if (not isinstance(frozen_jobs, list) or not isinstance(current_jobs, list)
            or not all(isinstance(item, Mapping) for item in frozen_jobs + current_jobs)):
        _reject("AUTH_CURRENT_QUEUE_DRIFT")
    frozen_identity = [{"ordinal": item.get("ordinal"), "job_id": item.get("job_id"),
                        "product_id": str(item.get("product_id"))} for item in frozen_jobs]
    current_identity = [{"ordinal": ordinal, "job_id": int(item.get("id")),
                         "product_id": str(item.get("product_id"))}
                        for ordinal, item in enumerate(current_jobs, start=1)]
    guard = frozen_queue.get("guard")
    if not isinstance(guard, Mapping):
        _reject("AUTH_CURRENT_QUEUE_DRIFT")
    indexes = [index for index, item in enumerate(current_jobs) if item.get("id") == guard.get("current_job_id")]
    if frozen_identity != current_identity or len(indexes) != 1 or task.get("status") != "running":
        _reject("AUTH_CURRENT_QUEUE_DRIFT")
    index = indexes[0]
    statuses = [str(item.get("status") or "") for item in current_jobs]
    if (statuses[index] != "running" or statuses.count("running") != 1
            or any(status not in {"succeeded", "completed"} for status in statuses[:index])
            or any(status != "pending" for status in statuses[index + 1:])
            or int(task.get("completed_jobs") or 0) != index or int(task.get("failed_jobs") or 0) != 0
            or current_jobs[index].get("current_step_code") not in allowed_steps):
        _reject("AUTH_CURRENT_QUEUE_DRIFT")
