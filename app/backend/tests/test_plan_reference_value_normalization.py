from src.batch_edit.plan_reference_store import ResolvedTemplateReferences
from src.batch_edit.plan_value_contract import PlanValueContract


def test_template_reference_values_are_normalized_to_schema_option_ids() -> None:
    values = PlanValueContract(ValueError)
    refs = ResolvedTemplateReferences(
        [
            {
                "ref_type": "attribute",
                "dxm_template_id": "901",
                "shop_id": "3001",
                "category_id": "2621",
                "observed_display_name": "属性模板",
                "source_digest": "A" * 64,
                "availability": "available",
                "_resolved_values": {
                    "material": {"valueId": "11", "nameZh": "塑料"},
                    "chemical": ["无", {"value_id": "12"}],
                    "grossWeight": "1.25",
                },
            }
        ],
        values=values,
    )
    resolved = refs.values_for_category(
        "2621",
        allowed_fields={
            "material": {
                "type": "string",
                "values": [{"id": "11", "nameZh": "塑料"}],
            },
            "chemical": {
                "type": "array",
                "items": {
                    "type": "string",
                    "values": [
                        {"id": "10", "nameZh": "无"},
                        {"id": "12", "nameZh": "乙醛"},
                    ],
                },
            },
            "grossWeight": {"type": "number"},
        },
    )
    assert resolved["material"][0] == "11"
    assert resolved["chemical"][0] == ["10", "12"]
    assert resolved["grossWeight"][0] == 1.25


def test_template_reference_unknown_schema_option_fails_closed() -> None:
    values = PlanValueContract(ValueError)
    refs = ResolvedTemplateReferences(
        [
            {
                "ref_type": "attribute",
                "dxm_template_id": "901",
                "shop_id": "3001",
                "category_id": "2621",
                "observed_display_name": "属性模板",
                "source_digest": "A" * 64,
                "availability": "available",
                "_resolved_values": {"material": "未知值"},
            }
        ],
        values=values,
    )
    try:
        refs.values_for_category(
            "2621",
            allowed_fields={
                "material": {
                    "type": "string",
                    "values": [{"id": "11", "nameZh": "塑料"}],
                }
            },
        )
    except ValueError as exc:
        assert "not present in the frozen schema" in str(exc)
    else:
        raise AssertionError("unknown template option must fail closed")
