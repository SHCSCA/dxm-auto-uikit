from __future__ import annotations

import sqlite3
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json

import pytest

from src import db
from src.execution.browser_agent_protocol import (
    BrowserAgentCommand,
    MutationCommandContractError,
    build_frozen_product_target_identity,
    build_mutation_id,
    build_mutation_scope_id,
    mutation_target_hash,
    validate_browser_agent_command,
)
from src.execution.batch_command_contract import (
    BatchCommandContractError,
    build_batch_queue_guard,
    build_save_verification_context,
    validate_save_verification_context,
)
from src.execution.batch_dispatch_authority import LiveDispatchFacts
from src.execution.browser_agent_worker import BrowserAgentRuntime
from src.execution.mutation_dispatch_ledger import MutationDispatchLedger
from src.execution.e3_authority_contract import (
    authorization_lease_authority_fingerprint,
)
from src.execution.v1_runner import V1ExecutionError, V1TaskRunner
from src.state_machine.contracts import StateName
from src.state_machine.two_stage import (
    build_authorization_context,
    build_batch_draft_save_task_facts,
    build_stage_a_task_facts,
    canonical_claim_target_identity,
)
from tests.test_batch_dispatch_authority import authority_case


HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
GIT_HEAD = "1" * 40
WORKTREE_IDENTITY = {
    "schema": "dxm.git_worktree_identity.v1",
    "git_head": GIT_HEAD,
    "git_dirty": True,
    "status_count": 3,
    "status_sha256": "d" * 64,
    "execution_file_count": 2,
    "execution_tree_sha256": "e" * 64,
}


@pytest.fixture()
def ledger_db(tmp_path, monkeypatch):
    db_path = tmp_path / "mutation-ledger.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.init_db()
    return db_path


def _claim_command(**overrides) -> BrowserAgentCommand:
    values = {
        "command_id": "command-1",
        "idempotency_key": "idempotency-1",
        "deadline": "2099-01-01T00:00:00+00:00",
        "expected_page": "data_acquisition",
        "runtime_id": "ephemeral-runtime-1",
        "task_id": 11,
        "job_id": 22,
        "state": "CLAIM_TO_DRAFT_BOX",
        "action": "claim_from_data_acquisition",
        "execution_mode": "claim_only",
        "params": {
            "claim_mark": "AI-OPS",
            "product_query": "product-1001",
            "category_name": "测试类目",
            "store_name": "Dang Kang",
            "target_source_urls": [
                "https://detail.1688.com/offer/1001.html"
            ],
        },
        "authorization_lease_id": "lease-claim-1",
        "stage_task_facts_fingerprint": HASH_A,
        "target_hash": HASH_B,
        "authorization_fingerprint": HASH_C,
    }
    values.update(overrides)
    values.setdefault(
        "mutation_scope_id",
        build_mutation_scope_id(
            authorization_lease_id=values["authorization_lease_id"],
            task_id=values["task_id"],
            job_id=values["job_id"],
            state=values["state"],
            action=values["action"],
        ),
    )
    return BrowserAgentCommand(**values)


