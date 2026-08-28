from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from importlib import import_module
from typing import Any, Callable

import pytest

from src import db
from src.batch_edit.frozen_execution_contract import (
    compile_frozen_execution_payload,
    frozen_execution_defaults,
)
from src.batch_edit.plan_snapshot_store import PlanSnapshotStore
from src.batch_edit.scope_contract import canonical_sha256
from src.execution.batch_command_contract import build_batch_queue_guard
from src.execution.batch_command_contract import validate_save_verification_context
from src.execution.browser_agent_protocol import (
    BrowserAgentCommand,
    build_frozen_product_target_identity,
    build_mutation_scope_id,
    mutation_target_hash,
)
from src.execution.mutation_dispatch_ledger import MutationDispatchLedger
from src.execution.e3_authority_contract import (
    authorization_lease_authority_fingerprint,
)
from src.repository import Repository
from src.state_machine.batch_draft_authorization import (
    build_authorization_context,
    build_batch_draft_save_task_facts,
)


GIT_HEAD = "5" * 40
L2_FINGERPRINT = "6" * 64
RUNTIME_INSTANCE_ID = "dispatch-authority-backend-runtime"
BROWSER_RUNTIME_ID = "dispatch-authority-browser-runtime"
BROWSER_SESSION_ID = "dispatch-authority-browser-session"
STORE_NAME = "Dispatch Authority Shop"


def _sha256(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest().upper()


def _worktree_identity(seed: str = "authority") -> dict[str, Any]:
    return {
        "schema": "dxm.git-worktree.identity.v1",
        "git_head": GIT_HEAD,
        "git_dirty": True,
        "status_count": 7,
        "status_sha256": _sha256(f"{seed}-status"),
        "execution_file_count": 91,
        "execution_tree_sha256": _sha256(f"{seed}-tree"),
    }


def _snapshot(store_id: int, product_ids: list[int]) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema": "dxm_batch_draft_save_plan.v1",
        "mode": "batch_draft_save",
        "path": "A",
        "shop_scope": str(store_id),
        "session_context": {
            "session_ref": "dispatch-authority-reader-session",
            "account_ref_hash": "A" * 64,
            "shop_id": str(store_id),
            "shop_name": STORE_NAME,
        },
        "local_plan_template": {"id": 1, "version": "1.0.0"},
        "product_ids": [str(value) for value in product_ids],
        "item_snapshots": [],
        "publish_allowed": False,
    }
    for product_id in product_ids:
        normalized_schema = {
            "type": "object",
            "properties": {
                "weight": {
                    "type": "string",
                    "ui_binding": "dxm_editor:weight",
                }
            },
        }
        mapping_body = {
            "mapping_version": "1.0.0",
            "entries": [
                {
                    "ui_label_zh": "包装重量",
                    "field_key": "weight",
                    "category_schema_path": "$.properties.weight",
                    "ui_binding": "dxm_editor:weight",
                }
            ],
        }
        resolution_body = {
            "resolved_fields": [
                {
                    "field_key": "weight",
                    "source": "local_plan_template",
                    "source_ref": "1@1.0.0",
                    "resolved_value": "10",
                    "natural_language": False,
                    "expected_language": None,
                    "detected_language": None,
                }
            ],
            "unresolved_fields": [],
            "price_validation": {"current_values": {}, "resolved_values": {}},
        }
        body["item_snapshots"].append(
            {
                "product_id": str(product_id),
                "categoryId": "2621",
                "target_identity": build_frozen_product_target_identity(
                    product_id=str(product_id),
                    store_name=STORE_NAME,
                    source_urls=[f"https://detail.1688.com/offer/{product_id}.html"],
                ),
                "category_schema": {
                    "normalized_schema": normalized_schema,
                    "schema_hash": canonical_sha256(normalized_schema),
                },
                "field_mapping": {
                    **mapping_body,
                    "mapping_hash": canonical_sha256(mapping_body),
                },
                "resolution_result": {
                    **resolution_body,
                    "resolution_hash": canonical_sha256(resolution_body),
                },
            }
        )
    return {**body, "snapshot_hash": canonical_sha256(body)}


