from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
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
    attribute_template_names = default_attribute_template_names(category_name)
    reference_templates = {
        "attribute_info": {"names": attribute_template_names, "required": True},
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
                    "title_strategy": "按来源标题生成英文标题",
                    "title_keyword_map": default_title_keyword_map(category_name),
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
                    "goods_code_strategy": "按来源商品ID生成安全货号",
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
                    "goods_code_strategy": "按来源商品ID生成安全货号",
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


def default_attribute_template_names(category_name: str) -> list[str]:
    """Return real DXM attribute template candidates for the built-in starter pack."""
    normalized = str(category_name or "").strip()
    if "立牌" in normalized:
        return ["万代立牌", "bilibili动漫周边", "万代"]
    return [f"{normalized}属性模板"] if normalized else []


def default_title_keyword_map(category_name: str) -> dict[str, str]:
    """Return editable starter mappings for deterministic English title generation."""
    mappings = {
        "宝可梦": "Pokemon",
        "神奇宝贝": "Pokemon",
        "皮卡丘": "Pikachu",
        "仙子伊布": "Sylveon",
        "伊布": "Eevee",
        "精灵球": "Poke Ball",
        "3D打印": "3D Printed",
        "玩具模型": "Toy Model",
        "模型": "Model",
        "周边": "Collectible",
        "礼物": "Gift",
        "球体摆件": "Ball Ornament",
        "摆件": "Ornament",
        "钥匙扣": "Keychain",
        "亚克力": "Acrylic",
        "高颜值": "Decorative",
    }
    if "立牌" in str(category_name or ""):
        mappings["立牌"] = "Display Stand"
    return mappings


def repair_legacy_starter_template(
    template: Mapping[str, Any],
    starter_template: Mapping[str, Any],
    *,
    category_name: str,
) -> dict[str, Any] | None:
    """Replace only the old generated placeholder attribute template name."""
    legacy_names = [f"{category_name}属性模板"]
    starter_payload = starter_template.get("payload")
    if not isinstance(starter_payload, Mapping):
        return None

    template_type = str(template.get("template_type") or "").strip().lower()
    payload = deepcopy(template.get("payload")) if isinstance(template.get("payload"), Mapping) else {}
    changed = False

    if template_type == "category":
        category = payload.get("category")
        starter_category = starter_payload.get("category")
        if isinstance(category, dict) and isinstance(starter_category, Mapping):
            next_names = _names_at(starter_category, "attribute_template_priorities")
            if _names_at(category, "attribute_template_priorities") == legacy_names and next_names:
                category["attribute_template_priorities"] = next_names
                changed = True
            for key in ("title_strategy", "title_keyword_map"):
                if not category.get(key) and starter_category.get(key):
                    category[key] = deepcopy(starter_category[key])
                    changed = True

    if template_type == "dxm_reference":
        reference = payload.get("dxm_reference_templates")
        starter_reference = starter_payload.get("dxm_reference_templates")
        if isinstance(reference, dict) and isinstance(starter_reference, Mapping):
            attribute_info = reference.get("attribute_info")
            starter_attribute_info = starter_reference.get("attribute_info")
            if isinstance(attribute_info, dict) and isinstance(starter_attribute_info, Mapping):
                next_names = _names_at(starter_attribute_info, "names")
                if _names_at(attribute_info, "names") == legacy_names and next_names:
                    attribute_info["names"] = next_names
                    changed = True

    if not changed:
        return None
    return {
        "template_type": template.get("template_type"),
        "template_name": template.get("template_name"),
        "binding_scope": template.get("binding_scope"),
        "payload": payload,
        "is_enabled": template.get("is_enabled", True),
    }


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


def _names_at(payload: Mapping[str, Any], key: str) -> list[str]:
    raw = payload.get(key)
    if raw is None:
        return []
    values = raw if isinstance(raw, (list, tuple, set)) else [raw]
    return [str(value or "").strip() for value in values if str(value or "").strip()]
