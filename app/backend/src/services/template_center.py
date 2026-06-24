from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.services.config_preview import DXM_REFERENCE_LABELS, FIELD_GROUPS
from src.services.dxm_reference_templates import REFERENCE_TEMPLATE_SECTIONS


TemplateLike = Mapping[str, Any] | None

SOURCE_SCOPE_LABELS = {
    "本次任务覆盖": "仅本次任务",
    "手动选择模板": "手动选择",
    "类目默认模板": "当前类目默认",
    "店铺默认模板": "当前店铺默认",
    "系统默认模板": "系统默认",
}


def editable_sections() -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    for group in FIELD_GROUPS:
        section = str(group["section"])
        template_type = str(group["templateType"])
        fields = _dxm_reference_fields() if section == "dxm_reference" else [
            {
                "key": str(field["field"]),
                "label": str(field["label"]),
                "required": bool(field["required"]),
                "value_kind": _value_kind_for_field(str(field["field"])),
            }
            for field in group["fields"]
        ]
        sections.append({
            "id": section,
            "label": str(group["label"]),
            "template_type": template_type,
            "fields": fields,
        })
    return sections


def _dxm_reference_fields() -> list[dict[str, Any]]:
    return [
        {
            "key": f"dxm_reference_templates.{section}.names",
            "label": DXM_REFERENCE_LABELS.get(section, section),
            "required": True,
            "value_kind": "list",
        }
        for section in REFERENCE_TEMPLATE_SECTIONS
    ]


def _value_kind_for_field(field: str) -> str:
    if field in {
        "stock",
        "jit_stock",
        "normal_stock",
        "product_price",
        "supply_price",
        "price_multiplier",
        "fixed_price",
        "weight",
        "length",
        "width",
        "height",
        "package_gross_weight",
    }:
        return "number"
    return "text"


def resolve_template(
    *,
    task_template: TemplateLike = None,
    selected_template: TemplateLike = None,
    category_template: TemplateLike = None,
    store_template: TemplateLike = None,
    system_template: TemplateLike = None,
) -> dict[str, Any]:
    candidates = [
        ("本次任务覆盖", task_template),
        ("手动选择模板", selected_template),
        ("类目默认模板", category_template),
        ("店铺默认模板", store_template),
        ("系统默认模板", system_template),
    ]
    for source_label, template in candidates:
        if template:
            return {
                **dict(template),
                "source_label": source_label,
                "scope_label": SOURCE_SCOPE_LABELS[source_label],
            }
    return {"id": None, "name": "未选择模板", "source_label": "未配置", "scope_label": "未配置"}


def template_center_metadata() -> dict[str, Any]:
    return {
        "sections": editable_sections(),
        "source_priority": ["本次任务覆盖", "手动选择模板", "类目默认模板", "店铺默认模板", "系统默认模板", "商品原始数据"],
        "actions": ["仅本次任务使用", "设为店铺默认模板", "设为类目默认模板", "另存为新模板", "套用预置配置模板"],
    }