@pytest.fixture()
def authority_case(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "batch-dispatch-authority.db")
    db.init_db()
    repository = Repository()
    store = repository.create_store(STORE_NAME, "AliExpress")
    product_ids = [70001, 70002, 70003]
    snapshot = _snapshot(store["id"], product_ids)
    row = PlanSnapshotStore().freeze_with_task(
        snapshot,
        idempotency_key="dispatch-authority-snapshot-1",
    )
    task = repository.get_task_private(int(row["task_id"]))
    assert task is not None
    stage_facts = build_batch_draft_save_task_facts(
        task_id=task["id"],
        store_id=task["store_id"],
        product_ids=product_ids,
        plan_snapshot_id=task["payload"]["plan_snapshot_id"],
        plan_snapshot_hash=task["payload"]["plan_snapshot_hash"],
        path="A",
    )
    worktree_identity = _worktree_identity()
    authorization_context = build_authorization_context(
        stage_task_facts=stage_facts,
        runtime_instance_id=RUNTIME_INSTANCE_ID,
        browser_session_id=BROWSER_SESSION_ID,
        git_head=GIT_HEAD,
        worktree_identity=worktree_identity,
        l2_evidence_fingerprint=L2_FINGERPRINT,
        approved_by="ops-owner",
    )
    issued_at = datetime.now(timezone.utc)
    approval = repository.approve_and_start_task_with_authorization(
        task["id"],
        token="dispatch-authority-token",
        confirmation="CONFIRM_DXM_SAVE_ONLY",
        approved_by="ops-owner",
        authorization_context=authorization_context,
        lease_id="dispatch-authority-lease",
        issued_at=issued_at.isoformat(),
        expires_at=(issued_at + timedelta(minutes=4)).isoformat(),
        consumed_at=issued_at.isoformat(),
    )
    assert approval.ok is True
    task = repository.get_task_private(task["id"])
    assert task is not None
    first_job = task["jobs"][0]
    assert repository.update_job(
        first_job["id"],
        status="running",
        current_step_code="SAVE_ONLY",
        current_step_name="只保存不发布",
    ) is True
    task = repository.get_task_private(task["id"])
    assert task is not None
    first_job = task["jobs"][0]
    execution_payload = compile_frozen_execution_payload(task, first_job)
    defaults = frozen_execution_defaults(execution_payload)
    queue_guard = build_batch_queue_guard(task, first_job["id"])
    target_identity = deepcopy(snapshot["item_snapshots"][0]["target_identity"])
    params = {
        "defaults": defaults,
        "batch_queue_guard": queue_guard,
        "store_name": STORE_NAME,
        "product_query": str(product_ids[0]),
        "target_source_urls": deepcopy(target_identity["source_urls"]),
        "target_identity": target_identity,
    }
    command_values = {
        "command_id": "dispatch-authority-command",
        "idempotency_key": "dispatch-authority-idempotency",
        "deadline": "2099-01-01T00:00:00+00:00",
        "expected_page": "editor",
        "runtime_id": BROWSER_RUNTIME_ID,
        "task_id": task["id"],
        "job_id": first_job["id"],
        "state": "SAVE_ONLY",
        "action": "save_only",
        "params": params,
        "execution_mode": "batch_draft_save",
        "execution_payload_hash": execution_payload["payload_hash"],
        "target_hash": mutation_target_hash("save_only", params),
        "authorization_fingerprint": authorization_context["fingerprint"],
        "authorization_lease_id": "dispatch-authority-lease",
        "authorization_lease_fingerprint": authorization_lease_authority_fingerprint(
            task["payload"]["manual_approval"]
        ),
        "stage_task_facts_fingerprint": stage_facts["fingerprint"],
    }
    command_values["mutation_scope_id"] = build_mutation_scope_id(
        authorization_lease_id=command_values["authorization_lease_id"],
        task_id=command_values["task_id"],
        job_id=command_values["job_id"],
        state=command_values["state"],
        action=command_values["action"],
    )
    command = BrowserAgentCommand(**command_values)
    ledger = MutationDispatchLedger(recover_inflight=False)
    assert ledger.reserve_command(command).ok is True
    identity = {
        "browser_session_id": BROWSER_SESSION_ID,
        "page_url": f"https://www.dianxiaomi.com/web/smt/edit?id={product_ids[0]}",
        "page_kind": "editor",
        "target_hash": command.target_hash,
    }
    live_facts = {
        "runtime_instance_id": RUNTIME_INSTANCE_ID,
        "browser_runtime_id": BROWSER_RUNTIME_ID,
        "browser_session_id": BROWSER_SESSION_ID,
        "git_head": GIT_HEAD,
        "worktree_identity": worktree_identity,
        "l2_status": "passed",
        "l2_evidence_fingerprint": L2_FINGERPRINT,
        "account_ref_hash": "A" * 64,
    }
    return {
        "repository": repository,
        "task": task,
        "job": first_job,
        "snapshot_id": int(row["id"]),
        "command": command,
        "identity": identity,
        "live_facts": live_facts,
        "ledger": ledger,
    }


