from __future__ import annotations

import hashlib
import json
from copy import deepcopy

import pytest

from src.execution.action_result_contract import (
    ACTION_RESULT_CONTRACTS,
    ActionResultContractError,
    validate_independent_save_verification_pair,
    validate_action_result_envelope,
)


_PAGE_URLS = {
    "authenticated_dxm": "https://www.dianxiaomi.com/web/index.htm",
    "draft_box": "https://www.dianxiaomi.com/web/smt/smtProductList/draft",
    "editor": "https://www.dianxiaomi.com/web/smt/edit",
    "semi_managed": "https://www.dianxiaomi.com/web/smt/editFromSmt",
}
_SAVE_URL = "https://www.dianxiaomi.com/api/popChoiceProduct/add.json"
_TARGET_IDENTITY = {
    "product_id": "product-1",
    "store_id": "store-1",
    "source_url": "https://www.dianxiaomi.com/web/smt/edit/1",
}
_STORE_NAME = "store-1"


def _canonical_sha256(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _valid_navigation_result() -> dict:
    return {
        "schema_version": "dxm.action-result.v1",
        "ok": True,
        "action": "open_draft_box",
        "attempted_state": "OPEN_DRAFT_LIST",
        "before_values": {"page_url": "https://www.dianxiaomi.com/web/product/index.htm"},
        "after_values": {"page_url": _PAGE_URLS["draft_box"]},
        "postconditions": {
            "expected_page": True,
            "business_marker_present": True,
            "loading_absent": True,
            "blocking_modal_absent": True,
        },
        "evidence": {
            "observations": {"business_marker": "速卖通商品箱"},
            "refs": [],
        },
        "page_identity": {
            "kind": "draft_box",
            "url": _PAGE_URLS["draft_box"],
            "runtime_id": "runtime-1",
            "browser_session_id": "browser-session-1",
        },
        "failure_code": None,
        "recoverability": {
            "kind": "none",
            "retryable": False,
            "requires_page_reverify": False,
            "reason": None,
        },
    }


def _immutable_ref(
    kind: str = "screenshot",
    *,
    path: str = "D:/evidence/proof.png",
    sha256: str = "A" * 64,
    captured_at: str = "2026-07-15T08:00:00+08:00",
) -> dict:
    return {
        "path": path,
        "sha256": sha256,
        "size": 128,
        "kind": kind,
        "captured_at": captured_at,
    }


def _valid_save_result() -> dict:
    value = _valid_navigation_result()
    target_identity = deepcopy(_TARGET_IDENTITY)
    target_digest = _canonical_sha256(target_identity)
    integrity = {
        "ok": True,
        "kind": "structured_nonempty_form_state",
        "field_count": 12,
        "nonempty_field_count": 12,
        "sha256": "C" * 64,
    }
    authorization = {
        "ok": True,
        "executed": True,
        "mutation_action": "save_only_click",
        "mutation_status": "DISPATCHED",
        "mutation_id": "mutation-1",
    }
    pre_dispatch = {
        "ok": True,
        "required_readback_complete": True,
        "write_attempted": False,
        "phase": "before_ledger_begin_dispatch",
        "exact_save_target": {
            "ok": True,
            "text": "保存",
            "exact_save_count": 1,
        },
        "identity": {
            "ok": True,
            "product_identity_match": True,
            "store_identity_match": True,
            "source_identity_match": True,
            "target_identity": target_identity,
            "target_identity_sha256": target_digest,
            "expected_store_name": _STORE_NAME,
        },
        "baseline_field_integrity": integrity,
        "current_field_integrity": dict(integrity),
    }
    network = {
        "ok": True,
        "receipt_complete": True,
        "receipt_count": 1,
        "method": "POST",
        "url": _SAVE_URL,
        "status": 200,
        "code": 0,
        "msg": "您的产品编辑保存成功！",
    }
    network_audit = {
        "scope": "same_origin_write_window",
        "complete": True,
        "window_closed": True,
        "registered_listener_count": 2,
        "removed_listener_count": 2,
        "mutation_request_count": 1,
        "save_request_count": 1,
        "other_mutation_request_count": 0,
        "publish_request_count": 0,
    }
    publish_signal = {
        "detected": False,
        "kind": "network_route_classification",
        "request_count": 0,
    }
    page_save_result = {
        "ok": True,
        "success_text": "保存成功",
        "status_transition": {
            "kind": "new_or_changed_structured_save_status",
            "entry": {"text": "保存成功", "kind": "toast"},
        },
    }
    save_result = {
        "ok": True,
        "published": False,
        "exact_save_target": True,
        "save_click_dispatched": True,
        "clicked": True,
        "publish_action_clicked": False,
        "text": "保存",
        "exact_save_count": 1,
        "click_method": "native_exact_save",
        "network_save_success": True,
        "page_save_success": True,
        "mutation_authorization": authorization,
        "pre_dispatch_readback": pre_dispatch,
        "network_save_result": network,
        "network_audit": network_audit,
        "publish_signal": publish_signal,
        "page_save_result": page_save_result,
        "save_decision": {
            "ok": True,
            "rule": "page_success_and_network_success",
            "page_ok": True,
            "network_ok": True,
            "network_receipt_ok": True,
            "network_audit_ok": True,
        },
    }
    value.update(
        {
            "action": "save_only",
            "attempted_state": "SAVE_ONLY",
            "before_values": {
                "target_identity": target_identity,
                "store_name": _STORE_NAME,
            },
            "after_values": {
                "exact_save_target": True,
                "save_click_dispatched": True,
                "published": False,
                "mutation_authorization": authorization,
                "pre_dispatch_readback": pre_dispatch,
                "network_save_result": network,
                "network_audit": network_audit,
                "publish_signal": publish_signal,
                "page_save_result": page_save_result,
            },
            "postconditions": {
                "mutation_authorized": True,
                "exact_save_target": True,
                "save_click_dispatched": True,
                "network_save_success": True,
                "page_save_success": True,
                "published_false": True,
                "publish_action_not_clicked": True,
            },
            "evidence": {
                "observations": {
                    "save_result": save_result,
                    "exact_save_target": {
                        "text": "保存",
                        "exact_save_count": 1,
                        "click_method": save_result["click_method"],
                    },
                    "save_click_dispatched": True,
                    "mutation_authorization": authorization,
                    "pre_dispatch_readback": pre_dispatch,
                    "network_save_result": network,
                    "network_audit": network_audit,
                    "publish_signal": publish_signal,
                    "page_save_result": page_save_result,
                },
                "refs": [_immutable_ref("save_screenshot")],
            },
            "page_identity": {
                "kind": "semi_managed",
                "url": _PAGE_URLS["semi_managed"],
                "runtime_id": "runtime-1",
                "browser_session_id": "browser-session-1",
            },
        }
    )
    return value


def _valid_unpublished_result() -> dict:
    value = _valid_save_result()
    target_identity = deepcopy(_TARGET_IDENTITY)
    target_digest = _canonical_sha256(target_identity)
    identity_readback = {
        "product_identity_match": True,
        "store_identity_match": True,
        "source_identity_match": True,
    }
    proof = {
        "ok": True,
        "published": False,
        "proof_kind": "structured_unpublished_status",
        "status_text": "待发布",
        "verified_on_current_page": True,
        "status_scope_unique": True,
        "bound_candidate_count": 1,
        "structured_candidate_count": 1,
        "target_bound": True,
        "product_matched": True,
        "store_matched": True,
        "source_identity_match": True,
        "identity_binding_kind": "frozen_target_structured_page_readback",
        "publish_risk_term": None,
        "target_identity_sha256": target_digest,
        "page_url": _PAGE_URLS["semi_managed"],
        "identity_readback": identity_readback,
    }
    observed_target = {
        "product_matched": True,
        "store_matched": True,
        "source_identity_match": True,
        "target_bound": True,
        "target_identity_sha256": target_digest,
    }
    value.update(
        {
            "action": "verify_not_published",
            "attempted_state": "VERIFY_NOT_PUBLISHED",
            "before_values": {
                "target_identity": target_identity,
            },
            "after_values": {
                "published": False,
                "fresh_probe": proof,
                "target_identity": observed_target,
                "identity_readback": identity_readback,
            },
            "postconditions": {
                "independent_probe": True,
                "product_identity_match": True,
                "unpublished_verified": True,
                "publish_status_absent_or_false": True,
                "save_evidence_not_reused": True,
            },
            "evidence": {
                "observations": {
                    "fresh_probe": proof,
                    "target_identity": observed_target,
                    "identity_readback": identity_readback,
                },
                "refs": [
                    _immutable_ref(
                        "unpublished_screenshot",
                        path="D:/evidence/unpublished-proof.png",
                        sha256="B" * 64,
                        captured_at="2026-07-15T08:00:01+08:00",
                    )
                ],
            },
        }
    )
    return value


def _valid_registered_result(action: str, state: str) -> dict:
    if state == "SAVE_ONLY":
        return _valid_save_result()
    if state == "VERIFY_NOT_PUBLISHED":
        return _valid_unpublished_result()
    contract = ACTION_RESULT_CONTRACTS[action][state]
    value = _valid_navigation_result()
    value.update(
        {
            "action": action,
            "attempted_state": state,
            "before_values": {"target": "expected"},
            "after_values": {"target": "observed"},
            "postconditions": {
                name: True for name in contract.required_postconditions
            },
            "evidence": {
                "observations": {"target": "observed"},
                "refs": [
                    _immutable_ref(
                        {
                            "SAVE_ONLY": "save_screenshot",
                            "VERIFY_NOT_PUBLISHED": "unpublished_screenshot",
                        }.get(state, "screenshot")
                    )
                ],
            },
            "page_identity": {
                "kind": contract.expected_page,
                "url": _PAGE_URLS[contract.expected_page],
                "runtime_id": "runtime-1",
                "browser_session_id": "browser-session-1",
            },
        }
    )
    return value


def test_valid_navigation_result_returns_an_isolated_canonical_dict():
    value = _valid_navigation_result()
    original = deepcopy(value)

    result = validate_action_result_envelope(
        value,
        expected_state="OPEN_DRAFT_LIST",
        expected_action="open_draft_box",
    )

    assert result == original
    assert result is not value
    assert result["before_values"] is not value["before_values"]


def test_registry_covers_precheck_and_all_supported_browser_actions():
    expected = {
        "check_login_state": {"PRECHECK_SESSION": "authenticated_dxm"},
        "open_draft_box": {"OPEN_DRAFT_LIST": "draft_box"},
        "open_editor": {"OPEN_EDIT_PAGE": "editor"},
        "verify_edit_ownership": {"VERIFY_EDIT_OWNERSHIP": "editor"},
        "fill_editor_required_defaults": {"FILL_BASE_INFO": "editor"},
        "fill_editor_variants": {"FILL_VARIANTS": "editor"},
        "fill_media_assets": {"FILL_MEDIA": "editor"},
        "fill_compliance_defaults": {"FILL_COMPLIANCE": "editor"},
        "enable_semi_managed": {"ENABLE_SEMI_MANAGED": "editor"},
        "open_semi_managed_page": {"OPEN_SEMI_MANAGED_PAGE": "semi_managed"},
        "fill_semi_managed_defaults": {
            "FILL_SEMI_GOODS": "semi_managed",
            "FILL_SEMI_VARIANTS": "semi_managed",
        },
        "save_only": {"SAVE_ONLY": "semi_managed"},
        "verify_not_published": {"VERIFY_NOT_PUBLISHED": "semi_managed"},
    }

    actual = {
        action: {
            state: contract.expected_page
            for state, contract in state_contracts.items()
        }
        for action, state_contracts in ACTION_RESULT_CONTRACTS.items()
    }

    assert actual == expected
    assert all(
        contract.required_postconditions
        for state_contracts in ACTION_RESULT_CONTRACTS.values()
        for contract in state_contracts.values()
    )


@pytest.mark.parametrize(
    ("action", "state"),
    [
        (action, state)
        for action, state_contracts in ACTION_RESULT_CONTRACTS.items()
        for state in state_contracts
    ],
)
def test_every_registered_state_action_pair_can_satisfy_its_declared_contract(
    action, state
):
    value = _valid_registered_result(action, state)

    assert validate_action_result_envelope(
        value,
        expected_action=action,
        expected_state=state,
    ) == value


def test_valid_failure_requires_an_explicit_code_and_recovery_decision():
    value = _valid_navigation_result()
    value.update(
        {
            "ok": False,
            "before_values": {},
            "after_values": {},
            "postconditions": {"expected_page": False},
            "failure_code": "E201",
            "recoverability": {
                "kind": "retry_same_page",
                "retryable": True,
                "requires_page_reverify": True,
                "reason": "draft box did not become ready",
            },
        }
    )

    assert validate_action_result_envelope(value) == value


def test_save_result_requires_an_immutable_evidence_reference():
    value = _valid_save_result()
    value["evidence"]["refs"] = []

    with pytest.raises(ActionResultContractError) as captured:
        validate_action_result_envelope(value)

    assert captured.value.reason_code == "ACTION_RESULT_CONTRACT_VIOLATION"
    assert "immutable evidence" in str(captured.value)


def test_success_rejects_a_page_identity_without_an_absolute_http_url():
    value = _valid_navigation_result()
    value["page_identity"]["url"] = "draft-box"

    with pytest.raises(ActionResultContractError, match="absolute HTTP URL"):
        validate_action_result_envelope(value)


def test_valid_save_result_accepts_descriptors_without_reading_the_filesystem():
    value = _valid_save_result()

    assert validate_action_result_envelope(value) == value


def test_valid_unpublished_result_requires_fresh_independent_proof_facts():
    value = _valid_unpublished_result()

    assert validate_action_result_envelope(value) == value


@pytest.mark.parametrize("invalid_ok", [None, "", {}, 1, "true"])
def test_empty_or_non_boolean_ok_is_rejected(invalid_ok):
    value = _valid_navigation_result()
    value["ok"] = invalid_ok

    with pytest.raises(ActionResultContractError, match="ok must be a boolean"):
        validate_action_result_envelope(value)


def test_missing_ok_is_rejected_by_the_exact_top_level_schema():
    value = _valid_navigation_result()
    value.pop("ok")

    with pytest.raises(ActionResultContractError, match="contain exactly"):
        validate_action_result_envelope(value)


def test_stage_and_label_cannot_be_used_as_success_facts():
    value = _valid_navigation_result()
    value["stage"] = "workflow_navigation"
    value["label"] = "done"

    with pytest.raises(ActionResultContractError, match="contain exactly"):
        validate_action_result_envelope(value)


@pytest.mark.parametrize(
    ("expected_state", "expected_action", "message"),
    [
        ("OPEN_EDIT_PAGE", "open_draft_box", "attempted_state does not match"),
        ("OPEN_DRAFT_LIST", "open_editor", "action does not match"),
    ],
)
def test_command_state_and_action_must_match_the_producer_envelope(
    expected_state, expected_action, message
):
    value = _valid_navigation_result()

    with pytest.raises(ActionResultContractError, match=message):
        validate_action_result_envelope(
            value,
            expected_state=expected_state,
            expected_action=expected_action,
        )


def test_unregistered_state_action_pair_is_rejected():
    value = _valid_navigation_result()
    value["attempted_state"] = "REMOVED_STATE"

    with pytest.raises(ActionResultContractError, match="unsupported state/action pair"):
        validate_action_result_envelope(value)


def test_wrong_expected_page_kind_is_rejected():
    value = _valid_navigation_result()
    value["page_identity"]["kind"] = "editor"

    with pytest.raises(ActionResultContractError, match="does not match"):
        validate_action_result_envelope(value)


def test_producer_ok_true_cannot_replace_a_missing_required_postcondition():
    value = _valid_navigation_result()
    value["postconditions"].pop("business_marker_present")

    with pytest.raises(ActionResultContractError, match="missing required postconditions"):
        validate_action_result_envelope(value)


def test_producer_ok_true_cannot_override_a_false_postcondition():
    value = _valid_navigation_result()
    value["postconditions"]["business_marker_present"] = False

    with pytest.raises(ActionResultContractError, match="must all be true"):
        validate_action_result_envelope(value)


@pytest.mark.parametrize("field", ["before_values", "after_values"])
def test_success_requires_non_empty_before_and_after_values(field):
    value = _valid_navigation_result()
    value[field] = {}

    with pytest.raises(ActionResultContractError, match="non-empty before_values"):
        validate_action_result_envelope(value)


def test_success_requires_non_empty_evidence_observations():
    value = _valid_navigation_result()
    value["evidence"]["observations"] = {}

    with pytest.raises(ActionResultContractError, match="non-empty evidence observations"):
        validate_action_result_envelope(value)


def test_evidence_requires_exact_observations_and_refs_shape():
    value = _valid_navigation_result()
    value["evidence"].pop("observations")

    with pytest.raises(ActionResultContractError, match="evidence must contain exactly"):
        validate_action_result_envelope(value)


@pytest.mark.parametrize(
    "field", ["kind", "url", "runtime_id", "browser_session_id"]
)
def test_success_requires_complete_page_runtime_and_session_identity(field):
    value = _valid_navigation_result()
    value["page_identity"][field] = ""

    with pytest.raises(ActionResultContractError, match=f"page_identity.{field}"):
        validate_action_result_envelope(value)


def test_page_identity_requires_exact_shape():
    value = _valid_navigation_result()
    value["page_identity"].pop("browser_session_id")

    with pytest.raises(ActionResultContractError, match="page_identity must contain exactly"):
        validate_action_result_envelope(value)


@pytest.mark.parametrize(
    ("failure_code", "recoverability", "message"),
    [
        (None, None, "stable failure_code"),
        ("temporary failure", None, "stable failure_code"),
        (
            "E201",
            {
                "kind": "none",
                "retryable": False,
                "requires_page_reverify": False,
                "reason": "not ready",
            },
            "non-none recoverability",
        ),
        (
            "E201",
            {
                "kind": "retry_same_page",
                "retryable": False,
                "requires_page_reverify": True,
                "reason": "not ready",
            },
            "conflicts",
        ),
        (
            "E201",
            {
                "kind": "manual_takeover",
                "retryable": False,
                "requires_page_reverify": True,
                "reason": "",
            },
            "reason must be a non-empty string",
        ),
    ],
)
def test_failures_require_a_stable_code_and_non_empty_recoverability(
    failure_code, recoverability, message
):
    value = _valid_navigation_result()
    value["ok"] = False
    value["failure_code"] = failure_code
    if recoverability is not None:
        value["recoverability"] = recoverability

    with pytest.raises(ActionResultContractError, match=message):
        validate_action_result_envelope(value)


@pytest.mark.parametrize(
    ("field", "invalid_value", "message"),
    [
        ("path", "", "path must be a non-empty string"),
        ("sha256", "A" * 63, "64 hexadecimal"),
        ("size", 0, "positive integer"),
        ("size", True, "positive integer"),
        ("kind", "", "kind must be a non-empty string"),
        ("captured_at", "2026-07-15T08:00:00", "include a timezone"),
        ("captured_at", "not-a-time", "must be ISO-8601"),
    ],
)
def test_evidence_reference_descriptors_are_structurally_validated(
    field, invalid_value, message
):
    value = _valid_save_result()
    value["evidence"]["refs"][0][field] = invalid_value

    with pytest.raises(ActionResultContractError, match=message):
        validate_action_result_envelope(value)


def test_evidence_reference_descriptor_has_an_exact_schema():
    value = _valid_save_result()
    value["evidence"]["refs"][0].pop("captured_at")

    with pytest.raises(ActionResultContractError, match="must contain exactly"):
        validate_action_result_envelope(value)


def test_schema_version_is_exact():
    value = _valid_navigation_result()
    value["schema_version"] = "dxm.action-result.v2"

    with pytest.raises(ActionResultContractError, match="dxm.action-result.v1"):
        validate_action_result_envelope(value)


def test_semi_goods_result_cannot_satisfy_the_semi_variants_state():
    value = _valid_registered_result(
        "fill_semi_managed_defaults", "FILL_SEMI_GOODS"
    )
    value["attempted_state"] = "FILL_SEMI_VARIANTS"

    with pytest.raises(ActionResultContractError, match="missing required postconditions"):
        validate_action_result_envelope(value)


def test_success_recoverability_booleans_are_not_truthy_coerced():
    value = _valid_navigation_result()
    value["recoverability"]["retryable"] = 0

    with pytest.raises(ActionResultContractError, match="retryable must be a boolean"):
        validate_action_result_envelope(value)


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/web/smt/smtProductList/draft",
        _PAGE_URLS["editor"],
        _PAGE_URLS["semi_managed"],
    ],
)
def test_page_identity_kind_must_match_the_authoritative_dxm_host_and_path(url):
    value = _valid_navigation_result()
    value["page_identity"]["url"] = url

    with pytest.raises(ActionResultContractError, match="controlled DXM page"):
        validate_action_result_envelope(value)


