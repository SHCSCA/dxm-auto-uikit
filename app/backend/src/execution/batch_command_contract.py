from __future__ import annotations

import hmac
import hashlib
import json
from copy import deepcopy
from collections.abc import Mapping
from typing import Any


BATCH_QUEUE_GUARD_SCHEMA = "dxm.batch_draft_save.queue_guard.v1"
SAVE_VERIFICATION_CONTEXT_SCHEMA = "dxm.batch_draft_save.save_verification.v1"
PATH_B_SAVE1_DISCOVERY_PROFILE_KEY = "real_dxm_path_b_discovery"
PATH_B_SAVE1_DISCOVERY_PROFILE_SCHEMA = "real_dxm_path_b_save1_discovery.v1"
PATH_B_SAVE1_DISCOVERY_EXECUTION_PROFILE = "path_b_save1_discovery"
PATH_B_SAVE1_DISCOVERY_STATE = "FIRST_SAVE_INTENT"
PATH_B_SAVE1_DISCOVERY_ACTION = "first_save_intent"
PATH_B_FORMAL_LINEAGE_KEY = "real_dxm_path_b_formal_lineage"
PATH_B_FORMAL_LINEAGE_SCHEMA = "real_dxm_path_b_formal_lineage.v1"

_PATH_B_SAVE1_DISCOVERY_PROFILE_KEYS = frozenset(
    {
        "schema",
        "execution_profile",
        "target_task_id",
        "target_job_id",
        "target_product_id",
        "target_product_ordinal",
        "scope_sha256",
        "approval_sha256",
        "discovery_key_sha256",
        "single_use",
        "save_stage_limit",
        "save2_allowed",
        "other_product_mutation_allowed",
    }
)


class BatchCommandContractError(ValueError):
    def __init__(self, reason_code: str, detail: str) -> None:
        self.reason_code = reason_code
        super().__init__(detail)


def build_path_b_save1_discovery_profile(
    task: Any,
    *,
    target_product_id: Any,
    scope_sha256: Any,
    approval_sha256: Any,
    discovery_key_sha256: Any,
) -> dict[str, Any]:
    """Derive the only fail-closed one-product SAVE1 discovery profile.

    The public caller chooses a product id, but cannot choose a queue position,
    job id, SAVE stage, or broaden the mutation boundary.  Discovery is only
    legal for the first product in the frozen exact three-product queue.
    """

    if not isinstance(task, Mapping):
        _reject(
            "DISCOVERY_TASK_INVALID",
            "a persisted Path B task is required",
        )
    task_id = _positive_int(task.get("id"), "task id")
    product_id = _positive_int(target_product_id, "target product id")
    if str(task.get("mode") or "") != "batch_draft_save":
        _reject(
            "DISCOVERY_TASK_MODE_INVALID",
            "SAVE1 discovery requires batch_draft_save",
        )
    payload = task.get("payload") if isinstance(task.get("payload"), Mapping) else {}
    if payload.get("path") != "B" or payload.get("publish_allowed") is not False:
        _reject(
            "DISCOVERY_TASK_PATH_INVALID",
            "SAVE1 discovery requires a no-publish Path B task",
        )
    jobs = task.get("jobs") if isinstance(task.get("jobs"), list) else []
    ordered_products = payload.get("product_ids")
    if (
        len(jobs) != 3
        or not isinstance(ordered_products, list)
        or len(ordered_products) != len(jobs)
        or any(not isinstance(job, Mapping) for job in jobs)
    ):
        _reject(
            "DISCOVERY_QUEUE_INVALID",
            "SAVE1 discovery requires the exact frozen three-product queue",
        )
    job_ids = [_positive_int(job.get("id"), "queue job id") for job in jobs]
    job_product_ids = [
        _positive_int(job.get("product_id"), "queue product id") for job in jobs
    ]
    ordered_product_ids = [
        _positive_int(value, "ordered product id") for value in ordered_products
    ]
    if (
        len(set(job_ids)) != 3
        or len(set(job_product_ids)) != 3
        or job_product_ids != ordered_product_ids
    ):
        _reject(
            "DISCOVERY_QUEUE_INVALID",
            "SAVE1 discovery requires three distinct jobs in exact product order",
        )
    first_job = jobs[0]
    first_product_id = _positive_int(first_job.get("product_id"), "first product id")
    if (
        product_id != first_product_id
    ):
        _reject(
            "DISCOVERY_TARGET_NOT_QUEUE_HEAD",
            "SAVE1 discovery is restricted to the first frozen product",
        )
    real_authorization = payload.get("real_dxm_write_authorization")
    if not isinstance(real_authorization, Mapping):
        _reject(
            "DISCOVERY_REAL_AUTHORIZATION_REQUIRED",
            "consumed Path B real-write authorization is required",
        )
    canonical_scope_sha256 = _sha256(scope_sha256, "scope sha256")
    canonical_approval_sha256 = _sha256(approval_sha256, "approval sha256")
    if (
        _sha256(real_authorization.get("scope_sha256"), "stored scope sha256")
        != canonical_scope_sha256
        or _sha256(
            real_authorization.get("approval_sha256"),
            "stored approval sha256",
        )
        != canonical_approval_sha256
    ):
        _reject(
            "DISCOVERY_AUTHORIZATION_BINDING_MISMATCH",
            "discovery scope or approval differs from the consumed authorization",
        )
    return validate_path_b_save1_discovery_profile(
        {
            "schema": PATH_B_SAVE1_DISCOVERY_PROFILE_SCHEMA,
            "execution_profile": PATH_B_SAVE1_DISCOVERY_EXECUTION_PROFILE,
            "target_task_id": task_id,
            "target_job_id": _positive_int(first_job.get("id"), "first job id"),
            "target_product_id": product_id,
            "target_product_ordinal": 1,
            "scope_sha256": canonical_scope_sha256,
            "approval_sha256": canonical_approval_sha256,
            "discovery_key_sha256": _sha256(
                discovery_key_sha256,
                "discovery key sha256",
            ),
            "single_use": True,
            "save_stage_limit": "SAVE1",
            "save2_allowed": False,
            "other_product_mutation_allowed": False,
        }
    )