def _update_task_payload(task_id: int, mutate: Callable[[dict[str, Any]], None]) -> None:
    with db.connection() as conn:
        row = conn.execute("SELECT payload_json FROM tasks WHERE id=?", (task_id,)).fetchone()
        payload = db.loads(row["payload_json"], {})
        mutate(payload)
        conn.execute(
            "UPDATE tasks SET payload_json=? WHERE id=?",
            (db.dumps(payload), task_id),
        )


def _validate(case: dict[str, Any], *, command=None, identity=None, live_facts=None):
    authority = import_module("src.execution.batch_dispatch_authority")
    trusted = authority.LiveDispatchFacts(**(live_facts or case["live_facts"]))
    with db.connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        return authority.validate_in_transaction(
            conn,
            command or case["command"],
            identity or case["identity"],
            trusted,
        )


def _assert_rejected_without_dispatch(case: dict[str, Any], decision, reason_code: str) -> None:
    operation_calls: list[str] = []
    if decision.ok:
        operation_calls.append("save_only_click")
    assert decision.ok is False
    assert decision.reason_code == reason_code
    assert operation_calls == []
    entry = case["ledger"].get_entry(
        case["command"].mutation_scope_id,
        "save_only_click",
    )
    assert entry["status"] == "RESERVED"
    assert entry["dispatch_started_at"] is None


def test_transaction_authority_rejects_account_context_drift_with_same_browser_session(
    authority_case,
) -> None:
    live = import_module("src.execution.batch_dispatch_authority").LiveDispatchFacts(
        **authority_case["live_facts"]
    )
    object.__setattr__(live, "account_ref_hash", "B" * 64)

    authority = import_module("src.execution.batch_dispatch_authority")
    with db.connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        decision = authority.validate_in_transaction(
            conn,
            authority_case["command"],
            authority_case["identity"],
            live,
        )

    _assert_rejected_without_dispatch(
        authority_case,
        decision,
        "AUTH_ACCOUNT_CONTEXT_MISMATCH",
    )


def test_ledger_begin_keeps_reservation_when_current_account_drifted(
    authority_case,
) -> None:
    authority = import_module("src.execution.batch_dispatch_authority")
    drifted = authority.LiveDispatchFacts(
        **{
            **authority_case["live_facts"],
            "account_ref_hash": "B" * 64,
        }
    )
    ledger = MutationDispatchLedger(
        recover_inflight=False,
        live_facts_provider=lambda: drifted,
    )

    decision = ledger.begin_dispatch(
        authority_case["command"],
        "save_only_click",
        identity=authority_case["identity"],
    )

    _assert_rejected_without_dispatch(
        {**authority_case, "ledger": ledger},
        decision,
        "AUTH_ACCOUNT_CONTEXT_MISMATCH",
    )


def test_restarted_live_authority_rejects_account_drift_with_same_session(
    authority_case,
) -> None:
    authority = import_module("src.execution.batch_dispatch_authority")
    frozen = _validate(authority_case)
    drifted = authority.LiveDispatchFacts(
        **{
            **authority_case["live_facts"],
            "account_ref_hash": "B" * 64,
        }
    )

    decision = authority.validate_current_live_facts_against_frozen_authority(
        frozen.authority,
        drifted,
    )

    assert decision.ok is False
    assert decision.reason_code == "AUTH_ACCOUNT_CONTEXT_MISMATCH"


