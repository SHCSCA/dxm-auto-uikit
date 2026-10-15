from copy import deepcopy

import pytest

from src.execution.action_result_contract import ActionResultContractError, validate_action_result_envelope
from tests.support.action_results import _valid_save_result


@pytest.mark.parametrize("method", ["dom_exact_save", "native_exact_save", "coordinate_click", ""])
def test_save_rejects_methods_without_exact_playwright_role_binding(method):
    result = _valid_save_result()
    result["evidence"]["observations"]["save_result"]["click_method"] = method
    with pytest.raises(ActionResultContractError, match="approved exact-save click method"):
        validate_action_result_envelope(result)


@pytest.mark.parametrize("field", [
    "request_body_sha256", "response_body_sha256", "request_evidence_id", "response_evidence_id",
])
def test_save_rejects_network_body_or_identity_tamper(field):
    result = _valid_save_result()
    receipt = result["evidence"]["observations"]["save_result"]["network_save_result"]
    receipt[field] = "F" * 64
    with pytest.raises(ActionResultContractError, match="evidence identities"):
        validate_action_result_envelope(result)


def test_save_rejects_response_observed_before_request():
    result = _valid_save_result()
    receipt = result["evidence"]["observations"]["save_result"]["network_save_result"]
    receipt["response_observed_at"] = "2026-07-15T07:59:57+08:00"
    with pytest.raises(ActionResultContractError, match="must not precede"):
        validate_action_result_envelope(result)


def test_save_requires_independent_post_save_field_readbacks():
    result = _valid_save_result()
    result["evidence"]["observations"]["save_field_readbacks"] = []
    with pytest.raises(ActionResultContractError, match="post-SAVE field readback"):
        validate_action_result_envelope(result)


def test_save_rejects_field_readback_contradiction():
    result = _valid_save_result()
    result["after_values"]["save_field_readbacks"] = deepcopy(
        result["evidence"]["observations"]["save_field_readbacks"])
    result["after_values"]["save_field_readbacks"][0]["after_value"] = "99"
    with pytest.raises(ActionResultContractError, match="field readbacks disagree"):
        validate_action_result_envelope(result)


@pytest.mark.parametrize("method, allowed", [
    ("playwright_exact_role", True), ("dom_exact_save", False), ("native_exact_save", False),
])
def test_delivery_uses_the_same_exact_save_click_contract(method, allowed):
    from src.services.delivery_workspace import _looks_like_save_result

    save = _valid_save_result()["evidence"]["observations"]["save_result"]
    save["click_method"] = method
    assert _looks_like_save_result(save) is allowed
