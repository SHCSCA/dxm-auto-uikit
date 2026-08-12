from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from importlib import import_module

import pytest

from src import db
from src.execution.batch_command_contract import build_save_verification_context
from src.execution.batch_dispatch_authority import LiveDispatchFacts
from src.execution.mutation_dispatch_ledger import MutationDispatchLedger
from tests.test_action_result_contract import (
    _as_path_a_editor,
    _valid_save_result,
)
from tests.test_mutation_dispatch_ledger import (
    _batch_save_command,
    _batch_verify_command,
    _canonical_sha256,
    _persist_running_batch_queue,
)
from tests.test_batch_dispatch_authority import authority_case


@pytest.fixture()
def ledger_db(tmp_path, monkeypatch):
    db_path = tmp_path / "e3-dispatch-authority.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.init_db()
    return db_path


@pytest.mark.parametrize(
    ("checked_at", "expires_at", "expected"),
    [
        pytest.param(
            "2026-08-12T00:00:00.999999Z",
            "2026-08-12T00:00:01.000000Z",
            True,
            id="one-microsecond-before-expiry",
        ),
        pytest.param(
            "2026-08-12T00:00:01.000000+00:00",
            "2026-08-12T00:00:01.000000Z",
            False,
            id="exact-expiry",
        ),
        pytest.param(
            "2026-08-12T00:00:01.000001Z",
            "2026-08-12T00:00:01.000000+00:00",
            False,
            id="one-microsecond-after-expiry",
        ),
        pytest.param(
            "2026-08-12T00:00:00.999999",
            "2026-08-12T00:00:01.000000Z",
            False,
            id="naive-checked-at-fails-closed",
        ),
        pytest.param(
            "not-a-timestamp",
            "2026-08-12T00:00:01.000000Z",
            False,
            id="malformed-checked-at-fails-closed",
        ),
    ],
)
def test_authorization_lease_uses_strict_utc_microsecond_boundary(
    checked_at: str,
    expires_at: str,
    expected: bool,
) -> None:
    contract = import_module("src.execution.e3_authority_contract")

    assert contract.authorization_lease_is_active(
        checked_at=checked_at,
        expires_at=expires_at,
    ) is expected


def test_begin_dispatch_rejects_naive_persisted_lease_expiry(ledger_db) -> None:
    queue_guard = _persist_running_batch_queue()
    with db.connection() as conn:
        row = conn.execute("SELECT payload_json FROM tasks WHERE id=31").fetchone()
        payload = db.loads(row["payload_json"], {})
        payload["manual_approval"]["expires_at"] = "2099-01-01T00:00:00.000001"
        conn.execute(
            "UPDATE tasks SET payload_json=? WHERE id=31",
            (db.dumps(payload),),
        )

    ledger = MutationDispatchLedger(recover_inflight=False)
    command = _batch_save_command(queue_guard=queue_guard)
    assert ledger.reserve_command(command).ok is True

    decision = ledger.begin_dispatch(
        command,
        "save_only_click",
        {
            "browser_session_id": "batch-browser-session-1",
            "page_url": "https://www.dianxiaomi.com/web/smt/edit",
            "page_kind": "editor",
        },
    )

    assert decision.ok is False
    assert decision.reason_code == "AUTH_LEASE_EXPIRED"


def _mark_save_dispatched(
    ledger: MutationDispatchLedger,
    command,
    identity,
) -> None:
    assert ledger.begin_dispatch(
        command,
        "save_only_click",
        identity,
    ).ok is True
    assert ledger.mark_dispatched(
        command,
        "save_only_click",
        {"dispatched": True},
    ).ok is True


def _canonical_path_a_save_result(save_command, browser_session_id: str) -> dict:
    result = _as_path_a_editor(
        _valid_save_result(),
        save_command.params["defaults"]["_frozen_execution_payload"],
    )
    result["page_identity"]["runtime_id"] = save_command.runtime_id
    result["page_identity"]["browser_session_id"] = browser_session_id
    target = deepcopy(save_command.params["target_identity"])
    store_name = save_command.params["store_name"]
    target_sha256 = _canonical_sha256(target).lower()
    result["before_values"]["target_identity"] = deepcopy(target)
    result["before_values"]["store_name"] = store_name
    for pre_dispatch in (
        result["after_values"]["pre_dispatch_readback"],
        result["evidence"]["observations"]["pre_dispatch_readback"],
        result["evidence"]["observations"]["save_result"]["pre_dispatch_readback"],
    ):
        pre_dispatch["identity"]["target_identity"] = deepcopy(target)
        pre_dispatch["identity"]["target_identity_sha256"] = target_sha256
        pre_dispatch["identity"]["expected_store_name"] = store_name
    return result


