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
    except BaseException:
        conn.rollback()
        raise
    else:
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
                requires_manual_configuration INTEGER NOT NULL DEFAULT 0,
                quarantine_reason TEXT,
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
                published INTEGER CHECK (published IS NULL OR published IN (0, 1)),
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

            CREATE TABLE IF NOT EXISTS dxm_template_refs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ref_type TEXT NOT NULL,
                dxm_template_id TEXT NOT NULL,
                shop_id TEXT NOT NULL,
                category_id TEXT,
                observed_display_name TEXT NOT NULL,
                source_api TEXT NOT NULL,
                availability TEXT NOT NULL,
                source_digest TEXT NOT NULL,
                resolved_values_json TEXT NOT NULL DEFAULT '{}',
                resolved_values_hash TEXT NOT NULL DEFAULT '44136FA355B3678A1146AD16F7E8649E94FB4FC21FE77E8310C060F61CAFF8A',
                audit_items_json TEXT NOT NULL DEFAULT '[]',
                audit_items_hash TEXT NOT NULL DEFAULT '4F53CDA18C2BAA0C0354BB5F9A3ECBE5ED12AB4D8E10F13D464B1CD0DEBDF735',
                synced_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_dxm_template_refs_identity
                ON dxm_template_refs (
                    ref_type,
                    dxm_template_id,
                    shop_id,
                    COALESCE(category_id, '')
                );

            CREATE TABLE IF NOT EXISTS local_plan_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lineage_id INTEGER,
                version TEXT NOT NULL,
                name TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                supersedes_id INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_local_plan_version
                ON local_plan_templates (lineage_id, version);

            CREATE TABLE IF NOT EXISTS plan_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                local_plan_template_id INTEGER NOT NULL,
                snapshot_hash TEXT NOT NULL UNIQUE,
                snapshot_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_plan_snapshots_plan
                ON plan_snapshots (local_plan_template_id, id DESC);

            CREATE TABLE IF NOT EXISTS plan_snapshot_idempotency_keys (
                idempotency_key TEXT PRIMARY KEY,
                snapshot_id INTEGER NOT NULL,
                snapshot_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_plan_snapshot_idempotency_snapshot
                ON plan_snapshot_idempotency_keys (snapshot_id);

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
                claimed_at TEXT,
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
            "dxm_template_refs",
            {
                "resolved_values_json": "TEXT NOT NULL DEFAULT '{}'",
                "resolved_values_hash": (
                    "TEXT NOT NULL DEFAULT "
                    "'44136FA355B3678A1146AD16F7E8649E94FB4FC21FE77E8310C060F61CAFF8A'"
                ),
                "audit_items_json": "TEXT NOT NULL DEFAULT '[]'",
                "audit_items_hash": (
                    "TEXT NOT NULL DEFAULT "
                    "'4F53CDA18C2BAA0C0354BB5F9A3ECBE5ED12AB4D8E10F13D464B1CD0DEBDF735'"
                ),
            },
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
                "claimed_at": "TEXT",
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

            CREATE TRIGGER IF NOT EXISTS trg_tasks_single_running_browser_update
            BEFORE UPDATE OF status ON tasks
            WHEN NEW.status='running' AND OLD.status<>'running'
            BEGIN
                SELECT RAISE(ABORT, 'AUTH_ANOTHER_TASK_ACTIVE')
                 WHERE EXISTS (
                    SELECT 1 FROM tasks
                     WHERE status='running' AND id<>NEW.id
                 );
                SELECT RAISE(ABORT, 'AUTH_EDIT_BATCH_ACTIVE')
                 WHERE EXISTS (
                    SELECT 1 FROM edit_batches
                     WHERE status IN ('running', 'stop_requested')
                 );
            END;

            CREATE TRIGGER IF NOT EXISTS trg_tasks_single_running_browser_insert
            BEFORE INSERT ON tasks
            WHEN NEW.status='running'
            BEGIN
                SELECT RAISE(ABORT, 'AUTH_ANOTHER_TASK_ACTIVE')
                 WHERE EXISTS (SELECT 1 FROM tasks WHERE status='running');
                SELECT RAISE(ABORT, 'AUTH_EDIT_BATCH_ACTIVE')
                 WHERE EXISTS (
                    SELECT 1 FROM edit_batches
                     WHERE status IN ('running', 'stop_requested')
                 );
            END;

            CREATE TRIGGER IF NOT EXISTS trg_edit_batches_single_browser_update
            BEFORE UPDATE OF status ON edit_batches
            WHEN NEW.status IN ('running', 'stop_requested')
             AND OLD.status NOT IN ('running', 'stop_requested')
            BEGIN
                SELECT RAISE(ABORT, 'LEGACY_TASK_ACTIVE')
                 WHERE EXISTS (SELECT 1 FROM tasks WHERE status='running');
            END;

            CREATE TRIGGER IF NOT EXISTS trg_edit_batches_single_browser_insert
            BEFORE INSERT ON edit_batches
            WHEN NEW.status IN ('running', 'stop_requested')
            BEGIN
                SELECT RAISE(ABORT, 'LEGACY_TASK_ACTIVE')
                 WHERE EXISTS (SELECT 1 FROM tasks WHERE status='running');
            END;
            """
        )
        _ensure_columns(
            conn,
            "templates",
            {
                "requires_manual_configuration": "INTEGER NOT NULL DEFAULT 0",
                "quarantine_reason": "TEXT",
            },
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
                "published": "INTEGER",
                "save_result_json": "TEXT NOT NULL DEFAULT '{}'",
                "summary_json": "TEXT NOT NULL DEFAULT '{}'",
            },
        )
        _ensure_columns(
            conn,
            "plan_snapshots",
            {
                "idempotency_key": "TEXT",
                "task_id": "INTEGER",
            },
        )
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_plan_snapshots_idempotency
                ON plan_snapshots (idempotency_key)
                WHERE idempotency_key IS NOT NULL
            """
        )
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_plan_snapshots_task
                ON plan_snapshots (task_id)
                WHERE task_id IS NOT NULL
            """
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO plan_snapshot_idempotency_keys (
                idempotency_key, snapshot_id, snapshot_hash, created_at
            )
            SELECT idempotency_key, id, snapshot_hash, created_at
              FROM plan_snapshots
             WHERE idempotency_key IS NOT NULL
            """
        )
        migrate_reports_published_to_tristate(conn)
        disable_legacy_generated_starter_templates(conn)
        disable_edit_batch_bundles_with_quarantined_sources(conn)
        disable_unexecutable_edit_batch_bundles(conn)


