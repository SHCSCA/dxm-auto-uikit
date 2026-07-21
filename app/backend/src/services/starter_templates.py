from __future__ import annotations

from collections.abc import Mapping
from typing import Any


STARTER_TEMPLATE_TYPES = (
    "category",
    "sku",
    "pricing",
    "logistics",
    "image",
    "compliance",
    "semi_managed",
    "dxm_reference",
)


def build_starter_templates(
    *,
    store_name: str,
    category_name: str,
    platform: str = "AliExpress",
) -> list[dict[str, Any]]:
    """Do not synthesize production templates from bundled business examples.

    A save-capable template must now be created from explicit operator input or
    composed from already persisted, store-bound source templates.  Keeping the
    legacy helper as a safe no-op avoids silently reintroducing fixed prices,
    stock, product taxonomy, compliance identities, or DXM reference names.
    """

    del store_name, category_name, platform
    return []


def default_attribute_template_names(category_name: str) -> list[str]:
    """Require the operator to select real DXM attribute templates explicitly."""

    del category_name
    return []


def default_title_keyword_map(category_name: str) -> dict[str, str]:
    """Require title mappings to come from the selected versioned template."""

    del category_name
    return {}


def repair_legacy_starter_template(
    template: Mapping[str, Any],
    starter_template: Mapping[str, Any],
    *,
    category_name: str,
) -> dict[str, Any] | None:
    """Never mutate persisted templates from bundled example data."""

    del template, starter_template, category_name
    return None


def starter_template_matches(
    template: Mapping[str, Any],
    *,
    template_type: str,
    store_name: str,
    category_name: str,
    platform: str = "AliExpress",
) -> bool:
    """Retain binding matching for callers auditing already persisted templates."""

    if str(template.get("template_type") or "").strip().lower() != template_type:
        return False
    if not bool(template.get("is_enabled", True)):
        return False
    payload = template.get("payload")
    if not isinstance(payload, Mapping):
        return False
    binding = payload.get("binding") or payload.get("applies_to") or payload.get("match")
    if not isinstance(binding, Mapping):
        return False
    return (
        _binding_value_matches(binding, ("store_name", "store", "stores", "store_names"), store_name)
        and _binding_value_matches(
            binding,
            ("category_name", "category", "categories", "category_names"),
            category_name,
        )
        and _binding_value_matches(binding, ("platform", "platforms"), platform)
    )


def _binding_value_matches(
    binding: Mapping[str, Any],
    keys: tuple[str, ...],
    actual: str,
) -> bool:
    expected = next((binding.get(key) for key in keys if key in binding), None)
    if expected is None or expected == "":
        return True
    values = expected if isinstance(expected, (list, tuple, set)) else [expected]
    normalized = [str(value or "").strip().lower() for value in values]
    actual_text = str(actual or "").strip().lower()
    return "*" in normalized or "all" in normalized or actual_text in normalized
