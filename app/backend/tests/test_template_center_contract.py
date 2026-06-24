from src.services.config_preview import FIELD_GROUPS
from src.services.dxm_reference_templates import REFERENCE_TEMPLATE_SECTIONS
from src.services.template_center import editable_sections, resolve_template


def test_template_resolution_priority_uses_task_then_selected_category_store_system():
    resolved = resolve_template(
        task_template={"id": "task", "name": "本次任务模板"},
        selected_template={"id": "selected", "name": "手动选择模板"},
        category_template={"id": "category", "name": "类目模板"},
        store_template={"id": "store", "name": "店铺模板"},
        system_template={"id": "system", "name": "系统默认模板"},
    )
    assert resolved["id"] == "task"
    assert resolved["source_label"] == "本次任务覆盖"

    fallback = resolve_template(
        task_template=None,
        selected_template=None,
        category_template=None,
        store_template={"id": "store", "name": "店铺模板"},
        system_template={"id": "system", "name": "系统默认模板"},
    )
    assert fallback["id"] == "store"
    assert fallback["source_label"] == "店铺默认模板"


def test_template_resolution_distinguishes_category_default_from_store_default():
    resolved = resolve_template(
        task_template=None,
        selected_template=None,
        category_template={"id": "category-default", "name": "立牌类目默认模板"},
        store_template={"id": "store-default", "name": "Dang Kang 店铺默认模板"},
        system_template={"id": "system", "name": "系统默认模板"},
    )

    assert resolved["id"] == "category-default"
    assert resolved["source_label"] == "类目默认模板"
    assert resolved["scope_label"] == "当前类目默认"


def test_template_fields_have_chinese_labels_and_store_edit_page_sections():
    sections = editable_sections()
    labels = [field["label"] for section in sections for field in section["fields"]]
    section_labels = [section["label"] for section in sections]

    for required_section in [
        "店铺与任务基础",
        "类目与标题",
        "SKU / 价格 / 库存",
        "图片与素材",
        "包装物流",
        "合规 / 海关",
        "半托管",
        "店小秘引用模板",
    ]:
        assert required_section in section_labels

    for required_label in ["店铺", "绑定类目", "认领标记", "主图策略", "物流属性", "报关品名", "半托管模板"]:
        assert required_label in labels

    assert all("_" not in field["label"] for section in sections for field in section["fields"])
    assert all(field["key"] for section in sections for field in section["fields"])


def test_template_center_fields_match_config_preview_execution_fields():
    sections = {section["template_type"]: section for section in editable_sections()}

    for group in FIELD_GROUPS:
        template_type = group["templateType"]
        assert template_type in sections
        if template_type == "dxm_reference":
            continue
        template_keys = {field["key"] for field in sections[template_type]["fields"]}
        preview_fields = {field["field"] for field in group["fields"]}
        assert preview_fields.issubset(template_keys)


def test_template_center_exposes_all_dxm_reference_template_sections():
    sections = {section["template_type"]: section for section in editable_sections()}
    reference_keys = {field["key"] for field in sections["dxm_reference"]["fields"]}

    for section in REFERENCE_TEMPLATE_SECTIONS:
        assert f"dxm_reference_templates.{section}.names" in reference_keys