def _verify_command_for_result(save_command, save_action_result):
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
    baseline = _batch_verify_command(save_command)
    return replace(
        baseline,
        params={"save_verification_context": context},
    )


def _trusted_ledger(authority_case) -> MutationDispatchLedger:
    live_facts = LiveDispatchFacts(**authority_case["live_facts"])
    return MutationDispatchLedger(
        recover_inflight=False,
        live_facts_provider=lambda: live_facts,
    )


def test_verify_requires_persisted_canonical_save_success(authority_case) -> None:
    ledger = _trusted_ledger(authority_case)
    save_command = authority_case["command"]
    _mark_save_dispatched(ledger, save_command, authority_case["identity"])

    decision = ledger.reserve_command(_batch_verify_command(save_command))

    assert decision.ok is False
    assert decision.reason_code == "SAVE_VERIFICATION_PREDECESSOR_FACTS_MISSING"


def test_record_success_freezes_full_action_result_before_verify(authority_case) -> None:
    ledger = _trusted_ledger(authority_case)
    save_command = authority_case["command"]
    _mark_save_dispatched(ledger, save_command, authority_case["identity"])
    save_action_result = _canonical_path_a_save_result(
        save_command,
        authority_case["live_facts"]["browser_session_id"],
    )

    recorded = ledger.record_success(save_command, save_action_result)

    assert recorded.ok is True
    assert recorded.entry["save_action_result_json"]
    assert recorded.entry["save_action_result_sha256"]
    verify = _verify_command_for_result(save_command, save_action_result)
    assert ledger.reserve_command(verify).ok is True


def test_verify_rejects_action_result_hash_not_frozen_by_save_ledger(authority_case) -> None:
    ledger = _trusted_ledger(authority_case)
    save_command = authority_case["command"]
    _mark_save_dispatched(ledger, save_command, authority_case["identity"])
    save_action_result = _canonical_path_a_save_result(
        save_command,
        authority_case["live_facts"]["browser_session_id"],
    )
    assert ledger.record_success(save_command, save_action_result).ok is True
    honest = _verify_command_for_result(save_command, save_action_result)
    forged_context = dict(honest.params["save_verification_context"])
    forged_context["save_action_result_sha256"] = "D" * 64
    forged_context["context_sha256"] = _canonical_sha256(
        {
            key: value
            for key, value in forged_context.items()
            if key != "context_sha256"
        }
    )
    forged = replace(
        honest,
        command_id="forged-action-result-hash",
        idempotency_key="forged-action-result-hash",
        params={"save_verification_context": forged_context},
    )

    decision = ledger.reserve_command(forged)

    assert decision.ok is False
    assert decision.reason_code == "SAVE_VERIFICATION_RESULT_MISMATCH"


def test_verify_rejects_synchronized_task_and_context_authority_tamper(
    authority_case,
) -> None:
    ledger = _trusted_ledger(authority_case)
    save_command = authority_case["command"]
    _mark_save_dispatched(ledger, save_command, authority_case["identity"])
    save_action_result = _canonical_path_a_save_result(
        save_command,
        authority_case["live_facts"]["browser_session_id"],
    )
    assert ledger.record_success(save_command, save_action_result).ok is True
    honest = _verify_command_for_result(save_command, save_action_result)
    forged_snapshot_hash = "D" * 64
    with db.connection() as conn:
        row = conn.execute(
            "SELECT payload_json FROM tasks WHERE id=?",
            (save_command.task_id,),
        ).fetchone()
        payload = db.loads(row["payload_json"], {})
        payload["plan_snapshot_hash"] = forged_snapshot_hash
        conn.execute(
            "UPDATE tasks SET payload_json=? WHERE id=?",
            (db.dumps(payload), save_command.task_id),
        )
    forged_context = dict(honest.params["save_verification_context"])
    forged_context["plan_snapshot_hash"] = forged_snapshot_hash
    forged_context["context_sha256"] = _canonical_sha256(
        {
            key: value
            for key, value in forged_context.items()
            if key != "context_sha256"
        }
    )
    forged = replace(
        honest,
        command_id="forged-task-and-context",
        idempotency_key="forged-task-and-context",
        params={"save_verification_context": forged_context},
    )

    decision = ledger.reserve_command(forged)

    assert decision.ok is False
    assert decision.reason_code == "SAVE_AUTHORITY_TASK_DRIFT"