def validate_path_b_save1_discovery_profile(value: Any) -> dict[str, Any]:
    """Canonicalize a persisted discovery profile without widening it."""

    if not isinstance(value, Mapping) or set(value) != _PATH_B_SAVE1_DISCOVERY_PROFILE_KEYS:
        _reject(
            "DISCOVERY_PROFILE_INVALID",
            "Path B SAVE1 discovery profile has an unexpected shape",
        )
    profile = deepcopy(dict(value))
    if (
        profile.get("schema") != PATH_B_SAVE1_DISCOVERY_PROFILE_SCHEMA
        or profile.get("execution_profile")
        != PATH_B_SAVE1_DISCOVERY_EXECUTION_PROFILE
        or profile.get("target_product_ordinal") != 1
        or profile.get("single_use") is not True
        or profile.get("save_stage_limit") != "SAVE1"
        or profile.get("save2_allowed") is not False
        or profile.get("other_product_mutation_allowed") is not False
    ):
        _reject(
            "DISCOVERY_PROFILE_WIDENED",
            "discovery must remain one first-product SAVE1 with SAVE2 forbidden",
        )
    for key in ("target_task_id", "target_job_id", "target_product_id"):
        profile[key] = _positive_int(profile.get(key), key.replace("_", " "))
    for key in ("scope_sha256", "approval_sha256", "discovery_key_sha256"):
        profile[key] = _sha256(profile.get(key), key.replace("_", " "))
    return profile


def validate_path_b_save1_discovery_dispatch(
    task: Any,
    *,
    job_id: Any,
    command_state: Any,
    command_action: Any,
) -> dict[str, Any] | None:
    """Reject every non-composite or out-of-head mutation for Discovery.

    ``None`` means the task is not a discovery task.  A profile-shaped payload
    is never ignored: malformed or widened values fail closed.
    """

    if not isinstance(task, Mapping):
        _reject("DISCOVERY_TASK_INVALID", "persisted task is required")
    payload = task.get("payload") if isinstance(task.get("payload"), Mapping) else {}
    raw_profile = payload.get(PATH_B_SAVE1_DISCOVERY_PROFILE_KEY)
    if raw_profile is None:
        return None
    profile = validate_path_b_save1_discovery_profile(raw_profile)
    jobs = task.get("jobs") if isinstance(task.get("jobs"), list) else []
    real_authorization = payload.get("real_dxm_write_authorization")
    if (
        str(task.get("mode") or "") != "batch_draft_save"
        or payload.get("path") != "B"
        or payload.get("publish_allowed") is not False
        or str(task.get("status") or "") != "running"
        or len(jobs) != 3
        or any(not isinstance(job, Mapping) for job in jobs)
        or not isinstance(real_authorization, Mapping)
    ):
        _reject(
            "DISCOVERY_CURRENT_TASK_DRIFT",
            "current discovery task is outside the armed Path B boundary",
        )
    first_job = jobs[0]
    ordered_products = payload.get("product_ids")
    if not isinstance(ordered_products, list) or len(ordered_products) != 3:
        _reject(
            "DISCOVERY_CURRENT_TASK_DRIFT",
            "current discovery product order is not the exact three-product queue",
        )
    job_ids = [_positive_int(candidate.get("id"), "queue job id") for candidate in jobs]
    job_product_ids = [
        _positive_int(candidate.get("product_id"), "queue product id")
        for candidate in jobs
    ]
    ordered_product_ids = [
        _positive_int(value, "ordered product id") for value in ordered_products
    ]
    current_job_id = _positive_int(job_id, "command job id")
    first_job_id = _positive_int(first_job.get("id"), "first job id")
    first_product_id = _positive_int(first_job.get("product_id"), "first product id")
    statuses = [str(job.get("status") or "") for job in jobs]
    if (
        profile["target_task_id"] != _positive_int(task.get("id"), "task id")
        or profile["target_job_id"] != first_job_id
        or profile["target_product_id"] != first_product_id
        or len(set(job_ids)) != 3
        or len(set(job_product_ids)) != 3
        or job_product_ids != ordered_product_ids
        or current_job_id != first_job_id
        or command_state != PATH_B_SAVE1_DISCOVERY_STATE
        or command_action != PATH_B_SAVE1_DISCOVERY_ACTION
        or statuses[0] != "running"
        or statuses.count("running") != 1
        or any(status != "pending" for status in statuses[1:])
        or _non_negative_int(task.get("completed_jobs"), "completed jobs") != 0
        or _non_negative_int(task.get("failed_jobs"), "failed jobs") != 0
        or _sha256(real_authorization.get("scope_sha256"), "stored scope sha256")
        != profile["scope_sha256"]
        or _sha256(
            real_authorization.get("approval_sha256"),
            "stored approval sha256",
        )
        != profile["approval_sha256"]
    ):
        _reject(
            "DISCOVERY_DISPATCH_BOUNDARY_MISMATCH",
            "only the armed first-product composite FIRST_SAVE command may dispatch",
        )
    return profile


