from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from importlib import import_module
from typing import Any, Callable

import pytest

from src import db
from src.batch_edit.scope_contract import canonical_sha256
from src.execution.browser_agent_protocol import (
    BrowserAgentCommand,
    build_frozen_product_target_identity,
    mutation_target_hash,
)
from src.execution.mutation_dispatch_ledger import MutationDispatchLedger
from src.execution.e3_authority_contract import (
    AuthorizationLeaseAuthorityError,
    canonical_authorization_lease_authority,
)

import test_batch_dispatch_authority as authority_support


authority_case = authority_support.authority_case


@dataclass(frozen=True)
class _Inputs:
    command: BrowserAgentCommand
    identity: dict[str, Any]
    live_facts: dict[str, Any]


@dataclass(frozen=True)
class _BoundaryCase:
    boundary: str
    phase: str
    expected_reason: str
    mutate: Callable[[dict[str, Any], _Inputs], _Inputs]
    expect_ok: bool = False


def _base_inputs(case: dict[str, Any]) -> _Inputs:
    return _Inputs(
        command=case["command"],
        identity=deepcopy(case["identity"]),
        live_facts=deepcopy(case["live_facts"]),
    )


def _unchanged(case: dict[str, Any], inputs: _Inputs) -> _Inputs:
    return inputs


def _mutate_payload(
    case: dict[str, Any], mutate: Callable[[dict[str, Any]], None]
) -> None:
    with db.connection() as conn:
        row = conn.execute(
            "SELECT payload_json FROM tasks WHERE id=?",
            (case["task"]["id"],),
        ).fetchone()
        payload = db.loads(row["payload_json"], {})
        mutate(payload)
        conn.execute(
            "UPDATE tasks SET payload_json=? WHERE id=?",
            (db.dumps(payload), case["task"]["id"]),
        )


def _approval_nested_drift(case: dict[str, Any], inputs: _Inputs) -> _Inputs:
    _mutate_payload(
        case,
        lambda payload: payload["manual_approval"]["authorization_context"].update(
            {"approved_by": "matrix-drifted-owner"}
        ),
    )
    return inputs


def _stage_drift(case: dict[str, Any], inputs: _Inputs) -> _Inputs:
    _mutate_payload(
        case,
        lambda payload: payload["manual_approval"]["stage_task_facts"].update(
            {"plan_snapshot_hash": "8" * 64}
        ),
    )
    return inputs


def _expired_lease(case: dict[str, Any], inputs: _Inputs) -> _Inputs:
    _mutate_payload(
        case,
        lambda payload: payload["manual_approval"].update(
            {"expires_at": "2000-01-01T00:00:00+00:00"}
        ),
    )
    return inputs


def _l2_blocked(case: dict[str, Any], inputs: _Inputs) -> _Inputs:
    return replace(
        inputs,
        live_facts={**inputs.live_facts, "l2_status": "blocked"},
    )


def _l2_fingerprint_drift(case: dict[str, Any], inputs: _Inputs) -> _Inputs:
    return replace(
        inputs,
        live_facts={**inputs.live_facts, "l2_evidence_fingerprint": "7" * 64},
    )


def _queue_drift(case: dict[str, Any], inputs: _Inputs) -> _Inputs:
    with db.connection() as conn:
        conn.execute(
            "UPDATE jobs SET status='pending' WHERE id=?",
            (case["job"]["id"],),
        )
    return inputs


def _stored_snapshot_drift(case: dict[str, Any], inputs: _Inputs) -> _Inputs:
    with db.connection() as conn:
        row = conn.execute(
            "SELECT snapshot_json FROM plan_snapshots WHERE id=?",
            (case["snapshot_id"],),
        ).fetchone()
        snapshot = db.loads(row["snapshot_json"], {})
        snapshot["item_snapshots"][0]["categoryId"] = "9999"
        conn.execute(
            "UPDATE plan_snapshots SET snapshot_json=? WHERE id=?",
            (db.dumps(snapshot), case["snapshot_id"]),
        )
    return inputs


def _embedded_resolution_drift(case: dict[str, Any], inputs: _Inputs) -> _Inputs:
    def mutate(payload: dict[str, Any]) -> None:
        payload["plan_snapshot"]["item_snapshots"][0]["resolution_result"][
            "resolved_fields"
        ][0]["resolved_value"] = "999"

    _mutate_payload(case, mutate)
    return inputs


