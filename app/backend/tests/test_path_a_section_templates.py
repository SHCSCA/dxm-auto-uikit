from src.batch_edit.frozen_execution_contract import (
    FrozenExecutionContractError,
    frozen_execution_defaults,
    validate_frozen_execution_defaults,
)
from src.batch_edit.path_a_section_templates import (
    PATH_A_FILL_CONTEXT_KEY,
    build_path_a_fill_context,
    evaluate_path_a_section_templates,
    reject_if_path_a_section_templates_missing,
)
from src.batch_edit.scope_contract import canonical_sha256


CATEGORY = "200083142"


def _ref(
    ref_type: str,
    template_id: str,
    category_id: str | None = None,
    *,
    name: str | None = None,
) -> dict:
    payload = {
        "type": ref_type,
        "id": template_id,
        "shop_id": "6517349",
        "category_id": category_id,
        "availability": "available",
    }
    if name is not None:
        payload["observed_display_name"] = name
    return payload


def test_product_only_freeze_is_not_ready_for_path_a_fill():
    report = evaluate_path_a_section_templates(
        [_ref("product", "1138913", name="DangKang 切割刀模包装")],
        CATEGORY,
    )

    assert report["ok"] is False
    assert report["missing_labels"] == [
        "属性信息 · 产品属性模板",
        "模版信息 · 运费模板",
        "模版信息 · 服务模板",
    ]
    assert [item["ref_type"] for item in report["present"]] == ["product"]
    assert report["present"][0]["template_name"] == "DangKang 切割刀模包装"


def test_category_bound_attribute_template_does_not_cover_another_category():
    report = evaluate_path_a_section_templates(
        [
            _ref("attribute", "902", "202228203", name="车载属性模板"),
            _ref("freight", "50146884722", name="默认运费"),
            _ref("service", "88", name="新卖家服务模板"),
        ],
        CATEGORY,
    )

    assert report["ok"] is False
    assert report["missing_labels"] == ["属性信息 · 产品属性模板"]


def test_required_section_templates_ready_when_attribute_freight_service_bound():
    report = evaluate_path_a_section_templates(
        [
            _ref("product", "1138913", name="产品模板"),
            _ref("attribute", "9911", CATEGORY, name="切割刀模属性模板"),
            _ref("freight", "50146884722", name="默认运费"),
            _ref("service", "88", name="新卖家服务模板"),
        ],
        CATEGORY,
    )

    assert report["ok"] is True
    assert report["missing"] == []
    assert report["recommended_missing"] == [
        {
            "section": "variation",
            "editor_label": "产品信息 · 变种模板",
            "ref_type": "variation",
            "category_bound": True,
            "template_id": None,
            "template_name": None,
        },
        {
            "section": "size",
            "editor_label": "描述信息 · 尺码表",
            "ref_type": "size",
            "category_bound": True,
            "template_id": None,
            "template_name": None,
        },
    ]


def test_legacy_fixture_without_template_refs_is_not_blocked():
    assert reject_if_path_a_section_templates_missing({"item_snapshots": []}, CATEGORY) is None


def test_real_snapshot_missing_section_templates_fail_closed():
    plan = {"dxm_template_refs": [_ref("product", "1138913")]}

    try:
        reject_if_path_a_section_templates_missing(plan, CATEGORY)
    except FrozenExecutionContractError as exc:
        assert exc.reason_code == "PATH_A_SECTION_TEMPLATES_MISSING"
        assert "产品属性模板" in str(exc)
        assert "运费模板" in str(exc)
        assert "服务模板" in str(exc)
    else:
        raise AssertionError("expected PATH_A_SECTION_TEMPLATES_MISSING")


def test_unavailable_template_ref_does_not_count():
    report = evaluate_path_a_section_templates(
        [
            {**_ref("attribute", "9911", CATEGORY, name="属性模板"), "availability": "missing"},
            _ref("freight", "50146884722", name="默认运费"),
            _ref("service", "88", name="服务模板"),
        ],
        CATEGORY,
    )

    assert report["ok"] is False
    assert report["missing_labels"] == ["属性信息 · 产品属性模板"]


