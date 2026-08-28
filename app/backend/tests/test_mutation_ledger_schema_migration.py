from __future__ import annotations

import sqlite3

from src import db


CURRENT_LEDGER_COLUMNS = {
    "mutation_id",
    "mutation_scope_id",
    "mutation_action",
    "ordinal",
    "command_state",
    "command_action",
    "task_id",
    "job_id",
    "authorization_lease_id",
    "authorization_lease_fingerprint",
    "snapshot_row_authority_sha256",
    "stage_task_facts_fingerprint",
    "target_hash",
    "authorization_fingerprint",
    "browser_session_id",
    "page_url",
    "page_kind",
    "status",
    "command_id",
    "command_sha256",
    "command_json",
    "save_action_result_sha256",
    "save_action_result_json",
    "save_authority_sha256",
    "save_authority_json",
    "save_success_recorded_at",
    "runtime_id",
    "outcome_json",
    "reserved_at",
    "dispatch_started_at",
    "dispatched_at",
    "unknown_at",
    "updated_at",
}


def test_init_db_migrates_legacy_mutation_ledger_to_current_contract(
    tmp_path,
    monkeypatch,
) -> None:
    database = tmp_path / "legacy-ledger.db"
    with sqlite3.connect(database) as conn:
        conn.execute(
            """
            CREATE TABLE mutation_dispatch_ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mutation_scope_id TEXT NOT NULL,
                mutation_action TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                command_action TEXT NOT NULL,
                task_id TEXT NOT NULL,
                job_id TEXT NOT NULL,
                authorization_lease_id TEXT NOT NULL,
                stage_task_facts_fingerprint TEXT NOT NULL,
                target_hash TEXT NOT NULL,
                authorization_fingerprint TEXT NOT NULL,
                status TEXT NOT NULL,
                command_id TEXT,
                runtime_id TEXT,
                outcome_json TEXT,
                reserved_at TEXT NOT NULL,
                dispatch_started_at TEXT,
                dispatched_at TEXT,
                unknown_at TEXT,
                updated_at TEXT NOT NULL,
                UNIQUE (mutation_scope_id, mutation_action),
                UNIQUE (mutation_scope_id, ordinal)
            )
            """
        )
    monkeypatch.setattr(db, "DB_PATH", database)

    db.init_db()

    with sqlite3.connect(database) as conn:
        columns = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(mutation_dispatch_ledger)"
            ).fetchall()
        }
        unique_indexes = {
            row[1]
            for row in conn.execute(
                "PRAGMA index_list(mutation_dispatch_ledger)"
            ).fetchall()
            if row[2] == 1
        }
    assert CURRENT_LEDGER_COLUMNS.issubset(columns)
    assert "idx_mutation_dispatch_ledger_mutation_id" in unique_indexes
