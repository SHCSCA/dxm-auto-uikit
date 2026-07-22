from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from src.batch_edit.scope_contract import SCOPE_SCHEMA, canonical_sha256
from src.services.dxm_reference_templates import (
    UNSUPPORTED_REFERENCE_TEMPLATE_SECTIONS,
    resolve_dxm_reference_templates,
)
from src.services.config_validation import ConfigValidationService


BATCH_SCHEMA = "dxm_edit_batch.v1"
TEMPLATE_BUNDLE_SCHEMA = "dxm_edit_template_bundle.v1"
POLICY_SCHEMA = "dxm_edit_batch_policy.v1"
BATCH_TEMPLATE_TYPE = "edit_batch_bundle"
BATCH_TEMPLATE_REQUIRED_SECTIONS = (
    "category",
    "sku",
    "pricing",
    "logistics",
    "image",
    "compliance",
    "semi_managed",
    "dxm_reference",
)
SOURCE_TEMPLATE_SNAPSHOT_KEYS = {
    "id",
    "template_type",
    "template_name",
    "binding_scope",
    "payload",
    "is_enabled",
    "created_at",
    "updated_at",
}
SOURCE_TEMPLATE_RECORD_KEYS = {
    "template_id",
    "template_type",
    "template_name",
    "binding_scope",
    "source_digest",
    "snapshot",
}
PUBLISH_BOOLEAN_KEYS = {"publish", "published", "should_publish", "auto_publish"}
PUBLISH_ACTION_KEYS = {"action", "intended_action", "target_action"}
FORBIDDEN_PUBLISH_ACTIONS = {"publish", "continue_publish", "save_and_publish"}


class BatchContractError(ValueError):
    def __init__(self, reason_code: str, detail: str) -> None:
        self.reason_code = reason_code
        super().__init__(detail)


def freeze_scope_snapshot(snapshot: Any) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        _reject("SCOPE_SNAPSHOT_NOT_FOUND", "scope snapshot does not exist")
    if snapshot.get("schema_version") != SCOPE_SCHEMA:
        _reject("SCOPE_SNAPSHOT_INVALID", "scope snapshot schema is not supported")
    snapshot_id = snapshot.get("id")
    created_at = snapshot.get("created_at")
    reported_digest = snapshot.get("digest")
    if (
        isinstance(snapshot_id, bool)
        or not isinstance(snapshot_id, int)
        or snapshot_id <= 0
        or not isinstance(created_at, str)
        or not created_at
        or not isinstance(reported_digest, str)
    ):
        _reject("SCOPE_SNAPSHOT_INVALID", "scope snapshot metadata is invalid")
    canonical = {
        key: value
        for key, value in snapshot.items()
        if key not in {"id", "created_at", "digest", "snapshot_sha256"}
    }
    digest = canonical_sha256(canonical)
    if reported_digest.upper() != digest or snapshot.get("snapshot_sha256", "").upper() != digest:
        _reject("SCOPE_SNAPSHOT_DIGEST_INVALID", "scope snapshot digest cannot be reproduced")
    items = canonical.get("items")
    if not isinstance(items, list) or not items:
        _reject("SCOPE_SNAPSHOT_INVALID", "scope snapshot contains no ordered items")
    for ordinal, item in enumerate(items, start=1):
        if not isinstance(item, dict) or item.get("ordinal") != ordinal:
            _reject("SCOPE_ORDER_INVALID", "scope snapshot item order has drifted")
        target = item.get("target_identity")
        target_digest = item.get("target_identity_sha256")
        if not isinstance(target, dict) or target_digest != canonical_sha256(target):
            _reject("SCOPE_ITEM_IDENTITY_INVALID", "scope item identity digest has drifted")
    return _clone(snapshot)


