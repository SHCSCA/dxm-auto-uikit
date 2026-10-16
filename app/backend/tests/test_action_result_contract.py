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


from tests.support.action_results import (
    _PAGE_URLS, _valid_navigation_result, _immutable_ref, _valid_save_result,
    _valid_unpublished_result, _path_a_execution_payload, _as_path_a_editor,
    _canonical_sha256, _bind_batch_save_verification_context,
)
from tests.test_content_observation_flow import observation_case
from tests.support.native_video_input_source_case import video_source_case


def test_batch_path_a_save_and_unpublished_proof_are_native_editor_contracts():
    execution_payload = _path_a_execution_payload()
    save = _as_path_a_editor(_valid_save_result(), execution_payload)
    unpublished = _as_path_a_editor(_valid_unpublished_result())
    verification_context = _bind_batch_save_verification_context(
        save,
        unpublished,
        execution_payload,
    )

    assert validate_action_result_envelope(
        save,
        expected_state="SAVE_ONLY",
        expected_action="save_only",
        expected_page="editor",
        execution_mode="batch_draft_save",
        expected_execution_payload=execution_payload,
    )["page_identity"]["kind"] == "editor"
    assert validate_independent_save_verification_pair(
        save,
        unpublished,
        expected_page="editor",
        execution_mode="batch_draft_save",
        expected_execution_payload=execution_payload,
        expected_verification_context=verification_context,
    )["verification"]["page_identity"]["kind"] == "editor"

    with pytest.raises(ActionResultContractError):
        validate_action_result_envelope(
            _valid_save_result(),
            expected_state="SAVE_ONLY",
            expected_action="save_only",
            expected_page="semi_managed",
            execution_mode="batch_draft_save",
        )
    with pytest.raises(ActionResultContractError):
        validate_action_result_envelope(
            save,
            expected_state="SAVE_ONLY",
            expected_action="save_only",
            expected_page="editor",
            execution_mode="single_save",
        )

    poisoned = deepcopy(save)
    poisoned["page_identity"]["url"] = (
        "https://www.dianxiaomi.com/web/smt/edit-not-a-real-editor"
    )
    with pytest.raises(ActionResultContractError):
        validate_action_result_envelope(
            poisoned,
            expected_state="SAVE_ONLY",
            expected_action="save_only",
            expected_page="editor",
        )


