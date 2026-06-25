import pytest

from src.state_machine.contracts import (
    ExecutionMode,
    FORBIDDEN_EXECUTION_MODES,
    StateName,
    build_v1_state_specs,
    normalize_execution_mode,
)


def test_v1_state_specs_have_required_contract_fields():
    specs = build_v1_state_specs()

    assert StateName.PRECHECK_CONFIG in specs
    assert StateName.SAVE_ONLY in specs
    for spec in specs.values():
        spec.validate()
        assert spec.failure_code.startswith("E")
        assert spec.evidence_required


def test_save_only_requires_publish_guard_and_ownership():
    spec = build_v1_state_specs()[StateName.SAVE_ONLY]

    assert spec.publish_guard_required is True
    assert spec.ownership_required is True
    assert "click save button only" in spec.actions


def test_acquisition_claim_states_are_first_class_and_do_not_save_or_publish():
    specs = build_v1_state_specs()

    for state in (
        StateName.OPEN_DATA_ACQUISITION,
        StateName.CLAIM_TO_DRAFT_BOX,
        StateName.VERIFY_DRAFT_BOX_CLAIM,
    ):
        assert state in specs

    claim_actions = " ".join(build_v1_state_specs()[StateName.CLAIM_TO_DRAFT_BOX].actions).lower()
    assert "claim" in claim_actions
    assert "edit" not in claim_actions
    assert "save" not in claim_actions
    assert "publish" not in claim_actions


def test_publish_modes_are_forbidden():
    for mode in FORBIDDEN_EXECUTION_MODES:
        with pytest.raises(ValueError):
            normalize_execution_mode(mode)


def test_supported_execution_mode_normalizes():
    assert normalize_execution_mode(" single_save ") == ExecutionMode.SINGLE_SAVE