def test_transaction_authority_rejects_nested_approval_context_drift_after_jit(
    authority_case,
) -> None:
    assert _validate(authority_case).ok is True
    _update_task_payload(
        authority_case["task"]["id"],
        lambda payload: payload["manual_approval"]["authorization_context"].update(
            {"approved_by": "drifted-owner"}
        ),
    )

    decision = _validate(authority_case)

    _assert_rejected_without_dispatch(
        authority_case,
        decision,
        "AUTH_COMMAND_AUTHORIZATION_MISMATCH",
    )


def test_transaction_authority_rejects_l2_evidence_drift_after_jit(
    authority_case,
) -> None:
    assert _validate(authority_case).ok is True
    live_facts = {
        **authority_case["live_facts"],
        "l2_evidence_fingerprint": "7" * 64,
    }

    decision = _validate(authority_case, live_facts=live_facts)

    _assert_rejected_without_dispatch(
        authority_case,
        decision,
        "AUTH_L2_EVIDENCE_MISMATCH",
    )


def test_transaction_authority_rejects_stage_facts_drift_after_jit(
    authority_case,
) -> None:
    assert _validate(authority_case).ok is True
    _update_task_payload(
        authority_case["task"]["id"],
        lambda payload: payload["manual_approval"]["stage_task_facts"].update(
            {"plan_snapshot_hash": "8" * 64}
        ),
    )

    decision = _validate(authority_case)

    _assert_rejected_without_dispatch(
        authority_case,
        decision,
        "AUTH_STAGE_FACTS_MISMATCH",
    )


def test_transaction_authority_rejects_stored_snapshot_drift_after_jit(
    authority_case,
) -> None:
    assert _validate(authority_case).ok is True
    with db.connection() as conn:
        row = conn.execute(
            "SELECT snapshot_json FROM plan_snapshots WHERE id=?",
            (authority_case["snapshot_id"],),
        ).fetchone()
        snapshot = db.loads(row["snapshot_json"], {})
        snapshot["item_snapshots"][0]["resolution_result"]["resolved_fields"][0][
            "resolved_value"
        ] = "99"
        conn.execute(
            "UPDATE plan_snapshots SET snapshot_json=? WHERE id=?",
            (db.dumps(snapshot), authority_case["snapshot_id"]),
        )

    decision = _validate(authority_case)

    _assert_rejected_without_dispatch(
        authority_case,
        decision,
        "AUTH_COMMAND_SNAPSHOT_MISMATCH",
    )


def test_transaction_authority_rejects_queue_drift_after_jit(
    authority_case,
) -> None:
    assert _validate(authority_case).ok is True
    with db.connection() as conn:
        conn.execute(
            "UPDATE jobs SET status='pending' WHERE id=?",
            (authority_case["job"]["id"],),
        )

    decision = _validate(authority_case)

    _assert_rejected_without_dispatch(
        authority_case,
        decision,
        "AUTH_COMMAND_QUEUE_STATE_MISMATCH",
    )


def test_transaction_authority_rejects_git_head_drift_after_jit(
    authority_case,
) -> None:
    assert _validate(authority_case).ok is True
    live_facts = {**authority_case["live_facts"], "git_head": "9" * 40}

    decision = _validate(authority_case, live_facts=live_facts)

    _assert_rejected_without_dispatch(
        authority_case,
        decision,
        "AUTH_GIT_HEAD_MISMATCH",
    )


def test_transaction_authority_rejects_worktree_drift_after_jit(
    authority_case,
) -> None:
    assert _validate(authority_case).ok is True
    worktree = {
        **authority_case["live_facts"]["worktree_identity"],
        "execution_tree_sha256": _sha256("drifted-execution-tree"),
    }
    live_facts = {
        **authority_case["live_facts"],
        "worktree_identity": worktree,
    }

    decision = _validate(authority_case, live_facts=live_facts)

    _assert_rejected_without_dispatch(
        authority_case,
        decision,
        "AUTH_WORKTREE_IDENTITY_MISMATCH",
    )


