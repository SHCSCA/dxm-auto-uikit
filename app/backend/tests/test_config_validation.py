from src.services.config_validation import ConfigValidationService


def _dxm_reference_templates():
    return {
        "attribute_info": {"names": ["立牌类谷子"]},
        "freight": {"names": ["40g普货包裹"]},
        "service": {"names": ["Service Template for New Sellers"]},
        "eu_responsible": {"names": ["Jacqueiline Marti"]},
        "manufacturer": {"names": ["jiyang county thunder"]},
    }


def _required_templates():
    return [
        {
            "template_type": "category",
            "template_name": "类目模板",
            "payload": {
                "dxm_reference_templates": _dxm_reference_templates(),
                "category": {
                    "category_keyword": "立牌",
                    "category_match": "ACG Stand",
                    "attribute_template_priorities": ["立牌类谷子"],
                },
            },
            "is_enabled": True,
        },
        {
            "template_type": "sku",
            "template_name": "SKU模板",
            "payload": {"sku": {"sku_code": "610274761685-DK-AD-10CM"}},
            "is_enabled": True,
        },
        {
            "template_type": "pricing",
            "template_name": "价格模板",
            "payload": {"pricing": {"declared_value": "1", "stock": "200", "retail_price": "9.99"}},
            "is_enabled": True,
        },
        {
            "template_type": "logistics",
            "template_name": "物流模板",
            "payload": {
                "logistics": {
                    "weight": "0.03",
                    "length": "10",
                    "width": "10",
                    "height": "2",
                    "delivery_days": "7",
                    "freight_template_priorities": ["40g普货包裹"],
                    "service_template_priorities": ["Service Template for New Sellers"],
                    "logistics_attribute": "普货",
                    "is_original_box": "否",
                },
            },
            "is_enabled": True,
        },
        {
            "template_type": "image",
            "template_name": "图片模板",
            "payload": {
                "image": {
                    "eu_outer_package_filename": "template-eu.jpg",
                    "marketing_images_strategy": "generate",
                },
            },
            "is_enabled": True,
        },
        {
            "template_type": "compliance",
            "template_name": "合规模板",
            "payload": {
                "compliance": {
                    "material": "ABS",
                    "eu_responsible_priorities": ["Jacqueiline Marti"],
                    "manufacturer_priorities": ["jiyang county thunder"],
                    "customs_product_name_priorities": ["钥匙扣", "keychain"],
                },
            },
            "is_enabled": True,
        },
        {
            "template_type": "semi_managed",
            "template_name": "半托管模板",
            "payload": {
                "semi_managed": {
                    "supply_price": "4.20",
                    "jit_stock": "100",
                    "is_original_box": "否",
                    "length": "10",
                    "width": "10",
                    "height": "2",
                    "goods_code_strategy": "allow_blank",
                    "barcode_strategy": "allow_blank",
                },
            },
            "is_enabled": True,
        },
    ]


def test_valid_single_save_passes_with_required_templates():
    service = ConfigValidationService()

    result = service.validate_task(
        {
            "mode": "single_save",
            "store_id": 1001,
            "payload": {"product_ids": [501], "publish": False},
        },
        _required_templates(),
    )

    assert result == {
        "ok": True,
        "error_code": None,
        "missing": [],
        "warnings": [],
        "mode": "single_save",
    }


def test_single_save_template_overrides_satisfy_required_save_fields():
    service = ConfigValidationService()
    templates = _required_templates()
    for template in templates:
        payload = template["payload"]
        if template["template_type"] == "image":
            payload["image"].pop("marketing_images_strategy", None)
        if template["template_type"] == "semi_managed":
            payload["semi_managed"].pop("supply_price", None)
            payload["semi_managed"].pop("goods_code_strategy", None)

    result = service.validate_task(
        {
            "mode": "single_save",
            "store_id": 1001,
            "payload": {
                "product_ids": [501],
                "publish": False,
                "template_overrides": {
                    "image": {"marketing_images_strategy": "使用商品图补齐营销图"},
                    "semi_managed": {
                        "product_price": "7.01",
                        "goods_code_strategy": "沿用店小秘生成",
                    },
                },
            },
        },
        templates,
    )

    assert result["ok"] is True
    assert result["missing"] == []


