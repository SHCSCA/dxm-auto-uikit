from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.db import connection, dumps
from src.utils import now_iso


class PlanSnapshotStoreError(RuntimeError):
    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(message)


class PlanSnapshotStore:
    """Persist one immutable E2 snapshot and its draft task atomically."""

    def freeze_with_task(
        self,
        snapshot: Mapping[str, Any],
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        now = now_iso()
        with connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                """
                SELECT snapshot.*
                  FROM plan_snapshot_idempotency_keys AS binding
                  JOIN plan_snapshots AS snapshot
                    ON snapshot.id=binding.snapshot_id
                 WHERE binding.idempotency_key=?
                """,
                (idempotency_key,),
            ).fetchone()
            if existing:
                if existing["snapshot_hash"] != snapshot["snapshot_hash"]:
                    raise PlanSnapshotStoreError(
                        "PLAN_SNAPSHOT_IDEMPOTENCY_CONFLICT",
                        "idempotency_key is already bound to another snapshot",
                    )
                if existing.get("task_id") is None:
                    raise PlanSnapshotStoreError(
                        "PLAN_SNAPSHOT_ATOMICITY_INVALID",
                        "idempotent snapshot is missing its atomic task",
                    )
                return existing

            existing = conn.execute(
                "SELECT * FROM plan_snapshots WHERE snapshot_hash=?",
                (snapshot["snapshot_hash"],),
            ).fetchone()
            if existing:
                if existing.get("task_id") is None:
                    task_id = self._insert_task(
                        conn,
                        snapshot_id=int(existing["id"]),
                        snapshot=snapshot,
                        now=now,
                    )
                    conn.execute(
                        """
                        UPDATE plan_snapshots
                           SET idempotency_key=COALESCE(idempotency_key, ?),
                               task_id=?
                         WHERE id=?
                        """,
                        (idempotency_key, task_id, int(existing["id"])),
                    )
                    existing = conn.execute(
                        "SELECT * FROM plan_snapshots WHERE id=?",
                        (int(existing["id"]),),
                    ).fetchone()
                self._bind_idempotency_key(
                    conn,
                    idempotency_key=idempotency_key,
                    snapshot_id=int(existing["id"]),
                    snapshot_hash=str(existing["snapshot_hash"]),
                    created_at=now,
                )
                return existing

            cursor = conn.execute(
                """
                INSERT INTO plan_snapshots (
                    local_plan_template_id, snapshot_hash, snapshot_json,
                    idempotency_key, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    snapshot["local_plan_template"]["id"],
                    snapshot["snapshot_hash"],
                    dumps(snapshot),
                    idempotency_key,
                    now,
                ),
            )
            snapshot_id = int(cursor.lastrowid)
            task_id = self._insert_task(
                conn,
                snapshot_id=snapshot_id,
                snapshot=snapshot,
                now=now,
            )
            conn.execute(
                "UPDATE plan_snapshots SET task_id=? WHERE id=?",
                (task_id, snapshot_id),
            )
            self._bind_idempotency_key(
                conn,
                idempotency_key=idempotency_key,
                snapshot_id=snapshot_id,
                snapshot_hash=str(snapshot["snapshot_hash"]),
                created_at=now,
            )
            return conn.execute(
                "SELECT * FROM plan_snapshots WHERE id=?",
                (snapshot_id,),
            ).fetchone()

    @staticmethod
    def get(snapshot_id: int) -> dict[str, Any] | None:
        with connection() as conn:
            return conn.execute(
                "SELECT * FROM plan_snapshots WHERE id=?",
                (snapshot_id,),
            ).fetchone()

    @staticmethod
    def _bind_idempotency_key(
        conn: Any,
        *,
        idempotency_key: str,
        snapshot_id: int,
        snapshot_hash: str,
        created_at: str,
    ) -> None:
        conn.execute(
            """
            INSERT INTO plan_snapshot_idempotency_keys (
                idempotency_key, snapshot_id, snapshot_hash, created_at
            ) VALUES (?, ?, ?, ?)
            """,
            (
                idempotency_key,
                snapshot_id,
                snapshot_hash,
                created_at,
            ),
        )

    @staticmethod
    def _insert_task(
        conn: Any,
        *,
        snapshot_id: int,
        snapshot: Mapping[str, Any],
        now: str,
    ) -> int:
        product_ids = [int(value) for value in snapshot["product_ids"]]
        task_payload = {
            "plan_snapshot_id": snapshot_id,
            "plan_snapshot_hash": snapshot["snapshot_hash"],
            "plan_snapshot": dict(snapshot),
            "path": "A",
            "publish_allowed": False,
            "runner_released": False,
            "product_ids": product_ids,
            "claim_mark": "E2_PLAN_SNAPSHOT_FROZEN",
            "execution_mode": "batch_draft_save",
            "max_count": len(product_ids),
        }
        cursor = conn.execute(
            """
            INSERT INTO tasks (
                name, store_id, status, mode, publish_scene, total_jobs,
                payload_json, created_at, updated_at
            ) VALUES (?, ?, 'draft', 'batch_draft_save', ?, ?, ?, ?, ?)
            """,
            (
                f"批量只保存 · 方案快照 {snapshot['snapshot_hash'][:12]}",
                int(snapshot["shop_scope"]),
                "SMT_SEMI_MANAGED_SAVE_ONLY",
                len(product_ids),
                dumps(task_payload),
                now,
                now,
            ),
        )
        task_id = int(cursor.lastrowid)
        for product_id in product_ids:
            conn.execute(
                """
                INSERT INTO jobs (
                    task_id, product_id, status, created_at, updated_at
                ) VALUES (?, ?, 'pending', ?, ?)
                """,
                (task_id, product_id, now, now),
            )
        return task_id
