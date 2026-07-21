import copy
import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from src import db
from src.execution.dxm_login_flow import DxmLoginFlow
from src.main import app
from src.repository import Repository


_BATCH_REQUIRED_SECTIONS = [
    "category",
    "sku",
    "pricing",
    "logistics",
    "image",
    "compliance",
    "semi_managed",
    "dxm_reference",
]


def _canonical_sha256(value: dict) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest().upper()


def _scope_capture(tmp_path) -> dict:
    items = []
    for ordinal, product_id, sku in (
        (1, "DXM-1001", "SKU-1001"),
        (2, "DXM-1002", "SKU-1002"),
    ):
        source_urls = [f"https://detail.1688.com/offer/{product_id[-4:]}.html"]
        dom_index = ordinal + 3
        row_text = f"商品 {ordinal} 产品ID：{product_id} 「DXM Shop A」 编辑"
        items.append(
            {
                "position": ordinal,
                "title": f"商品 {ordinal}",
                "product_id": product_id,
                "source_url": source_urls[0],
                "source_urls": source_urls,
                "stable_identity": {
                    "kind": "product_id",
                    "value": product_id,
                    "fingerprint": hashlib.sha256(
                        f"product_id:{product_id}".encode("utf-8")
                    ).hexdigest().upper(),
                },
                "store_evidence": {
                    "store_name": "DXM Shop A",
                    "cell_text": "「DXM Shop A」",
                    "source": "structured_store_cell",
                    "column_index": 2,
                    "tag": "TD",
                    "class_name": "store-cell",
                    "dom_index": dom_index,
                },
                "row_text_excerpt": row_text,
                "evidence_ref": {
                    "kind": "live_dom_row",
                    "browser_session_id": "browser-session-1",
                    "page_kind": "draft_box",
                    "page_url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft",
                    "dom_index": dom_index,
                    "row_sha256": hashlib.sha256(row_text.encode("utf-8")).hexdigest().upper(),
                },
            }
        )

    page = {
        "kind": "draft_box",
        "url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft",
        "title": "店小秘--速卖通商品箱",
        "ready": True,
        "business_marker": "标题/产品ID",
    }


    facts = {
        "filter": {"controls": [{"key": "status", "value": "draft", "source": "visible_filter_control"}]},
        "sort": {"keys": [{"key": "创建时间", "direction": "descending"}], "dom_order_authoritative": True},
        "pagination": {
            "current_page": 1,
            "page_size": 20,
            "total_items": 2,
            "visible_row_count": 2,
            "captured_count": 2,
            "max_items": 2,
            "truncated": False,
        },
        "runtime": {
            "browser_session_id": "browser-session-1",
            "browser_visible": True,
            "page_kind": "draft_box",
            "page_url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft",
            "owner_thread_id": 41,
            "capture_thread_id": 41,
            "binding": "current_live_browser_page",
        },
    }
    evidence_payload = {"page": page, "facts": facts, "items": items}
    evidence_refs = [dict(item["evidence_ref"]) for item in items]
    return {
        "schema": "dxm_draft_box_scope_capture.v1",
        "ok": True,
        "stage": "draft_box_scope_captured",
        "reason_code": "OK",
        "message": "已只读捕获当前商品箱可见范围，共 2 个商品。",
        "captured_at": "2026-07-21T08:00:00+00:00",
        "browser_session_id": "browser-session-1",
        "page": page,
        "facts": facts,
        "items": items,
        "evidence": {
            "kind": "live_dom_snapshot",
            "dom_sha256": _canonical_sha256(evidence_payload),
            "dom_digest": _canonical_sha256(evidence_refs),
            "summary": {
                "captured_count": 2,
                "visible_row_count": 2,
                "ordered": True,
                "stable_identity_complete": True,
                "page_kind": "draft_box",
            },
            "refs": evidence_refs,
        },
        "zero_write_proof": {
            "ok": True,
            "strategy": "current_visible_page_dom_read",
            "navigation_attempted": False,
            "interactive_action_attempted": False,
            "mutation_dispatch_attempted": False,
        },
    }


def _refresh_capture_evidence(capture: dict) -> None:
    capture["evidence"]["refs"] = [
        dict(item["evidence_ref"])
        for item in capture["items"]
    ]
    capture["evidence"]["dom_sha256"] = _canonical_sha256(
        {
            "page": capture["page"],
            "facts": capture["facts"],
            "items": capture["items"],
        }
    )
    capture["evidence"]["dom_digest"] = _canonical_sha256(
        capture["evidence"]["refs"]
    )


def _complete_bundle_payload() -> dict:
    sections = {
        "category": {"category_keyword": "车载用品"},
        "sku": {"sku_code_strategy": "use_product_or_dxm"},
        "pricing": {"retail_price_strategy": "preserve_or_template"},
        "logistics": {"weight": "0.5", "length": "20", "width": "15", "height": "10"},
        "image": {
            "eu_outer_package_filename": "eu-label.jpg",
            "marketing_images_strategy": "preserve_existing",
        },
        "compliance": {"material": "按商品现场与模板确认值"},
        "semi_managed": {
            "supply_price": "4.20",
            "jit_stock": "100",
            "is_original_box": "否",
            "length": "20",
            "width": "15",
            "height": "10",
            "goods_code_strategy": "allow_blank",
            "barcode_strategy": "allow_blank",
        },
        "dxm_reference": {
            "dxm_reference_templates": {
                name: {"names": [f"{name}-template"], "required": True}
                for name in (
                    "attribute_info",
                    "description",
                    "freight",
                    "service",
                    "eu_responsible",
                    "manufacturer",
                    "compliance",
                    "semi_managed",
                )
            }
        },
    }
    source_templates = {}
    for index, section in enumerate(_BATCH_REQUIRED_SECTIONS, start=1):
        source_payload = copy.deepcopy(
            sections[section]
            if section == "dxm_reference"
            else {section: sections[section]}
        )
        snapshot = {
            "id": 1000 + index,
            "template_type": section,
            "template_name": f"{section}-source",
            "binding_scope": "DXM Shop A / 车载用品",
            "payload": source_payload,
            "is_enabled": True,
            "created_at": "2026-07-21T08:00:00+00:00",
            "updated_at": "2026-07-21T08:00:00+00:00",
        }
        source_templates[section] = {
            "template_id": snapshot["id"],
            "template_type": section,
            "template_name": snapshot["template_name"],
            "binding_scope": snapshot["binding_scope"],
            "source_digest": _canonical_sha256(snapshot),
            "snapshot": snapshot,
        }
    return {
        "schema_version": "dxm_edit_template_bundle.v1",
        "version": "1.0.0",
        "required_sections": list(_BATCH_REQUIRED_SECTIONS),
        "binding": {
            "store_id": 1,
            "store_name": "DXM Shop A",
            "category_name": "车载用品",
            "platform": "AliExpress",
        },
        "source_templates": source_templates,
        "sections": sections,
    }


