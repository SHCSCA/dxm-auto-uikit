from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse
from playwright.sync_api import Page, Route


def _e2_plan_payload() -> dict[str, object]:
    return {
        "model": "local_plan_template",
        "id": 9,
        "lineage_id": 9,
        "supersedes_id": None,
        "name": "浏览器测试方案",
        "version": "1.0.0",
        "shop_id": "3001",
        "category_ids": ["100"],
        "path": "B",
        "fixed_values": {"publish_allowed": False},
        "fill_rules": {"100": {}},
        "dxm_template_refs": [{
            "ref_id": 31,
            "source_digest": "A" * 64,
        }],
        "field_mappings": {
            "100": {
                "mapping_version": "zh-map-100-v1",
                "entries": [
                    {
                        "ui_label_zh": "英文标题",
                        "field_key": "title",
                        "category_schema_path": "$.properties.title",
                        "ui_binding": "dxm_editor:title",
                    },
                    {
                        "ui_label_zh": "材质",
                        "field_key": "material",
                        "category_schema_path": "$.properties.material",
                        "ui_binding": "dxm_attribute:5301",
                    },
                ],
            }
        },
        "validation_policy": {
            "required_fields": "fail_closed",
            "natural_language": "english_before_save",
        },
        "exception_policy": {"unknown": "stop_batch"},
        "provenance": "operator_reviewed_local_plan",
        "is_active": True,
        "created_at": "2026-07-30T00:00:00Z",
        "updated_at": "2026-07-30T00:00:00Z",
    }


def _e2_snapshot(*, frozen: bool, execution_released: bool = False) -> dict[str, object]:
    snapshot_hash = "C" * 64
    return {
        **({"id": 5, "task_id": 17} if frozen else {}),
        "schema": "dxm_batch_draft_save_plan.v1",
        "mode": "batch_draft_save",
        "path": "B",
        "shop_scope": "3001",
        "product_ids": ["70001", "70002", "70003"],
        "local_plan_template": {"id": 9, "version": "1.0.0"},
        "dxm_template_refs": [],
        "fixed_values": {"publish_allowed": False},
        "fill_rules": {"100": {}},
        "session_context": {
            "session_ref": "0123456789abcdef",
            "account_ref_hash": "D" * 64,
            "shop_id": "3001",
        },
        "approval_context": {
            "state": "not_granted",
            "runner_released": execution_released,
            "publish_allowed": False,
        },
        "item_snapshots": [
            {"product_id": product_id}
            for product_id in ("70001", "70002", "70003")
        ],
        "evidence_policy": "three_proofs",
        "failure_policy": {"unknown": "stop_batch"},
        "publish_allowed": False,
        "snapshot_hash": snapshot_hash,
    }