def _embedded_category_drift(case: dict[str, Any], inputs: _Inputs) -> _Inputs:
    _mutate_payload(
        case,
        lambda payload: payload["plan_snapshot"]["item_snapshots"][0].update(
            {"categoryId": "9999"}
        ),
    )
    return inputs


def _embedded_schema_drift(case: dict[str, Any], inputs: _Inputs) -> _Inputs:
    def mutate(payload: dict[str, Any]) -> None:
        payload["plan_snapshot"]["item_snapshots"][0]["category_schema"][
            "normalized_schema"
        ]["properties"]["weight"]["type"] = "number"

    _mutate_payload(case, mutate)
    return inputs


def _execution_payload_drift(case: dict[str, Any], inputs: _Inputs) -> _Inputs:
    params = deepcopy(inputs.command.params)
    execution = params["defaults"]["_frozen_execution_payload"]
    execution["fields"][0]["resolved_value"] = "999"
    execution["payload_hash"] = canonical_sha256(
        {key: value for key, value in execution.items() if key != "payload_hash"}
    )
    params["defaults"]["weight"] = "999"
    params["defaults"]["_frozen_execution_payload_hash"] = execution[
        "payload_hash"
    ]
    return replace(
        inputs,
        command=replace(
            inputs.command,
            params=params,
            execution_payload_hash=execution["payload_hash"],
        ),
    )


def _git_drift(case: dict[str, Any], inputs: _Inputs) -> _Inputs:
    return replace(inputs, live_facts={**inputs.live_facts, "git_head": "9" * 40})


def _worktree_drift(case: dict[str, Any], inputs: _Inputs) -> _Inputs:
    worktree = {
        **inputs.live_facts["worktree_identity"],
        "execution_tree_sha256": authority_support._sha256("matrix-tree-drift"),
    }
    return replace(
        inputs,
        live_facts={**inputs.live_facts, "worktree_identity": worktree},
    )


def _backend_runtime_drift(case: dict[str, Any], inputs: _Inputs) -> _Inputs:
    return replace(
        inputs,
        live_facts={
            **inputs.live_facts,
            "runtime_instance_id": "matrix-backend-runtime-drift",
        },
    )


def _browser_runtime_drift(case: dict[str, Any], inputs: _Inputs) -> _Inputs:
    return replace(
        inputs,
        live_facts={
            **inputs.live_facts,
            "browser_runtime_id": "matrix-browser-runtime-drift",
        },
    )


def _session_drift(case: dict[str, Any], inputs: _Inputs) -> _Inputs:
    return replace(
        inputs,
        live_facts={
            **inputs.live_facts,
            "browser_session_id": "matrix-session-drift",
        },
    )


def _page_url(value: str) -> Callable[[dict[str, Any], _Inputs], _Inputs]:
    def mutate(case: dict[str, Any], inputs: _Inputs) -> _Inputs:
        return replace(inputs, identity={**inputs.identity, "page_url": value})

    return mutate


def _product_query_drift(case: dict[str, Any], inputs: _Inputs) -> _Inputs:
    params = {**inputs.command.params, "product_query": "79999"}
    return replace(inputs, command=replace(inputs.command, params=params))


def _visible_target_drift(case: dict[str, Any], inputs: _Inputs) -> _Inputs:
    return replace(
        inputs,
        identity={**inputs.identity, "target_hash": "A" * 64},
    )


def _rereserve_with_target(
    case: dict[str, Any],
    inputs: _Inputs,
    *,
    store_name: str,
    source_urls: list[str],
) -> _Inputs:
    identity = build_frozen_product_target_identity(
        product_id="70001",
        store_name=store_name,
        source_urls=source_urls,
    )
    params = {
        **inputs.command.params,
        "store_name": store_name,
        "target_source_urls": deepcopy(identity["source_urls"]),
        "target_identity": identity,
    }
    command = replace(
        inputs.command,
        params=params,
        target_hash=mutation_target_hash("save_only", params),
    )
    with db.connection() as conn:
        conn.execute(
            "DELETE FROM mutation_dispatch_ledger WHERE mutation_scope_id=?",
            (inputs.command.mutation_scope_id,),
        )
    assert case["ledger"].reserve_command(command).ok is True
    return replace(inputs, command=command)