def _create_draft_batch_via_api(
    tmp_path,
    monkeypatch,
    *,
    db_name="batch-create.db",
    captured_at="2026-07-21T08:00:00+00:00",
    max_items=2,
):
    db_path = tmp_path / db_name
    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.init_db()

    import src.main as main

    repository = Repository()
    capture = _scope_capture(tmp_path)
    capture["captured_at"] = captured_at
    capture["facts"]["pagination"]["max_items"] = max_items
    _refresh_capture_evidence(capture)

    class BrowserBoundary:
        def __init__(self):
            self.capture = capture
            self.max_items = []

        def capture_draft_box_scope(self, requested_max_items):
            self.max_items.append(requested_max_items)
            return self.capture

        def browser_session_id(self):
            return self.capture["browser_session_id"]

    monkeypatch.setattr(main, "repo", repository)
    monkeypatch.setattr(main, "workflow_adapter", BrowserBoundary())
    client = TestClient(app)
    scope_response = client.post(
        "/api/dxm/draft-box/scope-snapshots",
        json={"max_items": max_items},
    )
    assert scope_response.status_code == 201
    scope_snapshot = scope_response.json()

    bundle_payload = _complete_bundle_payload()
    template = repository.create_template(
        {
            "template_type": "edit_batch_bundle",
            "template_name": "车载商品编辑包",
            "binding_scope": "live-dxm-draft-box-scope",
            "payload": bundle_payload,
            "is_enabled": True,
        }
    )
    response = client.post(
        "/api/edit-batches",
        json={
            "scope_snapshot_id": scope_snapshot["id"],
            "template_id": template["id"],
        },
    )
    return client, scope_snapshot, template, bundle_payload, response


def test_operator_can_capture_and_persist_current_draft_box_scope(tmp_path, monkeypatch):
    db_path = tmp_path / "batch-edit.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.init_db()

    import src.main as main

    repository = Repository()
    capture = _scope_capture(tmp_path)

    class BrowserBoundary:
        def __init__(self):
            self.max_items = []

        def capture_draft_box_scope(self, max_items):
            self.max_items.append(max_items)
            return capture

        def browser_session_id(self):
            return capture["browser_session_id"]

    browser_boundary = BrowserBoundary()
    monkeypatch.setattr(main, "repo", repository)
    monkeypatch.setattr(main, "workflow_adapter", browser_boundary)

    response = TestClient(app).post(
        "/api/dxm/draft-box/scope-snapshots",
        json={"max_items": 2},
    )

    assert response.status_code == 201
    snapshot = response.json()
    assert browser_boundary.max_items == [2]
    assert snapshot["schema_version"] == "dxm_draft_box_scope.v1"
    assert snapshot["id"] > 0
    assert snapshot["digest"] == snapshot["snapshot_sha256"]
    canonical_snapshot = {
        key: value
        for key, value in snapshot.items()
        if key not in {"id", "digest", "snapshot_sha256", "created_at"}
    }
    assert snapshot["digest"] == _canonical_sha256(canonical_snapshot)
    assert [item["ordinal"] for item in snapshot["items"]] == [1, 2]
    assert snapshot["store_identity"]["store_name"] == "DXM Shop A"
    assert snapshot["zero_write_proof"] == {
        "strategy": "current_visible_page_dom_read",
        "navigation_attempted": False,
        "interactive_action_attempted": False,
        "mutation_dispatch_attempted": False,
    }
    assert snapshot["evidence"]["kind"] == "live_dom_snapshot"
    assert snapshot["evidence"]["dom_sha256"] == capture["evidence"]["dom_sha256"]
    assert snapshot["evidence"]["refs_digest"] == capture["evidence"]["dom_digest"]
    assert snapshot["created_at"]