def _canonical_sha256(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest().upper()


def _canonical_path_a_save_result(
    save_command: BrowserAgentCommand,
    browser_session_id: str = "batch-browser-session-1",
) -> dict:
    from tests.test_action_result_contract import _as_path_a_editor, _valid_save_result

    result = _as_path_a_editor(
        _valid_save_result(),
        save_command.params["defaults"]["_frozen_execution_payload"],
    )
    result["page_identity"]["runtime_id"] = save_command.runtime_id
    result["page_identity"]["browser_session_id"] = browser_session_id
    if isinstance(save_command.params.get("target_identity"), dict):
        target = deepcopy(save_command.params["target_identity"])
        store_name = save_command.params["store_name"]
        target_sha256 = _canonical_sha256(target).lower()
        result["before_values"]["target_identity"] = deepcopy(target)
        result["before_values"]["store_name"] = store_name
        for pre_dispatch in (
            result["after_values"]["pre_dispatch_readback"],
            result["evidence"]["observations"]["pre_dispatch_readback"],
            result["evidence"]["observations"]["save_result"][
                "pre_dispatch_readback"
            ],
        ):
            pre_dispatch["identity"]["target_identity"] = deepcopy(target)
            pre_dispatch["identity"]["target_identity_sha256"] = target_sha256
            pre_dispatch["identity"]["expected_store_name"] = store_name
    return result


def _record_batch_save_success(
    ledger: MutationDispatchLedger,
    save_command: BrowserAgentCommand,
) -> dict:
    entry = ledger.get_entry(save_command.mutation_scope_id, "save_only_click")
    result = _canonical_path_a_save_result(
        save_command,
        str(entry.get("browser_session_id") or "batch-browser-session-1"),
    )
    assert ledger.record_success(save_command, result).ok is True
    return result


def _trusted_authority_ledger(case) -> MutationDispatchLedger:
    live_facts = LiveDispatchFacts(**case["live_facts"])
    return MutationDispatchLedger(
        recover_inflight=False,
        live_facts_provider=lambda: live_facts,
    )


def _authority_verify_command(
    save_command: BrowserAgentCommand,
    save_action_result: dict,
) -> BrowserAgentCommand:
    with db.connection() as conn:
        task = dict(
            conn.execute(
                "SELECT * FROM tasks WHERE id=?",
                (save_command.task_id,),
            ).fetchone()
        )
        task["payload"] = db.loads(task.pop("payload_json"), {})
        job = dict(
            conn.execute(
                "SELECT * FROM jobs WHERE id=?",
                (save_command.job_id,),
            ).fetchone()
        )
    context = build_save_verification_context(
        task,
        job,
        save_command=save_command.to_payload(),
        save_action_result=save_action_result,
    )
    return replace(
        _batch_verify_command(save_command, save_action_result=save_action_result),
        params={"save_verification_context": context},
    )


def _batch_save_command(
    *,
    queue_guard: dict | None = None,
) -> BrowserAgentCommand:
    body = {
        "schema": "dxm.batch_draft_save.execution_payload.v1",
        "product_id": "70001",
        "category_id": "2621",
        "category_schema_hash": HASH_A,
        "field_mapping_hash": HASH_B,
        "resolution_hash": HASH_C,
        "fields": [
            {
                "field_key": "weight",
                "ui_binding": "dxm_editor:weight",
                "resolved_value": "10",
            }
        ],
        "unresolved_fields": [],
        "price_validation": {},
    }
    payload = {**body, "payload_hash": _canonical_sha256(body)}
    values = {
        "command_id": "batch-save-command-1",
        "idempotency_key": "batch-save-idempotency-1",
        "deadline": "2099-01-01T00:00:00+00:00",
        "expected_page": "editor",
        "runtime_id": "batch-runtime-1",
        "task_id": 31,
        "job_id": 41,
        "state": "SAVE_ONLY",
        "action": "save_only",
        "execution_mode": "batch_draft_save",
        "execution_payload_hash": payload["payload_hash"],
        "params": {
            "defaults": {
                "weight": "10",
                "_frozen_execution_payload": payload,
                "_frozen_execution_payload_hash": payload["payload_hash"],
            }
        },
        "authorization_lease_id": "batch-ledger-lease-1",
        "authorization_lease_fingerprint": HASH_A,
        "stage_task_facts_fingerprint": HASH_A,
        "target_hash": HASH_B,
        "authorization_fingerprint": HASH_C,
    }
    with db.connection() as conn:
        task_row = conn.execute(
            "SELECT payload_json FROM tasks WHERE id=31"
        ).fetchone()
    if task_row is not None:
        task_payload = db.loads(task_row["payload_json"], {})
        approval = task_payload.get("manual_approval")
        if isinstance(approval, dict):
            try:
                values["authorization_lease_fingerprint"] = (
                    authorization_lease_authority_fingerprint(approval)
                )
            except ValueError:
                pass
            stage_facts = approval.get("stage_task_facts")
            context = approval.get("authorization_context")
            if isinstance(stage_facts, dict) and isinstance(
                stage_facts.get("fingerprint"), str
            ):
                values["stage_task_facts_fingerprint"] = stage_facts["fingerprint"]
            if isinstance(context, dict) and isinstance(
                context.get("fingerprint"), str
            ):
                values["authorization_fingerprint"] = context["fingerprint"]
    if queue_guard is not None:
        values["params"]["batch_queue_guard"] = dict(queue_guard)
    values["mutation_scope_id"] = build_mutation_scope_id(
        authorization_lease_id=values["authorization_lease_id"],
        task_id=values["task_id"],
        job_id=values["job_id"],
        state=values["state"],
        action=values["action"],
    )
    return BrowserAgentCommand(**values)


def _persist_running_batch_queue() -> dict:
    approval_now = datetime.now(timezone.utc)
    created_at = approval_now.isoformat()
    issued_at = (approval_now - timedelta(minutes=1)).isoformat()
    snapshot_body = {
        "schema": "dxm_batch_draft_save_plan.v1",
        "mode": "batch_draft_save",
        "path": "A",
        "shop_scope": "1",
        "session_context": {
            "session_ref": "batch-ledger-reader-session",
            "account_ref_hash": HASH_B.upper(),
            "shop_id": "1",
            "shop_name": "Batch Ledger Shop",
        },
        "local_plan_template": {"id": 1, "version": "1.0.0"},
        "product_ids": ["70001"],
        "item_snapshots": [],
        "publish_allowed": False,
    }
    snapshot = {
        **snapshot_body,
        "snapshot_hash": _canonical_sha256(snapshot_body),
    }
    stage_task_facts = build_batch_draft_save_task_facts(
        task_id=31,
        store_id=1,
        product_ids=[70001],
        plan_snapshot_id=51,
        plan_snapshot_hash=snapshot["snapshot_hash"],
        path="A",
    )
    authorization_context = build_authorization_context(
        stage_task_facts=stage_task_facts,
        runtime_instance_id="batch-backend-instance",
        browser_session_id="batch-browser-session-lease-cas",
        git_head=GIT_HEAD,
        worktree_identity={
            **WORKTREE_IDENTITY,
            "schema": "dxm.git-worktree.identity.v1",
            "status_sha256": WORKTREE_IDENTITY["status_sha256"].upper(),
            "execution_tree_sha256": WORKTREE_IDENTITY[
                "execution_tree_sha256"
            ].upper(),
        },
        l2_evidence_fingerprint=HASH_B.upper(),
        approved_by="ops-owner",
    )
    task_payload = {
        "plan_snapshot_id": 51,
        "plan_snapshot_hash": snapshot["snapshot_hash"],
        "plan_snapshot": snapshot,
        "path": "A",
        "publish_allowed": False,
        "runner_released": True,
        "product_ids": [70001],
        "execution_mode": "batch_draft_save",
        "manual_approval": {
            "approved": True,
            "source": "server",
            "lease_id": "batch-ledger-lease-1",
            "issued_at": issued_at,
            "approved_at": issued_at,
            "expires_at": (approval_now + timedelta(minutes=4)).isoformat(),
            "consumed": True,
            "consumed_at": approval_now.isoformat(),
            "approved_by": "ops-owner",
            "confirmation": "CONFIRM_DXM_SAVE_ONLY",
            "token_hash": HASH_C,
            "authorization_context": authorization_context,
            "stage_task_facts": stage_task_facts,
        },
    }
    with db.connection() as conn:
        conn.execute(
            """
            INSERT INTO plan_snapshots (
                id, local_plan_template_id, snapshot_hash, snapshot_json,
                idempotency_key, task_id, created_at
            ) VALUES (51, 1, ?, ?, 'batch-ledger-snapshot-1', 31, ?)
            """,
            (snapshot["snapshot_hash"], db.dumps(snapshot), created_at),
        )
        conn.execute(
            """
            INSERT INTO plan_snapshot_idempotency_keys (
                idempotency_key, snapshot_id, snapshot_hash, created_at
            ) VALUES ('batch-ledger-snapshot-1', 51, ?, ?)
            """,
            (snapshot["snapshot_hash"], created_at),
        )
        conn.execute(
            """
            INSERT INTO tasks (
                id, name, store_id, status, mode, publish_scene,
                total_jobs, completed_jobs, failed_jobs, payload_json,
                created_at, updated_at
            ) VALUES (31, 'batch queue', 1, 'running', 'batch_draft_save',
                      'draft_only', 1, 0, 0, ?, ?, ?)
            """,
            (db.dumps(task_payload), created_at, created_at),
        )
        conn.execute(
            """
            INSERT INTO jobs (
                id, task_id, product_id, status, current_step_code,
                current_step_name, created_at, updated_at
            ) VALUES (41, 31, 70001, 'running', 'SAVE_ONLY',
                      '只保存不发布', ?, ?)
            """,
            (created_at, created_at),
        )
    task = {
        "id": 31,
        "status": "running",
        "completed_jobs": 0,
        "failed_jobs": 0,
        "payload": task_payload,
        "created_at": created_at,
        "updated_at": created_at,
        "jobs": [{
            "id": 41,
            "product_id": 70001,
            "status": "running",
            "current_step_code": "SAVE_ONLY",
            "updated_at": created_at,
        }],
    }
    return build_batch_queue_guard(task, 41)


def _batch_verify_command(
    save_command: BrowserAgentCommand,
    *,
    save_action_result: dict | None = None,
) -> BrowserAgentCommand:
    queue_guard = save_command.params["batch_queue_guard"]
    body = {
        "schema": "dxm.batch_draft_save.save_verification.v1",
        "task_id": save_command.task_id,
        "job_id": save_command.job_id,
        "execution_mode": "batch_draft_save",
        "plan_snapshot_id": 51,
        "plan_snapshot_hash": HASH_A.upper(),
        "queue_epoch": queue_guard["queue_epoch"],
        "queue_version": queue_guard["queue_version"],
        "runtime_id": save_command.runtime_id,
        "browser_session_id": "batch-browser-session-1",
        "git_head": GIT_HEAD,
        "worktree_identity_sha256": _canonical_sha256(WORKTREE_IDENTITY),
        "authorization_fingerprint": str(save_command.authorization_fingerprint).upper(),
        "authorization_lease_id": save_command.authorization_lease_id,
        "stage_task_facts_fingerprint": str(save_command.stage_task_facts_fingerprint).upper(),
        "target_hash": str(save_command.target_hash).upper(),
        "execution_payload_hash": str(save_command.execution_payload_hash).upper(),
        "mutation_scope_id": str(save_command.mutation_scope_id).upper(),
        "save_command_id": save_command.command_id,
        "save_command_sha256": _canonical_sha256(save_command.to_payload()),
        "save_action_result_sha256": _canonical_sha256(
            save_action_result or _canonical_path_a_save_result(save_command)
        ),
    }
    context = {**body, "context_sha256": _canonical_sha256(body)}
    return BrowserAgentCommand(
        command_id="batch-verify-command-1",
        idempotency_key="batch-verify-idempotency-1",
        deadline="2099-01-01T00:00:00+00:00",
        expected_page="editor",
        runtime_id=save_command.runtime_id,
        task_id=save_command.task_id,
        job_id=save_command.job_id,
        state="VERIFY_NOT_PUBLISHED",
        action="verify_not_published",
        execution_mode="batch_draft_save",
        params={"save_verification_context": context},
    )


def test_init_db_creates_durable_mutation_dispatch_ledger(ledger_db):
    with sqlite3.connect(ledger_db) as conn:
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(mutation_dispatch_ledger)").fetchall()
        }

    assert {
        "mutation_id",
        "mutation_scope_id",
        "mutation_action",
        "ordinal",
        "command_state",
        "target_hash",
        "authorization_fingerprint",
        "stage_task_facts_fingerprint",
        "authorization_lease_id",
        "browser_session_id",
        "page_url",
        "page_kind",
        "status",
        "command_sha256",
        "command_json",
        "save_action_result_sha256",
        "save_action_result_json",
        "save_authority_sha256",
        "save_authority_json",
        "save_success_recorded_at",
    }.issubset(columns)