def test_single_save_accepts_flat_image_strategy_from_default_template():
    service = ConfigValidationService()
    templates = _required_templates()
    for template in templates:
        if template["template_type"] == "image":
            image_payload = template["payload"]["image"]
            template["payload"]["marketing_images_strategy"] = image_payload.pop("marketing_images_strategy")

    result = service.validate_task(
        {
            "mode": "single_save",
            "store_id": 1001,
            "payload": {"product_ids": [501], "publish": False},
        },
        templates,
    )

    assert result["ok"] is True
    assert "image.marketing_images_strategy" not in result["missing"]


def test_single_save_ignores_templates_bound_to_other_store():
    service = ConfigValidationService()
    templates = [
        {
            **template,
            "payload": {
                **template["payload"],
                "binding": {"store_name": "Other Store", "category_name": "立牌类谷子", "platform": "AliExpress"},
            },
        }
        for template in _required_templates()
    ]

    result = service.validate_task(
        {
            "mode": "single_save",
            "store_id": 1001,
            "payload": {"store_name": "Dang Kang", "product_ids": [501], "publish": False},
        },
        templates,
        product={"category_name": "立牌类谷子", "payload": {}},
    )

    assert result["ok"] is False
    assert "category" in result["missing"]
    assert "sku" in result["missing"]
    assert "image.eu_outer_package_filename" in result["missing"]


def test_single_save_accepts_new_dxm_reference_templates():
    service = ConfigValidationService()
    templates = [
        (
            {
                **template,
                "payload": {
                    **template["payload"],
                    "dxm_reference_templates": _dxm_reference_templates(),
                },
            }
            if template["template_type"] == "category"
            else template
        )
        for template in _required_templates()
    ]

    result = service.validate_task(
        {
            "mode": "single_save",
            "store_id": 1001,
            "payload": {"product_ids": [501], "publish": False},
        },
        templates,
    )

    assert result["ok"] is True
    assert result["missing"] == []


def test_single_save_rejects_reference_sections_without_real_control_readback():
    templates = _required_templates()
    category = next(
        item for item in templates if item["template_type"] == "category"
    )
    category["payload"]["dxm_reference_templates"].update({
        "description": {"names": ["详情模板"]},
        "compliance": {"names": ["合规模板"]},
        "semi_managed": {"names": ["半托管模板"]},
    })

    result = ConfigValidationService().validate_task(
        {
            "mode": "single_save",
            "store_id": 1001,
            "payload": {"product_ids": [501], "publish": False},
        },
        templates,
    )

    assert result["ok"] is False
    assert result["missing"] == [
        "dxm_reference_templates.description.unsupported",
        "dxm_reference_templates.compliance.unsupported",
        "dxm_reference_templates.semi_managed.unsupported",
    ]


def test_single_save_new_dxm_reference_templates_take_priority_over_legacy_fields():
    service = ConfigValidationService()
    templates = [
        (
            {
                **template,
                "payload": {
                    **template["payload"],
                    "category": {
                        **template["payload"]["category"],
                        "dxm_reference_templates": {
                            "attribute_info": {"names": []},
                        },
                    },
                },
            }
            if template["template_type"] == "category"
            else template
        )
        for template in _required_templates()
    ]

    result = service.validate_task(
        {
            "mode": "single_save",
            "store_id": 1001,
            "payload": {"product_ids": [501], "publish": False},
        },
        templates,
    )

    assert result["ok"] is False
    assert result["missing"] == ["dxm_reference_templates.attribute_info"]


def test_batch_save_requires_configured_dxm_reference_template_names():
    service = ConfigValidationService()
    templates = [
        (
            {
                **template,
                "payload": {
                    **template["payload"],
                    "dxm_reference_templates": {
                        "freight": {"names": [], "required": True},
                    },
                },
            }
            if template["template_type"] == "logistics"
            else template
        )
        for template in _required_templates()
    ]

    result = service.validate_task(
        {
            "mode": "batch_save",
            "store_id": 1001,
            "payload": {"product_ids": [501], "publish": False},
        },
        templates,
    )

    assert result["ok"] is False
    assert result["missing"] == ["dxm_reference_templates.freight"]


def test_single_save_requires_semi_managed_template():
    service = ConfigValidationService()
    templates = [template for template in _required_templates() if template["template_type"] != "semi_managed"]

    result = service.validate_task(
        {
            "mode": "single_save",
            "store_id": 1001,
            "payload": {"product_ids": [501], "publish": False},
        },
        templates,
    )

    assert result["ok"] is False
    assert result["error_code"] == "E302"
    assert result["missing"] == ["semi_managed"]
    assert result["mode"] == "single_save"


