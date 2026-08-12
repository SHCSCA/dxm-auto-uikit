import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from src import db
from src.execution.browser_agent_protocol import canonical_mutation_target_payload
from src.execution.v1_runner import V1TaskRunner
from src.main import app
from src.repository import Repository


class _TrustedE2ReaderSource:
    def __init__(self):
        self.calls = []
        self.browser_session_id = "browser-e2-a"
        self.account_ref = "account-e2-a"
        self.template_revision = "v1"
        self.omitted_template_ids = set()
        self.extra_template_records = []
        self.schemas = _schemas()
        self.products = [
            {
                "idStr": "70001",
                "shopId": "3001",
                "subject": "Existing Car Phone Holder",
                "material": "ABS",
                "aeopAeProductSKUs": json.dumps(
                    [
                        {
                            "skuCode": "SKU-70001",
                            "skuPrice": "9.99",
                            "cargoPrice": "8.00",
                            "ipmSkuStock": "12",
                        }
                    ]
                ),
                "imageURLs": (
                    "https://img.example.test/70001-1.jpg;"
                    "https://img.example.test/70001-2.jpg"
                ),
                "productPrice": 9.99,
                "productMinPrice": 9.99,
                "productMaxPrice": 9.99,
                "aeopAeProductPropertys": json.dumps(
                    [
                        {"attrNameId": 5301, "attrValueId": 7301},
                        {"attrNameId": "5301", "attrValueId": "7302"},
                        {
                            "attrName": "Custom material note",
                            "customValue": "Matte",
                        },
                    ]
                ),
                "categoryId": "100",
                "dxmState": "draft",
                "sourceUrl": "https://detail.1688.com/offer/70001.html",
            },
            {
                "idStr": "70002",
                "shopId": "3001",
                "subject": "Existing Wireless Charger",
                "categoryId": "200",
                "dxmState": "draft",
                "sourceUrl": "https://detail.1688.com/offer/70002.html",
            },
            {
                "idStr": "70003",
                "shopId": "3001",
                "subject": "Existing Metal Phone Holder",
                "categoryId": "100",
                "dxmState": "draft",
                "sourceUrl": "https://detail.1688.com/offer/70003.html",
            },
        ]

    def read_draft_shops(self):
        self.calls.append(("read_draft_shops",))
        return {
            "browser_session_id": self.browser_session_id,
            "account_ref": self.account_ref,
            "payload": {
                "code": 0,
                "data": {
                    "userId": "42",
                    "shopMap": {
                        "3001": {
                            "idStr": "3001",
                            "name": "E2 测试店铺",
                            "platform": "smt",
                        }
                    },
                    "shopSmtTypeMap": {"3001": "POP"},
                },
            },
        }

    def read_e2_product_details(self, *, shop_id, product_ids):
        self.calls.append(
            ("read_e2_product_details", shop_id, tuple(product_ids))
        )
        assert shop_id == "3001"
        by_id = {item["idStr"]: item for item in self.products}
        return {
            "browser_session_id": self.browser_session_id,
            "account_ref": self.account_ref,
            "payload": {
                "products": [by_id[product_id] for product_id in product_ids],
            },
        }

    def read_draft_page(self, *, shop_id, page_no, page_size):
        self.calls.append(("read_draft_page", shop_id, page_no, page_size))
        assert shop_id == "3001"
        assert page_no == 1
        assert page_size == 100
        return {
            "browser_session_id": self.browser_session_id,
            "account_ref": self.account_ref,
            "payload": {
                "code": 0,
                "data": {
                    "page": {
                        "pageNo": 1,
                        "pageSize": 100,
                        "totalPage": 1,
                        "totalSize": len(self.products),
                        "list": self.products,
                    }
                },
            },
        }

    def read_e2_plan_scope(self, *, shop_id, category_ids):
        self.calls.append(("read_e2_plan_scope", shop_id, tuple(category_ids)))
        template_records = [
            {
                "ref_type": "freight",
                "dxm_template_id": "901",
                "shop_id": shop_id,
                "category_id": None,
                "observed_display_name": "默认运费模板",
                "source_api": "/api/smtShopInfoSync/list.json",
                "availability": "available",
                "source_record": {"revision": self.template_revision},
                "resolved_values": {},
            },
            {
                "ref_type": "attribute",
                "dxm_template_id": "902",
                "shop_id": shop_id,
                "category_id": category_ids[0],
                "observed_display_name": "车载属性模板",
                "source_api": "/api/smtAttributeTemplate/getTemplateListByCategory.json",
                "availability": "available",
                "source_record": {
                    "revision": self.template_revision,
                    "material": "Metal",
                },
                "resolved_values": {"material": "Metal"},
                "audit_items": [
                    {
                        "kind": "unmapped_custom_attribute",
                        "executable": False,
                        "source_index": 2,
                        "attr_name": "Custom finish",
                        "attr_value": "Brushed",
                        "reason_code": "DXM_TEMPLATE_ATTRIBUTE_ID_UNMAPPED",
                    }
                ],
            },
            {
                "ref_type": "attribute",
                "dxm_template_id": "903",
                "shop_id": shop_id,
                "category_id": category_ids[1],
                "observed_display_name": "充电器属性模板",
                "source_api": "/api/smtAttributeTemplate/getTemplateListByCategory.json",
                "availability": "available",
                "source_record": {"revision": self.template_revision},
                "resolved_values": {},
            },
        ]
        if len(category_ids) >= 3:
            template_records.append(
                {
                    "ref_type": "attribute",
                    "dxm_template_id": "904",
                    "shop_id": shop_id,
                    "category_id": category_ids[2],
                    "observed_display_name": "第三类目属性模板",
                    "source_api": "/api/smtAttributeTemplate/getTemplateListByCategory.json",
                    "availability": "available",
                    "source_record": {"revision": self.template_revision},
                    "resolved_values": {},
                }
            )
        template_records.extend(self.extra_template_records)
        return {
            "browser_session_id": self.browser_session_id,
            "account_ref": self.account_ref,
            "payload": {
                "template_records": [
                    record
                    for record in template_records
                    if record["dxm_template_id"] not in self.omitted_template_ids
                ],
                "category_schemas": {
                    category_id: self.schemas[index]
                    for index, category_id in enumerate(category_ids)
                },
            },
        }


def _sha256(value):
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest().upper()


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "e2-plan.db")
    db.init_db()
    import src.main as main

    repository = Repository()
    monkeypatch.setattr(main, "repo", repository)
    source = _TrustedE2ReaderSource()
    monkeypatch.setattr(main, "workflow_adapter", source)
    return TestClient(app), repository, source