def freeze_template_bundle(template: Any) -> dict[str, Any]:
    if not isinstance(template, dict):
        _reject("TEMPLATE_NOT_FOUND", "template does not exist")
    if template.get("template_type") != BATCH_TEMPLATE_TYPE:
        _reject(
            "TEMPLATE_BUNDLE_REQUIRED",
            "edit batch requires one aggregate edit_batch_bundle template",
        )
    if template.get("is_enabled") is not True:
        _reject("TEMPLATE_DISABLED", "edit batch template is disabled")
    payload = template.get("payload")
    if not isinstance(payload, dict) or set(payload) != {
        "schema_version",
        "version",
        "required_sections",
        "binding",
        "source_templates",
        "sections",
    }:
        _reject("TEMPLATE_BUNDLE_INVALID", "template bundle has an unexpected shape")
    if payload["schema_version"] != TEMPLATE_BUNDLE_SCHEMA:
        _reject("TEMPLATE_BUNDLE_INVALID", "template bundle schema is not supported")
    if (
        not isinstance(payload["version"], str)
        or len(payload["version"]) > 32
        or re.fullmatch(
            r"[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?",
            payload["version"],
        ) is None
    ):
        _reject("TEMPLATE_BUNDLE_INVALID", "template bundle version is required")
    if payload["required_sections"] != list(BATCH_TEMPLATE_REQUIRED_SECTIONS):
        _reject("TEMPLATE_BUNDLE_INCOMPLETE", "template bundle required section set is incomplete")
    sections = payload["sections"]
    if not isinstance(sections, dict) or set(sections) != set(BATCH_TEMPLATE_REQUIRED_SECTIONS):
        _reject("TEMPLATE_BUNDLE_INCOMPLETE", "template bundle does not contain every required section")
    for section in BATCH_TEMPLATE_REQUIRED_SECTIONS:
        value = sections.get(section)
        if not isinstance(value, dict) or not value:
            _reject("TEMPLATE_BUNDLE_INCOMPLETE", f"template bundle section {section} is empty")
    binding = payload["binding"]
    if not isinstance(binding, dict) or set(binding) != {
        "store_id",
        "store_name",
        "category_name",
        "platform",
    }:
        _reject("TEMPLATE_BUNDLE_INVALID", "template bundle binding has an unexpected shape")
    if (
        isinstance(binding["store_id"], bool)
        or not isinstance(binding["store_id"], int)
        or binding["store_id"] <= 0
        or not isinstance(binding["store_name"], str)
        or not binding["store_name"].strip()
        or not isinstance(binding["platform"], str)
        or not binding["platform"].strip()
        or (
            binding["category_name"] is not None
            and not isinstance(binding["category_name"], str)
        )
    ):
        _reject("TEMPLATE_BUNDLE_INVALID", "template bundle binding is invalid")
    if binding["category_name"] is not None:
        _reject(
            "BATCH_CATEGORY_SCOPE_UNVERIFIABLE",
            "category-bound edit batches are disabled until DXM exposes exact per-row category evidence",
        )

    source_templates = payload["source_templates"]
    if not isinstance(source_templates, dict) or set(source_templates) != set(BATCH_TEMPLATE_REQUIRED_SECTIONS):
        _reject("TEMPLATE_BUNDLE_INVALID", "template bundle source set is incomplete")
    for section in BATCH_TEMPLATE_REQUIRED_SECTIONS:
        source = source_templates[section]
        if not isinstance(source, dict) or set(source) != SOURCE_TEMPLATE_RECORD_KEYS:
            _reject("TEMPLATE_BUNDLE_INVALID", f"source template record {section} is invalid")
        snapshot = source["snapshot"]
        if not isinstance(snapshot, dict) or set(snapshot) != SOURCE_TEMPLATE_SNAPSHOT_KEYS:
            _reject("TEMPLATE_BUNDLE_INVALID", f"source template snapshot {section} is invalid")
        if (
            snapshot["id"] != source["template_id"]
            or snapshot["template_type"] != section
            or source["template_type"] != section
            or snapshot["template_name"] != source["template_name"]
            or snapshot["binding_scope"] != source["binding_scope"]
            or snapshot["is_enabled"] is not True
            or source["source_digest"] != canonical_sha256(snapshot)
        ):
            _reject("TEMPLATE_BUNDLE_SOURCE_DRIFT", f"source template {section} digest cannot be reproduced")
        normalized_section = normalize_bundle_source_section(section, snapshot["payload"])
        if normalized_section != sections[section]:
            _reject("TEMPLATE_BUNDLE_SOURCE_DRIFT", f"source template {section} no longer matches its section")
    assert_no_publish_directives(payload)
    validation = ConfigValidationService().validate_task(
        {
            "mode": "single_save",
            "store_id": binding["store_id"],
            "store_name": binding["store_name"],
            "payload": {
                "store_id": binding["store_id"],
                "store_name": binding["store_name"],
                "category_name": binding["category_name"],
                "publish": False,
            },
        },
        [source_templates[section]["snapshot"] for section in BATCH_TEMPLATE_REQUIRED_SECTIONS],
        product={"category_name": binding["category_name"], "payload": {}},
    )
    if validation["ok"] is not True:
        _reject(
            "TEMPLATE_BUNDLE_INCOMPLETE",
            "template bundle does not satisfy complete single_save configuration: "
            + ", ".join(validation.get("missing") or []),
        )
    return _clone(template)