def _valid_registered_result(action: str, state: str) -> dict:
    if action == "save_only":
        value = _valid_save_result()
        value["attempted_state"] = state
        return value
    if action == "verify_not_published":
        value = _valid_unpublished_result()
        if state == "VERIFY_SAVE1_NOT_PUBLISHED":
            value = _as_path_a_editor(value)
        value["attempted_state"] = state
        if state == "VERIFY_DISCOVERY_SAVE1_NOT_PUBLISHED":
            predecessor = {"state": "FIRST_SAVE_INTENT", "action": "first_save_intent"}
            for container in (value["before_values"], value["after_values"],
                    value["evidence"]["observations"], value["after_values"]["fresh_probe"]):
                container["save_predecessor"] = deepcopy(predecessor)
        return value
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
        "open_semi_managed_page": {"OPEN_SEMI_MANAGED_PAGE": "semi_managed", "SAVE_INTENT_MODAL": "semi_managed"},
        "fill_semi_managed_defaults": {
            "FILL_SEMI_GOODS": "semi_managed",
            "FILL_SEMI_VARIANTS": "semi_managed",
        },
        "prepare_rollback": {"PREPARE_ROLLBACK": "editor"},
        "validate_editor_wholesale": {"BATCH_WHOLESALE_FILL": "editor"},
        "translate_editor_content": {"BATCH_TRANSLATE_EXECUTE": "editor"},
        "observe_content_finalize": {"BATCH_TRANSLATE_EXECUTE": "editor"},
        "observe_native_video_inputs": {"BATCH_VIDEO_SELECT": "editor"},
        "first_save_intent": {"FIRST_SAVE_INTENT": "semi_managed"},
        "save_only": {"SAVE_ONLY": "semi_managed", "SAVE2_ONLY": "semi_managed"},
        "verify_not_published": {
            "VERIFY_NOT_PUBLISHED": "semi_managed",
            "VERIFY_SAVE1_NOT_PUBLISHED": "editor",
            "VERIFY_SAVE2_NOT_PUBLISHED": "semi_managed",
            "VERIFY_DISCOVERY_SAVE1_NOT_PUBLISHED": "semi_managed",
        },
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
def test_every_registered_state_action_pair_enforces_its_declared_contract(
    action, state, request
):
    if action in {'observe_content_finalize', 'observe_native_video_inputs'}:
        native_video = action == 'observe_native_video_inputs'
        case = request.getfixturevalue('video_source_case' if native_video else 'observation_case')
        value = case['runtime'].run(case['command'], timeout_seconds=10)
        expected = {'expected_action': action, 'expected_state': state, 'expected_page': 'editor',
            'execution_mode': 'batch_draft_save', 'expected_execution_payload': case['payload'],
            'expected_runtime_id': case['runtime'].runtime_id, 'expected_browser_session_id': case['flow'].session}
        assert validate_action_result_envelope(value, **expected) == value
        # 完整正例来自独立双读 producer，经 Adapter 和真实 Worker 合同，不用通用布尔摘要补齐。
        root = ('evidence', 'observations', 'native_video_input_observation' if native_video else 'content_finalize_observation')
        def at(document, path):
            for key in path:
                document = document[key]
            return document
        paths = ((), ('page_identity',), root, root + ('command',), root + ('observation',),
                     root + ('before',), root + ('after',), root + ('effect_facts',),
                      root + ('observation', 'evidence_ref'))
        if native_video:
            paths += (root + ('source_profile',), root + ('lifecycle',))
        for path in paths:
            for key in at(value, path):
                changed = deepcopy(value)
                del at(changed, path)[key]
                with pytest.raises(ActionResultContractError):
                    validate_action_result_envelope(changed, **expected)
        for key in value['postconditions']:
            for invalid in (False, None, 1):
                changed = deepcopy(value)
                changed['postconditions'][key] = invalid
                with pytest.raises(ActionResultContractError):
                    validate_action_result_envelope(changed, **expected)
        observed_path = root + ('observation', 'inputs' if native_video else 'values')
        for key in at(value, observed_path):
            changed = deepcopy(value)
            at(changed, observed_path)[key] = 'caller-replacement'
            with pytest.raises(ActionResultContractError):
                validate_action_result_envelope(changed, **expected)
        return
    value = _valid_registered_result(action, state)
    evidence_contracts = {
        "PREPARE_ROLLBACK": "rollback preparation is unproven",
        "BATCH_WHOLESALE_FILL": "wholesale finalization is unproven",
        "BATCH_TRANSLATE_EXECUTE": "native translation is unproven",
        "FIRST_SAVE_INTENT": "FIRST_SAVE_INTENT is only valid for batch_draft_save",
    }
    if state in evidence_contracts:
        # 专业动作必须拒绝通用布尔正例；独立能力测试验证完整观测与回执的成功链。
        if state == "FIRST_SAVE_INTENT":
            value["evidence"]["refs"][0]["kind"] = "save_screenshot"
        with pytest.raises(ActionResultContractError, match=evidence_contracts[state]):
            validate_action_result_envelope(value, expected_action=action, expected_state=state)
    else:
        assert validate_action_result_envelope(
            value, expected_action=action, expected_state=state,
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


def test_save_result_requires_explicit_read_only_schema_request_count():
    value = _valid_save_result()
    value["evidence"]["observations"]["save_result"]["network_audit"].pop(
        "read_only_schema_request_count"
    )

    with pytest.raises(ActionResultContractError):
        validate_action_result_envelope(value)


def test_batch_save_requires_current_category_schema_readback():
    execution_payload = _path_a_execution_payload()
    value = _as_path_a_editor(_valid_save_result(), execution_payload)
    value["evidence"]["observations"]["save_result"][
        "pre_dispatch_readback"
    ].pop("category_schema_readback")
    value["evidence"]["observations"]["save_result"]["network_audit"][
        "read_only_schema_request_count"
    ] = 1

    with pytest.raises(ActionResultContractError, match="category_schema_readback"):
        validate_action_result_envelope(
            value,
            expected_state="SAVE_ONLY",
            expected_action="save_only",
            expected_page="editor",
            execution_mode="batch_draft_save",
            expected_execution_payload=execution_payload,
        )


def test_batch_save_requires_a_live_read_only_schema_request():
    execution_payload = _path_a_execution_payload()
    value = _as_path_a_editor(_valid_save_result(), execution_payload)
    value["evidence"]["observations"]["save_result"]["network_audit"][
        "read_only_schema_request_count"
    ] = 0

    with pytest.raises(ActionResultContractError, match="read-only Schema request"):
        validate_action_result_envelope(
            value,
            expected_state="SAVE_ONLY",
            expected_action="save_only",
            expected_page="editor",
            execution_mode="batch_draft_save",
            expected_execution_payload=execution_payload,
        )


@pytest.mark.parametrize(
    ("field", "drifted_value"),
    [
        ("expected_category_id", "9999"),
        ("observed_category_id", "9999"),
        ("expected_category_schema_hash", "D" * 64),
        ("observed_category_schema_hash", "D" * 64),
    ],
)
def test_batch_save_category_schema_readback_matches_frozen_execution_payload(
    field, drifted_value
):
    execution_payload = _path_a_execution_payload()
    value = _as_path_a_editor(_valid_save_result(), execution_payload)
    category_schema_readback = value["evidence"]["observations"]["save_result"][
        "pre_dispatch_readback"
    ]["category_schema_readback"]
    category_schema_readback[field] = drifted_value

    with pytest.raises(ActionResultContractError, match="frozen execution payload"):
        validate_action_result_envelope(
            value,
            expected_state="SAVE_ONLY",
            expected_action="save_only",
            expected_page="editor",
            execution_mode="batch_draft_save",
            expected_execution_payload=execution_payload,
        )


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