def _install_e2_plan_routes(
    page: Page,
    requests: list[tuple[str, str, object | None]],
    *,
    approval_response_lost: bool = False,
    empty_choice_field: bool = False,
    execution_released: bool = False,
) -> None:
    approval_state = {"dispatched": False}

    def handle(route: Route) -> None:
        path = urlparse(route.request.url).path
        method = route.request.method
        body = (
            route.request.post_data_json
            if method == "POST" and route.request.post_data
            else None
        )
        requests.append((method, path, body))
        category_ids = ["10", "20", "100"]
        category_names = ["一级测试类目", "二级测试类目", "测试类目"]
        category_records = {category_id: {
            "categoryId": category_id, "nameZh": category_names[index],
            "pcid": category_ids[index - 1] if index else "0",
            "nodePath": "/".join(category_names[:index + 1]),
            "nodePathId": "/".join(category_ids[:index + 1]),
            "isleaf": index == len(category_ids) - 1,
            "executableLeaf": index == len(category_ids) - 1,
        } for index, category_id in enumerate(category_ids)}
        if path == "/api/dxm/category/children":
            pcid = parse_qs(urlparse(route.request.url).query).get("pcid", [""])[0]
            records = [record for record in category_records.values() if record["pcid"] == (pcid or "0")]
            route.fulfill(status=200, content_type="application/json", body=json.dumps(records, ensure_ascii=False))
            return
        if path == "/api/dxm/category/get":
            category_id = parse_qs(urlparse(route.request.url).query).get("category_id", [""])[0]
            route.fulfill(status=200, content_type="application/json", body=json.dumps(category_records.get(category_id), ensure_ascii=False))
            return
        if path == "/api/dxm/draft-reader/shops":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "source": "api",
                    "session_bound": True,
                    "session_ref": "0123456789abcdef",
                    "shops": [{
                        "id": "3001",
                        "name": "浏览器测试店铺",
                        "platform": "smt",
                        "shop_type": "POP",
                    }],
                }, ensure_ascii=False),
            )
            return
        if path == "/api/dxm/draft-reader/products":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "source": "api",
                    "session_bound": True,
                    "session_ref": "0123456789abcdef",
                    "filter": {"shop_id": "3001", "dxm_state": "draft"},
                    "pagination": {
                        "page_no": 1,
                        "page_size": 100,
                        "total_pages": 1,
                        "total_items": 1,
                        "has_previous": False,
                        "has_next": False,
                    },
                    "items": [{
                        "id": "70001",
                        "shop_id": "3001",
                        "subject": "Draft 70001",
                        "category_id": "100",
                        "category_name": "测试类目",
                        "dxm_state": "draft",
                    }],
                    "deduplicated_count": 0,
                }, ensure_ascii=False),
            )
            return
        if path == "/api/dxm-template-refs/sync":
            route.fulfill(
                status=201,
                content_type="application/json",
                body=json.dumps({
                    "source": "api",
                    "session_bound": True,
                    "session_ref": "0123456789abcdef",
                    "shop_id": "3001",
                    "category_ids": ["100"],
                    "category_schemas": {
                        "100": {
                            "type": "object",
                            "properties": {
                                "title": {
                                    "type": "string",
                                    "minLength": 8,
                                    "natural_language": True,
                                    "ui_label_zh": "英文标题",
                                    "ui_binding": "dxm_editor:title",
                                    "ui_section": "basic_info",
                                    "source_api": "/api/smtProduct/edit.json",
                                },
                                "material": {
                                    "type": "string",
                                    "ui_label_zh": "材质",
                                    "ui_binding": "dxm_attribute:5301",
                                    "ui_section": "attribute_info",
                                    "source_api": "/api/smtCategory/attributeList.json",
                                    "values": [
                                        {
                                            "id": "ABS",
                                            "name": "Plastic",
                                            "names": {"zh": "塑料"},
                                        },
                                        {
                                            "id": "Metal",
                                            "name": "Metal",
                                            "names": {"zh": "金属"},
                                        },
                                    ],
                                },
                                "imageURLs": {
                                    "type": "array",
                                    "ui_label_zh": "主图与附图",
                                    "ui_binding": "dxm_editor:imageURLs",
                                    "ui_section": "product_info",
                                    "source_api": "/api/smtProduct/edit.json",
                                    "items": {
                                        "type": "string",
                                        "minLength": 1,
                                    },
                                },
                                **({
                                    "attr_3": {
                                        "type": "string",
                                        "ui_label_zh": "自定义英文属性",
                                        "ui_binding": "dxm_attribute:3",
                                        "ui_section": "attribute_info",
                                        "source_api": "/api/smtCategory/attributeList.json",
                                        "natural_language": True,
                                        "values": [],
                                        "enum": [],
                                    },
                                } if empty_choice_field else {}),
                            },
                            "required": ["title", "material"],
                        }
                    },
                    "editor_models": {
                        "100": {
                            "schema": "dxm_editor_form.v3",
                            "category_id": "100",
                            "sections": [
                                {
                                    "code": "basic_info",
                                    "label": "基本信息",
                                    "help": "标题与类目基础字段。",
                                    "order": 0,
                                    "field_keys": ["title"],
                                    "templates": [],
                                    "source_apis": ["/api/smtProduct/edit.json"],
                                },
                                {
                                    "code": "attribute_info",
                                    "label": "属性信息",
                                    "help": "类目属性与属性模板。",
                                    "order": 1,
                                    "field_keys": [
                                        "material",
                                        *(["attr_3"] if empty_choice_field else []),
                                    ],
                                    "templates": [{
                                        "ref_id": 31,
                                        "ref_type": "attribute",
                                        "dxm_template_id": "902",
                                        "display_name": "属性模板甲",
                                        "category_id": "100",
                                        "source_digest": "A" * 64,
                                        "resolved_field_keys": ["material"],
                                        "resolved_values": {"material": "ABS"},
                                    }],
                                    "source_apis": [
                                        "/api/smtAttributeTemplate/pageList.json",
                                        "/api/smtCategory/attributeList.json",
                                    ],
                                },
                                {
                                    "code": "product_info",
                                    "label": "产品信息",
                                    "help": "图片、SKU 与价格字段。",
                                    "order": 2,
                                    "field_keys": ["imageURLs"],
                                    "templates": [],
                                    "source_apis": ["/api/smtProduct/edit.json"],
                                },
                                {
                                    "code": "description_info",
                                    "label": "描述信息",
                                    "help": "尺码表与新版描述编辑器流程。",
                                    "order": 3,
                                    "field_keys": [],
                                    "templates": [],
                                    "source_apis": ["/api/smtProduct/edit.json"],
                                    "widgets": [{
                                        "kind": "description_editor",
                                        "label": "描述",
                                        "workflow": [
                                            "使用新版编辑器",
                                            "根据 PC 端描述一键生成",
                                            "确认",
                                            "保存",
                                        ],
                                    }],
                                },
                            ],
                        }
                    },
                    "refs": [{
                        "model": "dxm_template_ref",
                        "id": 31,
                        "ref_type": "attribute",
                        "dxm_template_id": "902",
                        "shop_id": "3001",
                        "category_id": "100",
                        "observed_display_name": "属性模板甲",
                        "source_api": "/api/smtAttributeTemplate/pageList.json",
                        "availability": "available",
                        "source_digest": "A" * 64,
                        "resolved_values_hash": "B" * 64,
                        "resolved_field_count": 1,
                        "synced_at": "2026-07-30T00:00:00Z",
                    }],
                }, ensure_ascii=False),
            )
            return
        if path == "/api/local-plan-templates" and method == "POST":
            route.fulfill(
                status=201,
                content_type="application/json",
                body=json.dumps({
                    **_e2_plan_payload(),
                    **(body if isinstance(body, dict) else {}),
                    "id": 10,
                }, ensure_ascii=False),
            )
            return
        if path == "/api/local-plan-templates/71" and method == "DELETE":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    **_e2_plan_payload(),
                    "id": 71,
                    "name": "可删除方案",
                    "is_active": False,
                }, ensure_ascii=False),
            )
            return
        if path == "/api/local-plan-templates/9":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(_e2_plan_payload(), ensure_ascii=False),
            )
            return
        if path == "/api/plan-snapshots/preview":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(_e2_snapshot(frozen=False, execution_released=execution_released), ensure_ascii=False),
            )
            return
        if path == "/api/plan-snapshots":
            route.fulfill(
                status=201,
                content_type="application/json",
                body=json.dumps(_e2_snapshot(frozen=True, execution_released=execution_released), ensure_ascii=False),
            )
            return
        if path == "/api/tasks/17" and method == "GET":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "id": 17,
                    "name": "E2 atomic draft",
                    "status": (
                        "running" if approval_state["dispatched"] else "draft"
                    ),
                    "mode": "batch_draft_save",
                    "publish_scene": "SMT_SEMI_MANAGED_SAVE_ONLY",
                    "total_jobs": 3,
                    "completed_jobs": 0,
                    "failed_jobs": 0,
                    "payload": {"runner_released": execution_released},
                }, ensure_ascii=False),
            )
            return
        if path == "/api/tasks/17/approve-and-start" and method == "POST":
            approval_state["dispatched"] = True
            route.fulfill(
                status=503 if approval_response_lost else 200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "detail": "simulated response loss",
                    }
                    if approval_response_lost
                    else {
                        "ok": True,
                        "taskId": 17,
                        "status": "running",
                        "authorizationConsumed": True,
                    },
                    ensure_ascii=False,
                ),
            )
            return
        route.fulfill(
            status=404,
            content_type="application/json",
            body='{"detail":"unexpected E2 browser route"}',
        )

    page.route("**/api/**", handle)


