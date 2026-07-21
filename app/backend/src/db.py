import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from src.core.config import DB_PATH


def _row_factory(cursor, row):
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = _row_factory
    return conn


@contextmanager
def connection():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def loads(value: str | None, default: Any):
    if not value:
        return default
    return json.loads(value)


def init_db() -> None:
    with connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS stores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                platform TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'disconnected',
                last_login_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                template_type TEXT NOT NULL,
                template_name TEXT NOT NULL,
                binding_scope TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                is_enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'manual',
                status TEXT NOT NULL DEFAULT 'draft',
                category_name TEXT,
                price REAL DEFAULT 0,
                currency TEXT DEFAULT 'USD',
                sku_count INTEGER DEFAULT 1,
                image_count INTEGER DEFAULT 0,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                store_id INTEGER,
                status TEXT NOT NULL,
                mode TEXT NOT NULL,
                publish_scene TEXT NOT NULL,
                total_jobs INTEGER NOT NULL DEFAULT 0,
                completed_jobs INTEGER NOT NULL DEFAULT 0,
                failed_jobs INTEGER NOT NULL DEFAULT 0,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                product_id INTEGER,
                status TEXT NOT NULL,
                current_step_code TEXT,
                current_step_name TEXT,
                error_code TEXT,
                error_message TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS job_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                job_id INTEGER,
                level TEXT NOT NULL,
                message TEXT NOT NULL,
                context_json TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS job_evidences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                job_id INTEGER,
                evidence_type TEXT NOT NULL,
                file_path TEXT,
                meta_json TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS exceptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                job_id INTEGER,
                error_code TEXT NOT NULL,
                field_domain TEXT NOT NULL,
                title TEXT NOT NULL,
                detail TEXT,
                suggestion TEXT,
                status TEXT NOT NULL DEFAULT 'open',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                job_id INTEGER,
                product_id INTEGER,
                status TEXT NOT NULL,
                published INTEGER NOT NULL DEFAULT 0,
                save_result_json TEXT NOT NULL,
                summary_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS ownership_locks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lock_token TEXT NOT NULL UNIQUE,
                ownership_fingerprint TEXT NOT NULL,
                task_id INTEGER NOT NULL,
                job_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                store_name TEXT NOT NULL,
                source_title TEXT NOT NULL,
                sku_prefix TEXT,
                claim_mark TEXT NOT NULL,
                lock_owner_run_id TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                page_claim_mark TEXT,
                page_claim_verified INTEGER NOT NULL DEFAULT 0,
                page_claim_verified_at TEXT,
                expires_at TEXT NOT NULL,
                released_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_ownership_locks_active_fingerprint
                ON ownership_locks (ownership_fingerprint, status, expires_at);

            CREATE INDEX IF NOT EXISTS idx_ownership_locks_token
                ON ownership_locks (lock_token);

            CREATE TABLE IF NOT EXISTS mutation_dispatch_ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mutation_id TEXT NOT NULL UNIQUE,
                mutation_scope_id TEXT NOT NULL,
                mutation_action TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                command_state TEXT NOT NULL,
                command_action TEXT NOT NULL,
                task_id TEXT NOT NULL,
                job_id TEXT NOT NULL,
                authorization_lease_id TEXT NOT NULL,
                stage_task_facts_fingerprint TEXT NOT NULL,
                target_hash TEXT NOT NULL,
                authorization_fingerprint TEXT NOT NULL,
                browser_session_id TEXT,
                page_url TEXT,
                page_kind TEXT,
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
            );

            CREATE INDEX IF NOT EXISTS idx_mutation_dispatch_ledger_status
                ON mutation_dispatch_ledger (status, updated_at);

            CREATE INDEX IF NOT EXISTS idx_mutation_dispatch_ledger_scope
                ON mutation_dispatch_ledger (mutation_scope_id, ordinal);

            CREATE TABLE IF NOT EXISTS draft_box_scope_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                schema_version TEXT NOT NULL,
                digest TEXT NOT NULL UNIQUE,
                snapshot_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_draft_box_scope_snapshots_created
                ON draft_box_scope_snapshots (created_at DESC, id DESC);

            CREATE TABLE IF NOT EXISTS edit_batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                schema_version TEXT NOT NULL,
                status TEXT NOT NULL,
                scope_snapshot_id INTEGER NOT NULL,
                scope_snapshot_digest TEXT NOT NULL,
                scope_snapshot_json TEXT NOT NULL,
                template_id INTEGER NOT NULL,
                template_snapshot_digest TEXT NOT NULL,
                template_snapshot_json TEXT NOT NULL,
                policy_digest TEXT NOT NULL,
                policy_json TEXT NOT NULL,
                approval_token_hash TEXT,
                approval_lease_id TEXT,
                approval_context_json TEXT,
                approval_token_consumed_at TEXT,
                start_context_json TEXT,
                started_at TEXT,
                stop_requested_at TEXT,
                stopped_at TEXT,
                completed_at TEXT,
                execution_reason_code TEXT,
                execution_detail TEXT,
                stop_request_context_json TEXT,
                manual_review_required INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_edit_batches_created
                ON edit_batches (created_at DESC, id DESC);

            CREATE TABLE IF NOT EXISTS edit_batch_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id INTEGER NOT NULL,
                ordinal INTEGER NOT NULL,
                status TEXT NOT NULL,
                target_identity_sha256 TEXT NOT NULL,
                item_snapshot_json TEXT NOT NULL,
                grant_lease_id TEXT,
                grant_fingerprint TEXT,
                grant_nonce_hash TEXT,
                mutation_scope_id TEXT,
                grant_context_json TEXT,
                granted_at TEXT,
                grant_expires_at TEXT,
                grant_consumed_at TEXT,
                outcome_classification TEXT,
                outcome_reason_code TEXT,
                outcome_evidence_json TEXT,
                outcome_decision_json TEXT,
                action_results_json TEXT,
                finished_at TEXT,
                manual_review_required INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (batch_id, ordinal),
                UNIQUE (batch_id, target_identity_sha256)
            );

            CREATE INDEX IF NOT EXISTS idx_edit_batch_items_batch
                ON edit_batch_items (batch_id, ordinal);
            """
        )
        _ensure_columns(
            conn,
            "edit_batches",
            {
                "approval_token_hash": "TEXT",
                "approval_lease_id": "TEXT",
                "approval_context_json": "TEXT",
                "approval_token_consumed_at": "TEXT",
                "start_context_json": "TEXT",
                "started_at": "TEXT",
                "stop_requested_at": "TEXT",
                "stopped_at": "TEXT",
                "completed_at": "TEXT",
                "execution_reason_code": "TEXT",
                "execution_detail": "TEXT",
                "stop_request_context_json": "TEXT",
                "manual_review_required": "INTEGER NOT NULL DEFAULT 0",
            },
        )
        _ensure_columns(
            conn,
            "edit_batch_items",
            {
                "grant_lease_id": "TEXT",
                "grant_fingerprint": "TEXT",
                "grant_nonce_hash": "TEXT",
                "mutation_scope_id": "TEXT",
                "grant_context_json": "TEXT",
                "granted_at": "TEXT",
                "grant_expires_at": "TEXT",
                "grant_consumed_at": "TEXT",
                "outcome_classification": "TEXT",
                "outcome_reason_code": "TEXT",
                "outcome_evidence_json": "TEXT",
                "outcome_decision_json": "TEXT",
                "action_results_json": "TEXT",
                "finished_at": "TEXT",
                "manual_review_required": "INTEGER NOT NULL DEFAULT 0",
            },
        )
        recover_interrupted_edit_batches(conn)
        conn.executescript(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_edit_batch_items_one_running
                ON edit_batch_items (batch_id)
                WHERE status = 'running';

            CREATE UNIQUE INDEX IF NOT EXISTS idx_edit_batches_one_active
                ON edit_batches ((1))
                WHERE status IN ('running', 'stop_requested');

            CREATE UNIQUE INDEX IF NOT EXISTS idx_edit_batch_items_grant_lease
                ON edit_batch_items (grant_lease_id)
                WHERE grant_lease_id IS NOT NULL;

            CREATE UNIQUE INDEX IF NOT EXISTS idx_edit_batch_items_grant_nonce_hash
                ON edit_batch_items (grant_nonce_hash)
                WHERE grant_nonce_hash IS NOT NULL;

            CREATE UNIQUE INDEX IF NOT EXISTS idx_edit_batch_items_mutation_scope
                ON edit_batch_items (mutation_scope_id)
                WHERE mutation_scope_id IS NOT NULL;
            """
        )
        _ensure_columns(
            conn,
            "ownership_locks",
            {
                "lock_owner_run_id": "TEXT",
                "page_claim_mark": "TEXT",
                "page_claim_verified": "INTEGER NOT NULL DEFAULT 0",
                "page_claim_verified_at": "TEXT",
                "released_at": "TEXT",
            },
        )
        _ensure_columns(
            conn,
            "reports",
            {
                "product_id": "INTEGER",
                "published": "INTEGER NOT NULL DEFAULT 0",
                "save_result_json": "TEXT NOT NULL DEFAULT '{}'",
                "summary_json": "TEXT NOT NULL DEFAULT '{}'",
            },
        )