def test_build_path_a_fill_context_maps_refs_to_reference_template_selects():
    context = build_path_a_fill_context(
        [
            _ref("product", "1138913", name="DangKang 产品模板"),
            _ref("attribute", "9911", CATEGORY, name="切割刀模属性模板"),
            _ref("freight", "50146884722", name="默认运费"),
            _ref("service", "88", name="新卖家服务模板"),
        ],
        CATEGORY,
    )

    assert context["schema"] == "dxm.path_a.fill_context.v1"
    assert context["product_template"] == {
        "id": "1138913",
        "name": "DangKang 产品模板",
        "priorities": ["DangKang 产品模板", "1138913"],
    }
    assert context["dxm_reference_templates"] == {
        "attribute_info": {
            "names": ["切割刀模属性模板", "9911"],
            "required": True,
            "template_id": "9911",
            "template_name": "切割刀模属性模板",
        },
        "freight": {
            "names": ["默认运费", "50146884722"],
            "required": True,
            "template_id": "50146884722",
            "template_name": "默认运费",
        },
        "service": {
            "names": ["新卖家服务模板", "88"],
            "required": True,
            "template_id": "88",
            "template_name": "新卖家服务模板",
        },
    }


def test_apply_frozen_templates_uses_reference_template_select_not_hand_fill(monkeypatch):
    from src.execution.dxm_login_flow import DxmLoginFlow

    flow = object.__new__(DxmLoginFlow)
    flow._path_a_fill_context = build_path_a_fill_context(
        [
            _ref("product", "1138913", name="DangKang 产品模板"),
            _ref("attribute", "9911", CATEGORY, name="切割刀模属性模板"),
            _ref("freight", "50146884722", name="默认运费"),
            _ref("service", "88", name="新卖家服务模板"),
        ],
        CATEGORY,
    )
    calls: list[tuple[str, object]] = []

    monkeypatch.setattr(
        flow,
        "_apply_quoted_product_template_on_page",
        lambda page, template_id, template_name: calls.append(
            ("product", template_id, template_name)
        )
        or {"ok": True, "write_attempted": True, "strategy": "quote_product_template"},
    )
    monkeypatch.setattr(flow, "_dismiss_blocking_modals", lambda page: None)
    monkeypatch.setattr(
        flow,
        "_apply_dxm_reference_templates_on_page",
        lambda page, values: calls.append(("reference", values))
        or {
            "attribute_info": {"ok": True, "names": ["切割刀模属性模板"], "required": True},
            "freight": {"ok": True, "names": ["默认运费"], "required": True},
            "service": {"ok": True, "names": ["新卖家服务模板"], "required": True},
        },
    )
    monkeypatch.setattr(
        flow,
        "_apply_visible_freight_template",
        lambda page, expected: (_ for _ in ()).throw(
            AssertionError("must not hand-fill freight when template select succeeds")
        ),
    )

    class Page:
        def wait_for_timeout(self, _ms):
            return None

    result = flow._apply_frozen_templates_before_field_writes(
        Page(),
        [{"field_key": "freightTemplateId", "resolved_value": "50146884722"}],
    )

    assert result["ok"] is True
    assert result["covers_attributes"] is True
    assert result["covers_freight"] is True
    assert result["covers_service"] is True
    assert calls[0] == ("product", "1138913", "DangKang 产品模板")
    assert calls[1][0] == "reference"
    assert calls[1][1]["dxm_reference_templates"]["attribute_info"]["names"] == [
        "切割刀模属性模板",
        "9911",
    ]


def test_runtime_fill_context_does_not_break_frozen_defaults_validation():
    body = {
        "schema": "dxm.batch_draft_save.execution_payload.v1",
        "product_id": "70001",
        "category_id": CATEGORY,
        "category_schema_hash": "A" * 64,
        "field_mapping_hash": "B" * 64,
        "resolution_hash": "C" * 64,
        "fields": [
            {
                "field_key": "title",
                "ui_label_zh": "英文标题",
                "ui_binding": "dxm_editor:title",
                "category_schema_path": "$.properties.title",
                "resolved_value": "Collectible Display Model",
            }
        ],
        "unresolved_fields": [],
        "price_validation": {},
    }
    payload = {**body, "payload_hash": canonical_sha256(body)}
    defaults = frozen_execution_defaults(payload)
    defaults_with_context = {
        **defaults,
        PATH_A_FILL_CONTEXT_KEY: build_path_a_fill_context(
            [
                _ref("attribute", "9911", CATEGORY, name="切割刀模属性模板"),
                _ref("freight", "50146884722", name="默认运费"),
                _ref("service", "88", name="服务模板"),
            ],
            CATEGORY,
        ),
    }

    validated = validate_frozen_execution_defaults(
        defaults_with_context,
        expected_payload=payload,
    )
    assert validated["payload_hash"] == payload["payload_hash"]
    assert PATH_A_FILL_CONTEXT_KEY in defaults_with_context