def _ensure_columns(conn: sqlite3.Connection, table_name: str, columns: dict[str, str]) -> None:
    existing = {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    for column_name, column_definition in columns.items():
        if column_name not in existing:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}")


def migrate_reports_published_to_tristate(conn: sqlite3.Connection) -> bool:
    """Replace legacy default-false publication state with nullable truth."""

    published_column = next(
        (
            row
            for row in conn.execute("PRAGMA table_info(reports)").fetchall()
            if row["name"] == "published"
        ),
        None,
    )
    if published_column is None:
        conn.execute("ALTER TABLE reports ADD COLUMN published INTEGER")
        published_column = next(
            row
            for row in conn.execute("PRAGMA table_info(reports)").fetchall()
            if row["name"] == "published"
        )
    raw_default = published_column.get("dflt_value")
    normalized_default = (
        str(raw_default).strip().strip("()").strip().strip("'\"").lower()
        if raw_default is not None
        else None
    )
    legacy_default_false = (
        int(published_column.get("notnull") or 0) != 0
        or normalized_default in {"0", "false"}
    )
    table_row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='reports'"
    ).fetchone()
    normalized_sql = " ".join(str((table_row or {}).get("sql") or "").lower().split())
    has_tristate_check = (
        "published integer check (published is null or published in (0, 1))"
        in normalized_sql
    )
    if not legacy_default_false and has_tristate_check:
        return False

    # Zeros from the legacy NOT NULL/default-false schema never proved a
    # no-publish result.  A nullable/default-free table already had tri-state
    # semantics, so preserve its explicit zero while adding the DB constraint.
    published_projection = (
        "CASE WHEN published = 1 THEN 1 ELSE NULL END"
        if legacy_default_false
        else "CASE WHEN published = 1 THEN 1 WHEN published = 0 THEN 0 ELSE NULL END"
    )
    conn.execute("ALTER TABLE reports RENAME TO reports__legacy_published")
    conn.execute(
        """
        CREATE TABLE reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            job_id INTEGER,
            product_id INTEGER,
            status TEXT NOT NULL,
            published INTEGER CHECK (published IS NULL OR published IN (0, 1)),
            save_result_json TEXT NOT NULL,
            summary_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        f"""
        INSERT INTO reports (
            id, task_id, job_id, product_id, status, published,
            save_result_json, summary_json, created_at, updated_at
        )
        SELECT
            id, task_id, job_id, product_id, status,
            {published_projection},
            save_result_json, summary_json, created_at, updated_at
          FROM reports__legacy_published
         ORDER BY id ASC
        """
    )
    conn.execute("DROP TABLE reports__legacy_published")
    return True


def disable_legacy_generated_starter_templates(conn: sqlite3.Connection) -> list[int]:
    """Disable only complete packs that exactly reproduce the retired generator."""

    rows = conn.execute(
        """
        SELECT id, template_type, template_name, binding_scope, payload_json, is_enabled
          FROM templates
         WHERE template_name LIKE '%起步模板%'
         ORDER BY id ASC
        """
    ).fetchall()
    expected_types = {
        "category",
        "sku",
        "pricing",
        "logistics",
        "image",
        "compliance",
        "semi_managed",
        "dxm_reference",
    }
    cohorts: dict[tuple[str, str, str], list[tuple[dict[str, Any], str]]] = {}
    for row in rows:
        identity = _exact_legacy_generated_starter_identity(row)
        if identity is None:
            continue
        store_name, category_name, platform, template_type = identity
        cohorts.setdefault((store_name, category_name, platform), []).append(
            (row, template_type)
        )
    matched_ids: list[int] = []
    for cohort in cohorts.values():
        # The retired code generated one exact row for every type in one call.
        # Partial or duplicate packs are ambiguous and deliberately left alone.
        if len(cohort) != len(expected_types) or {item[1] for item in cohort} != expected_types:
            continue
        matched_ids.extend(
            int(row["id"])
            for row, _template_type in cohort
        )
    quarantined_at = datetime.now(timezone.utc).isoformat()
    candidate_ids = [
        int(row["id"])
        for cohort in cohorts.values()
        for row, _template_type in cohort
    ]
    for template_id in candidate_ids:
        conn.execute(
            """
            UPDATE templates
               SET requires_manual_configuration=1,
                   quarantine_reason='LEGACY_STARTER_REQUIRES_MANUAL_CONFIGURATION',
                   updated_at=?
             WHERE id=?
               AND requires_manual_configuration=0
            """,
            (quarantined_at, template_id),
        )
    for template_id in matched_ids:
        conn.execute(
            """
            UPDATE templates
               SET is_enabled=0,
                   requires_manual_configuration=1,
                   quarantine_reason='LEGACY_GENERATED_STARTER_EXACT_MATCH',
                   updated_at=?
             WHERE id=?
               AND (
                   is_enabled<>0
                   OR requires_manual_configuration<>1
                   OR COALESCE(quarantine_reason, '')<>'LEGACY_GENERATED_STARTER_EXACT_MATCH'
               )
            """,
            (quarantined_at, template_id),
        )
    return matched_ids


def disable_edit_batch_bundles_with_quarantined_sources(
    conn: sqlite3.Connection,
) -> list[int]:
    quarantined_source_ids = {
        int(row["id"])
        for row in conn.execute(
            """
            SELECT id FROM templates
             WHERE requires_manual_configuration=1
               AND template_type<>'edit_batch_bundle'
            """
        ).fetchall()
    }
    if not quarantined_source_ids:
        return []
    rows = conn.execute(
        """
        SELECT id, payload_json FROM templates
         WHERE template_type='edit_batch_bundle'
        """
    ).fetchall()
    affected: list[int] = []
    for row in rows:
        try:
            payload = json.loads(str(row.get("payload_json") or ""))
        except (TypeError, ValueError):
            continue
        sources = payload.get("source_templates") if isinstance(payload, dict) else None
        if not isinstance(sources, dict):
            continue
        referenced_ids = {
            int(source["template_id"])
            for source in sources.values()
            if isinstance(source, dict)
            and isinstance(source.get("template_id"), int)
            and not isinstance(source.get("template_id"), bool)
        }
        if not referenced_ids.intersection(quarantined_source_ids):
            continue
        affected.append(int(row["id"]))
    if not affected:
        return []
    updated_at = datetime.now(timezone.utc).isoformat()
    for template_id in affected:
        conn.execute(
            """
            UPDATE templates
               SET is_enabled=0,
                   requires_manual_configuration=1,
                   quarantine_reason='BUNDLE_REFERENCES_QUARANTINED_SOURCE',
                   updated_at=?
             WHERE id=?
               AND (
                   is_enabled<>0
                   OR requires_manual_configuration<>1
                   OR COALESCE(quarantine_reason, '')<>'BUNDLE_REFERENCES_QUARANTINED_SOURCE'
               )
            """,
            (updated_at, template_id),
        )
    return affected


def disable_unexecutable_edit_batch_bundles(conn: sqlite3.Connection) -> list[int]:
    """Quarantine only exact bundle shapes that current execution must reject."""

    rows = conn.execute(
        """
        SELECT id, payload_json
          FROM templates
         WHERE template_type='edit_batch_bundle' AND is_enabled=1
         ORDER BY id ASC
        """
    ).fetchall()
    disabled_ids: list[int] = []
    bundle_keys = {
        "schema_version",
        "version",
        "required_sections",
        "binding",
        "source_templates",
        "sections",
    }
    binding_keys = {"store_id", "store_name", "category_name", "platform"}
    section_names = {
        "category",
        "sku",
        "pricing",
        "logistics",
        "image",
        "compliance",
        "semi_managed",
        "dxm_reference",
    }
    ordered_section_names = [
        "category",
        "sku",
        "pricing",
        "logistics",
        "image",
        "compliance",
        "semi_managed",
        "dxm_reference",
    ]
    reference_names = {
        "attribute_info",
        "description",
        "freight",
        "service",
        "eu_responsible",
        "manufacturer",
        "compliance",
        "semi_managed",
    }
    unsupported_names = {"description", "compliance", "semi_managed"}
    for row in rows:
        try:
            payload = json.loads(str(row.get("payload_json") or ""))
        except (TypeError, ValueError):
            continue
        if (
            not isinstance(payload, dict)
            or set(payload) != bundle_keys
            or payload.get("schema_version") != "dxm_edit_template_bundle.v1"
        ):
            continue
        binding = payload.get("binding")
        sections = payload.get("sections")
        source_templates = payload.get("source_templates")
        if (
            not isinstance(payload.get("version"), str)
            or not payload["version"].strip()
            or payload.get("required_sections") != ordered_section_names
            or not isinstance(binding, dict)
            or set(binding) != binding_keys
            or not isinstance(sections, dict)
            or set(sections) != section_names
            or not isinstance(source_templates, dict)
            or set(source_templates) != section_names
            or isinstance(binding.get("store_id"), bool)
            or not isinstance(binding.get("store_id"), int)
            or binding["store_id"] <= 0
            or not isinstance(binding.get("store_name"), str)
            or not binding["store_name"].strip()
            or not isinstance(binding.get("platform"), str)
            or not binding["platform"].strip()
            or (
                binding.get("category_name") is not None
                and not isinstance(binding.get("category_name"), str)
            )
        ):
            continue
        category_name = binding.get("category_name")
        category_bound = isinstance(category_name, str) and bool(category_name.strip())
        dxm_reference = sections.get("dxm_reference")
        references = (
            dxm_reference.get("dxm_reference_templates")
            if isinstance(dxm_reference, dict)
            and set(dxm_reference) == {"dxm_reference_templates"}
            else None
        )
        unsupported_configured = False
        if isinstance(references, dict) and set(references) == reference_names:
            exact_reference_shape = all(
                isinstance(config, dict)
                and set(config) == {"names", "required"}
                and isinstance(config.get("names"), list)
                and all(
                    isinstance(value, str)
                    and bool(value.strip())
                    and value == value.strip()
                    for value in config["names"]
                )
                and isinstance(config.get("required"), bool)
                for config in references.values()
            )
            if exact_reference_shape:
                unsupported_configured = any(
                    references[name]["required"] is True
                    or any(
                        isinstance(value, str) and bool(value.strip())
                        for value in references[name]["names"]
                    )
                    for name in unsupported_names
                )
        if category_bound or unsupported_configured:
            disabled_ids.append(int(row["id"]))

    if not disabled_ids:
        return []
    disabled_at = datetime.now(timezone.utc).isoformat()
    for template_id in disabled_ids:
        conn.execute(
            """
            UPDATE templates
               SET is_enabled=0, updated_at=?
             WHERE id=? AND template_type='edit_batch_bundle' AND is_enabled=1
            """,
            (disabled_at, template_id),
        )
    return disabled_ids


def _exact_legacy_generated_starter_identity(
    row: dict[str, Any],
) -> tuple[str, str, str, str] | None:
    try:
        payload = json.loads(str(row.get("payload_json") or ""))
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    binding = payload.get("binding")
    if not isinstance(binding, dict) or set(binding) != {
        "store_name",
        "category_name",
        "platform",
    }:
        return None
    store_name = binding.get("store_name")
    category_name = binding.get("category_name")
    platform = binding.get("platform")
    if any(
        not isinstance(value, str) or not value or value != value.strip()
        for value in (store_name, category_name, platform)
    ):
        return None
    template_type = str(row.get("template_type") or "").strip().lower()
    expected_name, expected_payload = _legacy_generated_starter_signature(
        template_type,
        binding=dict(binding),
        category_name=category_name,
    )
    if expected_name is None or expected_payload is None:
        return None
    if (
        row.get("template_type") != template_type
        or row.get("template_name") != expected_name
        or row.get("binding_scope")
        != f"店铺：{store_name} / 类目：{category_name} / 平台：{platform}"
        or payload != expected_payload
    ):
        return None
    return store_name, category_name, platform, template_type


def _legacy_generated_starter_signature(
    template_type: str,
    *,
    binding: dict[str, str],
    category_name: str,
) -> tuple[str | None, dict[str, Any] | None]:
    references = _legacy_generated_reference_templates(category_name)
    payloads: dict[str, tuple[str, dict[str, Any]]] = {
        "category": (
            "类目与标题起步模板",
            {
                "binding": binding,
                "category": {
                    "category_keyword": "立牌" if "立牌" in category_name else category_name,
                    "category_match": "ACG Stand",
                    "title_strategy": "按来源标题生成英文标题",
                    "title_keyword_map": _legacy_generated_title_keyword_map(category_name),
                    "attribute_template_priorities": references["attribute_info"]["names"],
                },
            },
        ),
        "sku": (
            "SKU与库存起步模板",
            {
                "binding": binding,
                "sku": {
                    "goods_code_strategy": "按来源商品ID生成安全货号",
                    "barcode_strategy": "留空",
                    "stock": "200",
                    "jit_stock": "100",
                },
            },
        ),
        "pricing": (
            "价格策略起步模板",
            {
                "binding": binding,
                "pricing": {
                    "declared_value": "1",
                    "stock": "200",
                    "product_price": "7.01",
                    "supply_price": "5.20",
                },
            },
        ),
        "logistics": (
            "包装物流起步模板",
            {
                "binding": binding,
                "logistics": {
                    "weight": "0.03",
                    "length": "10",
                    "width": "10",
                    "height": "2",
                    "freight_templates": references["freight"]["names"],
                    "service_templates": references["service"]["names"],
                    "logistics_attribute": "普货",
                    "is_original_box": "否",
                },
            },
        ),
        "image": (
            "图片与素材起步模板",
            {
                "binding": binding,
                "image": {
                    "source": "图片银行（速卖通）",
                    "eu_outer_package_filename": "微信图片_202504092228421.jpg",
                    "marketing_images_strategy": "使用 EU 外包装图补齐 3:4",
                    "main_image_strategy": "保留 800x800 合规主图",
                    "invalid_image_strategy": "删除 0x0 无效图",
                },
            },
        ),
        "compliance": (
            "合规海关起步模板",
            {
                "binding": binding,
                "compliance": {
                    "eu_responsible_names": references["eu_responsible"]["names"],
                    "manufacturer_names": references["manufacturer"]["names"],
                    "customs_product_names": ["钥匙扣", "keychain"],
                    "customs_name": "钥匙扣",
                    "material": "Acrylic",
                    "purpose": "Decoration",
                    "brand": "无品牌",
                    "statement": "符合平台合规要求",
                },
            },
        ),
        "semi_managed": (
            "半托管起步模板",
            {
                "binding": binding,
                "semi_managed": {
                    "product_price": "7.01",
                    "supply_price": "5.20",
                    "jit_stock": "100",
                    "is_original_box": "否",
                    "length": "10",
                    "width": "10",
                    "height": "2",
                    "goods_code_strategy": "按来源商品ID生成安全货号",
                    "barcode_strategy": "留空",
                },
            },
        ),
        "dxm_reference": (
            "店小秘引用模板起步模板",
            {
                "binding": binding,
                "dxm_reference_templates": references,
            },
        ),
    }
    signature = payloads.get(template_type)
    if signature is None:
        return None, None
    name_suffix, payload = signature
    return f"{category_name} / {name_suffix}", payload


def _legacy_generated_reference_templates(category_name: str) -> dict[str, Any]:
    attribute_names = (
        ["万代立牌", "bilibili动漫周边", "万代"]
        if "立牌" in category_name
        else [f"{category_name}属性模板"]
    )
    return {
        "attribute_info": {"names": attribute_names, "required": True},
        "description": {"names": ["详情描述模板-ACG立牌"], "required": True},
        "freight": {"names": ["石油40g普货包裹.", "40g普货包裹"], "required": True},
        "service": {"names": ["Service Template for New Sellers"], "required": True},
        "eu_responsible": {"names": ["Jacqueiline Marti"], "required": True},
        "manufacturer": {
            "names": ["jiyang county thunder", "Jiyang County thunder"],
            "required": True,
        },
        "compliance": {"names": ["合规模板", "钥匙扣", "keychain"], "required": True},
        "semi_managed": {"names": ["半托管模板"], "required": True},
    }


def _legacy_generated_title_keyword_map(category_name: str) -> dict[str, str]:
    mappings = {
        "宝可梦": "Pokemon",
        "神奇宝贝": "Pokemon",
        "皮卡丘": "Pikachu",
        "仙子伊布": "Sylveon",
        "伊布": "Eevee",
        "精灵球": "Poke Ball",
        "3D打印": "3D Printed",
        "玩具模型": "Toy Model",
        "模型": "Model",
        "周边": "Collectible",
        "礼物": "Gift",
        "球体摆件": "Ball Ornament",
        "摆件": "Ornament",
        "钥匙扣": "Keychain",
        "亚克力": "Acrylic",
        "高颜值": "Decorative",
    }
    if "立牌" in category_name:
        mappings["立牌"] = "Display Stand"
    return mappings


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
