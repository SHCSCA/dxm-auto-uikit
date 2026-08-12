from __future__ import annotations

import hmac
import json
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlsplit

from src.batch_edit.frozen_execution_contract import (
    FrozenExecutionContractError,
    compile_frozen_execution_payload,
    validate_frozen_execution_defaults,
)
from src.batch_edit.scope_contract import ScopeContractError, canonical_sha256
from src.db import loads
from src.execution.action_result_contract import controlled_dxm_page_identity
from src.execution.batch_command_contract import (
    SAVE_VERIFICATION_CONTEXT_SCHEMA,
    BatchCommandContractError,
    canonical_contract_sha256,
    validate_current_batch_queue_guard,
)
from src.execution.browser_agent_protocol import (
    BrowserAgentCommand,
    MutationCommandContractError,
    canonical_frozen_target_identity,
    canonical_mutation_target_payload,
    mutation_target_hash,
    validate_browser_agent_command,
)
from src.execution.e3_authority_contract import (
    authorization_lease_authority_fingerprint,
    canonical_authorization_lease_authority,
)
from src.state_machine.two_stage import (
    TwoStageContractError,
    authorization_context_fingerprint,
    build_batch_draft_save_task_facts,
    verify_authorization_context,
)


@dataclass(frozen=True)
class LiveDispatchFacts:
    """Trusted process facts sampled outside the caller-controlled command."""

    runtime_instance_id: str
    browser_runtime_id: str
    browser_session_id: str
    git_head: str
    worktree_identity: Mapping[str, Any]
    l2_status: str
    l2_evidence_fingerprint: str


@dataclass(frozen=True)
class DispatchAuthorityDecision:
    ok: bool
    reason_code: str
    authority: Mapping[str, Any] | None = None
    authority_sha256: str | None = None


