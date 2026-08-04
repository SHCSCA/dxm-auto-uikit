from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, TypeVar

from src.batch_edit.english_policy import detect_english
from src.batch_edit.local_plan_store import (
    LOCAL_PLAN_MODEL,
    LocalPlanTemplateStore,
)
from src.batch_edit.plan_reference_store import (
    DXM_TEMPLATE_REF_MODEL,
    ResolvedTemplateReferences,
)
from src.batch_edit.plan_schema_contract import (
    active_required_fields,
    assert_price_policy,
    assert_value_matches_schema,
    normalize_category_schema,
    potential_required_fields,
    required_field_rules,
    schema_constraints,
)
from src.batch_edit.plan_template_contract import (
    PlanTemplateContractError,
    normalize_field_mapping,
)
from src.batch_edit.plan_value_contract import PlanValueContract
from src.batch_edit.scope_contract import canonical_sha256


PLAN_SNAPSHOT_SCHEMA = "dxm_batch_draft_save_plan.v1"
_ContractError = TypeVar("_ContractError", bound=Exception)


class PlanSnapshotCompiler:
    """Compile one immutable, fail-closed Path A snapshot from trusted inputs."""

    def __init__(
        self,
        error_type: type[_ContractError],
        *,
        local_plan_store: LocalPlanTemplateStore,
    ) -> None:
        self._error_type = error_type
        self._local_plan_store = local_plan_store
        self._values = PlanValueContract(error_type)

    def compile(self, request: dict[str, Any]) -> dict[str, Any]:
        exact = self._values.exact_object(
            request,
            {
                "local_plan_template_id",
                "shop_id",
                "items",
                "session_context",
            },
            "plan snapshot request",
        )
        plan_id = exact["local_plan_template_id"]
        if isinstance(plan_id, bool) or not isinstance(plan_id, int) or plan_id <= 0:
            self._reject(
                "LOCAL_PLAN_NOT_FOUND",
                "local_plan_template_id must be positive",
            )
        requested_shop_id = self._values.positive_id_text(
            exact["shop_id"],
            "shop_id",
        )
        session_context = self._values.exact_object(
            exact["session_context"],
            {"session_ref", "account_ref_hash", "shop_id"},
            "session_context",
        )
        session_ref = self._values.non_empty_text(
            session_context["session_ref"],
            "session_context.session_ref",
        )
        if re.fullmatch(r"[0-9a-f]{16}", session_ref) is None:
            self._reject(
                "DXM_PLAN_SESSION_REF_INVALID",
                "session_context.session_ref must be a current Reader proof",
            )
        account_ref_hash = self._values.sha256_text(
            session_context["account_ref_hash"],
            "session_context.account_ref_hash",
        )
        session_shop_id = self._values.positive_id_text(
            session_context["shop_id"],
            "session_context.shop_id",
        )
        if session_shop_id != requested_shop_id:
            self._reject(
                "PLAN_SCOPE_CONFLICT",
                "session context shop does not match snapshot shop",
            )
        raw_items = exact["items"]
        if not isinstance(raw_items, list) or not 3 <= len(raw_items) <= 100:
            self._reject(
                "PLAN_ITEM_COUNT_INVALID",
                "plan snapshot requires 3 to 100 draft products",
            )

        plan, template_refs = self._local_plan_store.load_snapshot_inputs(plan_id)
        if requested_shop_id != plan["shop_id"]:
            self._reject(
                "PLAN_SCOPE_CONFLICT",
                "requested shop does not match the local plan",
            )

        items: list[dict[str, Any]] = []
        product_ids: list[str] = []
        seen_products: set[str] = set()
        for index, raw_item in enumerate(raw_items):
            item = self._build_item_snapshot(
                raw_item,
                index=index,
                plan=plan,
                template_refs=template_refs,
                requested_shop_id=requested_shop_id,
            )
            if item["product_id"] in seen_products:
                self._reject(
                    "PLAN_PRODUCT_DUPLICATE",
                    "product_ids must be unique",
                )
            seen_products.add(item["product_id"])
            product_ids.append(item["product_id"])
            items.append(item)

        snapshot = {
            "schema": PLAN_SNAPSHOT_SCHEMA,
            "mode": "batch_draft_save",
            "path": "A",
            "shop_scope": requested_shop_id,
            "session_context": {
                "session_ref": session_ref,
                "account_ref_hash": account_ref_hash,
                "shop_id": session_shop_id,
            },
            "approval_context": {
                "state": "not_granted",
                "runner_released": False,
                "publish_allowed": False,
            },
            "product_ids": product_ids,
            "local_plan_template": {
                "id": plan["id"],
                "version": plan["version"],
            },
            "dxm_template_refs": template_refs.frozen_summary(),
            "fixed_values": self._values.clone(plan["fixed_values"]),
            "fill_rules": self._values.clone(plan["fill_rules"]),
            "item_snapshots": items,
            "evidence_policy": "three_proofs",
            "failure_policy": {"unknown": "stop_batch"},
            "publish_allowed": False,
        }
        return {**snapshot, "snapshot_hash": canonical_sha256(snapshot)}

    def assert_hash(self, snapshot: Mapping[str, Any]) -> None:
        reported = snapshot.get("snapshot_hash")
        body = {
            key: self._values.clone(value)
            for key, value in snapshot.items()
            if key not in {"id", "task_id", "created_at", "snapshot_hash"}
        }
        if not isinstance(reported, str) or reported != canonical_sha256(body):
            self._reject(
                "PLAN_SNAPSHOT_HASH_INVALID",
                "plan snapshot hash cannot be reproduced",
            )

    def _build_item_snapshot(
        self,
        raw_item: Any,
        *,
        index: int,
        plan: Mapping[str, Any],
        template_refs: ResolvedTemplateReferences,
        requested_shop_id: str,
    ) -> dict[str, Any]:
        item = self._values.exact_object(
            raw_item,
            {
                "product_id",
                "shop_id",
                "category_id",
                "category_schema",
                "expected_schema_hash",
                "current_values",
            },
            f"items[{index}]",
        )
        product_id = self._values.positive_id_text(
            item["product_id"],
            "product_id",
        )
        shop_id = self._values.positive_id_text(
            item["shop_id"],
            "item shop_id",
        )
        category_id = self._values.positive_id_text(
            item["category_id"],
            "category_id",
        )
        if shop_id != requested_shop_id:
            self._reject(
                "PLAN_SCOPE_CONFLICT",
                "item shop does not match the confirmed plan scope",
            )
        if category_id not in set(plan["category_ids"]):
            self._reject(
                "PLAN_CATEGORY_SCOPE_CONFLICT",
                "item category is not covered by the local plan",
            )
        normalized_schema = normalize_category_schema(item["category_schema"])
        schema_hash = canonical_sha256(normalized_schema)
        expected_schema_hash = self._values.sha256_text(
            item["expected_schema_hash"],
            "expected_schema_hash",
        )
        if expected_schema_hash != schema_hash:
            self._reject(
                "CATEGORY_SCHEMA_DRIFT",
                "category schema changed before the plan snapshot was frozen",
            )
        current_values = item["current_values"]
        if not isinstance(current_values, dict):
            self._reject(
                "PLAN_CURRENT_VALUES_INVALID",
                "current_values must be an object",
            )
        current_price_validation = assert_price_policy(
            normalized_schema,
            current_values,
            phase="current_values",
        )

        mapping = self._normalize_field_mapping(
            plan["field_mappings"][category_id],
            category_id=category_id,
            schema=normalized_schema,
        )
        properties = normalized_schema["properties"]
        potential_required_keys = potential_required_fields(normalized_schema)
        mapped_fields = {
            entry["field_key"]
            for entry in mapping["entries"]
        }
        missing_required_mappings = [
            field_key
            for field_key in potential_required_keys
            if field_key not in mapped_fields
        ]
        if missing_required_mappings:
            self._reject(
                "PLAN_REQUIRED_FIELD_MAPPING_MISSING",
                "required fields are not configured in field mappings: "
                + ", ".join(missing_required_mappings),
            )
        fill_rules = plan["fill_rules"][category_id]
        fixed_field_values = (
            plan["fixed_values"]
            .get("field_values", {})
            .get(category_id, {})
        )
        template_values = template_refs.values_for_category(
            category_id,
            allowed_fields=properties,
        )
        resolved_fields: list[dict[str, Any]] = []
        unresolved_fields: list[str] = []
        for entry in mapping["entries"]:
            field_key = entry["field_key"]
            property_schema = properties[field_key]
            if (
                field_key in fixed_field_values
                and self._values.is_resolved_value(
                    fixed_field_values[field_key]
                )
            ):
                value = self._values.clone(fixed_field_values[field_key])
                source = "fixed_value"
                source_ref = f"{plan['id']}@{plan['version']}#fixed"
            else:
                rule = fill_rules.get(field_key)
                if (
                    isinstance(rule, dict)
                    and set(rule) == {"value"}
                    and self._values.is_resolved_value(rule["value"])
                ):
                    value = self._values.clone(rule["value"])
                    source = LOCAL_PLAN_MODEL
                    source_ref = f"{plan['id']}@{plan['version']}"
                elif field_key in template_values:
                    value, source_ref = template_values[field_key]
                    source = DXM_TEMPLATE_REF_MODEL
                elif (
                    field_key in current_values
                    and self._values.is_resolved_value(current_values[field_key])
                ):
                    value = self._values.clone(current_values[field_key])
                    source = "current"
                    source_ref = f"{product_id}@scope"
                else:
                    unresolved_fields.append(field_key)
                    continue
            assert_value_matches_schema(
                value,
                property_schema,
                field_key=field_key,
            )
            natural_language = property_schema.get("natural_language") is True
            detected_language: str | None = None
            expected_language: str | None = None
            if natural_language:
                expected_language = "en"
                detected_language = detect_english(value)
                if detected_language != "en":
                    self._reject(
                        "NATURAL_LANGUAGE_ENGLISH_REQUIRED",
                        f"field {field_key} must contain validated English "
                        "natural-language content",
                    )
            resolved_fields.append(
                {
                    "field_key": field_key,
                    "source": source,
                    "source_ref": source_ref,
                    "resolved_value": value,
                    "natural_language": natural_language,
                    "expected_language": expected_language,
                    "detected_language": detected_language,
                }
            )
        resolved_values = {
            field["field_key"]: field["resolved_value"]
            for field in resolved_fields
        }
        resolved_price_validation = assert_price_policy(
            normalized_schema,
            resolved_values,
            phase="resolved_values",
        )
        active_required = active_required_fields(
            normalized_schema,
            resolved_values,
        )
        missing_required = [
            field
            for field in active_required
            if field in unresolved_fields
        ]
        if missing_required:
            self._reject(
                "PLAN_REQUIRED_FIELD_UNRESOLVED",
                "required fields are unresolved: " + ", ".join(missing_required),
            )
        required_fields = [
            {
                "field_key": field_key,
                "required_when": required_when,
                "active": field_key in active_required,
                "constraints": schema_constraints(properties[field_key]),
            }
            for field_key, required_when in required_field_rules(
                normalized_schema
            )
        ]
        resolution_body = {
            "resolved_fields": resolved_fields,
            "unresolved_fields": unresolved_fields,
            "price_validation": {
                "current_values": current_price_validation,
                "resolved_values": resolved_price_validation,
            },
        }
        return {
            "product_id": product_id,
            "shop_id": shop_id,
            "categoryId": category_id,
            "category_schema": {
                "normalized_schema": normalized_schema,
                "schema_hash": schema_hash,
            },
            "field_mapping": mapping,
            "current_value_snapshot": self._values.clone(current_values),
            "required_fields": required_fields,
            "resolution_result": {
                **resolution_body,
                "resolution_hash": canonical_sha256(resolution_body),
            },
        }

    def _normalize_field_mapping(
        self,
        raw: Any,
        *,
        category_id: str,
        schema: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        try:
            return normalize_field_mapping(
                raw,
                category_id=category_id,
                schema=schema,
            )
        except PlanTemplateContractError as exc:
            self._reject(exc.reason_code, str(exc))

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
