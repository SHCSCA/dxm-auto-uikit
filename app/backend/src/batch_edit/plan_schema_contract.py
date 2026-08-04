from __future__ import annotations

import math
import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from src.batch_edit.plan_value_contract import PlanValueContract
from src.batch_edit.scope_contract import canonical_sha256


class PlanSchemaError(ValueError):
    def __init__(self, reason_code: str, detail: str) -> None:
        self.reason_code = reason_code
        self.status_code = 409
        super().__init__(detail)


_SCHEMA_VALUES = PlanValueContract(PlanSchemaError)


def normalize_wire_value(
    value: Any,
    definition: Mapping[str, Any],
    *,
    field_key: str,
) -> Any:
    """Normalize only unambiguous wire encodings declared by frozen Schema."""

    expected_type = definition.get("type")
    if expected_type == "array":
        if isinstance(value, str) and definition.get("wire_format") == (
            "semicolon_delimited"
        ):
            raw_items = [item.strip() for item in value.split(";")]
            if not raw_items or any(not item for item in raw_items):
                _reject(
                    "PLAN_FIELD_WIRE_INVALID",
                    f"field {field_key} contains an empty delimited item",
                )
        else:
            raw_items = value if isinstance(value, list) else [value]
        item_schema = definition.get("items")
        if not isinstance(item_schema, Mapping):
            return [_SCHEMA_VALUES.clone(item) for item in raw_items]
        return [
            normalize_wire_value(
                item,
                item_schema,
                field_key=f"{field_key}[{index}]",
            )
            for index, item in enumerate(raw_items)
        ]
    if expected_type == "object":
        if not isinstance(value, Mapping):
            _reject(
                "PLAN_FIELD_WIRE_INVALID",
                f"field {field_key} wire value is not an object",
            )
        properties = definition.get("properties", {})
        normalized: dict[str, Any] = {}
        for child_key, child_value in value.items():
            child_schema = (
                properties.get(child_key)
                if isinstance(properties, Mapping)
                else None
            )
            normalized[child_key] = (
                normalize_wire_value(
                    child_value,
                    child_schema,
                    field_key=f"{field_key}.{child_key}",
                )
                if isinstance(child_schema, Mapping)
                else _SCHEMA_VALUES.clone(child_value)
            )
        return normalized
    if expected_type == "integer" and isinstance(value, str):
        if value != value.strip() or re.fullmatch(r"-?(?:0|[1-9]\d*)", value) is None:
            _reject(
                "PLAN_FIELD_WIRE_INVALID",
                f"field {field_key} is not a strict integer string",
            )
        return int(value)
    if expected_type == "number" and isinstance(value, str):
        if (
            value != value.strip()
            or re.fullmatch(r"-?(?:0|[1-9]\d*)(?:\.\d+)?", value) is None
        ):
            _reject(
                "PLAN_FIELD_WIRE_INVALID",
                f"field {field_key} is not a strict number string",
            )
        normalized_number = float(value) if "." in value else int(value)
        if not math.isfinite(normalized_number):
            _reject(
                "PLAN_FIELD_WIRE_INVALID",
                f"field {field_key} is not finite",
            )
        return normalized_number
    if expected_type == "boolean" and isinstance(value, str):
        if value not in {"true", "false", "1", "0"}:
            _reject(
                "PLAN_FIELD_WIRE_INVALID",
                f"field {field_key} is not a strict boolean string",
            )
        return value in {"true", "1"}
    return _SCHEMA_VALUES.clone(value)


