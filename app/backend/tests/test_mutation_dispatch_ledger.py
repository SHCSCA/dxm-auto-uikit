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
    mutation_target_hash,
    validate_browser_agent_command,
)
from src.execution.browser_agent_worker import BrowserAgentRuntime
from src.execution.mutation_dispatch_ledger import MutationDispatchLedger
from src.execution.v1_runner import V1ExecutionError, V1TaskRunner
from src.state_machine.contracts import StateName
from src.state_machine.two_stage import (
    build_authorization_context,
    build_stage_a_task_facts,
    canonical_claim_target_identity,
)


HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


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
        "params": {},
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

    assert restarted_runtime.reserve_command(retry_command)["ok"] is True
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
