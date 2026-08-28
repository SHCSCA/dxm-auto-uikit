from __future__ import annotations

from collections.abc import Mapping
from typing import Any


EDITOR_SECTIONS = (
    {
        "code": "basic_info",
        "label": "基本信息",
        "anchor": "productBasicInfo",
        "help": "与店小秘主编辑页一致：店铺名称、产品标题、产品分类。",
    },
    {
        "code": "dxm_info",
        "label": "店小秘信息",
        "anchor": "dxmInfo",
        "help": "与店小秘主编辑页一致：仅配置来源 URL。",
    },
    {
        "code": "attribute_info",
        "label": "属性信息",
        "anchor": "attrInfo",
        "help": "当前类目接口返回的产品属性、级联属性和属性模板。",
    },
    {
        "code": "product_info",
        "label": "产品信息",
        "anchor": "productProductInfo",
        "help": "图片、SKU、价格、库存和变种字段。",
    },
    {
        "code": "regional_pricing",
        "label": "区域调价信息",
        "anchor": "adjustPriceInfo",
        "help": "国家和区域定价接口返回的字段。",
    },
    {
        "code": "description_info",
        "label": "描述信息",
        "anchor": "describeInfo",
        "help": "尺码表与新版描述编辑器流程；不是普通字段清单。",
    },
    {
        "code": "packaging_info",
        "label": "包装信息",
        "anchor": "packageInfo",
        "help": "重量、包装尺寸和包装方式。",
    },
    {
        "code": "template_main",
        "label": "模版信息",
        "anchor": "templateInfo",
        "help": "店铺级运费、服务、海关监管与税率信息。",
    },
    {
        "code": "compliance_info",
        "label": "合规信息",
        "anchor": "complianceInfo",
        "help": "资质、责任人和制造商等合规字段。",
    },
    {
        "code": "other_info",
        "label": "其他信息",
        "anchor": "otherInfo",
        "help": "当前编辑合同返回但不属于以上分区的字段。",
    },
)

SEMI_MANAGED_SECTION = {
    "code": "semi_managed",
    "label": "半托管信息",
    "help": "方案选择参与半托管时，配置二段编辑页的货品、物流与库存字段。",
}

_SECTION_CODES = {
    *(section["code"] for section in EDITOR_SECTIONS),
    SEMI_MANAGED_SECTION["code"],
}

# The operator-facing plan is intentionally narrower than the raw edit.json
# payload.  These two sections are the most visible place where DXM returns
# transport/current-value fields that must remain available to the executor
# but must never leak into the shared plan configuration UI.
_OPERATOR_VISIBLE_ALLOWLIST = {
    "basic_info": {"title", "categoryId", "shopName"},
    "dxm_info": {"sourceUrl"},
}
_EDITOR_FIELD_SECTIONS = {
    "title": "basic_info",
    "categoryId": "basic_info",
    "productUnit": "product_info",
    "lotNum": "product_info",
    "deliveryTime": "product_info",
    "summary": "other_info",
    "shopName": "basic_info",
    "sourceUrl": "dxm_info",
    "sourcePlatform": "dxm_info",
    "sourceCategoryId": "dxm_info",
    "comment": "dxm_info",
    "aeopAeProductSKUs": "product_info",
    "imageURLs": "product_info",
    "detail": "description_info",
    "mobileDetail": "description_info",
    "grossWeight": "packaging_info",
    "packageLength": "packaging_info",
    "packageWidth": "packaging_info",
    "packageHeight": "packaging_info",
    "originalBox": "packaging_info",
    "productPrice": "product_info",
    "productMinPrice": "product_info",
    "productMaxPrice": "product_info",
    "currencyCode": "product_info",
    "variantTheme": "product_info",
    "marketImg1": "product_info",
    "marketImg2": "product_info",
    "videoUrl": "product_info",
    "aeopNationalQuoteConfiguration": "regional_pricing",
    "packageType": "packaging_info",
    "isPackSell": "packaging_info",
    "baseUnit": "packaging_info",
    "addUnit": "packaging_info",
    "addWeight": "packaging_info",
    "freightTemplateId": "template_main",
    "promiseTemplateId": "template_main",
    "sizechartId": "description_info",
    "hsCode": "template_main",
    "taxType": "template_main",
    "msrEuId": "compliance_info",
    "msrTrId": "compliance_info",
    "manufactureId": "compliance_info",
    "gpsrTag": "compliance_info",
    "aeopQualificationStructList": "compliance_info",
    "businessGoodsFlag": "other_info",
    "specialProductTypeList": "other_info",
    "isJoinChoice": "other_info",
    "semiManagedProductPrice": "semi_managed",
    "semiManagedSupplyPrice": "semi_managed",
    "semiManagedJitStock": "semi_managed",
    "semiManagedOriginalBox": "semi_managed",
    "semiManagedLength": "semi_managed",
    "semiManagedWidth": "semi_managed",
    "semiManagedHeight": "semi_managed",
    "semiManagedGoodsCodeStrategy": "semi_managed",
    "semiManagedBarcodeStrategy": "semi_managed",
}
_FALLBACK_TEMPLATE_SECTION = {
    "attribute": "attribute_info",
    "variation": "product_info",
    "size": "description_info",
    "freight": "template_main",
    "service": "template_main",
    "regional": "regional_pricing",
    "module_property": "attribute_info",
    "module_template": "template_main",
    "module_package": "packaging_info",
}

