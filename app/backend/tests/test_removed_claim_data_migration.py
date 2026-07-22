from __future__ import annotations

from src import db
from src.repository import Repository
from src.services.ownership_lock import OwnershipLockService


def test_removed_workflow_records_are_quarantined_and_not_reused(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "removed-workflow.db")
    db.init_db()
    now = "2026-07-22T00:00:00Z"
    with db.connection() as conn:
        product_id = conn.execute(
            """
            INSERT INTO products (
                title, source, status, category_name, price, currency,
                sku_count, image_count, payload_json, created_at, updated_at
            ) VALUES (?, 'dxm_data_acquisition', 'claimed_to_draft', ?, 1, 'USD', 1, 1, ?, ?, ?)
            """,
            (
                "legacy product",
                "legacy category",
                db.dumps(
                    {
                        "store_id": 7,
                        "store_name": "Legacy Store",
                        "draft_box_verified": True,
                        "source_url": "https://example.com/legacy-product",
                        "source_urls": ["https://example.com/legacy-product"],
                        "product_box_evidence_ref": {"path": "legacy.png"},
                        "product_box_target_identity": {"legacy": True},
                        "draft_box_proof": {"proof_content": {"evidence_ref": {"path": "legacy.png"}}},
                    }
                ),
                now,
                now,
            ),
        ).lastrowid
        task_id = conn.execute(
            """
            INSERT INTO tasks (
                name, store_id, status, mode, publish_scene, total_jobs,
                payload_json, created_at, updated_at
            ) VALUES ('legacy task', 7, 'draft', 'claim_only', 'save_only', 1, ?, ?, ?)
            """,
            (db.dumps({"product_ids": [product_id], "draft_box_verified": True}), now, now),
        ).lastrowid
        conn.execute(
            """
            INSERT INTO jobs (task_id, product_id, status, created_at, updated_at)
            VALUES (?, ?, 'pending', ?, ?)
            """,
            (task_id, product_id, now, now),
        )
        job_id = conn.execute(
            "SELECT id FROM jobs WHERE task_id=?",
            (task_id,),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO job_logs (task_id, job_id, level, message, context_json, created_at) VALUES (?, ?, 'info', 'legacy log', '{}', ?)",
            (task_id, job_id, now),
        )
        conn.execute(
            "INSERT INTO job_evidences (task_id, job_id, evidence_type, file_path, meta_json, created_at) VALUES (?, ?, 'legacy', NULL, '{}', ?)",
            (task_id, job_id, now),
        )
        conn.execute(
            "INSERT INTO exceptions (task_id, job_id, error_code, field_domain, title, detail, suggestion, created_at, updated_at) VALUES (?, ?, 'LEGACY', 'workflow', 'legacy', 'legacy', 'none', ?, ?)",
            (task_id, job_id, now, now),
        )
        conn.execute(
            "INSERT INTO reports (task_id, job_id, product_id, status, published, save_result_json, summary_json, created_at, updated_at) VALUES (?, ?, ?, 'failed', NULL, '{}', '{}', ?, ?)",
            (task_id, job_id, product_id, now, now),
        )
        downstream_task_id = conn.execute(
            """
            INSERT INTO tasks (
                name, store_id, status, mode, publish_scene, total_jobs,
                payload_json, created_at, updated_at
            ) VALUES ('legacy downstream save', 7, 'completed', 'single_save', 'save_only', 1, ?, ?, ?)
            """,
            (
                db.dumps({"product_ids": [product_id], "claim_task_id": task_id}),
                now,
                now,
            ),
        ).lastrowid
        conn.execute(
            """
            INSERT INTO jobs (task_id, product_id, status, created_at, updated_at)
            VALUES (?, ?, 'completed', ?, ?)
            """,
            (downstream_task_id, product_id, now, now),
        )

    db.init_db()

    with db.connection() as conn:
        product = conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
        task = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        downstream_task = conn.execute(
            "SELECT * FROM tasks WHERE id=?",
            (downstream_task_id,),
        ).fetchone()
        job = conn.execute("SELECT * FROM jobs WHERE task_id=?", (task_id,)).fetchone()

    assert product["source"] == "removed_workflow_legacy"
    assert product["status"] == "quarantined"
    product_payload = db.loads(product["payload_json"], {})
    assert product_payload == {
        "legacy_record_quarantined": True,
        "product_box_recapture_required": True,
        "store_id": 7,
        "store_name": "Legacy Store",
    }
    assert task["mode"] == "removed_workflow_legacy"
    assert task["status"] == "archived"
    assert db.loads(task["payload_json"], {}) == {
        "legacy_record_quarantined": True,
        "removed_workflow": True,
    }
    assert job["status"] == "cancelled"
    assert job["error_code"] == "FEATURE_REMOVED"
    assert downstream_task["mode"] == "removed_workflow_legacy"
    assert downstream_task["status"] == "archived"

    repo = Repository()
    assert all(item["id"] != product_id for item in repo.list_products())
    assert all(item["id"] != task_id for item in repo.list_tasks())
    assert all(item["id"] != downstream_task_id for item in repo.list_tasks())
    assert repo.get_task(task_id) is None
    assert repo.list_logs() == []
    assert repo.list_evidences() == []
    assert repo.list_exceptions() == []
    assert repo.list_reports() == []


def test_legacy_quarantine_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "removed-workflow-idempotent.db")
    db.init_db()
    db.init_db()

    with db.connection() as conn:
        assert db.migrate_legacy_product_box_rows(conn) == []
        assert db.migrate_legacy_claim_tasks(conn) == []


def test_legacy_ownership_lock_schema_is_rebuilt_with_neutral_tags(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "legacy-ownership-lock.db")
    with db.connection() as conn:
        conn.executescript(
            """
            CREATE TABLE ownership_locks (
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
            """
        )
        conn.execute(
            """
            INSERT INTO ownership_locks (
                lock_token, ownership_fingerprint, task_id, job_id, product_id,
                store_name, source_title, claim_mark, status, expires_at,
                created_at, updated_at
            ) VALUES ('legacy-token', 'legacy-fingerprint', 1, 1, 1,
                      'Legacy Store', 'Legacy Product', 'DXM-LOCK-1-1', 'released',
                      '2026-07-22T01:00:00Z', '2026-07-22T00:00:00Z',
                      '2026-07-22T00:00:00Z')
            """
        )

    db.init_db()

    with db.connection() as conn:
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(ownership_locks)").fetchall()
        }
        migrated = conn.execute(
            "SELECT * FROM ownership_locks WHERE lock_token='legacy-token'"
        ).fetchone()
    assert "ownership_tag" in columns
    assert "claim_mark" not in columns
    assert "page_claim_mark" not in columns
    assert migrated["ownership_tag"] == "DXM-LOCK-1-1"

    created = OwnershipLockService().acquire_lock(
        task_id=2,
        job_id=2,
        product_id=2,
        store_name="Live Store",
        source_title="Live Product",
    )
    assert created["acquired"] is True
    assert created["ownership_tag"] == "DXM-LOCK-2-2"