def test_mutation_id_is_stable_across_runtime_restart_and_unique_per_ordinal():
    before = _claim_command(runtime_id="runtime-before")
    after = _claim_command(runtime_id="runtime-after")

    before_first = build_mutation_id(
        mutation_scope_id=before.mutation_scope_id,
        state=before.state,
        ordinal=1,
        mutation_action="claim_open_dialog_click",
    )
    after_first = build_mutation_id(
        mutation_scope_id=after.mutation_scope_id,
        state=after.state,
        ordinal=1,
        mutation_action="claim_open_dialog_click",
    )
    second = build_mutation_id(
        mutation_scope_id=before.mutation_scope_id,
        state=before.state,
        ordinal=2,
        mutation_action="claim_confirm_click",
    )

    assert before_first == after_first
    assert before_first != second


def test_mutation_command_scope_is_independent_of_ephemeral_runtime_id():
    first = _claim_command(runtime_id="runtime-before-restart")
    second = _claim_command(runtime_id="runtime-after-restart")

    assert first.mutation_scope_id == second.mutation_scope_id
    assert validate_browser_agent_command(first) == {
        "claim_open_dialog_click": 1,
        "claim_confirm_click": 2,
    }


def test_mutation_command_missing_scope_fails_closed():
    with pytest.raises(MutationCommandContractError) as exc_info:
        validate_browser_agent_command(_claim_command(mutation_scope_id=None))

    assert exc_info.value.reason_code == "MUTATION_SCOPE_REQUIRED"


