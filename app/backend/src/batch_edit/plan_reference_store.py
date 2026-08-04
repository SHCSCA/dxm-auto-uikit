from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from src.batch_edit.plan_value_contract import PlanValueContract
from src.batch_edit.scope_contract import canonical_sha256
from src.db import connection, dumps, loads
from src.utils import now_iso


DXM_TEMPLATE_REF_MODEL = "dxm_template_ref"
DXM_TEMPLATE_REF_TYPES = {
    "product",
    "attribute",
    "variation",
    "freight",
    "service",
    "size",
}
DXM_TEMPLATE_REF_AVAILABILITY = {"available", "missing", "drifted"}
_ContractError = TypeVar("_ContractError", bound=Exception)


class ResolvedTemplateReferences:
    """Immutable, scope-checked view used by the E2 snapshot compiler."""

    def __init__(
        self,
        refs: list[dict[str, Any]],
        *,
        values: PlanValueContract,
    ) -> None:
        self._values = values
        self._refs = tuple(values.clone(ref) for ref in refs)

    def frozen_summary(self) -> list[dict[str, Any]]:
        return [
            {
                "type": ref["ref_type"],
                "id": ref["dxm_template_id"],
                "shop_id": ref["shop_id"],
                "category_id": ref["category_id"],
                "source_digest": ref["source_digest"],
                "resolved_values_hash": ref["resolved_values_hash"],
                "availability": ref["availability"],
            }
            for ref in self._refs
        ]

    def values_for_category(
        self,
        category_id: str,
        *,
        allowed_fields: Mapping[str, Any],
    ) -> dict[str, tuple[Any, str]]:
        resolved: dict[str, tuple[Any, str]] = {}
        for ref in self._refs:
            if (
                ref["category_id"] is not None
                and ref["category_id"] != category_id
            ):
                continue
            for field_key, value in ref["_resolved_values"].items():
                if field_key not in allowed_fields:
                    continue
                source_ref = (
                    f"{ref['dxm_template_id']}@{ref['source_digest']}"
                )
                previous = resolved.get(field_key)
                if previous is not None and previous[0] != value:
                    self._values.reject(
                        "DXM_TEMPLATE_VALUE_CONFLICT",
                        "multiple DXM templates resolve field "
                        f"{field_key} differently",
                    )
                resolved[field_key] = (
                    self._values.clone(value),
                    source_ref,
                )
        return resolved


