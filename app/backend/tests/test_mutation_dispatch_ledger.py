from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from src import db
from src.execution.browser_agent_protocol import (
    BrowserAgentCommand,
    MutationCommandContractError,
    build_mutation_id,
    build_mutation_scope_id,
    validate_browser_agent_command,
)
from src.execution.mutation_dispatch_ledger import MutationDispatchLedger


HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


@pytest.fixture()
def ledger_db(tmp_path, monkeypatch):
    db_path = tmp_path / "mutation-ledger.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.init_db()
    return db_path


def _save_command(**overrides) -> BrowserAgentCommand:
    values = {
        "command_id": "command-1",
        "idempotency_key": "idempotency-1",
        "deadline": "2099-01-01T00:00:00+00:00",
        "expected_page": "semi_managed",
        "runtime_id": "ephemeral-runtime-1",
        "task_id": 11,
        "job_id": 22,
        "state": "SAVE_ONLY",
        "action": "save_only",
        "params": {},
        "authorization_lease_id": "lease-save-1",
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


def test_init_db_creates_durable_mutation_dispatch_ledger(ledger_db) -> None:
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
    }.issubset(columns)


def test_save_mutation_identity_is_stable_across_runtime_restart() -> None:
    before = _save_command(runtime_id="runtime-before")
    after = _save_command(runtime_id="runtime-after")

    before_id = build_mutation_id(
        mutation_scope_id=before.mutation_scope_id,
        state=before.state,
        ordinal=1,
        mutation_action="save_only_click",
    )
    after_id = build_mutation_id(
        mutation_scope_id=after.mutation_scope_id,
        state=after.state,
        ordinal=1,
        mutation_action="save_only_click",
    )

    assert before.mutation_scope_id == after.mutation_scope_id
    assert before_id == after_id
    assert validate_browser_agent_command(before) == {"save_only_click": 1}


def test_mutation_command_missing_scope_fails_closed() -> None:
    with pytest.raises(MutationCommandContractError) as exc_info:
        validate_browser_agent_command(_save_command(mutation_scope_id=None))

    assert exc_info.value.reason_code == "MUTATION_SCOPE_REQUIRED"


def test_non_mutation_command_must_not_smuggle_mutation_scope() -> None:
    command = _save_command(state="OPEN_DRAFT_LIST", action="open_draft_box")

    with pytest.raises(MutationCommandContractError) as exc_info:
        validate_browser_agent_command(command)

    assert exc_info.value.reason_code == "NON_MUTATION_SCOPE_FORBIDDEN"


def test_only_one_concurrent_caller_can_begin_save(ledger_db) -> None:
    ledger = MutationDispatchLedger(recover_inflight=False)
    command = _save_command()
    assert ledger.reserve_command(command).ok is True

    with ThreadPoolExecutor(max_workers=2) as executor:
        decisions = list(
            executor.map(
                lambda _ignored: ledger.begin_dispatch(command, "save_only_click"),
                range(2),
            )
        )

    assert sum(decision.ok is True for decision in decisions) == 1
    assert {decision.reason_code for decision in decisions} == {
        "OK",
        "MUTATION_ALREADY_DISPATCHING",
    }


def test_restart_recovers_dispatching_save_to_unknown_and_never_retries(ledger_db) -> None:
    command = _save_command()
    first_process = MutationDispatchLedger(recover_inflight=False)
    assert first_process.reserve_command(command).ok is True
    assert first_process.begin_dispatch(command, "save_only_click").ok is True

    restarted_process = MutationDispatchLedger()
    retry = restarted_process.begin_dispatch(command, "save_only_click")

    assert retry.ok is False
    assert retry.reason_code == "MUTATION_OUTCOME_UNKNOWN"
    assert restarted_process.get_entry(
        command.mutation_scope_id,
        "save_only_click",
    )["status"] == "UNKNOWN"


def test_dispatched_save_is_terminal_and_cannot_auto_dispatch_again(ledger_db) -> None:
    ledger = MutationDispatchLedger(recover_inflight=False)
    command = _save_command()
    assert ledger.reserve_command(command).ok is True
    assert ledger.begin_dispatch(command, "save_only_click").ok is True
    assert ledger.mark_dispatched(command, "save_only_click").ok is True

    retry = ledger.begin_dispatch(command, "save_only_click")

    assert retry.ok is False
    assert retry.reason_code == "MUTATION_ALREADY_DISPATCHED"


def test_same_save_scope_rejects_authorization_or_target_drift(ledger_db) -> None:
    ledger = MutationDispatchLedger(recover_inflight=False)
    command = _save_command()
    assert ledger.reserve_command(command).ok is True

    drifted = _save_command(
        command_id="command-drifted",
        target_hash="d" * 64,
        authorization_fingerprint="e" * 64,
    )
    decision = ledger.reserve_command(drifted)

    assert decision.ok is False
    assert decision.reason_code == "MUTATION_SCOPE_BINDING_MISMATCH"