def test_transaction_authority_rejects_runtime_drift_after_jit(
    authority_case,
) -> None:
    assert _validate(authority_case).ok is True
    live_facts = {
        **authority_case["live_facts"],
        "runtime_instance_id": "drifted-backend-runtime",
    }

    decision = _validate(authority_case, live_facts=live_facts)

    _assert_rejected_without_dispatch(
        authority_case,
        decision,
        "AUTH_RUNTIME_IDENTITY_MISMATCH",
    )


def test_transaction_authority_rejects_browser_session_drift_after_jit(
    authority_case,
) -> None:
    assert _validate(authority_case).ok is True
    live_facts = {
        **authority_case["live_facts"],
        "browser_session_id": "drifted-browser-session",
    }

    decision = _validate(authority_case, live_facts=live_facts)

    _assert_rejected_without_dispatch(
        authority_case,
        decision,
        "AUTH_BROWSER_SESSION_MISMATCH",
    )


def test_transaction_authority_rejects_visible_target_drift_after_jit(
    authority_case,
) -> None:
    assert _validate(authority_case).ok is True
    identity = {
        **authority_case["identity"],
        "target_hash": "A" * 64,
    }

    decision = _validate(authority_case, identity=identity)

    _assert_rejected_without_dispatch(
        authority_case,
        decision,
        "AUTH_COMMAND_TARGET_MISMATCH",
    )


def test_transaction_authority_rejects_execution_payload_drift_after_jit(
    authority_case,
) -> None:
    assert _validate(authority_case).ok is True
    params = deepcopy(authority_case["command"].params)
    execution_payload = params["defaults"]["_frozen_execution_payload"]
    execution_payload["fields"][0]["resolved_value"] = "99"
    execution_payload["payload_hash"] = canonical_sha256(
        {
            key: value
            for key, value in execution_payload.items()
            if key != "payload_hash"
        }
    )
    params["defaults"]["weight"] = "99"
    params["defaults"]["_frozen_execution_payload_hash"] = execution_payload[
        "payload_hash"
    ]
    command = replace(
        authority_case["command"],
        params=params,
        execution_payload_hash=execution_payload["payload_hash"],
    )

    decision = _validate(authority_case, command=command)

    _assert_rejected_without_dispatch(
        authority_case,
        decision,
        "AUTH_COMMAND_EXECUTION_MISMATCH",
    )


def test_transaction_authority_returns_full_immutable_canonical_blob(
    authority_case,
) -> None:
    decision = _validate(authority_case)

    assert decision.ok is True
    assert decision.reason_code == "OK"
    authority = decision.authority
    assert authority["schema"] == "dxm.batch_draft_save.dispatch_authority.v1"
    assert authority["authorization"]["authorization_context"]["fingerprint"]
    assert authority["authorization"]["stage_task_facts"]["fingerprint"]
    assert authority["l2"] == {
        "status": "passed",
        "evidence_fingerprint": L2_FINGERPRINT,
    }
    assert authority["snapshot"]["plan_snapshot"]["snapshot_hash"]
    assert authority["queue"]["guard"] == authority_case["command"].params[
        "batch_queue_guard"
    ]
    assert [item["status"] for item in authority["queue"]["ordered_jobs"]] == [
        "running",
        "pending",
        "pending",
    ]
    assert authority["code_identity"]["git_head"] == GIT_HEAD
    assert authority["code_identity"]["worktree_identity"] == _worktree_identity()
    assert authority["runtime"] == {
        "runtime_instance_id": RUNTIME_INSTANCE_ID,
        "browser_runtime_id": BROWSER_RUNTIME_ID,
        "browser_session_id": BROWSER_SESSION_ID,
        "account_ref_hash": "A" * 64,
    }
    assert authority["target"]["identity"]["stable_identity"]["value"] == "70001"
    assert authority["target"]["payload"]["target_identity"] == authority["target"][
        "identity"
    ]
    assert authority["execution"]["payload"]["fields"][0]["resolved_value"] == "10"
    assert decision.authority_sha256 == canonical_sha256(authority)
    with pytest.raises(TypeError):
        authority["runtime"]["browser_session_id"] = "mutated"
    with pytest.raises(TypeError):
        authority["queue"]["ordered_jobs"][0]["status"] = "succeeded"