class DxmTemplateReferenceStore:
    """Normalize and persist PASSIVE_ONLY DXM template references."""

    def __init__(self, error_type: type[_ContractError]) -> None:
        self._values = PlanValueContract(error_type)

    def sync(
        self,
        records: list[dict[str, Any]],
        *,
        shop_id: str,
        category_ids: list[str],
    ) -> list[dict[str, Any]]:
        if not isinstance(records, list):
            self._values.reject(
                "DXM_TEMPLATE_REF_SYNC_INVALID",
                "readonly DXM template references must be a list",
            )
        normalized_shop_id = self._values.positive_id_text(
            shop_id,
            "sync shop_id",
        )
        normalized_category_ids = [
            self._values.positive_id_text(category_id, "sync category_id")
            for category_id in category_ids
        ]
        if (
            not normalized_category_ids
            or len(set(normalized_category_ids)) != len(normalized_category_ids)
        ):
            self._values.reject(
                "DXM_TEMPLATE_REF_SYNC_INVALID",
                "sync category scope must be non-empty and unique",
            )
        category_scope = set(normalized_category_ids)
        normalized_records = [
            self._normalize(raw, index=index)
            for index, raw in enumerate(records)
        ]
        for record in normalized_records:
            if (
                record["shop_id"] != normalized_shop_id
                or (
                    record["category_id"] is not None
                    and record["category_id"] not in category_scope
                )
            ):
                self._values.reject(
                    "DXM_TEMPLATE_REF_SCOPE_CONFLICT",
                    "readonly DXM template reference is outside the synchronized scope",
                )
        observed_identities = {
            (
                record["ref_type"],
                record["dxm_template_id"],
                record["shop_id"],
                record["category_id"],
            )
            for record in normalized_records
        }
        now = now_iso()
        synced_ids: list[int] = []
        with connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            scoped_rows = conn.execute(
                "SELECT * FROM dxm_template_refs WHERE shop_id=?",
                (normalized_shop_id,),
            ).fetchall()
            for row in scoped_rows:
                row_category_id = row["category_id"]
                if (
                    row_category_id is not None
                    and row_category_id not in category_scope
                ):
                    continue
                identity = (
                    row["ref_type"],
                    row["dxm_template_id"],
                    row["shop_id"],
                    row_category_id,
                )
                if identity in observed_identities:
                    continue
                conn.execute(
                    """
                    UPDATE dxm_template_refs
                       SET availability='missing', synced_at=?, updated_at=?
                     WHERE id=?
                    """,
                    (now, now, row["id"]),
                )
            for record in normalized_records:
                current = conn.execute(
                    """
                    SELECT * FROM dxm_template_refs
                     WHERE ref_type=?
                       AND dxm_template_id=?
                       AND shop_id=?
                       AND category_id IS ?
                    """,
                    (
                        record["ref_type"],
                        record["dxm_template_id"],
                        record["shop_id"],
                        record["category_id"],
                    ),
                ).fetchone()
                if current:
                    conn.execute(
                        """
                        UPDATE dxm_template_refs
                           SET observed_display_name=?,
                               source_api=?,
                               availability=?,
                               source_digest=?,
                               resolved_values_json=?,
                               resolved_values_hash=?,
                               audit_items_json=?,
                               audit_items_hash=?,
                               synced_at=?,
                               updated_at=?
                         WHERE id=?
                        """,
                        (
                            record["observed_display_name"],
                            record["source_api"],
                            record["availability"],
                            record["source_digest"],
                            dumps(record["resolved_values"]),
                            record["resolved_values_hash"],
                            dumps(record["audit_items"]),
                            record["audit_items_hash"],
                            now,
                            now,
                            current["id"],
                        ),
                    )
                    synced_ids.append(int(current["id"]))
                else:
                    cursor = conn.execute(
                        """
                        INSERT INTO dxm_template_refs (
                            ref_type, dxm_template_id, shop_id, category_id,
                            observed_display_name, source_api, availability,
                            source_digest, resolved_values_json,
                            resolved_values_hash, audit_items_json,
                            audit_items_hash, synced_at, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            record["ref_type"],
                            record["dxm_template_id"],
                            record["shop_id"],
                            record["category_id"],
                            record["observed_display_name"],
                            record["source_api"],
                            record["availability"],
                            record["source_digest"],
                            dumps(record["resolved_values"]),
                            record["resolved_values_hash"],
                            dumps(record["audit_items"]),
                            record["audit_items_hash"],
                            now,
                            now,
                            now,
                        ),
                    )
                    synced_ids.append(int(cursor.lastrowid))
            rows = [
                conn.execute(
                    "SELECT * FROM dxm_template_refs WHERE id=?",
                    (ref_id,),
                ).fetchone()
                for ref_id in synced_ids
            ]
        return [self.public(row) for row in rows if row]

    def resolve_bindings(
        self,
        conn: Any,
        bindings: list[dict[str, Any]],
        *,
        shop_id: str,
        category_ids: list[str],
    ) -> "ResolvedTemplateReferences":
        normalized_shop_id = self._values.positive_id_text(
            shop_id,
            "plan shop_id",
        )
        normalized_category_ids = {
            self._values.positive_id_text(category_id, "plan category_id")
            for category_id in category_ids
        }
        refs: list[dict[str, Any]] = []
        for binding_index, binding in enumerate(bindings):
            if (
                not isinstance(binding, dict)
                or set(binding) != {"ref_id", "source_digest"}
                or isinstance(binding["ref_id"], bool)
                or not isinstance(binding["ref_id"], int)
                or binding["ref_id"] <= 0
            ):
                self._values.reject(
                    "DXM_TEMPLATE_REF_BINDING_INVALID",
                    f"DXM template binding {binding_index} is invalid",
                )
            expected_digest = self._values.sha256_text(
                binding["source_digest"],
                "source_digest",
            )
            row = conn.execute(
                "SELECT * FROM dxm_template_refs WHERE id=?",
                (binding["ref_id"],),
            ).fetchone()
            if not row:
                self._values.reject(
                    "DXM_TEMPLATE_REF_NOT_FOUND",
                    "local plan references a missing DXM template",
                )
            ref = self.stored(row)
            if (
                ref["source_digest"] != expected_digest
                or ref["availability"] != "available"
            ):
                self._values.reject(
                    "DXM_TEMPLATE_REF_DRIFT",
                    "readonly DXM template reference has drifted",
                )
            if ref["shop_id"] != normalized_shop_id:
                self._values.reject(
                    "DXM_TEMPLATE_REF_SCOPE_CONFLICT",
                    "DXM template reference belongs to another shop",
                )
            if (
                ref["category_id"] is not None
                and ref["category_id"] not in normalized_category_ids
            ):
                self._values.reject(
                    "DXM_TEMPLATE_REF_SCOPE_CONFLICT",
                    "DXM template reference belongs to another category",
                )
            refs.append(ref)
        return ResolvedTemplateReferences(refs, values=self._values)

    def list(self) -> list[dict[str, Any]]:
        with connection() as conn:
            rows = conn.execute(
                "SELECT * FROM dxm_template_refs ORDER BY id ASC"
            ).fetchall()
        return [self.public(row) for row in rows]

    def public(self, row: Mapping[str, Any]) -> dict[str, Any]:
        resolved_values = loads(row.get("resolved_values_json"), {})
        audit_items = loads(row.get("audit_items_json"), [])
        return {
            "model": DXM_TEMPLATE_REF_MODEL,
            "id": int(row["id"]),
            "ref_type": row["ref_type"],
            "dxm_template_id": row["dxm_template_id"],
            "shop_id": row["shop_id"],
            "category_id": row["category_id"],
            "observed_display_name": row["observed_display_name"],
            "source_api": row["source_api"],
            "availability": row["availability"],
            "source_digest": row["source_digest"],
            "resolved_values_hash": (
                row.get("resolved_values_hash")
                or canonical_sha256({})
            ),
            "resolved_field_count": (
                len(resolved_values)
                if isinstance(resolved_values, dict)
                else 0
            ),
            "audit_items_hash": (
                row.get("audit_items_hash")
                or canonical_sha256([])
            ),
            "audit_item_count": (
                len(audit_items)
                if isinstance(audit_items, list)
                else 0
            ),
            "synced_at": row["synced_at"],
        }

    def stored(self, row: Mapping[str, Any]) -> dict[str, Any]:
        public = self.public(row)
        resolved_values = loads(row.get("resolved_values_json"), {})
        audit_items = loads(row.get("audit_items_json"), [])
        if not isinstance(resolved_values, dict):
            self._values.reject(
                "DXM_TEMPLATE_REF_VALUES_INVALID",
                "stored DXM template values are invalid",
            )
        expected_hash = canonical_sha256(resolved_values)
        if public["resolved_values_hash"] != expected_hash:
            self._values.reject(
                "DXM_TEMPLATE_REF_DRIFT",
                "stored DXM template value hash has drifted",
            )
        if not isinstance(audit_items, list):
            self._values.reject(
                "DXM_TEMPLATE_REF_AUDIT_INVALID",
                "stored DXM template audit items are invalid",
            )
        if public["audit_items_hash"] != canonical_sha256(audit_items):
            self._values.reject(
                "DXM_TEMPLATE_REF_DRIFT",
                "stored DXM template audit item hash has drifted",
            )
        return {
            **public,
            "_resolved_values": resolved_values,
            "_audit_items": audit_items,
        }

    def _normalize(self, raw: Any, *, index: int) -> dict[str, Any]:
        if isinstance(raw, dict) and "audit_items" not in raw:
            raw = {**raw, "audit_items": []}
        record = self._values.exact_object(
            raw,
            {
                "ref_type",
                "dxm_template_id",
                "shop_id",
                "category_id",
                "observed_display_name",
                "source_api",
                "availability",
                "source_digest",
                "resolved_values",
                "audit_items",
            },
            f"records[{index}]",
        )
        ref_type = self._values.non_empty_text(
            record["ref_type"],
            "ref_type",
        )
        if ref_type not in DXM_TEMPLATE_REF_TYPES:
            self._values.reject(
                "DXM_TEMPLATE_REF_TYPE_INVALID",
                "DXM template reference type is not stable",
            )
        availability = self._values.non_empty_text(
            record["availability"],
            "availability",
        )
        if availability not in DXM_TEMPLATE_REF_AVAILABILITY:
            self._values.reject(
                "DXM_TEMPLATE_REF_AVAILABILITY_INVALID",
                "DXM template availability is invalid",
            )
        raw_resolved_values = record["resolved_values"]
        if not isinstance(raw_resolved_values, dict):
            self._values.reject(
                "DXM_TEMPLATE_REF_VALUES_INVALID",
                "DXM template resolved values must be an object",
            )
        resolved_values: dict[str, Any] = {}
        for field_key, value in raw_resolved_values.items():
            stable_key = self._values.stable_field_key(field_key)
            if not self._values.is_resolved_value(value):
                continue
            resolved_values[stable_key] = self._values.clone(value)
        self._values.assert_no_publish_true(
            resolved_values,
            path="dxm_template_ref.resolved_values",
        )
        raw_audit_items = record["audit_items"]
        if not isinstance(raw_audit_items, list):
            self._values.reject(
                "DXM_TEMPLATE_REF_AUDIT_INVALID",
                "DXM template audit_items must be an array",
            )
        audit_items: list[dict[str, Any]] = []
        for audit_index, raw_audit in enumerate(raw_audit_items):
            audit = self._values.exact_object(
                raw_audit,
                {
                    "kind",
                    "executable",
                    "source_index",
                    "attr_name",
                    "attr_value",
                    "reason_code",
                },
                f"audit_items[{audit_index}]",
            )
            if (
                audit["kind"] != "unmapped_custom_attribute"
                or audit["executable"] is not False
                or isinstance(audit["source_index"], bool)
                or not isinstance(audit["source_index"], int)
                or audit["source_index"] < 0
                or audit["reason_code"]
                != "DXM_TEMPLATE_ATTRIBUTE_ID_UNMAPPED"
                or not self._values.is_resolved_value(audit["attr_value"])
            ):
                self._values.reject(
                    "DXM_TEMPLATE_REF_AUDIT_INVALID",
                    "DXM template audit item is not safely non-executable",
                )
            audit_items.append(
                {
                    "kind": "unmapped_custom_attribute",
                    "executable": False,
                    "source_index": audit["source_index"],
                    "attr_name": self._values.non_empty_text(
                        audit["attr_name"],
                        "audit attr_name",
                    ),
                    "attr_value": self._values.clone(audit["attr_value"]),
                    "reason_code": "DXM_TEMPLATE_ATTRIBUTE_ID_UNMAPPED",
                }
            )
        self._values.assert_no_publish_true(
            audit_items,
            path="dxm_template_ref.audit_items",
        )
        return {
            "ref_type": ref_type,
            "dxm_template_id": self._values.positive_id_text(
                record["dxm_template_id"],
                "dxm_template_id",
            ),
            "shop_id": self._values.positive_id_text(
                record["shop_id"],
                "shop_id",
            ),
            "category_id": (
                None
                if record["category_id"] is None
                else self._values.positive_id_text(
                    record["category_id"],
                    "category_id",
                )
            ),
            "observed_display_name": self._values.non_empty_text(
                record["observed_display_name"],
                "observed_display_name",
            ),
            "source_api": self._values.non_empty_text(
                record["source_api"],
                "source_api",
            ),
            "availability": availability,
            "source_digest": self._values.sha256_text(
                record["source_digest"],
                "source_digest",
            ),
            "resolved_values": resolved_values,
            "resolved_values_hash": canonical_sha256(resolved_values),
            "audit_items": audit_items,
            "audit_items_hash": canonical_sha256(audit_items),
        }