def test_dxm_template_ref_sync_accepts_only_scope_and_reads_trusted_browser(
    tmp_path,
    monkeypatch,
):
    client, _repository, source = _setup(tmp_path, monkeypatch)
    import src.main as main

    monkeypatch.setattr(main, "workflow_adapter", source)

    spoofed = client.post(
        "/api/dxm-template-refs/sync",
        json={
            "records": [
                {
                    "ref_type": "freight",
                    "dxm_template_id": "999",
                    "shop_id": "3001",
                    "category_id": None,
                    "observed_display_name": "伪造模板",
                    "source_api": "caller.supplied",
                    "availability": "available",
                    "source_digest": "F" * 64,
                }
            ]
        },
    )
    assert spoofed.status_code == 422
    assert source.calls == []

    synced = client.post(
        "/api/dxm-template-refs/sync",
        json={"shop_id": "3001", "category_ids": ["100", "200"]},
    )
    assert synced.status_code == 201
    body = synced.json()
    assert body["source"] == "api"
    assert body["session_bound"] is True
    assert len(body["session_ref"]) == 16
    assert body["shop_id"] == "3001"
    assert body["category_ids"] == ["100", "200"]
    assert [item["dxm_template_id"] for item in body["refs"]] == ["901", "902", "903"]
    assert all(len(item["source_digest"]) == 64 for item in body["refs"])
    assert all(item["source_digest"] != "F" * 64 for item in body["refs"])
    ref_by_template = {
        item["dxm_template_id"]: item
        for item in body["refs"]
    }
    assert ref_by_template["902"]["audit_item_count"] == 1
    assert len(ref_by_template["902"]["audit_items_hash"]) == 64
    assert ref_by_template["901"]["audit_item_count"] == 0
    assert source.calls == [("read_e2_plan_scope", "3001", ("100", "200"))]


def test_dxm_template_ref_sync_marks_disappeared_scope_records_missing(
    tmp_path,
    monkeypatch,
):
    client, _repository, source = _setup(tmp_path, monkeypatch)
    refs = _sync_refs(client)
    by_template_id = {item["dxm_template_id"]: item for item in refs}
    assert by_template_id["902"]["availability"] == "available"

    source.omitted_template_ids.add("902")
    synced = client.post(
        "/api/dxm-template-refs/sync",
        json={"shop_id": "3001", "category_ids": ["100", "200"]},
    )
    assert synced.status_code == 201
    assert {item["dxm_template_id"] for item in synced.json()["refs"]} == {
        "901",
        "903",
    }

    listed = client.get("/api/dxm-template-refs").json()
    refreshed = {item["dxm_template_id"]: item for item in listed}
    assert refreshed["902"]["availability"] == "missing"
    assert refreshed["901"]["availability"] == "available"
    assert refreshed["903"]["availability"] == "available"


def _schemas():
    first = {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "minLength": 8,
                "natural_language": True,
                "ui_binding": "dxm_editor:title",
            },
            "material": {
                "type": "string",
                "enum": ["ABS", "Metal"],
                "ui_binding": "dxm_attribute:1001",
            },
            "aeopAeProductSKUs": {
                "type": "array",
                "ui_binding": "dxm_editor:aeopAeProductSKUs",
                "items": {
                    "type": "object",
                    "properties": {
                        "skuCode": {"type": "string"},
                        "skuPrice": {"type": "string"},
                        "cargoPrice": {"type": "string"},
                        "ipmSkuStock": {
                            "type": "integer",
                            "minimum": 0,
                        },
                    },
                    "required": ["skuCode", "skuPrice", "ipmSkuStock"],
                },
            },
            "imageURLs": {
                "type": "array",
                "wire_format": "semicolon_delimited",
                "items": {
                    "type": "string",
                    "pattern": "^https?://",
                },
                "ui_binding": "dxm_editor:imageURLs",
            },
            "productPrice": {
                "type": "number",
                "minimum": 0,
                "ui_binding": "dxm_editor:productPrice",
            },
            "productMinPrice": {
                "type": "number",
                "minimum": 0,
                "ui_binding": "dxm_editor:productMinPrice",
            },
            "productMaxPrice": {
                "type": "number",
                "minimum": 0,
                "ui_binding": "dxm_editor:productMaxPrice",
            },
            "attr_5301": {
                "type": "array",
                "items": {"type": "string"},
                "ui_binding": "dxm_attribute:5301",
            },
        },
        "required": ["title", "material"],
        "price_policy": {
            "sku_cargo_not_above_sale": True,
            "sku_prices_within_range": True,
        },
    }
    second = {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "minLength": 8,
                "natural_language": True,
                "ui_binding": "dxm_editor:title",
            },
            "power_watts": {
                "type": "number",
                "minimum": 1,
                "ui_binding": "dxm_attribute:2001",
            },
        },
        "required": ["title", "power_watts"],
    }
    third = {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "minLength": 8,
                "natural_language": True,
                "ui_binding": "dxm_editor:title",
            },
            "voltage": {
                "type": "number",
                "minimum": 1,
                "ui_binding": "dxm_attribute:3001",
            },
        },
        "required": ["title", "voltage"],
    }
    return first, second, third


def _mapping(version, fields):
    labels = {
        "title": "英文标题",
        "material": "材质",
        "power_watts": "功率瓦数",
        "battery_included": "是否含电池",
        "battery_type": "电池类型",
        "warranty": "保修信息",
        "compliance": "合规信息",
        "voltage": "电压",
        "aeopAeProductSKUs": "SKU 当前值",
    }
    bindings = {
        "title": "dxm_editor:title",
        "material": "dxm_attribute:1001",
        "power_watts": "dxm_attribute:2001",
        "battery_included": "dxm_attribute:1101",
        "battery_type": "dxm_attribute:1102",
        "warranty": "dxm_attribute:1104",
        "compliance": "dxm_attribute:1103",
        "voltage": "dxm_attribute:3001",
        "aeopAeProductSKUs": "dxm_editor:aeopAeProductSKUs",
    }
    return {
        "mapping_version": version,
        "entries": [
            {
                "ui_label_zh": labels[field],
                "field_key": field,
                "category_schema_path": f"$.properties.{field}",
                "ui_binding": bindings[field],
            }
            for field in fields
        ],
    }


def _sync_refs(client):
    response = client.post(
        "/api/dxm-template-refs/sync",
        json={"shop_id": "3001", "category_ids": ["100", "200"]},
    )
    assert response.status_code == 201
    return response.json()["refs"]


def _plan_payload(refs, *, version="1.0.0", first_title="Car Phone Holder"):
    ref_by_template_id = {item["dxm_template_id"]: item for item in refs}
    return {
        "name": "普货英语补差方案",
        "version": version,
        "shop_id": "3001",
        "category_ids": ["100", "200"],
        "path": "A",
        "fixed_values": {
            "publish_allowed": False,
            "field_values": {
                "100": {},
                "200": {
                    "power_watts": 30,
                },
            },
        },
        "fill_rules": {
            "100": {
                "title": {"value": first_title},
                "material": {"value": "ABS"},
            },
            "200": {
                "title": {"value": "Wireless Fast Charger"},
                "power_watts": {"value": 20},
            },
        },
        "dxm_template_refs": [
            {
                "ref_id": item["id"],
                "source_digest": item["source_digest"],
            }
            for item in (
                ref_by_template_id["901"],
                ref_by_template_id["902"],
                ref_by_template_id["903"],
            )
        ],
        "field_mappings": {
            "100": _mapping(
                "zh-map-100-v1",
                ["title", "material", "aeopAeProductSKUs"],
            ),
            "200": _mapping("zh-map-200-v1", ["title", "power_watts"]),
        },
        "validation_policy": {
            "required_fields": "fail_closed",
            "natural_language": "english_before_save",
        },
        "exception_policy": {"unknown": "stop_batch"},
        "provenance": "operator_reviewed_local_plan",
    }


