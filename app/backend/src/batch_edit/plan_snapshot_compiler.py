from __future__ import annotations

import hashlib
import json
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
from src.execution.browser_agent_protocol import (
    MutationCommandContractError,
    canonical_frozen_target_identity,
)


PLAN_SNAPSHOT_SCHEMA = "dxm_batch_draft_save_plan.v1"
SNAPSHOT_INSTANCE_SCHEMA = "dxm_batch_draft_save_plan_instance.v1"
PLAN_PATH_EXECUTION_NOT_RELEASED = "PLAN_PATH_EXECUTION_NOT_RELEASED"
RELEASED_PLAN_EXECUTION_PATHS = frozenset({"A"})
_ContractError = TypeVar("_ContractError", bound=Exception)

MANDATORY_CAPABILITIES = frozenset(
    {"video", "translation", "wholesale", "semiManaged", "rollbackPreparation"}
)

CAPABILITY_NAMES = {
    "video": "视频生成",
    "translation": "一键翻译",
    "wholesale": "批发配置",
    "semiManaged": "半托管编辑",
    "rollbackPreparation": "回滚准备",
}

DEFAULT_MAX_AGE_HOURS = 24
DRIFT_POLICY_ABORT = "ABORT"
DRIFT_POLICY_WARN = "WARN"

_SCHEMA_VERSION = "dxm_plan_snapshot_compiler.v3"

# ``ui_section`` is attached at the trusted Reader/schema boundary from exact
# DXM bindings.  It is the only stage authority used here: labels, field-name
# heuristics, request annotations, and operator-authored phase declarations are
# deliberately excluded.
_SAVE1_UI_SECTIONS = frozenset(
    {
        "basic_info",
        "dxm_info",
        "attribute_info",
        "product_info",
        "regional_pricing",
        "description_info",
        "packaging_info",
        "template_main",
        "compliance_info",
        "other_info",
    }
)
_SAVE2_UI_SECTION = "semi_managed"
_REAL_WRITE_STAGE_FACTS_SCHEMA = "dxm.real_write_stage_facts.v1"


def is_plan_execution_path_released(path: Any) -> bool:
    """Return whether an immutable plan path may enter the real-write runner."""

    return str(path or "").strip().upper() in RELEASED_PLAN_EXECUTION_PATHS


class WorkflowMandatoryCapabilityChecker:
    """Adapt a workflow runtime's explicit capability proof to the compiler."""

    def __init__(self, provider: Any) -> None:
        self._provider = provider

    def is_available(self, capability: str) -> dict[str, Any]:
        probe = getattr(self._provider, "mandatory_capability_status", None)
        if not callable(probe):
            return {
                "ok": False,
                "reason_code": "MANDATORY_CAPABILITY_PROVIDER_MISSING",
            }
        result = probe(capability)
        if not isinstance(result, Mapping) or result.get("ok") is not True:
            return {
                "ok": False,
                "reason_code": str(
                    result.get("reason_code")
                    if isinstance(result, Mapping)
                    else "MANDATORY_CAPABILITY_PROOF_INVALID"
                ),
            }
        return {"ok": True}