def validate_path_b_formal_lineage(value: Any) -> dict[str, Any]:
    """Validate the narrow sealed-Discovery to fresh-Formal execution grant."""

    required_keys = {
        "schema",
        "predecessor_scope_sha256",
        "discovery_receipt_sha256",
        "formal_scope_sha256",
        "lineage_sha256",
        "discovery_task_id",
        "discovery_snapshot_id",
        "discovery_snapshot_sha256",
        "formal_task_id",
        "formal_snapshot_id",
        "formal_snapshot_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != required_keys:
        _reject(
            "FORMAL_LINEAGE_INVALID",
            "formal Path B lineage has an unexpected shape",
        )
    lineage = deepcopy(dict(value))
    if lineage.get("schema") != PATH_B_FORMAL_LINEAGE_SCHEMA:
        _reject("FORMAL_LINEAGE_INVALID", "formal lineage schema is invalid")
    for key in (
        "predecessor_scope_sha256",
        "discovery_receipt_sha256",
        "formal_scope_sha256",
        "lineage_sha256",
        "discovery_snapshot_sha256",
        "formal_snapshot_sha256",
    ):
        lineage[key] = _sha256(lineage.get(key), key.replace("_", " "))
    for key in (
        "discovery_task_id",
        "discovery_snapshot_id",
        "formal_task_id",
        "formal_snapshot_id",
    ):
        lineage[key] = _positive_int(lineage.get(key), key.replace("_", " "))
    if (
        lineage["predecessor_scope_sha256"]
        == lineage["formal_scope_sha256"]
        or lineage["discovery_task_id"] == lineage["formal_task_id"]
        or lineage["discovery_snapshot_id"] == lineage["formal_snapshot_id"]
        or lineage["discovery_snapshot_sha256"]
        == lineage["formal_snapshot_sha256"]
    ):
        _reject(
            "FORMAL_LINEAGE_NOT_FRESH",
            "formal task, snapshot, and scope must all be fresh",
        )
    unsigned = {
        key: lineage[key]
        for key in (
            "predecessor_scope_sha256",
            "discovery_receipt_sha256",
            "formal_scope_sha256",
            "formal_task_id",
            "formal_snapshot_id",
            "formal_snapshot_sha256",
        )
    }
    expected_lineage_sha256 = canonical_contract_sha256(
        {
            "schemaVersion": PATH_B_FORMAL_LINEAGE_SCHEMA,
            "predecessorScopeSha256": unsigned["predecessor_scope_sha256"],
            "discoveryReceiptSha256": unsigned["discovery_receipt_sha256"],
            "formalScopeSha256": unsigned["formal_scope_sha256"],
            "formalTaskId": unsigned["formal_task_id"],
            "formalSnapshotId": unsigned["formal_snapshot_id"],
            "formalSnapshotSha256": unsigned["formal_snapshot_sha256"],
        }
    )
    if lineage["lineage_sha256"] != expected_lineage_sha256:
        _reject("FORMAL_LINEAGE_HASH_MISMATCH", "formal lineage hash differs")
    return lineage


def build_batch_queue_guard(task: Any, job_id: Any) -> dict[str, Any]:
    """Freeze the exact persisted queue generation and state seen by a command."""

    if not isinstance(task, Mapping):
        _reject("BATCH_QUEUE_TASK_INVALID", "batch task is missing")
    task_id = _positive_int(task.get("id"), "task id")
    current_job_id = _positive_int(job_id, "job id")
    payload = task.get("payload") if isinstance(task.get("payload"), Mapping) else {}
    jobs = task.get("jobs") if isinstance(task.get("jobs"), list) else []
    if not jobs:
        _reject("BATCH_QUEUE_EMPTY", "batch queue is empty")

    identities: list[dict[str, int]] = []
    states: list[dict[str, Any]] = []
    current_ordinal: int | None = None
    for ordinal, candidate in enumerate(jobs, start=1):
        if not isinstance(candidate, Mapping):
            _reject("BATCH_QUEUE_JOB_INVALID", "batch queue contains a non-object job")
        candidate_id = _positive_int(candidate.get("id"), "queue job id")
        product_id = _positive_int(candidate.get("product_id"), "queue product id")
        identities.append(
            {
                "ordinal": ordinal,
                "job_id": candidate_id,
                "product_id": product_id,
            }
        )
        states.append(
            {
                "ordinal": ordinal,
                "job_id": candidate_id,
                "status": _text(candidate.get("status"), "queue job status"),
                "current_step_code": str(candidate.get("current_step_code") or ""),
                "updated_at": _text(candidate.get("updated_at"), "queue job updated_at"),
            }
        )
        if candidate_id == current_job_id:
            if current_ordinal is not None:
                _reject("BATCH_QUEUE_JOB_DUPLICATE", "current job occurs more than once")
            current_ordinal = ordinal
    if current_ordinal is None:
        _reject("BATCH_QUEUE_JOB_MISSING", "current job is outside the persisted queue")

    epoch_facts = {
        "task_id": task_id,
        "task_created_at": _text(task.get("created_at"), "task created_at"),
        "plan_snapshot_id": _positive_int(
            payload.get("plan_snapshot_id"), "plan snapshot id"
        ),
        "plan_snapshot_hash": _sha256(
            payload.get("plan_snapshot_hash"), "plan snapshot hash"
        ),
        "ordered_jobs": identities,
    }
    queue_epoch = _canonical_sha256(epoch_facts)
    version_facts = {
        "queue_epoch": queue_epoch,
        "task_status": _text(task.get("status"), "task status"),
        "task_updated_at": _text(task.get("updated_at"), "task updated_at"),
        "completed_jobs": _non_negative_int(
            task.get("completed_jobs"), "completed_jobs"
        ),
        "failed_jobs": _non_negative_int(task.get("failed_jobs"), "failed_jobs"),
        "job_states": states,
    }
    return {
        "schema": BATCH_QUEUE_GUARD_SCHEMA,
        "queue_epoch": queue_epoch,
        "queue_version": _canonical_sha256(version_facts),
        "current_job_id": current_job_id,
        "current_ordinal": current_ordinal,
        "queue_total": len(jobs),
    }


def validate_current_batch_queue_guard(
    task: Any,
    job_id: Any,
    expected_guard: Any,
) -> dict[str, Any]:
    """Require an unchanged, strictly serial queue at the last mutation boundary."""

    current = build_batch_queue_guard(task, job_id)
    expected_guard = validate_batch_queue_guard_shape(expected_guard)
    for key, value in current.items():
        observed = expected_guard.get(key)
        if isinstance(value, str):
            if not isinstance(observed, str) or not hmac.compare_digest(value, observed):
                _reject("BATCH_QUEUE_VERSION_DRIFT", "persisted queue version has changed")
        elif observed != value:
            _reject("BATCH_QUEUE_VERSION_DRIFT", "persisted queue version has changed")

    jobs = task.get("jobs") if isinstance(task, Mapping) else None
    statuses = [str(job.get("status") or "") for job in jobs or []]
    current_index = current["current_ordinal"] - 1
    if (
        str(task.get("status") or "") != "running"
        or statuses[current_index] != "running"
        or statuses.count("running") != 1
        or any(status not in {"succeeded", "completed"} for status in statuses[:current_index])
        or any(status != "pending" for status in statuses[current_index + 1 :])
        or _non_negative_int(task.get("completed_jobs"), "completed_jobs") != current_index
        or _non_negative_int(task.get("failed_jobs"), "failed_jobs") != 0
    ):
        _reject("BATCH_QUEUE_STATE_INVALID", "current job is not the sole serial queue head")
    return current


def validate_batch_queue_guard_shape(value: Any) -> dict[str, Any]:
    """Validate the immutable queue token before it crosses a mutation boundary."""

    expected_keys = {
        "schema",
        "queue_epoch",
        "queue_version",
        "current_job_id",
        "current_ordinal",
        "queue_total",
    }
    if not isinstance(value, Mapping) or set(value) != expected_keys:
        _reject(
            "BATCH_QUEUE_GUARD_INVALID",
            "command queue guard has an unexpected shape",
        )
    if value.get("schema") != BATCH_QUEUE_GUARD_SCHEMA:
        _reject("BATCH_QUEUE_GUARD_INVALID", "command queue guard schema is invalid")
    guard = deepcopy(dict(value))
    guard["queue_epoch"] = _sha256(guard.get("queue_epoch"), "queue epoch")
    guard["queue_version"] = _sha256(
        guard.get("queue_version"),
        "queue version",
    )
    guard["current_job_id"] = _positive_int(
        guard.get("current_job_id"),
        "current job id",
    )
    guard["current_ordinal"] = _positive_int(
        guard.get("current_ordinal"),
        "current ordinal",
    )
    guard["queue_total"] = _positive_int(guard.get("queue_total"), "queue total")
    if guard["current_ordinal"] > guard["queue_total"]:
        _reject(
            "BATCH_QUEUE_GUARD_INVALID",
            "current queue ordinal exceeds the frozen queue length",
        )
    return guard


def validate_frozen_execution_readback(
    readback: Any,
    *,
    expected_payload: Mapping[str, Any],
    expected_phase: str = "before_ledger_begin_dispatch",
) -> dict[str, Any]:
    """Bind every page readback field to the exact frozen command payload."""

    if not isinstance(readback, Mapping) or set(readback) != {
        "schema",
        "ok",
        "phase",
        "execution_payload_hash",
        "field_count",
        "fields",
        "reason",
    }:
        _reject("FROZEN_EXECUTION_READBACK_INVALID", "readback shape is invalid")
    if not isinstance(expected_payload, Mapping):
        _reject("FROZEN_EXECUTION_PAYLOAD_INVALID", "expected payload is missing")
    payload = deepcopy(dict(expected_payload))
    payload_hash = _sha256(payload.get("payload_hash"), "payload_hash")
    payload_body = {key: value for key, value in payload.items() if key != "payload_hash"}
    if _canonical_sha256(payload_body) != payload_hash:
        _reject("FROZEN_EXECUTION_PAYLOAD_DRIFT", "expected payload hash does not match")
    if (
        readback.get("schema") != "dxm.frozen_execution.readback.v1"
        or readback.get("ok") is not True
        or readback.get("phase") != expected_phase
        or readback.get("reason") is not None
    ):
        _reject(
            "FROZEN_EXECUTION_READBACK_INVALID",
            "readback is not a successful attestation of the frozen payload",
        )
    if _sha256(
        readback.get("execution_payload_hash"),
        "readback execution_payload_hash",
    ) != payload_hash:
        _reject(
            "FROZEN_EXECUTION_READBACK_HASH_MISMATCH",
            "readback payload hash differs from the frozen command payload",
        )
    expected_fields = payload.get("fields")
    observed_fields = readback.get("fields")
    if (
        not isinstance(expected_fields, list)
        or not expected_fields
        or not isinstance(observed_fields, list)
        or type(readback.get("field_count")) is not int
        or readback.get("field_count") != len(expected_fields)
        or len(observed_fields) != len(expected_fields)
    ):
        _reject(
            "FROZEN_EXECUTION_READBACK_FIELD_SET_MISMATCH",
            "readback must contain every frozen field exactly once",
        )
    seen: set[str] = set()
    for index, (expected, observed) in enumerate(
        zip(expected_fields, observed_fields, strict=True)
    ):
        if not isinstance(expected, Mapping) or not isinstance(observed, Mapping):
            _reject(
                "FROZEN_EXECUTION_READBACK_FIELD_INVALID",
                f"readback field {index} is invalid",
            )
        if set(observed) != {
            "field_key",
            "ui_binding",
            "expected_value_hash",
            "observed_value_hash",
            "match_count",
            "aggregate_kind",
            "exact",
        }:
            _reject(
                "FROZEN_EXECUTION_READBACK_FIELD_INVALID",
                f"readback field {index} has an unexpected shape",
            )
        field_key = _text(expected.get("field_key"), "field_key")
        ui_binding = _text(expected.get("ui_binding"), "ui_binding")
        if field_key in seen:
            _reject(
                "FROZEN_EXECUTION_READBACK_FIELD_SET_MISMATCH",
                "frozen field keys are duplicated",
            )
        seen.add(field_key)
        expected_value_hash = _canonical_sha256(expected.get("resolved_value"))
        match_count = observed.get("match_count")
        aggregate_kind = observed.get("aggregate_kind")
        resolved_value = expected.get("resolved_value")
        binding_shape_valid = bool(
            type(match_count) is int
            and match_count > 0
            and aggregate_kind in {"single", "choice_group", "sku_rows"}
            and (
                (aggregate_kind == "single" and match_count == 1)
                or (
                    aggregate_kind == "choice_group"
                    and not isinstance(resolved_value, Mapping)
                    and resolved_value is not None
                )
                or (
                    aggregate_kind == "sku_rows"
                    and isinstance(resolved_value, list)
                    and match_count == len(resolved_value)
                )
            )
        )
        if (
            observed.get("field_key") != field_key
            or observed.get("ui_binding") != ui_binding
            or not binding_shape_valid
            or _sha256(
                observed.get("expected_value_hash"),
                f"readback {field_key} expected hash",
            )
            != expected_value_hash
            or _sha256(
                observed.get("observed_value_hash"),
                f"readback {field_key} observed hash",
            )
            != expected_value_hash
            or observed.get("exact") is not True
        ):
            _reject(
                "FROZEN_EXECUTION_READBACK_FIELD_MISMATCH",
                f"readback field {field_key} differs from the frozen payload",
            )
    return deepcopy(dict(readback))


def build_save_verification_context(
    task: Any,
    job: Any,
    *,
    save_command: Any,
    save_action_result: Any,
) -> dict[str, Any]:
    """Bind VERIFY to one exact authorized SAVE command and its canonical result."""

    if not isinstance(task, Mapping) or not isinstance(job, Mapping):
        _reject("SAVE_VERIFICATION_TASK_INVALID", "task and job are required")
    if not isinstance(save_command, Mapping) or not isinstance(save_action_result, Mapping):
        _reject(
            "SAVE_VERIFICATION_PREDECESSOR_INVALID",
            "the exact preceding SAVE command and action result are required",
        )
    task_id = _positive_int(task.get("id"), "task id")
    job_id = _positive_int(job.get("id"), "job id")
    save_state = str(save_command.get("state") or "")
    expected_save_action = {
        "SAVE_ONLY": "save_only",
        "SAVE2_ONLY": "save_only",
        PATH_B_SAVE1_DISCOVERY_STATE: PATH_B_SAVE1_DISCOVERY_ACTION,
    }.get(save_state)
    if (
        save_command.get("task_id") != task_id
        or save_command.get("job_id") != job_id
        or expected_save_action is None
        or save_command.get("action") != expected_save_action
        or save_command.get("execution_mode") != "batch_draft_save"
    ):
        _reject(
            "SAVE_VERIFICATION_PREDECESSOR_MISMATCH",
            "preceding command is not this batch job's exact SAVE command",
        )
    if (
        save_action_result.get("attempted_state") != save_state
        or save_action_result.get("action") != expected_save_action
        or save_action_result.get("ok") is not True
    ):
        _reject(
            "SAVE_VERIFICATION_RESULT_INVALID",
            "preceding SAVE action result is not canonical success evidence",
        )

    payload = task.get("payload") if isinstance(task.get("payload"), Mapping) else {}
    approval = (
        payload.get("manual_approval")
        if isinstance(payload.get("manual_approval"), Mapping)
        else {}
    )
    authorization_context = (
        approval.get("authorization_context")
        if isinstance(approval.get("authorization_context"), Mapping)
        else {}
    )
    worktree_identity = authorization_context.get("worktree_identity")
    if not isinstance(worktree_identity, Mapping):
        _reject(
            "SAVE_VERIFICATION_WORKTREE_REQUIRED",
            "authorized Git worktree identity is required",
        )
    save_params = (
        save_command.get("params")
        if isinstance(save_command.get("params"), Mapping)
        else {}
    )
    queue_guard = (
        save_params.get("batch_queue_guard")
        if isinstance(save_params.get("batch_queue_guard"), Mapping)
        else {}
    )
    page_identity = (
        save_action_result.get("page_identity")
        if isinstance(save_action_result.get("page_identity"), Mapping)
        else {}
    )
    body = {
        "schema": SAVE_VERIFICATION_CONTEXT_SCHEMA,
        "task_id": task_id,
        "job_id": job_id,
        "execution_mode": "batch_draft_save",
        "plan_snapshot_id": _positive_int(
            payload.get("plan_snapshot_id"), "plan snapshot id"
        ),
        "plan_snapshot_hash": _sha256(
            payload.get("plan_snapshot_hash"), "plan snapshot hash"
        ),
        "queue_epoch": _sha256(queue_guard.get("queue_epoch"), "queue epoch"),
        "queue_version": _sha256(queue_guard.get("queue_version"), "queue version"),
        "runtime_id": _text(save_command.get("runtime_id"), "runtime id"),
        "browser_session_id": _text(
            page_identity.get("browser_session_id"), "browser session id"
        ),
        "git_head": _git_head(authorization_context.get("git_head")),
        "worktree_identity_sha256": _canonical_sha256(dict(worktree_identity)),
        "authorization_fingerprint": _sha256(
            save_command.get("authorization_fingerprint"),
            "authorization fingerprint",
        ),
        "authorization_lease_id": _text(
            save_command.get("authorization_lease_id"), "authorization lease id"
        ),
        "stage_task_facts_fingerprint": _sha256(
            save_command.get("stage_task_facts_fingerprint"),
            "stage task facts fingerprint",
        ),
        "target_hash": _sha256(save_command.get("target_hash"), "target hash"),
        "execution_payload_hash": _sha256(
            save_command.get("execution_payload_hash"), "execution payload hash"
        ),
        "mutation_scope_id": _sha256(
            save_command.get("mutation_scope_id"), "mutation scope id"
        ),
        "save_command_id": _text(save_command.get("command_id"), "save command id"),
        "save_command_sha256": canonical_contract_sha256(dict(save_command)),
        "save_action_result_sha256": _canonical_sha256(dict(save_action_result)),
    }
    if body["authorization_fingerprint"] != _sha256(
        authorization_context.get("fingerprint"), "stored authorization fingerprint"
    ):
        _reject(
            "SAVE_VERIFICATION_AUTHORIZATION_MISMATCH",
            "SAVE command differs from the stored authorization context",
        )
    return {**body, "context_sha256": _canonical_sha256(body)}


def rebuild_save_verification_authority(
    task: Any,
    *,
    save_command: Any,
    ledger_entry: Any,
) -> dict[str, Any]:
    """Rebuild VERIFY facts from the persisted task and actual SAVE dispatch."""

    if not isinstance(task, Mapping):
        _reject(
            "SAVE_VERIFICATION_PREDECESSOR_FACTS_INVALID",
            "the persisted SAVE task is required",
        )
    if not isinstance(save_command, Mapping) or not isinstance(ledger_entry, Mapping):
        _reject(
            "SAVE_VERIFICATION_PREDECESSOR_FACTS_INVALID",
            "the persisted SAVE command and ledger entry are required",
        )
    task_id = _positive_int(task.get("id"), "task id")
    job_id = _positive_int(save_command.get("job_id"), "job id")
    save_state = str(save_command.get("state") or "")
    expected_save_action = {
        "SAVE_ONLY": "save_only",
        "SAVE2_ONLY": "save_only",
        PATH_B_SAVE1_DISCOVERY_STATE: PATH_B_SAVE1_DISCOVERY_ACTION,
    }.get(save_state)
    expected_mutation_action = (
        "first_save_intent"
        if save_state == PATH_B_SAVE1_DISCOVERY_STATE
        else "save_only_click"
    )
    if (
        str(task.get("mode") or "") != "batch_draft_save"
        or save_command.get("task_id") != task_id
        or expected_save_action is None
        or save_command.get("action") != expected_save_action
        or save_command.get("execution_mode") != "batch_draft_save"
    ):
        _reject(
            "SAVE_VERIFICATION_PREDECESSOR_FACTS_INVALID",
            "the persisted predecessor is not this task's batch SAVE command",
        )
    payload = task.get("payload") if isinstance(task.get("payload"), Mapping) else {}
    approval = (
        payload.get("manual_approval")
        if isinstance(payload.get("manual_approval"), Mapping)
        else {}
    )
    authorization_context = (
        approval.get("authorization_context")
        if isinstance(approval.get("authorization_context"), Mapping)
        else {}
    )
    worktree_identity = authorization_context.get("worktree_identity")
    if not isinstance(worktree_identity, Mapping):
        _reject(
            "SAVE_VERIFICATION_PREDECESSOR_FACTS_INVALID",
            "the persisted authorization worktree identity is required",
        )
    save_params = (
        save_command.get("params")
        if isinstance(save_command.get("params"), Mapping)
        else {}
    )
    queue_guard = validate_batch_queue_guard_shape(save_params.get("batch_queue_guard"))
    command_sha256 = canonical_contract_sha256(dict(save_command))
    if _sha256(
        ledger_entry.get("command_sha256"), "ledger SAVE command hash"
    ) != command_sha256:
        _reject(
            "SAVE_VERIFICATION_PREDECESSOR_FACTS_INVALID",
            "the persisted SAVE command digest does not match its ledger row",
        )
    exact_pairs = (
        (ledger_entry.get("status"), "DISPATCHED"),
        (ledger_entry.get("mutation_action"), expected_mutation_action),
        (ledger_entry.get("command_state"), save_state),
        (ledger_entry.get("command_action"), expected_save_action),
        (ledger_entry.get("task_id"), str(task_id)),
        (ledger_entry.get("job_id"), str(job_id)),
        (ledger_entry.get("command_id"), save_command.get("command_id")),
        (ledger_entry.get("runtime_id"), save_command.get("runtime_id")),
        (
            ledger_entry.get("authorization_lease_id"),
            save_command.get("authorization_lease_id"),
        ),
    )
    if any(observed != expected for observed, expected in exact_pairs):
        _reject(
            "SAVE_VERIFICATION_PREDECESSOR_FACTS_INVALID",
            "the persisted SAVE command differs from its ledger binding",
        )
    authorization_fingerprint = _sha256(
        save_command.get("authorization_fingerprint"), "authorization fingerprint"
    )
    if authorization_fingerprint != _sha256(
        authorization_context.get("fingerprint"),
        "persisted authorization fingerprint",
    ):
        _reject(
            "SAVE_VERIFICATION_PREDECESSOR_FACTS_INVALID",
            "the actual SAVE authorization differs from the persisted task approval",
        )
    real_authorization = (
        payload.get("real_dxm_write_authorization")
        if isinstance(payload.get("real_dxm_write_authorization"), Mapping)
        else None
    )
    expected_lease_id = approval.get("lease_id")
    if isinstance(real_authorization, Mapping):
        matching_jobs = [
            item
            for item in task.get("jobs", [])
            if isinstance(item, Mapping) and item.get("id") == job_id
        ]
        product_id = (
            matching_jobs[0].get("product_id") if len(matching_jobs) == 1 else None
        )
        save_stage = (
            "SAVE1"
            if save_state in {"SAVE_ONLY", PATH_B_SAVE1_DISCOVERY_STATE}
            else "SAVE2"
        )
        matching_leases = [
            item
            for item in real_authorization.get("save_leases", [])
            if isinstance(item, Mapping)
            and item.get("product_id") == product_id
            and item.get("save_stage") == save_stage
        ]
        expected_lease_id = (
            matching_leases[0].get("lease_id")
            if len(matching_leases) == 1
            else None
        )
    if _text(
        expected_lease_id, "persisted authorization lease id"
    ) != _text(save_command.get("authorization_lease_id"), "authorization lease id"):
        _reject(
            "SAVE_VERIFICATION_PREDECESSOR_FACTS_INVALID",
            "the actual SAVE lease differs from the persisted task approval",
        )
    return {
        "task_id": task_id,
        "job_id": job_id,
        "execution_mode": "batch_draft_save",
        "plan_snapshot_id": _positive_int(
            payload.get("plan_snapshot_id"), "plan snapshot id"
        ),
        "plan_snapshot_hash": _sha256(
            payload.get("plan_snapshot_hash"), "plan snapshot hash"
        ),
        "queue_epoch": queue_guard["queue_epoch"],
        "queue_version": queue_guard["queue_version"],
        "runtime_id": _text(save_command.get("runtime_id"), "runtime id"),
        "browser_session_id": _text(
            ledger_entry.get("browser_session_id"), "browser session id"
        ),
        "git_head": _git_head(authorization_context.get("git_head")),
        "worktree_identity_sha256": _canonical_sha256(dict(worktree_identity)),
        "authorization_fingerprint": authorization_fingerprint,
        "authorization_lease_id": _text(
            save_command.get("authorization_lease_id"), "authorization lease id"
        ),
        "stage_task_facts_fingerprint": _sha256(
            save_command.get("stage_task_facts_fingerprint"),
            "stage task facts fingerprint",
        ),
        "target_hash": _sha256(save_command.get("target_hash"), "target hash"),
        "execution_payload_hash": _sha256(
            save_command.get("execution_payload_hash"), "execution payload hash"
        ),
        "mutation_scope_id": _sha256(
            save_command.get("mutation_scope_id"), "mutation scope id"
        ),
        "save_command_id": _text(save_command.get("command_id"), "save command id"),
        "save_command_sha256": command_sha256,
    }


def validate_save_verification_context(
    value: Any,
    *,
    task_id: Any | None = None,
    job_id: Any | None = None,
    runtime_id: Any | None = None,
    execution_mode: Any | None = None,
    save_command: Mapping[str, Any] | None = None,
    save_action_result: Mapping[str, Any] | None = None,
    authoritative_facts: Mapping[str, Any] | None = None,
    structural_only: bool = False,
) -> dict[str, Any]:
    """Validate the immutable SAVE predecessor attestation carried by VERIFY."""

    expected_keys = {
        "schema",
        "task_id",
        "job_id",
        "execution_mode",
        "plan_snapshot_id",
        "plan_snapshot_hash",
        "queue_epoch",
        "queue_version",
        "runtime_id",
        "browser_session_id",
        "git_head",
        "worktree_identity_sha256",
        "authorization_fingerprint",
        "authorization_lease_id",
        "stage_task_facts_fingerprint",
        "target_hash",
        "execution_payload_hash",
        "mutation_scope_id",
        "save_command_id",
        "save_command_sha256",
        "save_action_result_sha256",
        "context_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != expected_keys:
        _reject(
            "SAVE_VERIFICATION_CONTEXT_INVALID",
            "SAVE verification context has an unexpected shape",
        )
    context = deepcopy(dict(value))
    if context.get("schema") != SAVE_VERIFICATION_CONTEXT_SCHEMA:
        _reject(
            "SAVE_VERIFICATION_CONTEXT_INVALID",
            "SAVE verification context schema is invalid",
        )
    for key in (
        "plan_snapshot_hash",
        "queue_epoch",
        "queue_version",
        "worktree_identity_sha256",
        "authorization_fingerprint",
        "stage_task_facts_fingerprint",
        "target_hash",
        "execution_payload_hash",
        "mutation_scope_id",
        "save_command_sha256",
        "save_action_result_sha256",
        "context_sha256",
    ):
        context[key] = _sha256(context.get(key), key.replace("_", " "))
    context["task_id"] = _positive_int(context.get("task_id"), "task id")
    context["job_id"] = _positive_int(context.get("job_id"), "job id")
    context["plan_snapshot_id"] = _positive_int(
        context.get("plan_snapshot_id"), "plan snapshot id"
    )
    for key in (
        "execution_mode",
        "runtime_id",
        "browser_session_id",
        "authorization_lease_id",
        "save_command_id",
    ):
        context[key] = _text(context.get(key), key.replace("_", " "))
    context["git_head"] = _git_head(context.get("git_head"))
    body = {key: context[key] for key in context if key != "context_sha256"}
    if _canonical_sha256(body) != context["context_sha256"]:
        _reject(
            "SAVE_VERIFICATION_CONTEXT_HASH_MISMATCH",
            "SAVE verification context hash does not match its facts",
        )
    if task_id is not None and context["task_id"] != _positive_int(task_id, "task id"):
        _reject("SAVE_VERIFICATION_TASK_MISMATCH", "VERIFY task differs from SAVE")
    if job_id is not None and context["job_id"] != _positive_int(job_id, "job id"):
        _reject("SAVE_VERIFICATION_JOB_MISMATCH", "VERIFY job differs from SAVE")
    if runtime_id is not None and context["runtime_id"] != _text(runtime_id, "runtime id"):
        _reject("SAVE_VERIFICATION_RUNTIME_MISMATCH", "VERIFY runtime differs from SAVE")
    if execution_mode is not None and context["execution_mode"] != _text(
        execution_mode, "execution mode"
    ):
        _reject("SAVE_VERIFICATION_MODE_MISMATCH", "VERIFY mode differs from SAVE")
    if save_command is not None and context["save_command_sha256"] != canonical_contract_sha256(
        dict(save_command)
    ):
        _reject(
            "SAVE_VERIFICATION_COMMAND_MISMATCH",
            "VERIFY is not bound to this exact SAVE command",
        )
    if save_action_result is not None and context["save_action_result_sha256"] != _canonical_sha256(
        dict(save_action_result)
    ):
        _reject(
            "SAVE_VERIFICATION_RESULT_MISMATCH",
            "VERIFY is not bound to this exact SAVE action result",
        )
    if authoritative_facts is None:
        if structural_only is not True:
            _reject(
                "SAVE_VERIFICATION_AUTHORITY_REQUIRED",
                "SAVE verification metadata requires persisted predecessor authority",
            )
    else:
        if not isinstance(authoritative_facts, Mapping) or not authoritative_facts:
            _reject(
                "SAVE_VERIFICATION_PREDECESSOR_FACTS_INVALID",
                "persisted SAVE verification authority is invalid",
            )
        for key, expected in authoritative_facts.items():
            if key not in context or context[key] != expected:
                _reject(
                    "SAVE_VERIFICATION_AUTHORITY_MISMATCH",
                    f"SAVE verification field {key} differs from persisted authority",
                )
    return context


def canonical_contract_sha256(value: Any) -> str:
    """Return the one canonical JSON digest used by cross-layer E3 contracts."""

    return _canonical_sha256(value)


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        _reject("BATCH_QUEUE_ID_INVALID", f"{label} must be a positive integer")
    return value


def _non_negative_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _reject("BATCH_QUEUE_COUNT_INVALID", f"{label} must be a non-negative integer")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        _reject("BATCH_QUEUE_TEXT_INVALID", f"{label} must be canonical text")
    return value


def _sha256(value: Any, label: str) -> str:
    text = _text(value, label).upper()
    if len(text) != 64 or any(character not in "0123456789ABCDEF" for character in text):
        _reject("BATCH_QUEUE_HASH_INVALID", f"{label} must be SHA-256")
    return text


def _git_head(value: Any) -> str:
    text = _text(value, "git head").lower()
    if len(text) != 40 or any(character not in "0123456789abcdef" for character in text):
        _reject("SAVE_VERIFICATION_GIT_HEAD_INVALID", "git head must be a full SHA-1")
    return text


def _canonical_sha256(value: Any) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise BatchCommandContractError(
            "BATCH_COMMAND_CANONICAL_JSON_REQUIRED",
            "batch command facts must be canonical JSON",
        ) from exc
    return hashlib.sha256(encoded).hexdigest().upper()


def _reject(reason_code: str, detail: str) -> None:
    raise BatchCommandContractError(reason_code, detail)
