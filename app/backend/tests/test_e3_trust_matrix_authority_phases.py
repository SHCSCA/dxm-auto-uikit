from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable

import pytest

from src import db
from src.execution.batch_dispatch_authority import LiveDispatchFacts
from src.execution.mutation_dispatch_ledger import MutationDispatchLedger
from tests.test_batch_dispatch_authority import authority_case
from tests.test_e3_dispatch_authority import (
    _canonical_path_a_save_result,
    _mark_save_dispatched,
    _trusted_ledger,
    _verify_command_for_result,
)


def _live(case: dict[str, Any], **updates: Any) -> LiveDispatchFacts:
    values = deepcopy(case["live_facts"])
    values.update(updates)
    return LiveDispatchFacts(**values)


def _ledger(
    case: dict[str, Any],
    *,
    live: LiveDispatchFacts | None,
) -> MutationDispatchLedger:
    return MutationDispatchLedger(
        recover_inflight=False,
        live_facts_provider=(None if live is None else lambda: live),
    )


def _entry(case: dict[str, Any], ledger: MutationDispatchLedger) -> dict[str, Any]:
    entry = ledger.get_entry(
        case["command"].mutation_scope_id,
        "save_only_click",
    )
    assert entry is not None
    return entry


def _assert_reserved_zero_operation(
    case: dict[str, Any],
    ledger: MutationDispatchLedger,
    decision: Any,
    reason_code: str,
) -> None:
    operations: list[str] = []
    if decision.ok:
        operations.append("save_only_click")
    assert operations == []
    assert decision.ok is False
    assert decision.reason_code == reason_code
    entry = _entry(case, ledger)
    assert entry["status"] == "RESERVED"
    assert entry["dispatch_started_at"] is None
    assert entry["command_json"] is None
    assert entry["save_authority_json"] is None


def _prepare_proven_save(
    case: dict[str, Any],
) -> tuple[dict[str, Any], Any]:
    ledger = _trusted_ledger(case)
    command = case["command"]
    _mark_save_dispatched(ledger, command, case["identity"])
    result = _canonical_path_a_save_result(
        command,
        case["live_facts"]["browser_session_id"],
    )
    recorded = ledger.record_success(command, result)
    assert recorded.ok is True
    verify = _verify_command_for_result(command, result)
    before = _entry(case, ledger)
    assert before["status"] == "DISPATCHED"
    assert before["save_action_result_sha256"]
    assert before["save_authority_sha256"]
    return before, verify


def _assert_restart_verify_rejected_safely(
    case: dict[str, Any],
    ledger: MutationDispatchLedger,
    verify: Any,
    *,
    reason_code: str,
    before: dict[str, Any],
) -> None:
    operations: list[str] = []
    decision = ledger.reserve_command(verify)
    if decision.ok:
        operations.append("verify_not_published")
    assert operations == []
    assert decision.ok is False
    assert decision.reason_code == reason_code
    after = _entry(case, ledger)
    assert after["status"] == "DISPATCHED"
    assert after["command_sha256"] == before["command_sha256"]
    assert after["save_authority_sha256"] == before["save_authority_sha256"]
    assert after["save_action_result_sha256"] == before["save_action_result_sha256"]


@pytest.mark.parametrize(
    ("boundary", "table", "column", "value"),
    [
        pytest.param(
            "queue.job.status",
            "jobs",
            "status",
            "pending",
            id="reserve-to-jit-job-status",
        ),
        pytest.param(
            "queue.job.current_step_code",
            "jobs",
            "current_step_code",
            "VERIFY_NOT_PUBLISHED",
            id="reserve-to-jit-job-step",
        ),
        pytest.param(
            "queue.job.updated_at",
            "jobs",
            "updated_at",
            "1999-01-01T00:00:00.000000Z",
            id="reserve-to-jit-job-version",
        ),
        pytest.param(
            "queue.task.completed_jobs",
            "tasks",
            "completed_jobs",
            1,
            id="reserve-to-jit-task-counter",
        ),
    ],
)
def test_class_2_reserve_to_jit_rejects_single_field_queue_drift(
    authority_case,
    boundary: str,
    table: str,
    column: str,
    value: Any,
) -> None:
    target_id = (
        authority_case["job"]["id"]
        if table == "jobs"
        else authority_case["task"]["id"]
    )
    with db.connection() as conn:
        conn.execute(
            f"UPDATE {table} SET {column}=? WHERE id=?",
            (value, target_id),
        )
    ledger = _ledger(authority_case, live=_live(authority_case))

    decision = ledger.begin_dispatch(
        authority_case["command"],
        "save_only_click",
        authority_case["identity"],
    )

    assert boundary.startswith("queue.")
    _assert_reserved_zero_operation(
        authority_case,
        ledger,
        decision,
        "AUTH_COMMAND_QUEUE_STATE_MISMATCH",
    )


