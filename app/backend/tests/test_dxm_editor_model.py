from src.services.dxm_editor_model import (
    build_dxm_editor_models,
    enrich_dxm_editor_schema,
    normalize_dxm_editor_schemas,
)
from src.execution.dxm_login_flow import DxmLoginFlow


def test_editor_model_uses_backend_section_metadata_and_places_templates_with_fields() -> None:
    schemas = {
        "2621": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "ui_label_zh": "英文标题",
                    "ui_binding": "dxm_editor:title",
                    "ui_section": "basic_info",
                    "source_api": "/api/smtProduct/edit.json",
                    "ui_visible": True,
                },
                "attr_2": {
                    "type": "string",
                    "ui_label_zh": "品牌",
                    "ui_binding": "dxm_attribute:2",
                    "ui_section": "attribute_info",
                    "source_api": "/api/smtCategory/attributeList.json",
                    "ui_visible": True,
                },
                "grossWeight": {
                    "type": "number",
                    "ui_label_zh": "包装后重量",
                    "ui_binding": "dxm_editor:grossWeight",
                    "ui_section": "packaging_info",
                    "source_api": "/api/smtProduct/edit.json",
                    "ui_visible": True,
                },
            },
            "required": ["title", "attr_2"],
        }
    }
    template_records = [
        {
            "ref_type": "attribute",
            "dxm_template_id": "9301",
            "shop_id": "101",
            "category_id": "2621",
            "observed_display_name": "产品属性模板 A",
            "resolved_values": {"attr_2": "200000123"},
        },
        {
            "ref_type": "product",
            "dxm_template_id": "701",
            "shop_id": "101",
            "category_id": "2621",
            "observed_display_name": "产品模板 A",
            "resolved_values": {"title": "Example", "grossWeight": 1.2, "mystery": "x"},
        },
    ]
    refs = [
        {
            "id": 11,
            "ref_type": "attribute",
            "dxm_template_id": "9301",
            "shop_id": "101",
            "category_id": "2621",
            "observed_display_name": "产品属性模板 A",
            "availability": "available",
            "source_digest": "a" * 64,
        },
        {
            "id": 12,
            "ref_type": "product",
            "dxm_template_id": "701",
            "shop_id": "101",
            "category_id": "2621",
            "observed_display_name": "产品模板 A",
            "availability": "available",
            "source_digest": "b" * 64,
        },
    ]

    model = build_dxm_editor_models(
        category_schemas=schemas,
        template_records=template_records,
        refs=refs,
    )["2621"]

    assert model["schema"] == "dxm_editor_form.v4"
    assert model["value_scope"] == "store_category_plan"
    assert "representative_product_id" not in model
    assert "current_values" not in model
    sections = {section["code"]: section for section in model["sections"]}
    assert sections["basic_info"]["field_keys"] == ["title"]
    assert sections["attribute_info"]["field_keys"] == ["attr_2"]
    assert sections["packaging_info"]["field_keys"] == ["grossWeight"]
    assert [item["ref_id"] for item in sections["attribute_info"]["templates"]] == [11]
    assert sections["attribute_info"]["templates"][0]["resolved_values"] == {
        "attr_2": "200000123"
    }
    assert [item["ref_id"] for item in sections["basic_info"]["templates"]] == [12]
    assert sections["basic_info"]["templates"][0]["coverage_state"] == "partial"
    assert sections["basic_info"]["templates"][0]["unmapped_field_keys"] == ["mystery"]
    assert [item["ref_id"] for item in sections["packaging_info"]["templates"]] == [12]
    assert sections["attribute_info"]["source_apis"] == [
        "/api/smtCategory/attributeList.json"
    ]


def test_editor_model_fails_closed_when_a_field_has_no_backend_section() -> None:
    schemas = {
        "2621": {
            "type": "object",
            "properties": {
                "attr_2": {
                    "type": "string",
                    "ui_label_zh": "品牌",
                    "ui_binding": "dxm_attribute:2",
                }
            },
            "required": [],
        }
    }

    try:
        build_dxm_editor_models(
            category_schemas=schemas,
            template_records=[],
            refs=[],
        )
    except ValueError as exc:
        assert "ui_section" in str(exc)
    else:
        raise AssertionError("missing ui_section must fail closed")