def test_scope_endpoint_accepts_exact_raw_contract_emitted_by_login_flow(tmp_path, monkeypatch):
    class LiveClient:
        pass

    class Browser:
        pass

    class Context:
        pass

    class Page:
        url = "https://www.dianxiaomi.com/web/smt/smtProductList/draft?status=0"

        def __init__(self, context):
            self.context = context

    context = Context()
    page = Page(context)
    flow = DxmLoginFlow(LiveClient(), state_file=tmp_path / "scope-flow-state.json")
    flow._browser = Browser()
    flow._context = context
    flow._page = page
    flow._browser_session_thread_id = threading.get_ident()
    monkeypatch.setattr(flow, "browser_session_id", lambda: "real-flow-session-1")
    monkeypatch.setattr(flow, "_is_playwright_object_closed", lambda _value: False)
    monkeypatch.setattr(flow, "_is_browser_connected", lambda _value: True)
    monkeypatch.setattr(flow, "_is_headless", lambda: False)
    monkeypatch.setattr(
        flow,
        "_browser_readiness_gate",
        lambda *_args, **_kwargs: {
            "ok": True,
            "page_title": "店小秘--速卖通商品箱",
            "business_marker": "标题/产品ID",
        },
    )
    monkeypatch.setattr(
        flow,
        "_read_draft_box_scope_dom",
        lambda _page, *, max_items: {
            "items": [
                {
                    "domIndex": index,
                    "title": f"真实契约商品 {index + 1}",
                    "productId": f"DXM-30{index + 1:02d}",
                    "sourceUrls": [
                        f"https://detail.1688.com/offer/300{index + 1}.html"
                    ],
                    "storeEvidence": {
                        "store_name": "DXM Shop A",
                        "cell_text": "「DXM Shop A」",
                        "source": "structured_store_cell",
                        "column_index": 2,
                        "tag": "TD",
                        "class_name": "store-cell",
                    },
                    "rowText": f"真实契约商品 {index + 1} 产品ID：DXM-30{index + 1:02d} 「DXM Shop A」",
                }
                for index in range(max_items)
            ],
            "visibleRowCount": max_items,
            "filter": {"controls": []},
            "sort": {"keys": [], "dom_order_authoritative": True},
            "pagination": {
                "current_page": 1,
                "page_size": 20,
                "total_items": max_items,
            },
        },
    )

    raw_capture = flow.capture_draft_box_scope(max_items=2)
    assert raw_capture["ok"] is True
    assert set(raw_capture["evidence"]) == {
        "kind",
        "dom_sha256",
        "dom_digest",
        "summary",
        "refs",
    }

    db_path = tmp_path / "real-raw-contract.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.init_db()
    import src.main as main

    class BrowserBoundary:
        def capture_draft_box_scope(self, _max_items):
            return raw_capture

        def browser_session_id(self):
            return raw_capture["browser_session_id"]

    monkeypatch.setattr(main, "repo", Repository())
    monkeypatch.setattr(main, "workflow_adapter", BrowserBoundary())

    response = TestClient(app).post(
        "/api/dxm/draft-box/scope-snapshots",
        json={"max_items": 2},
    )

    assert response.status_code == 201
    evidence = response.json()["evidence"]
    assert evidence["dom_sha256"] == raw_capture["evidence"]["dom_sha256"]
    assert evidence["refs_digest"] == raw_capture["evidence"]["dom_digest"]


@pytest.mark.parametrize(
    "injected",
    [
        {"store_id": 99},
        {"product_ids": [1001, 1002]},
        {"items": [{"ordinal": 1, "title": "客户端伪造商品"}]},
    ],
)
def test_scope_capture_request_rejects_client_selected_scope(monkeypatch, injected):
    import src.main as main

    class BrowserBoundary:
        def __init__(self):
            self.calls = 0

        def capture_draft_box_scope(self, _max_items):
            self.calls += 1
            raise AssertionError("invalid client input must not reach the browser")

    browser_boundary = BrowserBoundary()
    monkeypatch.setattr(main, "workflow_adapter", browser_boundary)

    response = TestClient(app).post(
        "/api/dxm/draft-box/scope-snapshots",
        json={"max_items": 2, **injected},
    )

    assert response.status_code == 422
    assert browser_boundary.calls == 0


def test_operator_can_create_immutable_draft_batch_from_scope_and_complete_bundle(tmp_path, monkeypatch):
    _client, scope_snapshot, template, bundle_payload, response = _create_draft_batch_via_api(
        tmp_path,
        monkeypatch,
    )

    assert response.status_code == 201
    batch = response.json()
    assert batch["schema_version"] == "dxm_edit_batch.v1"
    assert batch["status"] == "draft"
    assert batch["scope_snapshot_id"] == scope_snapshot["id"]
    assert batch["scope_snapshot_digest"] == scope_snapshot["digest"]
    assert batch["template_id"] == template["id"]
    assert batch["template_snapshot"]["payload"] == bundle_payload
    assert batch["template_snapshot_digest"] == _canonical_sha256(batch["template_snapshot"])
    assert batch["policy"]["approval_mode"] == "batch_once"
    assert batch["policy"]["dispatch_mode"] == "strict_sequential"
    assert batch["policy"]["global_concurrency"] == 1
    assert batch["policy"]["publish_allowed"] is False
    assert batch["policy"]["unknown_result_policy"] == "stop_no_retry"
    assert [item["ordinal"] for item in batch["items"]] == [1, 2]
    assert [item["status"] for item in batch["items"]] == ["pending", "pending"]
    assert [item["target_identity_sha256"] for item in batch["items"]] == [
        item["target_identity_sha256"] for item in scope_snapshot["items"]
    ]


def test_bundle_content_change_is_rejected_and_does_not_rewrite_frozen_draft_batch(
    tmp_path,
    monkeypatch,
):
    client, _scope_snapshot, template, original_payload, create_response = _create_draft_batch_via_api(
        tmp_path,
        monkeypatch,
        db_name="batch-template-freeze.db",
    )
    assert create_response.status_code == 201
    created_batch = create_response.json()

    changed_payload = _complete_bundle_payload()
    changed_payload["version"] = "2.0.0"
    changed_payload["sections"]["category"] = {
        "category": {"category_keyword": "完全不同的新类目"}
    }
    update_response = client.patch(
        f"/api/templates/{template['id']}",
        json={"template_name": "已修改模板", "payload": changed_payload},
    )
    assert update_response.status_code == 409

    response = client.get(f"/api/edit-batches/{created_batch['id']}")

    assert response.status_code == 200
    frozen_batch = response.json()
    assert frozen_batch == created_batch
    assert frozen_batch["template_snapshot"]["template_name"] == "车载商品编辑包"
    assert frozen_batch["template_snapshot"]["payload"] == original_payload
    assert frozen_batch["template_snapshot_digest"] == created_batch["template_snapshot_digest"]
    assert frozen_batch["scope_snapshot_digest"] == created_batch["scope_snapshot_digest"]
    assert frozen_batch["policy_digest"] == created_batch["policy_digest"]


