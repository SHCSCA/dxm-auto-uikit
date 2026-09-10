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


def validate_editor_actions(actions: Any, field_values: Mapping[str, Any] | None = None) -> None:
    """Validate shared action configuration; this does not establish runtime capability."""
    if not isinstance(actions, dict) or set(actions) - {"description", "marketing_images", "video", "wholesale", "translation"}:
        _reject("LOCAL_PLAN_EDITOR_ACTIONS_INVALID", "unsupported shared editor action")
    if "description" in actions and actions["description"] != {
        "editor": "new", "generate_mobile_from_pc": True, "confirm_before_save": True,
    }:
        _reject("LOCAL_PLAN_EDITOR_ACTIONS_INVALID", "description action must bind the proven new-editor workflow")
    if "marketing_images" in actions and actions["marketing_images"] != {
        "generate_from_product_images": True, "required_slots": ["1:1_white_background", "3:4_scene"],
    }:
        _reject("LOCAL_PLAN_EDITOR_ACTIONS_INVALID", "marketing image action must bind the proven one-click workflow")
    if not set(actions).intersection({"video", "wholesale", "translation"}):
        return

    from dataclasses import fields
    from src.batch_edit.path_a_section_templates import AutoTranslateConfig, VideoGenerationConfig, WholesaleConfig
    from src.batch_edit.translator import BatchTranslator
    from src.batch_edit.wholesale_filler import WholesaleFiller

    for name, model in (("video", VideoGenerationConfig), ("wholesale", WholesaleConfig), ("translation", AutoTranslateConfig)):
        if name not in actions:
            continue
        config = actions[name]
        required_keys = {field.name for field in fields(model)}
        allowed_shapes = (required_keys, required_keys | {'generation_rule'}) if name == 'video' else (required_keys,)
        if (not isinstance(config, dict) or set(config) not in allowed_shapes
                or config.get("enabled") is not True):
            _reject("LOCAL_PLAN_EDITOR_ACTIONS_INVALID", f"{name} requires every explicit configuration field and enabled=true")
        if name == "video":
            if 'generation_rule' in config:
                from src.batch_edit.video_generator import validate_native_video_generation_rule
                try:
                    validate_native_video_generation_rule(config['generation_rule'])
                except ValueError as exc:
                    _reject('LOCAL_PLAN_EDITOR_ACTIONS_INVALID', str(exc))
            valid = (config["failure_strategy"] == "pause"
                     and type(config["max_wait_seconds"]) is int and type(config["poll_interval_seconds"]) is int
                     and 0 < config["poll_interval_seconds"] <= config["max_wait_seconds"])
        elif name == "wholesale":
            valid = (type(config["min_quantity"]) is int and type(config["discount_percent"]) is int
                     and WholesaleFiller.TIER_MIN_QUANTITY_RANGE[0] <= config["min_quantity"] <= WholesaleFiller.TIER_MIN_QUANTITY_RANGE[1]
                     and WholesaleFiller.DISCOUNT_RANGE[0] <= config["discount_percent"] <= WholesaleFiller.DISCOUNT_RANGE[1]
                     and isinstance(config["deduction_method"], str)
                     and config["deduction_method"] in WholesaleFiller.VALID_DEDUCTION_METHODS)
        else:
            apply_to = config["apply_to"]
            # Use the existing translator's concrete field names, including both descriptions.
            valid = (config["direction"] == "zh_en" and isinstance(config["translate_type"], str)
                     and config["translate_type"] in BatchTranslator.TRANSLATE_TYPE_MAP
                     and isinstance(apply_to, list) and all(isinstance(value, str) for value in apply_to)
                     and len(apply_to) == len(set(apply_to))
                     and set(apply_to) == {"title", "attributes", "description_pc", "description_mobile", "custom_name"})
        if not valid:
            _reject("LOCAL_PLAN_EDITOR_ACTIONS_INVALID", f"{name} explicit configuration is invalid")
    wholesale = actions.get("wholesale")
    if wholesale is not None and field_values is not None:
        for field_key, action_key in (("bulkOrder", "min_quantity"), ("bulkDiscount", "discount_percent")):
            if field_key in field_values and (isinstance(field_values[field_key], bool) or field_values[field_key] != wholesale[action_key]):
                _reject("LOCAL_PLAN_EDITOR_ACTIONS_INVALID", f"wholesale conflicts with frozen field {field_key}")
        if "reduceStrategy" in field_values and not (
            field_values["reduceStrategy"] == "payment_success_deduct" and wholesale["deduction_method"] == "payment"
        ):
            _reject("LOCAL_PLAN_EDITOR_ACTIONS_INVALID", "wholesale deduction conflicts with or lacks a proven reduceStrategy binding")


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
    if isinstance(semi_managed, dict) and "freeze_timing" in semi_managed:
        if plan["path"] != "B" or semi_managed["freeze_timing"] != "after_native_gate":
            _reject("SEMI_MANAGED_FREEZE_TIMING_INVALID", "deferred freeze is only allowed after the native Path B gate")
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
            if isinstance(rule, dict) and set(rule) == {"value"}:
                continue
            row_values = rule.get("set_each") if isinstance(rule, dict) else None
            if (
                field_key != "aeopAeProductSKUs"
                or not isinstance(rule, dict)
                or set(rule) != {"source", "set_each"}
                or rule["source"] != "current"
                or not isinstance(row_values, dict)
                or not row_values
                or set(row_values) - {
                    "skuPrice", "cargoPrice", "ipmSkuStock", "packageWeight",
                    "packageLength", "packageWidth", "packageHeight",
                    "originalBox", "logisticAttrList",
                }
                or any(not _is_resolved_value(value) for value in row_values.values())
            ):
                _reject(
                    "LOCAL_PLAN_FILL_RULES_INVALID",
                    "fill rules require value or a shared current-SKU set_each rule; SKU identity cannot be overridden",
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
        explicit_values = {
            field_key: rule["value"] for field_key, rule in category_rules.items()
            if isinstance(rule, dict) and set(rule) == {"value"}
        }
        explicit_values.update(category_fixed_values)
        validate_editor_actions(category_editor_actions, explicit_values)
        for entry in normalized_mapping['entries']:
            if 'delegated_to' in entry:
                action = entry['delegated_to'].removeprefix('content_finalize.')
                if plan.get('path') != 'B' or category_editor_actions.get(action, {}).get('enabled') is not True:
                    _reject('CONTENT_FINALIZE_ACTION_REQUIRED', 'delegated fields require the enabled shared Path B action')
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
            optional_keys=frozenset({"delegated_to"}),
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
        owner = entry.get("delegated_to")
        if "delegated_to" in entry and (
            not isinstance(owner, str) or owner not in {"content_finalize.video", "content_finalize.translation"}
        ):
            _reject("CONTENT_FINALIZE_OWNER_INVALID", "only video and translation may own generated output fields")
        if owner == 'content_finalize.video' and (field_key != 'videoUrl' or ui_binding != 'dxm_editor:videoUrl'):
            _reject('CONTENT_FINALIZE_VIDEO_FIELD_INVALID', 'video output must bind the product video field')
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
                **({"delegated_to": owner} if "delegated_to" in entry else {}),
            }
        )
    body = {"mapping_version": version, "entries": normalized_entries}
    return {**body, "mapping_hash": canonical_sha256(body)}
