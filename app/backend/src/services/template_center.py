from __future__ import annotations

from collections.abc import Mapping
from typing import Any


TemplateLike = Mapping[str, Any] | None

SOURCE_SCOPE_LABELS = {
    "本次任务覆盖": "仅本次任务",
    "手动选择模板": "手动选择",
    "类目默认模板": "当前类目默认",
    "店铺默认模板": "当前店铺默认",
    "系统默认模板": "系统默认",
}


def editable_sections() -> list[dict[str, Any]]:
    return [
        {
            "id": "basis",
            "label": "店铺与任务基础",
            "template_type": "task_basic",
            "fields": [
                {"key": "store_name", "label": "店铺", "required": True, "value_kind": "text"},
                {"key": "category_name", "label": "绑定类目", "required": True, "value_kind": "text"},
                {"key": "claim_mark", "label": "认领标记", "required": True, "value_kind": "text"},
            ],
        },
        {
            "id": "title",
            "label": "类目与标题",
            "template_type": "category",
            "fields": [
                {"key": "title_prefix", "label": "标题前缀", "required": False, "value_kind": "text"},
                {"key": "title_suffix", "label": "标题后缀", "required": False, "value_kind": "text"},
                {"key": "title_cleaning_rule", "label": "标题清洗规则", "required": False, "value_kind": "text"},
            ],
        },
        {
            "id": "sku_price_stock",
            "label": "SKU / 价格 / 库存",
            "template_type": "sku",
            "fields": [
                {"key": "stock", "label": "库存", "required": False, "value_kind": "number"},
                {"key": "price_strategy", "label": "价格策略", "required": False, "value_kind": "text"},
                {"key": "price_multiplier", "label": "价格倍率", "required": False, "value_kind": "number"},
            ],
        },
        {
            "id": "media",
            "label": "图片与素材",
            "template_type": "image",
            "fields": [
                {"key": "main_image_policy", "label": "主图处理", "required": False, "value_kind": "text"},
                {"key": "eu_outer_package_image", "label": "欧盟外包装图", "required": True, "value_kind": "text"},
                {"key": "marketing_images_strategy", "label": "营销图策略", "required": False, "value_kind": "text"},
            ],
        },
        {
            "id": "logistics",
            "label": "包装物流",
            "template_type": "logistics",
            "fields": [
                {"key": "logistics_type", "label": "物流属性", "required": True, "value_kind": "text"},
                {"key": "package_weight", "label": "包裹重量", "required": False, "value_kind": "number"},
                {"key": "freight_template", "label": "运费模板", "required": False, "value_kind": "text"},
            ],
        },
        {
            "id": "compliance",
            "label": "合规 / 海关",
            "template_type": "compliance",
            "fields": [
                {"key": "customs_cn_name", "label": "海关中文名", "required": False, "value_kind": "text"},
                {"key": "customs_en_name", "label": "海关英文名", "required": False, "value_kind": "text"},
                {"key": "brand", "label": "品牌", "required": False, "value_kind": "text"},
            ],
        },
        {
            "id": "semi_managed",
            "label": "半托管",
            "template_type": "semi_managed",
            "fields": [
                {"key": "semi_managed_template", "label": "半托管模板", "required": True, "value_kind": "text"},
                {"key": "supply_price", "label": "供货价", "required": False, "value_kind": "number"},
            ],
        },
        {
            "id": "dxm_reference",
            "label": "店小秘引用模板",
            "template_type": "dxm_reference",
            "fields": [
                {"key": "dxm_product_template_name", "label": "产品引用模板", "required": False, "value_kind": "text"},
                {"key": "dxm_logistics_template_name", "label": "物流引用模板", "required": False, "value_kind": "text"},
                {"key": "dxm_service_template_name", "label": "服务引用模板", "required": False, "value_kind": "text"},
            ],
        },
    ]


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
