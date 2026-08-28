from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import pytest

from src.execution.action_result_contract import (
    ActionResultContractError,
    validate_action_result_envelope,
)
from src.execution.batch_dispatch_authority import LiveDispatchFacts
from src.execution.browser_agent_protocol import (
    build_frozen_product_target_identity,
    mutation_target_hash,
)
from src.execution.mutation_dispatch_ledger import MutationDispatchLedger
from tests.test_batch_dispatch_authority import authority_case
from tests.test_e3_dispatch_authority import _verify_command_for_result
from tests.test_action_result_contract import (
    _as_path_a_editor,
    _path_a_execution_payload,
    _valid_save_result,
)


STORE_NAME = "Dispatch Authority Shop"


def _target(
    product_id: str,
    *,
    store_name: str = STORE_NAME,
    source_url: str | None = None,
) -> dict:
    return build_frozen_product_target_identity(
        product_id=product_id,
        store_name=store_name,
        source_urls=[
            source_url or f"https://detail.1688.com/offer/{product_id}.html"
        ],
    )


def _target_hash(target: dict) -> str:
    return mutation_target_hash(
        "save_only",
        {
            "store_name": STORE_NAME,
            "target_identity": target,
            "target_source_urls": target["source_urls"],
        },
    )


def _self_consistent_result_for(
    target: dict,
    *,
    store_name: str = STORE_NAME,
) -> dict:
    result = _as_path_a_editor(_valid_save_result(), _path_a_execution_payload())
    digest = hashlib.sha256(
        json.dumps(
            target,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
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
        pre_dispatch["identity"]["target_identity_sha256"] = digest
        pre_dispatch["identity"]["expected_store_name"] = store_name
    return result


def test_save_result_accepts_exact_frozen_target_binding() -> None:
    frozen_target = _target("70001")
    result = _self_consistent_result_for(frozen_target)

    validated = validate_action_result_envelope(
        result,
        expected_state="SAVE_ONLY",
        expected_action="save_only",
        expected_page="editor",
        execution_mode="batch_draft_save",
        expected_execution_payload=_path_a_execution_payload(),
        expected_target_identity=frozen_target,
        expected_store_name=STORE_NAME,
        expected_target_hash=_target_hash(frozen_target),
    )

    assert validated["ok"] is True


def test_save_result_rejects_self_consistent_wrong_product_target() -> None:
    frozen_target = _target("70001")
    wrong_target = _target("79999")
    result = _self_consistent_result_for(wrong_target)

    with pytest.raises(ActionResultContractError):
        validate_action_result_envelope(
            result,
            expected_state="SAVE_ONLY",
            expected_action="save_only",
            expected_page="editor",
            execution_mode="batch_draft_save",
            expected_execution_payload=_path_a_execution_payload(),
            expected_target_identity=frozen_target,
            expected_store_name=STORE_NAME,
            expected_target_hash=_target_hash(frozen_target),
        )


def test_save_result_rejects_self_consistent_wrong_store_target() -> None:
    frozen_target = _target("70001")
    wrong_store = "Other Shop"
    wrong_target = _target("70001", store_name=wrong_store)
    result = _self_consistent_result_for(wrong_target, store_name=wrong_store)

    with pytest.raises(ActionResultContractError):
        validate_action_result_envelope(
            result,
            expected_state="SAVE_ONLY",
            expected_action="save_only",
            expected_page="editor",
            execution_mode="batch_draft_save",
            expected_execution_payload=_path_a_execution_payload(),
            expected_target_identity=frozen_target,
            expected_store_name=STORE_NAME,
            expected_target_hash=_target_hash(frozen_target),
        )


def test_save_result_rejects_self_consistent_wrong_source_target() -> None:
    frozen_target = _target("70001")
    wrong_target = _target(
        "70001",
        source_url="https://detail.1688.com/offer/79999.html",
    )
    result = _self_consistent_result_for(wrong_target)

    with pytest.raises(ActionResultContractError):
        validate_action_result_envelope(
            result,
            expected_state="SAVE_ONLY",
            expected_action="save_only",
            expected_page="editor",
            execution_mode="batch_draft_save",
            expected_execution_payload=_path_a_execution_payload(),
            expected_target_identity=frozen_target,
            expected_store_name=STORE_NAME,
            expected_target_hash=_target_hash(frozen_target),
        )


def test_save_result_rejects_wrong_frozen_target_hash() -> None:
    frozen_target = _target("70001")
    result = _self_consistent_result_for(frozen_target)

    with pytest.raises(ActionResultContractError):
        validate_action_result_envelope(
            result,
            expected_state="SAVE_ONLY",
            expected_action="save_only",
            expected_page="editor",
            execution_mode="batch_draft_save",
            expected_execution_payload=_path_a_execution_payload(),
            expected_target_identity=frozen_target,
            expected_store_name=STORE_NAME,
            expected_target_hash="F" * 64,
        )


def test_ledger_rejects_wrong_target_result_and_restart_verify_fail_closed(
    authority_case,
) -> None:
    command = authority_case["command"]
    live_facts = LiveDispatchFacts(**authority_case["live_facts"])
    ledger = MutationDispatchLedger(
        recover_inflight=False,
        live_facts_provider=lambda: live_facts,
    )
    assert ledger.begin_dispatch(
        command,
        "save_only_click",
        authority_case["identity"],
    ).ok is True
    assert ledger.mark_dispatched(
        command,
        "save_only_click",
        {"dispatched": True, "external_write": False},
    ).ok is True
    wrong_result = _self_consistent_result_for(_target("79999"))
    wrong_result["page_identity"]["runtime_id"] = command.runtime_id
    wrong_result["page_identity"]["browser_session_id"] = authority_case[
        "live_facts"
    ]["browser_session_id"]

    rejected = ledger.record_success(command, wrong_result)

    assert rejected.ok is False
    entry = ledger.get_entry(command.mutation_scope_id, "save_only_click")
    assert entry["status"] == "DISPATCHED"
    assert entry["save_action_result_sha256"] is None

    restarted = MutationDispatchLedger(
        live_facts_provider=lambda: live_facts,
    )
    entry = restarted.get_entry(command.mutation_scope_id, "save_only_click")
    assert entry["status"] == "UNKNOWN"
    verify = _verify_command_for_result(command, wrong_result)
    decision = restarted.reserve_command(verify)
    assert decision.ok is False