def test_non_mutation_command_must_not_smuggle_mutation_scope():
    command = _claim_command(
        state="OPEN_DRAFT_LIST",
        action="open_draft_box",
    )

    with pytest.raises(MutationCommandContractError) as exc_info:
        validate_browser_agent_command(command)

    assert exc_info.value.reason_code == "NON_MUTATION_SCOPE_FORBIDDEN"


def test_ordinal_two_cannot_dispatch_before_ordinal_one(ledger_db):
    ledger = MutationDispatchLedger(recover_inflight=False)
    command = _claim_command()
    assert ledger.reserve_command(command).ok is True

    blocked = ledger.begin_dispatch(command, "claim_confirm_click")
    first = ledger.begin_dispatch(command, "claim_open_dialog_click")
    first_done = ledger.mark_dispatched(command, "claim_open_dialog_click", {"clicked": True})
    second = ledger.begin_dispatch(command, "claim_confirm_click")

    assert blocked.reason_code == "MUTATION_ORDINAL_BLOCKED"
    assert first.ok is True
    assert first_done.ok is True
    assert second.ok is True


def test_only_one_concurrent_caller_can_begin_the_same_mutation(ledger_db):
    ledger = MutationDispatchLedger(recover_inflight=False)
    command = _claim_command()
    assert ledger.reserve_command(command).ok is True

    with ThreadPoolExecutor(max_workers=2) as executor:
        decisions = list(
            executor.map(
                lambda _ignored: ledger.begin_dispatch(command, "claim_open_dialog_click"),
                range(2),
            )
        )

    assert sum(decision.ok is True for decision in decisions) == 1
    assert {decision.reason_code for decision in decisions} == {
        "OK",
        "MUTATION_ALREADY_DISPATCHING",
    }


def test_constructor_recovers_dispatching_to_unknown_and_never_redispatches(ledger_db):
    command = _claim_command()
    first_process = MutationDispatchLedger(recover_inflight=False)
    assert first_process.reserve_command(command).ok is True
    assert first_process.begin_dispatch(command, "claim_open_dialog_click").ok is True

    restarted_process = MutationDispatchLedger()
    retry = restarted_process.begin_dispatch(command, "claim_open_dialog_click")

    assert retry.ok is False
    assert retry.reason_code == "MUTATION_OUTCOME_UNKNOWN"
    assert restarted_process.get_entry(
        command.mutation_scope_id,
        "claim_open_dialog_click",
    )["status"] == "UNKNOWN"


