from __future__ import annotations

from collections.abc import Iterable, Mapping
from enum import StrEnum
from typing import Any

from src.services.dxm_reference_templates import resolve_dxm_reference_templates


class ExecutionMode(StrEnum):
    PROBE = "probe"
    DRY_RUN = "dry_run"
    CLAIM_ONLY = "claim_only"
    SINGLE_SAVE = "single_save"
    BATCH_SAVE = "batch_save"


class ConfigValidationService:
    CONFIG_ERROR_CODE = "E302"
    PUBLISH_ERROR_CODE = "E999"

    ALLOWED_MODES = frozenset(mode.value for mode in ExecutionMode)
    FORBIDDEN_MODES = frozenset({"publish", "continue_publish", "save_and_publish"})
    SAVE_REQUIRED_TEMPLATES = ("category", "sku", "pricing", "logistics", "image", "semi_managed")

    _TEMPLATE_ALIASES = {
        "类目": "category",
        "类目模板": "category",
        "category_template": "category",
        "sku模板": "sku",
        "sku_template": "sku",
        "价格": "pricing",
        "价格模板": "pricing",
        "计价": "pricing",
        "计价模板": "pricing",
        "pricing_template": "pricing",
        "物流": "logistics",
        "物流模板": "logistics",
        "包装物流": "logistics",
        "包装物流模板": "logistics",
        "shipping": "logistics",
        "shipping_template": "logistics",
        "logistics_template": "logistics",
        "图片": "image",
        "图片模板": "image",
        "主图": "image",
        "主图模板": "image",
        "image_template": "image",
        "合规": "compliance",
        "合规模板": "compliance",
        "compliance_template": "compliance",
        "半托管": "semi_managed",
        "半托管模板": "semi_managed",
        "semi-managed": "semi_managed",
        "semi_managed_template": "semi_managed",
    }

    _PUBLISH_KEYS = ("publish", "published", "should_publish", "auto_publish")
    _PUBLISH_ACTION_KEYS = ("action", "intended_action", "target_action")

    def validate_task(
        self,
        task: Mapping[str, Any] | None,
        templates: Any,
        product: Mapping[str, Any] | None = None,
    ) -> dict:
        task_data = dict(task or {})
        payload = self._payload(task_data)
        effective_payload = self._payload_with_template_overrides(payload)
        product_payload = self._payload(product or {})
        mode = self._normalize_mode(task_data.get("mode") or effective_payload.get("mode"))
        warnings: list[str] = []

        if not mode:
            return self._result(False, self.CONFIG_ERROR_CODE, ["mode"], warnings, mode)
        if mode in self.FORBIDDEN_MODES:
            warnings.append(f"forbidden execution mode: {mode}")
            return self._result(False, self.PUBLISH_ERROR_CODE, [], warnings, mode)
        if mode not in self.ALLOWED_MODES:
            warnings.append(f"unsupported execution mode: {mode}")
            return self._result(False, self.CONFIG_ERROR_CODE, ["mode"], warnings, mode)

        publish_warnings = self._publish_warnings(task_data, effective_payload)
        if publish_warnings:
            return self._result(False, self.PUBLISH_ERROR_CODE, [], publish_warnings, mode)

        applicable_templates = self._applicable_templates(templates, task_data, product)
        missing = self._missing_for_mode(mode, task_data, effective_payload, applicable_templates, product_payload)
        return self._result(not missing, self.CONFIG_ERROR_CODE if missing else None, missing, warnings, mode)

    def _payload(self, task: Mapping[str, Any]) -> dict:
        payload = task.get("payload")
        return dict(payload) if isinstance(payload, Mapping) else {}

    def _payload_with_template_overrides(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        effective = dict(payload)
        overrides = payload.get("template_overrides")
        if not isinstance(overrides, Mapping):
            return effective
        for section, section_values in overrides.items():
            if not isinstance(section_values, Mapping):
                continue
            normalized = self._normalize_template_key(section)
            if not normalized:
                continue
            existing = effective.get(normalized)
            merged = dict(existing) if isinstance(existing, Mapping) else {}
            self._deep_merge(merged, section_values)
            effective[normalized] = merged
        return effective

    def _deep_merge(self, target: dict[str, Any], source: Mapping[str, Any]) -> None:
        for key, value in source.items():
            current = target.get(key)
            if isinstance(current, dict) and isinstance(value, Mapping):
                self._deep_merge(current, value)
            else:
                target[key] = value

    def _missing_for_mode(
        self,
        mode: str,
        task: Mapping[str, Any],
        payload: Mapping[str, Any],
        templates: Any,
        product_payload: Mapping[str, Any],
    ) -> list[str]:
        if mode == ExecutionMode.PROBE.value:
            return []
        if mode == ExecutionMode.CLAIM_ONLY.value:
            missing: list[str] = []
            if not self._has_store(task, payload):
                missing.append("store")
            if not self._has_value(task, payload, "claim_mark"):
                missing.append("claim_mark")
            return missing
        if mode in (ExecutionMode.SINGLE_SAVE.value, ExecutionMode.BATCH_SAVE.value):
            present_templates = self._present_template_types(templates)
            missing = [name for name in self.SAVE_REQUIRED_TEMPLATES if name not in present_templates]
            if "compliance" not in present_templates and not self._has_payload_domain(payload, product_payload, "compliance"):
                missing.append("compliance")
            if not self._has_eu_outer_package_image(payload, product_payload, templates):
                missing.append("image.eu_outer_package_filename")
            missing.extend(self._missing_save_only_template_fields(payload, product_payload, templates, present_templates))
            missing.extend(self._missing_required_reference_templates(payload, product_payload, templates))
            return missing
        return []

    def _missing_required_reference_templates(
        self,
        task_payload: Mapping[str, Any],
        product_payload: Mapping[str, Any],
        templates: Any,
    ) -> list[str]:
        resolved = resolve_dxm_reference_templates(
            *self._all_template_payloads(templates),
            task_payload,
            product_payload,
        )
        missing: list[str] = []
        for section, config in resolved.items():
            if config.get("required", True) and not config.get("names"):
                missing.append(f"dxm_reference_templates.{section}")
        return missing

    def _missing_save_only_template_fields(
        self,
        task_payload: Mapping[str, Any],
        product_payload: Mapping[str, Any],
        templates: Any,
        present_templates: set[str],
    ) -> list[str]:
        missing: list[str] = []
        check_domain = present_templates.__contains__
        if not self._has_any_domain_value(
            "category",
            task_payload,
            product_payload,
            templates,
            (
                "category.category_match",
                "category.category_name",
                "category.category_keyword",
                "category.template_category_id",
                "category_name",
            ),
        ) and check_domain("category"):
            missing.append("category")
        if not self._has_any_domain_value(
            "image",
            task_payload,
            product_payload,
            templates,
            ("image.marketing_images_strategy", "image.marketing_strategy", "marketing_images_strategy", "marketing_strategy"),
        ) and check_domain("image"):
            missing.append("image.marketing_images_strategy")
        if not self._has_any_domain_value(
            "logistics",
            task_payload,
            product_payload,
            templates,
            ("logistics.weight", "weight"),
        ) and check_domain("logistics"):
            missing.append("logistics.weight")
        if not self._has_all_domain_values(
            "logistics",
            task_payload,
            product_payload,
            templates,
            ("length", "width", "height"),
        ) and check_domain("logistics"):
            missing.append("logistics.dimensions")
        if not self._has_any_domain_value(
            "semi_managed",
            task_payload,
            product_payload,
            templates,
            ("semi_managed.product_price", "semi_managed.supply_price", "product_price", "supply_price"),
        ) and check_domain("semi_managed"):
            missing.append("semi_managed.product_price_or_supply_price")
        if not self._has_any_domain_value(
            "semi_managed",
            task_payload,
            product_payload,
            templates,
            ("semi_managed.jit_stock", "semi_managed.stock", "jit_stock"),
        ) and check_domain("semi_managed"):
            missing.append("semi_managed.jit_stock")
        if not self._has_any_domain_value(
            "semi_managed",
            task_payload,
            product_payload,
            templates,
            ("semi_managed.is_original_box", "semi_managed.original_box", "is_original_box"),
        ) and check_domain("semi_managed"):
            missing.append("semi_managed.is_original_box")
        if not self._has_all_domain_values(
            "semi_managed",
            task_payload,
            product_payload,
            templates,
            ("length", "width", "height"),
        ) and check_domain("semi_managed"):
            missing.append("semi_managed.dimensions")
        if not self._has_any_domain_value(
            "semi_managed",
            task_payload,
            product_payload,
            templates,
            ("semi_managed.goods_code_strategy", "goods_code_strategy"),
        ) and check_domain("semi_managed"):
            missing.append("semi_managed.goods_code_strategy")
        if not self._has_any_domain_value(
            "semi_managed",
            task_payload,
            product_payload,
            templates,
            ("semi_managed.barcode_strategy", "barcode_strategy"),
        ) and check_domain("semi_managed"):
            missing.append("semi_managed.barcode_strategy")
        return missing

    def _present_template_types(self, templates: Any) -> set[str]:
        present: set[str] = set()
        for template in self._iter_templates(templates):
            if isinstance(template, Mapping) and not self._is_template_enabled(template):
                continue
            template_type = self._template_type(template)
            if template_type:
                present.add(template_type)
        return present

    def _applicable_templates(
        self,
        templates: Any,
        task: Mapping[str, Any],
        product: Mapping[str, Any] | None,
    ) -> list[Any]:
        return [
            template
            for template in self._iter_templates(templates)
            if self._template_applies_to(template, task, product)
        ]

    def _template_applies_to(
        self,
        template: Any,
        task: Mapping[str, Any],
        product: Mapping[str, Any] | None,
    ) -> bool:
        payload = self._template_payload(template)
        binding = payload.get("binding") or payload.get("applies_to") or payload.get("match")
        if not isinstance(binding, Mapping):
            return True

        task_payload = task.get("payload") if isinstance(task.get("payload"), Mapping) else {}
        product_payload = (product or {}).get("payload") if isinstance((product or {}).get("payload"), Mapping) else {}
        actual_store = (
            task_payload.get("store_name")
            or task.get("store_name")
            or task_payload.get("store")
            or task.get("store")
        )
        actual_category = (
            (product or {}).get("category_name")
            or product_payload.get("category_name")
            or task_payload.get("category_name")
            or task_payload.get("category")
        )
        actual_platform = (
            task_payload.get("platform")
            or task.get("platform")
            or "AliExpress"
        )
        return (
            self._matches_binding(binding, ("store_name", "store", "stores", "store_names"), actual_store)
            and self._matches_binding(binding, ("category_name", "category", "categories", "category_names"), actual_category)
            and self._matches_binding(binding, ("platform", "platforms"), actual_platform)
        )

    def _template_payload(self, template: Any) -> Mapping[str, Any]:
        if isinstance(template, Mapping):
            payload = template.get("payload")
            return payload if isinstance(payload, Mapping) else template
        if isinstance(template, tuple) and len(template) == 2 and isinstance(template[1], Mapping):
            payload = template[1].get("payload")
            return payload if isinstance(payload, Mapping) else template[1]
        return {}

    def _matches_binding(self, binding: Mapping[str, Any], keys: tuple[str, ...], actual: Any) -> bool:
        expected = next((binding.get(key) for key in keys if key in binding), None)
        if expected is None or expected == "":
            return True
        actual_text = str(actual or "").strip().lower()
        values = expected if isinstance(expected, (list, tuple, set)) else [expected]
        normalized = [str(value or "").strip().lower() for value in values]
        return "*" in normalized or "all" in normalized or actual_text in normalized

    def _template_payloads(self, templates: Any, template_type: str) -> list[Mapping[str, Any]]:
        payloads: list[Mapping[str, Any]] = []
        for template in self._iter_templates(templates):
            if not isinstance(template, Mapping):
                continue
            if not self._is_template_enabled(template):
                continue
            if self._template_type(template) != template_type:
                continue
            payload = template.get("payload")
            if isinstance(payload, Mapping):
                payloads.append(payload)
        return payloads

    def _all_template_payloads(self, templates: Any) -> list[Mapping[str, Any]]:
        payloads: list[Mapping[str, Any]] = []
        for template in self._iter_templates(templates):
            if not isinstance(template, Mapping):
                continue
            if not self._is_template_enabled(template):
                continue
            payload = template.get("payload")
            if isinstance(payload, Mapping):
                payloads.append(payload)
        return payloads

    def _iter_templates(self, templates: Any) -> Iterable[Any]:
        if templates is None:
            return ()
        if isinstance(templates, Mapping):
            return templates.items()
        if isinstance(templates, (str, bytes)):
            return (templates,)
        return templates

    def _template_type(self, template: Any) -> str:
        if isinstance(template, tuple) and len(template) == 2:
            key, value = template
            if isinstance(value, Mapping) and not self._is_template_enabled(value):
                return ""
            return self._normalize_template_key(key)
        if isinstance(template, Mapping):
            return self._normalize_template_key(
                template.get("template_type")
                or template.get("type")
                or template.get("code")
                or template.get("name")
                or template.get("template_name")
            )
        return self._normalize_template_key(template)

    def _is_template_enabled(self, template: Mapping[str, Any]) -> bool:
        return bool(template.get("is_enabled", template.get("enabled", True)))

    def _normalize_template_key(self, value: Any) -> str:
        normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        if not normalized:
            return ""
        return self._TEMPLATE_ALIASES.get(normalized, normalized)

    def _publish_warnings(self, task: Mapping[str, Any], payload: Mapping[str, Any]) -> list[str]:
        warnings: list[str] = []
        for source_name, source in (("task", task), ("payload", payload)):
            for key in self._PUBLISH_KEYS:
                if source.get(key) is True:
                    warnings.append(f"{source_name}.{key} requests publish")
            for key in self._PUBLISH_ACTION_KEYS:
                action = self._normalize_mode(source.get(key))
                if action in self.FORBIDDEN_MODES:
                    warnings.append(f"{source_name}.{key} requests forbidden publish action: {action}")
        return warnings

    def _has_store(self, task: Mapping[str, Any], payload: Mapping[str, Any]) -> bool:
        return bool(task.get("store_id") or task.get("store") or payload.get("store_id") or payload.get("store"))

    def _has_value(self, task: Mapping[str, Any], payload: Mapping[str, Any], key: str) -> bool:
        value = task.get(key, payload.get(key))
        return value is not None and str(value).strip() != ""

    def _has_payload_domain(
        self,
        task_payload: Mapping[str, Any],
        product_payload: Mapping[str, Any],
        domain: str,
    ) -> bool:
        for payload in (task_payload, product_payload):
            value = payload.get(domain)
            if isinstance(value, Mapping):
                return bool(value)
        return False

    def _has_any_domain_value(
        self,
        domain: str,
        task_payload: Mapping[str, Any],
        product_payload: Mapping[str, Any],
        templates: Any,
        paths: tuple[str, ...],
    ) -> bool:
        for payload in self._domain_payloads(domain, task_payload, product_payload, templates):
            if any(self._non_empty(self._path_value(payload, path)) for path in paths):
                return True
        return False

    def _has_all_domain_values(
        self,
        domain: str,
        task_payload: Mapping[str, Any],
        product_payload: Mapping[str, Any],
        templates: Any,
        keys: tuple[str, ...],
    ) -> bool:
        return all(
            self._has_any_domain_value(
                domain,
                task_payload,
                product_payload,
                templates,
                (f"{domain}.{key}", key),
            )
            for key in keys
        )

    def _domain_payloads(
        self,
        domain: str,
        task_payload: Mapping[str, Any],
        product_payload: Mapping[str, Any],
        templates: Any,
    ) -> tuple[Mapping[str, Any], ...]:
        return (*self._template_payloads(templates, domain), task_payload, product_payload)

    def _path_value(self, payload: Mapping[str, Any], path: str) -> Any:
        current: Any = payload
        for part in path.split("."):
            if not isinstance(current, Mapping):
                return None
            current = current.get(part)
        return current

    def _has_eu_outer_package_image(
        self,
        task_payload: Mapping[str, Any],
        product_payload: Mapping[str, Any],
        templates: Any,
    ) -> bool:
        for payload in (*self._template_payloads(templates, "image"), task_payload, product_payload):
            if self._payload_has_eu_outer_package_image(payload):
                return True
        return False

    def _payload_has_eu_outer_package_image(self, payload: Mapping[str, Any]) -> bool:
        if self._non_empty(payload.get("eu_outer_package_filename")):
            return True
        image_payload = payload.get("image")
        if isinstance(image_payload, Mapping):
            if self._non_empty(image_payload.get("eu_outer_package_filename")):
                return True
            if self._image_filename_present(image_payload.get("eu_outer_package_image")):
                return True
            if self._image_slots_have_eu_outer_package_image(image_payload.get("slots")):
                return True
        return self._image_filename_present(payload.get("eu_outer_package_image"))

    def _image_slots_have_eu_outer_package_image(self, slots: Any) -> bool:
        if not isinstance(slots, list):
            return False
        for slot in slots:
            if not isinstance(slot, Mapping):
                continue
            label = f"{slot.get('label') or slot.get('slot_label') or ''} {slot.get('slot_key') or slot.get('type') or ''}"
            normalized = label.lower().replace("-", "_").replace(" ", "_")
            is_outer_package = (
                "eu_outer_package" in normalized
                or "外包装" in normalized
                or "标签实拍图_欧盟" in normalized
                or "标签实拍图-欧盟" in normalized
            )
            if is_outer_package and self._non_empty(slot.get("filename") or slot.get("file_name") or slot.get("name")):
                return True
        return False

    def _image_filename_present(self, value: Any) -> bool:
        if isinstance(value, Mapping):
            return self._non_empty(value.get("filename"))
        return self._non_empty(value)

    def _non_empty(self, value: Any) -> bool:
        return value is not None and str(value).strip() != ""

    def _normalize_mode(self, mode: Any) -> str:
        return str(mode or "").strip().lower()

    def _result(
        self,
        ok: bool,
        error_code: str | None,
        missing: list[str],
        warnings: list[str],
        mode: str,
    ) -> dict:
        return {
            "ok": ok,
            "error_code": error_code,
            "missing": missing,
            "warnings": warnings,
            "mode": mode,
        }