def test_current_task_validator_rejects_database_drift_from_frozen_authority(
    authority_case,
) -> None:
    dispatch = _validate(authority_case)
    assert dispatch.ok is True
    authority_module = import_module("src.execution.batch_dispatch_authority")
    with db.connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        current = authority_module.validate_current_task_against_frozen_authority(
            conn,
            dispatch.authority,
        )
    assert current.ok is True
    assert current.authority_sha256 == dispatch.authority_sha256

    _update_task_payload(
        authority_case["task"]["id"],
        lambda payload: payload["manual_approval"]["authorization_context"].update(
            {"approved_by": "post-dispatch-drift"}
        ),
    )
    with db.connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        drifted = authority_module.validate_current_task_against_frozen_authority(
            conn,
            dispatch.authority,
        )

    assert drifted.ok is False
    assert drifted.reason_code == "AUTH_CURRENT_TASK_DRIFT"


def test_save_verification_facts_are_derived_from_frozen_authority(
    authority_case,
) -> None:
    authority_module = import_module("src.execution.batch_dispatch_authority")
    dispatch = _validate(authority_case)
    action_result_sha256 = "B" * 64
    command_payload = authority_case["command"].to_payload()
    ledger_entry = {
        "status": "DISPATCHED",
        "mutation_action": "save_only_click",
        "task_id": str(authority_case["task"]["id"]),
        "job_id": str(authority_case["job"]["id"]),
        "command_sha256": canonical_sha256(command_payload),
        "save_action_result_sha256": action_result_sha256,
        "save_authority_sha256": dispatch.authority_sha256,
        "save_authority_json": json.dumps(
            dispatch.authority,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ),
    }

    facts = authority_module.save_verification_facts_from_frozen_authority(
        dispatch.authority,
        save_command=authority_case["command"],
        ledger_entry=ledger_entry,
        save_action_result_sha256=action_result_sha256,
    )

    assert facts["plan_snapshot_hash"] == dispatch.authority["snapshot"][
        "plan_snapshot_hash"
    ]
    assert facts["queue_version"] == dispatch.authority["queue"]["guard"][
        "queue_version"
    ]
    assert facts["browser_session_id"] == BROWSER_SESSION_ID
    assert facts["save_action_result_sha256"] == action_result_sha256
    assert facts["target_hash"] == authority_case["command"].target_hash.upper()
    assert facts["mutation_scope_id"] == authority_case[
        "command"
    ].mutation_scope_id.upper()
    assert facts["context_sha256"] == canonical_sha256(
        {key: value for key, value in facts.items() if key != "context_sha256"}
    )
    assert validate_save_verification_context(
        facts,
        task_id=authority_case["task"]["id"],
        job_id=authority_case["job"]["id"],
        runtime_id=BROWSER_RUNTIME_ID,
        execution_mode="batch_draft_save",
        authoritative_facts={
            key: value
            for key, value in facts.items()
            if key not in {"schema", "context_sha256"}
        },
    )["context_sha256"] == facts["context_sha256"]


def test_save_verification_facts_reject_tampered_authority(
    authority_case,
) -> None:
    authority_module = import_module("src.execution.batch_dispatch_authority")
    dispatch = _validate(authority_case)
    action_result_sha256 = "B" * 64
    command_payload = authority_case["command"].to_payload()
    ledger_entry = {
        "status": "DISPATCHED",
        "mutation_action": "save_only_click",
        "task_id": str(authority_case["task"]["id"]),
        "job_id": str(authority_case["job"]["id"]),
        "command_sha256": canonical_sha256(command_payload),
        "save_action_result_sha256": action_result_sha256,
        "save_authority_sha256": dispatch.authority_sha256,
        "save_authority_json": json.dumps(
            dispatch.authority,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ),
    }
    forged = json.loads(json.dumps(dispatch.authority))
    forged["runtime"]["browser_session_id"] = "forged-session"

    with pytest.raises(authority_module.DispatchAuthorityError) as exc_info:
        authority_module.save_verification_facts_from_frozen_authority(
            forged,
            save_command=authority_case["command"],
            ledger_entry=ledger_entry,
            save_action_result_sha256=action_result_sha256,
        )

    assert exc_info.value.reason_code == "SAVE_VERIFICATION_PREDECESSOR_FACTS_INVALID"
