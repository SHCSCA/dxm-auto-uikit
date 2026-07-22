from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any


REFERENCE_TEMPLATE_SECTIONS = (
    "attribute_info",
    "description",
    "freight",
    "service",
    "eu_responsible",
    "manufacturer",
    "compliance",
    "semi_managed",
)

# Only these sections currently have a real DXM control-selection path plus
# exact post-selection readback. Name-only sections stay disabled until the
# corresponding editor controls are implemented end to end.
EXECUTABLE_REFERENCE_TEMPLATE_SECTIONS = (
    "attribute_info",
    "freight",
    "service",
    "eu_responsible",
    "manufacturer",
)
UNSUPPORTED_REFERENCE_TEMPLATE_SECTIONS = tuple(
    section
    for section in REFERENCE_TEMPLATE_SECTIONS
    if section not in EXECUTABLE_REFERENCE_TEMPLATE_SECTIONS
)

LEGACY_REFERENCE_TEMPLATE_PATHS = {
    "attribute_info": (
        "attribute_template_priorities",
        "category.attribute_template_priorities",
    ),
    "freight": (
        "freight_template_priorities",
        "logistics.freight_template_priorities",
        "freight_templates",
        "logistics.freight_templates",
    ),
    "service": (
        "service_template_priorities",
        "logistics.service_template_priorities",
        "service_templates",
        "logistics.service_templates",
    ),
    "eu_responsible": (
        "eu_responsible_priorities",
        "compliance.eu_responsible_priorities",
        "eu_responsible_names",
        "compliance.eu_responsible_names",
    ),
    "manufacturer": (
        "manufacturer_priorities",
        "compliance.manufacturer_priorities",
        "manufacturer_names",
        "compliance.manufacturer_names",
    ),
}


def resolve_dxm_reference_templates(*payloads: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    resolved: dict[str, dict[str, Any]] = {
        section: {
            "names": [],
            "required": section in EXECUTABLE_REFERENCE_TEMPLATE_SECTIONS,
        }
        for section in REFERENCE_TEMPLATE_SECTIONS
    }
    explicit_sections: set[str] = set()
    for payload in payloads:
        if not isinstance(payload, Mapping):
            continue
        for candidate in reference_payload_candidates(payload):
            new_mapping = candidate.get("dxm_reference_templates")
            if not isinstance(new_mapping, Mapping):
                continue
            for raw_section, raw_config in new_mapping.items():
                section = normalize_reference_template_section_name(raw_section)
                if section not in REFERENCE_TEMPLATE_SECTIONS:
                    continue
                resolved[section] = normalize_reference_template_config(raw_config)
                explicit_sections.add(section)
        for candidate in reference_payload_candidates(payload):
            for section, paths in LEGACY_REFERENCE_TEMPLATE_PATHS.items():
                if section in explicit_sections:
                    continue
                names = first_non_empty_names(candidate, paths)
                if names:
                    resolved[section] = {"names": names, "required": True}
    return {section: resolved[section] for section in REFERENCE_TEMPLATE_SECTIONS}


def reference_payload_candidates(payload: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    yield payload
    for value in payload.values():
        if isinstance(value, Mapping):
            yield value


def normalize_reference_template_config(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        names = names_from_value(
            value.get("names")
            or value.get("templates")
            or value.get("template_names")
            or value.get("priorities")
            or value.get("name")
        )
        required = bool_from_value(value.get("required", True))
        return {"names": names, "required": required}
    return {"names": names_from_value(value), "required": True}


def bool_from_value(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in {"false", "0", "no", "否"}
    return bool(value)


def normalize_reference_template_section_name(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "attribute": "attribute_info",
        "attribute_template": "attribute_info",
        "attributes": "attribute_info",
        "shipping": "freight",
        "freight_template": "freight",
        "service_template": "service",
        "eu": "eu_responsible",
        "eu_responsible_person": "eu_responsible",
        "manufacturer_template": "manufacturer",
        "compliance_template": "compliance",
        "semi": "semi_managed",
        "semi_managed_template": "semi_managed",
    }
    return aliases.get(text, text)


def first_non_empty_names(payload: Mapping[str, Any], paths: Sequence[str]) -> list[str]:
    for path in paths:
        names = names_from_value(path_value(payload, path))
        if names:
            return names
    return []


def path_value(payload: Mapping[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, Mapping):
            return None
        current = current.get(part)
    return current


def names_from_value(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        values = list(value)
    else:
        values = [value]
    names: list[str] = []
    for item in values:
        text = str(item or "").strip()
        if text and text not in names:
            names.append(text)
    return names
