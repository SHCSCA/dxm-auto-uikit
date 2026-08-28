from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from src.batch_edit.scope_contract import canonical_sha256
from src.batch_edit.plan_value_contract import PlanValueContract


LOCAL_PLAN_MODEL = "local_plan_template"
SEMVER_PATTERN = re.compile(
    r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)
HAN_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


class PlanTemplateContractError(ValueError):
    def __init__(self, reason_code: str, detail: str) -> None:
        self.reason_code = reason_code
        super().__init__(detail)


_plan_values = PlanValueContract(PlanTemplateContractError)
_assert_no_publish_true = _plan_values.assert_no_publish_true
_is_resolved_value = _plan_values.is_resolved_value
_exact_object = _plan_values.exact_object
_stable_field_key = _plan_values.stable_field_key
_positive_id_text = _plan_values.positive_id_text
_sha256_text = _plan_values.sha256_text
_non_empty_text = _plan_values.non_empty_text
_clone = _plan_values.clone
_reject = _plan_values.reject


def normalize_local_plan_payload(payload: Any) -> dict[str, Any]:
    plan = _exact_object(
        payload,
        {
            "name",
            "version",
            "shop_id",
            "category_ids",
            "path",
            "fixed_values",
            "fill_rules",
            "dxm_template_refs",
            "field_mappings",
            "validation_policy",
            "exception_policy",
            "provenance",
        },
        LOCAL_PLAN_MODEL,
        optional_keys=frozenset({
            "source_policies",
            "editor_actions",
            "scope_contract",
            "configuration_contract",
            "status",
            "semi_managed",
            "source_snapshots",
        }),
    )
    name = _non_empty_text(plan["name"], "plan name")
    version = _non_empty_text(plan["version"], "plan version")
    if len(version) > 32 or SEMVER_PATTERN.fullmatch(version) is None:
        _reject("LOCAL_PLAN_VERSION_INVALID", "local plan version must be semver")
    if plan["path"] not in {"A", "B"}:
        _reject("PLAN_PATH_FORBIDDEN", "local plan path must be A or B")
    shop_id = _positive_id_text(plan["shop_id"], "shop_id")
    category_ids = plan["category_ids"]
    if not isinstance(category_ids, list) or not category_ids:
        _reject(
            "LOCAL_PLAN_CATEGORY_SCOPE_INVALID",
            "local plan requires category constraints",
        )
    normalized_categories = [
        _positive_id_text(value, "category_id")
        for value in category_ids
    ]
    if len(set(normalized_categories)) != len(normalized_categories):
        _reject(
            "LOCAL_PLAN_CATEGORY_SCOPE_INVALID",
            "local plan categories must be unique",
        )
    scope_contract = plan.get("scope_contract")
    if scope_contract not in {None, "single_category.v1", "single_target_category.v2"}:
        _reject(
            "LOCAL_PLAN_CATEGORY_SCOPE_INVALID",
            "unknown local plan category scope contract",
        )

    configuration_contract = plan.get("configuration_contract")
    if configuration_contract not in {None, "local_plan_template.v3"}:
        _reject(
            "LOCAL_PLAN_CONFIGURATION_CONTRACT_INVALID",
            "unknown local plan configuration contract",
        )
    status = plan.get("status", "ready")
    if status not in {"draft", "ready"}:
        _reject(
            "LOCAL_PLAN_STATUS_INVALID",
            "local plan status must be draft or ready",
        )
    semi_managed = plan.get("semi_managed")
    source_snapshots = plan.get("source_snapshots", {})
    if configuration_contract == "local_plan_template.v3":
        if not isinstance(source_snapshots, dict):
            _reject(
                "LOCAL_PLAN_SOURCE_SNAPSHOTS_INVALID",
                "source snapshots must be an object",
            )
        if plan["path"] == "A" and isinstance(semi_managed, dict) and semi_managed.get("enabled") is True:
            _reject(
                "SEMI_MANAGED_PATH_INVALID",
                "path A cannot enable semi-managed configuration",
            )
        if plan["path"] == "B" and status == "ready":
            if not isinstance(semi_managed, dict) or semi_managed.get("enabled") is not True:
                _reject(
                    "SEMI_MANAGED_CONFIG_REQUIRED",
                    "ready path B plans require semi-managed configuration",
                )
            countries = semi_managed.get("countries")
            goods = semi_managed.get("goods_config")
            variants = semi_managed.get("variant_config")
            if not isinstance(countries, list) or not countries:
                _reject(
                    "SEMI_MANAGED_COUNTRIES_REQUIRED",
                    "ready path B plans require explicit participating countries",
                )
            if not isinstance(goods, dict) or not isinstance(variants, dict):
                _reject(
                    "SEMI_MANAGED_RULES_REQUIRED",
                    "ready path B plans require independent goods and variant rules",
                )
    if scope_contract in {"single_category.v1", "single_target_category.v2"} and len(normalized_categories) != 1:
        _reject(
            "LOCAL_PLAN_CATEGORY_SCOPE_INVALID",
            f"{scope_contract} requires exactly one category",
        )

    fixed_values = plan["fixed_values"]
    if (
        not isinstance(fixed_values, dict)
        or fixed_values.get("publish_allowed") is not False
        or not set(fixed_values) <= {"publish_allowed", "field_values"}
    ):
        _reject(
            "PLAN_PUBLISH_FORBIDDEN",
            "local plan must freeze publish_allowed=false",
        )
    _assert_no_publish_true(fixed_values)
    fill_rules = plan["fill_rules"]
    field_mappings = plan["field_mappings"]
    expected_category_keys = set(normalized_categories)
    if not isinstance(fill_rules, dict) or set(fill_rules) != expected_category_keys:
        _reject(
            "LOCAL_PLAN_FILL_RULES_INVALID",
            "fill rules must be isolated per category",
        )
    if (
        not isinstance(field_mappings, dict)
        or set(field_mappings) != expected_category_keys
    ):
        _reject(
            "LOCAL_PLAN_FIELD_MAPPING_INVALID",
            "field mappings must be isolated per category",
        )
    fixed_field_values = fixed_values.get("field_values", {})
    source_policies = plan.get("source_policies", {})
    editor_actions = plan.get("editor_actions", {})
    if not isinstance(source_policies, dict) or (
        source_policies and set(source_policies) != expected_category_keys
    ):
        _reject(
            "LOCAL_PLAN_SOURCE_POLICIES_INVALID",
            "source policies must be isolated per category",
        )
    if not isinstance(editor_actions, dict) or (
        editor_actions and set(editor_actions) != expected_category_keys
    ):
        _reject(
            "LOCAL_PLAN_EDITOR_ACTIONS_INVALID",
            "editor actions must be isolated per category",
        )
    if (
        not isinstance(fixed_field_values, dict)
        or (
            fixed_field_values
            and set(fixed_field_values) != expected_category_keys
        )
    ):
        _reject(
            "LOCAL_PLAN_FIXED_VALUES_INVALID",
            "fixed field values must be isolated per category",
        )
    for category_id in normalized_categories:
        category_rules = fill_rules[category_id]
        if not isinstance(category_rules, dict):
            _reject(
                "LOCAL_PLAN_FILL_RULES_INVALID",
                "category fill rules must be an object",
            )
        for field_key, rule in category_rules.items():
            _stable_field_key(field_key)
            if not isinstance(rule, dict) or set(rule) != {"value"}:
                _reject(
                    "LOCAL_PLAN_FILL_RULES_INVALID",
                    "each fill rule must contain only value",
                )
        normalized_mapping = normalize_field_mapping(
            field_mappings[category_id],
            category_id=category_id,
            schema=None,
        )
        category_fixed_values = fixed_field_values.get(category_id, {})
        if not isinstance(category_fixed_values, dict):
            _reject(
                "LOCAL_PLAN_FIXED_VALUES_INVALID",
                "category fixed field values must be an object",
            )
        mapped_fields = {
            entry["field_key"]
            for entry in normalized_mapping["entries"]
        }
        category_source_policies = source_policies.get(category_id, {})
        category_editor_actions = editor_actions.get(category_id, {})
        if not isinstance(category_editor_actions, dict) or set(category_editor_actions) - {"description", "marketing_images"}:
            _reject(
                "LOCAL_PLAN_EDITOR_ACTIONS_INVALID",
                "category editor actions only support description and marketing_images",
            )
        if "description" in category_editor_actions and category_editor_actions["description"] != {
            "editor": "new",
            "generate_mobile_from_pc": True,
            "confirm_before_save": True,
        }:
            _reject(
                "LOCAL_PLAN_EDITOR_ACTIONS_INVALID",
                "description action must bind the proven new-editor workflow",
            )
        if "marketing_images" in category_editor_actions and category_editor_actions["marketing_images"] != {
            "generate_from_product_images": True,
            "required_slots": ["1:1_white_background", "3:4_scene"],
        }:
            _reject(
                "LOCAL_PLAN_EDITOR_ACTIONS_INVALID",
                "marketing image action must bind the proven one-click workflow",
            )
        if not isinstance(category_source_policies, dict):
            _reject(
                "LOCAL_PLAN_SOURCE_POLICIES_INVALID",
                "category source policies must be an object",
            )
        for field_key, policy in category_source_policies.items():
            _stable_field_key(field_key)
            if field_key not in mapped_fields or policy not in {
                "auto",
                "current",
                "template",
            }:
                _reject(
                    "LOCAL_PLAN_SOURCE_POLICIES_INVALID",
                    "source policy must bind a mapped field and be auto/current/template",
                )
        for field_key, fixed_value in category_fixed_values.items():
            _stable_field_key(field_key)
            if (
                field_key not in mapped_fields
                or not _is_resolved_value(fixed_value)
            ):
                _reject(
                    "LOCAL_PLAN_FIXED_VALUES_INVALID",
                    "fixed field values must bind mapped non-empty fields",
                )

    bindings = plan["dxm_template_refs"]
    allow_incomplete_v3_draft = (
        configuration_contract == "local_plan_template.v3"
        and status == "draft"
    )
    if not isinstance(bindings, list) or (not bindings and not allow_incomplete_v3_draft):
        _reject(
            "DXM_TEMPLATE_REF_REQUIRED",
            "local plan requires readonly DXM template references",
        )
    normalized_bindings: list[dict[str, Any]] = []
    seen_refs: set[int] = set()
    for index, raw in enumerate(bindings):
        binding = _exact_object(
            raw,
            {"ref_id", "source_digest"},
            f"dxm_template_refs[{index}]",
        )
        ref_id = binding["ref_id"]
        if (
            isinstance(ref_id, bool)
            or not isinstance(ref_id, int)
            or ref_id <= 0
            or ref_id in seen_refs
        ):
            _reject(
                "DXM_TEMPLATE_REF_BINDING_INVALID",
                "DXM template reference ids must be unique",
            )
        seen_refs.add(ref_id)
        normalized_bindings.append(
            {
                "ref_id": ref_id,
                "source_digest": _sha256_text(
                    binding["source_digest"],
                    "source_digest",
                ),
            }
        )
    validation_policy = plan["validation_policy"]
    if validation_policy != {
        "required_fields": "fail_closed",
        "natural_language": "english_before_save",
    }:
        _reject(
            "LOCAL_PLAN_VALIDATION_POLICY_INVALID",
            "local plan validation policy is not fail-closed",
        )
    if plan["exception_policy"] != {"unknown": "stop_batch"}:
        _reject(
            "LOCAL_PLAN_EXCEPTION_POLICY_INVALID",
            "UNKNOWN must stop the batch",
        )
    normalized = {
        "name": name,
        "version": version,
        "shop_id": shop_id,
        "category_ids": normalized_categories,
        "path": plan["path"],
        "fixed_values": _clone(fixed_values),
        "fill_rules": _clone(fill_rules),
        "dxm_template_refs": normalized_bindings,
        "field_mappings": _clone(field_mappings),
        "source_policies": {
            category_id: _clone(source_policies.get(category_id, {}))
            for category_id in normalized_categories
        },
        "validation_policy": _clone(validation_policy),
        "exception_policy": {"unknown": "stop_batch"},
        "provenance": _non_empty_text(plan["provenance"], "provenance"),
    }
    if editor_actions:
        normalized["editor_actions"] = {
            category_id: _clone(editor_actions.get(category_id, {}))
            for category_id in normalized_categories
        }
    if scope_contract is not None:
        normalized["scope_contract"] = scope_contract
    if configuration_contract is not None:
        normalized["configuration_contract"] = configuration_contract
        normalized["status"] = status
        normalized["source_snapshots"] = _clone(source_snapshots)
        if semi_managed is not None:
            normalized["semi_managed"] = _clone(semi_managed)
    _assert_no_publish_true(normalized)
    return normalized


