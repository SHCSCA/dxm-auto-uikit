from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from uuid import uuid4

from src.db import connection


class OwnershipLockService:
    def __init__(self, lock_ttl_seconds: int = 30 * 60):
        self.lock_ttl_seconds = lock_ttl_seconds

    def build_claim_mark(self, base_mark: str, task_id: int, job_id: int | None = None) -> str:
        if job_id is None:
            return f"{base_mark}-{task_id}"
        return f"{base_mark}-{task_id}-{job_id}"

    def acquire_lock(
        self,
        task_id: int,
        job_id: int,
        product_id: int,
        store_name: str,
        source_title: str,
        sku_prefix: str | None = None,
        claim_mark_base: str = "AI认领",
        lock_owner_run_id: str | None = None,
    ) -> dict:
        now = self._now_iso()
        expires_at = self._expires_at_iso()
        claim_mark = self.build_claim_mark(claim_mark_base, task_id, job_id)
        fingerprint = self._build_fingerprint(
            product_id=product_id,
            store_name=store_name,
            source_title=source_title,
            sku_prefix=sku_prefix,
        )

        with connection() as conn:
            active_lock = conn.execute(
                """
                SELECT * FROM ownership_locks
                WHERE ownership_fingerprint=?
                  AND status='active'
                  AND expires_at>?
                ORDER BY id DESC
                LIMIT 1
                """,
                (fingerprint, now),
            ).fetchone()

            if active_lock and active_lock["task_id"] != task_id:
                return self._result(
                    acquired=False,
                    conflict=True,
                    lock_token=active_lock["lock_token"],
                    claim_mark=active_lock["claim_mark"],
                    status="conflict",
                    reason="ownership_locked",
                )

            if active_lock:
                conn.execute(
                    """
                    UPDATE ownership_locks
                    SET job_id=?, claim_mark=?, lock_owner_run_id=?, expires_at=?, updated_at=?
                    WHERE lock_token=?
                    """,
                    (
                        job_id,
                        claim_mark,
                        lock_owner_run_id,
                        expires_at,
                        now,
                        active_lock["lock_token"],
                    ),
                )
                return self._result(
                    acquired=True,
                    conflict=False,
                    lock_token=active_lock["lock_token"],
                    claim_mark=claim_mark,
                    status="refreshed",
                    reason="lock_refreshed",
                )

            lock_token = uuid4().hex
            conn.execute(
                """
                INSERT INTO ownership_locks (
                    lock_token,
                    ownership_fingerprint,
                    task_id,
                    job_id,
                    product_id,
                    store_name,
                    source_title,
                    sku_prefix,
                    claim_mark,
                    lock_owner_run_id,
                    status,
                    expires_at,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
                """,
                (
                    lock_token,
                    fingerprint,
                    task_id,
                    job_id,
                    product_id,
                    store_name,
                    source_title,
                    sku_prefix,
                    claim_mark,
                    lock_owner_run_id,
                    expires_at,
                    now,
                    now,
                ),
            )
            return self._result(
                acquired=True,
                conflict=False,
                lock_token=lock_token,
                claim_mark=claim_mark,
                status="acquired",
                reason="lock_acquired",
            )

    def mark_page_claim_verified(self, lock_token: str, page_claim_mark: str) -> dict:
        now = self._now_iso()
        with connection() as conn:
            lock = conn.execute(
                "SELECT * FROM ownership_locks WHERE lock_token=?",
                (lock_token,),
            ).fetchone()
            if not lock:
                return self._result(
                    acquired=False,
                    conflict=False,
                    lock_token=lock_token,
                    claim_mark=None,
                    status="missing",
                    reason="lock_not_found",
                )

            if lock["claim_mark"] != page_claim_mark:
                return self._result(
                    acquired=lock["status"] == "active",
                    conflict=True,
                    lock_token=lock["lock_token"],
                    claim_mark=lock["claim_mark"],
                    status="claim_mismatch",
                    reason="page_claim_mark_mismatch",
                )

            conn.execute(
                """
                UPDATE ownership_locks
                SET page_claim_mark=?, page_claim_verified=1, page_claim_verified_at=?, updated_at=?
                WHERE lock_token=?
                """,
                (page_claim_mark, now, now, lock_token),
            )
            return self._result(
                acquired=lock["status"] == "active",
                conflict=False,
                lock_token=lock["lock_token"],
                claim_mark=lock["claim_mark"],
                status="verified",
                reason="page_claim_mark_verified",
            )

    def release_lock(self, lock_token: str) -> dict:
        now = self._now_iso()
        with connection() as conn:
            lock = conn.execute(
                "SELECT * FROM ownership_locks WHERE lock_token=?",
                (lock_token,),
            ).fetchone()
            if not lock:
                return self._result(
                    acquired=False,
                    conflict=False,
                    lock_token=lock_token,
                    claim_mark=None,
                    status="missing",
                    reason="lock_not_found",
                )

            conn.execute(
                """
                UPDATE ownership_locks
                SET status='released', released_at=?, updated_at=?
                WHERE lock_token=?
                """,
                (now, now, lock_token),
            )
            return self._result(
                acquired=False,
                conflict=False,
                lock_token=lock["lock_token"],
                claim_mark=lock["claim_mark"],
                status="released",
                reason="lock_released",
            )

    def _build_fingerprint(
        self,
        product_id: int,
        store_name: str,
        source_title: str,
        sku_prefix: str | None,
    ) -> str:
        raw = "|".join(
            [
                self._normalize(store_name),
                str(product_id),
                self._normalize(sku_prefix or ""),
                self._normalize(source_title),
            ]
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _normalize(self, value: str) -> str:
        return " ".join(value.strip().lower().split())

    def _result(
        self,
        acquired: bool,
        conflict: bool,
        lock_token: str | None,
        claim_mark: str | None,
        status: str,
        reason: str,
    ) -> dict:
        return {
            "acquired": acquired,
            "conflict": conflict,
            "lock_token": lock_token,
            "claim_mark": claim_mark,
            "status": status,
            "reason": reason,
        }

    def _now_iso(self) -> str:
        return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    def _expires_at_iso(self) -> str:
        return (
            datetime.utcnow()
            .replace(microsecond=0)
            + timedelta(seconds=self.lock_ttl_seconds)
        ).isoformat() + "Z"