def _worktree_drift(case: dict[str, Any]) -> dict[str, Any]:
    value = deepcopy(case["live_facts"]["worktree_identity"])
    value["execution_tree_sha256"] = "E" * 64
    return value


@pytest.mark.parametrize(
    ("boundary", "updates", "reason_code"),
    [
        pytest.param(
            "code.git_head",
            {"git_head": "9" * 40},
            "AUTH_GIT_HEAD_MISMATCH",
            id="reserve-to-jit-git-head",
        ),
        pytest.param(
            "runtime.backend_instance",
            {"runtime_instance_id": "reserve-to-jit-backend-runtime"},
            "AUTH_RUNTIME_IDENTITY_MISMATCH",
            id="reserve-to-jit-backend-runtime",
        ),
        pytest.param(
            "runtime.browser_instance",
            {"browser_runtime_id": "reserve-to-jit-browser-runtime"},
            "AUTH_RUNTIME_IDENTITY_MISMATCH",
            id="reserve-to-jit-browser-runtime",
        ),
        pytest.param(
            "runtime.browser_session",
            {"browser_session_id": "reserve-to-jit-browser-session"},
            "AUTH_BROWSER_SESSION_MISMATCH",
            id="reserve-to-jit-browser-session",
        ),
        pytest.param(
            "runtime.lifecycle_generation",
            {
                "browser_runtime_id": "takeover-runtime-generation",
                "browser_session_id": "takeover-context-generation",
            },
            "AUTH_BROWSER_SESSION_MISMATCH",
            id="reserve-to-jit-takeover-lifecycle",
        ),
    ],
)
def test_class_4_reserve_to_jit_rejects_live_identity_drift(
    authority_case,
    boundary: str,
    updates: dict[str, Any],
    reason_code: str,
) -> None:
    if boundary == "runtime.lifecycle_generation":
        # The formal contract has no caller-supplied lifecycle token. Its
        # trusted lifecycle generation is the browser runtime + context/session
        # pair, so a takeover/reset changes both values together.
        assert set(updates) == {"browser_runtime_id", "browser_session_id"}
    ledger = _ledger(authority_case, live=_live(authority_case, **updates))

    decision = ledger.begin_dispatch(
        authority_case["command"],
        "save_only_click",
        authority_case["identity"],
    )

    _assert_reserved_zero_operation(
        authority_case,
        ledger,
        decision,
        reason_code,
    )


def test_class_4_reserve_to_jit_rejects_worktree_drift(authority_case) -> None:
    ledger = _ledger(
        authority_case,
        live=_live(
            authority_case,
            worktree_identity=_worktree_drift(authority_case),
        ),
    )

    decision = ledger.begin_dispatch(
        authority_case["command"],
        "save_only_click",
        authority_case["identity"],
    )

    _assert_reserved_zero_operation(
        authority_case,
        ledger,
        decision,
        "AUTH_WORKTREE_IDENTITY_MISMATCH",
    )


