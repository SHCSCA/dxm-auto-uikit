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

TASK_CONTEXT_KEYS = {
    "store_id",
    "store_name",
    "store",
    "platform",
    "category",
    "category_name",
    "mode",
    "claim_mark",
    "product_ids",
    "source_url",
    "source_urls",
    "publish_scene",
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
        task_payload = task.get("payload") or {}
        if not isinstance(task_payload, Mapping):
            task_payload = {}
        product_payload = (product or {}).get("payload") or {}
        if not isinstance(product_payload, Mapping):
            product_payload = {}
        selected_template_id = self.selected_template_id(task_payload, product_payload)
        applicable_templates: list[tuple[int, int, str, Mapping[str, Any]]] = []
        selected_templates: list[tuple[int, str, Mapping[str, Any]]] = []
        for index, template in enumerate(templates):
            if not template.get("is_enabled", True):
                continue
            template_type = self.normalize_template_type(template.get("template_type"))
            if template_type not in DEFAULT_TEMPLATE_TYPES:
                continue
            if selected_template_id and self.template_id_matches(template, selected_template_id):
                selected_templates.append((self.template_sort_id(template, index), template_type, template))
                continue
            if not self.template_applies_to(template, task, product):
                continue
            applicable_templates.append((
                self.template_binding_specificity(template, task, product),
                self.template_sort_id(template, index),
                template_type,
                template,
            ))
        for _specificity, _sort_id, template_type, template in sorted(applicable_templates, key=lambda item: (item[0], item[1])):
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

        if product_payload:
            product_label = f"商品：{(product or {}).get('title') or (product or {}).get('id')}"
            self.merge_payload_missing(defaults, sources, product_payload, product_label)

        for _sort_id, template_type, template in sorted(selected_templates, key=lambda item: item[0]):
            payload = template.get("payload") or {}
            if isinstance(payload, Mapping):
                label = f"模板：{template.get('template_name') or template_type}"
                self.merge_template_payload(defaults, sources, template_type, payload, label)
                template_trace.append({
                    "template_id": template.get("id"),
                    "template_type": template_type,
                    "template_name": template.get("template_name"),
                    "binding_scope": template.get("binding_scope"),
                    "selected": True,
                })

        if task_payload:
            task_label = f"任务：{task.get('name') or task.get('id')}"
            self.merge_payload_missing(
                defaults,
                sources,
                task_payload,
                task_label,
                skip_keys={"template_overrides"},
                replace_source_prefixes=("商品：",),
                force_replace_keys=TASK_CONTEXT_KEYS,
            )
            overrides = task_payload.get("template_overrides")
            if isinstance(overrides, Mapping):
                for template_type, payload in overrides.items():
                    normalized = self.normalize_template_type(template_type)
                    if normalized in DEFAULT_TEMPLATE_TYPES and isinstance(payload, Mapping):
                        self.deep_fill_missing_with_sources(
                            self.ensure_section(defaults, normalized),
                            self.ensure_section(sources, normalized),
                            payload,
                            "高级：本次任务临时覆盖",
                            replace_source_prefixes=("商品：",),
                        )

        defaults["dxm_reference_templates_resolved"] = resolve_dxm_reference_templates(defaults)
        defaults["_template_trace"] = template_trace
        return ConfigDefaultsResult(defaults=defaults, sources=sources, template_trace=template_trace)

    def selected_template_id(
        self,
        task_payload: Mapping[str, Any],
        product_payload: Mapping[str, Any],
    ) -> str | None:
        value = task_payload.get("template_id")
        if value is None or value == "":
            value = product_payload.get("template_id")
        text = str(value or "").strip()
        return text or None

    def template_id_matches(self, template: Mapping[str, Any], selected_template_id: str) -> bool:
        return str(template.get("id") or "").strip() == selected_template_id

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

        context = self.template_binding_context(task, product)
        return (
            self.matches_binding(binding, ("store_name", "store", "stores", "store_names"), context["store_name"])
            and self.matches_binding(binding, ("category_name", "category", "categories", "category_names"), context["category_name"])
            and self.matches_binding(binding, ("platform", "platforms"), context["platform"])
        )

    def template_binding_context(
        self,
        task: Mapping[str, Any],
        product: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        task_payload = task.get("payload") or {}
        product_payload = (product or {}).get("payload") or {}
        return {
            "store_name": task_payload.get("store_name") or "Dang Kang",
            "category_name": (
                (product or {}).get("category_name")
                or product_payload.get("category_name")
                or task_payload.get("category_name")
                or task_payload.get("category")
            ),
            "platform": task_payload.get("platform") or task.get("platform") or "AliExpress",
        }

    def template_binding_specificity(
        self,
        template: Mapping[str, Any],
        task: Mapping[str, Any],
        product: Mapping[str, Any] | None,
    ) -> int:
        payload = template.get("payload") or {}
        if not isinstance(payload, Mapping):
            return 0
        binding = payload.get("binding") or payload.get("applies_to") or payload.get("match")
        if not isinstance(binding, Mapping):
            return 0
        context = self.template_binding_context(task, product)
        return (
            self.binding_specificity_value(binding, ("store_name", "store", "stores", "store_names"), context["store_name"])
            + self.binding_specificity_value(binding, ("category_name", "category", "categories", "category_names"), context["category_name"])
            + self.binding_specificity_value(binding, ("platform", "platforms"), context["platform"])
        )

    def binding_specificity_value(self, binding: Mapping[str, Any], keys: tuple[str, ...], actual: Any) -> int:
        expected = next((binding.get(key) for key in keys if key in binding), None)
        if expected is None or expected == "":
            return 0
        actual_text = str(actual or "").strip().lower()
        values = expected if isinstance(expected, (list, tuple, set)) else [expected]
        normalized = [str(value or "").strip().lower() for value in values]
        if "*" in normalized or "all" in normalized:
            return 0
        return 1 if actual_text in normalized else 0

    def template_sort_id(self, template: Mapping[str, Any], index: int) -> int:
        try:
            return int(template.get("id"))
        except (TypeError, ValueError):
            return index

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

    def merge_payload_missing(
        self,
        target: dict[str, Any],
        sources: dict[str, Any],
        payload: Mapping[str, Any],
        source_label: str,
        skip_keys: set[str] | None = None,
        replace_source_prefixes: tuple[str, ...] = (),
        force_replace_keys: set[str] | None = None,
    ) -> None:
        skip_keys = skip_keys or set()
        force_replace_keys = force_replace_keys or set()
        for key, value in payload.items():
            if key in skip_keys:
                continue
            normalized = self.normalize_template_type(key)
            target_key = normalized if normalized in DEFAULT_TEMPLATE_TYPES else key
            existing_source = sources.get(target_key)
            force_replace = key in force_replace_keys or target_key in force_replace_keys
            if isinstance(value, Mapping):
                if isinstance(target.get(target_key), dict):
                    self.deep_fill_missing_with_sources(
                        target[target_key],
                        sources.setdefault(target_key, {}),
                        value,
                        source_label,
                        replace_source_prefixes=replace_source_prefixes,
                    )
                elif force_replace or self.value_missing(target.get(target_key)) or self.source_can_be_replaced(existing_source, replace_source_prefixes):
                    target[target_key] = dict(value)
                    sources[target_key] = self.source_tree(value, source_label)
            elif force_replace or self.value_missing(target.get(target_key)) or self.source_can_be_replaced(existing_source, replace_source_prefixes):
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

    def deep_fill_missing_with_sources(
        self,
        target: dict[str, Any],
        source_target: dict[str, Any],
        source: Mapping[str, Any],
        source_label: str,
        replace_source_prefixes: tuple[str, ...] = (),
    ) -> None:
        for key, value in source.items():
            if isinstance(value, Mapping):
                current = target.get(key)
                if isinstance(current, dict):
                    nested_source = source_target.setdefault(key, {})
                    if not isinstance(nested_source, dict):
                        nested_source = {}
                        source_target[key] = nested_source
                    self.deep_fill_missing_with_sources(
                        current,
                        nested_source,
                        value,
                        source_label,
                        replace_source_prefixes=replace_source_prefixes,
                    )
                elif self.value_missing(current) or self.source_can_be_replaced(source_target.get(key), replace_source_prefixes):
                    target[key] = dict(value)
                    source_target[key] = self.source_tree(value, source_label)
            elif self.value_missing(target.get(key)) or self.source_can_be_replaced(source_target.get(key), replace_source_prefixes):
                target[key] = value
                source_target[key] = source_label

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

    def value_missing(self, value: Any) -> bool:
        if isinstance(value, Mapping):
            return not value
        return value is None or str(value).strip() == ""

    def source_can_be_replaced(self, source: Any, prefixes: tuple[str, ...]) -> bool:
        text = str(source or "").strip()
        return bool(text and any(text.startswith(prefix) for prefix in prefixes))

    def normalize_template_type(self, value: Any) -> str:
        return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
