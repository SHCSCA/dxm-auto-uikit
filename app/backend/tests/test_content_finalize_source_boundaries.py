from copy import deepcopy

import pytest

from src.batch_edit.content_finalize_sources import (
    index_content_sources, require_reviewed_video_source, validate_content_sources,
)
from src.batch_edit.frozen_execution_contract import FrozenExecutionContractError
from src.batch_edit.scope_contract import canonical_sha256


def case():
    task = {"id": 701}
    job = {"id": 801, "product_id": 81010001}
    candidate = {"snapshot_sha256": "A" * 64, "scope_sha256": "B" * 64,
        "initial_execution_payload_hash": "C" * 64,
        "observation": {"browser_session_id": "synthetic-session", "observed_at": "2026-08-31T00:04:00Z"}}
    return task, job, candidate


def source(state, candidate):
    record = {"schema": "dxm.path_b_editor_source.v1", "task_id": 701, "job_id": 801,
        "product_id": 81010001, "snapshot_sha256": candidate["snapshot_sha256"],
        "scope_sha256": candidate["scope_sha256"], "execution_payload_hash": candidate["initial_execution_payload_hash"],
        "command": {"task_id": 701, "job_id": 801, "state": state, "command_id": "synthetic-" + state},
        "action_result": {"ok": True, "page_identity": {"browser_session_id": "synthetic-session"}},
        "created_at": "2026-08-31T00:03:00Z"}
    return signed(record)


def signed(record):
    body = {key: value for key, value in record.items() if key != "source_sha256"}
    return {**body, "source_sha256": canonical_sha256(body)}


def test_source_index_checks_metadata_without_certifying_actual_files_or_actions():
    task, job, candidate = case()
    record = source("FILL_BASE_INFO", candidate)
    result = index_content_sources([record], task=task, job=job, candidate=candidate)
    assert result == {"FILL_BASE_INFO": record}
    assert "verified" not in result


@pytest.mark.parametrize(("change", "code"), [
    (lambda value: value.update(job_id=802), "CONTENT_FINALIZE_SOURCE_IDENTITY_DRIFT"),
    (lambda value: value["command"].update(task_id=702), "CONTENT_FINALIZE_SOURCE_IDENTITY_DRIFT"),
    (lambda value: value.update(product_id=81010002), "CONTENT_FINALIZE_SOURCE_IDENTITY_DRIFT"),
    (lambda value: value.update(scope_sha256="D" * 64), "CONTENT_FINALIZE_SOURCE_IDENTITY_DRIFT"),
    (lambda value: value["action_result"]["page_identity"].update(browser_session_id="other"), "CONTENT_FINALIZE_SOURCE_SESSION_DRIFT"),
    (lambda value: value["action_result"].update(ok=False), "CONTENT_FINALIZE_SOURCE_NOT_SUCCESSFUL"),
    (lambda value: value.update(created_at="2026-08-31T00:05:00Z"), "CONTENT_FINALIZE_SOURCE_ORDER_INVALID"),
])
def test_resigned_source_cannot_move_to_another_authority_or_change_outcome(change, code):
    task, job, candidate = case()
    record = source("FILL_BASE_INFO", candidate)
    change(record)
    with pytest.raises(FrozenExecutionContractError) as failure:
        index_content_sources([signed(record)], task=task, job=job, candidate=candidate)
    assert failure.value.reason_code == code


def test_source_hash_tampering_duplicate_and_action_order_are_separately_rejected():
    task, job, candidate = case()
    fill = source("FILL_BASE_INFO", candidate)
    wholesale = source("BATCH_WHOLESALE_FILL", candidate)
    tampered = deepcopy(fill)
    tampered["command"]["job_id"] = 802
    for records, expected in (([tampered], "CONTENT_FINALIZE_SOURCE_HASH_DRIFT"),
            ([fill, fill], "CONTENT_FINALIZE_SOURCE_DUPLICATE"),
            ([wholesale, fill], "CONTENT_FINALIZE_SOURCE_ORDER_INVALID")):
        with pytest.raises(FrozenExecutionContractError) as failure:
            index_content_sources(records, task=task, job=job, candidate=candidate)
        assert failure.value.reason_code == expected


def test_missing_actual_sources_stop_before_any_worker_file_or_ledger_access(tmp_path):
    task, job, candidate = case()
    with pytest.raises(FrozenExecutionContractError) as failure:
        validate_content_sources(None, task=task, job=job, candidate=candidate, records=[],
                                 screenshot_root=tmp_path, snapshot_authority={})
    assert failure.value.reason_code == "CONTENT_FINALIZE_SOURCE_MISSING"
    assert list(tmp_path.iterdir()) == []


def test_unreviewed_video_producer_stays_closed_even_with_candidate_source_labels():
    task, job, candidate = case()
    for indexed in ({}, {state: source(state, candidate) for state in ("BATCH_VIDEO_SUBMIT", "BATCH_VIDEO_PLACE")}):
        with pytest.raises(FrozenExecutionContractError) as failure:
            require_reviewed_video_source(indexed)
        assert failure.value.reason_code == "CONTENT_FINALIZE_VIDEO_SOURCE_NOT_BOUND"