def test_editor_schema_covers_real_sections_api_options_and_optional_semi_managed() -> None:
    schema = enrich_dxm_editor_schema(
        {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "ui_label_zh": "英文标题",
                    "ui_binding": "dxm_editor:title",
                    "ui_section": "basic_info",
                    "source_api": "/api/smtProduct/edit.json",
                    "ui_visible": True,
                },
                "aeopAeProductSKUs": {
                    "type": "array",
                    "ui_label_zh": "SKU 行",
                    "ui_binding": "dxm_editor:aeopAeProductSKUs",
                    "ui_section": "product_info",
                    "source_api": "/api/smtProduct/edit.json",
                    "ui_visible": True,
                    "items": {"type": "object", "properties": {}, "required": []},
                },
            },
            "required": ["title"],
        },
        msr_options=[{"msrEuId": 91, "msrEuName": "欧盟责任人甲"}],
        manufacturer_options=[{"manufactureId": 81, "manufactureName": "制造商甲"}],
        qualifications=[{
            "key": "eu_doc",
            "label": "欧盟资质文件",
            "countryCode": "EU",
            "required": True,
        }],
        logistics_options=[
            {"value_id": "1983471271", "label": "普货", "children": None},
            {
                "value_id": "1983471275",
                "label": "纯电",
                "children": [{"value_id": "796", "label": "干电池"}],
            },
        ],
    )

    assert schema["properties"]["msrEuId"]["values"] == [
        {"id": "91", "name": "欧盟责任人甲"}
    ]
    assert schema["properties"]["manufactureId"]["option_source"] == (
        "/api/smtCommManufacture/list.json"
    )
    assert schema["properties"]["aeopAeProductSKUs"]["ui_control"] == "sku_matrix"
    assert schema["properties"]["aeopNationalQuoteConfiguration"]["ui_control"] == "regional_pricing"
    assert schema["properties"]["qualification_eu_doc"]["ui_section"] == (
        "compliance_info"
    )
    assert "qualification_eu_doc" in schema["required"]
    assert schema["properties"]["isJoinChoice"]["ui_section"] == "other_info"
    logistic_values = (
        schema["properties"]["aeopAeProductSKUs"]["items"]["properties"]
        ["logisticAttrList"]["items"]["properties"]["value"]["values"]
    )
    assert logistic_values == [
        {"id": "1983471271", "name": "普货"},
        {"id": "1983471275", "name": "纯电"},
        {"id": "796", "name": "干电池"},
    ]

    model = build_dxm_editor_models(
        category_schemas={"2621": schema},
        template_records=[],
        refs=[],
        representative_products={
            "2621": {"__product_id": "70001", "title": "Current title"}
        },
    )["2621"]
    section_codes = [section["code"] for section in model["sections"]]
    assert section_codes == [
        "basic_info",
        "dxm_info",
        "attribute_info",
        "product_info",
        "regional_pricing",
        "description_info",
        "packaging_info",
        "template_main",
        "compliance_info",
        "other_info",
    ]
    sections = {section["code"]: section for section in model["sections"]}
    assert sections["description_info"]["widgets"] == [{
        "kind": "description_editor",
        "label": "描述",
        "workflow": ["使用新版编辑器", "根据 PC 端描述一键生成", "确认", "保存"],
    }]
    assert model["value_scope"] == "store_category_plan"
    assert "representative_product_id" not in model
    assert "current_values" not in model
    assert sections["product_info"]["widgets"] == [{
        "kind": "marketing_image_generator",
        "label": "营销图片",
        "workflow": ["使用商品主图一键生成", "生成 1:1 白底图", "生成 3:4 场景图"],
    }]
    assert "categoryId" in schema["required"]
    assert "title" not in schema["required"]


