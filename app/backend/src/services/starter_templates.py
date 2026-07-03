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
    """Return the built-in editable starter template pack for one store/category."""
    binding = {
        "store_name": store_name,
        "category_name": category_name,
        "platform": platform,
    }
    binding_scope = f"店铺：{store_name} / 类目：{category_name} / 平台：{platform}"
    reference_templates = {
        "attribute_info": {"names": [f"{category_name}属性模板"], "required": True},
        "description": {"names": ["详情描述模板-ACG立牌"], "required": True},
        "freight": {"names": ["石油40g普货包裹.", "40g普货包裹"], "required": True},
        "service": {"names": ["Service Template for New Sellers"], "required": True},
        "eu_responsible": {"names": ["Jacqueiline Marti"], "required": True},
        "manufacturer": {"names": ["jiyang county thunder", "Jiyang County thunder"], "required": True},
        "compliance": {"names": ["合规模板", "钥匙扣", "keychain"], "required": True},
        "semi_managed": {"names": ["半托管模板"], "required": True},
    }
    return [
        {
            "template_type": "category",
            "template_name": f"{category_name} / 类目与标题起步模板",
            "binding_scope": binding_scope,
            "payload": {
                "binding": binding,
                "category": {
                    "category_keyword": "立牌" if "立牌" in category_name else category_name,
                    "category_match": "ACG Stand",
                    "attribute_template_priorities": reference_templates["attribute_info"]["names"],
                },
            },
            "is_enabled": True,
        },
        {
            "template_type": "sku",
            "template_name": f"{category_name} / SKU与库存起步模板",
            "binding_scope": binding_scope,
            "payload": {
                "binding": binding,
                "sku": {
                    "goods_code_strategy": "沿用店小秘生成",
                    "barcode_strategy": "留空",
                    "stock": "200",
                    "jit_stock": "100",
                },
            },
            "is_enabled": True,
        },
        {
            "template_type": "pricing",
            "template_name": f"{category_name} / 价格策略起步模板",
            "binding_scope": binding_scope,
            "payload": {
                "binding": binding,
                "pricing": {
                    "declared_value": "1",
                    "stock": "200",
                    "product_price": "7.01",
                    "supply_price": "5.20",
                },
            },
            "is_enabled": True,
        },
        {
            "template_type": "logistics",
            "template_name": f"{category_name} / 包装物流起步模板",
            "binding_scope": binding_scope,
            "payload": {
                "binding": binding,
                "logistics": {
                    "weight": "0.03",
                    "length": "10",
                    "width": "10",
                    "height": "2",
                    "freight_templates": reference_templates["freight"]["names"],
                    "service_templates": reference_templates["service"]["names"],
                    "logistics_attribute": "普货",
                    "is_original_box": "否",
                },
            },
            "is_enabled": True,
        },
        {
            "template_type": "image",
            "template_name": f"{category_name} / 图片与素材起步模板",
            "binding_scope": binding_scope,
            "payload": {
                "binding": binding,
                "image": {
                    "source": "图片银行（速卖通）",
                    "eu_outer_package_filename": "微信图片_202504092228421.jpg",
                    "marketing_images_strategy": "使用 EU 外包装图补齐 3:4",
                    "main_image_strategy": "保留 800x800 合规主图",
                    "invalid_image_strategy": "删除 0x0 无效图",
                },
            },
            "is_enabled": True,
        },
        {
            "template_type": "compliance",
            "template_name": f"{category_name} / 合规海关起步模板",
            "binding_scope": binding_scope,
            "payload": {
                "binding": binding,
                "compliance": {
                    "eu_responsible_names": reference_templates["eu_responsible"]["names"],
                    "manufacturer_names": reference_templates["manufacturer"]["names"],
                    "customs_product_names": ["钥匙扣", "keychain"],
                    "customs_name": "钥匙扣",
                    "material": "Acrylic",
                    "purpose": "Decoration",
                    "brand": "无品牌",
                    "statement": "符合平台合规要求",
                },
            },
            "is_enabled": True,
        },
        {
            "template_type": "semi_managed",
            "template_name": f"{category_name} / 半托管起步模板",
            "binding_scope": binding_scope,
            "payload": {
                "binding": binding,
                "semi_managed": {
                    "product_price": "7.01",
                    "supply_price": "5.20",
                    "jit_stock": "100",
                    "is_original_box": "否",
                    "length": "10",
                    "width": "10",
                    "height": "2",
                    "goods_code_strategy": "沿用店小秘生成",
                    "barcode_strategy": "留空",
                },
            },
            "is_enabled": True,
        },
        {
            "template_type": "dxm_reference",
            "template_name": f"{category_name} / 店小秘引用模板起步模板",
            "binding_scope": binding_scope,
            "payload": {
                "binding": binding,
                "dxm_reference_templates": reference_templates,
            },
            "is_enabled": True,
        },
    ]


def starter_template_matches(
    template: Mapping[str, Any],
    *,
    template_type: str,
    store_name: str,
    category_name: str,
    platform: str = "AliExpress",
) -> bool:
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
        and _binding_value_matches(binding, ("category_name", "category", "categories", "category_names"), category_name)
        and _binding_value_matches(binding, ("platform", "platforms"), platform)
    )


def _binding_value_matches(binding: Mapping[str, Any], keys: tuple[str, ...], actual: str) -> bool:
    expected = next((binding.get(key) for key in keys if key in binding), None)
    if expected is None or expected == "":
        return True
    values = expected if isinstance(expected, (list, tuple, set)) else [expected]
    normalized = [str(value or "").strip().lower() for value in values]
    actual_text = str(actual or "").strip().lower()
    return "*" in normalized or "all" in normalized or actual_text in normalized