def source_template_snapshot(template: Mapping[str, Any]) -> dict[str, Any]:
    snapshot = {key: template.get(key) for key in SOURCE_TEMPLATE_SNAPSHOT_KEYS}
    if not isinstance(snapshot["payload"], Mapping):
        _reject("TEMPLATE_SOURCE_INVALID", "source template payload must be an object")
    snapshot["payload"] = _clone(snapshot["payload"])
    snapshot["is_enabled"] = snapshot["is_enabled"] is True
    return snapshot


def normalize_bundle_source_section(section: str, payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        _reject("TEMPLATE_SOURCE_INVALID", f"source template {section} payload must be an object")
    if section != "dxm_reference":
        value = payload.get(section)
        if not isinstance(value, Mapping) or not value:
            _reject(
                "TEMPLATE_SOURCE_INCOMPLETE",
                f"source template {section} must contain a non-empty payload[{section}] object",
            )
        return _clone(value)

    direct = payload.get("dxm_reference_templates")
    grouped = payload.get("dxm_reference")
    if isinstance(grouped, Mapping):
        grouped = grouped.get("dxm_reference_templates", grouped)
    raw_mapping = direct if isinstance(direct, Mapping) else grouped
    if not isinstance(raw_mapping, Mapping) or not raw_mapping:
        _reject(
            "TEMPLATE_SOURCE_INCOMPLETE",
            "dxm_reference source must contain dxm_reference_templates or grouped dxm_reference",
        )
    normalized = resolve_dxm_reference_templates({"dxm_reference_templates": raw_mapping})
    unsupported = [
        section
        for section in UNSUPPORTED_REFERENCE_TEMPLATE_SECTIONS
        if normalized[section].get("required") is True or bool(normalized[section].get("names"))
    ]
    if unsupported:
        _reject(
            "DXM_REFERENCE_SECTION_UNSUPPORTED",
            "name-only DXM reference sections have no executable exact-control path: "
            + ", ".join(unsupported),
        )
    return {"dxm_reference_templates": normalized}


def assert_no_publish_directives(value: Any, *, path: str = "payload") -> None:
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = str(raw_key).strip().lower()
            child_path = f"{path}.{raw_key}"
            if key in PUBLISH_BOOLEAN_KEYS:
                explicitly_safe = (
                    child is None
                    or child is False
                    or (isinstance(child, str) and not child.strip())
                )
                if not explicitly_safe:
                    _reject("TEMPLATE_PUBLISH_FORBIDDEN", f"{child_path} is not explicitly non-publishing")
            if (
                key in PUBLISH_ACTION_KEYS
                and str(child or "").strip().lower() in FORBIDDEN_PUBLISH_ACTIONS
            ):
                _reject("TEMPLATE_PUBLISH_FORBIDDEN", f"{child_path} requests publish")
            assert_no_publish_directives(child, path=child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            assert_no_publish_directives(child, path=f"{path}[{index}]")


def frozen_batch_policy() -> dict[str, Any]:
    return {
        "schema_version": POLICY_SCHEMA,
        "approval_mode": "batch_once",
        "dispatch_mode": "strict_sequential",
        "global_concurrency": 1,
        "publish_allowed": False,
        "unknown_result_policy": "stop_no_retry",
        "identity_drift_policy": "stop_batch",
        "session_loss_policy": "stop_batch",
        "pre_save_no_effect_failure_policy": "isolate_and_continue_with_evidence",
    }


def _clone(value: Any) -> Any:
    try:
        return json.loads(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        )
    except (TypeError, ValueError) as exc:
        raise BatchContractError("BATCH_FACTS_NOT_CANONICAL", "batch facts are not canonical JSON") from exc


def _reject(reason_code: str, detail: str) -> None:
    raise BatchContractError(reason_code, detail)
