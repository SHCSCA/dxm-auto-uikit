from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from importlib import import_module
from typing import Any

import pytest

from src import db
from src.execution.browser_agent_protocol import (
    build_frozen_product_target_identity,
    mutation_target_hash,
)
from src.execution.browser_agent_worker import BrowserAgentRuntime
from src.execution.mutation_dispatch_ledger import MutationDispatchLedger

import test_batch_dispatch_authority as authority_support


authority_case = authority_support.authority_case


class _AccountBoundAdapter:
    def refresh_account_context_hash(self) -> str:
        return "A" * 64


def _runtime_reservation(
    case: dict[str, Any],
) -> tuple[BrowserAgentRuntime, MutationDispatchLedger, Any, dict[str, Any]]:
    live_facts = deepcopy(case["live_facts"])
    authority_module = import_module("src.execution.batch_dispatch_authority")
    ledger = MutationDispatchLedger(
        recover_inflight=False,
        live_facts_provider=lambda: authority_module.LiveDispatchFacts(**live_facts),
    )
    runtime = BrowserAgentRuntime(_AccountBoundAdapter(), mutation_ledger=ledger)
    live_facts["browser_runtime_id"] = runtime.runtime_id
    command = replace(
        case["command"],
        command_id=f"{case['command'].command_id}-runtime",
        runtime_id=runtime.runtime_id,
    )
    reserved = runtime.reserve_command(command)
    assert reserved["ok"] is True
    return runtime, ledger, command, live_facts


def _jit(
    case: dict[str, Any],
    command: Any,
    identity: dict[str, Any],
    live_facts: dict[str, Any],
):
    authority_module = import_module("src.execution.batch_dispatch_authority")
    with db.connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        return authority_module.validate_in_transaction(
            conn,
            command,
            identity,
            authority_module.LiveDispatchFacts(**live_facts),
        )


def _assert_reserved_zero_operation(
    ledger: MutationDispatchLedger,
    command: Any,
    decision: Any,
    expected_reason: str,
    operation_calls: list[str],
) -> None:
    assert decision.ok is False
    assert decision.reason_code == expected_reason
    assert operation_calls == []
    entry = ledger.get_entry(command.mutation_scope_id, "save_only_click")
    assert entry["status"] == "RESERVED"
    assert entry["dispatch_started_at"] is None
    assert entry["save_authority_json"] is None


def test_jit_to_begin_rejects_editor_url_product_identity_drift(
    authority_case,
) -> None:
    runtime, ledger, command, live_facts = _runtime_reservation(authority_case)
    operation_calls: list[str] = []
    try:
        assert _jit(
            authority_case,
            command,
            deepcopy(authority_case["identity"]),
            live_facts,
        ).ok is True
        drifted_identity = {
            **authority_case["identity"],
            "page_url": "https://www.dianxiaomi.com/web/smt/edit?id=79999",
        }

        decision = ledger.begin_dispatch(
            command,
            "save_only_click",
            drifted_identity,
        )

        _assert_reserved_zero_operation(
            ledger,
            command,
            decision,
            "AUTH_COMMAND_TARGET_MISMATCH",
            operation_calls,
        )
    finally:
        runtime.shutdown(timeout_seconds=1)


@pytest.mark.parametrize(
    ("boundary", "identity_patch"),
    [
        pytest.param(
            "page.scheme",
            {"page_url": "http://www.dianxiaomi.com/web/smt/edit?id=70001"},
            id="scheme",
        ),
        pytest.param(
            "page.domain",
            {"page_url": "https://evil.dianxiaomi.com/web/smt/edit?id=70001"},
            id="domain",
        ),
        pytest.param(
            "page.port",
            {"page_url": "https://www.dianxiaomi.com:444/web/smt/edit?id=70001"},
            id="port",
        ),
        pytest.param(
            "page.kind",
            {"page_kind": "draft_box"},
            id="kind",
        ),
    ],
)
def test_jit_to_begin_rechecks_exact_page_identity(
    authority_case,
    boundary: str,
    identity_patch: dict[str, Any],
) -> None:
    runtime, ledger, command, live_facts = _runtime_reservation(authority_case)
    operation_calls: list[str] = []
    try:
        assert _jit(
            authority_case,
            command,
            deepcopy(authority_case["identity"]),
            live_facts,
        ).ok is True
        drifted_identity = {**authority_case["identity"], **identity_patch}

        decision = ledger.begin_dispatch(
            command,
            "save_only_click",
            drifted_identity,
        )

        assert boundary in {"page.scheme", "page.domain", "page.port", "page.kind"}
        _assert_reserved_zero_operation(
            ledger,
            command,
            decision,
            "AUTH_BROWSER_PAGE_MISMATCH",
            operation_calls,
        )
    finally:
        runtime.shutdown(timeout_seconds=1)


def test_reservation_does_not_freeze_page_and_begin_always_rechecks_it(
    authority_case,
) -> None:
    """Page identity is unavailable at reserve time; BEGIN is the fail-closed gate."""

    runtime, ledger, command, live_facts = _runtime_reservation(authority_case)
    operation_calls: list[str] = []
    try:
        reserved_entry = ledger.get_entry(command.mutation_scope_id, "save_only_click")
        assert reserved_entry["status"] == "RESERVED"
        assert reserved_entry["page_url"] is None
        assert reserved_entry["page_kind"] is None
        assert _jit(
            authority_case,
            command,
            deepcopy(authority_case["identity"]),
            live_facts,
        ).ok is True

        decision = ledger.begin_dispatch(
            command,
            "save_only_click",
            {
                **authority_case["identity"],
                "page_url": "https://www.dianxiaomi.com/web/home",
                "page_kind": "authenticated_dxm",
            },
        )

        _assert_reserved_zero_operation(
            ledger,
            command,
            decision,
            "AUTH_BROWSER_PAGE_MISMATCH",
            operation_calls,
        )
    finally:
        runtime.shutdown(timeout_seconds=1)


