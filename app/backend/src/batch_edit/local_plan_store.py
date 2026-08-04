from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from src.batch_edit.plan_reference_store import (
    DxmTemplateReferenceStore,
    ResolvedTemplateReferences,
)
from src.batch_edit.plan_template_contract import (
    PlanTemplateContractError,
    normalize_local_plan_payload,
)
from src.db import connection, dumps, loads
from src.utils import now_iso


LOCAL_PLAN_MODEL = "local_plan_template"
_ContractError = TypeVar("_ContractError", bound=Exception)


class LocalPlanTemplateStore:
    """Own immutable local-plan versions and their trusted snapshot inputs."""

    def __init__(
        self,
        error_type: type[_ContractError],
        *,
        reference_store: DxmTemplateReferenceStore,
    ) -> None:
        self._error_type = error_type
        self._reference_store = reference_store

    def create(
        self,
        payload: dict[str, Any],
        *,
        supersedes_id: int | None = None,
    ) -> dict[str, Any]:
        normalized = self._normalize(payload)
        now = now_iso()
        with connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            lineage_id: int | None = None
            if supersedes_id is not None:
                previous = conn.execute(
                    "SELECT * FROM local_plan_templates WHERE id=?",
                    (supersedes_id,),
                ).fetchone()
                if not previous:
                    self._reject(
                        "LOCAL_PLAN_NOT_FOUND",
                        "local plan version does not exist",
                        status_code=404,
                    )
                lineage_id = int(previous["lineage_id"] or previous["id"])
                if normalized["version"] == previous["version"]:
                    self._reject(
                        "LOCAL_PLAN_VERSION_CONFLICT",
                        "new local plan version must be different",
                    )
            self._reference_store.resolve_bindings(
                conn,
                normalized["dxm_template_refs"],
                shop_id=normalized["shop_id"],
                category_ids=normalized["category_ids"],
            )
            if lineage_id is None:
                duplicate = conn.execute(
                    "SELECT id FROM local_plan_templates WHERE name=? AND version=?",
                    (normalized["name"], normalized["version"]),
                ).fetchone()
            else:
                duplicate = conn.execute(
                    "SELECT id FROM local_plan_templates WHERE lineage_id=? AND version=?",
                    (lineage_id, normalized["version"]),
                ).fetchone()
            if duplicate:
                self._reject(
                    "LOCAL_PLAN_VERSION_CONFLICT",
                    "local plan version already exists",
                )
            cursor = conn.execute(
                """
                INSERT INTO local_plan_templates (
                    lineage_id, version, name, payload_json, is_active,
                    supersedes_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (
                    lineage_id,
                    normalized["version"],
                    normalized["name"],
                    dumps(normalized),
                    supersedes_id,
                    now,
                    now,
                ),
            )
            plan_id = int(cursor.lastrowid)
            if lineage_id is None:
                conn.execute(
                    "UPDATE local_plan_templates SET lineage_id=? WHERE id=?",
                    (plan_id, plan_id),
                )
            row = conn.execute(
                "SELECT * FROM local_plan_templates WHERE id=?",
                (plan_id,),
            ).fetchone()
        return self._public(row)

    def list(self) -> list[dict[str, Any]]:
        with connection() as conn:
            rows = conn.execute(
                "SELECT * FROM local_plan_templates ORDER BY id DESC"
            ).fetchall()
        return [self._public(row) for row in rows]

    def get(self, plan_id: int) -> dict[str, Any]:
        with connection() as conn:
            row = conn.execute(
                "SELECT * FROM local_plan_templates WHERE id=?",
                (plan_id,),
            ).fetchone()
        if not row:
            self._reject(
                "LOCAL_PLAN_NOT_FOUND",
                "local plan version does not exist",
                status_code=404,
            )
        return self._public(row)

    def archive(self, plan_id: int) -> dict[str, Any]:
        now = now_iso()
        with connection() as conn:
            row = conn.execute(
                "SELECT * FROM local_plan_templates WHERE id=?",
                (plan_id,),
            ).fetchone()
            if not row:
                self._reject(
                    "LOCAL_PLAN_NOT_FOUND",
                    "local plan version does not exist",
                    status_code=404,
                )
            conn.execute(
                "UPDATE local_plan_templates SET is_active=0, updated_at=? WHERE id=?",
                (now, plan_id),
            )
            updated = conn.execute(
                "SELECT * FROM local_plan_templates WHERE id=?",
                (plan_id,),
            ).fetchone()
        return self._public(updated)

    def load_snapshot_inputs(
        self,
        plan_id: int,
    ) -> tuple[dict[str, Any], ResolvedTemplateReferences]:
        with connection() as conn:
            row = conn.execute(
                "SELECT * FROM local_plan_templates WHERE id=?",
                (plan_id,),
            ).fetchone()
            if not row:
                self._reject(
                    "LOCAL_PLAN_NOT_FOUND",
                    "local plan version does not exist",
                    status_code=404,
                )
            plan = self._public(row)
            if plan["is_active"] is not True:
                self._reject(
                    "LOCAL_PLAN_ARCHIVED",
                    "local plan version is archived",
                )
            refs = self._reference_store.resolve_bindings(
                conn,
                plan["dxm_template_refs"],
                shop_id=plan["shop_id"],
                category_ids=plan["category_ids"],
            )
        return plan, refs

    def _normalize(self, payload: Any) -> dict[str, Any]:
        try:
            return normalize_local_plan_payload(payload)
        except PlanTemplateContractError as exc:
            self._reject(exc.reason_code, str(exc))

    @staticmethod
    def _public(row: Mapping[str, Any]) -> dict[str, Any]:
        payload = loads(row["payload_json"], {})
        return {
            "model": LOCAL_PLAN_MODEL,
            "id": int(row["id"]),
            "lineage_id": int(row["lineage_id"] or row["id"]),
            "supersedes_id": (
                int(row["supersedes_id"])
                if row.get("supersedes_id") is not None
                else None
            ),
            **payload,
            "is_active": bool(row["is_active"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _reject(
        self,
        reason_code: str,
        detail: str,
        *,
        status_code: int = 409,
    ) -> None:
        raise self._error_type(
            reason_code,
            detail,
            status_code=status_code,
        )
