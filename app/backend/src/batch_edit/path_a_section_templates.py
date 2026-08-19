from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from src.batch_edit.frozen_execution_contract import FrozenExecutionContractError


PATH_A_REQUIRED_TEMPLATE_SECTIONS: tuple[dict[str, Any], ...] = (
    {
        "section": "attribute_info",
        "editor_label": "属性信息 · 产品属性模板",
        "ref_type": "attribute",
        "category_bound": True,
    },
    {
        "section": "freight",
        "editor_label": "模版信息 · 运费模板",
        "ref_type": "freight",
        "category_bound": False,
    },
    {
        "section": "service",
        "editor_label": "模版信息 · 服务模板",
        "ref_type": "service",
        "category_bound": False,
    },
)

PATH_A_RECOMMENDED_TEMPLATE_SECTIONS: tuple[dict[str, Any], ...] = (
    {
        "section": "product",
        "editor_label": "动作栏 · 引用产品模板 / 包装信息",
        "ref_type": "product",
        "category_bound": False,
    },
    {
        "section": "variation",
        "editor_label": "产品信息 · 变种模板",
        "ref_type": "variation",
        "category_bound": True,
    },
    {
        "section": "size",
        "editor_label": "描述信息 · 尺码表",
        "ref_type": "size",
        "category_bound": True,
    },
)

# Map frozen DXM template-ref types onto the field-level reference-template
# sections that `_apply_dxm_reference_templates_on_page` already knows.
PATH_A_REF_TYPE_TO_REFERENCE_SECTION = {
    "attribute": "attribute_info",
    "freight": "freight",
    "service": "service",
}

PATH_A_FILL_CONTEXT_KEY = "_path_a_fill_context"


def evaluate_path_a_section_templates(
    refs: Any,
    category_id: str,
) -> dict[str, Any]:
    """Report which Path A editor sections already have frozen DXM templates."""

    category = str(category_id or "").strip()
    normalized_refs = [
        ref
        for ref in refs
        if isinstance(ref, Mapping)
        and str(ref.get("availability") or "available") == "available"
        and str(ref.get("type") or ref.get("ref_type") or "").strip()
        and str(ref.get("id") or ref.get("dxm_template_id") or "").strip()
    ]
    present: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    recommended_missing: list[dict[str, Any]] = []

    for spec in PATH_A_REQUIRED_TEMPLATE_SECTIONS:
        match = _matching_ref(normalized_refs, spec, category)
        if match is None:
            missing.append({**spec, "template_id": None, "template_name": None})
        else:
            present.append(match)

    for spec in PATH_A_RECOMMENDED_TEMPLATE_SECTIONS:
        match = _matching_ref(normalized_refs, spec, category)
        if match is None:
            recommended_missing.append(
                {**spec, "template_id": None, "template_name": None}
            )
        else:
            present.append(match)

    return {
        "ok": not missing,
        "category_id": category,
        "present": present,
        "missing": missing,
        "recommended_missing": recommended_missing,
        "missing_labels": [item["editor_label"] for item in missing],
    }


def build_path_a_fill_context(
    refs: Any,
    category_id: str,
) -> dict[str, Any]:
    """Build the runtime-only context that drives template Select writes.

    This context is attached to execution defaults as ``_path_a_fill_context`` and
    is ignored by frozen-defaults validation. It never invents template names;
    it only re-exports frozen DXM template refs for the existing reference-template
    UI path.
    """

    report = evaluate_path_a_section_templates(refs, category_id)
    reference_templates: dict[str, dict[str, Any]] = {}
    product_template: dict[str, Any] | None = None

    for item in report["present"]:
        ref_type = str(item.get("ref_type") or "")
        template_id = str(item.get("template_id") or "").strip()
        template_name = str(item.get("template_name") or "").strip()
        names = [value for value in (template_name, template_id) if value]
        if ref_type == "product":
            product_template = {
                "id": template_id,
                "name": template_name,
                "priorities": names,
            }
            continue
        section = PATH_A_REF_TYPE_TO_REFERENCE_SECTION.get(ref_type)
        if section is None or not names:
            continue
        reference_templates[section] = {
            "names": names,
            "required": True,
            "template_id": template_id,
            "template_name": template_name or None,
        }

    return {
        "schema": "dxm.path_a.fill_context.v1",
        "category_id": str(category_id or "").strip(),
        "report": report,
        "dxm_reference_templates": reference_templates,
        "product_template": product_template,
    }


def reject_if_path_a_section_templates_missing(
    plan: Mapping[str, Any] | None,
    category_id: str,
) -> dict[str, Any] | None:
    """Fail closed for real E2 snapshots that still lack required section templates.

    Synthetic fixtures without ``dxm_template_refs`` stay unchanged.
    """

    if not isinstance(plan, Mapping) or "dxm_template_refs" not in plan:
        return None
    report = evaluate_path_a_section_templates(plan.get("dxm_template_refs"), category_id)
    if report["ok"] is True:
        return report
    labels = "、".join(report["missing_labels"])
    raise FrozenExecutionContractError(
        "PATH_A_SECTION_TEMPLATES_MISSING",
        "Path A 实机填写前必须先配齐该类目分区模板，当前缺少：" + labels,
    )


def _matching_ref(
    refs: Sequence[Mapping[str, Any]],
    spec: Mapping[str, Any],
    category_id: str,
) -> dict[str, Any] | None:
    wanted = str(spec["ref_type"])
    for ref in refs:
        ref_type = str(ref.get("type") or ref.get("ref_type") or "").strip()
        if ref_type != wanted:
            continue
        ref_category = ref.get("category_id")
        if spec.get("category_bound") is True:
            if str(ref_category or "").strip() != category_id:
                continue
        elif ref_category not in {None, "", category_id}:
            continue
        template_id = str(ref.get("id") or ref.get("dxm_template_id") or "").strip()
        if not template_id:
            continue
        template_name = str(
            ref.get("observed_display_name")
            or ref.get("name")
            or ref.get("template_name")
            or ""
        ).strip()
        return {
            **dict(spec),
            "template_id": template_id,
            "template_name": template_name or None,
        }
    return None