def _update_approval(
    case: dict[str, Any],
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    with db.connection() as conn:
        row = conn.execute(
            "SELECT payload_json FROM tasks WHERE id=?",
            (case["task"]["id"],),
        ).fetchone()
        payload = db.loads(row["payload_json"], {})
        mutate(payload["manual_approval"])
        conn.execute(
            "UPDATE tasks SET payload_json=? WHERE id=?",
            (db.dumps(payload), case["task"]["id"]),
        )


@pytest.mark.parametrize(
    ("boundary", "mutate"),
    [
        pytest.param(
            "approval.approved",
            lambda approval: approval.update({"approved": False}),
            id="restart-approval-revoked",
        ),
        pytest.param(
            "approval.lease.expires_at",
            lambda approval: approval.update(
                {"expires_at": "2098-01-01T00:00:00.000000Z"}
            ),
            id="restart-lease-authority-drift",
        ),
    ],
)
def test_class_1_restart_rejects_approval_or_lease_drift(
    authority_case,
    boundary: str,
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    before, verify = _prepare_proven_save(authority_case)
    _update_approval(authority_case, mutate)
    restarted = _ledger(authority_case, live=_live(authority_case))

    _assert_restart_verify_rejected_safely(
        authority_case,
        restarted,
        verify,
        reason_code="SAVE_AUTHORITY_TASK_DRIFT",
        before=before,
    )
    assert boundary.startswith("approval.")


@pytest.mark.parametrize(
    ("boundary", "updates", "reason_code"),
    [
        pytest.param(
            "l2.status",
            {"l2_status": "blocked"},
            "AUTH_L2_GATE_NOT_PASSED",
            id="restart-l2-status",
        ),
        pytest.param(
            "l2.evidence_fingerprint",
            {"l2_evidence_fingerprint": "7" * 64},
            "AUTH_L2_EVIDENCE_MISMATCH",
            id="restart-l2-evidence",
        ),
        pytest.param(
            "code.git_head",
            {"git_head": "9" * 40},
            "AUTH_GIT_HEAD_MISMATCH",
            id="restart-git-head",
        ),
        pytest.param(
            "runtime.backend_instance",
            {"runtime_instance_id": "restart-backend-runtime"},
            "AUTH_RUNTIME_IDENTITY_MISMATCH",
            id="restart-backend-runtime",
        ),
        pytest.param(
            "runtime.browser_instance",
            {"browser_runtime_id": "restart-browser-runtime"},
            "AUTH_RUNTIME_IDENTITY_MISMATCH",
            id="restart-browser-runtime",
        ),
        pytest.param(
            "runtime.browser_session",
            {"browser_session_id": "restart-browser-session"},
            "AUTH_BROWSER_SESSION_MISMATCH",
            id="restart-browser-session",
        ),
        pytest.param(
            "runtime.lifecycle_generation",
            {
                "browser_runtime_id": "reset-runtime-generation",
                "browser_session_id": "reset-context-generation",
            },
            "AUTH_RUNTIME_IDENTITY_MISMATCH",
            id="restart-reset-lifecycle",
        ),
    ],
)
def test_classes_1_and_4_restart_reject_live_authority_drift(
    authority_case,
    boundary: str,
    updates: dict[str, Any],
    reason_code: str,
) -> None:
    before, verify = _prepare_proven_save(authority_case)
    restarted = _ledger(authority_case, live=_live(authority_case, **updates))

    _assert_restart_verify_rejected_safely(
        authority_case,
        restarted,
        verify,
        reason_code=reason_code,
        before=before,
    )
    assert boundary.split(".", 1)[0] in {"l2", "code", "runtime"}


def test_class_4_restart_rejects_worktree_drift(authority_case) -> None:
    before, verify = _prepare_proven_save(authority_case)
    restarted = _ledger(
        authority_case,
        live=_live(
            authority_case,
            worktree_identity=_worktree_drift(authority_case),
        ),
    )

    _assert_restart_verify_rejected_safely(
        authority_case,
        restarted,
        verify,
        reason_code="AUTH_WORKTREE_IDENTITY_MISMATCH",
        before=before,
    )


def test_restart_verify_without_trusted_live_provider_fails_closed(
    authority_case,
) -> None:
    before, verify = _prepare_proven_save(authority_case)
    restarted = _ledger(authority_case, live=None)

    _assert_restart_verify_rejected_safely(
        authority_case,
        restarted,
        verify,
        reason_code="AUTH_DISPATCH_AUTHORITY_UNAVAILABLE",
        before=before,
    )
