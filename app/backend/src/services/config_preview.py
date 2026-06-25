from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.services.config_defaults import DEFAULT_TEMPLATE_TYPES, ConfigDefaultsResolver
from src.services.config_validation import ConfigValidationService
from src.services.dxm_reference_templates import LEGACY_REFERENCE_TEMPLATE_PATHS, REFERENCE_TEMPLATE_SECTIONS

FIELD_GROUPS = [
    {
        "section": "task_basic",
        "label": "店铺与任务基础",
        "templateType": "task_basic",
        "fields": [
            {"path": "store_name", "field": "store_name", "label": "店铺", "required": True},
            {"path": "execution_mode", "field": "execution_mode", "label": "任务模式", "required": True},
            {"path": "category_name", "field": "category_name", "label": "绑定类目", "required": False},
            {"path": "claim_mark", "field": "claim_mark", "label": "认领标记", "required": False},
        ],
    },
    {
        "section": "category",
        "label": "类目与标题",
        "templateType": "category",
        "fields": [
            {"path": "category.category_name", "field": "category_name", "label": "目标类目", "required": False},
            {"path": "category.template_category_id", "field": "template_category_id", "label": "目标类目 ID", "required": False},
            {"path": "category.category_keyword", "field": "category_keyword", "label": "类目关键词", "required": True},
            {"path": "category.title_strategy", "field": "title_strategy", "label": "标题策略", "required": False},
            {"path": "category.title_override", "field": "title_override", "label": "标题覆盖值", "required": False},
            {"path": "category.title_cleaning_rule", "field": "title_cleaning_rule", "label": "标题清洗规则", "required": False},
        ],
    },
    {
        "section": "sku",
        "label": "SKU / 价格 / 库存",
        "templateType": "sku",
        "fields": [
            {"path": "sku.sku_code", "field": "sku_code", "label": "SKU 编码", "required": False},
            {"path": "sku.stock", "field": "stock", "label": "库存", "required": False},
            {"path": "sku.jit_stock", "field": "jit_stock", "label": "JIT 库存", "required": False},
            {"path": "sku.normal_stock", "field": "normal_stock", "label": "普通库存", "required": False},
            {"path": "sku.template_sku_rule", "field": "template_sku_rule", "label": "SKU 规则", "required": False},
            {"path": "sku.sku_attribute_strategy", "field": "sku_attribute_strategy", "label": "SKU 属性策略", "required": False},
            {"path": "sku.variant_strategy", "field": "variant_strategy", "label": "变体处理策略", "required": False},
        ],
    },
    {
        "section": "pricing",
        "label": "价格策略",
        "templateType": "pricing",
        "fields": [
            {"path": "pricing.product_price", "field": "product_price", "label": "商品价", "required": False},
            {"path": "pricing.supply_price", "field": "supply_price", "label": "供货价", "required": False},
            {"path": "pricing.price_source", "field": "price_source", "label": "价格来源", "required": False},
            {"path": "pricing.price_multiplier", "field": "price_multiplier", "label": "价格倍率", "required": False},
            {"path": "pricing.fixed_price", "field": "fixed_price", "label": "固定价", "required": False},
            {"path": "pricing.price_strategy", "field": "price_strategy", "label": "价格策略", "required": False},
        ],
    },
    {
        "section": "image",
        "label": "图片与素材",
        "templateType": "image",
        "fields": [
            {"path": "image.eu_outer_package_filename", "field": "eu_outer_package_filename", "label": "EU 外包装图", "required": True},
            {"path": "image.marketing_images_strategy", "field": "marketing_images_strategy", "label": "营销图策略", "required": True},
            {"path": "image.main_image_strategy", "field": "main_image_strategy", "label": "主图策略", "required": False},
            {"path": "image.fallback_strategy", "field": "fallback_strategy", "label": "图片不足时处理方式", "required": False},
            {"path": "image.invalid_image_strategy", "field": "invalid_image_strategy", "label": "无效图片处理", "required": False},
            {"path": "image.local_asset_path", "field": "local_asset_path", "label": "本地素材路径", "required": False},
        ],
    },
    {
        "section": "logistics",
        "label": "包装物流",
        "templateType": "logistics",
        "fields": [
            {"path": "logistics.weight", "field": "weight", "label": "重量 kg", "required": True},
            {"path": "logistics.length", "field": "length", "label": "长 cm", "required": True},
            {"path": "logistics.width", "field": "width", "label": "宽 cm", "required": True},
            {"path": "logistics.height", "field": "height", "label": "高 cm", "required": True},
            {"path": "logistics.logistics_attribute", "field": "logistics_attribute", "label": "物流属性", "required": False},
            {"path": "logistics.freight_template", "field": "freight_template", "label": "运费模板", "required": False},
            {"path": "logistics.service_template", "field": "service_template", "label": "服务模板", "required": False},
            {"path": "logistics.package_gross_weight", "field": "package_gross_weight", "label": "包装毛重", "required": False},
        ],
    },
    {
        "section": "compliance",
        "label": "合规 / 海关",
        "templateType": "compliance",
        "fields": [
            {"path": "compliance.customs_name", "field": "customs_name", "label": "报关品名", "required": False},
            {"path": "compliance.material", "field": "material", "label": "材质", "required": False},
            {"path": "compliance.purpose", "field": "purpose", "label": "用途", "required": False},
            {"path": "compliance.brand", "field": "brand", "label": "品牌", "required": False},
            {"path": "compliance.statement", "field": "statement", "label": "合规声明", "required": False},
        ],
    },
    {
        "section": "semi_managed",
        "label": "半托管",
        "templateType": "semi_managed",
        "fields": [
            {"path": "semi_managed.product_price", "field": "product_price", "label": "商品价", "required": False},
            {"path": "semi_managed.supply_price", "field": "supply_price", "label": "供货价", "required": False},
            {"path": "semi_managed.jit_stock", "field": "jit_stock", "label": "JIT 库存", "required": True},
            {"path": "semi_managed.is_original_box", "field": "is_original_box", "label": "是否原包装", "required": True},
            {"path": "semi_managed.length", "field": "length", "label": "半托管长 cm", "required": True},
            {"path": "semi_managed.width", "field": "width", "label": "半托管宽 cm", "required": True},
            {"path": "semi_managed.height", "field": "height", "label": "半托管高 cm", "required": True},
            {"path": "semi_managed.goods_code_strategy", "field": "goods_code_strategy", "label": "货号策略", "required": True},
            {"path": "semi_managed.barcode_strategy", "field": "barcode_strategy", "label": "条码策略", "required": True},
        ],
    },
    {
        "section": "dxm_reference",
        "label": "店小秘引用模板",
        "templateType": "dxm_reference",
        "fields": [],
    },
]