def _store_drift(case: dict[str, Any], inputs: _Inputs) -> _Inputs:
    return _rereserve_with_target(
        case,
        inputs,
        store_name="Different Matrix Shop",
        source_urls=["https://detail.1688.com/offer/70001.html"],
    )


def _source_drift(case: dict[str, Any], inputs: _Inputs) -> _Inputs:
    return _rereserve_with_target(
        case,
        inputs,
        store_name=authority_support.STORE_NAME,
        source_urls=["https://detail.1688.com/offer/79999.html"],
    )


_BOUNDARY_CASES = [
    _BoundaryCase("all_authorities", "normal", "OK", _unchanged, expect_ok=True),
    _BoundaryCase(
        "approval.authorization_context.nested",
        "reserve_to_jit",
        "AUTH_COMMAND_AUTHORIZATION_MISMATCH",
        _approval_nested_drift,
    ),
    _BoundaryCase(
        "approval.stage_task_facts",
        "reserve_to_jit",
        "AUTH_STAGE_FACTS_MISMATCH",
        _stage_drift,
    ),
    _BoundaryCase("approval.lease.expiry", "jit_to_begin", "AUTH_LEASE_EXPIRED", _expired_lease),
    _BoundaryCase("l2.status", "jit_to_begin", "AUTH_L2_GATE_NOT_PASSED", _l2_blocked),
    _BoundaryCase(
        "l2.evidence_fingerprint",
        "jit_to_begin",
        "AUTH_L2_EVIDENCE_MISMATCH",
        _l2_fingerprint_drift,
    ),
    _BoundaryCase(
        "queue.serial_head",
        "jit_to_begin",
        "AUTH_COMMAND_QUEUE_STATE_MISMATCH",
        _queue_drift,
    ),
    _BoundaryCase(
        "snapshot.persisted_row",
        "reserve_to_jit",
        "AUTH_SNAPSHOT_ROW_AUTHORITY_MISMATCH",
        _stored_snapshot_drift,
    ),
    _BoundaryCase(
        "snapshot.embedded_resolution",
        "reserve_to_jit",
        "AUTH_SNAPSHOT_ROW_AUTHORITY_MISMATCH",
        _embedded_resolution_drift,
    ),
    _BoundaryCase(
        "snapshot.category_id",
        "reserve_to_jit",
        "AUTH_SNAPSHOT_ROW_AUTHORITY_MISMATCH",
        _embedded_category_drift,
    ),
    _BoundaryCase(
        "snapshot.category_schema",
        "reserve_to_jit",
        "AUTH_SNAPSHOT_ROW_AUTHORITY_MISMATCH",
        _embedded_schema_drift,
    ),
    _BoundaryCase(
        "execution.frozen_payload",
        "jit_to_begin",
        "AUTH_COMMAND_EXECUTION_MISMATCH",
        _execution_payload_drift,
    ),
    _BoundaryCase("code.git_head", "jit_to_begin", "AUTH_GIT_HEAD_MISMATCH", _git_drift),
    _BoundaryCase(
        "code.worktree_identity",
        "jit_to_begin",
        "AUTH_WORKTREE_IDENTITY_MISMATCH",
        _worktree_drift,
    ),
    _BoundaryCase(
        "runtime.backend_instance",
        "jit_to_begin",
        "AUTH_RUNTIME_IDENTITY_MISMATCH",
        _backend_runtime_drift,
    ),
    _BoundaryCase(
        "runtime.browser_instance",
        "jit_to_begin",
        "AUTH_RUNTIME_IDENTITY_MISMATCH",
        _browser_runtime_drift,
    ),
    _BoundaryCase(
        "runtime.browser_session",
        "jit_to_begin",
        "AUTH_BROWSER_SESSION_MISMATCH",
        _session_drift,
    ),
    _BoundaryCase(
        "page.scheme",
        "single",
        "AUTH_BROWSER_PAGE_MISMATCH",
        _page_url("http://www.dianxiaomi.com/web/smt/edit?id=70001"),
    ),
    _BoundaryCase(
        "page.domain",
        "single",
        "AUTH_BROWSER_PAGE_MISMATCH",
        _page_url("https://evil.dianxiaomi.com/web/smt/edit?id=70001"),
    ),
    _BoundaryCase(
        "page.port",
        "single",
        "AUTH_BROWSER_PAGE_MISMATCH",
        _page_url("https://www.dianxiaomi.com:444/web/smt/edit?id=70001"),
    ),
    _BoundaryCase(
        "page.kind",
        "single",
        "AUTH_BROWSER_PAGE_MISMATCH",
        _page_url("https://www.dianxiaomi.com/web/home"),
    ),
    _BoundaryCase(
        "target.product_id",
        "single",
        "AUTH_COMMAND_TARGET_MISMATCH",
        _product_query_drift,
    ),
    _BoundaryCase(
        "target.store",
        "reserve_to_jit",
        "AUTH_COMMAND_TARGET_MISMATCH",
        _store_drift,
    ),
    _BoundaryCase(
        "target.source_url",
        "reserve_to_jit",
        "AUTH_COMMAND_TARGET_MISMATCH",
        _source_drift,
    ),
    _BoundaryCase(
        "target.visible_identity",
        "jit_to_begin",
        "AUTH_COMMAND_TARGET_MISMATCH",
        _visible_target_drift,
    ),
]