def test_dispatched_mutation_is_terminal_and_cannot_auto_dispatch_again(ledger_db):
    ledger = MutationDispatchLedger(recover_inflight=False)
    command = _claim_command()
    assert ledger.reserve_command(command).ok is True
    assert ledger.begin_dispatch(command, "claim_open_dialog_click").ok is True
    assert ledger.mark_dispatched(command, "claim_open_dialog_click").ok is True

    retry = ledger.begin_dispatch(command, "claim_open_dialog_click")

    assert retry.ok is False
    assert retry.reason_code == "MUTATION_ALREADY_DISPATCHED"


def test_batch_save_protocol_requires_the_frozen_queue_guard():
    with pytest.raises(MutationCommandContractError) as exc_info:
        validate_browser_agent_command(_batch_save_command())

    assert exc_info.value.reason_code == "BATCH_QUEUE_GUARD_INVALID"


def test_batch_ledger_cas_rejects_queue_drift_after_jit_authorization(ledger_db):
    queue_guard = _persist_running_batch_queue()
    ledger = MutationDispatchLedger(recover_inflight=False)
    command = _batch_save_command(queue_guard=queue_guard)
    assert ledger.reserve_command(command).ok is True

    with db.connection() as conn:
        conn.execute(
            """
            UPDATE jobs
               SET status='pending', updated_at='2099-01-01T00:00:01Z'
             WHERE id=41 AND task_id=31
            """
        )

    decision = ledger.begin_dispatch(command, "save_only_click")

    assert decision.ok is False
    assert decision.reason_code == "AUTH_COMMAND_QUEUE_STATE_MISMATCH"
    assert ledger.get_entry(
        command.mutation_scope_id,
        "save_only_click",
    )["status"] == "RESERVED"


def test_batch_ledger_cas_rejects_lease_expiry_after_jit_before_dispatch(ledger_db):
    queue_guard = _persist_running_batch_queue()
    ledger = MutationDispatchLedger(recover_inflight=False)
    command = _batch_save_command(queue_guard=queue_guard)
    assert ledger.reserve_command(command).ok is True

    with db.connection() as conn:
        row = conn.execute("SELECT payload_json FROM tasks WHERE id=31").fetchone()
        payload = db.loads(row["payload_json"], {})
        payload["manual_approval"]["expires_at"] = "2000-01-01T00:00:00+00:00"
        conn.execute(
            "UPDATE tasks SET payload_json=? WHERE id=31",
            (db.dumps(payload),),
        )

    click_count = 0
    decision = ledger.begin_dispatch(command, "save_only_click")
    if decision.ok:
        click_count += 1

    assert decision.ok is False
    assert decision.reason_code == "AUTH_LEASE_EXPIRED"
    assert click_count == 0
    entry = ledger.get_entry(command.mutation_scope_id, "save_only_click")
    assert entry["status"] == "RESERVED"
    assert entry["dispatch_started_at"] is None


@pytest.mark.parametrize(
    ("approval_drift", "reason_code"),
    [
        ({"approved": False}, "AUTH_LEASE_NOT_APPROVED"),
        ({"consumed": False}, "AUTH_LEASE_NOT_CONSUMED"),
        (
            {"lease_id": "batch-ledger-lease-replaced"},
            "AUTH_COMMAND_AUTHORIZATION_MISMATCH",
        ),
    ],
)
def test_batch_ledger_cas_rejects_approval_drift_after_jit_before_dispatch(
    ledger_db,
    approval_drift,
    reason_code,
):
    queue_guard = _persist_running_batch_queue()
    ledger = MutationDispatchLedger(recover_inflight=False)
    command = _batch_save_command(queue_guard=queue_guard)
    assert ledger.reserve_command(command).ok is True

    with db.connection() as conn:
        row = conn.execute("SELECT payload_json FROM tasks WHERE id=31").fetchone()
        payload = db.loads(row["payload_json"], {})
        payload["manual_approval"].update(approval_drift)
        conn.execute(
            "UPDATE tasks SET payload_json=? WHERE id=31",
            (db.dumps(payload),),
        )

    operation_calls = 0
    decision = ledger.begin_dispatch(command, "save_only_click")
    if decision.ok:
        operation_calls += 1

    assert decision.ok is False
    assert decision.reason_code == reason_code
    assert operation_calls == 0
    entry = ledger.get_entry(command.mutation_scope_id, "save_only_click")
    assert entry["status"] == "RESERVED"
    assert entry["dispatch_started_at"] is None