@pytest.mark.parametrize(
    ("field", "expected_value"),
    [
        ("runtime_id", "runtime-authoritative"),
        ("browser_session_id", "session-authoritative"),
    ],
)
def test_runtime_and_session_identity_can_be_bound_to_authoritative_values(
    field, expected_value
):
    value = _valid_navigation_result()

    kwargs = {
        "expected_runtime_id": expected_value if field == "runtime_id" else "runtime-1",
        "expected_browser_session_id": (
            expected_value if field == "browser_session_id" else "browser-session-1"
        ),
    }
    with pytest.raises(ActionResultContractError, match=f"page_identity.{field} does not match"):
        validate_action_result_envelope(value, **kwargs)


@pytest.mark.parametrize("state,action", [("SAVE_ONLY", "save_only")])
def test_unknown_mutation_failure_cannot_allow_automatic_retry(state, action):
    value = _valid_registered_result(action, state)
    value.update(
        {
            "ok": False,
            "before_values": {},
            "after_values": {},
            "postconditions": {},
            "evidence": {"observations": {}, "refs": []},
            "failure_code": "MUTATION_RESULT_UNKNOWN",
            "recoverability": {
                "kind": "retry_same_page",
                "retryable": True,
                "requires_page_reverify": True,
                "reason": "mutation outcome is unknown",
            },
        }
    )

    with pytest.raises(ActionResultContractError, match="must not be retried automatically"):
        validate_action_result_envelope(value)