class _FrozenDict(dict):
    """JSON-compatible recursively immutable canonical mapping."""

    def _immutable(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("dispatch authority is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable

    def __deepcopy__(self, memo: dict[int, Any]) -> "_FrozenDict":
        return self


class DispatchAuthorityError(ValueError):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


def validate_in_transaction(
    conn: Any,
    command: BrowserAgentCommand,
    identity: Mapping[str, Any],
    live_facts: LiveDispatchFacts,
) -> DispatchAuthorityDecision:
    """Rebuild the complete batch SAVE authority on an existing DB transaction.

    The caller must acquire ``BEGIN IMMEDIATE`` before calling. This function
    never opens another database connection and never trusts command parameters
    as the source of live L2, Git, runtime, or browser-session facts.
    """

    try:
        authority = _validate(conn, command, identity, live_facts)
    except DispatchAuthorityError as exc:
        return DispatchAuthorityDecision(False, exc.reason_code)
    frozen = _deep_freeze(authority)
    return DispatchAuthorityDecision(
        True,
        "OK",
        authority=frozen,
        authority_sha256=canonical_sha256(frozen),
    )


def snapshot_row_authority_in_transaction(
    conn: Any,
    task_id: int,
) -> dict[str, Any]:
    """Rebuild immutable E2 snapshot-row and idempotency provenance facts."""

    task = _load_task_by_id(conn, task_id)
    payload = task.get("payload") if isinstance(task.get("payload"), Mapping) else {}
    snapshot_id = payload.get("plan_snapshot_id")
    if isinstance(snapshot_id, bool) or not isinstance(snapshot_id, int) or snapshot_id <= 0:
        _reject("AUTH_SNAPSHOT_ROW_AUTHORITY_MISMATCH")
    row = conn.execute(
        "SELECT * FROM plan_snapshots WHERE id=?",
        (snapshot_id,),
    ).fetchone()
    if row is None:
        _reject("AUTH_SNAPSHOT_ROW_AUTHORITY_MISMATCH")
    stored = dict(row)
    snapshot = loads(stored.get("snapshot_json"), {})
    if not isinstance(snapshot, dict):
        _reject("AUTH_SNAPSHOT_ROW_AUTHORITY_MISMATCH")
    snapshot_body = {
        key: value for key, value in snapshot.items() if key != "snapshot_hash"
    }
    local_plan = snapshot.get("local_plan_template")
    idempotency_key = stored.get("idempotency_key")
    created_at = stored.get("created_at")
    try:
        snapshot_body_sha256 = canonical_sha256(snapshot_body)
        embedded_snapshot_sha256 = canonical_sha256(payload.get("plan_snapshot"))
        stored_snapshot_sha256 = canonical_sha256(snapshot)
    except (ScopeContractError, TypeError, ValueError):
        _reject("AUTH_SNAPSHOT_ROW_AUTHORITY_MISMATCH")
    if (
        snapshot_body_sha256 != snapshot.get("snapshot_hash")
        or stored.get("snapshot_hash") != snapshot.get("snapshot_hash")
        or payload.get("plan_snapshot_hash") != snapshot.get("snapshot_hash")
        or embedded_snapshot_sha256 != stored_snapshot_sha256
        or stored.get("task_id") != task_id
        or not isinstance(local_plan, Mapping)
        or stored.get("local_plan_template_id") != local_plan.get("id")
        or not isinstance(idempotency_key, str)
        or not idempotency_key
        or not isinstance(created_at, str)
        or not created_at
    ):
        _reject("AUTH_SNAPSHOT_ROW_AUTHORITY_MISMATCH")
    provenance = conn.execute(
        """
        SELECT * FROM plan_snapshot_idempotency_keys
         WHERE idempotency_key=?
        """,
        (idempotency_key,),
    ).fetchone()
    if (
        provenance is None
        or provenance.get("snapshot_id") != snapshot_id
        or provenance.get("snapshot_hash") != snapshot.get("snapshot_hash")
        or not isinstance(provenance.get("created_at"), str)
        or not provenance.get("created_at")
    ):
        _reject("AUTH_SNAPSHOT_ROW_AUTHORITY_MISMATCH")
    return {
        "schema": "dxm.batch_draft_save.snapshot_row_authority.v1",
        "task_id": task_id,
        "snapshot_json_sha256": canonical_sha256(snapshot),
        "row": {
            "id": snapshot_id,
            "task_id": stored["task_id"],
            "local_plan_template_id": stored["local_plan_template_id"],
            "snapshot_hash": stored["snapshot_hash"],
            "idempotency_key": idempotency_key,
            "created_at": created_at,
        },
        "idempotency_provenance": {
            "idempotency_key": provenance["idempotency_key"],
            "snapshot_id": provenance["snapshot_id"],
            "snapshot_hash": provenance["snapshot_hash"],
            "created_at": provenance["created_at"],
        },
    }


def snapshot_row_authority_fingerprint_in_transaction(
    conn: Any,
    task_id: int,
) -> str:
    return canonical_sha256(snapshot_row_authority_in_transaction(conn, task_id))


def validate_current_task_against_frozen_authority(
    conn: Any,
    authority: Mapping[str, Any],
) -> DispatchAuthorityDecision:
    """Compare current persisted task/snapshot facts with a frozen SAVE authority."""

    try:
        canonical = _validated_authority(authority)
        expected_task = canonical["task_authority"]
        task = _load_task_by_id(conn, expected_task.get("task_id"))
        current_task = _task_authority_projection(task)
        if canonical_sha256(current_task) != canonical_sha256(expected_task):
            _reject("AUTH_CURRENT_TASK_DRIFT")
        snapshot_id = canonical["snapshot"]["plan_snapshot_id"]
        row = conn.execute(
            "SELECT * FROM plan_snapshots WHERE id=?",
            (snapshot_id,),
        ).fetchone()
        current_snapshot = loads(row["snapshot_json"], {}) if row is not None else None
        current_row_binding = (
            {
                "id": int(row["id"]),
                "task_id": row["task_id"],
                "snapshot_hash": row["snapshot_hash"],
                "local_plan_template_id": row["local_plan_template_id"],
                "idempotency_key": row["idempotency_key"],
                "created_at": row["created_at"],
            }
            if row is not None
            else None
        )
        if (
            current_row_binding != canonical["snapshot"].get("row_binding")
            or canonical_sha256(current_snapshot)
            != canonical_sha256(canonical["snapshot"]["plan_snapshot"])
        ):
            _reject("AUTH_CURRENT_TASK_DRIFT")
        provenance = conn.execute(
            """
            SELECT snapshot_id, snapshot_hash
              FROM plan_snapshot_idempotency_keys
             WHERE idempotency_key=?
            """,
            (canonical["snapshot"]["row_binding"]["idempotency_key"],),
        ).fetchone()
        if (
            provenance is None
            or provenance["snapshot_id"] != snapshot_id
            or provenance["snapshot_hash"]
            != canonical["snapshot"]["plan_snapshot_hash"]
        ):
            _reject("AUTH_CURRENT_TASK_DRIFT")
        _validate_current_queue_against_frozen_authority(
            task,
            canonical["queue"],
        )
    except DispatchAuthorityError as exc:
        return DispatchAuthorityDecision(False, exc.reason_code)
    frozen = _deep_freeze(canonical)
    return DispatchAuthorityDecision(
        True,
        "OK",
        authority=frozen,
        authority_sha256=canonical_sha256(frozen),
    )


def validate_current_live_facts_against_frozen_authority(
    authority: Mapping[str, Any],
    live_facts: LiveDispatchFacts,
) -> DispatchAuthorityDecision:
    """Re-sample trusted process facts before a restarted VERIFY is accepted.

    The SAVE authority freezes the exact L2, code, worktree, backend runtime,
    browser runtime and browser-context generation that performed the click.
    A caller-authored VERIFY context cannot prove those facts are still the
    current ones after a process/lifecycle boundary, so the ledger must obtain
    them from its trusted provider and compare every component here.
    """

    try:
        canonical = _validated_authority(authority)
        if not isinstance(live_facts, LiveDispatchFacts):
            _reject("AUTH_DISPATCH_AUTHORITY_UNAVAILABLE")

        frozen_l2 = canonical["l2"]
        if live_facts.l2_status != "passed":
            _reject("AUTH_L2_GATE_NOT_PASSED")
        if (
            frozen_l2.get("status") != live_facts.l2_status
            or frozen_l2.get("evidence_fingerprint")
            != live_facts.l2_evidence_fingerprint
        ):
            _reject("AUTH_L2_EVIDENCE_MISMATCH")

        frozen_code = canonical["code_identity"]
        if frozen_code.get("git_head") != live_facts.git_head:
            _reject("AUTH_GIT_HEAD_MISMATCH")
        try:
            frozen_worktree_sha256 = canonical_sha256(
                frozen_code.get("worktree_identity")
            )
            current_worktree_sha256 = canonical_sha256(
                dict(live_facts.worktree_identity)
            )
        except (ScopeContractError, TypeError, ValueError):
            _reject("AUTH_WORKTREE_IDENTITY_MISMATCH")
        if not hmac.compare_digest(
            frozen_worktree_sha256.casefold(),
            current_worktree_sha256.casefold(),
        ):
            _reject("AUTH_WORKTREE_IDENTITY_MISMATCH")

        frozen_runtime = canonical["runtime"]
        if (
            frozen_runtime.get("runtime_instance_id")
            != live_facts.runtime_instance_id
            or frozen_runtime.get("browser_runtime_id")
            != live_facts.browser_runtime_id
        ):
            _reject("AUTH_RUNTIME_IDENTITY_MISMATCH")
        if (
            frozen_runtime.get("browser_session_id")
            != live_facts.browser_session_id
        ):
            _reject("AUTH_BROWSER_SESSION_MISMATCH")
    except DispatchAuthorityError as exc:
        return DispatchAuthorityDecision(False, exc.reason_code)

    frozen = _deep_freeze(canonical)
    return DispatchAuthorityDecision(
        True,
        "OK",
        authority=frozen,
        authority_sha256=canonical_sha256(frozen),
    )


def save_verification_facts_from_frozen_authority(
    authority: Mapping[str, Any],
    *,
    save_command: BrowserAgentCommand | Mapping[str, Any],
    ledger_entry: Mapping[str, Any],
    save_action_result_sha256: str,
) -> dict[str, Any]:
    """Map a persisted SAVE authority to the sole authoritative VERIFY context."""

    canonical = _validated_authority(authority)
    command_payload = (
        save_command.to_payload()
        if isinstance(save_command, BrowserAgentCommand)
        else deepcopy(dict(save_command)) if isinstance(save_command, Mapping) else None
    )
    if not isinstance(command_payload, dict):
        _reject("SAVE_VERIFICATION_PREDECESSOR_FACTS_INVALID")
    frozen_command = canonical["command"]
    command_sha256 = canonical_contract_sha256(command_payload)
    if (
        command_payload != frozen_command["payload"]
        or command_sha256 != frozen_command["sha256"]
        or not isinstance(ledger_entry, Mapping)
        or ledger_entry.get("status") != "DISPATCHED"
        or ledger_entry.get("mutation_action") != "save_only_click"
        or str(ledger_entry.get("task_id"))
        != str(canonical["task_authority"]["task_id"])
        or str(ledger_entry.get("job_id"))
        != str(command_payload.get("job_id"))
        or str(ledger_entry.get("command_sha256") or "").casefold()
        != command_sha256.casefold()
    ):
        _reject("SAVE_VERIFICATION_PREDECESSOR_FACTS_INVALID")
    action_hash = _sha256_text(
        save_action_result_sha256,
        "SAVE_VERIFICATION_PREDECESSOR_FACTS_INVALID",
    )
    if str(ledger_entry.get("save_action_result_sha256") or "").casefold() != (
        action_hash.casefold()
    ):
        _reject("SAVE_VERIFICATION_RESULT_MISMATCH")
    authority_hash = canonical_sha256(canonical)
    stored_authority_hash = ledger_entry.get("save_authority_sha256")
    raw_authority = ledger_entry.get("save_authority_json")
    try:
        persisted_authority = json.loads(raw_authority)
    except (TypeError, ValueError):
        _reject("SAVE_VERIFICATION_PREDECESSOR_FACTS_INVALID")
    if (
        not isinstance(stored_authority_hash, str)
        or stored_authority_hash.casefold() != authority_hash.casefold()
        or canonical_sha256(persisted_authority).casefold() != authority_hash.casefold()
        or persisted_authority != canonical
    ):
        _reject("SAVE_VERIFICATION_PREDECESSOR_FACTS_INVALID")

    authorization = canonical["authorization"]
    snapshot = canonical["snapshot"]
    queue_guard = canonical["queue"]["guard"]
    runtime = canonical["runtime"]
    code_identity = canonical["code_identity"]
    body = {
        "schema": SAVE_VERIFICATION_CONTEXT_SCHEMA,
        "task_id": int(canonical["task_authority"]["task_id"]),
        "job_id": int(command_payload["job_id"]),
        "execution_mode": "batch_draft_save",
        "plan_snapshot_id": int(snapshot["plan_snapshot_id"]),
        "plan_snapshot_hash": _sha256_text(
            snapshot["plan_snapshot_hash"],
            "SAVE_VERIFICATION_PREDECESSOR_FACTS_INVALID",
        ),
        "queue_epoch": _sha256_text(
            queue_guard["queue_epoch"],
            "SAVE_VERIFICATION_PREDECESSOR_FACTS_INVALID",
        ),
        "queue_version": _sha256_text(
            queue_guard["queue_version"],
            "SAVE_VERIFICATION_PREDECESSOR_FACTS_INVALID",
        ),
        "runtime_id": runtime["browser_runtime_id"],
        "browser_session_id": runtime["browser_session_id"],
        "git_head": code_identity["git_head"],
        "worktree_identity_sha256": canonical_sha256(code_identity["worktree_identity"]),
        "authorization_fingerprint": _sha256_text(
            authorization["authorization_context"]["fingerprint"],
            "SAVE_VERIFICATION_PREDECESSOR_FACTS_INVALID",
        ),
        "authorization_lease_id": authorization["lease_id"],
        "stage_task_facts_fingerprint": _sha256_text(
            authorization["stage_task_facts"]["fingerprint"],
            "SAVE_VERIFICATION_PREDECESSOR_FACTS_INVALID",
        ),
        "target_hash": _sha256_text(
            canonical["target"]["target_hash"],
            "SAVE_VERIFICATION_PREDECESSOR_FACTS_INVALID",
        ),
        "execution_payload_hash": _sha256_text(
            canonical["execution"]["payload_hash"],
            "SAVE_VERIFICATION_PREDECESSOR_FACTS_INVALID",
        ),
        "mutation_scope_id": _sha256_text(
            command_payload["mutation_scope_id"],
            "SAVE_VERIFICATION_PREDECESSOR_FACTS_INVALID",
        ),
        "save_command_id": command_payload["command_id"],
        "save_command_sha256": command_sha256,
        "save_action_result_sha256": action_hash,
    }
    return {**body, "context_sha256": canonical_sha256(body)}


def _validate(
    conn: Any,
    command: BrowserAgentCommand,
    identity: Mapping[str, Any],
    live: LiveDispatchFacts,
) -> dict[str, Any]:
    if not isinstance(live, LiveDispatchFacts):
        _reject("AUTH_DISPATCH_AUTHORITY_UNAVAILABLE")
    try:
        validate_browser_agent_command(command)
    except (MutationCommandContractError, TypeError, ValueError):
        _reject("AUTH_COMMAND_CONTRACT_INVALID")
    if (
        command.execution_mode != "batch_draft_save"
        or command.state != "SAVE_ONLY"
        or command.action != "save_only"
        or command.expected_page != "editor"
    ):
        _reject("AUTH_COMMAND_MODE_MISMATCH")

    task = _load_task(conn, command)
    snapshot, item_snapshot, job, snapshot_row = _load_snapshot_binding(
        conn, task, command
    )
    current_queue_guard = _validate_queue(task, command)
    stage_facts, stored_context, lease_authority = _validate_authorization(
        task,
        snapshot,
        command,
        live,
    )
    target_hash, target_identity, target_payload = _validate_target(
        item_snapshot, snapshot, command
    )
    execution_payload = _validate_execution(task, job, command)
    _validate_live_identity(
        identity,
        command,
        live,
        target_hash,
        target_identity,
    )

    payload = task["payload"]
    approval = payload["manual_approval"]
    ordered_jobs = [
        {
            "ordinal": ordinal,
            "job_id": int(candidate["id"]),
            "product_id": str(candidate["product_id"]),
            "status": str(candidate["status"]),
            "current_step_code": str(candidate.get("current_step_code") or ""),
            "updated_at": str(candidate["updated_at"]),
        }
        for ordinal, candidate in enumerate(task["jobs"], start=1)
    ]
    task_authority = _task_authority_projection(task)
    return {
        "schema": "dxm.batch_draft_save.dispatch_authority.v1",
        "task_authority": task_authority,
        "authorization": {
            "lease_id": str(command.authorization_lease_id),
            "lease_fingerprint": str(command.authorization_lease_fingerprint),
            "lease_authority": lease_authority,
            "authorization_context": deepcopy(stored_context),
            "stage_task_facts": deepcopy(stage_facts),
        },
        "l2": {
            "status": live.l2_status,
            "evidence_fingerprint": live.l2_evidence_fingerprint,
        },
        "snapshot": {
            "plan_snapshot_id": int(payload["plan_snapshot_id"]),
            "plan_snapshot_hash": snapshot["snapshot_hash"],
            "row_binding": snapshot_row,
            "plan_snapshot": deepcopy(snapshot),
        },
        "queue": {
            "guard": deepcopy(current_queue_guard),
            "task_status": str(task["status"]),
            "task_updated_at": str(task["updated_at"]),
            "completed_jobs": int(task["completed_jobs"]),
            "failed_jobs": int(task["failed_jobs"]),
            "ordered_jobs": ordered_jobs,
        },
        "code_identity": {
            "git_head": live.git_head,
            "worktree_identity": deepcopy(dict(live.worktree_identity)),
        },
        "runtime": {
            "runtime_instance_id": live.runtime_instance_id,
            "browser_runtime_id": live.browser_runtime_id,
            "browser_session_id": live.browser_session_id,
        },
        "browser_identity": deepcopy(dict(identity)),
        "target": {
            "identity": deepcopy(target_identity),
            "payload": deepcopy(target_payload),
            "target_hash": target_hash,
        },
        "execution": {
            "payload": deepcopy(execution_payload),
            "payload_hash": execution_payload["payload_hash"],
        },
        "command": {
            "payload": command.to_payload(),
            "sha256": canonical_contract_sha256(command.to_payload()),
        },
    }


def _load_task(conn: Any, command: BrowserAgentCommand) -> dict[str, Any]:
    return _load_task_by_id(conn, command.task_id)


def _load_task_by_id(conn: Any, task_id: Any) -> dict[str, Any]:
    if isinstance(task_id, bool) or not isinstance(task_id, int) or task_id <= 0:
        _reject("AUTH_TASK_NOT_FOUND")
    row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if row is None:
        _reject("AUTH_TASK_NOT_FOUND")
    task = dict(row)
    task["payload"] = loads(task.pop("payload_json", None), {})
    task["jobs"] = [
        dict(job)
        for job in conn.execute(
            "SELECT * FROM jobs WHERE task_id=? ORDER BY id ASC",
            (task_id,),
        ).fetchall()
    ]
    if task.get("mode") != "batch_draft_save":
        _reject("AUTH_COMMAND_MODE_MISMATCH")
    return task


def _task_authority_projection(task: Mapping[str, Any]) -> dict[str, Any]:
    payload = task.get("payload") if isinstance(task.get("payload"), Mapping) else {}
    approval = (
        payload.get("manual_approval")
        if isinstance(payload.get("manual_approval"), Mapping)
        else None
    )
    if not isinstance(approval, Mapping):
        _reject("AUTH_CURRENT_TASK_DRIFT")
    return {
        "task_id": int(task["id"]),
        "execution_mode": str(task.get("mode") or ""),
        "task_status": str(task.get("status") or ""),
        "store_id": int(task["store_id"]),
        "publish_scene": str(task.get("publish_scene") or ""),
        "plan_snapshot_id": int(payload["plan_snapshot_id"]),
        "plan_snapshot_hash": str(payload["plan_snapshot_hash"]),
        "path": str(payload.get("path") or ""),
        "publish_allowed": payload.get("publish_allowed"),
        # VERIFY/restart must bind every frozen E2 input, not only the public
        # snapshot pointer. Keeping the complete canonical payload here makes
        # resolution/category/schema/session/product drift observable even
        # when an attacker preserves the outer plan_snapshot_id/hash fields.
        "task_payload": deepcopy(dict(payload)),
        "manual_approval": deepcopy(dict(approval)),
    }


def _validate_current_queue_against_frozen_authority(
    task: Mapping[str, Any],
    frozen_queue: Any,
) -> None:
    if not isinstance(frozen_queue, Mapping):
        _reject("AUTH_CURRENT_QUEUE_DRIFT")
    frozen_jobs = frozen_queue.get("ordered_jobs")
    current_jobs = task.get("jobs")
    if not isinstance(frozen_jobs, list) or not isinstance(current_jobs, list):
        _reject("AUTH_CURRENT_QUEUE_DRIFT")
    frozen_identity = [
        {
            "ordinal": item.get("ordinal"),
            "job_id": item.get("job_id"),
            "product_id": str(item.get("product_id")),
        }
        for item in frozen_jobs
        if isinstance(item, Mapping)
    ]
    current_identity = [
        {
            "ordinal": ordinal,
            "job_id": int(item.get("id")),
            "product_id": str(item.get("product_id")),
        }
        for ordinal, item in enumerate(current_jobs, start=1)
        if isinstance(item, Mapping)
    ]
    current_job_id = frozen_queue.get("guard", {}).get("current_job_id")
    statuses = [str(item.get("status") or "") for item in current_jobs]
    current_indexes = [
        index
        for index, item in enumerate(current_jobs)
        if item.get("id") == current_job_id
    ]
    if (
        frozen_identity != current_identity
        or len(current_indexes) != 1
        or str(task.get("status") or "") != "running"
    ):
        _reject("AUTH_CURRENT_QUEUE_DRIFT")
    current_index = current_indexes[0]
    if (
        statuses[current_index] != "running"
        or statuses.count("running") != 1
        or any(status not in {"succeeded", "completed"} for status in statuses[:current_index])
        or any(status != "pending" for status in statuses[current_index + 1 :])
        or int(task.get("completed_jobs") or 0) != current_index
        or int(task.get("failed_jobs") or 0) != 0
    ):
        _reject("AUTH_CURRENT_QUEUE_DRIFT")
    step = str(current_jobs[current_index].get("current_step_code") or "")
    if step not in {"SAVE_ONLY", "VERIFY_NOT_PUBLISHED"}:
        _reject("AUTH_CURRENT_QUEUE_DRIFT")


def _load_snapshot_binding(
    conn: Any,
    task: Mapping[str, Any],
    command: BrowserAgentCommand,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    payload = task.get("payload") if isinstance(task.get("payload"), Mapping) else {}
    snapshot_id = payload.get("plan_snapshot_id")
    if isinstance(snapshot_id, bool) or not isinstance(snapshot_id, int) or snapshot_id <= 0:
        _reject("AUTH_COMMAND_SNAPSHOT_MISMATCH")
    row = conn.execute("SELECT * FROM plan_snapshots WHERE id=?", (snapshot_id,)).fetchone()
    if row is None:
        _reject("AUTH_COMMAND_SNAPSHOT_MISMATCH")
    stored_row = dict(row)
    snapshot = loads(stored_row.get("snapshot_json"), {})
    if not isinstance(snapshot, dict):
        _reject("AUTH_COMMAND_SNAPSHOT_MISMATCH")
    snapshot_hash = snapshot.get("snapshot_hash")
    body = {key: value for key, value in snapshot.items() if key != "snapshot_hash"}
    try:
        reproduced_hash = canonical_sha256(body)
        embedded_hash = canonical_sha256(payload.get("plan_snapshot"))
        stored_hash = canonical_sha256(snapshot)
    except (ScopeContractError, TypeError, ValueError):
        _reject("AUTH_COMMAND_SNAPSHOT_MISMATCH")
    row_task_id = stored_row.get("task_id")
    if (
        not isinstance(snapshot_hash, str)
        or not hmac.compare_digest(snapshot_hash, reproduced_hash)
        or stored_row.get("snapshot_hash") != snapshot_hash
        or payload.get("plan_snapshot_hash") != snapshot_hash
        or embedded_hash != stored_hash
        or row_task_id != task.get("id")
        or payload.get("execution_mode") != "batch_draft_save"
        or payload.get("path") != "A"
        or snapshot.get("path") != "A"
        or payload.get("publish_allowed") is not False
        or snapshot.get("publish_allowed") is not False
    ):
        _reject("AUTH_COMMAND_SNAPSHOT_MISMATCH")

    product_ids = snapshot.get("product_ids")
    items = snapshot.get("item_snapshots")
    jobs = task.get("jobs")
    if (
        not isinstance(product_ids, list)
        or not product_ids
        or not isinstance(items, list)
        or not isinstance(jobs, list)
        or [str(job.get("product_id")) for job in jobs] != [str(value) for value in product_ids]
        or [str(item.get("product_id")) for item in items if isinstance(item, Mapping)]
        != [str(value) for value in product_ids]
        or str(task.get("store_id")) != str(snapshot.get("shop_scope"))
    ):
        _reject("AUTH_COMMAND_SNAPSHOT_MISMATCH")
    matches = [
        (index, job)
        for index, job in enumerate(jobs)
        if job.get("id") == command.job_id
    ]
    if len(matches) != 1:
        _reject("AUTH_COMMAND_JOB_MISMATCH")
    index, job = matches[0]
    if index >= len(items) or not isinstance(items[index], Mapping):
        _reject("AUTH_COMMAND_JOB_MISMATCH")
    item = dict(items[index])
    if str(item.get("product_id")) != str(job.get("product_id")):
        _reject("AUTH_COMMAND_JOB_MISMATCH")
    return (
        snapshot,
        item,
        dict(job),
        {
            "id": int(stored_row["id"]),
            "task_id": stored_row.get("task_id"),
            "snapshot_hash": stored_row.get("snapshot_hash"),
            "local_plan_template_id": stored_row.get("local_plan_template_id"),
            "idempotency_key": stored_row.get("idempotency_key"),
            "created_at": stored_row.get("created_at"),
        },
    )


def _validate_queue(
    task: Mapping[str, Any], command: BrowserAgentCommand
) -> dict[str, Any]:
    try:
        return validate_current_batch_queue_guard(
            task,
            command.job_id,
            command.params.get("batch_queue_guard"),
        )
    except BatchCommandContractError:
        _reject("AUTH_COMMAND_QUEUE_STATE_MISMATCH")


def _validate_authorization(
    task: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    command: BrowserAgentCommand,
    live: LiveDispatchFacts,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    payload = task.get("payload") if isinstance(task.get("payload"), Mapping) else {}
    approval = (
        payload.get("manual_approval")
        if isinstance(payload.get("manual_approval"), Mapping)
        else {}
    )
    if approval.get("approved") is not True or approval.get("source") != "server":
        _reject("AUTH_LEASE_NOT_APPROVED")
    if approval.get("consumed") is not True or not approval.get("consumed_at"):
        _reject("AUTH_LEASE_NOT_CONSUMED")
    if str(approval.get("lease_id") or "") != str(command.authorization_lease_id or ""):
        _reject("AUTH_COMMAND_AUTHORIZATION_MISMATCH")
    stored_context = (
        dict(approval.get("authorization_context"))
        if isinstance(approval.get("authorization_context"), Mapping)
        else {}
    )
    if verify_authorization_context(stored_context).get("ok") is not True:
        _reject("AUTH_COMMAND_AUTHORIZATION_MISMATCH")
    stored_stage = (
        dict(approval.get("stage_task_facts"))
        if isinstance(approval.get("stage_task_facts"), Mapping)
        else {}
    )
    context_stage = stored_context.get("stage_task_facts")
    if not isinstance(context_stage, Mapping) or stored_stage != dict(context_stage):
        _reject("AUTH_STAGE_FACTS_MISMATCH")
    try:
        current_stage = build_batch_draft_save_task_facts(
            task_id=int(task["id"]),
            store_id=int(task["store_id"]),
            product_ids=payload.get("product_ids") or snapshot.get("product_ids") or [],
            plan_snapshot_id=int(payload.get("plan_snapshot_id") or 0),
            plan_snapshot_hash=str(payload.get("plan_snapshot_hash") or ""),
            path=str(payload.get("path") or ""),
        )
    except (KeyError, TypeError, ValueError, TwoStageContractError):
        _reject("AUTH_STAGE_FACTS_MISMATCH")
    if current_stage != stored_stage or not hmac.compare_digest(
        str(command.stage_task_facts_fingerprint or "").casefold(),
        str(current_stage.get("fingerprint") or "").casefold(),
    ):
        _reject("AUTH_STAGE_FACTS_MISMATCH")
    try:
        lease_authority = canonical_authorization_lease_authority(approval)
        lease_fingerprint = authorization_lease_authority_fingerprint(approval)
    except ValueError:
        _reject("AUTH_LEASE_AUTHORITY_MISMATCH")
    if not hmac.compare_digest(
        str(command.authorization_lease_fingerprint or "").casefold(),
        lease_fingerprint.casefold(),
    ):
        _reject("AUTH_LEASE_AUTHORITY_MISMATCH")

    if live.l2_status != "passed":
        _reject("AUTH_L2_GATE_NOT_PASSED")
    if stored_context.get("l2_evidence_fingerprint") != live.l2_evidence_fingerprint:
        _reject("AUTH_L2_EVIDENCE_MISMATCH")
    if stored_context.get("git_head") != live.git_head:
        _reject("AUTH_GIT_HEAD_MISMATCH")
    try:
        stored_worktree_hash = canonical_sha256(stored_context.get("worktree_identity"))
        live_worktree_hash = canonical_sha256(dict(live.worktree_identity))
    except (ScopeContractError, TypeError, ValueError):
        _reject("AUTH_WORKTREE_IDENTITY_MISMATCH")
    if not hmac.compare_digest(stored_worktree_hash, live_worktree_hash):
        _reject("AUTH_WORKTREE_IDENTITY_MISMATCH")
    if stored_context.get("runtime_instance_id") != live.runtime_instance_id:
        _reject("AUTH_RUNTIME_IDENTITY_MISMATCH")
    if stored_context.get("browser_session_id") != live.browser_session_id:
        _reject("AUTH_BROWSER_SESSION_MISMATCH")
    if command.runtime_id != live.browser_runtime_id:
        _reject("AUTH_RUNTIME_IDENTITY_MISMATCH")
    try:
        context_fingerprint = authorization_context_fingerprint(stored_context)
    except TwoStageContractError:
        _reject("AUTH_COMMAND_AUTHORIZATION_MISMATCH")
    if not hmac.compare_digest(
        str(command.authorization_fingerprint or "").casefold(),
        context_fingerprint.casefold(),
    ):
        _reject("AUTH_COMMAND_AUTHORIZATION_MISMATCH")
    return current_stage, stored_context, lease_authority


def _validate_target(
    item_snapshot: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    command: BrowserAgentCommand,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    session_context = (
        snapshot.get("session_context")
        if isinstance(snapshot.get("session_context"), Mapping)
        else {}
    )
    store_name = str(session_context.get("shop_name") or "").strip()
    try:
        frozen_target = canonical_frozen_target_identity(
            item_snapshot.get("target_identity"),
            store_name=store_name,
        )
        actual = canonical_mutation_target_payload(command.action, command.params)
        expected = canonical_mutation_target_payload(
            "save_only",
            {
                "store_name": store_name,
                "target_identity": frozen_target,
            },
        )
        current_hash = mutation_target_hash(command.action, command.params)
    except MutationCommandContractError:
        _reject("AUTH_COMMAND_TARGET_MISMATCH")
    if (
        frozen_target is None
        or actual != expected
        or command.params.get("target_identity") != frozen_target
        or command.params.get("target_source_urls") != frozen_target.get("source_urls")
        or command.params.get("product_query") != str(item_snapshot.get("product_id"))
        or command.params.get("store_name") != store_name
        or not hmac.compare_digest(
            str(command.target_hash or "").casefold(),
            current_hash.casefold(),
        )
    ):
        _reject("AUTH_COMMAND_TARGET_MISMATCH")
    return current_hash, frozen_target, expected


def _validate_execution(
    task: Mapping[str, Any],
    job: Mapping[str, Any],
    command: BrowserAgentCommand,
) -> dict[str, Any]:
    try:
        expected = compile_frozen_execution_payload(task, job)
        actual = validate_frozen_execution_defaults(
            command.params.get("defaults"),
            expected_payload=expected,
        )
    except FrozenExecutionContractError:
        _reject("AUTH_COMMAND_EXECUTION_MISMATCH")
    expected_hash = str(actual.get("payload_hash") or "")
    if not hmac.compare_digest(
        str(command.execution_payload_hash or "").casefold(),
        expected_hash.casefold(),
    ):
        _reject("AUTH_COMMAND_EXECUTION_MISMATCH")
    return expected


def _validate_live_identity(
    identity: Mapping[str, Any],
    command: BrowserAgentCommand,
    live: LiveDispatchFacts,
    target_hash: str,
    target_identity: Mapping[str, Any],
) -> None:
    if not isinstance(identity, Mapping):
        _reject("AUTH_BROWSER_IDENTITY_UNAVAILABLE")
    if identity.get("browser_session_id") != live.browser_session_id:
        _reject("AUTH_BROWSER_SESSION_MISMATCH")
    if identity.get("page_kind") != "editor" or controlled_dxm_page_identity(
        identity.get("page_url")
    ) != "editor":
        _reject("AUTH_BROWSER_PAGE_MISMATCH")
    stable_identity = target_identity.get("stable_identity")
    if isinstance(stable_identity, Mapping) and stable_identity.get("kind") == "product_id":
        try:
            page_product_ids = parse_qs(
                urlsplit(str(identity.get("page_url") or "")).query,
                keep_blank_values=True,
            ).get("id", [])
        except (TypeError, ValueError):
            _reject("AUTH_BROWSER_PAGE_MISMATCH")
        if page_product_ids and (
            len(page_product_ids) != 1
            or page_product_ids[0] != str(stable_identity.get("value") or "")
        ):
            _reject("AUTH_COMMAND_TARGET_MISMATCH")
    observed_target_hash = str(identity.get("target_hash") or "")
    if not (
        hmac.compare_digest(observed_target_hash.casefold(), target_hash.casefold())
        and hmac.compare_digest(
            observed_target_hash.casefold(),
            str(command.target_hash or "").casefold(),
        )
    ):
        _reject("AUTH_COMMAND_TARGET_MISMATCH")


def _validated_authority(value: Mapping[str, Any]) -> dict[str, Any]:
    expected_keys = {
        "schema",
        "task_authority",
        "authorization",
        "l2",
        "snapshot",
        "queue",
        "code_identity",
        "runtime",
        "browser_identity",
        "target",
        "execution",
        "command",
    }
    if not isinstance(value, Mapping) or set(value) != expected_keys:
        _reject("AUTH_FROZEN_AUTHORITY_INVALID")
    canonical = _canonical_thaw(value)
    if canonical.get("schema") != "dxm.batch_draft_save.dispatch_authority.v1":
        _reject("AUTH_FROZEN_AUTHORITY_INVALID")
    for key in (
        "task_authority",
        "authorization",
        "l2",
        "snapshot",
        "queue",
        "code_identity",
        "runtime",
        "browser_identity",
        "target",
        "execution",
        "command",
    ):
        if not isinstance(canonical.get(key), dict):
            _reject("AUTH_FROZEN_AUTHORITY_INVALID")
    authorization = canonical["authorization"]
    context = authorization.get("authorization_context")
    stage = authorization.get("stage_task_facts")
    lease_authority = authorization.get("lease_authority")
    if (
        not isinstance(context, dict)
        or not isinstance(stage, dict)
        or not isinstance(lease_authority, dict)
        or verify_authorization_context(context).get("ok") is not True
        or context.get("stage_task_facts") != stage
        or canonical["task_authority"].get("manual_approval", {}).get(
            "authorization_context"
        )
        != context
        or canonical["task_authority"].get("manual_approval", {}).get(
            "stage_task_facts"
        )
        != stage
        or authorization.get("lease_id") != lease_authority.get("lease_id")
        or authorization.get("lease_fingerprint")
        != authorization_lease_authority_fingerprint(lease_authority)
    ):
        _reject("AUTH_FROZEN_AUTHORITY_INVALID")
    snapshot = canonical["snapshot"]
    plan_snapshot = snapshot.get("plan_snapshot")
    row_binding = snapshot.get("row_binding")
    if not isinstance(plan_snapshot, dict) or not isinstance(row_binding, dict):
        _reject("AUTH_FROZEN_AUTHORITY_INVALID")
    body = {key: item for key, item in plan_snapshot.items() if key != "snapshot_hash"}
    if (
        canonical_sha256(body) != plan_snapshot.get("snapshot_hash")
        or snapshot.get("plan_snapshot_hash") != plan_snapshot.get("snapshot_hash")
        or snapshot.get("plan_snapshot_id")
        != canonical["task_authority"].get("plan_snapshot_id")
        or row_binding
        != {
            "id": snapshot.get("plan_snapshot_id"),
            "task_id": canonical["task_authority"].get("task_id"),
            "snapshot_hash": snapshot.get("plan_snapshot_hash"),
            "local_plan_template_id": plan_snapshot.get("local_plan_template", {}).get(
                "id"
            ),
            "idempotency_key": row_binding.get("idempotency_key"),
            "created_at": row_binding.get("created_at"),
        }
        or not isinstance(row_binding.get("idempotency_key"), str)
        or not row_binding.get("idempotency_key")
        or not isinstance(row_binding.get("created_at"), str)
        or not row_binding.get("created_at")
    ):
        _reject("AUTH_FROZEN_AUTHORITY_INVALID")
    command = canonical["command"]
    if (
        not isinstance(command.get("payload"), dict)
        or command.get("sha256")
        != canonical_contract_sha256(command.get("payload"))
    ):
        _reject("AUTH_FROZEN_AUTHORITY_INVALID")
    try:
        canonical_sha256(canonical)
    except (ScopeContractError, TypeError, ValueError):
        _reject("AUTH_FROZEN_AUTHORITY_INVALID")
    return canonical


def _canonical_thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _canonical_thaw(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical_thaw(item) for item in value]
    return deepcopy(value)


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _FrozenDict(
            {str(key): _deep_freeze(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(item) for item in value)
    return deepcopy(value)


def _sha256_text(value: Any, reason_code: str) -> str:
    if not isinstance(value, str):
        _reject(reason_code)
    normalized = value.upper()
    if len(normalized) != 64 or any(ch not in "0123456789ABCDEF" for ch in normalized):
        _reject(reason_code)
    return normalized


def _reject(reason_code: str) -> None:
    raise DispatchAuthorityError(reason_code)