def normalize_category_schema(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        _reject("CATEGORY_SCHEMA_INVALID", "category schema must be an object")
    normalized = _SCHEMA_VALUES.clone(raw)
    allowed_keys = {
        "type",
        "properties",
        "required",
        "dependentRequired",
        "allOf",
        "price_policy",
    }
    if (
        not {"type", "properties", "required"} <= set(normalized)
        or not set(normalized) <= allowed_keys
        or normalized["type"] != "object"
    ):
        _reject("CATEGORY_SCHEMA_INVALID", "category schema has an unexpected shape")
    properties = normalized["properties"]
    required = normalized["required"]
    if not isinstance(properties, dict) or not properties:
        _reject("CATEGORY_SCHEMA_INVALID", "category schema properties are required")
    if (
        not isinstance(required, list)
        or any(not isinstance(field, str) for field in required)
        or len(set(required)) != len(required)
        or any(field not in properties for field in required)
    ):
        _reject("CATEGORY_SCHEMA_INVALID", "category schema required fields are invalid")
    for field_key, definition in properties.items():
        _SCHEMA_VALUES.stable_field_key(field_key)
        _validate_schema_definition(definition, field_path=field_key)
    dependent_required = normalized.get("dependentRequired", {})
    if not isinstance(dependent_required, dict):
        _reject("CATEGORY_SCHEMA_INVALID", "dependentRequired must be an object")
    for trigger, dependencies in dependent_required.items():
        if (
            trigger not in properties
            or not isinstance(dependencies, list)
            or not dependencies
            or any(
                not isinstance(field, str) or field not in properties
                for field in dependencies
            )
            or len(set(dependencies)) != len(dependencies)
        ):
            _reject(
                "CATEGORY_SCHEMA_INVALID",
                "dependentRequired contains an invalid field dependency",
            )
    all_of = normalized.get("allOf", [])
    if not isinstance(all_of, list):
        _reject("CATEGORY_SCHEMA_INVALID", "allOf must be an array")
    for condition in all_of:
        _validate_required_condition(condition, properties=properties)
    price_policy = normalized.get("price_policy")
    if price_policy is not None and (
        not isinstance(price_policy, dict)
        or price_policy
        != {
            "sku_cargo_not_above_sale": True,
            "sku_prices_within_range": True,
        }
    ):
        _reject(
            "CATEGORY_SCHEMA_INVALID",
            "price_policy must be the frozen E2 price relationship contract",
        )
    return normalized


def required_field_rules(
    schema: Mapping[str, Any],
) -> list[tuple[str, str]]:
    rules: list[tuple[str, str]] = [
        (field_key, "always")
        for field_key in schema["required"]
    ]
    for trigger, dependencies in schema.get("dependentRequired", {}).items():
        rules.extend(
            (field_key, f"dependentRequired:{trigger}")
            for field_key in dependencies
        )
    for condition in schema.get("allOf", []):
        condition_hash = canonical_sha256(condition["if"])[:12]
        rules.extend(
            (field_key, f"condition:{condition_hash}")
            for field_key in condition["then"]["required"]
        )
    deduplicated: dict[str, str] = {}
    for field_key, required_when in rules:
        deduplicated.setdefault(field_key, required_when)
    return list(deduplicated.items())


def potential_required_fields(schema: Mapping[str, Any]) -> list[str]:
    return [
        field_key
        for field_key, _required_when in required_field_rules(schema)
    ]


def active_required_fields(
    schema: Mapping[str, Any],
    resolved_values: Mapping[str, Any],
) -> set[str]:
    active = set(schema["required"])
    for trigger, dependencies in schema.get("dependentRequired", {}).items():
        if trigger in resolved_values:
            active.update(dependencies)
    for condition in schema.get("allOf", []):
        raw_if = condition["if"]
        if any(
            field_key not in resolved_values
            for field_key in raw_if["required"]
        ):
            continue
        matched = True
        for field_key, predicate in raw_if["properties"].items():
            if field_key not in resolved_values:
                continue
            value = resolved_values[field_key]
            if "const" in predicate and value != predicate["const"]:
                matched = False
            if "enum" in predicate and value not in predicate["enum"]:
                matched = False
            if "contains" in predicate:
                expected_item = predicate["contains"]["const"]
                if not isinstance(value, list) or expected_item not in value:
                    matched = False
        if matched:
            active.update(condition["then"]["required"])
    return active


def schema_constraints(definition: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: _SCHEMA_VALUES.clone(value)
        for key, value in definition.items()
        if key != "natural_language"
    }


def assert_value_matches_schema(
    value: Any,
    definition: Mapping[str, Any],
    *,
    field_key: str,
) -> None:
    expected_type = definition.get("type")
    type_matches = {
        "string": isinstance(value, str),
        "number": (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
        ),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "boolean": type(value) is bool,
        "array": isinstance(value, list),
        "object": isinstance(value, dict),
    }.get(str(expected_type), False)
    if not type_matches:
        _reject(
            "PLAN_FIELD_SCHEMA_INVALID",
            f"field {field_key} does not match Schema type {expected_type}",
        )
    if "enum" in definition:
        enum_values = definition["enum"]
        if not isinstance(enum_values, list) or value not in enum_values:
            _reject(
                "PLAN_FIELD_SCHEMA_INVALID",
                f"field {field_key} is outside the frozen enum",
            )
    if "const" in definition and value != definition["const"]:
        _reject(
            "PLAN_FIELD_SCHEMA_INVALID",
            f"field {field_key} differs from the frozen const",
        )
    if isinstance(value, str):
        for constraint, predicate in (
            ("minLength", lambda limit: len(value) >= limit),
            ("maxLength", lambda limit: len(value) <= limit),
        ):
            if constraint not in definition:
                continue
            limit = definition[constraint]
            if (
                isinstance(limit, bool)
                or not isinstance(limit, int)
                or limit < 0
                or not predicate(limit)
            ):
                _reject(
                    "PLAN_FIELD_SCHEMA_INVALID",
                    f"field {field_key} violates {constraint}",
                )
        pattern = definition.get("pattern")
        if pattern is not None:
            if not isinstance(pattern, str):
                _reject(
                    "CATEGORY_SCHEMA_INVALID",
                    f"field {field_key} pattern is invalid",
                )
            try:
                matched = re.search(pattern, value) is not None
            except re.error as exc:
                raise PlanSchemaError(
                    "CATEGORY_SCHEMA_INVALID",
                    f"field {field_key} pattern cannot be compiled",
                ) from exc
            if not matched:
                _reject(
                    "PLAN_FIELD_SCHEMA_INVALID",
                    f"field {field_key} violates pattern",
                )
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        for constraint, predicate in (
            ("minimum", lambda limit: value >= limit),
            ("maximum", lambda limit: value <= limit),
            ("exclusiveMinimum", lambda limit: value > limit),
            ("exclusiveMaximum", lambda limit: value < limit),
        ):
            if constraint not in definition:
                continue
            limit = definition[constraint]
            if (
                isinstance(limit, bool)
                or not isinstance(limit, (int, float))
                or not predicate(limit)
            ):
                _reject(
                    "PLAN_FIELD_SCHEMA_INVALID",
                    f"field {field_key} violates {constraint}",
                )
    if isinstance(value, list):
        for constraint, predicate in (
            ("minItems", lambda limit: len(value) >= limit),
            ("maxItems", lambda limit: len(value) <= limit),
        ):
            if constraint not in definition:
                continue
            limit = definition[constraint]
            if (
                isinstance(limit, bool)
                or not isinstance(limit, int)
                or limit < 0
                or not predicate(limit)
            ):
                _reject(
                    "PLAN_FIELD_SCHEMA_INVALID",
                    f"field {field_key} violates {constraint}",
                )
        item_schema = definition.get("items")
        if item_schema is not None:
            for index, item in enumerate(value):
                assert_value_matches_schema(
                    item,
                    item_schema,
                    field_key=f"{field_key}[{index}]",
                )
    if isinstance(value, dict):
        nested_properties = definition.get("properties", {})
        nested_required = definition.get("required", [])
        for child_key in nested_required:
            if (
                child_key not in value
                or not _SCHEMA_VALUES.is_resolved_value(value[child_key])
            ):
                _reject(
                    "PLAN_FIELD_SCHEMA_INVALID",
                    f"field {field_key}.{child_key} is required",
                )
        for child_key, child_definition in nested_properties.items():
            if child_key not in value:
                continue
            assert_value_matches_schema(
                value[child_key],
                child_definition,
                field_key=f"{field_key}.{child_key}",
            )


def assert_price_policy(
    schema: Mapping[str, Any],
    values: Mapping[str, Any],
    *,
    phase: str,
) -> dict[str, Any]:
    policy = schema.get("price_policy")
    if policy is None:
        return {
            "active": False,
            "phase": phase,
            "checked_rules": [],
        }
    checked_rules: list[str] = []
    sku_prices: list[Decimal] = []
    raw_skus = values.get("aeopAeProductSKUs")
    if raw_skus is not None:
        if not isinstance(raw_skus, list):
            _reject(
                "PLAN_PRICE_RELATION_INVALID",
                "SKU values are not an array for frozen price validation",
            )
        for index, raw_sku in enumerate(raw_skus):
            if not isinstance(raw_sku, Mapping):
                _reject(
                    "PLAN_PRICE_RELATION_INVALID",
                    f"SKU {index} is not an object for frozen price validation",
                )
            sale_price = _optional_decimal(
                raw_sku.get("skuPrice"),
                field_key=f"aeopAeProductSKUs[{index}].skuPrice",
            )
            cargo_price = _optional_decimal(
                raw_sku.get("cargoPrice"),
                field_key=f"aeopAeProductSKUs[{index}].cargoPrice",
            )
            if sale_price is not None:
                sku_prices.append(sale_price)
            if sale_price is not None and cargo_price is not None:
                checked_rules.append(
                    f"sku[{index}].cargoPrice<=skuPrice"
                )
                if cargo_price > sale_price:
                    _reject(
                        "PLAN_PRICE_RELATION_INVALID",
                        f"SKU {index} cargoPrice exceeds skuPrice",
                    )
    minimum = _optional_decimal(
        values.get("productMinPrice"),
        field_key="productMinPrice",
    )
    maximum = _optional_decimal(
        values.get("productMaxPrice"),
        field_key="productMaxPrice",
    )
    if minimum is not None and maximum is not None:
        checked_rules.append("productMinPrice<=productMaxPrice")
        if minimum > maximum:
            _reject(
                "PLAN_PRICE_RELATION_INVALID",
                "productMinPrice exceeds productMaxPrice",
            )
    if sku_prices and minimum is not None and maximum is not None:
        checked_rules.append(
            "productMinPrice<=each.skuPrice<=productMaxPrice"
        )
        if any(not minimum <= price <= maximum for price in sku_prices):
            _reject(
                "PLAN_PRICE_RELATION_INVALID",
                "a SKU sale price is outside the frozen product price range",
            )
    return {
        "active": True,
        "phase": phase,
        "policy": _SCHEMA_VALUES.clone(policy),
        "checked_rules": checked_rules,
    }


def _optional_decimal(value: Any, *, field_key: str) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        _reject(
            "PLAN_PRICE_RELATION_INVALID",
            f"{field_key} is not a numeric price",
        )
    text = str(value)
    if (
        text != text.strip()
        or re.fullmatch(r"(?:0|[1-9]\d*)(?:\.\d+)?", text) is None
    ):
        _reject(
            "PLAN_PRICE_RELATION_INVALID",
            f"{field_key} is not a strict nonnegative price",
        )
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise PlanSchemaError(
            "PLAN_PRICE_RELATION_INVALID",
            f"{field_key} cannot be compared as a price",
        ) from exc


def _validate_schema_definition(
    definition: Any,
    *,
    field_path: str,
) -> None:
    if not isinstance(definition, dict) or not isinstance(
        definition.get("type"),
        str,
    ):
        _reject("CATEGORY_SCHEMA_INVALID", f"field {field_path} schema is invalid")
    if "natural_language" in definition and not isinstance(
        definition["natural_language"],
        bool,
    ):
        _reject("CATEGORY_SCHEMA_INVALID", "natural_language must be boolean")
    if definition["type"] == "object":
        nested_properties = definition.get("properties")
        nested_required = definition.get("required", [])
        if (
            not isinstance(nested_properties, dict)
            or not nested_properties
            or not isinstance(nested_required, list)
            or any(
                not isinstance(field, str) or field not in nested_properties
                for field in nested_required
            )
            or len(set(nested_required)) != len(nested_required)
        ):
            _reject(
                "CATEGORY_SCHEMA_INVALID",
                f"field {field_path} object schema is invalid",
            )
        for child_key, child_definition in nested_properties.items():
            _SCHEMA_VALUES.stable_field_key(child_key)
            _validate_schema_definition(
                child_definition,
                field_path=f"{field_path}.{child_key}",
            )
    if definition["type"] == "array" and "items" in definition:
        _validate_schema_definition(
            definition["items"],
            field_path=f"{field_path}[]",
        )


def _validate_required_condition(
    condition: Any,
    *,
    properties: Mapping[str, Any],
) -> None:
    if not isinstance(condition, dict) or set(condition) != {"if", "then"}:
        _reject("CATEGORY_SCHEMA_INVALID", "allOf conditions must contain if/then")
    raw_if = condition["if"]
    raw_then = condition["then"]
    if (
        not isinstance(raw_if, dict)
        or set(raw_if) != {"properties", "required"}
        or not isinstance(raw_if["properties"], dict)
        or not isinstance(raw_if["required"], list)
        or not isinstance(raw_then, dict)
        or set(raw_then) != {"required"}
        or not isinstance(raw_then["required"], list)
    ):
        _reject("CATEGORY_SCHEMA_INVALID", "conditional required shape is invalid")
    condition_fields = raw_if["properties"]
    referenced = list(raw_if["required"]) + list(condition_fields)
    then_required = raw_then["required"]
    if (
        any(field not in properties for field in referenced)
        or any(field not in properties for field in then_required)
        or len(set(raw_if["required"])) != len(raw_if["required"])
        or not then_required
        or len(set(then_required)) != len(then_required)
    ):
        _reject("CATEGORY_SCHEMA_INVALID", "conditional required fields are invalid")
    for definition in condition_fields.values():
        contains = (
            definition.get("contains")
            if isinstance(definition, dict)
            else None
        )
        contains_is_valid = (
            isinstance(contains, dict)
            and set(contains) == {"const"}
            and not isinstance(contains["const"], (dict, list))
        )
        if (
            not isinstance(definition, dict)
            or not definition
            or not set(definition) <= {"const", "enum", "contains"}
            or ("contains" in definition and not contains_is_valid)
            or (
                "enum" in definition
                and (
                    not isinstance(definition["enum"], list)
                    or not definition["enum"]
                )
            )
        ):
            _reject(
                "CATEGORY_SCHEMA_INVALID",
                "conditional required predicates must use const/enum/contains.const",
            )


def _reject(reason_code: str, detail: str) -> None:
    raise PlanSchemaError(reason_code, detail)