_PRODUCT_MODULE_SECTIONS = {
    "basic": "basic_info",
    "property": "attribute_info",
    "attribute": "attribute_info",
    "variant": "product_info",
    "sku": "product_info",
    "product": "product_info",
    "region": "regional_pricing",
    "desc": "description_info",
    "description": "description_info",
    "sizechart": "description_info",
    "package": "packaging_info",
    "template": "template_main",
    "tax": "template_main",
    "compliance": "compliance_info",
    "other": "other_info",
}


def normalize_dxm_editor_schemas(
    category_schemas: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    """Attach stable editor metadata at the backend Reader boundary.

    This is deliberately exact-binding based. It exists for trusted Reader
    implementations that predate ``ui_section``; unknown bindings do not fall
    into a heuristic bucket.
    """

    normalized: dict[str, dict[str, Any]] = {}
    for raw_category_id, raw_schema in category_schemas.items():
        category_id = str(raw_category_id)
        if not isinstance(raw_schema, Mapping):
            raise ValueError(f"category {category_id} schema must be an object")
        properties = raw_schema.get("properties")
        if not isinstance(properties, Mapping):
            raise ValueError(f"category {category_id} schema properties are missing")
        schema = dict(raw_schema)
        normalized_properties: dict[str, dict[str, Any]] = {}
        for raw_field_key, raw_definition in properties.items():
            field_key = str(raw_field_key)
            if not isinstance(raw_definition, Mapping):
                raise ValueError(f"field {category_id}.{field_key} must be an object")
            definition = dict(raw_definition)
            section = str(definition.get("ui_section") or "")
            binding = str(definition.get("ui_binding") or "")
            if section not in _SECTION_CODES:
                if binding.startswith("dxm_attribute:"):
                    identity = binding.removeprefix("dxm_attribute:")
                    if not identity.isdecimal() or int(identity) <= 0:
                        raise ValueError(
                            f"field {category_id}.{field_key} has invalid attribute binding"
                        )
                    section = "attribute_info"
                elif binding.startswith("dxm_editor:"):
                    editor_field = binding.removeprefix("dxm_editor:")
                    section = _EDITOR_FIELD_SECTIONS.get(editor_field, "")
                if section not in _SECTION_CODES:
                    raise ValueError(
                        f"field {category_id}.{field_key} has no valid ui_section"
                    )
                definition["ui_section"] = section
            visible_allowlist = _OPERATOR_VISIBLE_ALLOWLIST.get(section)
            if visible_allowlist is not None and field_key not in visible_allowlist:
                # Keep the raw field in the execution schema, but make the
                # operator contract explicit.  Relying only on the frontend
                # to hide these fields made old payloads reappear after a
                # sync/remount and caused the basic/DXM sections to drift.
                definition["ui_visible"] = False
                definition["ui_hidden_reason"] = "operator_section_allowlist"
            definition.setdefault(
                "source_api",
                "/api/smtCategory/attributeList.json"
                if section == "attribute_info"
                else "/api/smtProduct/edit.json",
            )
            normalized_properties[field_key] = definition
        schema["properties"] = normalized_properties
        normalized[category_id] = schema
    return normalized


def enrich_dxm_editor_schema(
    schema: Mapping[str, Any],
    *,
    product: Mapping[str, Any] | None = None,
    unit_options: list[Mapping[str, Any]] | None = None,
    msr_options: list[Mapping[str, Any]] | None = None,
    manufacturer_options: list[Mapping[str, Any]] | None = None,
    qualifications: list[Mapping[str, Any]] | None = None,
    logistics_options: list[Mapping[str, Any]] | None = None,
    include_semi_managed: bool = True,
) -> dict[str, Any]:
    """Extend the category-attribute schema with the real editor partitions.

    DXM's category API describes only product attributes.  The editor itself
    is bootstrapped by ``smtProduct/edit.json`` plus store/category option
    endpoints.  This function keeps that distinction explicit and never
    invents option values that were not returned by those endpoints.
    """

    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        raise ValueError("editor schema properties are missing")
    enriched = dict(schema)
    merged = {str(key): dict(value) for key, value in properties.items()}

    definitions: dict[str, dict[str, Any]] = {
        "categoryId": _field("string", "产品分类", "basic_info", read_only=True, visible=True),
        "productType": _field("string", "产品形态", "basic_info", read_only=True),
        "brandId": _field("string", "品牌 ID", "attribute_info", read_only=True),
        "productUnit": _field("string", "计件单位", "product_info", visible=True, options=_option_values(unit_options, ("unitId", "id"), ("chName", "displayName", "name")), option_source="/api/smtProduct/edit.json"),
        "lotNum": _field("integer", "每包数量", "product_info"),
        "deliveryTime": _field("integer", "发货期限", "product_info", visible=True),
        "summary": _field("string", "商品简述", "other_info", natural_language=True, control="textarea"),
        "shopName": _field("string", "店铺名称", "basic_info", read_only=True, visible=True),
        "sourceUrl": _field("string", "来源 URL", "dxm_info", read_only=True, visible=True),
        "sourcePlatform": _field("string", "来源平台", "dxm_info", read_only=True),
        "sourceCategoryId": _field("string", "来源类目", "dxm_info", read_only=True),
        "comment": _field("string", "店小秘备注", "dxm_info", control="textarea"),
        "commentColor": _field("string", "备注颜色", "dxm_info"),
        "sourceName": _field("string", "来源名称", "dxm_info", read_only=True),
        "dxmState": _field("string", "草稿状态", "dxm_info", read_only=True),
        "variantTheme": _field("string", "变种主题", "product_info"),
        "marketImg1": _field("string", "1:1 白底营销图", "product_info", visible=True, control="media"),
        "marketImg2": _field("string", "3:4 场景营销图", "product_info", visible=True, control="media"),
        "videoUrl": _field("string", "产品视频", "product_info", visible=True, control="media"),
        "groupId": _field("string", "产品分组", "product_info", visible=True),
        "bulkOrder": _field("integer", "批发起订量", "product_info", visible=True),
        "bulkDiscount": _field("number", "批发折扣", "product_info", visible=True),
        "bulkDiscountType": _field("integer", "批发折扣类型", "product_info"),
        "aeopNationalQuoteConfiguration": _field("string", "区域调价", "regional_pricing", visible=True, control="regional_pricing"),
        "packageType": _field("boolean", "包装类型", "packaging_info", visible=True),
        "isPackSell": _field("boolean", "自定义计重", "packaging_info", visible=True),
        "baseUnit": _field("integer", "基础件数", "packaging_info", visible=True),
        "addUnit": _field("integer", "增加件数", "packaging_info", visible=True),
        "addWeight": _field("number", "增加重量", "packaging_info", visible=True),
        "hsCode": _field("string", "海关监管属性", "template_main", visible=True, control="json"),
        "taxType": _field("integer", "税率类型", "template_main", visible=True),
        "msrEuId": _field("string", "欧盟责任人", "compliance_info", visible=True, options=_option_values(msr_options, ("msrEuId", "id"), ("msrEuName", "name")), option_source="/api/smtCommMsr/list.json"),
        "msrTrId": _field("string", "土耳其责任人", "compliance_info", visible=True, options=_option_values(msr_options, ("msrTrId", "id"), ("msrTrName", "msrEuName", "name")), option_source="/api/smtCommMsr/list.json"),
        "manufactureId": _field("string", "品牌制造商", "compliance_info", visible=True, options=_option_values(manufacturer_options, ("manufactureId", "id"), ("manufactureName", "name")), option_source="/api/smtCommManufacture/list.json"),
        "gpsrTag": _field("integer", "商品是否含大头针", "compliance_info", visible=True),
        "aeopQualificationStructList": _field("array", "资质信息", "compliance_info", visible=True, control="qualification"),
        "submitEuQualification": _field("boolean", "商品销售欧盟国家", "compliance_info", visible=True),
        "businessGoodsFlag": _field("boolean", "商机品", "other_info", visible=True),
        "reduceStrategy": _field("string", "库存扣减策略", "other_info"),
        "wsValidNum": _field("integer", "产品有效期", "product_info", visible=True),
        "productAdvertisingRecommend": _field("boolean", "广告推荐商品", "other_info"),
        "specialProductTypeList": _field("array", "特殊商品类型", "other_info", items={"type": "string"}),
    }
    if include_semi_managed:
        definitions.update({
            "isJoinChoice": _field("boolean", "半托管服务 · 参与", "other_info", visible=True, control="switch"),
            "semiManagedProductPrice": _field("number", "半托管商品价", "semi_managed"),
            "semiManagedSupplyPrice": _field("number", "半托管供货价", "semi_managed"),
            "semiManagedJitStock": _field("integer", "JIT 库存", "semi_managed"),
            "semiManagedOriginalBox": _field("boolean", "半托管原包装", "semi_managed"),
            "semiManagedLength": _field("number", "半托管长度", "semi_managed"),
            "semiManagedWidth": _field("number", "半托管宽度", "semi_managed"),
            "semiManagedHeight": _field("number", "半托管高度", "semi_managed"),
            "semiManagedGoodsCodeStrategy": _field("string", "货号策略", "semi_managed"),
            "semiManagedBarcodeStrategy": _field("string", "条码策略", "semi_managed"),
        })
    for field_key, definition in definitions.items():
        definition["ui_binding"] = f"dxm_editor:{field_key}"
        merged.setdefault(field_key, definition)

    sku_definition = merged.get("aeopAeProductSKUs")
    if isinstance(sku_definition, Mapping):
        sku_definition = dict(sku_definition)
        sku_definition["ui_control"] = "sku_matrix"
        sku_items = sku_definition.get("items")
        if isinstance(sku_items, Mapping):
            sku_items = dict(sku_items)
            sku_properties = sku_items.get("properties")
            if isinstance(sku_properties, Mapping):
                sku_properties = {
                    str(key): dict(value) if isinstance(value, Mapping) else value
                    for key, value in sku_properties.items()
                }
                sku_properties["logisticAttrList"] = {
                    "type": "array",
                    "ui_label_zh": "SKU 物流属性",
                    "ui_control": "logistics_attribute",
                    "source_api": (
                        "/api/smtCommLogisticAttribute/"
                        "getLogisticAttributeList.json"
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "value": {
                                "type": "string",
                                "ui_label_zh": "物流属性值",
                                "values": [
                                    {"id": item["value"], "name": item["label"]}
                                    for item in _flatten_logistics_options(logistics_options)
                                ],
                            },
                            "parent_value_id": {
                                "type": "string",
                                "ui_label_zh": "上级物流属性值",
                            },
                            "text": {
                                "type": "string",
                                "ui_label_zh": "物流属性中文名",
                            },
                        },
                        "required": ["value", "text"],
                    },
                }
                sku_items["properties"] = sku_properties
                sku_definition["items"] = sku_items
                sku_definition["source_api"] = (
                    "/api/smtProduct/edit.json + "
                    "/api/smtCommLogisticAttribute/getLogisticAttributeList.json"
                )
                merged["aeopAeProductSKUs"] = sku_definition

    qualification_fields: list[str] = []
    for index, raw in enumerate(qualifications or []):
        if not isinstance(raw, Mapping):
            continue
        raw_key = str(raw.get("key") or "").strip()
        label = str(raw.get("label") or "").strip()
        if not raw_key or not label:
            continue
        stable_suffix = "".join(char if char.isalnum() else "_" for char in raw_key)
        stable_suffix = stable_suffix.strip("_") or str(index + 1)
        field_key = f"qualification_{stable_suffix}"
        merged[field_key] = _field(
            "string",
            label,
            "compliance_info",
            visible=True,
            control="qualification",
            option_source="/api/smtCategory/syncQualification.json",
        )
        merged[field_key]["ui_binding"] = f"dxm_editor:{field_key}"
        merged[field_key]["qualification_key"] = raw_key
        merged[field_key]["tips"] = str(raw.get("tips") or "")
        merged[field_key]["country_code"] = str(raw.get("countryCode") or "")
        merged[field_key]["conditional_required"] = bool(raw.get("required"))
        qualification_fields.append(field_key)

    enriched["properties"] = merged
    required = [
        field_key
        for field_key in (enriched.get("required") or [])
        if field_key != "title"
    ]
    if "categoryId" not in required:
        required.append("categoryId")
    for field_key in qualification_fields:
        if merged[field_key].get("conditional_required") and field_key not in required:
            required.append(field_key)
    enriched["required"] = required
    return enriched


