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
    PATH_B_SAVE1_DISCOVERY_ACTION,
    PATH_B_SAVE1_DISCOVERY_STATE,
    SAVE_VERIFICATION_CONTEXT_SCHEMA,
    BatchCommandContractError,
    canonical_contract_sha256,
    validate_current_batch_queue_guard,
    validate_path_b_save1_discovery_dispatch,
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
    StrictUtcTimestampError,
    authorization_lease_authority_fingerprint,
    authorization_lease_is_active,
    canonical_authorization_lease_authority,
    parse_strict_utc_timestamp,
    utc_now_iso,
)
from src.real_dxm_write_scope import (
    RealDxmWriteScopeError,
    validate_real_dxm_write_scope,
)
from src.state_machine.batch_draft_authorization import (
    BatchDraftAuthorizationError,
    authorization_context_fingerprint,
    build_batch_draft_save_task_facts,
    verify_authorization_context,
)


_BATCH_SAVE_BINDINGS = {
    "SAVE_ONLY": ("SAVE1", "editor"),
    "SAVE2_ONLY": ("SAVE2", "semi_managed"),
    PATH_B_SAVE1_DISCOVERY_STATE: ("SAVE1", "editor"),
}
_BATCH_SAVE_ACTIONS = {
    "SAVE_ONLY": "save_only",
    "SAVE2_ONLY": "save_only",
    PATH_B_SAVE1_DISCOVERY_STATE: PATH_B_SAVE1_DISCOVERY_ACTION,
}
_BATCH_SAVE_AND_VERIFY_STATES = frozenset(
    {
        "SAVE_ONLY",
        PATH_B_SAVE1_DISCOVERY_STATE,
        "VERIFY_NOT_PUBLISHED",
        "VERIFY_SAVE1_NOT_PUBLISHED",
        "VERIFY_DISCOVERY_SAVE1_NOT_PUBLISHED",
        "DISCOVERY_SEAL_STOP",
        "SAVE2_ONLY",
        "VERIFY_SAVE2_NOT_PUBLISHED",
    }
)
_PATH_B_SAVE_LEASE_KEYS = frozenset(
    {
        "product_id",
        "product_ordinal",
        "save_stage",
        "lease_id",
        "scope_sha256",
        "expires_at",
        "single_use",
    }
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
    account_ref_hash: str


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
        live_account_hash = _sha256_text(
            live_facts.account_ref_hash,
            "AUTH_ACCOUNT_CONTEXT_UNAVAILABLE",
        )
        if frozen_runtime.get("account_ref_hash") != live_account_hash:
            _reject("AUTH_ACCOUNT_CONTEXT_MISMATCH")
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
    expected_mutation_action = (
        "first_save_intent"
        if command_payload.get("state") == PATH_B_SAVE1_DISCOVERY_STATE
        else "save_only_click"
    )
    if (
        command_payload != frozen_command["payload"]
        or command_sha256 != frozen_command["sha256"]
        or not isinstance(ledger_entry, Mapping)
        or ledger_entry.get("status") != "DISPATCHED"
        or ledger_entry.get("mutation_action") != expected_mutation_action
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
    save_binding = _BATCH_SAVE_BINDINGS.get(command.state)
    if (
        command.execution_mode != "batch_draft_save"
        or save_binding is None
        or command.action != _BATCH_SAVE_ACTIONS.get(command.state)
        or command.expected_page != save_binding[1]
    ):
        _reject("AUTH_COMMAND_MODE_MISMATCH")

    task = _load_task(conn, command)
    try:
        discovery_profile = validate_path_b_save1_discovery_dispatch(
            task,
            job_id=command.job_id,
            command_state=command.state,
            command_action=command.action,
        )
    except BatchCommandContractError as exc:
        _reject(exc.reason_code)
    if (
        command.state == PATH_B_SAVE1_DISCOVERY_STATE
        and discovery_profile is None
    ):
        _reject("DISCOVERY_PROFILE_REQUIRED")
    snapshot, item_snapshot, job, snapshot_row = _load_snapshot_binding(
        conn, task, command
    )
    current_queue_guard = _validate_queue(task, command)
    (
        stage_facts,
        stored_context,
        lease_authority,
        parent_lease_authority,
        save_stage,
    ) = _validate_authorization(
        conn,
        task,
        snapshot,
        job,
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
    authorization_authority = {
        "lease_id": str(command.authorization_lease_id),
        "lease_fingerprint": str(command.authorization_lease_fingerprint),
        "lease_authority": lease_authority,
        "authorization_context": deepcopy(stored_context),
        "stage_task_facts": deepcopy(stage_facts),
    }
    if parent_lease_authority is not None:
        authorization_authority.update(
            {
                "parent_lease_authority": parent_lease_authority,
                "save_stage": save_stage,
            }
        )
    return {
        "schema": "dxm.batch_draft_save.dispatch_authority.v1",
        "task_authority": task_authority,
        "authorization": authorization_authority,
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
            "account_ref_hash": _sha256_text(
                live.account_ref_hash,
                "AUTH_ACCOUNT_CONTEXT_UNAVAILABLE",
            ),
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
    if step not in _BATCH_SAVE_AND_VERIFY_STATES:
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
    task_path = payload.get("path")
    if (
        not isinstance(snapshot_hash, str)
        or not hmac.compare_digest(snapshot_hash, reproduced_hash)
        or stored_row.get("snapshot_hash") != snapshot_hash
        or payload.get("plan_snapshot_hash") != snapshot_hash
        or embedded_hash != stored_hash
        or row_task_id != task.get("id")
        or payload.get("execution_mode") != "batch_draft_save"
        or task_path not in {"A", "B"}
        or snapshot.get("path") != task_path
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


def _canonical_path_b_save_lease(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _PATH_B_SAVE_LEASE_KEYS:
        _reject("AUTH_REAL_SAVE_LEASE_INVALID")
    lease = deepcopy(dict(value))
    for field_name in ("product_id", "product_ordinal"):
        field_value = lease.get(field_name)
        if isinstance(field_value, bool) or not isinstance(field_value, int) or field_value <= 0:
            _reject("AUTH_REAL_SAVE_LEASE_INVALID")
    if lease.get("save_stage") not in {"SAVE1", "SAVE2"}:
        _reject("AUTH_REAL_SAVE_LEASE_INVALID")
    if lease.get("single_use") is not True:
        _reject("AUTH_REAL_SAVE_LEASE_NOT_SINGLE_USE")
    for field_name in ("lease_id", "scope_sha256"):
        field_value = lease.get(field_name)
        if (
            not isinstance(field_value, str)
            or len(field_value) != 64
            or any(character not in "0123456789abcdefABCDEF" for character in field_value)
        ):
            _reject("AUTH_REAL_SAVE_LEASE_INVALID")
    try:
        parse_strict_utc_timestamp(lease.get("expires_at"), field="expires_at")
        canonical_sha256(lease)
    except (StrictUtcTimestampError, ScopeContractError, TypeError, ValueError):
        _reject("AUTH_REAL_SAVE_LEASE_INVALID")
    return lease


def _validated_path_b_save_lease(
    conn: Any,
    task: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    job: Mapping[str, Any],
    command: BrowserAgentCommand,
    live: LiveDispatchFacts,
    *,
    checked_at: str,
) -> dict[str, Any]:
    payload = task.get("payload") if isinstance(task.get("payload"), Mapping) else {}
    real_authorization = payload.get("real_dxm_write_authorization")
    if not isinstance(real_authorization, Mapping):
        _reject("AUTH_REAL_WRITE_AUTHORIZATION_MISSING")
    if (
        real_authorization.get("schema") != "real_dxm_write_authorization.v1"
        or real_authorization.get("publish_allowed") is not False
    ):
        _reject("AUTH_REAL_WRITE_AUTHORIZATION_INVALID")
    scope_sha256 = _sha256_text(
        real_authorization.get("scope_sha256"),
        "AUTH_REAL_WRITE_AUTHORIZATION_INVALID",
    )
    approval_sha256 = _sha256_text(
        real_authorization.get("approval_sha256"),
        "AUTH_REAL_WRITE_AUTHORIZATION_INVALID",
    )
    approval_nonce_sha256 = _sha256_text(
        real_authorization.get("approval_nonce_sha256"),
        "AUTH_REAL_WRITE_AUTHORIZATION_INVALID",
    )
    product_ids = snapshot.get("product_ids")
    ordered_product_ids = real_authorization.get("ordered_product_ids")
    if (
        not isinstance(product_ids, list)
        or not isinstance(ordered_product_ids, list)
        or any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in ordered_product_ids)
        or [str(value) for value in ordered_product_ids]
        != [str(value) for value in product_ids]
    ):
        _reject("AUTH_REAL_WRITE_PRODUCT_ORDER_MISMATCH")
    jobs = task.get("jobs")
    if not isinstance(jobs, list):
        _reject("AUTH_REAL_SAVE_LEASE_INVALID")
    job_indexes = [
        index
        for index, candidate in enumerate(jobs, start=1)
        if isinstance(candidate, Mapping) and candidate.get("id") == job.get("id")
    ]
    if len(job_indexes) != 1:
        _reject("AUTH_REAL_SAVE_LEASE_INVALID")
    try:
        product_id = int(job.get("product_id"))
    except (TypeError, ValueError):
        _reject("AUTH_REAL_SAVE_LEASE_INVALID")
    if str(product_id) != str(job.get("product_id")) or product_id <= 0:
        _reject("AUTH_REAL_SAVE_LEASE_INVALID")
    expected_pairs = [
        (product_ordinal, int(candidate_product_id), save_stage)
        for product_ordinal, candidate_product_id in enumerate(ordered_product_ids, start=1)
        for save_stage in ("SAVE1", "SAVE2")
    ]
    raw_leases = real_authorization.get("save_leases")
    if not isinstance(raw_leases, list) or len(raw_leases) != len(expected_pairs):
        _reject("AUTH_REAL_SAVE_LEASE_INVALID")
    leases = [_canonical_path_b_save_lease(value) for value in raw_leases]
    actual_pairs = [
        (lease["product_ordinal"], lease["product_id"], lease["save_stage"])
        for lease in leases
    ]
    lease_ids = [str(lease["lease_id"]).casefold() for lease in leases]
    if (
        actual_pairs != expected_pairs
        or len(set(lease_ids)) != len(lease_ids)
        or any(
            str(lease["scope_sha256"]).casefold() != scope_sha256.casefold()
            or lease["expires_at"] != real_authorization.get("approval_expires_at")
            for lease in leases
        )
    ):
        _reject("AUTH_REAL_SAVE_LEASE_INVALID")
    save_stage, _expected_page = _BATCH_SAVE_BINDINGS[command.state]
    matches = [
        lease
        for lease in leases
        if lease["product_id"] == product_id
        and lease["product_ordinal"] == job_indexes[0]
        and lease["save_stage"] == save_stage
    ]
    if len(matches) != 1:
        _reject("AUTH_REAL_SAVE_LEASE_MISMATCH")
    selected = matches[0]
    if str(command.authorization_lease_id or "") != str(selected["lease_id"]):
        _reject("AUTH_COMMAND_AUTHORIZATION_MISMATCH")
    selected_fingerprint = canonical_sha256(selected)
    if not hmac.compare_digest(
        str(command.authorization_lease_fingerprint or "").casefold(),
        selected_fingerprint.casefold(),
    ):
        _reject("AUTH_LEASE_AUTHORITY_MISMATCH")
    if not authorization_lease_is_active(
        checked_at=checked_at,
        expires_at=selected["expires_at"],
    ):
        _reject("AUTH_LEASE_EXPIRED")

    row = conn.execute(
        "SELECT * FROM real_dxm_write_scopes WHERE scope_sha256=?",
        (real_authorization.get("scope_sha256"),),
    ).fetchone()
    if row is None:
        _reject("AUTH_REAL_WRITE_SCOPE_NOT_CONSUMED")
    stored = dict(row)
    scope = loads(stored.get("scope_json"), {})
    try:
        canonical_scope = validate_real_dxm_write_scope(scope, now=checked_at)
    except (RealDxmWriteScopeError, TypeError, ValueError):
        _reject("AUTH_REAL_WRITE_SCOPE_INVALID")
    scope_snapshot = canonical_scope.get("snapshot")
    scope_products = canonical_scope.get("orderedProducts")
    scope_account = canonical_scope.get("account")
    scope_shop = canonical_scope.get("shop")
    scope_git = canonical_scope.get("git")
    scope_worktree = canonical_scope.get("worktree")
    scope_runtime = canonical_scope.get("runtime")
    scope_l2 = canonical_scope.get("l2")
    scope_product_ids = [
        item.get("productId")
        for item in scope_products
        if isinstance(item, Mapping)
    ] if isinstance(scope_products, list) else []
    try:
        scope_worktree_sha256 = canonical_sha256(scope_worktree)
        live_worktree_sha256 = canonical_sha256(dict(live.worktree_identity))
        product_order_sha256 = canonical_sha256(ordered_product_ids)
    except (ScopeContractError, TypeError, ValueError):
        _reject("AUTH_REAL_WRITE_SCOPE_BINDING_MISMATCH")
    if (
        stored.get("status") != "consumed"
        or int(stored.get("task_id") or 0) != int(task["id"])
        or str(stored.get("scope_sha256") or "").casefold() != scope_sha256.casefold()
        or str(stored.get("approval_sha256") or "").casefold() != approval_sha256.casefold()
        or str(stored.get("approval_nonce_sha256") or "").casefold()
        != approval_nonce_sha256.casefold()
        or str(stored.get("scope_nonce_sha256") or "").casefold()
        != approval_nonce_sha256.casefold()
        or stored.get("expires_at") != selected["expires_at"]
        or int(stored.get("snapshot_id") or 0) != int(payload.get("plan_snapshot_id") or 0)
        or str(stored.get("snapshot_sha256") or "").casefold()
        != str(payload.get("plan_snapshot_hash") or "").casefold()
        or str(stored.get("account_ref_hash") or "").casefold()
        != str(live.account_ref_hash or "").casefold()
        or str(stored.get("shop_id") or "") != str(task["store_id"])
        or str(stored.get("product_order_sha256") or "").casefold()
        != product_order_sha256.casefold()
        or stored.get("approval_stage") != canonical_scope.get("stage")
        or canonical_scope.get("expiresAt") != selected["expires_at"]
        or not isinstance(scope_snapshot, Mapping)
        or int(scope_snapshot.get("taskId") or 0) != int(task["id"])
        or int(scope_snapshot.get("snapshotId") or 0) != int(payload.get("plan_snapshot_id") or 0)
        or str(scope_snapshot.get("snapshotSha256") or "").casefold()
        != str(payload.get("plan_snapshot_hash") or "").casefold()
        or [str(value) for value in scope_product_ids]
        != [str(value) for value in ordered_product_ids]
        or not isinstance(scope_account, Mapping)
        or str(scope_account.get("accountContextHash") or "").casefold()
        != str(live.account_ref_hash or "").casefold()
        or not isinstance(scope_shop, Mapping)
        or int(scope_shop.get("shopId") or 0) != int(task["store_id"])
        or not isinstance(scope_git, Mapping)
        or scope_git.get("head") != live.git_head
        or not isinstance(scope_worktree, Mapping)
        or scope_worktree_sha256 != live_worktree_sha256
        or not isinstance(scope_runtime, Mapping)
        or scope_runtime.get("runtimeInstanceId") != live.runtime_instance_id
        or scope_runtime.get("browserRuntimeId") != live.browser_runtime_id
        or scope_runtime.get("browserSessionId") != live.browser_session_id
        or not isinstance(scope_l2, Mapping)
        or scope_l2.get("status") != "passed"
        or scope_l2.get("status") != live.l2_status
        or scope_l2.get("evidenceFingerprint") != live.l2_evidence_fingerprint
    ):
        _reject("AUTH_REAL_WRITE_SCOPE_BINDING_MISMATCH")
    return selected


def _validate_authorization(
    conn: Any,
    task: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    job: Mapping[str, Any],
    command: BrowserAgentCommand,
    live: LiveDispatchFacts,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any] | None,
    str | None,
]:
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
    checked_at = utc_now_iso()
    if not authorization_lease_is_active(
        checked_at=checked_at,
        expires_at=approval.get("expires_at"),
    ):
        _reject("AUTH_LEASE_EXPIRED")
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
            real_authorization=(
                payload.get("real_dxm_write_authorization")
                if str(payload.get("path") or "") == "B"
                else None
            ),
        )
    except (KeyError, TypeError, ValueError, BatchDraftAuthorizationError):
        _reject("AUTH_STAGE_FACTS_MISMATCH")
    if current_stage != stored_stage or not hmac.compare_digest(
        str(command.stage_task_facts_fingerprint or "").casefold(),
        str(current_stage.get("fingerprint") or "").casefold(),
    ):
        _reject("AUTH_STAGE_FACTS_MISMATCH")
    try:
        parent_lease_authority = canonical_authorization_lease_authority(approval)
        parent_lease_fingerprint = authorization_lease_authority_fingerprint(approval)
    except ValueError:
        _reject("AUTH_LEASE_AUTHORITY_MISMATCH")
    path = str(payload.get("path") or "")
    if path == "A":
        if str(approval.get("lease_id") or "") != str(command.authorization_lease_id or ""):
            _reject("AUTH_COMMAND_AUTHORIZATION_MISMATCH")
        if not hmac.compare_digest(
            str(command.authorization_lease_fingerprint or "").casefold(),
            parent_lease_fingerprint.casefold(),
        ):
            _reject("AUTH_LEASE_AUTHORITY_MISMATCH")
        lease_authority = parent_lease_authority
        frozen_parent_lease_authority = None
        save_stage = None
    elif path == "B":
        lease_authority = _validated_path_b_save_lease(
            conn,
            task,
            snapshot,
            job,
            command,
            live,
            checked_at=checked_at,
        )
        frozen_parent_lease_authority = parent_lease_authority
        save_stage = _BATCH_SAVE_BINDINGS[command.state][0]
    else:
        _reject("AUTH_COMMAND_MODE_MISMATCH")

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
    session_context = (
        snapshot.get("session_context")
        if isinstance(snapshot.get("session_context"), Mapping)
        else {}
    )
    frozen_account_hash = _sha256_text(
        session_context.get("account_ref_hash"),
        "AUTH_SNAPSHOT_ACCOUNT_CONTEXT_INVALID",
    )
    live_account_hash = _sha256_text(
        live.account_ref_hash,
        "AUTH_ACCOUNT_CONTEXT_UNAVAILABLE",
    )
    if not hmac.compare_digest(frozen_account_hash, live_account_hash):
        _reject("AUTH_ACCOUNT_CONTEXT_MISMATCH")
    try:
        context_fingerprint = authorization_context_fingerprint(stored_context)
    except BatchDraftAuthorizationError:
        _reject("AUTH_COMMAND_AUTHORIZATION_MISMATCH")
    if not hmac.compare_digest(
        str(command.authorization_fingerprint or "").casefold(),
        context_fingerprint.casefold(),
    ):
        _reject("AUTH_COMMAND_AUTHORIZATION_MISMATCH")
    return (
        current_stage,
        stored_context,
        lease_authority,
        frozen_parent_lease_authority,
        save_stage,
    )


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
            command.action,
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
    expected_page = _BATCH_SAVE_BINDINGS.get(command.state, (None, None))[1]
    if (
        expected_page is None
        or identity.get("page_kind") != expected_page
        or controlled_dxm_page_identity(identity.get("page_url")) != expected_page
    ):
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
    task_authority = canonical["task_authority"]
    task_path = task_authority.get("path")
    if (
        not isinstance(context, dict)
        or not isinstance(stage, dict)
        or not isinstance(lease_authority, dict)
        or verify_authorization_context(context).get("ok") is not True
        or context.get("stage_task_facts") != stage
        or task_authority.get("manual_approval", {}).get(
            "authorization_context"
        )
        != context
        or task_authority.get("manual_approval", {}).get(
            "stage_task_facts"
        )
        != stage
    ):
        _reject("AUTH_FROZEN_AUTHORITY_INVALID")
    if task_path == "A":
        try:
            lease_fingerprint = authorization_lease_authority_fingerprint(
                lease_authority
            )
        except ValueError:
            _reject("AUTH_FROZEN_AUTHORITY_INVALID")
        if (
            authorization.get("lease_id") != lease_authority.get("lease_id")
            or str(authorization.get("lease_fingerprint") or "").casefold()
            != lease_fingerprint.casefold()
            or "parent_lease_authority" in authorization
            or "save_stage" in authorization
        ):
            _reject("AUTH_FROZEN_AUTHORITY_INVALID")
    elif task_path == "B":
        parent_lease_authority = authorization.get("parent_lease_authority")
        save_stage = authorization.get("save_stage")
        command_payload = canonical["command"].get("payload")
        task_payload = task_authority.get("task_payload")
        real_authorization = (
            task_payload.get("real_dxm_write_authorization")
            if isinstance(task_payload, dict)
            else None
        )
        real_save_leases = (
            real_authorization.get("save_leases")
            if isinstance(real_authorization, dict)
            else None
        )
        try:
            canonical_child_lease = _canonical_path_b_save_lease(lease_authority)
            canonical_parent_lease = canonical_authorization_lease_authority(
                parent_lease_authority
            )
            persisted_parent_lease = canonical_authorization_lease_authority(
                task_authority.get("manual_approval")
            )
        except (DispatchAuthorityError, TypeError, ValueError):
            _reject("AUTH_FROZEN_AUTHORITY_INVALID")
        if (
            not isinstance(command_payload, dict)
            or command_payload.get("state") not in _BATCH_SAVE_BINDINGS
            or command_payload.get("action")
            != _BATCH_SAVE_ACTIONS.get(command_payload.get("state"))
            or save_stage != _BATCH_SAVE_BINDINGS[command_payload["state"]][0]
            or canonical_child_lease.get("save_stage") != save_stage
            or authorization.get("lease_id") != canonical_child_lease.get("lease_id")
            or str(authorization.get("lease_fingerprint") or "").casefold()
            != canonical_sha256(canonical_child_lease).casefold()
            or canonical_parent_lease != persisted_parent_lease
            or not isinstance(real_authorization, dict)
            or not isinstance(real_save_leases, list)
            or canonical_child_lease not in real_save_leases
        ):
            _reject("AUTH_FROZEN_AUTHORITY_INVALID")
    else:
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
    runtime = canonical["runtime"]
    session_context = plan_snapshot.get("session_context")
    if not isinstance(session_context, dict):
        _reject("AUTH_FROZEN_AUTHORITY_INVALID")
    try:
        frozen_account_hash = _sha256_text(
            session_context.get("account_ref_hash"),
            "AUTH_FROZEN_AUTHORITY_INVALID",
        )
        runtime_account_hash = _sha256_text(
            runtime.get("account_ref_hash"),
            "AUTH_FROZEN_AUTHORITY_INVALID",
        )
    except DispatchAuthorityError:
        _reject("AUTH_FROZEN_AUTHORITY_INVALID")
    if not hmac.compare_digest(frozen_account_hash, runtime_account_hash):
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