def test_operator_model_matches_basic_and_dxm_visible_fields_exactly() -> None:
    schema = enrich_dxm_editor_schema({
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "ui_label_zh": "产品标题",
                "ui_binding": "dxm_editor:title",
                "ui_section": "basic_info",
                "source_api": "/api/smtProduct/edit.json",
                "ui_visible": True,
            },
            "attr_1": {
                "type": "string",
                "ui_label_zh": "隐藏属性",
                "ui_binding": "dxm_attribute:1",
                "ui_section": "attribute_info",
                "source_api": "/api/smtCategory/attributeList.json",
                "ui_visible": False,
            },
        },
        "required": ["title"],
    })
    model = build_dxm_editor_models(
        category_schemas={"2621": schema},
        template_records=[],
        refs=[],
    )["2621"]
    sections = {section["code"]: section for section in model["sections"]}
    assert sections["basic_info"]["field_keys"] == ["title", "categoryId", "shopName"]
    assert sections["dxm_info"]["field_keys"] == ["sourceUrl"]
    assert "attr_1" not in sections["attribute_info"]["field_keys"]
    assert len(model["sections"]) == 10


def test_description_payload_fields_are_owned_by_the_new_editor_widget() -> None:
    schema = enrich_dxm_editor_schema({
        "type": "object",
        "properties": {
            "detail": {
                "type": "string",
                "ui_label_zh": "PC 英文描述",
                "ui_binding": "dxm_editor:detail",
                "ui_section": "description_info",
                "ui_visible": True,
            },
            "mobileDetail": {
                "type": "string",
                "ui_label_zh": "移动端英文描述",
                "ui_binding": "dxm_editor:mobileDetail",
                "ui_section": "description_info",
                "ui_visible": True,
            },
        },
        "required": [],
    })
    model = build_dxm_editor_models(category_schemas={"2621": schema}, template_records=[], refs=[])["2621"]
    description = next(section for section in model["sections"] if section["code"] == "description_info")
    assert description["field_keys"] == []
    assert description["widgets"][0]["kind"] == "description_editor"


def test_category_visible_flag_controls_operator_display_without_dropping_schema() -> None:
    schema = DxmLoginFlow._e2_category_schema([
        {
            "arrtNameId": 1,
            "nameZh": "后台隐藏属性",
            "nameEn": "Hidden",
            "inputType": "SINGLE",
            "sku": 0,
            "required": 0,
            "visible": 0,
            "values": [],
            "units": [],
        },
        {
            "arrtNameId": 2,
            "nameZh": "页面显示属性",
            "nameEn": "Visible",
            "inputType": "SINGLE",
            "sku": 0,
            "required": 0,
            "visible": 1,
            "values": [],
            "units": [],
        },
    ], category_id="2621")
    assert "attr_1" in schema["properties"]
    assert schema["properties"]["attr_1"]["ui_visible"] is False
    model = build_dxm_editor_models(
        category_schemas={"2621": schema},
        template_records=[],
        refs=[],
    )["2621"]
    attribute_fields = next(
        section["field_keys"]
        for section in model["sections"]
        if section["code"] == "attribute_info"
    )
    assert attribute_fields == ["attr_2"]


def test_raw_edit_schema_cannot_expand_basic_or_dxm_operator_sections() -> None:
    normalized = normalize_dxm_editor_schemas({
        "2621": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "ui_section": "basic_info",
                    "ui_visible": True,
                },
                "categoryId": {
                    "type": "string",
                    "ui_section": "basic_info",
                    "ui_visible": True,
                },
                "shopName": {
                    "type": "string",
                    "ui_section": "basic_info",
                    "ui_visible": True,
                },
                "productType": {
                    "type": "string",
                    "ui_section": "basic_info",
                    "ui_visible": True,
                },
                "sourceUrl": {
                    "type": "string",
                    "ui_section": "dxm_info",
                    "ui_visible": True,
                },
                "sourcePlatform": {
                    "type": "string",
                    "ui_section": "dxm_info",
                    "ui_visible": True,
                },
            },
        }
    })["2621"]["properties"]
    assert normalized["title"]["ui_visible"] is True
    assert normalized["categoryId"]["ui_visible"] is True
    assert normalized["shopName"]["ui_visible"] is True
    assert normalized["productType"]["ui_visible"] is False
    assert normalized["productType"]["ui_hidden_reason"] == "operator_section_allowlist"
    assert normalized["sourceUrl"]["ui_visible"] is True
    assert normalized["sourcePlatform"]["ui_visible"] is False