@pytest.mark.parametrize(
    "matrix_case",
    [
        pytest.param(item, id=f"{item.phase}-{item.boundary}")
        for item in _BOUNDARY_CASES
    ],
)
def test_real_ledger_begin_dispatch_trust_boundary_matrix(
    authority_case,
    matrix_case: _BoundaryCase,
) -> None:
    inputs = _base_inputs(authority_case)
    if matrix_case.phase == "jit_to_begin":
        assert authority_support._validate(authority_case).ok is True
    inputs = matrix_case.mutate(authority_case, inputs)
    authority_module = import_module("src.execution.batch_dispatch_authority")
    ledger = MutationDispatchLedger(
        recover_inflight=False,
        live_facts_provider=lambda: authority_module.LiveDispatchFacts(
            **inputs.live_facts
        ),
    )

    decision = ledger.begin_dispatch(
        inputs.command,
        "save_only_click",
        inputs.identity,
    )

    assert matrix_case.phase in {
        "normal",
        "single",
        "reserve_to_jit",
        "jit_to_begin",
        "restart",
    }
    assert decision.ok is matrix_case.expect_ok
    assert decision.reason_code == matrix_case.expected_reason
    entry = ledger.get_entry(inputs.command.mutation_scope_id, "save_only_click")
    if matrix_case.expect_ok:
        assert entry["status"] == "DISPATCHING"
        assert entry["save_authority_json"]
        assert entry["save_authority_sha256"]
    else:
        operation_calls: list[str] = []
        if decision.ok:
            operation_calls.append("save_only_click")
        assert operation_calls == []
        assert entry["status"] == "RESERVED"
        assert entry["dispatch_started_at"] is None
        assert entry["save_authority_json"] is None


@pytest.mark.parametrize(
    ("boundary", "phase", "expected_reason"),
    [
        pytest.param(
            "snapshot.embedded_resolution_result",
            "restart",
            "AUTH_CURRENT_TASK_DRIFT",
            id="restart-rejects-embedded-resolution-drift",
        ),
    ],
)
def test_restart_rejects_embedded_snapshot_input_drift(
    authority_case,
    boundary: str,
    phase: str,
    expected_reason: str,
) -> None:
    authority_module = import_module("src.execution.batch_dispatch_authority")
    trusted = authority_module.LiveDispatchFacts(**authority_case["live_facts"])
    with db.connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        frozen = authority_module.validate_in_transaction(
            conn,
            authority_case["command"],
            authority_case["identity"],
            trusted,
        )
    assert frozen.ok is True

    with db.connection() as conn:
        row = conn.execute(
            "SELECT payload_json FROM tasks WHERE id=?",
            (authority_case["task"]["id"],),
        ).fetchone()
        payload = db.loads(row["payload_json"], {})
        assert payload["plan_snapshot_hash"] == frozen.authority["snapshot"][
            "plan_snapshot_hash"
        ]
        payload["plan_snapshot"]["item_snapshots"][0]["resolution_result"][
            "resolved_fields"
        ][0]["resolved_value"] = "999"
        conn.execute(
            "UPDATE tasks SET payload_json=? WHERE id=?",
            (db.dumps(payload), authority_case["task"]["id"]),
        )

    operation_calls: list[str] = []
    with db.connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        decision = authority_module.validate_current_task_against_frozen_authority(
            conn,
            frozen.authority,
        )
    if decision.ok:
        operation_calls.append("save_only_click")

    assert boundary == "snapshot.embedded_resolution_result"
    assert phase == "restart"
    assert decision.ok is False
    assert decision.reason_code == expected_reason
    assert operation_calls == []
    entry = authority_case["ledger"].get_entry(
        authority_case["command"].mutation_scope_id,
        "save_only_click",
    )
    assert entry["status"] == "RESERVED"
    assert entry["dispatch_started_at"] is None