def test_single_save_allows_compliance_payload_without_compliance_template():
    service = ConfigValidationService()
    templates = [template for template in _required_templates() if template["template_type"] != "compliance"]

    result = service.validate_task(
        {
            "mode": "single_save",
            "store_id": 1001,
            "payload": {"product_ids": [501], "publish": False, "compliance": {"material": "ABS"}},
        },
        templates,
    )

    assert result["ok"] is True
    assert result["missing"] == []


def test_batch_save_requires_compliance_template_or_payload():
    service = ConfigValidationService()
    templates = [template for template in _required_templates() if template["template_type"] != "compliance"]

    result = service.validate_task(
        {
            "mode": "batch_save",
            "store_id": 1001,
            "payload": {"product_ids": [501], "publish": False},
        },
        templates,
    )

    assert result["ok"] is False
    assert result["missing"] == ["compliance"]


def test_single_save_requires_eu_outer_package_image_from_template_task_or_product():
    service = ConfigValidationService()
    templates = [
        (
            {**template, "payload": {"image": {"alt_text": "missing eu image", "marketing_images_strategy": "generate"}}}
            if template["template_type"] == "image"
            else template
        )
        for template in _required_templates()
    ]

    result = service.validate_task(
        {
            "mode": "single_save",
            "store_id": 1001,
            "payload": {"product_ids": [501], "publish": False},
        },
        templates,
    )

    assert result["ok"] is False
    assert result["missing"] == ["image.eu_outer_package_filename"]


def test_single_save_requires_reusable_save_only_template_fields():
    service = ConfigValidationService()
    templates = [
        (
            {**template, "payload": {"image": {"eu_outer_package_filename": "template-eu.jpg"}}}
            if template["template_type"] == "image"
            else {**template, "payload": {"semi_managed": {"supply_price": "4.20"}}}
            if template["template_type"] == "semi_managed"
            else template
        )
        for template in _required_templates()
    ]

    result = service.validate_task(
        {
            "mode": "single_save",
            "store_id": 1001,
            "payload": {"product_ids": [501], "publish": False},
        },
        templates,
    )

    assert result["ok"] is False
    assert result["missing"] == [
        "image.marketing_images_strategy",
        "semi_managed.jit_stock",
        "semi_managed.is_original_box",
        "semi_managed.dimensions",
        "semi_managed.goods_code_strategy",
        "semi_managed.barcode_strategy",
    ]


def test_single_save_accepts_product_eu_outer_package_image_filename():
    service = ConfigValidationService()
    templates = [
        (
            {**template, "payload": {"image": {"alt_text": "missing eu image", "marketing_images_strategy": "generate"}}}
            if template["template_type"] == "image"
            else template
        )
        for template in _required_templates()
    ]

    result = service.validate_task(
        {
            "mode": "single_save",
            "store_id": 1001,
            "payload": {"product_ids": [501], "publish": False},
        },
        templates,
        product={"payload": {"eu_outer_package_image": {"filename": "product-eu.jpg"}}},
    )

    assert result["ok"] is True
    assert result["missing"] == []


def test_single_save_accepts_eu_outer_package_image_slot_filename():
    service = ConfigValidationService()
    templates = [
        (
            {
                **template,
                "payload": {
                    "image": {
                        "marketing_images_strategy": "generate",
                        "slots": [
                            {
                                "slot_key": "eu_outer_package",
                                "label": "外包装/标签实拍图-欧盟",
                                "filename": "微信图片_202504092228421.jpg",
                            }
                        ],
                    },
                },
            }
            if template["template_type"] == "image"
            else template
        )
        for template in _required_templates()
    ]

    result = service.validate_task(
        {
            "mode": "single_save",
            "store_id": 1001,
            "payload": {"product_ids": [501], "publish": False},
        },
        templates,
    )

    assert result["ok"] is True
    assert result["missing"] == []


def test_publish_modes_are_rejected_before_template_checks():
    service = ConfigValidationService()

    result = service.validate_task(
        {
            "mode": "save_and_publish",
            "store_id": 1001,
            "payload": {"product_ids": [501], "publish": True},
        },
        _required_templates(),
    )

    assert result["ok"] is False
    assert result["error_code"] == "E999"
    assert result["missing"] == []
    assert any("forbidden execution mode" in warning for warning in result["warnings"])
    assert result["mode"] == "save_and_publish"


def test_probe_allows_empty_templates_and_payload():
    service = ConfigValidationService()

    result = service.validate_task({"mode": "probe"}, [])

    assert result["ok"] is True
    assert result["error_code"] is None
    assert result["missing"] == []
    assert result["warnings"] == []
    assert result["mode"] == "probe"