def normalize_field_mapping(
    raw: Any,
    *,
    category_id: str,
    schema: Mapping[str, Any] | None,
) -> dict[str, Any]:
    mapping = _exact_object(
        raw,
        {"mapping_version", "entries"},
        f"field_mappings[{category_id}]",
    )
    version = _non_empty_text(mapping["mapping_version"], "mapping_version")
    entries = mapping["entries"]
    if not isinstance(entries, list) or not entries:
        _reject(
            "LOCAL_PLAN_FIELD_MAPPING_INVALID",
            "field mapping entries are required",
        )
    normalized_entries: list[dict[str, str]] = []
    seen_fields: set[str] = set()
    properties = schema.get("properties") if isinstance(schema, Mapping) else None
    for index, raw_entry in enumerate(entries):
        entry = _exact_object(
            raw_entry,
            {"ui_label_zh", "field_key", "category_schema_path", "ui_binding"},
            f"field_mappings[{category_id}].entries[{index}]",
        )
        label = _non_empty_text(entry["ui_label_zh"], "ui_label_zh")
        if HAN_PATTERN.search(label) is None:
            _reject(
                "LOCAL_PLAN_FIELD_MAPPING_INVALID",
                "operator field labels must be Chinese",
            )
        field_key = _stable_field_key(entry["field_key"])
        if field_key in seen_fields:
            _reject(
                "LOCAL_PLAN_FIELD_MAPPING_INVALID",
                "field mapping keys must be unique",
            )
        seen_fields.add(field_key)
        path = _non_empty_text(
            entry["category_schema_path"],
            "category_schema_path",
        )
        if path != f"$.properties.{field_key}":
            _reject(
                "LOCAL_PLAN_FIELD_MAPPING_INVALID",
                "field mapping schema path is not stable",
            )
        if isinstance(properties, Mapping) and field_key not in properties:
            _reject(
                "LOCAL_PLAN_FIELD_MAPPING_INVALID",
                "field mapping is absent from category schema",
            )
        ui_binding = _non_empty_text(entry["ui_binding"], "ui_binding")
        if isinstance(properties, Mapping):
            expected_binding = properties[field_key].get("ui_binding")
            if (
                not isinstance(expected_binding, str)
                or re.fullmatch(
                    r"dxm_(?:editor:[A-Za-z][A-Za-z0-9_]*|attribute:[1-9][0-9]*)",
                    expected_binding,
                ) is None
                or ui_binding != expected_binding
            ):
                _reject(
                    "LOCAL_PLAN_FIELD_MAPPING_INVALID",
                    "ui_binding is not proven by the frozen category schema",
                )
        normalized_entries.append(
            {
                "ui_label_zh": label,
                "field_key": field_key,
                "category_schema_path": path,
                "ui_binding": ui_binding,
            }
        )
    body = {"mapping_version": version, "entries": normalized_entries}
    return {**body, "mapping_hash": canonical_sha256(body)}
