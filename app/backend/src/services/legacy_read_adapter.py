"""
LegacyReadAdapter — backward-compatible read adapter for historical tasks/jobs/receipts.

All old write interfaces return HTTP 410 (Gone).  Only read paths remain functional.
Use V1TaskRunner for new execution workflows.
"""

from __future__ import annotations

from typing import Any

from src.db import connection


class LegacyReadAdapter:
    """Read-only adapter for legacy batch edit batch/task/job/receipt data.

    All write operations have been removed.  Use V1TaskRunner for new workflows.
    """

    def get_batch(self, batch_id: int) -> dict[str, Any] | None:
        """Read a batch by ID (read-only, backward compatible)."""
        with connection() as conn:
            row = conn.execute(
                "SELECT * FROM edit_batches WHERE id=?",
                (batch_id,),
            ).fetchone()
            if not row:
                return None
            return dict(row)

    def list_batches(
        self,
        store_id: int | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List batches with optional filters (read-only)."""
        query = "SELECT * FROM edit_batches"
        params: list[Any] = []
        conditions: list[str] = []

        if store_id is not None:
            conditions.append("store_id=?")
            params.append(store_id)
        if status is not None:
            conditions.append("status=?")
            params.append(status)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        with connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]

    def get_batch_items(self, batch_id: int) -> list[dict[str, Any]]:
        """Read items belonging to a batch (read-only)."""
        with connection() as conn:
            rows = conn.execute(
                "SELECT * FROM edit_batch_items WHERE batch_id=? ORDER BY id ASC",
                (batch_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_task(self, task_id: int) -> dict[str, Any] | None:
        """Read a task by ID (read-only)."""
        with connection() as conn:
            row = conn.execute(
                "SELECT * FROM tasks WHERE id=?",
                (task_id,),
            ).fetchone()
            return dict(row) if row else None

    def get_job(self, job_id: int) -> dict[str, Any] | None:
        """Read a job by ID (read-only)."""
        with connection() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE id=?",
                (job_id,),
            ).fetchone()
            return dict(row) if row else None

    def get_receipt(self, receipt_id: int) -> dict[str, Any] | None:
        """Read an execution receipt by ID (read-only)."""
        with connection() as conn:
            row = conn.execute(
                "SELECT * FROM execution_receipts WHERE id=?",
                (receipt_id,),
            ).fetchone()
            return dict(row) if row else None

    def get_mutation_ledger_entries(
        self,
        task_id: str,
        job_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Read mutation ledger entries for a task/job (read-only)."""
        with connection() as conn:
            if job_id is not None:
                rows = conn.execute(
                    """
                    SELECT * FROM mutation_dispatch_ledger
                    WHERE task_id=? AND job_id=?
                    ORDER BY ordinal ASC
                    """,
                    (task_id, job_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM mutation_dispatch_ledger
                    WHERE task_id=?
                    ORDER BY ordinal ASC
                    """,
                    (task_id,),
                ).fetchall()
            return [dict(row) for row in rows]

    def get_ownership_locks(
        self,
        task_id: int | None = None,
        product_id: int | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """Read ownership locks with optional filters (read-only)."""
        conditions: list[str] = []
        params: list[Any] = []

        if task_id is not None:
            conditions.append("task_id=?")
            params.append(task_id)
        if product_id is not None:
            conditions.append("product_id=?")
            params.append(product_id)
        if status is not None:
            conditions.append("status=?")
            params.append(status)

        query = "SELECT * FROM ownership_locks"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY id DESC"

        with connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]

    def get_writer_fence(
        self,
        writer_fence_id: str,
    ) -> dict[str, Any] | None:
        """Read a writer fence by ID (read-only)."""
        with connection() as conn:
            row = conn.execute(
                "SELECT * FROM writer_fences WHERE writer_fence_id=?",
                (writer_fence_id,),
            ).fetchone()
            return dict(row) if row else None

    def get_active_writer_fences(
        self,
        shop_id: str,
    ) -> list[dict[str, Any]]:
        """Read all active writer fences for a shop (read-only)."""
        from datetime import datetime
        now = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

        with connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM writer_fences
                WHERE shop_id=? AND status='active' AND expires_at>?
                ORDER BY id DESC
                """,
                (shop_id, now),
            ).fetchall()
            return [dict(row) for row in rows]
