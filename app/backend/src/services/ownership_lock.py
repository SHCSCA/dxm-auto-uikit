from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from uuid import uuid4

from src.db import connection


class OwnershipLockService:
    def __init__(self, lock_ttl_seconds: int = 30 * 60):
        self.lock_ttl_seconds = lock_ttl_seconds

    def build_ownership_tag(self, base_tag: str, task_id: int, job_id: int | None = None) -> str:
        if job_id is None:
            return f"{base_tag}-{task_id}"
        return f"{base_tag}-{task_id}-{job_id}"

    def acquire_lock(
        self,
        task_id: int,
        job_id: int,
        product_id: int,
        store_name: str,
        source_title: str,
        sku_prefix: str | None = None,
        ownership_tag_base: str = "DXM-LOCK",
        lock_owner_run_id: str | None = None,
    ) -> dict:
        now = self._now_iso()
        expires_at = self._expires_at_iso()
        ownership_tag = self.build_ownership_tag(ownership_tag_base, task_id, job_id)
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
                    ownership_tag=active_lock["ownership_tag"],
                    status="conflict",
                    reason="ownership_locked",
                )

            if active_lock:
                conn.execute(
                    """
                    UPDATE ownership_locks
                    SET job_id=?, ownership_tag=?, lock_owner_run_id=?, expires_at=?, updated_at=?
                    WHERE lock_token=?
                    """,
                    (
                        job_id,
                        ownership_tag,
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
                    ownership_tag=ownership_tag,
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
                    ownership_tag,
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
                    ownership_tag,
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
                ownership_tag=ownership_tag,
                status="acquired",
                reason="lock_acquired",
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
                    ownership_tag=None,
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
                ownership_tag=lock["ownership_tag"],
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
        ownership_tag: str | None,
        status: str,
        reason: str,
    ) -> dict:
        return {
            "acquired": acquired,
            "conflict": conflict,
            "lock_token": lock_token,
            "ownership_tag": ownership_tag,
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


class ConcurrentEditorGuard:
    """Writer fence guard for per-shop concurrent editing control.

    Uses transaction CAS to acquire/release/validate writer fences.
    Generation is permanently invalidated after release.

    Lifecycle:
      - task start -> acquire()
      - task stop/succeeded/failed -> release()
      - task pause -> hold (keep fence alive)
    """

    DEFAULT_FENCE_TTL_SECONDS = 30 * 60

    def __init__(self, fence_ttl_seconds: int = DEFAULT_FENCE_TTL_SECONDS):
        self._fence_ttl_seconds = fence_ttl_seconds

    def acquire_writer_fence(
        self,
        shop_id: str,
        task_id: str,
        generation: int = 0,
    ) -> dict:
        """Acquire a writer fence for a shop/task/generation.

        Returns:
            {"acquired": True, "writer_fence_id": str, "generation": int, ...}
            or
            {"acquired": False, "conflict": True, "writer_fence_id": str, ...}
        """
        writer_fence_id = uuid4().hex
        now = self._now_iso()
        expires_at = self._expires_at_iso()
        expected_gen = int(generation)

        with connection() as conn:
            conn.execute("BEGIN IMMEDIATE")

            active = conn.execute(
                """
                SELECT * FROM writer_fences
                WHERE shop_id=? AND status='active' AND expires_at>?
                ORDER BY id DESC LIMIT 1
                """,
                (shop_id, now),
            ).fetchone()

            if active:
                # Same task_id may refresh its own fence (heartbeat) when
                # generation matches. ANY OTHER active fence on the same
                # shop_id — including a different task_id — must conflict,
                # otherwise concurrent tasks could mutate the same shop in
                # parallel and corrupt editor state.
                if active["task_id"] != task_id or int(active["generation"] or 0) != expected_gen:
                    conn.execute("ROLLBACK")
                    return self._fence_result(
                        acquired=False,
                        conflict=True,
                        writer_fence_id=active["writer_fence_id"],
                        shop_id=shop_id,
                        task_id=task_id,
                        generation=int(active["generation"] or 0),
                        status="conflict",
                        reason=(
                            "shop_writer_fence_held_by_other_task"
                            if active["task_id"] != task_id
                            else "generation_mismatch"
                        ),
                    )
                active_gen = int(active["generation"] or 0)
                conn.execute(
                    """
                    UPDATE writer_fences
                    SET heartbeat_at=?, expires_at=?, updated_at=?
                    WHERE writer_fence_id=?
                    """,
                    (now, expires_at, now, active["writer_fence_id"]),
                )
                conn.execute("COMMIT")
                return self._fence_result(
                    acquired=True,
                    conflict=False,
                    writer_fence_id=active["writer_fence_id"],
                    shop_id=shop_id,
                    task_id=task_id,
                    generation=active_gen,
                    status="refreshed",
                    reason="fence_refreshed",
                )

            conn.execute(
                """
                INSERT INTO writer_fences (
                    writer_fence_id, shop_id, task_id, generation,
                    acquired_at, heartbeat_at, expires_at,
                    status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
                """,
                (
                    writer_fence_id,
                    shop_id,
                    task_id,
                    expected_gen,
                    now,
                    now,
                    expires_at,
                    now,
                    now,
                ),
            )
            conn.execute("COMMIT")
            return self._fence_result(
                acquired=True,
                conflict=False,
                writer_fence_id=writer_fence_id,
                shop_id=shop_id,
                task_id=task_id,
                generation=expected_gen,
                status="acquired",
                reason="fence_acquired",
            )

    def release_writer_fence(
        self,
        writer_fence_id: str,
        generation: int,
    ) -> dict:
        """Release a writer fence, permanently invalidating the generation.

        Generation is permanently invalidated — cannot be reacquired.
        """
        now = self._now_iso()
        expected_gen = int(generation)

        with connection() as conn:
            conn.execute("BEGIN IMMEDIATE")

            fence = conn.execute(
                "SELECT * FROM writer_fences WHERE writer_fence_id=?",
                (writer_fence_id,),
            ).fetchone()

            if not fence:
                conn.execute("ROLLBACK")
                return self._fence_result(
                    acquired=False,
                    conflict=False,
                    writer_fence_id=writer_fence_id,
                    shop_id=None,
                    task_id=None,
                    generation=None,
                    status="missing",
                    reason="fence_not_found",
                )

            if fence["status"] == "released" or fence["status"] == "invalidated":
                conn.execute("ROLLBACK")
                return self._fence_result(
                    acquired=False,
                    conflict=False,
                    writer_fence_id=writer_fence_id,
                    shop_id=fence["shop_id"],
                    task_id=fence["task_id"],
                    generation=int(fence["generation"] or 0),
                    status=fence["status"],
                    reason="already_released",
                )

            current_gen = int(fence["generation"] or 0)
            if current_gen != expected_gen:
                conn.execute("ROLLBACK")
                return self._fence_result(
                    acquired=False,
                    conflict=True,
                    writer_fence_id=writer_fence_id,
                    shop_id=fence["shop_id"],
                    task_id=fence["task_id"],
                    generation=current_gen,
                    status="conflict",
                    reason="generation_mismatch",
                )

            conn.execute(
                """
                UPDATE writer_fences
                SET status='released', generation=generation+999999,
                    released_at=?, invalidated_at=?, updated_at=?
                WHERE writer_fence_id=?
                """,
                (now, now, now, writer_fence_id),
            )
            conn.execute("COMMIT")
            return self._fence_result(
                acquired=False,
                conflict=False,
                writer_fence_id=writer_fence_id,
                shop_id=fence["shop_id"],
                task_id=fence["task_id"],
                generation=current_gen,
                status="released",
                reason="fence_released",
            )

    def validate_writer_fence(
        self,
        shop_id: str,
        task_id: str,
    ) -> dict:
        """Check if there is an active fence for this shop/task."""
        now = self._now_iso()

        with connection() as conn:
            active = conn.execute(
                """
                SELECT * FROM writer_fences
                WHERE shop_id=? AND task_id=? AND status='active' AND expires_at>?
                ORDER BY id DESC LIMIT 1
                """,
                (shop_id, task_id, now),
            ).fetchone()

            if not active:
                return self._fence_result(
                    acquired=False,
                    conflict=False,
                    writer_fence_id=None,
                    shop_id=shop_id,
                    task_id=task_id,
                    generation=None,
                    status="no_active_fence",
                    reason="no_active_fence",
                )

            return self._fence_result(
                acquired=True,
                conflict=False,
                writer_fence_id=active["writer_fence_id"],
                shop_id=active["shop_id"],
                task_id=active["task_id"],
                generation=int(active["generation"] or 0),
                acquired_at=active["acquired_at"],
                heartbeat_at=active["heartbeat_at"],
                expires_at=active["expires_at"],
                status="active",
                reason="fence_valid",
            )

    def heartbeat_writer_fence(
        self,
        writer_fence_id: str,
    ) -> dict:
        """Send a heartbeat to keep the fence alive."""
        now = self._now_iso()
        expires_at = self._expires_at_iso()

        with connection() as conn:
            conn.execute("BEGIN IMMEDIATE")

            fence = conn.execute(
                "SELECT * FROM writer_fences WHERE writer_fence_id=?",
                (writer_fence_id,),
            ).fetchone()

            if not fence or fence["status"] != "active":
                conn.execute("ROLLBACK")
                return self._fence_result(
                    acquired=False,
                    conflict=False,
                    writer_fence_id=writer_fence_id,
                    shop_id=fence["shop_id"] if fence else None,
                    task_id=fence["task_id"] if fence else None,
                    generation=int(fence["generation"] or 0) if fence else None,
                    status="missing",
                    reason="fence_not_found_or_inactive",
                )

            conn.execute(
                """
                UPDATE writer_fences
                SET heartbeat_at=?, expires_at=?, updated_at=?
                WHERE writer_fence_id=?
                """,
                (now, expires_at, now, writer_fence_id),
            )
            conn.execute("COMMIT")
            return self._fence_result(
                acquired=True,
                conflict=False,
                writer_fence_id=writer_fence_id,
                shop_id=fence["shop_id"],
                task_id=fence["task_id"],
                generation=int(fence["generation"] or 0),
                acquired_at=fence["acquired_at"],
                heartbeat_at=now,
                expires_at=expires_at,
                status="active",
                reason="heartbeat_ok",
            )

    def _fence_result(
        self,
        acquired: bool,
        conflict: bool,
        writer_fence_id: str | None,
        shop_id: str | None,
        task_id: str | None,
        generation: int | None,
        status: str,
        reason: str,
        **extra: object,
    ) -> dict:
        result = {
            "acquired": acquired,
            "conflict": conflict,
            "writer_fence_id": writer_fence_id,
            "shop_id": shop_id,
            "task_id": task_id,
            "generation": generation,
            "status": status,
            "reason": reason,
        }
        result.update(extra)
        return result

    def _now_iso(self) -> str:
        return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    def _expires_at_iso(self) -> str:
        return (
            datetime.utcnow()
            .replace(microsecond=0)
            + timedelta(seconds=self._fence_ttl_seconds)
        ).isoformat() + "Z"