def _ensure_columns(conn: sqlite3.Connection, table_name: str, columns: dict[str, str]) -> None:
    existing = {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    for column_name, column_definition in columns.items():
        if column_name not in existing:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}")


def recover_interrupted_edit_batches(conn: sqlite3.Connection) -> list[int]:
    """Fail closed on process restart; a live batch is never auto-resumed."""
    interrupted = conn.execute(
        "SELECT id, status FROM edit_batches WHERE status IN ('running', 'stop_requested')"
    ).fetchall()
    if not interrupted:
        return []

    recovered_at = datetime.now(timezone.utc).isoformat()
    reason_code = "PROCESS_RESTART_REQUIRES_MANUAL_REVIEW"
    for batch in interrupted:
        batch_id = int(batch["id"])
        prior_status = str(batch["status"])
        recovery_evidence = dumps(
            {
                "schema_version": "dxm_edit_batch_recovery_evidence.v1",
                "reason_code": reason_code,
                "prior_batch_status": prior_status,
                "recovered_at": recovered_at,
                "retry_allowed": False,
            }
        )
        conn.execute(
            """
            UPDATE edit_batch_items
               SET status='stopped_uncertain',
                   outcome_classification='STOPPED_UNCERTAIN',
                   outcome_reason_code=?,
                   outcome_evidence_json=?,
                   finished_at=?,
                   manual_review_required=1,
                   updated_at=?
             WHERE batch_id=? AND status='running'
            """,
            (reason_code, recovery_evidence, recovered_at, recovered_at, batch_id),
        )
        conn.execute(
            """
            UPDATE edit_batches
               SET status='stopped',
                   stopped_at=?,
                   execution_reason_code=?,
                   execution_detail='进程重启后批次不会自动恢复，请人工核对后重新创建批次。',
                   manual_review_required=1,
                   updated_at=?
             WHERE id=? AND status IN ('running', 'stop_requested')
            """,
            (recovered_at, reason_code, recovered_at, batch_id),
        )
    return [int(batch["id"]) for batch in interrupted]