def _snapshot_request(plan_id, *, expected_snapshot_hash=None):
    request = {
        "local_plan_template_id": plan_id,
        "shop_id": "3001",
        "session_ref": hashlib.sha256(
            b"dxm-draft-reader:browser-e2-a:account-e2-a"
        ).hexdigest()[:16],
        "product_ids": ["70001", "70002", "70003"],
        "expected_snapshot_hash": expected_snapshot_hash,
    }
    if expected_snapshot_hash is not None:
        request["idempotency_key"] = (
            f"e2-freeze-{expected_snapshot_hash[:24].lower()}"
        )
    return request


def test_plan_snapshot_rejects_caller_schema_and_rereads_selected_drafts(
    tmp_path,
    monkeypatch,
):
    client, _repository, source = _setup(tmp_path, monkeypatch)
    refs = _sync_refs(client)
    plan = client.post("/api/local-plan-templates", json=_plan_payload(refs)).json()

    spoofed = client.post(
        "/api/plan-snapshots/preview",
        json={
            "local_plan_template_id": plan["id"],
            "shop_id": "3001",
            "items": [
                {
                    "product_id": "70001",
                    "shop_id": "3001",
                    "category_id": "100",
                    "category_schema": _schemas()[0],
                    "expected_schema_hash": _sha256(_schemas()[0]),
                    "current_values": {},
                }
            ]
            * 3,
        },
    )
    assert spoofed.status_code == 422

    source.calls = []
    preview = client.post(
        "/api/plan-snapshots/preview",
        json=_snapshot_request(plan["id"]),
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["product_ids"] == ["70001", "70002", "70003"]
    assert {
        item["categoryId"]
        for item in body["item_snapshots"]
    } == {"100", "200"}
    first_item = next(
        item
        for item in body["item_snapshots"]
        if item["product_id"] == "70001"
    )
    assert first_item["category_schema"]["normalized_schema"][
        "price_policy"
    ] == {
        "sku_cargo_not_above_sale": True,
        "sku_prices_within_range": True,
    }
    assert first_item["current_value_snapshot"]["aeopAeProductSKUs"] == [
        {
            "skuCode": "SKU-70001",
            "skuPrice": "9.99",
            "cargoPrice": "8.00",
            "ipmSkuStock": 12,
        }
    ]
    assert first_item["current_value_snapshot"]["imageURLs"] == [
        "https://img.example.test/70001-1.jpg",
        "https://img.example.test/70001-2.jpg",
    ]
    assert first_item["current_value_snapshot"]["attr_5301"] == [
        "7301",
        "7302",
    ]
    assert first_item["current_value_snapshot"][
        "__unmapped_custom_attributes__"
    ] == [
        {"name": "Custom material note", "value": "Matte"}
    ]
    assert source.calls.count(("read_draft_shops",)) >= 1
    assert ("read_draft_page", "3001", 1, 100) in source.calls
    assert (
        "read_e2_product_details",
        "3001",
        ("70001", "70002", "70003"),
    ) in source.calls
    assert source.calls[-1] == (
        "read_e2_plan_scope",
        "3001",
        ("100", "200"),
    )


@pytest.mark.parametrize(
    ("sku_stock", "image_urls"),
    [
        ("12.5", "https://img.example.test/a.jpg"),
        ("12", "https://img.example.test/a.jpg;;https://img.example.test/b.jpg"),
    ],
)
def test_plan_snapshot_rejects_ambiguous_editor_wire_values(
    tmp_path,
    monkeypatch,
    sku_stock,
    image_urls,
):
    client, _repository, source = _setup(tmp_path, monkeypatch)
    refs = _sync_refs(client)
    plan = client.post("/api/local-plan-templates", json=_plan_payload(refs)).json()
    source.products[0]["aeopAeProductSKUs"] = json.dumps(
        [
            {
                "skuCode": "SKU-70001",
                "skuPrice": "9.99",
                "ipmSkuStock": sku_stock,
            }
        ]
    )
    source.products[0]["imageURLs"] = image_urls

    preview = client.post(
        "/api/plan-snapshots/preview",
        json=_snapshot_request(plan["id"]),
    )

    assert preview.status_code == 409
    assert preview.json()["detail"]["reason_code"] == (
        "DXM_PRODUCT_DETAIL_RESPONSE_INVALID"
    )


def test_plan_snapshot_rejects_invalid_frozen_price_relationship(
    tmp_path,
    monkeypatch,
):
    client, _repository, source = _setup(tmp_path, monkeypatch)
    refs = _sync_refs(client)
    plan = client.post("/api/local-plan-templates", json=_plan_payload(refs)).json()
    source.products[0]["aeopAeProductSKUs"] = json.dumps(
        [
            {
                "skuCode": "SKU-70001",
                "skuPrice": "9.99",
                "cargoPrice": "10.50",
                "ipmSkuStock": "12",
            }
        ]
    )

    preview = client.post(
        "/api/plan-snapshots/preview",
        json=_snapshot_request(plan["id"]),
    )

    assert preview.status_code == 409
    assert preview.json()["detail"]["reason_code"] == (
        "PLAN_PRICE_RELATION_INVALID"
    )


def test_plan_snapshot_does_not_compare_independent_product_price_to_sku_range(
    tmp_path,
    monkeypatch,
):
    client, _repository, source = _setup(tmp_path, monkeypatch)
    refs = _sync_refs(client)
    plan = client.post("/api/local-plan-templates", json=_plan_payload(refs)).json()
    source.products[0]["productMinPrice"] = 9.99
    source.products[0]["productMaxPrice"] = 9.99
    source.products[0]["productPrice"] = 19.99

    preview = client.post(
        "/api/plan-snapshots/preview",
        json=_snapshot_request(plan["id"]),
    )

    assert preview.status_code == 200, preview.text
    first_item = next(
        item
        for item in preview.json()["item_snapshots"]
        if item["product_id"] == "70001"
    )
    current_rules = first_item["resolution_result"]["price_validation"][
        "current_values"
    ]["checked_rules"]
    assert "productMinPrice<=each.skuPrice<=productMaxPrice" in current_rules
    assert "productMinPrice<=productPrice<=productMaxPrice" not in current_rules


def test_e2_models_are_separate_and_plan_versions_are_immutable(tmp_path, monkeypatch):
    client, _repository, _source = _setup(tmp_path, monkeypatch)
    refs = _sync_refs(client)

    listed_refs = client.get("/api/dxm-template-refs")
    assert listed_refs.status_code == 200
    assert listed_refs.json() == refs
    assert client.patch(f"/api/dxm-template-refs/{refs[0]['id']}", json={"observed_display_name": "禁止修改"}).status_code == 405

    created = client.post("/api/local-plan-templates", json=_plan_payload(refs))
    assert created.status_code == 201
    plan_v1 = created.json()
    assert plan_v1["model"] == "local_plan_template"
    assert plan_v1["version"] == "1.0.0"
    assert all(item["model"] == "dxm_template_ref" for item in refs)

    mutation = client.patch(
        f"/api/local-plan-templates/{plan_v1['id']}",
        json={"name": "不得原地修改"},
    )
    assert mutation.status_code == 409
    assert mutation.json()["detail"]["reason_code"] == "LOCAL_PLAN_VERSION_IMMUTABLE"

    next_version = client.post(
        f"/api/local-plan-templates/{plan_v1['id']}/versions",
        json=_plan_payload(refs, version="1.1.0", first_title="Upgraded Car Phone Holder"),
    )
    assert next_version.status_code == 201
    plan_v2 = next_version.json()
    assert plan_v2["lineage_id"] == plan_v1["lineage_id"]
    assert plan_v2["supersedes_id"] == plan_v1["id"]
    assert plan_v2["id"] != plan_v1["id"]
    assert client.get(f"/api/local-plan-templates/{plan_v1['id']}").json()["fill_rules"]["100"]["title"]["value"] == "Car Phone Holder"

    archived = client.delete(f"/api/local-plan-templates/{plan_v1['id']}")
    assert archived.status_code == 200
    assert archived.json()["is_active"] is False
    assert archived.json()["fill_rules"]["100"]["title"]["value"] == "Car Phone Holder"
    assert client.get(f"/api/local-plan-templates/{plan_v1['id']}").json()["is_active"] is False
    archived_preview = client.post(
        "/api/plan-snapshots/preview",
        json=_snapshot_request(plan_v1["id"]),
    )
    assert archived_preview.status_code == 409
    assert archived_preview.json()["detail"]["reason_code"] == (
        "LOCAL_PLAN_ARCHIVED"
    )


def test_e2_freezes_multi_category_snapshot_and_task_payload(tmp_path, monkeypatch):
    client, _repository, _source = _setup(tmp_path, monkeypatch)
    refs = _sync_refs(client)
    plan_v1 = client.post("/api/local-plan-templates", json=_plan_payload(refs)).json()
    request = _snapshot_request(plan_v1["id"])

    preview = client.post("/api/plan-snapshots/preview", json=request)
    assert preview.status_code == 200
    preview_snapshot = preview.json()
    assert preview_snapshot["schema"] == "dxm_batch_draft_save_plan.v1"
    assert preview_snapshot["mode"] == "batch_draft_save"
    assert preview_snapshot["path"] == "A"
    assert preview_snapshot["publish_allowed"] is False
    assert preview_snapshot["fixed_values"] == {
        "publish_allowed": False,
        "field_values": {
            "100": {},
            "200": {"power_watts": 30},
        },
    }
    assert preview_snapshot["session_context"] == {
        "session_ref": _snapshot_request(plan_v1["id"])["session_ref"],
        "account_ref_hash": hashlib.sha256(
            b"dxm-e2-account-context:account-e2-a"
        ).hexdigest().upper(),
        "shop_id": "3001",
        "shop_name": "E2 测试店铺",
    }
    assert preview_snapshot["approval_context"] == {
        "state": "not_granted",
        "runner_released": False,
        "publish_allowed": False,
    }
    assert preview_snapshot["failure_policy"] == {"unknown": "stop_batch"}
    assert preview_snapshot["product_ids"] == ["70001", "70002", "70003"]
    assert len(preview_snapshot["item_snapshots"]) == 3
    assert preview_snapshot["snapshot_hash"] == _sha256(
        {key: value for key, value in preview_snapshot.items() if key != "snapshot_hash"}
    )

    by_product = {item["product_id"]: item for item in preview_snapshot["item_snapshots"]}
    for product_id, item in by_product.items():
        target = item["target_identity"]
        assert canonical_mutation_target_payload(
            "save_only",
            {
                "store_name": "E2 测试店铺",
                "target_identity": target,
            },
        )["target_identity"] == target
        assert target["stable_identity"]["value"] == product_id
    assert by_product["70001"]["categoryId"] == "100"
    assert by_product["70002"]["categoryId"] == "200"
    assert by_product["70001"]["category_schema"]["schema_hash"] != by_product["70002"]["category_schema"]["schema_hash"]
    assert by_product["70001"]["field_mapping"]["mapping_hash"] != by_product["70002"]["field_mapping"]["mapping_hash"]
    product_three_fields = {
        field["field_key"]: field
        for field in by_product["70003"]["resolution_result"]["resolved_fields"]
    }
    assert product_three_fields["title"]["source"] == "local_plan_template"
    assert product_three_fields["material"]["source"] == "local_plan_template"
    assert product_three_fields["material"]["resolved_value"] == "ABS"
    product_one_fields = {
        field["field_key"]: field
        for field in by_product["70001"]["resolution_result"]["resolved_fields"]
    }
    assert product_one_fields["material"]["source"] == "local_plan_template"
    assert product_one_fields["material"]["resolved_value"] == "ABS"
    product_two_fields = {
        field["field_key"]: field
        for field in by_product["70002"]["resolution_result"]["resolved_fields"]
    }
    assert product_two_fields["power_watts"]["source"] == "fixed_value"
    assert product_two_fields["power_watts"]["resolved_value"] == 30
    for item in preview_snapshot["item_snapshots"]:
        assert item["category_schema"]["schema_hash"] == _sha256(item["category_schema"]["normalized_schema"])
        assert item["field_mapping"]["mapping_hash"] == _sha256(
            {
                "mapping_version": item["field_mapping"]["mapping_version"],
                "entries": item["field_mapping"]["entries"],
            }
        )
        natural = [
            field
            for field in item["resolution_result"]["resolved_fields"]
            if field["natural_language"]
        ]
        assert natural
        assert all(field["expected_language"] == "en" and field["detected_language"] == "en" for field in natural)

    frozen = client.post(
        "/api/plan-snapshots",
        json=_snapshot_request(
            plan_v1["id"],
            expected_snapshot_hash=preview_snapshot["snapshot_hash"],
        ),
    )
    assert frozen.status_code == 201
    stored = frozen.json()
    assert stored["snapshot_hash"] == preview_snapshot["snapshot_hash"]
    assert isinstance(stored["task_id"], int)

    retried = client.post(
        "/api/plan-snapshots",
        json=_snapshot_request(
            plan_v1["id"],
            expected_snapshot_hash=preview_snapshot["snapshot_hash"],
        ),
    )
    assert retried.status_code == 201
    assert retried.json()["id"] == stored["id"]
    assert retried.json()["task_id"] == stored["task_id"]
    assert len(client.get("/api/tasks").json()) == 1

    task = client.post(f"/api/plan-snapshots/{stored['id']}/tasks")
    assert task.status_code == 201
    created_task = task.json()
    assert created_task["id"] == stored["task_id"]
    assert created_task["mode"] == "batch_draft_save"
    assert created_task["status"] == "draft"
    assert created_task["payload"]["plan_snapshot"]["snapshot_hash"] == stored["snapshot_hash"]
    assert created_task["payload"]["plan_snapshot"]["item_snapshots"] == stored["item_snapshots"]
    private_task = _repository.get_task_private(created_task["id"])
    frozen_runner = V1TaskRunner(_repository, manager=None)
    runner_target = frozen_runner._frozen_batch_draft_target_identity(
        private_task,
        private_task["jobs"][0],
    )
    assert runner_target == stored["item_snapshots"][0]["target_identity"]
    execution_payload = frozen_runner._execution_defaults(
        private_task,
        None,
        job=private_task["jobs"][0],
    )["_frozen_execution_payload"]
    assert [field["field_key"] for field in execution_payload["fields"]] == [
        "title",
        "material",
        "aeopAeProductSKUs",
    ]
    assert [field["ui_binding"] for field in execution_payload["fields"]] == [
        "dxm_editor:title",
        "dxm_attribute:1001",
        "dxm_editor:aeopAeProductSKUs",
    ]

    plan_v2 = client.post(
        f"/api/local-plan-templates/{plan_v1['id']}/versions",
        json=_plan_payload(refs, version="1.1.0", first_title="Changed After Task"),
    )
    assert plan_v2.status_code == 201
    reloaded_task = client.get(f"/api/tasks/{created_task['id']}").json()
    assert reloaded_task["payload"]["plan_snapshot"]["local_plan_template"] == {
        "id": plan_v1["id"],
        "version": "1.0.0",
    }
    assert reloaded_task["payload"]["plan_snapshot"]["snapshot_hash"] == stored["snapshot_hash"]

    start = client.post(f"/api/tasks/{created_task['id']}/start", json={})
    assert start.status_code in {400, 403}


def test_operator_configured_values_override_template_and_current_values(
    tmp_path,
    monkeypatch,
):
    client, _repository, _source = _setup(tmp_path, monkeypatch)
    refs = _sync_refs(client)
    payload = _plan_payload(
        refs,
        version="1.0.1",
        first_title="Configured English Product Title",
    )
    payload["fill_rules"]["100"]["material"] = {"value": "Metal"}
    created = client.post("/api/local-plan-templates", json=payload)
    assert created.status_code == 201, created.text

    preview = client.post(
        "/api/plan-snapshots/preview",
        json=_snapshot_request(created.json()["id"]),
    )
    assert preview.status_code == 200, preview.text
    by_product = {
        item["product_id"]: {
            field["field_key"]: field
            for field in item["resolution_result"]["resolved_fields"]
        }
        for item in preview.json()["item_snapshots"]
    }

    assert by_product["70001"]["title"]["source"] == "local_plan_template"
    assert by_product["70001"]["title"]["resolved_value"] == (
        "Configured English Product Title"
    )
    assert by_product["70001"]["material"]["source"] == "local_plan_template"
    assert by_product["70001"]["material"]["resolved_value"] == "Metal"
    assert by_product["70003"]["material"]["source"] == "local_plan_template"
    assert by_product["70003"]["material"]["resolved_value"] == "Metal"


@pytest.mark.parametrize(
    ("template_category_id", "expected_status"),
    [("100", 409), ("200", 200)],
)
def test_template_value_conflict_is_isolated_to_its_category(
    tmp_path,
    monkeypatch,
    template_category_id,
    expected_status,
):
    client, _repository, source = _setup(tmp_path, monkeypatch)
    source.extra_template_records.append(
        {
            "ref_type": "attribute",
            "dxm_template_id": "905",
            "shop_id": "3001",
            "category_id": template_category_id,
            "observed_display_name": "冲突隔离模板",
            "source_api": "/api/smtAttributeTemplate/getTemplateListByCategory.json",
            "availability": "available",
            "source_record": {"revision": "conflict", "material": "Polycarbonate"},
            "resolved_values": {"material": "Polycarbonate"},
        }
    )
    refs = _sync_refs(client)
    payload = _plan_payload(refs)
    extra_ref = next(
        item for item in refs if item["dxm_template_id"] == "905"
    )
    payload["dxm_template_refs"].append(
        {
            "ref_id": extra_ref["id"],
            "source_digest": extra_ref["source_digest"],
        }
    )
    plan = client.post(
        "/api/local-plan-templates",
        json=payload,
    )
    assert plan.status_code == 201, plan.text

    preview = client.post(
        "/api/plan-snapshots/preview",
        json=_snapshot_request(plan.json()["id"]),
    )

    assert preview.status_code == expected_status, preview.text
    if expected_status == 409:
        assert preview.json()["detail"]["reason_code"] == (
            "DXM_TEMPLATE_VALUE_CONFLICT"
        )


def test_checkbox_single_current_value_is_frozen_as_schema_array(
    tmp_path,
    monkeypatch,
):
    client, _repository, source = _setup(tmp_path, monkeypatch)
    source.products[0]["aeopAeProductPropertys"] = json.dumps([
        {"attrNameId": 5301, "attrValueId": 7301},
        {"attrNameId": 400000603, "attrValueId": 400001001},
    ])
    source.schemas[0]["properties"]["attr_400000603"] = {
        "type": "array",
        "items": {"type": "string"},
        "minItems": 1,
        "ui_binding": "dxm_attribute:400000603",
    }
    refs = _sync_refs(client)
    payload = _plan_payload(refs, version="1.0.2")
    payload["field_mappings"]["100"]["entries"].append({
        "ui_label_zh": "复选属性",
        "field_key": "attr_400000603",
        "category_schema_path": "$.properties.attr_400000603",
        "ui_binding": "dxm_attribute:400000603",
    })
    created = client.post("/api/local-plan-templates", json=payload)
    assert created.status_code == 201, created.text

    preview = client.post(
        "/api/plan-snapshots/preview",
        json=_snapshot_request(created.json()["id"]),
    )

    assert preview.status_code == 200, preview.text
    product = next(
        item
        for item in preview.json()["item_snapshots"]
        if item["product_id"] == "70001"
    )
    assert product["current_value_snapshot"]["attr_400000603"] == [
        "400001001"
    ]
    resolved = {
        field["field_key"]: field
        for field in product["resolution_result"]["resolved_fields"]
    }
    assert resolved["attr_400000603"]["source"] == "current"
    assert resolved["attr_400000603"]["resolved_value"] == ["400001001"]


def test_e2_snapshot_and_task_roll_back_as_one_transaction(
    tmp_path,
    monkeypatch,
):
    client, _repository, _source = _setup(tmp_path, monkeypatch)
    refs = _sync_refs(client)
    plan = client.post(
        "/api/local-plan-templates",
        json=_plan_payload(refs),
    ).json()
    preview = client.post(
        "/api/plan-snapshots/preview",
        json=_snapshot_request(plan["id"]),
    ).json()
    with db.connection() as conn:
        conn.execute(
            """
            CREATE TRIGGER force_e2_task_insert_failure
            BEFORE INSERT ON tasks
            WHEN NEW.mode='batch_draft_save'
            BEGIN
                SELECT RAISE(ABORT, 'FORCED_E2_TASK_INSERT_FAILURE');
            END
            """
        )

    response = TestClient(app, raise_server_exceptions=False).post(
        "/api/plan-snapshots",
        json=_snapshot_request(
            plan["id"],
            expected_snapshot_hash=preview["snapshot_hash"],
        ),
    )

    assert response.status_code == 500
    with db.connection() as conn:
        assert conn.execute(
            "SELECT COUNT(*) AS count FROM plan_snapshots"
        ).fetchone()["count"] == 0
        assert conn.execute(
            "SELECT COUNT(*) AS count FROM tasks WHERE mode='batch_draft_save'"
        ).fetchone()["count"] == 0


def test_e2_successful_snapshot_alias_key_is_permanently_bound(
    tmp_path,
    monkeypatch,
):
    client, _repository, _source = _setup(tmp_path, monkeypatch)
    refs = _sync_refs(client)
    plan_v1 = client.post(
        "/api/local-plan-templates",
        json=_plan_payload(refs),
    ).json()
    preview_v1 = client.post(
        "/api/plan-snapshots/preview",
        json=_snapshot_request(plan_v1["id"]),
    ).json()
    primary_request = _snapshot_request(
        plan_v1["id"],
        expected_snapshot_hash=preview_v1["snapshot_hash"],
    )
    primary = client.post("/api/plan-snapshots", json=primary_request)
    assert primary.status_code == 201

    alias_key = "e2-freeze-alias-key-00000001"
    alias_request = {
        **primary_request,
        "idempotency_key": alias_key,
    }
    alias = client.post("/api/plan-snapshots", json=alias_request)
    assert alias.status_code == 201
    assert alias.json()["id"] == primary.json()["id"]

    plan_v2 = client.post(
        f"/api/local-plan-templates/{plan_v1['id']}/versions",
        json=_plan_payload(
            refs,
            version="1.1.0",
            first_title="Changed Snapshot Title",
        ),
    ).json()
    preview_v2 = client.post(
        "/api/plan-snapshots/preview",
        json=_snapshot_request(plan_v2["id"]),
    ).json()
    conflict = client.post(
        "/api/plan-snapshots",
        json={
            **_snapshot_request(
                plan_v2["id"],
                expected_snapshot_hash=preview_v2["snapshot_hash"],
            ),
            "idempotency_key": alias_key,
        },
    )

    assert conflict.status_code == 409
    assert conflict.json()["detail"]["reason_code"] == (
        "PLAN_SNAPSHOT_IDEMPOTENCY_CONFLICT"
    )


def test_e2_three_category_snapshot_matrix_is_isolated_per_product(
    tmp_path,
    monkeypatch,
):
    client, _repository, source = _setup(tmp_path, monkeypatch)
    category_ids = ["201273776", "2621", "201898401"]
    source.products[0]["categoryId"] = category_ids[0]
    source.products[1]["categoryId"] = category_ids[1]
    source.products[2].update({
        "categoryId": category_ids[2],
        "voltage": 110,
    })
    sync = client.post(
        "/api/dxm-template-refs/sync",
        json={
            "shop_id": "3001",
            "category_ids": category_ids,
        },
    )
    assert sync.status_code == 201
    refs = sync.json()["refs"]
    payload = _plan_payload(refs, version="1.2.0")
    payload["category_ids"] = category_ids
    payload["fixed_values"]["field_values"] = {
        category_ids[0]: {},
        category_ids[1]: {"power_watts": 30},
        category_ids[2]: {},
    }
    payload["fill_rules"] = {
        category_ids[0]: payload["fill_rules"]["100"],
        category_ids[1]: payload["fill_rules"]["200"],
        category_ids[2]: {
            "title": {"value": "Portable Voltage Converter"},
            "voltage": {"value": 220},
        },
    }
    payload["field_mappings"] = {
        category_ids[0]: payload["field_mappings"]["100"],
        category_ids[1]: payload["field_mappings"]["200"],
        category_ids[2]: _mapping(
            "zh-map-201898401-v1",
            ["title", "voltage"],
        ),
    }
    payload["dxm_template_refs"] = [
        {
            "ref_id": ref["id"],
            "source_digest": ref["source_digest"],
        }
        for ref in refs
    ]
    plan = client.post("/api/local-plan-templates", json=payload)
    assert plan.status_code == 201

    preview = client.post(
        "/api/plan-snapshots/preview",
        json=_snapshot_request(plan.json()["id"]),
    )

    assert preview.status_code == 200
    items = preview.json()["item_snapshots"]
    assert [item["categoryId"] for item in items] == category_ids
    assert len({
        item["category_schema"]["schema_hash"]
        for item in items
    }) == 3
    assert len({
        item["field_mapping"]["mapping_hash"]
        for item in items
    }) == 3
    third_fields = {
        field["field_key"]: field
        for field in items[2]["resolution_result"]["resolved_fields"]
    }
    assert third_fields["voltage"]["source"] == "local_plan_template"
    assert third_fields["voltage"]["resolved_value"] == 220
    assert all(
        field["field_key"] != "material"
        for field in items[2]["resolution_result"]["resolved_fields"]
    )


def test_e2_snapshot_fail_closed_on_drift_scope_required_and_language(tmp_path, monkeypatch):
    client, _repository, source = _setup(tmp_path, monkeypatch)
    refs = _sync_refs(client)
    plan = client.post("/api/local-plan-templates", json=_plan_payload(refs)).json()

    preview = client.post(
        "/api/plan-snapshots/preview",
        json=_snapshot_request(plan["id"]),
    ).json()
    source.schemas[0]["properties"]["title"]["maxLength"] = 200
    response = client.post(
        "/api/plan-snapshots",
        json=_snapshot_request(
            plan["id"],
            expected_snapshot_hash=preview["snapshot_hash"],
        ),
    )
    assert response.status_code == 409
    assert response.json()["detail"]["reason_code"] == "PLAN_SNAPSHOT_PREVIEW_DRIFT"
    source.schemas = _schemas()

    source.browser_session_id = "browser-e2-b"
    response = client.post(
        "/api/plan-snapshots/preview",
        json=_snapshot_request(plan["id"]),
    )
    assert response.status_code == 409
    assert response.json()["detail"]["reason_code"] == "DXM_PLAN_SESSION_MISMATCH"
    source.browser_session_id = "browser-e2-a"

    removed_product = source.products.pop()
    response = client.post(
        "/api/plan-snapshots/preview",
        json=_snapshot_request(plan["id"]),
    )
    assert response.status_code == 409
    assert response.json()["detail"]["reason_code"] == "PLAN_PRODUCT_NOT_IN_CURRENT_READER"
    source.products.append(removed_product)

    wrong_scope = _snapshot_request(plan["id"])
    wrong_scope["shop_id"] = "9999"
    response = client.post("/api/plan-snapshots/preview", json=wrong_scope)
    assert response.status_code == 409
    assert response.json()["detail"]["reason_code"] == "PLAN_SCOPE_CONFLICT"

    missing_plan = _plan_payload(refs, version="2.0.0")
    del missing_plan["fill_rules"]["200"]["power_watts"]
    del missing_plan["fixed_values"]["field_values"]["200"]["power_watts"]
    missing = client.post("/api/local-plan-templates", json=missing_plan).json()
    response = client.post(
        "/api/plan-snapshots/preview",
        json=_snapshot_request(missing["id"]),
    )
    assert response.status_code == 409
    assert response.json()["detail"]["reason_code"] == "PLAN_REQUIRED_FIELD_UNRESOLVED"

    short_title = client.post(
        "/api/local-plan-templates",
        json=_plan_payload(refs, version="2.1.0", first_title="Short"),
    ).json()
    response = client.post(
        "/api/plan-snapshots/preview",
        json=_snapshot_request(short_title["id"]),
    )
    assert response.status_code == 409
    assert response.json()["detail"]["reason_code"] == "PLAN_FIELD_SCHEMA_INVALID"

    chinese = client.post(
        "/api/local-plan-templates",
        json=_plan_payload(refs, version="3.0.0", first_title="这是一个中文商品标题"),
    ).json()
    source.products[0]["subject"] = ""
    response = client.post(
        "/api/plan-snapshots/preview",
        json=_snapshot_request(chinese["id"]),
    )
    assert response.status_code == 409
    assert response.json()["detail"]["reason_code"] == "NATURAL_LANGUAGE_ENGLISH_REQUIRED"
    source.products[0]["subject"] = "Existing Car Phone Holder"

    source.template_revision = "v2"
    response = client.post(
        "/api/plan-snapshots/preview",
        json=_snapshot_request(plan["id"]),
    )
    assert response.status_code == 409
    assert response.json()["detail"]["reason_code"] == "DXM_TEMPLATE_REF_DRIFT"


def test_e2_preview_rejects_required_schema_field_missing_from_mapping(
    tmp_path,
    monkeypatch,
):
    client, _repository, _source = _setup(tmp_path, monkeypatch)
    refs = _sync_refs(client)
    payload = _plan_payload(refs, version="4.0.0")
    payload["field_mappings"]["100"]["entries"] = [
        entry
        for entry in payload["field_mappings"]["100"]["entries"]
        if entry["field_key"] != "material"
    ]
    created = client.post("/api/local-plan-templates", json=payload)
    assert created.status_code == 201

    preview = client.post(
        "/api/plan-snapshots/preview",
        json=_snapshot_request(created.json()["id"]),
    )

    assert preview.status_code == 409
    assert (
        preview.json()["detail"]["reason_code"]
        == "PLAN_REQUIRED_FIELD_MAPPING_MISSING"
    )
    assert "material" in preview.json()["detail"]["message"]


def test_e2_preview_rejects_conditional_required_field_missing_from_mapping(
    tmp_path,
    monkeypatch,
):
    client, _repository, source = _setup(tmp_path, monkeypatch)
    source.schemas[0]["properties"].update(
        {
            "battery_included": {
                "type": "boolean",
                "ui_binding": "dxm_attribute:1101",
            },
            "battery_type": {
                "type": "string",
                "minLength": 2,
                "ui_binding": "dxm_attribute:1102",
            },
        }
    )
    source.schemas[0]["allOf"] = [
        {
            "if": {
                "properties": {
                    "battery_included": {"const": True},
                },
                "required": ["battery_included"],
            },
            "then": {"required": ["battery_type"]},
        }
    ]
    refs = _sync_refs(client)
    payload = _plan_payload(refs, version="4.1.0")
    payload["fill_rules"]["100"].update(
        {
            "battery_included": {"value": True},
            "battery_type": {"value": "AA"},
        }
    )
    payload["field_mappings"]["100"] = _mapping(
        "zh-map-100-v2",
        ["title", "material", "battery_included"],
    )
    plan = client.post("/api/local-plan-templates", json=payload)
    assert plan.status_code == 201

    preview = client.post(
        "/api/plan-snapshots/preview",
        json=_snapshot_request(plan.json()["id"]),
    )

    assert preview.status_code == 409
    assert (
        preview.json()["detail"]["reason_code"]
        == "PLAN_REQUIRED_FIELD_MAPPING_MISSING"
    )
    assert "battery_type" in preview.json()["detail"]["message"]


def test_e2_preview_activates_child_required_for_selected_checkbox_value(
    tmp_path,
    monkeypatch,
):
    client, _repository, source = _setup(tmp_path, monkeypatch)
    source.schemas[0]["properties"].update({
        "attr_5301": {
            "type": "array",
            "items": {"type": "string"},
            "ui_binding": "dxm_attribute:5301",
        },
        "attr_6301": {
            "type": "string",
            "minLength": 2,
            "ui_binding": "dxm_attribute:6301",
        },
    })
    source.schemas[0]["allOf"] = [
        {
            "if": {
                "properties": {
                    "attr_5301": {
                        "contains": {"const": "301"},
                    }
                },
                "required": ["attr_5301"],
            },
            "then": {"required": ["attr_6301"]},
        }
    ]
    refs = _sync_refs(client)
    payload = _plan_payload(refs, version="4.1.1")
    payload["fill_rules"]["100"].update({
        "attr_5301": {"value": ["301"]},
        "attr_6301": {"value": "Grade A"},
    })
    payload["field_mappings"]["100"]["entries"].extend([
        {
            "ui_label_zh": "材质",
            "field_key": "attr_5301",
            "category_schema_path": "$.properties.attr_5301",
            "ui_binding": "dxm_attribute:5301",
        },
        {
            "ui_label_zh": "材质等级",
            "field_key": "attr_6301",
            "category_schema_path": "$.properties.attr_6301",
            "ui_binding": "dxm_attribute:6301",
        },
    ])
    plan = client.post("/api/local-plan-templates", json=payload)
    assert plan.status_code == 201, plan.text

    preview = client.post(
        "/api/plan-snapshots/preview",
        json=_snapshot_request(plan.json()["id"]),
    )

    assert preview.status_code == 200, preview.text
    first = preview.json()["item_snapshots"][0]
    required = {
        item["field_key"]: item
        for item in first["required_fields"]
    }
    assert required["attr_6301"]["active"] is True


def test_e2_preview_rejects_missing_required_subproperty(
    tmp_path,
    monkeypatch,
):
    client, _repository, source = _setup(tmp_path, monkeypatch)
    source.schemas[0]["properties"]["compliance"] = {
        "type": "object",
        "ui_binding": "dxm_attribute:1103",
        "properties": {
            "manufacturer": {"type": "string", "minLength": 2},
            "country": {"type": "string", "minLength": 2},
        },
        "required": ["manufacturer", "country"],
    }
    source.schemas[0]["required"].append("compliance")
    refs = _sync_refs(client)
    payload = _plan_payload(refs, version="4.2.0")
    payload["fill_rules"]["100"]["compliance"] = {
        "value": {"manufacturer": "ACME"},
    }
    payload["field_mappings"]["100"] = _mapping(
        "zh-map-100-v3",
        ["title", "material", "compliance"],
    )
    plan = client.post("/api/local-plan-templates", json=payload)
    assert plan.status_code == 201

    preview = client.post(
        "/api/plan-snapshots/preview",
        json=_snapshot_request(plan.json()["id"]),
    )

    assert preview.status_code == 409
    assert (
        preview.json()["detail"]["reason_code"]
        == "PLAN_FIELD_SCHEMA_INVALID"
    )
    assert "compliance.country" in preview.json()["detail"]["message"]


def test_e2_preview_rejects_dependent_required_field_missing_from_mapping(
    tmp_path,
    monkeypatch,
):
    client, _repository, source = _setup(tmp_path, monkeypatch)
    source.schemas[0]["properties"]["warranty"] = {
        "type": "string",
        "minLength": 2,
        "ui_binding": "dxm_attribute:1104",
    }
    source.schemas[0]["dependentRequired"] = {
        "material": ["warranty"],
    }
    refs = _sync_refs(client)
    payload = _plan_payload(refs, version="4.3.0")
    payload["fill_rules"]["100"]["warranty"] = {
        "value": "One year",
    }
    plan = client.post("/api/local-plan-templates", json=payload)
    assert plan.status_code == 201

    preview = client.post(
        "/api/plan-snapshots/preview",
        json=_snapshot_request(plan.json()["id"]),
    )

    assert preview.status_code == 409
    assert (
        preview.json()["detail"]["reason_code"]
        == "PLAN_REQUIRED_FIELD_MAPPING_MISSING"
    )
    assert "warranty" in preview.json()["detail"]["message"]


@pytest.mark.parametrize(
    "mixed_script_title",
    [
        "a Отличный товар для дома",
        "a منتج ممتاز للمنزل",
        "Support de telephone pour voiture",
        "Soporte de telefono para coche",
        "Qzxv brtkl plmnw",
        "Product title malapa rebeka",
    ],
)
def test_e2_preview_rejects_non_english_script_mixed_with_latin_letter(
    tmp_path,
    monkeypatch,
    mixed_script_title,
):
    client, _repository, source = _setup(tmp_path, monkeypatch)
    refs = _sync_refs(client)
    payload = _plan_payload(
        refs,
        version="5.0.0",
        first_title=mixed_script_title,
    )
    created = client.post("/api/local-plan-templates", json=payload)
    assert created.status_code == 201
    source.products[0]["subject"] = ""

    preview = client.post(
        "/api/plan-snapshots/preview",
        json=_snapshot_request(created.json()["id"]),
    )

    assert preview.status_code == 409
    assert (
        preview.json()["detail"]["reason_code"]
        == "NATURAL_LANGUAGE_ENGLISH_REQUIRED"
    )


@pytest.mark.parametrize(
    "english_title",
    [
        "Adjustable Aluminum Laptop Stand for Desk",
        "Lightweight Waterproof Hooded Rain Jacket for Women",
        "Stainless Steel Insulated Water Bottle with Straw",
        "Portable Bluetooth Speaker with Deep Bass",
        "Rechargeable Cordless Electric Hair Clipper",
        "Marvel Spider Man Action Figure Collectible Toy",
        "Anime Demon Slayer Tanjiro Kamado PVC Figurine Model Gift",
        "Wireless Bluetooth Earbuds Noise Cancelling Stereo Headphones",
        "Cosplay Costume Accessories for Halloween Party",
        "Handmade Resin Statue Desktop Decoration Gift",
        "Fantasy Hotel Character Acrylic Stand Keychain Colorful Bag Pendant Card",
    ],
)
def test_e2_preview_accepts_normal_english_product_titles(
    tmp_path,
    monkeypatch,
    english_title,
):
    client, _repository, _source = _setup(tmp_path, monkeypatch)
    refs = _sync_refs(client)
    payload = _plan_payload(
        refs,
        version="5.1.0",
        first_title=english_title,
    )
    created = client.post("/api/local-plan-templates", json=payload)
    assert created.status_code == 201, created.text

    preview = client.post(
        "/api/plan-snapshots/preview",
        json=_snapshot_request(created.json()["id"]),
    )

    assert preview.status_code == 200, preview.text


def test_e2_preview_validates_english_inside_html_and_mobile_json(
    tmp_path,
    monkeypatch,
):
    client, _repository, source = _setup(tmp_path, monkeypatch)
    source.schemas[0]["properties"].update({
        "detail": {
            "type": "string",
            "minLength": 1,
            "natural_language": True,
            "content_format": "html",
            "ui_binding": "dxm_editor:detail",
        },
        "mobileDetail": {
            "type": "string",
            "minLength": 1,
            "natural_language": True,
            "content_format": "json",
            "ui_binding": "dxm_editor:mobileDetail",
        },
    })
    refs = _sync_refs(client)
    payload = _plan_payload(refs, version="5.2.0")
    payload["fill_rules"]["100"].update({
        "detail": {
            "value": "<p>Durable waterproof product for outdoor travel.</p>",
        },
        "mobileDetail": {
            "value": json.dumps({
                "moduleList": [
                    {
                        "type": "text",
                        "content": "Portable product description for travel",
                    }
                ]
            }),
        },
    })
    payload["field_mappings"]["100"]["entries"].extend([
        {
            "ui_label_zh": "PC 英文描述",
            "field_key": "detail",
            "category_schema_path": "$.properties.detail",
            "ui_binding": "dxm_editor:detail",
        },
        {
            "ui_label_zh": "移动端英文描述",
            "field_key": "mobileDetail",
            "category_schema_path": "$.properties.mobileDetail",
            "ui_binding": "dxm_editor:mobileDetail",
        },
    ])
    created = client.post("/api/local-plan-templates", json=payload)
    assert created.status_code == 201, created.text

    preview = client.post(
        "/api/plan-snapshots/preview",
        json=_snapshot_request(created.json()["id"]),
    )

    assert preview.status_code == 200, preview.text