@pytest.mark.parametrize(
    ("boundary", "replacement"),
    [
        pytest.param(
            "approval.lease.issued_at",
            "1999-01-01T00:00:00+00:00",
            id="issued-at",
        ),
        pytest.param(
            "approval.lease.expires_at",
            "2099-01-01T00:00:00+00:00",
            id="expires-at-extended",
        ),
        pytest.param(
            "approval.lease.consumed_at",
            "2098-01-01T00:00:00+00:00",
            id="consumed-at",
        ),
        pytest.param(
            "approval.lease.token_hash",
            "D" * 64,
            id="token-hash",
        ),
        pytest.param(
            "approval.lease.confirmation",
            "FORGED_CONFIRMATION",
            id="confirmation",
        ),
    ],
)
def test_jit_to_begin_rejects_lease_timestamp_authority_drift(
    authority_case,
    boundary: str,
    replacement: str,
) -> None:
    assert authority_support._validate(authority_case).ok is True
    field = boundary.rsplit(".", 1)[-1]
    _mutate_payload(
        authority_case,
        lambda payload: payload["manual_approval"].update({field: replacement}),
    )
    authority_module = import_module("src.execution.batch_dispatch_authority")
    ledger = MutationDispatchLedger(
        recover_inflight=False,
        live_facts_provider=lambda: authority_module.LiveDispatchFacts(
            **authority_case["live_facts"]
        ),
    )

    decision = ledger.begin_dispatch(
        authority_case["command"],
        "save_only_click",
        authority_case["identity"],
    )

    assert decision.ok is False
    assert decision.reason_code == "AUTH_LEASE_AUTHORITY_MISMATCH"
    entry = ledger.get_entry(
        authority_case["command"].mutation_scope_id,
        "save_only_click",
    )
    assert entry["status"] == "RESERVED"
    assert entry["dispatch_started_at"] is None


@pytest.mark.parametrize(
    ("boundary", "sql", "params"),
    [
        pytest.param(
            "snapshot.row.task_id",
            "UPDATE plan_snapshots SET task_id=NULL WHERE id=?",
            (),
            id="row-task-id",
        ),
        pytest.param(
            "snapshot.row.snapshot_hash",
            "UPDATE plan_snapshots SET snapshot_hash=? WHERE id=?",
            ("C" * 64,),
            id="row-snapshot-hash",
        ),
        pytest.param(
            "snapshot.row.local_plan_template_id",
            "UPDATE plan_snapshots SET local_plan_template_id=999 WHERE id=?",
            (),
            id="row-local-plan-template",
        ),
        pytest.param(
            "snapshot.row.idempotency_key",
            "UPDATE plan_snapshots SET idempotency_key='forged-key' WHERE id=?",
            (),
            id="row-idempotency-key",
        ),
        pytest.param(
            "snapshot.row.created_at",
            "UPDATE plan_snapshots SET created_at='1999-01-01T00:00:00Z' WHERE id=?",
            (),
            id="row-created-at",
        ),
    ],
)
def test_restart_rejects_plan_snapshot_row_binding_drift(
    authority_case,
    boundary: str,
    sql: str,
    params: tuple[Any, ...],
) -> None:
    authority_module = import_module("src.execution.batch_dispatch_authority")
    trusted = authority_module.LiveDispatchFacts(**authority_case["live_facts"])
    with db.connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        frozen = authority_module.validate_in_transaction(
            conn,
            authority_case["command"],
            authority_case["identity"],
            trusted,
        )
    assert frozen.ok is True
    with db.connection() as conn:
        conn.execute(sql, (*params, authority_case["snapshot_id"]))

    with db.connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        decision = authority_module.validate_current_task_against_frozen_authority(
            conn,
            frozen.authority,
        )

    assert boundary in {
        "snapshot.row.task_id",
        "snapshot.row.snapshot_hash",
        "snapshot.row.local_plan_template_id",
        "snapshot.row.idempotency_key",
        "snapshot.row.created_at",
    }
    assert decision.ok is False
    assert decision.reason_code == "AUTH_CURRENT_TASK_DRIFT"
    entry = authority_case["ledger"].get_entry(
        authority_case["command"].mutation_scope_id,
        "save_only_click",
    )
    assert entry["status"] == "RESERVED"
    assert entry["dispatch_started_at"] is None