def build_dxm_editor_models(
    *,
    category_schemas: Mapping[str, Any],
    template_records: list[Mapping[str, Any]],
    refs: list[Mapping[str, Any]],
    representative_products: Mapping[str, Mapping[str, Any]] | None = None,
    data_sources: list[Mapping[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Build the JSON-driven operator form from normalized DXM read results.

    The frontend is intentionally not allowed to infer sections from field
    names. Every field must carry backend-proven ``ui_section`` provenance.
    Template options are placed beside every section containing a value that
    the template resolves; type fallbacks cover templates whose wire payload
    intentionally contains only identity metadata.
    """

    ref_by_identity = {
        _identity(ref): ref
        for ref in refs
        if ref.get("availability") == "available"
    }
    result: dict[str, dict[str, Any]] = {}
    # Kept as an accepted compatibility argument for older callers.  A local
    # plan is a store + category contract and must not derive its editable
    # defaults from one arbitrary product.
    del representative_products
    for raw_category_id, raw_schema in category_schemas.items():
        category_id = str(raw_category_id)
        if not isinstance(raw_schema, Mapping):
            raise ValueError(f"category {category_id} schema must be an object")
        properties = raw_schema.get("properties")
        if not isinstance(properties, Mapping):
            raise ValueError(f"category {category_id} schema properties are missing")

        section_fields = {code: [] for code in _SECTION_CODES}
        section_sources = {code: set() for code in _SECTION_CODES}
        section_option_sources: dict[str, list[dict[str, Any]]] = {
            code: [] for code in _SECTION_CODES
        }
        field_sections: dict[str, str] = {}
        for raw_field_key, raw_definition in properties.items():
            field_key = str(raw_field_key)
            if not isinstance(raw_definition, Mapping):
                raise ValueError(f"field {category_id}.{field_key} must be an object")
            section_code = str(raw_definition.get("ui_section") or "")
            if section_code not in _SECTION_CODES:
                raise ValueError(
                    f"field {category_id}.{field_key} has no valid ui_section"
                )
            field_sections[field_key] = section_code
            # Captures created before the visibility contract did not carry
            # ui_visible. Preserve those trusted fields, while an explicit
            # DXM visible=0 remains authoritative and hidden.
            is_visible = raw_definition.get("ui_visible", True) is True
            # Description is a two-step editor workflow in DXM, not a normal
            # text field. Keep detail/mobileDetail in the execution Schema so
            # the runner can bind the generated payload, but do not expose a
            # misleading text input in the plan configuration UI.
            is_widget_owned = (
                section_code == "description_info"
                and field_key in {"detail", "mobileDetail"}
            )
            if is_visible and not is_widget_owned:
                section_fields[section_code].append(field_key)
            source_api = str(raw_definition.get("source_api") or "").strip()
            if source_api and is_visible:
                section_sources[section_code].add(source_api)
            option_source = str(raw_definition.get("option_source") or "").strip()
            if option_source and is_visible:
                raw_values = raw_definition.get("values")
                if not isinstance(raw_values, list):
                    items = raw_definition.get("items")
                    raw_values = items.get("values") if isinstance(items, Mapping) else []
                section_option_sources[section_code].append({
                    "field_key": field_key,
                    "label": str(raw_definition.get("ui_label_zh") or field_key),
                    "source_api": option_source,
                    "option_count": len(raw_values) if isinstance(raw_values, list) else 0,
                })

        templates_by_section: dict[str, list[dict[str, Any]]] = {
            code: [] for code in _SECTION_CODES
        }
        seen_template_sections: set[tuple[str, int]] = set()
        for record in template_records:
            record_category_id = record.get("category_id")
            if record_category_id is not None and str(record_category_id) != category_id:
                continue
            ref = ref_by_identity.get(_identity(record))
            if ref is None:
                continue
            resolved_values = record.get("resolved_values")
            if not isinstance(resolved_values, Mapping):
                raise ValueError("template resolved_values must be an object")
            target_sections = {
                field_sections[field_key]
                for field_key in resolved_values
                if field_key in field_sections
            }
            module_types: list[str] = []
            if str(record.get("ref_type") or "") == "product":
                source_record = record.get("source_record")
                module_list = source_record.get("moduleList") if isinstance(source_record, Mapping) else None
                if isinstance(module_list, list):
                    for module in module_list:
                        if not isinstance(module, Mapping):
                            continue
                        module_type = str(module.get("moduleType") or module.get("type") or "").strip().casefold()
                        if module_type:
                            module_types.append(module_type)
                            section = _PRODUCT_MODULE_SECTIONS.get(module_type)
                            if section:
                                target_sections.add(section)
            if not target_sections:
                fallback = _FALLBACK_TEMPLATE_SECTION.get(str(record.get("ref_type") or ""))
                if fallback:
                    target_sections.add(fallback)
            option = {
                "ref_id": int(ref["id"]),
                "ref_type": str(ref["ref_type"]),
                "dxm_template_id": str(ref["dxm_template_id"]),
                "display_name": str(ref.get("observed_display_name") or ""),
                "category_id": (
                    str(ref["category_id"])
                    if ref.get("category_id") is not None
                    else None
                ),
                "source_digest": str(ref["source_digest"]),
                "resolved_field_keys": sorted(
                    field_key
                    for field_key in resolved_values
                    if field_sections.get(field_key) in target_sections
                ),
                "resolved_values": {
                    str(field_key): value
                    for field_key, value in resolved_values.items()
                    if field_sections.get(str(field_key)) in target_sections
                },
                "module_types": sorted(set(module_types)),
            }
            raw_resolved_keys = {
                str(field_key)
                for field_key in resolved_values
                if str(field_key).strip()
            }
            mapped_resolved_keys = set(option["resolved_field_keys"])
            unmapped_resolved_keys = sorted(raw_resolved_keys - mapped_resolved_keys)
            option["resolved_field_count"] = len(mapped_resolved_keys)
            option["unmapped_field_keys"] = unmapped_resolved_keys
            option["coverage_state"] = (
                "none"
                if not mapped_resolved_keys
                else "complete"
                if not unmapped_resolved_keys
                else "partial"
            )
            source_api = str(record.get("source_api") or "").strip()
            for section_code in sorted(target_sections):
                dedupe_key = (section_code, option["ref_id"])
                if dedupe_key in seen_template_sections:
                    continue
                seen_template_sections.add(dedupe_key)
                templates_by_section[section_code].append(dict(option))
                if source_api:
                    section_sources[section_code].add(source_api)

        sections = []
        # The main DXM editor has exactly ten anchors. Semi-managed remains a
        # selectable plan path, but it is not allowed to masquerade as an
        # eleventh main-editor section.
        section_contracts = list(EDITOR_SECTIONS)
        for order, section_contract in enumerate(section_contracts):
            code = section_contract["code"]
            widgets: list[dict[str, Any]] = []
            if code == "description_info":
                widgets.append({
                    "kind": "description_editor",
                    "label": "描述",
                    "workflow": [
                        "使用新版编辑器",
                        "根据 PC 端描述一键生成",
                        "确认",
                        "保存",
                    ],
                })
            if code == "product_info":
                widgets.append({
                    "kind": "marketing_image_generator",
                    "label": "营销图片",
                    "workflow": [
                        "使用商品主图一键生成",
                        "生成 1:1 白底图",
                        "生成 3:4 场景图",
                    ],
                })
            sections.append(
                {
                    **section_contract,
                    "order": order,
                    "field_keys": section_fields[code],
                    "templates": sorted(
                        templates_by_section[code],
                        key=lambda item: (
                            item["ref_type"],
                            item["display_name"],
                            item["ref_id"],
                        ),
                    ),
                    "source_apis": sorted(section_sources[code]),
                    "option_sources": section_option_sources[code],
                    "widgets": widgets,
                    "data_sources": [
                        dict(item)
                        for item in (data_sources or [])
                        if (
                            str(item.get("section") or "") == code
                            or str(item.get("path") or item.get("url") or "")
                            in section_sources[code]
                        )
                    ],
                }
            )
        result[category_id] = {
            "schema": "dxm_editor_form.v4",
            "category_id": category_id,
            "sections": sections,
            "value_scope": "store_category_plan",
        }
    return result


def _identity(value: Mapping[str, Any]) -> tuple[str, str, str, str | None]:
    category_id = value.get("category_id")
    return (
        str(value.get("ref_type") or ""),
        str(value.get("dxm_template_id") or ""),
        str(value.get("shop_id") or ""),
        str(category_id) if category_id is not None else None,
    )


def _field(
    field_type: str,
    label: str,
    section: str,
    *,
    natural_language: bool = False,
    read_only: bool = False,
    visible: bool = False,
    control: str | None = None,
    options: list[dict[str, str]] | None = None,
    option_source: str | None = None,
    items: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    definition: dict[str, Any] = {
        "type": field_type,
        "ui_label_zh": label,
        "ui_binding": "",
        "ui_section": section,
        "source_api": "/api/smtProduct/edit.json",
        "natural_language": natural_language,
        "read_only": read_only,
        "ui_visible": visible,
        "ui_control": control or ("select" if options else "input"),
    }
    # The caller owns the stable field key, so the binding is attached there.
    if options:
        definition["values"] = [
            {"id": item["value"], "name": item["label"]}
            for item in options
        ]
    if option_source:
        definition["option_source"] = option_source
        definition["source_api"] = option_source
    if items is not None:
        definition["items"] = dict(items)
    return definition


def _option_values(
    values: list[Mapping[str, Any]] | None,
    id_keys: tuple[str, ...],
    name_keys: tuple[str, ...],
) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in values or []:
        if not isinstance(raw, Mapping):
            continue
        option_id = next((str(raw.get(key)).strip() for key in id_keys if raw.get(key) not in (None, "")), "")
        label = next((str(raw.get(key)).strip() for key in name_keys if str(raw.get(key) or "").strip()), "")
        if not option_id or not label or option_id in seen:
            continue
        seen.add(option_id)
        result.append({"value": option_id, "label": label})
    return result


def _flatten_logistics_options(
    values: list[Mapping[str, Any]] | None,
) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[str] = set()

    def visit(raw: Mapping[str, Any]) -> None:
        option_id = str(raw.get("value_id") or raw.get("value") or "").strip()
        label = str(raw.get("label") or raw.get("text") or "").strip()
        if option_id and label and option_id not in seen:
            seen.add(option_id)
            result.append({"value": option_id, "label": label})
        children = raw.get("children")
        if isinstance(children, list):
            for child in children:
                if isinstance(child, Mapping):
                    visit(child)

    for raw in values or []:
        if isinstance(raw, Mapping):
            visit(raw)
    return result