def test_retry_same_page_failure_requires_page_reverification_and_identity():
    value = _valid_navigation_result()
    value.update(
        {
            "ok": False,
            "failure_code": "PAGE_NOT_READY",
            "recoverability": {
                "kind": "retry_same_page",
                "retryable": True,
                "requires_page_reverify": False,
                "reason": "page was still loading",
            },
        }
    )

    with pytest.raises(ActionResultContractError, match="page re-verification"):
        validate_action_result_envelope(value)


def test_save_and_unpublished_proofs_are_checked_as_an_independent_pair():
    result = validate_independent_save_verification_pair(
        _valid_save_result(),
        _valid_unpublished_result(),
    )

    assert result["save"]["attempted_state"] == "SAVE_ONLY"
    assert result["verification"]["attempted_state"] == "VERIFY_NOT_PUBLISHED"


def test_unpublished_proof_cannot_reuse_the_save_path_even_when_self_reported_fresh():
    save = _valid_save_result()
    verification = _valid_unpublished_result()
    verification["evidence"]["refs"][0]["path"] = save["evidence"]["refs"][0]["path"]

    with pytest.raises(ActionResultContractError, match="reuse SAVE evidence"):
        validate_independent_save_verification_pair(save, verification)


def test_unpublished_proof_must_be_captured_after_save():
    verification = _valid_unpublished_result()
    verification["evidence"]["refs"][0]["captured_at"] = "2026-07-15T07:59:59+08:00"

    with pytest.raises(ActionResultContractError, match="captured after SAVE"):
        validate_independent_save_verification_pair(_valid_save_result(), verification)


def test_unpublished_probe_target_must_match_the_saved_target():
    verification = _valid_unpublished_result()
    verification["before_values"]["target_identity"] = "product-2"

    with pytest.raises(ActionResultContractError, match="target identity"):
        validate_independent_save_verification_pair(_valid_save_result(), verification)


@pytest.mark.parametrize("field", ["runtime_id", "browser_session_id"])
def test_unpublished_probe_must_stay_on_the_same_runtime_and_browser_session(field):
    verification = _valid_unpublished_result()
    verification["page_identity"][field] = f"different-{field}"

    with pytest.raises(ActionResultContractError, match=f"page_identity.{field} must match"):
        validate_independent_save_verification_pair(_valid_save_result(), verification)