def test_restart_rejects_deleted_snapshot_idempotency_provenance(
    authority_case,
) -> None:
    authority_module = import_module("src.execution.batch_dispatch_authority")
    trusted = authority_module.LiveDispatchFacts(**authority_case["live_facts"])
    with db.connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        frozen = authority_module.validate_in_transaction(
            conn,
            authority_case["command"],
            authority_case["identity"],
            trusted,
        )
    assert frozen.ok is True
    key = frozen.authority["snapshot"]["row_binding"]["idempotency_key"]
    with db.connection() as conn:
        conn.execute(
            "DELETE FROM plan_snapshot_idempotency_keys WHERE idempotency_key=?",
            (key,),
        )

    with db.connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        decision = authority_module.validate_current_task_against_frozen_authority(
            conn,
            frozen.authority,
        )

    assert decision.ok is False
    assert decision.reason_code == "AUTH_CURRENT_TASK_DRIFT"


@pytest.mark.parametrize(
    ("boundary", "mutate"),
    [
        pytest.param(
            "approval.approved_at_after_expiry",
            lambda approval: approval.update(
                {"approved_at": "2099-01-01T00:00:00+00:00"}
            ),
            id="approved-at-after-expiry",
        ),
        pytest.param(
            "approval.confirmation_wrong_before_command",
            lambda approval: approval.update({"confirmation": "CONFIRM_PUBLISH"}),
            id="wrong-path-a-confirmation",
        ),
        pytest.param(
            "approval.approved_by_context_mismatch",
            lambda approval: approval.update({"approved_by": "forged-operator"}),
            id="outer-approved-by-mismatch",
        ),
    ],
)
def test_pre_command_polluted_lease_authority_is_not_canonicalizable(
    authority_case,
    boundary: str,
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    approval = deepcopy(
        authority_case["task"]["payload"]["manual_approval"]
    )
    mutate(approval)

    with pytest.raises(AuthorizationLeaseAuthorityError):
        canonical_authorization_lease_authority(approval)

    assert boundary.startswith("approval.")


def test_final_cas_rechecks_clock_after_authority_provider(
    authority_case,
    monkeypatch,
) -> None:
    ledger_module = import_module("src.execution.mutation_dispatch_ledger")
    expiry = authority_case["task"]["payload"]["manual_approval"]["expires_at"]
    expiry_dt = authority_support.datetime.fromisoformat(expiry)
    clock_values = iter(
        [
            (expiry_dt - authority_support.timedelta(microseconds=1)).isoformat(),
            expiry_dt.isoformat(),
        ]
    )
    calls: list[str] = []

    def clock() -> str:
        value = next(clock_values)
        calls.append(value)
        return value

    monkeypatch.setattr(ledger_module, "utc_now_iso", clock)
    authority_module = import_module("src.execution.batch_dispatch_authority")
    ledger = MutationDispatchLedger(
        recover_inflight=False,
        live_facts_provider=lambda: authority_module.LiveDispatchFacts(
            **authority_case["live_facts"]
        ),
    )

    decision = ledger.begin_dispatch(
        authority_case["command"],
        "save_only_click",
        authority_case["identity"],
    )

    assert len(calls) == 2
    assert decision.ok is False
    assert decision.reason_code == "AUTH_LEASE_EXPIRED"
    entry = ledger.get_entry(
        authority_case["command"].mutation_scope_id,
        "save_only_click",
    )
    assert entry["status"] == "RESERVED"
    assert entry["dispatch_started_at"] is None


@pytest.mark.parametrize(
    ("boundary", "sql"),
    [
        pytest.param(
            "queue.current_product_id",
            "UPDATE jobs SET product_id=79999 WHERE id=?",
            id="current-product-id",
        ),
        pytest.param(
            "queue.current_status",
            "UPDATE jobs SET status='pending' WHERE id=?",
            id="current-status",
        ),
    ],
)
def test_restart_rejects_current_queue_drift(
    authority_case,
    boundary: str,
    sql: str,
) -> None:
    authority_module = import_module("src.execution.batch_dispatch_authority")
    trusted = authority_module.LiveDispatchFacts(**authority_case["live_facts"])
    with db.connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        frozen = authority_module.validate_in_transaction(
            conn,
            authority_case["command"],
            authority_case["identity"],
            trusted,
        )
    assert frozen.ok is True
    with db.connection() as conn:
        conn.execute(sql, (authority_case["job"]["id"],))

    with db.connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        decision = authority_module.validate_current_task_against_frozen_authority(
            conn,
            frozen.authority,
        )

    assert boundary in {"queue.current_product_id", "queue.current_status"}
    assert decision.ok is False
    assert decision.reason_code == "AUTH_CURRENT_QUEUE_DRIFT"


@pytest.mark.parametrize(
    ("boundary", "sql"),
    [
        pytest.param(
            "snapshot.reserve_to_begin.local_plan_template_id",
            "UPDATE plan_snapshots SET local_plan_template_id=999 WHERE id=?",
            id="local-plan-template-id",
        ),
        pytest.param(
            "snapshot.reserve_to_begin.idempotency_key",
            "UPDATE plan_snapshots SET idempotency_key='forged-after-reserve' WHERE id=?",
            id="idempotency-key",
        ),
        pytest.param(
            "snapshot.reserve_to_begin.created_at",
            "UPDATE plan_snapshots SET created_at='1999-01-01T00:00:00Z' WHERE id=?",
            id="created-at",
        ),
    ],
)
def test_reserve_to_begin_rejects_snapshot_row_authority_drift(
    authority_case,
    boundary: str,
    sql: str,
) -> None:
    with db.connection() as conn:
        conn.execute(sql, (authority_case["snapshot_id"],))
    authority_module = import_module("src.execution.batch_dispatch_authority")
    ledger = MutationDispatchLedger(
        recover_inflight=False,
        live_facts_provider=lambda: authority_module.LiveDispatchFacts(
            **authority_case["live_facts"]
        ),
    )

    decision = ledger.begin_dispatch(
        authority_case["command"],
        "save_only_click",
        authority_case["identity"],
    )

    assert boundary.startswith("snapshot.reserve_to_begin.")
    assert decision.ok is False
    assert decision.reason_code == "AUTH_SNAPSHOT_ROW_AUTHORITY_MISMATCH"
    entry = ledger.get_entry(
        authority_case["command"].mutation_scope_id,
        "save_only_click",
    )
    assert entry["status"] == "RESERVED"
    assert entry["dispatch_started_at"] is None


def test_reserve_to_begin_rejects_deleted_snapshot_idempotency_provenance(
    authority_case,
) -> None:
    with db.connection() as conn:
        row = conn.execute(
            "SELECT idempotency_key FROM plan_snapshots WHERE id=?",
            (authority_case["snapshot_id"],),
        ).fetchone()
        assert row is not None
        conn.execute(
            "DELETE FROM plan_snapshot_idempotency_keys WHERE idempotency_key=?",
            (row["idempotency_key"],),
        )
    authority_module = import_module("src.execution.batch_dispatch_authority")
    ledger = MutationDispatchLedger(
        recover_inflight=False,
        live_facts_provider=lambda: authority_module.LiveDispatchFacts(
            **authority_case["live_facts"]
        ),
    )

    decision = ledger.begin_dispatch(
        authority_case["command"],
        "save_only_click",
        authority_case["identity"],
    )

    assert decision.ok is False
    assert decision.reason_code == "AUTH_SNAPSHOT_ROW_AUTHORITY_MISMATCH"
    entry = ledger.get_entry(
        authority_case["command"].mutation_scope_id,
        "save_only_click",
    )
    assert entry["status"] == "RESERVED"
    assert entry["dispatch_started_at"] is None
