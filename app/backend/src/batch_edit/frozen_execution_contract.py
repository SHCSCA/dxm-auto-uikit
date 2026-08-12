from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from src.batch_edit.scope_contract import canonical_sha256


FROZEN_EXECUTION_PAYLOAD_SCHEMA = "dxm.batch_draft_save.execution_payload.v1"


class FrozenExecutionContractError(ValueError):
    def __init__(self, reason_code: str, detail: str) -> None:
        self.reason_code = reason_code
        super().__init__(detail)


def compile_frozen_execution_payload(
    task: Mapping[str, Any],
    job: Mapping[str, Any],
) -> dict[str, Any]:
    """Compile the only values E3 may write from one frozen E2 item snapshot."""

    product_id = _positive_id_text(job.get("product_id"), "job.product_id")
    payload = task.get("payload")
    plan = payload.get("plan_snapshot") if isinstance(payload, Mapping) else None
    if not isinstance(plan, Mapping):
        _reject("FROZEN_EXECUTION_SNAPSHOT_REQUIRED", "task plan_snapshot is missing")
    item_snapshots = plan.get("item_snapshots")
    if not isinstance(item_snapshots, list):
        _reject("FROZEN_EXECUTION_ITEMS_INVALID", "plan item_snapshots must be a list")
    matches = [
        item
        for item in item_snapshots
        if isinstance(item, Mapping)
        and str(item.get("product_id") or "").strip() == product_id
    ]
    if len(matches) != 1:
        _reject(
            "FROZEN_EXECUTION_ITEM_MISMATCH",
            "current job must bind exactly one frozen item_snapshot",
        )
    item = matches[0]
    category_id = _non_empty_text(item.get("categoryId"), "categoryId")

    category_schema = item.get("category_schema")
    if not isinstance(category_schema, Mapping):
        _reject("FROZEN_EXECUTION_SCHEMA_REQUIRED", "category_schema is missing")
    normalized_schema = category_schema.get("normalized_schema")
    schema_hash = _sha256_text(category_schema.get("schema_hash"), "schema_hash")
    if not isinstance(normalized_schema, Mapping):
        _reject("FROZEN_EXECUTION_SCHEMA_INVALID", "normalized category schema is missing")
    if canonical_sha256(normalized_schema) != schema_hash:
        _reject("FROZEN_EXECUTION_SCHEMA_DRIFT", "category schema hash does not match")
    properties = normalized_schema.get("properties")
    if not isinstance(properties, Mapping):
        _reject("FROZEN_EXECUTION_SCHEMA_INVALID", "category schema properties are missing")

    field_mapping = item.get("field_mapping")
    if not isinstance(field_mapping, Mapping):
        _reject("FROZEN_EXECUTION_MAPPING_REQUIRED", "field_mapping is missing")
    mapping_version = _non_empty_text(
        field_mapping.get("mapping_version"),
        "mapping_version",
    )
    entries = field_mapping.get("entries")
    mapping_hash = _sha256_text(field_mapping.get("mapping_hash"), "mapping_hash")
    if not isinstance(entries, list) or not entries:
        _reject("FROZEN_EXECUTION_MAPPING_INVALID", "field mapping entries are missing")
    mapping_body = {"mapping_version": mapping_version, "entries": entries}
    if canonical_sha256(mapping_body) != mapping_hash:
        _reject("FROZEN_EXECUTION_MAPPING_DRIFT", "field mapping hash does not match")

    resolution = item.get("resolution_result")
    if not isinstance(resolution, Mapping):
        _reject("FROZEN_EXECUTION_RESOLUTION_REQUIRED", "resolution_result is missing")
    resolved_fields = resolution.get("resolved_fields")
    unresolved_fields = resolution.get("unresolved_fields")
    price_validation = resolution.get("price_validation")
    resolution_hash = _sha256_text(
        resolution.get("resolution_hash"),
        "resolution_hash",
    )
    if not isinstance(resolved_fields, list):
        _reject("FROZEN_EXECUTION_RESOLUTION_INVALID", "resolved_fields must be a list")
    if not isinstance(unresolved_fields, list) or any(
        not isinstance(value, str) or not value.strip()
        for value in unresolved_fields
    ):
        _reject("FROZEN_EXECUTION_RESOLUTION_INVALID", "unresolved_fields is invalid")
    if not isinstance(price_validation, Mapping):
        _reject("FROZEN_EXECUTION_RESOLUTION_INVALID", "price_validation is missing")
    resolution_body = {
        "resolved_fields": resolved_fields,
        "unresolved_fields": unresolved_fields,
        "price_validation": price_validation,
    }
    if canonical_sha256(resolution_body) != resolution_hash:
        _reject("FROZEN_EXECUTION_RESOLUTION_DRIFT", "resolution hash does not match")

    mappings: dict[str, dict[str, str]] = {}
    for index, raw_entry in enumerate(entries):
        if not isinstance(raw_entry, Mapping):
            _reject("FROZEN_EXECUTION_MAPPING_INVALID", f"mapping entry {index} is invalid")
        field_key = _non_empty_text(raw_entry.get("field_key"), "field_key")
        ui_label_zh = _non_empty_text(
            raw_entry.get("ui_label_zh"),
            "ui_label_zh",
        )
        ui_binding = _non_empty_text(raw_entry.get("ui_binding"), "ui_binding")
        schema_path = _non_empty_text(
            raw_entry.get("category_schema_path"),
            "category_schema_path",
        )
        if field_key in mappings:
            _reject("FROZEN_EXECUTION_MAPPING_INVALID", "field mapping keys are duplicated")
        if schema_path != f"$.properties.{field_key}":
            _reject("FROZEN_EXECUTION_MAPPING_INVALID", "field mapping path is unstable")
        property_schema = properties.get(field_key)
        if (
            not isinstance(property_schema, Mapping)
            or property_schema.get("ui_binding") != ui_binding
        ):
            _reject(
                "FROZEN_EXECUTION_BINDING_DRIFT",
                "field UI binding is not proven by the frozen category schema",
            )
        mappings[field_key] = {
            "ui_label_zh": ui_label_zh,
            "ui_binding": ui_binding,
            "category_schema_path": schema_path,
        }

    fields: list[dict[str, Any]] = []
    seen_fields: set[str] = set()
    for index, raw_field in enumerate(resolved_fields):
        if not isinstance(raw_field, Mapping):
            _reject("FROZEN_EXECUTION_RESOLUTION_INVALID", f"resolved field {index} is invalid")
        field_key = _non_empty_text(raw_field.get("field_key"), "field_key")
        if field_key in seen_fields:
            _reject("FROZEN_EXECUTION_RESOLUTION_INVALID", "resolved field keys are duplicated")
        seen_fields.add(field_key)
        binding = mappings.get(field_key)
        if binding is None:
            _reject(
                "FROZEN_EXECUTION_BINDING_MISSING",
                f"resolved field {field_key} has no frozen UI binding",
            )
        if "resolved_value" not in raw_field:
            _reject(
                "FROZEN_EXECUTION_VALUE_MISSING",
                f"resolved field {field_key} has no value",
            )
        fields.append(
            {
                "field_key": field_key,
                "ui_label_zh": binding["ui_label_zh"],
                "ui_binding": binding["ui_binding"],
                "category_schema_path": binding["category_schema_path"],
                "resolved_value": deepcopy(raw_field["resolved_value"]),
            }
        )

    unresolved = [str(value).strip() for value in unresolved_fields]
    if len(set(unresolved)) != len(unresolved) or seen_fields.intersection(unresolved):
        _reject("FROZEN_EXECUTION_RESOLUTION_INVALID", "resolution field sets overlap or duplicate")
    body = {
        "schema": FROZEN_EXECUTION_PAYLOAD_SCHEMA,
        "product_id": product_id,
        "category_id": category_id,
        "category_schema_hash": schema_hash,
        "field_mapping_hash": mapping_hash,
        "resolution_hash": resolution_hash,
        "fields": fields,
        "unresolved_fields": unresolved,
        "price_validation": deepcopy(dict(price_validation)),
    }
    return {**body, "payload_hash": canonical_sha256(body)}


