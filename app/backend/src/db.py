import json
import sqlite3
from contextlib import contextmanager
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