def test_batch_ledger_cas_accepts_current_consumed_approval_lease(authority_case):
    ledger = _trusted_authority_ledger(authority_case)
    command = authority_case["command"]

    decision = ledger.begin_dispatch(
        command,
        "save_only_click",
        authority_case["identity"],
    )

    assert decision.ok is True
    assert decision.reason_code == "OK"
    entry = ledger.get_entry(command.mutation_scope_id, "save_only_click")
    assert entry["status"] == "DISPATCHING"
    assert entry["dispatch_started_at"]


def test_browser_runtime_never_calls_operation_when_lease_expires_after_jit(ledger_db):
    queue_guard = _persist_running_batch_queue()
    operation_calls: list[str] = []

    class PersistentBatchAdapter:
        requires_persistent_browser_agent = True

        def __init__(self):
            self.authorizer = None
            self.command_context = None
            self.target_hash = None

        def browser_session_id(self):
            return "batch-browser-session-lease-cas"

        def refresh_account_context_hash(self):
            return "A" * 64

        def current_mutation_identity(self):
            return {
                "browser_session_id": self.browser_session_id(),
                "page_url": "https://www.dianxiaomi.com/web/smt/edit?id=70001",
                "page_kind": "editor",
                "target_hash": self.target_hash,
            }

        def set_mutation_authorizer(self, authorizer, command_context=None):
            self.authorizer = authorizer
            self.command_context = dict(command_context or {})

        def clear_mutation_authorizer(self):
            self.authorizer = None

        def save_only(self, **_kwargs):
            decision = self.authorizer(
                {
                    **self.command_context,
                    "mutation_action": "save_only_click",
                    "_pre_dispatch_guard": lambda: {"ok": True},
                },
                lambda: operation_calls.append("save_only_click")
                or {"dispatched": True},
            )
            if decision.get("ok") is not True:
                raise RuntimeError(decision.get("reason_code") or "mutation rejected")
            return {"ok": True}

    adapter = PersistentBatchAdapter()
    ledger = MutationDispatchLedger(recover_inflight=False)
    runtime = BrowserAgentRuntime(adapter, mutation_ledger=ledger)

    def expire_after_jit(_command, _context):
        with db.connection() as conn:
            row = conn.execute("SELECT payload_json FROM tasks WHERE id=31").fetchone()
            payload = db.loads(row["payload_json"], {})
            payload["manual_approval"]["expires_at"] = "2000-01-01T00:00:00+00:00"
            conn.execute(
                "UPDATE tasks SET payload_json=? WHERE id=31",
                (db.dumps(payload),),
            )
        return {"ok": True, "reason_code": "OK"}

    runtime.set_mutation_authorizer(expire_after_jit)
    base_command = _batch_save_command(queue_guard=queue_guard)
    target = build_frozen_product_target_identity(
        product_id="70001",
        store_name="E3 Draft Shop",
        source_urls=["https://detail.1688.com/offer/70001.html"],
    )
    params = {
        **base_command.params,
        "store_name": "E3 Draft Shop",
        "product_query": "70001",
        "target_source_urls": target["source_urls"],
        "target_identity": target,
    }
    command = replace(
        base_command,
        runtime_id=runtime.runtime_id,
        params=params,
        target_hash=mutation_target_hash("save_only", params),
    )
    adapter.target_hash = command.target_hash
    assert runtime.reserve_command(command)["ok"] is True

    with pytest.raises(RuntimeError, match="AUTH_LEASE_EXPIRED"):
        runtime.run(command, timeout_seconds=1)

    assert operation_calls == []
    entry = ledger.get_entry(command.mutation_scope_id, "save_only_click")
    assert entry["status"] == "RESERVED"
    assert entry["dispatch_started_at"] is None
    runtime.shutdown()


def test_batch_verify_must_match_the_actual_dispatched_save_command_in_ledger(
    authority_case,
):
    ledger = _trusted_authority_ledger(authority_case)
    save_command = authority_case["command"]
    assert ledger.begin_dispatch(
        save_command,
        "save_only_click",
        authority_case["identity"],
    ).ok is True
    assert ledger.mark_dispatched(
        save_command,
        "save_only_click",
        {"dispatched": True},
    ).ok is True
    save_action_result = _record_batch_save_success(ledger, save_command)

    verify_command = _authority_verify_command(
        save_command,
        save_action_result,
    )
    assert ledger.reserve_command(verify_command).ok is True

    forged_context = dict(verify_command.params["save_verification_context"])
    forged_context["save_command_sha256"] = "D" * 64
    forged_body = {
        key: value
        for key, value in forged_context.items()
        if key != "context_sha256"
    }
    forged_context["context_sha256"] = _canonical_sha256(forged_body)
    forged_verify = replace(
        verify_command,
        command_id="batch-verify-command-forged",
        idempotency_key="batch-verify-idempotency-forged",
        params={"save_verification_context": forged_context},
    )

    forged = ledger.reserve_command(forged_verify)
    assert forged.ok is False
    assert forged.reason_code == "SAVE_VERIFICATION_LEDGER_MISMATCH"


