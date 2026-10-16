import sqlite3

import pytest

from src.batch_edit.content_finalize_store import EVIDENCE_TYPE, append_content_finalize_stage, require_content_finalize_stage
from src.batch_edit.frozen_execution_contract import FrozenExecutionContractError
from src.batch_edit.scope_contract import canonical_sha256
from src.db import dumps


@pytest.fixture
def store_connection():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("CREATE TABLE job_evidences(id INTEGER PRIMARY KEY, task_id INTEGER, job_id INTEGER, evidence_type TEXT, meta_json TEXT)")
    yield connection
    connection.close()


def candidate_task():
    return {"id": 701, "_content_finalize_freezes": {"801": {"freeze_sha256": "A" * 64, "fields": []}}}


def require(conn, tmp_path):
    return require_content_finalize_stage(conn, task=candidate_task(), job={"id": 801},
        browser_session_id="synthetic-session", screenshot_root=tmp_path)


def insert(conn, record):
    conn.execute("INSERT INTO job_evidences(task_id,job_id,evidence_type,meta_json) VALUES(701,801,?,?)", (EVIDENCE_TYPE, dumps(record)))


def test_candidate_map_cannot_replace_missing_persisted_stage(store_connection, tmp_path):
    with pytest.raises(FrozenExecutionContractError) as failure:
        require(store_connection, tmp_path)
    assert failure.value.reason_code == "CONTENT_FINALIZE_STAGE_NOT_FROZEN"
    assert store_connection.execute("SELECT COUNT(*) FROM job_evidences").fetchone()[0] == 0


def test_duplicate_rows_are_not_coalesced_into_one_success(store_connection, tmp_path):
    insert(store_connection, {})
    insert(store_connection, {})
    with pytest.raises(FrozenExecutionContractError) as failure:
        require(store_connection, tmp_path)
    assert failure.value.reason_code == "CONTENT_FINALIZE_STAGE_DUPLICATE"


def test_tampered_persisted_hash_and_wrong_session_are_rejected_before_consumption(store_connection, tmp_path):
    body = {"schema": "dxm.persisted_content_finalize.v1", "candidate": {
        "observation": {"browser_session_id": "other-session"}}, "source_sha256s": [], "created_at": "2026-08-31T00:04:00Z",
        'observation_source_sha256': 'B' * 64}
    insert(store_connection, {**body, "record_sha256": "A" * 64})
    with pytest.raises(FrozenExecutionContractError) as failure:
        require(store_connection, tmp_path)
    assert failure.value.reason_code == "CONTENT_FINALIZE_STAGE_RECORD_DRIFT"
    store_connection.execute("DELETE FROM job_evidences")
    insert(store_connection, {**body, "record_sha256": canonical_sha256(body)})
    with pytest.raises(FrozenExecutionContractError) as failure:
        require(store_connection, tmp_path)
    assert failure.value.reason_code == "CONTENT_FINALIZE_SOURCE_SESSION_DRIFT"


def test_missing_running_job_cannot_append_or_modify_any_source(store_connection, tmp_path):
    with pytest.raises(FrozenExecutionContractError) as failure:
        append_content_finalize_stage(store_connection, task=candidate_task(), job=None,
            observation={}, receipts={}, screenshot_root=tmp_path, now="2026-08-31T00:04:00Z")
    assert failure.value.reason_code == "CONTENT_FINALIZE_STATE_INVALID"
    assert store_connection.execute("SELECT COUNT(*) FROM job_evidences").fetchone()[0] == 0


def test_repository_boundary_records_rejection_and_preserves_existing_task(tmp_path, monkeypatch, caplog):
    from src import db
    from src.repository import Repository

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "local-contract.sqlite")
    db.init_db()
    repository = Repository()
    with pytest.raises(FrozenExecutionContractError) as failure:
        repository.persist_content_finalize_stage(701, 801, observation={}, receipts={})
    assert failure.value.reason_code == "CONTENT_FINALIZE_STATE_INVALID"
    with pytest.raises(FrozenExecutionContractError) as failure:
        repository.require_content_finalize_stage(701, 801, browser_session_id="synthetic-session")
    assert failure.value.reason_code == "CONTENT_FINALIZE_STAGE_NOT_FROZEN"
    assert any(record.message == "content_finalize_persistence_rejected" for record in caplog.records)
    with db.connection() as conn:
        assert conn.execute("SELECT COUNT(*) AS total FROM job_evidences").fetchone()["total"] == 0
        assert conn.execute("SELECT COUNT(*) AS total FROM mutation_dispatch_ledger").fetchone()["total"] == 0