class PlanSnapshotCompiler:
    """Compile one immutable, fail-closed plan snapshot from trusted inputs.

    R1 deepening:
    - Each item is frozen independently with its own hashes:
      sourceCategory, targetCategory, catalogNodeIdentitySha256,
      catalogSha256, schemaSha256, capabilitiesSha256
    - mandatory_capabilities block with 5 always-on capabilities
    - fail-closed if any mandatory capability unavailable
    - max_age_hours, schema_drift_policy=ABORT, catalog_drift_policy=ABORT
    - execution_constraints dict with drift policies
    """

    def __init__(
        self,
        error_type: type[_ContractError],
        *,
        local_plan_store: LocalPlanTemplateStore,
        capability_checker: Any = None,
        max_age_hours: int = DEFAULT_MAX_AGE_HOURS,
    ) -> None:
        self._error_type = error_type
        self._local_plan_store = local_plan_store
        self._values = PlanValueContract(error_type)
        self._capability_checker = capability_checker
        self._max_age_hours = max_age_hours

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
            optional_keys=frozenset(
                {
                    "target_category_id",
                    "target_category_schema",
                    "expected_target_schema_hash",
                    "target_category_name",
                    "target_category_match",
                    "idempotency_key",
                }
            ),
        )
        idempotency_key = exact.get("idempotency_key") or ""
        target_category = self._normalize_target_category(exact)
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
            {"session_ref", "account_ref_hash", "shop_id", "shop_name"},
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
        session_shop_name = self._values.non_empty_text(
            session_context["shop_name"],
            "session_context.shop_name",
        )
        raw_items = exact["items"]
        if not isinstance(raw_items, list) or not 1 <= len(raw_items) <= 100:
            self._reject(
                "PLAN_ITEM_COUNT_INVALID",
                "plan snapshot requires 1 to 100 draft products",
            )

        plan, template_refs = self._local_plan_store.load_snapshot_inputs(plan_id)
        if plan.get("path") not in ("A", "B"):
            self._reject(
                "PLAN_PATH_INVALID",
                "plan path must be 'A' or 'B'",
            )
        if requested_shop_id != plan["shop_id"]:
            self._reject(
                "PLAN_SCOPE_CONFLICT",
                "requested shop does not match the local plan",
            )
        if plan.get("scope_contract") == "single_target_category.v2":
            if target_category is None:
                self._reject(
                    "PLAN_TARGET_CATEGORY_REQUIRED",
                    "the selected plan requires its configured target category",
                )
            if target_category["category_id"] != plan["category_ids"][0]:
                self._reject(
                    "PLAN_TARGET_CATEGORY_CONFLICT",
                    "task target category does not match the selected plan",
                )

        capability_result = self._check_mandatory_capabilities()
        if not capability_result["ok"]:
            self._reject(
                capability_result["reason_code"],
                capability_result["message"],
            )

        mandatory_capabilities = self._build_mandatory_capabilities_block()

        items: list[dict[str, Any]] = []
        product_ids: list[str] = []
        seen_products: set[str] = set()
        plan_content_frozen = self._freeze_plan_content(plan, target_category, idempotency_key)
        plan_content_sha256 = plan_content_frozen["plan_content_sha256"]

        for index, raw_item in enumerate(raw_items):
            item = self._build_item_snapshot(
                raw_item,
                index=index,
                plan=plan,
                template_refs=template_refs,
                requested_shop_id=requested_shop_id,
                requested_shop_name=session_shop_name,
                target_category=target_category,
                plan_content_sha256=plan_content_sha256,
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
            "compiler_version": _SCHEMA_VERSION,
            "mode": "batch_draft_save",
            "path": plan.get("path", "A"),
            "shop_scope": requested_shop_id,
            "session_context": {
                "session_ref": session_ref,
                "account_ref_hash": account_ref_hash,
                "shop_id": session_shop_id,
                "shop_name": session_shop_name,
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
            **(
                {"scope_contract": plan["scope_contract"]}
                if plan.get("scope_contract") is not None
                else {}
            ),
            "dxm_template_refs": template_refs.frozen_summary(),
            "fixed_values": self._values.clone(plan["fixed_values"]),
            "fill_rules": self._values.clone(plan["fill_rules"]),
            "source_policies": self._values.clone(plan.get("source_policies", {})),
            "item_snapshots": items,
            "mandatory_capabilities": mandatory_capabilities,
            "execution_constraints": {
                "max_age_hours": self._max_age_hours,
                "schema_drift_policy": DRIFT_POLICY_ABORT,
                "catalog_drift_policy": DRIFT_POLICY_ABORT,
                "plan_drift_policy": DRIFT_POLICY_ABORT,
            },
            "evidence_policy": "three_proofs",
            "failure_policy": {"unknown": "stop_batch"},
            "publish_allowed": False,
        }
        if plan.get("editor_actions"):
            snapshot["editor_actions"] = self._values.clone(plan["editor_actions"])
        snapshot_hash = canonical_sha256(snapshot)
        snapshot["plan_content_sha256"] = plan_content_sha256
        snapshot["snapshot_hash"] = snapshot_hash
        return snapshot

    def compile_instance(
        self,
        snapshot: Mapping[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Create an instance from a frozen snapshot with idempotency.

        Same plan_content_sha256 + different idempotency_key ->
        different snapshot_instance_sha256.
        """
        plan_content_sha = snapshot.get("plan_content_sha256")
        if not plan_content_sha:
            self._reject(
                "SNAPSHOT_INSTANCE_INVALID",
                "plan_content_sha256 is required for instance creation",
            )
        instance_body = {
            "schema": SNAPSHOT_INSTANCE_SCHEMA,
            "plan_content_sha256": plan_content_sha,
            "idempotency_key": str(idempotency_key),
            "snapshot_hash": snapshot.get("snapshot_hash"),
        }
        instance_sha = self._canonical_json_hash(instance_body)
        return {
            "schema": SNAPSHOT_INSTANCE_SCHEMA,
            "plan_content_sha256": plan_content_sha,
            "idempotency_key": str(idempotency_key),
            "snapshot_instance_sha256": instance_sha,
            "snapshot_hash": snapshot.get("snapshot_hash"),
        }

    def _freeze_plan_content(
        self,
        plan: Mapping[str, Any],
        target_category: dict[str, Any] | None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Build deterministic plan content for hashing."""
        content = {
            "id": plan["id"],
            "version": plan["version"],
            "shop_id": plan["shop_id"],
            "category_ids": sorted(plan["category_ids"]),
            "scope_contract": plan.get("scope_contract"),
            "fixed_values": self._values.clone(plan["fixed_values"]),
            "fill_rules": self._values.clone(plan["fill_rules"]),
            "source_policies": self._values.clone(plan.get("source_policies", {})),
            "idempotency_key": str(idempotency_key),
        }
        if target_category is not None:
            content["target_category"] = {
                "category_id": target_category["category_id"],
                "schema_hash": target_category["schema_hash"],
            }
        return {
            "plan_content_sha256": self._canonical_json_hash(content),
            "content": content,
        }

    def _canonical_json_hash(self, value: Any) -> str:
        """Compute deterministic SHA-256 from a value using canonical JSON."""
        serialized = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest().upper()

    def _check_mandatory_capabilities(self) -> dict[str, Any]:
        """Fail-closed check: if ANY mandatory capability is unavailable OR
        the capability_checker is not configured, reject freeze.

        A None checker (production default) MUST NOT silently pass: if no
        live capability verification is wired in, the safe default is to
        reject until the operator explicitly opts into a permissive mode.
        """
        if self._capability_checker is None:
            return {
                "ok": False,
                "reason_code": "MANDATORY_CAPABILITY_CHECKER_MISSING",
                "message": "未注入必选能力校验器，无法证明五项能力可用；拒绝冻结执行任务",
            }
        for cap in MANDATORY_CAPABILITIES:
            try:
                result = self._capability_checker.is_available(cap)
            except Exception as exc:
                return {
                    "ok": False,
                    "reason_code": f"MANDATORY_CAPABILITY_CHECKER_ERROR_{cap.upper()}",
                    "message": f"必选能力 {CAPABILITY_NAMES.get(cap, cap)} 校验异常：{exc}",
                }
            # An explicit {"ok": False} or {"available": False} both fail the
            # check; an absent/missing "ok" key defaults to True (legacy shape)
            # ONLY when the checker explicitly returned available=True. A bare
            # response of {} or {"available": False} is treated as unavailable.
            available = result.get("ok")
            if available is None:
                available = bool(result.get("available", False))
            if not available:
                return {
                    "ok": False,
                    "reason_code": f"MANDATORY_CAPABILITY_UNAVAILABLE_{cap.upper()}",
                    "message": f"必选能力 {CAPABILITY_NAMES.get(cap, cap)} 当前不可用，无法冻结执行任务",
                }
        return {"ok": True}

    def _build_mandatory_capabilities_block(self) -> dict[str, Any]:
        """Build the mandatory_capabilities block with all 5 capabilities enabled."""
        return {
            capability: {
                "enabled": True,
                "description": CAPABILITY_NAMES[capability],
                "required": True,
            }
            for capability in MANDATORY_CAPABILITIES
        }

    def assert_hash(self, snapshot: Mapping[str, Any]) -> None:
        reported = snapshot.get("snapshot_hash")
        body = {
            key: self._values.clone(value)
            for key, value in snapshot.items()
            if key
            not in {
                "id",
                "task_id",
                "created_at",
                "snapshot_hash",
                "plan_content_sha256",
                "snapshot_instance_sha256",
            }
        }
        if not isinstance(reported, str) or reported != canonical_sha256(body):
            self._reject(
                "PLAN_SNAPSHOT_HASH_INVALID",
                "plan snapshot hash cannot be reproduced",
            )

    def _normalize_target_category(
        self,
        request: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        target_category_id = request.get("target_category_id")
        if target_category_id in (None, ""):
            return None
        category_id = self._values.positive_id_text(
            target_category_id,
            "target_category_id",
        )
        raw_schema = request.get("target_category_schema")
        if not isinstance(raw_schema, dict):
            self._reject(
                "PLAN_TARGET_CATEGORY_INVALID",
                "target_category_schema must be an object",
            )
        normalized_schema = normalize_category_schema(raw_schema)
        schema_hash = canonical_sha256(normalized_schema)
        expected_hash = self._values.sha256_text(
            request.get("expected_target_schema_hash"),
            "expected_target_schema_hash",
        )
        if expected_hash != schema_hash:
            self._reject(
                "PLAN_TARGET_SCHEMA_DRIFT",
                "target category schema changed before the plan snapshot was frozen",
            )
        normalized_name = self._values.optional_text(
            request.get("target_category_name"),
            "target_category_name",
            max_length=120,
        )
        normalized_match = self._values.optional_text(
            request.get("target_category_match"),
            "target_category_match",
            max_length=200,
        )
        return {
            "category_id": category_id,
            "schema": normalized_schema,
            "schema_hash": schema_hash,
            **(
                {"category_name": normalized_name}
                if normalized_name is not None
                else {}
            ),
            **(
                {"category_match": normalized_match}
                if normalized_match is not None
                else {}
            ),
        }

    def _normalize_target_category(
        self,
        request: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        target_category_id = request.get("target_category_id")
        if target_category_id in (None, ""):
            return None
        category_id = self._values.positive_id_text(
            target_category_id,
            "target_category_id",
        )
        raw_schema = request.get("target_category_schema")
        if not isinstance(raw_schema, dict):
            self._reject(
                "PLAN_TARGET_CATEGORY_INVALID",
                "target_category_schema must be an object",
            )
        normalized_schema = normalize_category_schema(raw_schema)
        schema_hash = canonical_sha256(normalized_schema)
        expected_hash = self._values.sha256_text(
            request.get("expected_target_schema_hash"),
            "expected_target_schema_hash",
        )
        if expected_hash != schema_hash:
            self._reject(
                "PLAN_TARGET_SCHEMA_DRIFT",
                "target category schema changed before the plan snapshot was frozen",
            )
        normalized_name = self._values.optional_text(
            request.get("target_category_name"),
            "target_category_name",
            max_length=120,
        )
        normalized_match = self._values.optional_text(
            request.get("target_category_match"),
            "target_category_match",
            max_length=200,
        )
        return {
            "category_id": category_id,
            "schema": normalized_schema,
            "schema_hash": schema_hash,
            **(
                {"category_name": normalized_name}
                if normalized_name is not None
                else {}
            ),
            **(
                {"category_match": normalized_match}
                if normalized_match is not None
                else {}
            ),
        }

    def _build_item_snapshot(
        self,
        raw_item: Any,
        *,
        index: int,
        plan: Mapping[str, Any],
        template_refs: ResolvedTemplateReferences,
        requested_shop_id: str,
        requested_shop_name: str,
        target_category: dict[str, Any] | None,
        plan_content_sha256: str | None = None,
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
                "target_identity",
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
        if (
            plan.get("scope_contract") != "single_target_category.v2"
            and category_id not in set(plan["category_ids"])
        ):
            self._reject(
                "PLAN_CATEGORY_SCOPE_CONFLICT",
                f"商品类目 {category_id} 不在本地方案覆盖范围内"
                f"（方案仅覆盖：{', '.join(plan['category_ids'])}）",
            )
        try:
            target_identity = canonical_frozen_target_identity(
                item["target_identity"],
                store_name=requested_shop_name,
            )
        except MutationCommandContractError as exc:
            self._reject(
                "PLAN_TARGET_IDENTITY_INVALID",
                f"frozen item target is invalid: {exc.reason_code}",
            )
        if (
            target_identity is None
            or target_identity != item["target_identity"]
            or target_identity["stable_identity"]["kind"] != "product_id"
            or target_identity["stable_identity"]["value"] != product_id
        ):
            self._reject(
                "PLAN_TARGET_IDENTITY_INVALID",
                "frozen item target must exactly bind the current product_id",
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

        resolution_category_id = category_id
        resolution_schema = normalized_schema
        resolution_schema_hash = schema_hash
        if plan.get("scope_contract") == "single_target_category.v2":
            if target_category is None:
                self._reject(
                    "PLAN_TARGET_CATEGORY_REQUIRED",
                    "the selected plan requires its configured target category",
                )
            resolution_category_id = str(target_category["category_id"])
            resolution_schema = target_category["schema"]
            resolution_schema_hash = str(target_category["schema_hash"])

        mapping = self._normalize_field_mapping(
            plan["field_mappings"][resolution_category_id],
            category_id=resolution_category_id,
            schema=resolution_schema,
        )
        properties = resolution_schema["properties"]
        potential_required_keys = potential_required_fields(resolution_schema)
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
        fill_rules = plan["fill_rules"][resolution_category_id]
        source_policies = plan.get("source_policies", {}).get(resolution_category_id, {})
        fixed_field_values = (
            plan["fixed_values"]
            .get("field_values", {})
            .get(resolution_category_id, {})
        )
        template_values = template_refs.values_for_category(
            resolution_category_id,
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
                elif (
                    source_policies.get(field_key) == "current"
                    and field_key in current_values
                    and self._values.is_resolved_value(current_values[field_key])
                ):
                    value = self._values.clone(current_values[field_key])
                    source = "current"
                    source_ref = f"{product_id}@scope"
                elif (
                    source_policies.get(field_key) != "current"
                    and field_key in template_values
                ):
                    value, source_ref = template_values[field_key]
                    source = DXM_TEMPLATE_REF_MODEL
                elif (
                    source_policies.get(field_key) != "template"
                    and
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
            resolution_schema,
            resolved_values,
            phase="resolved_values",
        )
        active_required = active_required_fields(
            resolution_schema,
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
                resolution_schema
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
        target_category_snapshot: dict[str, Any] | None = None
        if target_category is not None:
            target_category_snapshot = self._resolve_target_category_preflight(
                target_category,
                plan=plan,
                template_refs=template_refs,
                current_values=current_values,
                product_id=product_id,
            )
            if plan.get("scope_contract") == "single_target_category.v2":
                target_category_snapshot["plan_owned"] = True
        real_write_stage_authority = self._freeze_real_write_stage_authority(
            plan=plan,
            mapping=mapping,
            properties=properties,
            current_values=current_values,
            resolved_fields=resolved_fields,
            unresolved_fields=unresolved_fields,
        )
        item_snapshot = {
            "product_id": product_id,
            "shop_id": shop_id,
            "source_urls": list(target_identity["source_urls"]),
            "target_identity": self._values.clone(target_identity),
            "target_identity_sha256": canonical_sha256(target_identity),
            "categoryId": category_id,
            "category_schema": {
                "normalized_schema": resolution_schema,
                "schema_hash": resolution_schema_hash,
            },
            "field_mapping": mapping,
            "current_value_snapshot": self._values.clone(current_values),
            "required_fields": required_fields,
            "resolution_result": {
                **resolution_body,
                "resolution_hash": canonical_sha256(resolution_body),
            },
            **real_write_stage_authority,
            **(
                {"target_category": target_category_snapshot}
                if target_category_snapshot is not None
                else {}
            ),
        }
        item_result = self._build_item_identity_hashes(
            product_id=product_id,
            shop_id=shop_id,
            category_id=category_id,
            target_identity=target_identity,
            normalized_schema=normalized_schema,
            target_category=target_category,
            plan_content_sha256=plan_content_sha256,
        )
        item_snapshot.update(item_result)
        return item_snapshot

    def _freeze_real_write_stage_authority(
        self,
        *,
        plan: Mapping[str, Any],
        mapping: Mapping[str, Any],
        properties: Mapping[str, Any],
        current_values: Mapping[str, Any],
        resolved_fields: list[dict[str, Any]],
        unresolved_fields: list[str],
    ) -> dict[str, Any]:
        """Freeze the exact Path B SAVE1/SAVE2 field and value authority.

        The normalized Reader schema is authoritative for the physical editor
        section.  SAVE2 is *only* ``ui_section=semi_managed``; all other known
        editor sections are SAVE1.  Every field authorized for a physical save
        must have an explicit Reader preimage and a resolved expected value.
        In particular, absence is never normalized to ``null`` because the
        current Reader contract omits unavailable values.
        """

        if str(plan.get("path") or "").strip().upper() != "B":
            return {}

        semi_managed = plan.get("semi_managed")
        if (
            plan.get("configuration_contract") != "local_plan_template.v3"
            or plan.get("status") != "ready"
            or not isinstance(semi_managed, Mapping)
            or semi_managed.get("enabled") is not True
        ):
            self._reject(
                "SEMI_MANAGED_PLAN_AUTHORITY_MISSING",
                "Path B snapshot requires a ready v3 plan with semi-managed enabled",
            )

        raw_entries = mapping.get("entries")
        if not isinstance(raw_entries, list) or not raw_entries:
            self._reject(
                "REAL_WRITE_STAGE_AUTHORITY_MISSING",
                "Path B field mapping is unavailable for stage derivation",
            )
        resolved_by_field: dict[str, Mapping[str, Any]] = {}
        for resolved in resolved_fields:
            field_key = resolved.get("field_key")
            if (
                not isinstance(field_key, str)
                or field_key in resolved_by_field
                or "resolved_value" not in resolved
            ):
                self._reject(
                    "REAL_WRITE_EXPECTED_FACT_INVALID",
                    "Path B resolved field facts are incomplete or duplicated",
                )
            resolved_by_field[field_key] = resolved

        unresolved = set(unresolved_fields)
        stage_fields: dict[str, list[str]] = {"SAVE1": [], "SAVE2": []}
        stage_facts: dict[str, list[dict[str, Any]]] = {
            "SAVE1": [],
            "SAVE2": [],
        }
        seen_fields: set[str] = set()
        for raw_entry in raw_entries:
            if not isinstance(raw_entry, Mapping):
                self._reject(
                    "REAL_WRITE_STAGE_AUTHORITY_MISSING",
                    "Path B field mapping contains an invalid entry",
                )
            field_key = raw_entry.get("field_key")
            if not isinstance(field_key, str) or field_key in seen_fields:
                self._reject(
                    "REAL_WRITE_STAGE_AUTHORITY_MISSING",
                    "Path B field mapping identity is invalid or duplicated",
                )
            seen_fields.add(field_key)
            definition = properties.get(field_key)
            if not isinstance(definition, Mapping):
                self._reject(
                    "REAL_WRITE_STAGE_AUTHORITY_MISSING",
                    f"field {field_key} is absent from the frozen Reader schema",
                )
            ui_section = definition.get("ui_section")
            if ui_section == _SAVE2_UI_SECTION:
                stage = "SAVE2"
            elif (
                isinstance(ui_section, str)
                and ui_section in _SAVE1_UI_SECTIONS
            ):
                stage = "SAVE1"
            else:
                self._reject(
                    "REAL_WRITE_STAGE_AUTHORITY_MISSING",
                    f"field {field_key} has no trusted Reader ui_section",
                )

            if field_key in unresolved:
                if stage == "SAVE2":
                    self._reject(
                        "SEMI_MANAGED_EXPECTED_FACT_MISSING",
                        f"semi-managed field {field_key} has no resolved expected value",
                    )
                continue
            resolved = resolved_by_field.get(field_key)
            if resolved is None:
                self._reject(
                    "REAL_WRITE_EXPECTED_FACT_MISSING",
                    f"field {field_key} has no resolved expected value",
                )
            if field_key not in current_values:
                reason_code = (
                    "SEMI_MANAGED_PREIMAGE_FACT_MISSING"
                    if stage == "SAVE2"
                    else "REAL_WRITE_PREIMAGE_FACT_MISSING"
                )
                self._reject(
                    reason_code,
                    f"field {field_key} has no explicit Reader preimage value",
                )

            ui_binding = definition.get("ui_binding")
            if (
                not isinstance(ui_binding, str)
                or ui_binding != raw_entry.get("ui_binding")
            ):
                self._reject(
                    "REAL_WRITE_BINDING_AUTHORITY_DRIFT",
                    f"field {field_key} binding differs from the frozen Reader schema",
                )
            stage_fields[stage].append(field_key)
            stage_facts[stage].append(
                {
                    "field_key": field_key,
                    "ui_section": ui_section,
                    "ui_binding": ui_binding,
                    "preimage_sha256": canonical_sha256(current_values[field_key]),
                    "expected_sha256": canonical_sha256(
                        resolved["resolved_value"]
                    ),
                }
            )

        if set(resolved_by_field) != {
            field_key
            for fields in stage_fields.values()
            for field_key in fields
        }:
            self._reject(
                "REAL_WRITE_STAGE_COVERAGE_INVALID",
                "Path B stage authority must exactly cover all resolved fields",
            )
        if not stage_fields["SAVE1"] or not stage_fields["SAVE2"]:
            self._reject(
                "REAL_WRITE_STAGE_EMPTY",
                "Path B requires non-empty trusted SAVE1 and SAVE2 field sets",
            )

        return {
            "real_write_stage_fields": stage_fields,
            "real_write_stage_facts": {
                "schema": _REAL_WRITE_STAGE_FACTS_SCHEMA,
                "stage_authority": (
                    "category_schema.normalized_schema.properties.ui_section"
                ),
                "preimage_source": "current_value_snapshot",
                "expected_source": "resolution_result.resolved_fields",
                "SAVE1": stage_facts["SAVE1"],
                "SAVE2": stage_facts["SAVE2"],
            },
        }

    def _build_item_identity_hashes(
        self,
        *,
        product_id: str,
        shop_id: str,
        category_id: str,
        target_identity: dict[str, Any],
        normalized_schema: dict[str, Any],
        target_category: dict[str, Any] | None,
        plan_content_sha256: str | None,
    ) -> dict[str, Any]:
        """Build per-item independent identity hashes for drift detection."""
        source_category_hash = self._canonical_json_hash({
            "category_id": category_id,
            "schema_hash": canonical_sha256(normalized_schema),
        })

        target_category_hash = None
        if target_category is not None:
            target_category_hash = self._canonical_json_hash({
                "category_id": target_category["category_id"],
                "schema_hash": target_category["schema_hash"],
            })

        catalog_node_hash = None
        if "catalog_node_identity" in target_identity:
            catalog_node_hash = canonical_sha256(
                target_identity["catalog_node_identity"]
            )

        catalog_hash = canonical_sha256(target_identity)

        schema_hash = canonical_sha256(normalized_schema)

        capabilities_hash = self._canonical_json_hash(
            dict(self._build_mandatory_capabilities_block())
        )

        return {
            "source_category_sha256": source_category_hash,
            "target_category_sha256": target_category_hash,
            "catalog_node_identity_sha256": catalog_node_hash,
            "catalog_sha256": catalog_hash,
            "schema_sha256": schema_hash,
            "capabilities_sha256": capabilities_hash,
            **(
                {"plan_content_sha256": plan_content_sha256}
                if plan_content_sha256
                else {}
            ),
        }

    def _resolve_target_category_preflight(
        self,
        target_category: Mapping[str, Any],
        *,
        plan: Mapping[str, Any],
        template_refs: ResolvedTemplateReferences,
        current_values: Mapping[str, Any],
        product_id: str,
    ) -> dict[str, Any]:
        category_id = str(target_category["category_id"])
        schema = target_category["schema"]
        properties = schema["properties"]
        required_keys = potential_required_fields(schema)
        field_mappings = plan["field_mappings"]
        if isinstance(field_mappings, dict) and category_id in field_mappings:
            mapping_entries = {
                entry["field_key"]
                for entry in self._normalize_field_mapping(
                    field_mappings[category_id],
                    category_id=category_id,
                    schema=schema,
                )["entries"]
            }
        else:
            mapping_entries = set()
        fill_rules = (
            plan["fill_rules"].get(category_id, {})
            if isinstance(plan["fill_rules"], dict)
            else {}
        )
        fixed_field_values = (
            plan["fixed_values"]
            .get("field_values", {})
            .get(category_id, {})
            if isinstance(plan["fixed_values"], dict)
            else {}
        )
        template_values = template_refs.values_for_category(
            category_id,
            allowed_fields=properties,
        )
        resolved_sources: dict[str, str] = {}
        unresolved: list[str] = []
        for field_key in required_keys:
            if (
                field_key in fixed_field_values
                and self._values.is_resolved_value(fixed_field_values[field_key])
            ):
                resolved_sources[field_key] = "fixed_value"
            elif (
                field_key in fill_rules
                and isinstance(fill_rules[field_key], dict)
                and set(fill_rules[field_key]) == {"value"}
                and self._values.is_resolved_value(fill_rules[field_key]["value"])
            ):
                resolved_sources[field_key] = LOCAL_PLAN_MODEL
            elif field_key in template_values:
                resolved_sources[field_key] = DXM_TEMPLATE_REF_MODEL
            elif (
                field_key in current_values
                and self._values.is_resolved_value(current_values[field_key])
            ):
                resolved_sources[field_key] = f"current@{product_id}"
            else:
                unresolved.append(field_key)
        if unresolved:
            self._reject(
                "PLAN_TARGET_REQUIRED_FIELD_UNRESOLVED",
                "target category required fields are unresolved for "
                + category_id
                + ": "
                + ", ".join(unresolved),
            )
        return {
            "category_id": category_id,
            "schema": {
                "normalized_schema": schema,
                "schema_hash": target_category["schema_hash"],
            },
            **(
                {"category_name": target_category["category_name"]}
                if "category_name" in target_category
                else {}
            ),
            **(
                {"category_match": target_category["category_match"]}
                if "category_match" in target_category
                else {}
            ),
            "required_fields_preflight": [
                {
                    "field_key": field_key,
                    "resolved_source": resolved_sources.get(field_key),
                }
                for field_key in required_keys
            ],
            "mapped_fields": sorted(mapping_entries),
            "unresolved_required_fields": unresolved,
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