@pytest.mark.parametrize(
    ("field", "forged_value"),
    [
        ("plan_snapshot_hash", "d" * 64),
        ("git_head", "2" * 40),
        ("worktree_identity_sha256", "e" * 64),
        ("queue_version", "f" * 64),
    ],
)
def test_batch_verify_rebuilds_metadata_from_actual_dispatched_save_authority(
    authority_case,
    field,
    forged_value,
):
    ledger = _trusted_authority_ledger(authority_case)
    save_command = authority_case["command"]
    assert ledger.begin_dispatch(
        save_command,
        "save_only_click",
        authority_case["identity"],
    ).ok is True
    assert ledger.mark_dispatched(
        save_command,
        "save_only_click",
        {"dispatched": True},
    ).ok is True
    save_action_result = _record_batch_save_success(ledger, save_command)

    honest_verify = _authority_verify_command(
        save_command,
        save_action_result,
    )
    assert ledger.reserve_command(honest_verify).ok is True

    forged_context = dict(honest_verify.params["save_verification_context"])
    forged_context[field] = forged_value.upper()
    forged_context["context_sha256"] = _canonical_sha256(
        {
            key: value
            for key, value in forged_context.items()
            if key != "context_sha256"
        }
    )
    forged_verify = replace(
        honest_verify,
        command_id=f"batch-verify-forged-{field}",
        idempotency_key=f"batch-verify-forged-{field}",
        params={"save_verification_context": forged_context},
    )

    decision = ledger.reserve_command(forged_verify)

    assert decision.ok is False
    assert decision.reason_code == "SAVE_VERIFICATION_AUTHORITY_MISMATCH"


def test_verify_semantic_validator_rejects_self_signed_metadata_without_authority(
    ledger_db,
):
    queue_guard = _persist_running_batch_queue()
    save_command = _batch_save_command(queue_guard=queue_guard)
    context = _batch_verify_command(save_command).params["save_verification_context"]

    with pytest.raises(BatchCommandContractError) as exc_info:
        validate_save_verification_context(
            context,
            save_command=save_command.to_payload(),
        )

    assert exc_info.value.reason_code == "SAVE_VERIFICATION_AUTHORITY_REQUIRED"


def test_same_lease_and_scope_rejects_authorization_or_target_drift(ledger_db):
    ledger = MutationDispatchLedger(recover_inflight=False)
    command = _claim_command()
    assert ledger.reserve_command(command).ok is True

    drifted = _claim_command(
        command_id="command-drifted",
        target_hash="d" * 64,
        authorization_fingerprint="e" * 64,
    )
    decision = ledger.reserve_command(drifted)

    assert decision.ok is False
    assert decision.reason_code == "MUTATION_SCOPE_BINDING_MISMATCH"


def test_browser_runtime_ledger_blocks_same_scope_after_runtime_restart(ledger_db):
    operation_calls: list[str] = []

    class PersistentMutationAdapter:
        requires_persistent_browser_agent = True

        def __init__(self) -> None:
            self.authorizer = None
            self.command_context = None

        def browser_session_id(self):
            return "browser-session-ledger-1"

        def current_mutation_identity(self):
            return {
                "browser_session_id": self.browser_session_id(),
                "page_url": "https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
                "page_kind": "data_acquisition",
                "target_hash": HASH_B,
            }

        def set_mutation_authorizer(self, authorizer, command_context=None):
            self.authorizer = authorizer
            self.command_context = dict(command_context or {})

        def clear_mutation_authorizer(self):
            self.authorizer = None

        def claim_from_data_acquisition(self, *_args, **_kwargs):
            for mutation_action in (
                "claim_open_dialog_click",
                "claim_confirm_click",
            ):
                decision = self.authorizer(
                    {
                        **self.command_context,
                        "mutation_action": mutation_action,
                    },
                    lambda action=mutation_action: operation_calls.append(action)
                    or {"dispatched": True, "action": action},
                )
                if decision.get("ok") is not True:
                    raise RuntimeError(
                        decision.get("reason_code")
                        or decision.get("reason")
                        or "mutation rejected"
                    )
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
                "contract_facts": {
                    "before_values": {"claim_state": "pending"},
                    "after_values": {"claim_state": "dispatched"},
                    "postconditions": {
                        "target_unique": True,
                        "source_identity_match": True,
                        "store_selected_exact": True,
                        "category_selected_exact": True,
                        "claim_dispatched": True,
                        "publish_not_attempted": True,
                    },
                    "evidence_observations": {
                        "mutation_actions": list(operation_calls),
                    },
                    "failure_code": None,
                    "recoverability": {
                        "kind": "none",
                        "retryable": False,
                        "requires_page_reverify": False,
                        "reason": None,
                    },
                },
            }

    first_ledger = MutationDispatchLedger(recover_inflight=False)
    first_adapter = PersistentMutationAdapter()
    first_runtime = BrowserAgentRuntime(first_adapter, mutation_ledger=first_ledger)
    first_runtime.set_mutation_authorizer(lambda _command, _context: {"ok": True})
    first_command = _claim_command(runtime_id=first_runtime.runtime_id)

    assert first_runtime.reserve_command(first_command)["ok"] is True
    assert first_runtime.run(first_command, timeout_seconds=1)["ok"] is True
    assert operation_calls == [
        "claim_open_dialog_click",
        "claim_confirm_click",
    ]
    first_runtime.shutdown()

    restarted_ledger = MutationDispatchLedger(recover_inflight=False)
    restarted_adapter = PersistentMutationAdapter()
    restarted_runtime = BrowserAgentRuntime(
        restarted_adapter,
        mutation_ledger=restarted_ledger,
    )
    restarted_runtime.set_mutation_authorizer(lambda _command, _context: {"ok": True})
    retry_command = _claim_command(
        command_id="command-after-restart",
        idempotency_key="idempotency-after-restart",
        runtime_id=restarted_runtime.runtime_id,
    )

    reserve_retry = restarted_runtime.reserve_command(retry_command)
    assert reserve_retry["ok"] is False
    assert reserve_retry["reasonCode"] == "MUTATION_ALREADY_DISPATCHED"
    with pytest.raises(RuntimeError, match="MUTATION_ALREADY_DISPATCHED"):
        restarted_runtime.run(retry_command, timeout_seconds=1)

    assert operation_calls == [
        "claim_open_dialog_click",
        "claim_confirm_click",
    ]
    restarted_runtime.shutdown()