@pytest.mark.parametrize(
    ("boundary", "identity_patch"),
    [
        pytest.param(
            "page.scheme",
            {"page_url": "http://www.dianxiaomi.com/web/smt/edit?id=70001"},
            id="restart-scheme",
        ),
        pytest.param(
            "page.domain",
            {"page_url": "https://evil.dianxiaomi.com/web/smt/edit?id=70001"},
            id="restart-domain",
        ),
        pytest.param(
            "page.port",
            {"page_url": "https://www.dianxiaomi.com:444/web/smt/edit?id=70001"},
            id="restart-port",
        ),
        pytest.param(
            "page.kind",
            {"page_kind": "draft_box"},
            id="restart-kind",
        ),
    ],
)
def test_restart_reacquires_and_rejects_invalid_page_identity(
    authority_case,
    boundary: str,
    identity_patch: dict[str, Any],
) -> None:
    first_runtime, _first_ledger, _first_command, _first_live = _runtime_reservation(
        authority_case
    )
    assert first_runtime.shutdown(timeout_seconds=1)["ok"] is True

    restarted_runtime, restarted_ledger, restarted_command, _live_facts = (
        _runtime_reservation(authority_case)
    )
    operation_calls: list[str] = []
    try:
        reacquired_identity = {**authority_case["identity"], **identity_patch}

        decision = restarted_ledger.begin_dispatch(
            restarted_command,
            "save_only_click",
            reacquired_identity,
        )

        assert boundary in {"page.scheme", "page.domain", "page.port", "page.kind"}
        _assert_reserved_zero_operation(
            restarted_ledger,
            restarted_command,
            decision,
            "AUTH_BROWSER_PAGE_MISMATCH",
            operation_calls,
        )
    finally:
        restarted_runtime.shutdown(timeout_seconds=1)


def _self_consistent_target_drift(command: Any, boundary: str) -> Any:
    params = deepcopy(command.params)
    if boundary == "target.product_query":
        # product_query is display/search text and intentionally excluded from
        # target_hash; BEGIN must still compare it with the frozen item.
        params["product_query"] = "79999"
    else:
        product_id = "79999" if boundary == "target.identity" else "70001"
        store_name = (
            "Restarted Different Shop"
            if boundary == "target.store"
            else authority_support.STORE_NAME
        )
        source_urls = [
            (
                "https://detail.1688.com/offer/79999.html"
                if boundary in {"target.source", "target.identity"}
                else "https://detail.1688.com/offer/70001.html"
            )
        ]
        target_identity = build_frozen_product_target_identity(
            product_id=product_id,
            store_name=store_name,
            source_urls=source_urls,
        )
        params.update(
            {
                "product_query": product_id,
                "store_name": store_name,
                "target_source_urls": deepcopy(target_identity["source_urls"]),
                "target_identity": target_identity,
            }
        )
    return replace(
        command,
        target_hash=mutation_target_hash(command.action, params),
        params=params,
    )


@pytest.mark.parametrize(
    ("boundary", "expected_reason"),
    [
        pytest.param(
            "target.product_query",
            "AUTH_COMMAND_TARGET_MISMATCH",
            id="restart-product",
        ),
        pytest.param(
            "target.store",
            "MUTATION_SCOPE_BINDING_MISMATCH",
            id="restart-store",
        ),
        pytest.param(
            "target.source",
            "MUTATION_SCOPE_BINDING_MISMATCH",
            id="restart-source",
        ),
        pytest.param(
            "target.identity",
            "MUTATION_SCOPE_BINDING_MISMATCH",
            id="restart-target-identity",
        ),
    ],
)
def test_restart_rejects_self_consistent_target_drift(
    authority_case,
    boundary: str,
    expected_reason: str,
) -> None:
    first_runtime, _first_ledger, _first_command, _first_live = _runtime_reservation(
        authority_case
    )
    assert first_runtime.shutdown(timeout_seconds=1)["ok"] is True

    authority_module = import_module("src.execution.batch_dispatch_authority")
    restarted_live = deepcopy(authority_case["live_facts"])
    restarted_ledger = MutationDispatchLedger(
        recover_inflight=False,
        live_facts_provider=lambda: authority_module.LiveDispatchFacts(**restarted_live),
    )
    restarted_runtime = BrowserAgentRuntime(
        _AccountBoundAdapter(),
        mutation_ledger=restarted_ledger,
    )
    restarted_live["browser_runtime_id"] = restarted_runtime.runtime_id
    restarted_command = replace(
        authority_case["command"],
        command_id=f"{authority_case['command'].command_id}-restart-{boundary}",
        runtime_id=restarted_runtime.runtime_id,
    )
    drifted_command = _self_consistent_target_drift(restarted_command, boundary)
    operation_calls: list[str] = []
    try:
        drifted_identity = {
            **authority_case["identity"],
            "target_hash": drifted_command.target_hash,
        }

        decision = restarted_ledger.begin_dispatch(
            drifted_command,
            "save_only_click",
            drifted_identity,
        )

        _assert_reserved_zero_operation(
            restarted_ledger,
            authority_case["command"],
            decision,
            expected_reason,
            operation_calls,
        )
    finally:
        restarted_runtime.shutdown(timeout_seconds=1)