def test_edit_batch_rejects_bundle_bound_to_a_different_scope_store(tmp_path, monkeypatch):
    client, scope_snapshot, _template, _payload, create_response = _create_draft_batch_via_api(
        tmp_path,
        monkeypatch,
        db_name="batch-bundle-store-conflict.db",
    )
    assert create_response.status_code == 201
    import src.main as main

    payload = _complete_bundle_payload()
    payload["binding"]["store_id"] = 999
    payload["binding"]["store_name"] = "Other Store"
    mismatched = main.repo.create_template(
        {
            "template_type": "edit_batch_bundle",
            "template_name": "other-store-bundle",
            "binding_scope": "store:999;category:车载用品",
            "payload": payload,
            "is_enabled": True,
        }
    )

    response = client.post(
        "/api/edit-batches",
        json={
            "scope_snapshot_id": scope_snapshot["id"],
            "template_id": mismatched["id"],
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["reason_code"] == "TEMPLATE_SCOPE_STORE_MISMATCH"


def test_edit_batch_freeze_revalidates_bundle_single_save_completeness(tmp_path, monkeypatch):
    client, scope_snapshot, _template, _payload, create_response = _create_draft_batch_via_api(
        tmp_path,
        monkeypatch,
        db_name="batch-bundle-freeze-completeness.db",
    )
    assert create_response.status_code == 201
    import src.main as main

    payload = _complete_bundle_payload()
    payload["sections"]["logistics"].pop("weight")
    logistics_source = payload["source_templates"]["logistics"]
    logistics_source["snapshot"]["payload"]["logistics"].pop("weight")
    logistics_source["source_digest"] = _canonical_sha256(logistics_source["snapshot"])
    incomplete = main.repo.create_template(
        {
            "template_type": "edit_batch_bundle",
            "template_name": "incomplete-frozen-bundle",
            "binding_scope": "store:1;category:车载用品",
            "payload": payload,
            "is_enabled": True,
        }
    )

    response = client.post(
        "/api/edit-batches",
        json={
            "scope_snapshot_id": scope_snapshot["id"],
            "template_id": incomplete["id"],
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["reason_code"] == "TEMPLATE_BUNDLE_INCOMPLETE"


def test_operator_can_list_draft_batches_without_loading_full_snapshots(tmp_path, monkeypatch):
    client, scope_snapshot, template, _payload, create_response = _create_draft_batch_via_api(
        tmp_path,
        monkeypatch,
        db_name="batch-list.db",
    )
    assert create_response.status_code == 201
    created = create_response.json()

    response = client.get("/api/edit-batches")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": created["id"],
            "schema_version": "dxm_edit_batch.v1",
            "status": "draft",
            "scope_snapshot_id": scope_snapshot["id"],
            "scope_snapshot_digest": scope_snapshot["digest"],
            "template_id": template["id"],
            "template_snapshot_digest": created["template_snapshot_digest"],
            "policy_digest": created["policy_digest"],
            "item_count": 2,
            "store_identity": scope_snapshot["store_identity"],
            "template": {
                "name": "车载商品编辑包",
                "version": "1.0.0",
            },
            "created_at": created["created_at"],
            "updated_at": created["updated_at"],
        }
    ]


@pytest.mark.parametrize(
    ("invalid_fact", "reason_code"),
    [
        ("multi_store", "SCOPE_MULTI_STORE_FORBIDDEN"),
        ("identity_digest", "SCOPE_ITEM_IDENTITY_INVALID"),
        ("source_url_drift", "SCOPE_ITEM_SOURCE_INVALID"),
        ("dxm_source_url_injection", "SCOPE_ITEM_SOURCE_INVALID"),
        ("ordinary_source_url_injection", "SCOPE_ITEM_SOURCE_INVALID"),
        ("mutation_attempted", "SCOPE_ZERO_WRITE_PROOF_INVALID"),
        ("missing_refs_digest", "SCOPE_SCHEMA_INVALID"),
        ("tampered_refs_digest", "SCOPE_EVIDENCE_DIGEST_INVALID"),
    ],
)
def test_scope_snapshot_fails_closed_when_live_read_facts_are_unsafe(
    tmp_path,
    monkeypatch,
    invalid_fact,
    reason_code,
):
    db_path = tmp_path / f"unsafe-scope-{invalid_fact}.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.init_db()

    import src.main as main

    capture = copy.deepcopy(_scope_capture(tmp_path))
    if invalid_fact == "multi_store":
        capture["items"][1]["store_evidence"]["store_name"] = "Another DXM Shop"
        capture["items"][1]["store_evidence"]["cell_text"] = "「Another DXM Shop」"
    elif invalid_fact == "identity_digest":
        capture["items"][0]["stable_identity"]["fingerprint"] = "F" * 64
    elif invalid_fact == "source_url_drift":
        capture["items"][0]["source_url"] = "https://example.com/injected"
    elif invalid_fact in {"dxm_source_url_injection", "ordinary_source_url_injection"}:
        injected_url = (
            "https://www.dianxiaomi.com/web/smt/smtProductList/draft"
            if invalid_fact == "dxm_source_url_injection"
            else "https://example.com/product/1001"
        )
        capture["items"][0]["source_url"] = injected_url
        capture["items"][0]["source_urls"] = [injected_url]
        _refresh_capture_evidence(capture)
    elif invalid_fact == "mutation_attempted":
        capture["zero_write_proof"]["mutation_dispatch_attempted"] = True
    elif invalid_fact == "missing_refs_digest":
        capture["evidence"].pop("dom_digest")
    else:
        capture["evidence"]["dom_digest"] = "C" * 64

    class BrowserBoundary:
        def capture_draft_box_scope(self, _max_items):
            return capture

        def browser_session_id(self):
            return capture["browser_session_id"]

    monkeypatch.setattr(main, "repo", Repository())
    monkeypatch.setattr(main, "workflow_adapter", BrowserBoundary())

    response = TestClient(app).post(
        "/api/dxm/draft-box/scope-snapshots",
        json={"max_items": 2},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["reason_code"] == reason_code


@pytest.mark.parametrize(
    ("candidate_kind", "reason_code"),
    [
        ("section_template", "TEMPLATE_BUNDLE_REQUIRED"),
        ("incomplete_bundle", "TEMPLATE_BUNDLE_INCOMPLETE"),
    ],
)
def test_edit_batch_rejects_non_aggregate_or_incomplete_template(
    tmp_path,
    monkeypatch,
    candidate_kind,
    reason_code,
):
    client, scope_snapshot, _template, _payload, valid_batch_response = _create_draft_batch_via_api(
        tmp_path,
        monkeypatch,
        db_name=f"batch-template-reject-{candidate_kind}.db",
    )
    assert valid_batch_response.status_code == 201

    if candidate_kind == "section_template":
        template_type = "category"
        payload = {"category": {"category_keyword": "单分区不是完整模板包"}}
    else:
        template_type = "edit_batch_bundle"
        payload = _complete_bundle_payload()
        payload["sections"].pop("image")
    template_data = {
            "template_type": template_type,
            "template_name": f"invalid-{candidate_kind}",
            "binding_scope": "live-dxm-draft-box-scope",
            "payload": payload,
            "is_enabled": True,
    }
    if candidate_kind == "section_template":
        template_response = client.post("/api/templates", json=template_data)
        assert template_response.status_code == 200
        invalid_template = template_response.json()
    else:
        import src.main as main

        invalid_template = main.repo.create_template(template_data)

    response = client.post(
        "/api/edit-batches",
        json={
            "scope_snapshot_id": scope_snapshot["id"],
            "template_id": invalid_template["id"],
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["reason_code"] == reason_code
    assert len(client.get("/api/edit-batches").json()) == 1


def test_frozen_scope_order_template_and_policy_have_no_mutation_endpoint(tmp_path, monkeypatch):
    client, _scope, _template, _payload, create_response = _create_draft_batch_via_api(
        tmp_path,
        monkeypatch,
        db_name="batch-immutable-api.db",
    )
    assert create_response.status_code == 201
    before = create_response.json()

    response = client.patch(
        f"/api/edit-batches/{before['id']}",
        json={
            "scope_snapshot_id": 999,
            "template_id": 999,
            "policy": {"publish_allowed": True},
            "items": list(reversed(before["items"])),
        },
    )

    assert response.status_code == 405
    assert client.get(f"/api/edit-batches/{before['id']}").json() == before


def test_edit_batch_read_api_is_newest_first_and_missing_detail_is_404(tmp_path, monkeypatch):
    client, _scope, _template, _payload, first_response = _create_draft_batch_via_api(
        tmp_path,
        monkeypatch,
        db_name="batch-read-api.db",
        captured_at="2026-07-21T08:00:00+00:00",
    )
    assert first_response.status_code == 201
    _client, _scope, _template, _payload, second_response = _create_draft_batch_via_api(
        tmp_path,
        monkeypatch,
        db_name="batch-read-api.db",
        captured_at="2026-07-21T08:01:00+00:00",
    )
    assert second_response.status_code == 201

    listed = client.get("/api/edit-batches")

    assert listed.status_code == 200
    assert [batch["id"] for batch in listed.json()] == [
        second_response.json()["id"],
        first_response.json()["id"],
    ]
    missing = client.get("/api/edit-batches/999999")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Edit batch not found"


def test_operator_can_approve_unchanged_live_batch_scope_once(tmp_path, monkeypatch):
    client, _scope, _template, _payload, create_response = _create_draft_batch_via_api(
        tmp_path,
        monkeypatch,
        db_name="batch-manual-approval.db",
    )
    assert create_response.status_code == 201
    batch = create_response.json()

    response = client.post(
        f"/api/edit-batches/{batch['id']}/manual-approval",
        json={
            "approved_by": "operator@example.com",
            "confirmation": "CONFIRM_DXM_BATCH_SAVE_ONLY",
        },
    )

    assert response.status_code == 200
    approval = response.json()
    assert approval["ok"] is True
    assert approval["batchId"] == batch["id"]
    assert approval["confirmation"] == "CONFIRM_DXM_BATCH_SAVE_ONLY"
    assert approval["approvedBy"] == "operator@example.com"
    assert isinstance(approval["approvalToken"], str)
    assert len(approval["approvalToken"]) >= 32
    assert approval["issuedAt"]
    assert approval["expiresAt"]
    assert approval["scopeRevalidation"]["kind"] == "scope_revalidation"
    assert approval["scopeRevalidation"]["status"] == "matched"

    approved_batch = client.get(f"/api/edit-batches/{batch['id']}").json()
    assert approved_batch["status"] == "approved"


def test_batch_approval_recaptures_frozen_max_items_when_visible_count_is_smaller(
    tmp_path,
    monkeypatch,
):
    client, _scope, _template, _payload, create_response = _create_draft_batch_via_api(
        tmp_path,
        monkeypatch,
        db_name="batch-frozen-max-items.db",
        max_items=5,
    )
    batch = create_response.json()
    import src.main as main

    assert batch["scope_snapshot"]["page_state"]["captured_count"] == 2
    assert batch["scope_snapshot"]["page_state"]["max_items"] == 5

    response = client.post(
        f"/api/edit-batches/{batch['id']}/manual-approval",
        json={
            "approved_by": "operator@example.com",
            "confirmation": "CONFIRM_DXM_BATCH_SAVE_ONLY",
        },
    )

    assert response.status_code == 200
    assert main.workflow_adapter.max_items == [5, 5]


def test_batch_approval_rejects_any_confirmation_other_than_exact_phrase(tmp_path, monkeypatch):
    client, _scope, _template, _payload, create_response = _create_draft_batch_via_api(
        tmp_path,
        monkeypatch,
        db_name="batch-wrong-confirmation.db",
    )
    batch = create_response.json()

    response = client.post(
        f"/api/edit-batches/{batch['id']}/manual-approval",
        json={
            "approved_by": "operator@example.com",
            "confirmation": "确认批量保存",
        },
    )

    assert response.status_code == 400
    assert client.get(f"/api/edit-batches/{batch['id']}").json()["status"] == "draft"


def test_batch_approval_request_forbids_client_supplied_scope_or_policy(tmp_path, monkeypatch):
    client, _scope, _template, _payload, create_response = _create_draft_batch_via_api(
        tmp_path,
        monkeypatch,
        db_name="batch-approval-extra-fields.db",
    )
    batch = create_response.json()

    response = client.post(
        f"/api/edit-batches/{batch['id']}/manual-approval",
        json={
            "approved_by": "operator@example.com",
            "confirmation": "CONFIRM_DXM_BATCH_SAVE_ONLY",
            "scope_snapshot_id": 999,
        },
    )

    assert response.status_code == 422
    assert client.get(f"/api/edit-batches/{batch['id']}").json()["status"] == "draft"


@pytest.mark.parametrize(
    "approval_payload",
    [
        {
            "approved_by": "a" * 201,
            "confirmation": "CONFIRM_DXM_BATCH_SAVE_ONLY",
        },
        {
            "approved_by": "operator@example.com",
            "confirmation": "C" * 65,
        },
    ],
)
def test_batch_approval_request_rejects_unbounded_operator_input(
    tmp_path,
    monkeypatch,
    approval_payload,
):
    client, _scope, _template, _payload, create_response = _create_draft_batch_via_api(
        tmp_path,
        monkeypatch,
        db_name=(
            "batch-approval-input-"
            f"{len(approval_payload['approved_by'])}-{len(approval_payload['confirmation'])}.db"
        ),
    )
    batch = create_response.json()
    import src.main as main

    response = client.post(
        f"/api/edit-batches/{batch['id']}/manual-approval",
        json=approval_payload,
    )

    assert response.status_code == 422
    assert main.workflow_adapter.max_items == [2]


def test_batch_approval_fails_closed_when_browser_session_drifts(tmp_path, monkeypatch):
    client, _scope, _template, _payload, create_response = _create_draft_batch_via_api(
        tmp_path,
        monkeypatch,
        db_name="batch-session-drift.db",
    )
    batch = create_response.json()
    import src.main as main

    capture = main.workflow_adapter.capture
    capture["browser_session_id"] = "browser-session-2"
    capture["facts"]["runtime"]["browser_session_id"] = "browser-session-2"
    for item in capture["items"]:
        item["evidence_ref"]["browser_session_id"] = "browser-session-2"
    _refresh_capture_evidence(capture)

    response = client.post(
        f"/api/edit-batches/{batch['id']}/manual-approval",
        json={
            "approved_by": "operator@example.com",
            "confirmation": "CONFIRM_DXM_BATCH_SAVE_ONLY",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["reason_code"] == "BATCH_RUNTIME_DRIFT"
    assert client.get(f"/api/edit-batches/{batch['id']}").json()["status"] == "draft"


@pytest.mark.parametrize("drift_kind", ["runtime_instance", "browser_runtime", "git_head"])
def test_batch_approval_fails_closed_when_authoritative_runtime_drifts(
    tmp_path,
    monkeypatch,
    drift_kind,
):
    client, _scope, _template, _payload, create_response = _create_draft_batch_via_api(
        tmp_path,
        monkeypatch,
        db_name=f"batch-{drift_kind}-drift.db",
    )
    batch = create_response.json()
    import src.main as main

    if drift_kind == "browser_runtime":
        class DriftedBrowserRuntime:
            runtime_id = "browser-runtime-after-freeze"

        monkeypatch.setattr(main, "browser_agent_runtime", DriftedBrowserRuntime())
    else:
        changed = dict(main.runtime_identity.as_dict())
        changed[
            "instanceId" if drift_kind == "runtime_instance" else "gitHead"
        ] = f"{drift_kind}-after-freeze"

        class DriftedRuntimeIdentity:
            def as_dict(self):
                return changed

        monkeypatch.setattr(main, "runtime_identity", DriftedRuntimeIdentity())

    response = client.post(
        f"/api/edit-batches/{batch['id']}/manual-approval",
        json={
            "approved_by": "operator@example.com",
            "confirmation": "CONFIRM_DXM_BATCH_SAVE_ONLY",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["reason_code"] == "BATCH_RUNTIME_DRIFT"


def test_batch_approval_fails_closed_when_draft_box_page_identity_drifts(tmp_path, monkeypatch):
    client, _scope, _template, _payload, create_response = _create_draft_batch_via_api(
        tmp_path,
        monkeypatch,
        db_name="batch-page-drift.db",
    )
    batch = create_response.json()
    import src.main as main

    capture = main.workflow_adapter.capture
    capture["page"]["title"] = "店小秘--另一个商品箱视图"
    _refresh_capture_evidence(capture)

    response = client.post(
        f"/api/edit-batches/{batch['id']}/manual-approval",
        json={
            "approved_by": "operator@example.com",
            "confirmation": "CONFIRM_DXM_BATCH_SAVE_ONLY",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["reason_code"] == "BATCH_PAGE_DRIFT"


def test_batch_approval_fails_closed_when_ordered_targets_drift(tmp_path, monkeypatch):
    client, _scope, _template, _payload, create_response = _create_draft_batch_via_api(
        tmp_path,
        monkeypatch,
        db_name="batch-target-order-drift.db",
    )
    batch = create_response.json()
    import src.main as main

    capture = main.workflow_adapter.capture
    capture["items"] = list(reversed(capture["items"]))
    for position, item in enumerate(capture["items"], start=1):
        item["position"] = position
    _refresh_capture_evidence(capture)

    response = client.post(
        f"/api/edit-batches/{batch['id']}/manual-approval",
        json={
            "approved_by": "operator@example.com",
            "confirmation": "CONFIRM_DXM_BATCH_SAVE_ONLY",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["reason_code"] == "BATCH_TARGET_ORDER_DRIFT"


def test_batch_approval_fails_closed_when_live_dom_double_digest_drifts(tmp_path, monkeypatch):
    client, _scope, _template, _payload, create_response = _create_draft_batch_via_api(
        tmp_path,
        monkeypatch,
        db_name="batch-dom-drift.db",
    )
    batch = create_response.json()
    import src.main as main

    capture = main.workflow_adapter.capture
    capture["items"][0]["title"] = "同一目标但页面可见标题已变化"
    _refresh_capture_evidence(capture)

    response = client.post(
        f"/api/edit-batches/{batch['id']}/manual-approval",
        json={
            "approved_by": "operator@example.com",
            "confirmation": "CONFIRM_DXM_BATCH_SAVE_ONLY",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["reason_code"] == "BATCH_DOM_DRIFT"


@pytest.mark.parametrize("digest_key", ["dom_sha256", "dom_digest"])
def test_batch_approval_rejects_tampered_live_capture_digest(
    tmp_path,
    monkeypatch,
    digest_key,
):
    client, _scope, _template, _payload, create_response = _create_draft_batch_via_api(
        tmp_path,
        monkeypatch,
        db_name=f"batch-tampered-{digest_key}.db",
    )
    batch = create_response.json()
    import src.main as main

    main.workflow_adapter.capture["evidence"][digest_key] = "C" * 64

    response = client.post(
        f"/api/edit-batches/{batch['id']}/manual-approval",
        json={
            "approved_by": "operator@example.com",
            "confirmation": "CONFIRM_DXM_BATCH_SAVE_ONLY",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["reason_code"] == "SCOPE_EVIDENCE_DIGEST_INVALID"


def test_batch_approval_is_single_use_and_repeated_request_cannot_issue_another_token(
    tmp_path,
    monkeypatch,
):
    client, _scope, _template, _payload, create_response = _create_draft_batch_via_api(
        tmp_path,
        monkeypatch,
        db_name="batch-repeat-approval.db",
    )
    batch = create_response.json()
    request = {
        "approved_by": "operator@example.com",
        "confirmation": "CONFIRM_DXM_BATCH_SAVE_ONLY",
    }

    first = client.post(f"/api/edit-batches/{batch['id']}/manual-approval", json=request)
    repeated = client.post(f"/api/edit-batches/{batch['id']}/manual-approval", json=request)

    assert first.status_code == 200
    assert repeated.status_code == 409
    assert repeated.json()["detail"]["reason_code"] == "BATCH_NOT_DRAFT"
    assert "approvalToken" not in repeated.json()


def test_batch_read_apis_never_leak_raw_approval_token_or_hash(tmp_path, monkeypatch):
    client, _scope, _template, _payload, create_response = _create_draft_batch_via_api(
        tmp_path,
        monkeypatch,
        db_name="batch-token-boundary.db",
    )
    batch = create_response.json()

    approved = client.post(
        f"/api/edit-batches/{batch['id']}/manual-approval",
        json={
            "approved_by": "operator@example.com",
            "confirmation": "CONFIRM_DXM_BATCH_SAVE_ONLY",
        },
    ).json()
    raw_token = approved["approvalToken"]
    expected_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest().upper()

    detail = client.get(f"/api/edit-batches/{batch['id']}").json()
    listed = client.get("/api/edit-batches").json()
    public_json = json.dumps({"detail": detail, "listed": listed}, ensure_ascii=False)
    assert raw_token not in public_json
    assert expected_hash not in public_json
    assert "token_hash" not in public_json
    assert "approval_token_hash" not in public_json
    assert detail["approval"]["scope_revalidation"]["kind"] == "scope_revalidation"

    with db.connection() as conn:
        row = conn.execute(
            """
            SELECT approval_token_hash, approval_lease_id, approval_context_json
              FROM edit_batches
             WHERE id=?
            """,
            (batch["id"],),
        ).fetchone()
    assert row["approval_token_hash"] == expected_hash
    assert row["approval_lease_id"]
    assert raw_token not in row["approval_context_json"]
    assert "token_hash" not in row["approval_context_json"]


def test_batch_approval_context_has_five_minute_lease_and_all_frozen_bindings(
    tmp_path,
    monkeypatch,
):
    client, scope, template, _payload, create_response = _create_draft_batch_via_api(
        tmp_path,
        monkeypatch,
        db_name="batch-approval-context.db",
    )
    batch = create_response.json()
    approved = client.post(
        f"/api/edit-batches/{batch['id']}/manual-approval",
        json={
            "approved_by": "operator@example.com",
            "confirmation": "CONFIRM_DXM_BATCH_SAVE_ONLY",
        },
    ).json()

    issued_at = datetime.fromisoformat(approved["issuedAt"])
    expires_at = datetime.fromisoformat(approved["expiresAt"])
    assert (expires_at - issued_at).total_seconds() == 300

    with db.connection() as conn:
        row = conn.execute(
            "SELECT approval_lease_id, approval_context_json FROM edit_batches WHERE id=?",
            (batch["id"],),
        ).fetchone()
    context = json.loads(row["approval_context_json"])
    assert context["schema_version"] == "dxm_edit_batch_approval_context.v1"
    assert context["batch"]["id"] == batch["id"]
    assert context["scope"] == {
        "snapshot_id": scope["id"],
        "snapshot_digest": batch["scope_snapshot_digest"],
    }
    assert context["template"] == {
        "id": template["id"],
        "snapshot_digest": batch["template_snapshot_digest"],
    }
    assert context["policy"]["digest"] == batch["policy_digest"]
    assert context["store_identity"] == scope["store_identity"]
    assert context["runtime_identity"] == scope["runtime_identity"]
    assert context["approved_by"] == "operator@example.com"
    assert context["confirmation"] == "CONFIRM_DXM_BATCH_SAVE_ONLY"
    assert context["lease_id"] == row["approval_lease_id"]
    assert context["read_attestation"]["kind"] == "scope_revalidation"
    assert context["read_attestation"]["status"] == "matched"
    unsigned_context = dict(context)
    fingerprint = unsigned_context.pop("fingerprint")
    assert fingerprint == _canonical_sha256(unsigned_context)


def test_concurrent_batch_approval_compare_and_swap_issues_exactly_one_token(
    tmp_path,
    monkeypatch,
):
    client, _scope, _template, _payload, create_response = _create_draft_batch_via_api(
        tmp_path,
        monkeypatch,
        db_name="batch-concurrent-approval.db",
    )
    batch = create_response.json()
    import src.main as main

    barrier = threading.Barrier(2)

    class BarrierRepository(Repository):
        def approve_edit_batch(self, batch_id, approval):
            barrier.wait(timeout=5)
            return super().approve_edit_batch(batch_id, approval)

    monkeypatch.setattr(main, "repo", BarrierRepository())

    def approve(approver):
        return TestClient(app).post(
            f"/api/edit-batches/{batch['id']}/manual-approval",
            json={
                "approved_by": approver,
                "confirmation": "CONFIRM_DXM_BATCH_SAVE_ONLY",
            },
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(approve, ["operator-a", "operator-b"]))

    assert sorted(response.status_code for response in responses) == [200, 409]
    winners = [response.json() for response in responses if response.status_code == 200]
    losers = [response.json() for response in responses if response.status_code == 409]
    assert len(winners) == 1
    assert len(winners[0]["approvalToken"]) >= 32
    assert losers[0]["detail"]["reason_code"] == "BATCH_NOT_DRAFT"
    assert client.get(f"/api/edit-batches/{batch['id']}").json()["status"] == "approved"


@pytest.mark.parametrize(
    ("drift_kind", "reason_code"),
    [
        ("scope_snapshot_json", "SCOPE_SNAPSHOT_DIGEST_INVALID"),
        ("scope_binding", "BATCH_SCOPE_SNAPSHOT_DRIFT"),
        ("template_snapshot", "BATCH_TEMPLATE_SNAPSHOT_DRIFT"),
        ("template_binding", "BATCH_TEMPLATE_SNAPSHOT_DRIFT"),
        ("policy", "BATCH_POLICY_DRIFT"),
        ("batch_item", "BATCH_ITEM_DRIFT"),
    ],
)
def test_batch_approval_revalidates_all_frozen_database_facts_before_live_capture(
    tmp_path,
    monkeypatch,
    drift_kind,
    reason_code,
):
    client, _scope, _template, _payload, create_response = _create_draft_batch_via_api(
        tmp_path,
        monkeypatch,
        db_name=f"batch-frozen-{drift_kind}.db",
    )
    batch = create_response.json()
    import src.main as main

    with db.connection() as conn:
        if drift_kind == "scope_snapshot_json":
            scope_snapshot = copy.deepcopy(batch["scope_snapshot"])
            scope_snapshot["filter_state"] = {"controls": []}
            conn.execute(
                "UPDATE edit_batches SET scope_snapshot_json=? WHERE id=?",
                (db.dumps(scope_snapshot), batch["id"]),
            )
        elif drift_kind == "scope_binding":
            conn.execute(
                "UPDATE edit_batches SET scope_snapshot_digest=? WHERE id=?",
                ("F" * 64, batch["id"]),
            )
        elif drift_kind == "template_snapshot":
            template_snapshot = copy.deepcopy(batch["template_snapshot"])
            template_snapshot["template_name"] = "数据库中被改写的模板"
            conn.execute(
                "UPDATE edit_batches SET template_snapshot_json=? WHERE id=?",
                (db.dumps(template_snapshot), batch["id"]),
            )
        elif drift_kind == "template_binding":
            conn.execute(
                "UPDATE edit_batches SET template_id=? WHERE id=?",
                (batch["template_id"] + 1000, batch["id"]),
            )
        elif drift_kind == "policy":
            policy = copy.deepcopy(batch["policy"])
            policy["publish_allowed"] = True
            conn.execute(
                "UPDATE edit_batches SET policy_json=? WHERE id=?",
                (db.dumps(policy), batch["id"]),
            )
        else:
            conn.execute(
                """
                UPDATE edit_batch_items
                   SET target_identity_sha256=?
                 WHERE batch_id=? AND ordinal=1
                """,
                ("E" * 64, batch["id"]),
            )

    response = client.post(
        f"/api/edit-batches/{batch['id']}/manual-approval",
        json={
            "approved_by": "operator@example.com",
            "confirmation": "CONFIRM_DXM_BATCH_SAVE_ONLY",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["reason_code"] == reason_code
    assert main.workflow_adapter.max_items == [2]