def _authorized_claim_task(*, include_lease: bool = True):
    target = canonical_claim_target_identity(
        "https://detail.1688.com/offer/1001.html",
        keyword="Hazbin Hotel 立牌",
        category_name="立牌类谷子",
    )
    facts = build_stage_a_task_facts(
        task_id=11,
        job_id=22,
        store_id=3,
        target_identity=target,
    )
    context = build_authorization_context(
        stage_task_facts=facts,
        runtime_instance_id="backend-instance-1",
        browser_session_id="browser-session-1",
        git_head="1" * 40,
        l2_evidence_fingerprint="2" * 64,
        approved_by="ops-owner",
    )
    approval = {
        "approved": True,
        "source": "server",
        "approved_by": "ops-owner",
        "consumed": True,
        "consumed_at": "2098-01-01T00:00:00+00:00",
        "stage_task_facts": facts,
        "authorization_context": context,
    }
    if include_lease:
        approval["lease_id"] = "lease-claim-v1"
    return {
        "id": 11,
        "mode": "claim_only",
        "payload": {"manual_approval": approval},
    }


def test_v1_builder_binds_real_mutation_to_consumed_lease_facts_and_target():
    task = _authorized_claim_task()

    class Repo:
        def get_task_private(self, task_id):
            assert task_id == task["id"]
            return task

    class Runtime:
        runtime_id = "ephemeral-browser-runtime"

    class RealMutationAdapterMarker:
        requires_persistent_browser_agent = True

    runner = V1TaskRunner(
        Repo(),
        manager=None,
        workflow_adapter=RealMutationAdapterMarker(),
        browser_agent_runtime=Runtime(),
        workflow_action_timeout_seconds=5,
    )
    params = {
        "claim_mark": "AI认领-11",
        "product_query": "Hazbin Hotel 立牌",
        "category_name": "立牌类谷子",
        "store_name": "Dang Kang",
        "target_source_urls": ["https://detail.1688.com/offer/1001.html"],
    }

    command = runner._build_browser_agent_command(
        task,
        {"id": 22},
        StateName.CLAIM_TO_DRAFT_BOX,
        "claim_from_data_acquisition",
        params,
    )

    assert command.authorization_lease_id == "lease-claim-v1"
    assert command.stage_task_facts_fingerprint == task["payload"]["manual_approval"]["stage_task_facts"]["fingerprint"]
    assert command.target_hash == mutation_target_hash(command.action, params)
    assert validate_browser_agent_command(command)["claim_confirm_click"] == 2
    assert "ephemeral-browser-runtime" not in command.mutation_scope_id


def test_v1_builder_fails_closed_when_real_mutation_has_no_lease():
    task = _authorized_claim_task(include_lease=False)

    class Repo:
        def get_task_private(self, _task_id):
            return task

    class Runtime:
        runtime_id = "ephemeral-browser-runtime"

    class RealMutationAdapterMarker:
        requires_persistent_browser_agent = True

    runner = V1TaskRunner(
        Repo(),
        manager=None,
        workflow_adapter=RealMutationAdapterMarker(),
        browser_agent_runtime=Runtime(),
        workflow_action_timeout_seconds=5,
    )

    with pytest.raises(V1ExecutionError) as exc_info:
        runner._build_browser_agent_command(
            task,
            {"id": 22},
            StateName.CLAIM_TO_DRAFT_BOX,
            "claim_from_data_acquisition",
            {
                "claim_mark": "AI认领-11",
                "product_query": "Hazbin Hotel 立牌",
                "category_name": "立牌类谷子",
                "store_name": "Dang Kang",
                "target_source_urls": ["https://detail.1688.com/offer/1001.html"],
            },
        )

    assert "mutation authorization lease" in exc_info.value.detail
