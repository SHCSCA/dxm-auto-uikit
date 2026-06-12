from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from src.services.dxm_reference_templates import resolve_dxm_reference_templates


DEFAULT_TEMPLATE_TYPES = {
    "task_basic",
    "category",
    "sku",
    "pricing",
    "logistics",
    "image",
    "compliance",
    "semi_managed",
    "dxm_reference",
}


@dataclass(frozen=True)
class ConfigDefaultsResult:
    defaults: dict[str, Any]
    sources: dict[str, Any]
    template_trace: list[dict[str, Any]]


class ConfigDefaultsResolver:
    def resolve(
        self,
        templates: list[Mapping[str, Any]],
        task: Mapping[str, Any],
        product: Mapping[str, Any] | None,
    ) -> ConfigDefaultsResult:
        defaults: dict[str, Any] = {}
        sources: dict[str, Any] = {}
        template_trace: list[dict[str, Any]] = []
        for template in reversed(templates):
            if not template.get("is_enabled", True):
                continue
            if not self.template_applies_to(template, task, product):
                continue
            template_type = self.normalize_template_type(template.get("template_type"))
            if template_type not in DEFAULT_TEMPLATE_TYPES:
                continue
            payload = template.get("payload") or {}
            if isinstance(payload, Mapping):
                label = f"模板：{template.get('template_name') or template_type}"
                self.merge_template_payload(defaults, sources, template_type, payload, label)
                template_trace.append({
                    "template_id": template.get("id"),
                    "template_type": template_type,
                    "template_name": template.get("template_name"),
                    "binding_scope": template.get("binding_scope"),
                })

        product_payload = (product or {}).get("payload") or {}
        if isinstance(product_payload, Mapping):
            product_label = f"商品：{(product or {}).get('title') or (product or {}).get('id')}"
            self.merge_payload(defaults, sources, product_payload, product_label)

        task_payload = task.get("payload") or {}
        if isinstance(task_payload, Mapping):
            task_label = f"任务：{task.get('name') or task.get('id')}"
            self.merge_payload(defaults, sources, task_payload, task_label, skip_keys={"template_overrides"})
            overrides = task_payload.get("template_overrides")
            if isinstance(overrides, Mapping):
                for template_type, payload in overrides.items():
                    normalized = self.normalize_template_type(template_type)
                    if normalized in DEFAULT_TEMPLATE_TYPES and isinstance(payload, Mapping):
                        self.deep_merge(self.ensure_section(defaults, normalized), payload)
                        self.deep_source_merge(self.ensure_section(sources, normalized), payload, "任务覆盖")

        defaults["dxm_reference_templates_resolved"] = resolve_dxm_reference_templates(defaults)
        defaults["_template_trace"] = template_trace
        return ConfigDefaultsResult(defaults=defaults, sources=sources, template_trace=template_trace)

    def template_applies_to(
        self,
        template: Mapping[str, Any],
        task: Mapping[str, Any],
        product: Mapping[str, Any] | None,
    ) -> bool:
        payload = template.get("payload") or {}
        if not isinstance(payload, Mapping):
            return True
        binding = payload.get("binding") or payload.get("applies_to") or payload.get("match")
        if not isinstance(binding, Mapping):
            return True

        task_payload = task.get("payload") or {}
        product_payload = (product or {}).get("payload") or {}
        actual_store = task_payload.get("store_name") or "Dang Kang"
        actual_category = (
            (product or {}).get("category_name")
            or product_payload.get("category_name")
            or task_payload.get("category_name")
            or task_payload.get("category")
        )
        actual_platform = task_payload.get("platform") or task.get("platform") or "AliExpress"
        return (
            self.matches_binding(binding, ("store_name", "store", "stores", "store_names"), actual_store)
            and self.matches_binding(binding, ("category_name", "category", "categories", "category_names"), actual_category)
            and self.matches_binding(binding, ("platform", "platforms"), actual_platform)
        )

    def matches_binding(self, binding: Mapping[str, Any], keys: tuple[str, ...], actual: Any) -> bool:
        expected = next((binding.get(key) for key in keys if key in binding), None)
        if expected is None or expected == "":
            return True
        actual_text = str(actual or "").strip().lower()
        values = expected if isinstance(expected, (list, tuple, set)) else [expected]
        normalized = [str(value or "").strip().lower() for value in values]
        return "*" in normalized or "all" in normalized or actual_text in normalized

    def merge_template_payload(
        self,
        target: dict[str, Any],
        sources: dict[str, Any],
        template_type: str,
        payload: Mapping[str, Any],
        source_label: str,
    ) -> None:
        self.merge_payload(target, sources, payload, source_label)
        grouped_payload = payload.get(template_type)
        if isinstance(grouped_payload, Mapping):
            self.deep_merge(self.ensure_section(target, template_type), grouped_payload)
            self.deep_source_merge(self.ensure_section(sources, template_type), grouped_payload, source_label)
            return
        flat_group_payload = {
            key: value
            for key, value in payload.items()
            if key not in DEFAULT_TEMPLATE_TYPES and key != "template_overrides"
        }
        if flat_group_payload:
            self.deep_merge(self.ensure_section(target, template_type), flat_group_payload)
            self.deep_source_merge(self.ensure_section(sources, template_type), flat_group_payload, source_label)

    def merge_payload(
        self,
        target: dict[str, Any],
        sources: dict[str, Any],
        payload: Mapping[str, Any],
        source_label: str,
        skip_keys: set[str] | None = None,
    ) -> None:
        skip_keys = skip_keys or set()
        for key, value in payload.items():
            if key in skip_keys:
                continue
            normalized = self.normalize_template_type(key)
            target_key = normalized if normalized in DEFAULT_TEMPLATE_TYPES else key
            if isinstance(value, Mapping) and isinstance(target.get(target_key), dict):
                self.deep_merge(target[target_key], value)
                self.deep_source_merge(sources.setdefault(target_key, {}), value, source_label)
            elif isinstance(value, Mapping):
                target[target_key] = dict(value)
                sources[target_key] = self.source_tree(value, source_label)
            else:
                target[target_key] = value
                sources[target_key] = source_label

    def deep_merge(self, target: dict[str, Any], source: Mapping[str, Any]) -> None:
        for key, value in source.items():
            if isinstance(value, Mapping) and isinstance(target.get(key), dict):
                self.deep_merge(target[key], value)
            elif isinstance(value, Mapping):
                target[key] = dict(value)
            else:
                target[key] = value

    def ensure_section(self, target: dict[str, Any], key: str) -> dict[str, Any]:
        value = target.get(key)
        if not isinstance(value, dict):
            value = {}
            target[key] = value
        return value

    def deep_source_merge(self, target: dict[str, Any], source: Mapping[str, Any], source_label: str) -> None:
        for key, value in source.items():
            if isinstance(value, Mapping) and isinstance(target.get(key), dict):
                self.deep_source_merge(target[key], value, source_label)
            elif isinstance(value, Mapping):
                target[key] = self.source_tree(value, source_label)
            else:
                target[key] = source_label

    def source_tree(self, payload: Mapping[str, Any], source_label: str) -> dict[str, Any]:
        return {
            key: self.source_tree(value, source_label) if isinstance(value, Mapping) else source_label
            for key, value in payload.items()
        }

    def normalize_template_type(self, value: Any) -> str:
        return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