DXM_REFERENCE_LABELS = {
    "attribute_info": "属性信息模板",
    "description": "描述模板",
    "freight": "运费模板",
    "service": "服务模板",
    "eu_responsible": "欧盟责任人",
    "manufacturer": "制造商",
    "compliance": "合规模板",
    "semi_managed": "半托管模板",
}

CUSTOMER_TEMPLATE_PRIORITY = ["本次任务覆盖", "手动选择模板", "类目默认模板", "店铺默认模板", "系统默认模板"]


class ConfigPreviewService:
    def __init__(self):
        self.validation = ConfigValidationService()
        self.defaults_resolver = ConfigDefaultsResolver()

    def build(self, repo: Any, task_id: int | None = None) -> dict[str, Any]:
        templates = repo.list_templates()
        task = self._task(repo, task_id)
        if not task:
            field_groups = self._field_groups({}, {}, ["task"], templates)
            return {
                "ok": False,
                "mode": None,
                "taskId": task_id,
                "productId": None,
                "missing": ["task"],
                "warnings": ["未选择任务，无法预览真实执行取值"],
                "fieldGroups": field_groups,
                "templatePriority": CUSTOMER_TEMPLATE_PRIORITY,
                "executionSections": self._execution_sections(field_groups),
                "templateTrace": [],
                "resolvedDefaults": {},
            }

        product = self._product_for_task(repo, task)
        applicable_templates = self._applicable_templates(templates, task, product)
        validation = self.validation.validate_task(task, applicable_templates, product=product)
        defaults, source_tree, template_trace = self._effective_defaults(templates, task, product)
        missing = list(validation.get("missing") or [])
        field_groups = self._field_groups(defaults, source_tree, missing, applicable_templates)
        return {
            "ok": bool(validation.get("ok")),
            "mode": validation.get("mode"),
            "taskId": task.get("id"),
            "productId": product.get("id") if isinstance(product, Mapping) else None,
            "missing": missing,
            "warnings": list(validation.get("warnings") or []),
            "fieldGroups": field_groups,
            "templatePriority": CUSTOMER_TEMPLATE_PRIORITY,
            "executionSections": self._execution_sections(field_groups),
            "templateTrace": template_trace,
            "resolvedDefaults": defaults,
        }

    def _task(self, repo: Any, task_id: int | None) -> Mapping[str, Any] | None:
        if task_id is not None:
            return repo.get_task_private(task_id)
        tasks = repo.list_tasks()
        if not tasks:
            return None
        return repo.get_task_private(tasks[0]["id"])

    def _product_for_task(self, repo: Any, task: Mapping[str, Any]) -> Mapping[str, Any] | None:
        payload = task.get("payload") if isinstance(task.get("payload"), Mapping) else {}
        product_ids = payload.get("product_ids") if isinstance(payload, Mapping) else []
        target_id = product_ids[0] if isinstance(product_ids, list) and product_ids else None
        products = repo.list_products()
        if target_id is not None:
            for product in products:
                if product.get("id") == target_id:
                    return product
        return products[0] if products else None

    def _field_groups(
        self,
        defaults: Mapping[str, Any],
        source_tree: Mapping[str, Any],
        missing: list[str],
        templates: list[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        missing_set = set(missing)
        present_templates = {
            self._normalize_template_type(template.get("template_type"))
            for template in templates
            if template.get("is_enabled", True)
        }
        groups: list[dict[str, Any]] = []
        for group in FIELD_GROUPS:
            section = str(group["section"])
            template_type = str(group["templateType"])
            group_missing = self._missing_for_group(section, missing_set)
            if section == "dxm_reference":
                fields = self._dxm_reference_fields(defaults, source_tree, missing_set)
            else:
                fields = []
                for field in group["fields"]:
                    path = str(field["path"])
                    value = self._path_value(defaults, path)
                    required = bool(field["required"])
                    field_missing = required and (not self._non_empty(value) or self._path_missing(path, missing_set))
                    fields.append({
                        "path": path,
                        "name": field["field"],
                        "label": field["label"],
                        "value": value if value is not None else "",
                        "source": self._path_value(source_tree, path) or "未设置",
                        "required": required,
                        "missing": field_missing,
                    })
            template_present = template_type in present_templates or template_type == "task_basic"
            complete = template_present and not group_missing and all(not item["missing"] for item in fields)
            groups.append({
                "section": section,
                "label": group["label"],
                "templateType": template_type,
                "required": template_type in ConfigValidationService.SAVE_REQUIRED_TEMPLATES or template_type in {"compliance", "dxm_reference"},
                "templatePresent": template_present,
                "complete": complete,
                "missing": sorted(group_missing),
                "fields": fields,
            })
        return groups

    def _execution_sections(self, field_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
        sections: list[dict[str, Any]] = []
        for group in field_groups:
            sections.append({
                "section": group["section"],
                "label": group["label"],
                "complete": group["complete"],
                "required": group["required"],
                "missing": group["missing"],
                "fields": [
                    {
                        "label": field["label"],
                        "value": field["value"],
                        "source": self._customer_source_label(field.get("source")),
                        "required": field["required"],
                        "missing": field["missing"],
                    }
                    for field in group["fields"]
                ],
            })
        return sections

    def _customer_source_label(self, source: Any) -> str:
        text = str(source or "").strip()
        if not text or text == "未设置":
            return "未填写"
        if text == "任务覆盖" or text.startswith("任务："):
            return "来自本次任务"
        if text.startswith("模板："):
            return f"来自{text}"
        if text.startswith("商品："):
            return "来自商品原始数据"
        if text.startswith("系统"):
            return "来自系统默认"
        return f"来自{text}"

    def _missing_for_group(self, section: str, missing: set[str]) -> set[str]:
        aliases = {
            "task_basic": {"store", "mode", "claim_mark"},
            "category": {"category"},
            "sku": {"sku"},
            "pricing": {"pricing"},
            "image": {"image", "image.eu_outer_package_filename", "image.marketing_images_strategy"},
            "logistics": {"logistics", "logistics.weight", "logistics.dimensions"},
            "compliance": {"compliance"},
            "semi_managed": {
                "semi_managed",
                "semi_managed.product_price_or_supply_price",
                "semi_managed.jit_stock",
                "semi_managed.is_original_box",
                "semi_managed.dimensions",
                "semi_managed.goods_code_strategy",
                "semi_managed.barcode_strategy",
            },
            "dxm_reference": {"dxm_reference_templates"},
        }
        prefixes = aliases.get(section, {section})
        return {
            item
            for item in missing
            if item in prefixes
            or item.startswith(f"{section}.")
            or (section == "dxm_reference" and item.startswith("dxm_reference_templates."))
        }

    def _path_missing(self, path: str, missing: set[str]) -> bool:
        if path in missing:
            return True
        if path.startswith("logistics.") and "logistics.dimensions" in missing and path.rsplit(".", 1)[-1] in {"length", "width", "height"}:
            return True
        if path.startswith("semi_managed.") and "semi_managed.dimensions" in missing and path.rsplit(".", 1)[-1] in {"length", "width", "height"}:
            return True
        if path == "semi_managed.product_price" and "semi_managed.product_price_or_supply_price" in missing:
            return True
        return False

    def _dxm_reference_fields(
        self,
        defaults: Mapping[str, Any],
        source_tree: Mapping[str, Any],
        missing: set[str],
    ) -> list[dict[str, Any]]:
        resolved = self._path_value(defaults, "dxm_reference_templates_resolved")
        fields: list[dict[str, Any]] = []
        for section in REFERENCE_TEMPLATE_SECTIONS:
            config = resolved.get(section) if isinstance(resolved, Mapping) else {}
            names = config.get("names") if isinstance(config, Mapping) else []
            required = bool(config.get("required", True)) if isinstance(config, Mapping) else True
            path = f"dxm_reference_templates_resolved.{section}.names"
            field_missing = required and (not self._non_empty(names) or f"dxm_reference_templates.{section}" in missing)
            fields.append({
                "path": path,
                "name": section,
                "label": DXM_REFERENCE_LABELS.get(section, section),
                "value": names if names is not None else [],
                "source": self._dxm_reference_source(source_tree, section),
                "required": required,
                "missing": field_missing,
            })
        return fields

    def _dxm_reference_source(self, source_tree: Mapping[str, Any], section: str) -> str:
        candidate_paths = [
            f"dxm_reference_templates.{section}.names",
            f"dxm_reference_templates.{section}.templates",
            f"dxm_reference_templates.{section}.template_names",
            f"dxm_reference_templates.{section}.priorities",
            f"dxm_reference_templates.{section}.name",
            f"dxm_reference_templates.{section}",
        ]
        candidate_paths.extend(LEGACY_REFERENCE_TEMPLATE_PATHS.get(section, ()))
        for path in candidate_paths:
            source = self._path_value(source_tree, path)
            if isinstance(source, str) and source:
                return source
        return "未设置"

    def _effective_defaults(
        self,
        templates: list[Mapping[str, Any]],
        task: Mapping[str, Any],
        product: Mapping[str, Any] | None,
    ) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
        result = self.defaults_resolver.resolve(templates, task, product)
        return result.defaults, result.sources, result.template_trace

    def _applicable_templates(
        self,
        templates: list[Mapping[str, Any]],
        task: Mapping[str, Any],
        product: Mapping[str, Any] | None,
    ) -> list[Mapping[str, Any]]:
        return [
            template
            for template in templates
            if self.defaults_resolver.template_applies_to(template, task, product)
        ]

    def _template_applies_to(
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
        actual_category = (product or {}).get("category_name") or product_payload.get("category_name") or task_payload.get("category_name") or task_payload.get("category")
        actual_platform = task_payload.get("platform") or task.get("platform") or "AliExpress"
        return (
            self._matches_binding(binding, ("store_name", "store", "stores", "store_names"), actual_store)
            and self._matches_binding(binding, ("category_name", "category", "categories", "category_names"), actual_category)
            and self._matches_binding(binding, ("platform", "platforms"), actual_platform)
        )

    def _matches_binding(self, binding: Mapping[str, Any], keys: tuple[str, ...], actual: Any) -> bool:
        expected = next((binding.get(key) for key in keys if key in binding), None)
        if expected is None or expected == "":
            return True
        actual_text = str(actual or "").strip().lower()
        values = expected if isinstance(expected, (list, tuple, set)) else [expected]
        normalized = [str(value or "").strip().lower() for value in values]
        return "*" in normalized or "all" in normalized or actual_text in normalized

    def _merge_template_payload(
        self,
        target: dict[str, Any],
        sources: dict[str, Any],
        template_type: str,
        payload: Mapping[str, Any],
        source_label: str,
    ) -> None:
        self._merge_payload(target, sources, payload, source_label)
        grouped_payload = payload.get(template_type)
        if isinstance(grouped_payload, Mapping):
            self._deep_merge(target.setdefault(template_type, {}), grouped_payload)
            self._deep_source_merge(sources.setdefault(template_type, {}), grouped_payload, source_label)
            return
        flat_group_payload = {
            key: value
            for key, value in payload.items()
            if key not in DEFAULT_TEMPLATE_TYPES and key != "template_overrides"
        }
        if flat_group_payload:
            self._deep_merge(target.setdefault(template_type, {}), flat_group_payload)
            self._deep_source_merge(sources.setdefault(template_type, {}), flat_group_payload, source_label)

    def _merge_payload(
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
            normalized = self._normalize_template_type(key)
            target_key = normalized if normalized in DEFAULT_TEMPLATE_TYPES else key
            if isinstance(value, Mapping) and isinstance(target.get(target_key), dict):
                self._deep_merge(target[target_key], value)
                self._deep_source_merge(sources.setdefault(target_key, {}), value, source_label)
            elif isinstance(value, Mapping):
                target[target_key] = dict(value)
                sources[target_key] = self._source_tree(value, source_label)
            else:
                target[target_key] = value
                sources[target_key] = source_label

    def _deep_merge(self, target: dict[str, Any], source: Mapping[str, Any]) -> None:
        for key, value in source.items():
            if isinstance(value, Mapping) and isinstance(target.get(key), dict):
                self._deep_merge(target[key], value)
            elif isinstance(value, Mapping):
                target[key] = dict(value)
            else:
                target[key] = value

    def _deep_source_merge(self, target: dict[str, Any], source: Mapping[str, Any], source_label: str) -> None:
        for key, value in source.items():
            if isinstance(value, Mapping) and isinstance(target.get(key), dict):
                self._deep_source_merge(target[key], value, source_label)
            elif isinstance(value, Mapping):
                target[key] = self._source_tree(value, source_label)
            else:
                target[key] = source_label

    def _source_tree(self, payload: Mapping[str, Any], source_label: str) -> dict[str, Any]:
        return {
            key: self._source_tree(value, source_label) if isinstance(value, Mapping) else source_label
            for key, value in payload.items()
        }

    def _path_value(self, payload: Mapping[str, Any], path: str) -> Any:
        current: Any = payload
        for part in path.split("."):
            if not isinstance(current, Mapping):
                return None
            current = current.get(part)
        return current

    def _normalize_template_type(self, value: Any) -> str:
        return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")

    def _non_empty(self, value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, Mapping):
            return bool(value)
        if isinstance(value, (list, tuple, set)):
            return any(self._non_empty(item) for item in value)
        return str(value).strip() != ""