def frozen_execution_defaults(execution_payload: Mapping[str, Any]) -> dict[str, Any]:
    """Expose resolved values without consulting mutable templates or products."""

    fields = execution_payload.get("fields")
    if not isinstance(fields, list):
        _reject("FROZEN_EXECUTION_PAYLOAD_INVALID", "execution payload fields are missing")
    defaults: dict[str, Any] = {}
    for raw_field in fields:
        if not isinstance(raw_field, Mapping):
            _reject("FROZEN_EXECUTION_PAYLOAD_INVALID", "execution field is invalid")
        field_key = _non_empty_text(raw_field.get("field_key"), "field_key")
        if field_key in defaults or "resolved_value" not in raw_field:
            _reject("FROZEN_EXECUTION_PAYLOAD_INVALID", "execution field is duplicated or empty")
        defaults[field_key] = deepcopy(raw_field["resolved_value"])
    defaults["_frozen_execution_payload"] = deepcopy(dict(execution_payload))
    defaults["_frozen_execution_payload_hash"] = _sha256_text(
        execution_payload.get("payload_hash"),
        "payload_hash",
    )
    return defaults


def validate_frozen_execution_defaults(
    defaults: Any,
    *,
    expected_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify the actual Runner defaults are exactly the embedded frozen payload."""

    if not isinstance(defaults, Mapping):
        _reject("FROZEN_EXECUTION_DEFAULTS_INVALID", "execution defaults must be an object")
    execution_payload = defaults.get("_frozen_execution_payload")
    if not isinstance(execution_payload, Mapping):
        _reject("FROZEN_EXECUTION_PAYLOAD_REQUIRED", "embedded execution payload is missing")
    payload_hash = _sha256_text(
        execution_payload.get("payload_hash"),
        "payload_hash",
    )
    payload_body = {
        key: deepcopy(value)
        for key, value in execution_payload.items()
        if key != "payload_hash"
    }
    if canonical_sha256(payload_body) != payload_hash:
        _reject("FROZEN_EXECUTION_PAYLOAD_DRIFT", "execution payload hash does not match")
    if _sha256_text(
        defaults.get("_frozen_execution_payload_hash"),
        "_frozen_execution_payload_hash",
    ) != payload_hash:
        _reject("FROZEN_EXECUTION_PAYLOAD_DRIFT", "defaults payload hash does not match")
    canonical_defaults = frozen_execution_defaults(execution_payload)
    if dict(defaults) != canonical_defaults:
        _reject(
            "FROZEN_EXECUTION_DEFAULTS_DRIFT",
            "execution defaults differ from the embedded resolved fields",
        )
    if expected_payload is not None and dict(execution_payload) != dict(expected_payload):
        _reject(
            "FROZEN_EXECUTION_SNAPSHOT_DRIFT",
            "execution payload differs from the current frozen item snapshot",
        )
    return deepcopy(dict(execution_payload))


def _positive_id_text(value: Any, label: str) -> str:
    if isinstance(value, bool):
        _reject("FROZEN_EXECUTION_ID_INVALID", f"{label} must be a positive integer")
    text = str(value or "").strip()
    if not text.isdecimal() or int(text) <= 0:
        _reject("FROZEN_EXECUTION_ID_INVALID", f"{label} must be a positive integer")
    return text


def _non_empty_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        _reject("FROZEN_EXECUTION_TEXT_INVALID", f"{label} must be normalized text")
    return value


def _sha256_text(value: Any, label: str) -> str:
    text = _non_empty_text(value, label).upper()
    if len(text) != 64 or any(character not in "0123456789ABCDEF" for character in text):
        _reject("FROZEN_EXECUTION_HASH_INVALID", f"{label} must be SHA256")
    return text


def _reject(reason_code: str, detail: str) -> None:
    raise FrozenExecutionContractError(reason_code, detail)
