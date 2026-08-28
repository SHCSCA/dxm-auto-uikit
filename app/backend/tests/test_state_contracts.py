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


def test_removed_acquisition_states_are_absent_and_single_save_stays_guarded():
    specs = build_v1_state_specs()

    removed_states = {
        "OPEN_DATA_ACQUISITION",
        "CLAIM_TO_DRAFT_BOX",
        "VERIFY_DRAFT_BOX_CLAIM",
    }
    assert removed_states.isdisjoint({state.value for state in StateName})
    assert removed_states.isdisjoint({state.value for state in specs})

    save_spec = specs[StateName.SAVE_ONLY]
    assert save_spec.publish_guard_required is True
    assert save_spec.ownership_required is True


def test_publish_modes_are_forbidden():
    for mode in FORBIDDEN_EXECUTION_MODES:
        with pytest.raises(ValueError):
            normalize_execution_mode(mode)


def test_supported_execution_mode_normalizes():
    assert normalize_execution_mode(" single_save ") == ExecutionMode.SINGLE_SAVE
