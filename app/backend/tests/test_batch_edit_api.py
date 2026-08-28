import copy
import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from src import db
from src.batch_edit.plan_contract import E2PlanService
from src.execution.dxm_login_flow import DxmLoginFlow
from src.main import app
from src.repository import Repository
from tests.test_e2_plan_snapshot_api import (
    _plan_payload as _current_plan_payload,
    _setup as _setup_current_plan_api,
    _snapshot_request as _current_snapshot_request,
    _sync_refs as _sync_current_refs,
)


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
                name: (
                    {"names": [], "required": False}
                    if name in {"description", "compliance", "semi_managed"}
                    else {"names": [f"{name}-template"], "required": True}
                )
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
            "binding_scope": "DXM Shop A",
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
            "category_name": None,
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
    store = next(
        (
            candidate
            for candidate in repository.list_stores()
            if candidate["name"] == "DXM Shop A"
            and candidate["platform"] == "AliExpress"
        ),
        None,
    )
    if store is None:
        store = repository.create_store("DXM Shop A", "AliExpress")
    assert store["id"] == 1
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
    public_scope_snapshot = scope_response.json()
    scope_snapshot = repository.get_draft_box_scope_snapshot(public_scope_snapshot["id"])
    assert scope_snapshot is not None

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


def _create_frozen_plan_batch_via_api(
    tmp_path,
    monkeypatch,
    *,
    version="1.0.0",
    first_title="Car Phone Holder",
):
    """Create the current public plan_snapshot + batch_draft_save aggregate."""

    client, repository, source = _setup_current_plan_api(tmp_path, monkeypatch)
    refs = _sync_current_refs(client)
    plan_payload = _current_plan_payload(
        refs,
        version=version,
        first_title=first_title,
    )
    plan_response = client.post("/api/local-plan-templates", json=plan_payload)
    assert plan_response.status_code == 201, plan_response.text
    plan = plan_response.json()
    preview_request = _current_snapshot_request(plan["id"])
    preview_response = client.post(
        "/api/plan-snapshots/preview",
        json=preview_request,
    )
    assert preview_response.status_code == 200, preview_response.text
    preview = preview_response.json()
    freeze_response = client.post(
        "/api/plan-snapshots",
        json=_current_snapshot_request(
            plan["id"],
            expected_snapshot_hash=preview["snapshot_hash"],
        ),
    )
    assert freeze_response.status_code == 201, freeze_response.text
    frozen = freeze_response.json()
    task_response = client.post(
        f"/api/plan-snapshots/{frozen['id']}/tasks",
    )
    assert task_response.status_code == 201, task_response.text
    return {
        "client": client,
        "repository": repository,
        "source": source,
        "refs": refs,
        "plan_payload": plan_payload,
        "plan": plan,
        "preview": preview,
        "frozen": frozen,
        "task": task_response.json(),
    }


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

    assert response.status_code == 201, response.text
    snapshot = response.json()
    assert browser_boundary.max_items == [2]
    assert snapshot["id"] > 0
    assert snapshot["store_identity"] == {"store_name": "DXM Shop A"}
    assert [item["ordinal"] for item in snapshot["items"]] == [1, 2]
    assert [item["dxm_product_id"] for item in snapshot["items"]] == [
        "DXM-1001",
        "DXM-1002",
    ]
    assert "digest" not in snapshot
    assert "evidence" not in snapshot

    persisted = repository.get_draft_box_scope_snapshot(snapshot["id"])
    assert persisted is not None
    assert persisted["schema_version"] == "dxm_draft_box_scope.v1"
    assert persisted["digest"] == persisted["snapshot_sha256"]
    canonical_snapshot = {
        key: value
        for key, value in persisted.items()
        if key not in {"id", "digest", "snapshot_sha256", "created_at"}
    }
    assert persisted["digest"] == _canonical_sha256(canonical_snapshot)
    assert persisted["zero_write_proof"] == {
        "strategy": "current_visible_page_dom_read",
        "navigation_attempted": False,
        "interactive_action_attempted": False,
        "mutation_dispatch_attempted": False,
    }
    assert persisted["evidence"]["kind"] == "live_dom_snapshot"
    assert persisted["evidence"]["dom_sha256"] == capture["evidence"]["dom_sha256"]
    assert persisted["evidence"]["refs_digest"] == capture["evidence"]["dom_digest"]
    assert persisted["created_at"]


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

    repository = Repository()
    monkeypatch.setattr(main, "repo", repository)
    monkeypatch.setattr(main, "workflow_adapter", BrowserBoundary())

    response = TestClient(app).post(
        "/api/dxm/draft-box/scope-snapshots",
        json={"max_items": 2},
    )

    assert response.status_code == 201
    public_snapshot = response.json()
    assert "evidence" not in public_snapshot
    assert "digest" not in public_snapshot
    persisted = repository.get_draft_box_scope_snapshot(public_snapshot["id"])
    assert persisted is not None
    evidence = persisted["evidence"]
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
    case = _create_frozen_plan_batch_via_api(tmp_path, monkeypatch)
    snapshot = case["frozen"]
    task = case["task"]

    assert snapshot["schema"] == "dxm_batch_draft_save_plan.v1"
    assert snapshot["mode"] == "batch_draft_save"
    assert snapshot["path"] == "A"
    assert snapshot["local_plan_template"] == {
        "id": case["plan"]["id"],
        "version": case["plan"]["version"],
    }
    assert snapshot["approval_context"] == {
        "state": "not_granted",
        "runner_released": False,
        "publish_allowed": False,
    }
    assert snapshot["failure_policy"] == {"unknown": "stop_batch"}
    assert snapshot["evidence_policy"] == "three_proofs"
    assert snapshot["publish_allowed"] is False
    assert task["status"] == "draft"
    assert task["mode"] == "batch_draft_save"
    assert task["payload"]["product_ids"] == [70001, 70002, 70003]
    assert [job["product_id"] for job in task["jobs"]] == [70001, 70002, 70003]
    assert [job["status"] for job in task["jobs"]] == ["pending", "pending", "pending"]

    private_task = case["repository"].get_task_private(task["id"])
    assert private_task is not None
    rebound = E2PlanService().assert_task_snapshot_binding(private_task)
    assert rebound["snapshot_hash"] == snapshot["snapshot_hash"]
    assert rebound["item_snapshots"] == snapshot["item_snapshots"]
    assert [
        item["target_identity"] for item in rebound["item_snapshots"]
    ] == [
        item["target_identity"] for item in case["preview"]["item_snapshots"]
    ]
    public = json.dumps(task, ensure_ascii=False).lower()
    assert "approvaltoken" not in public
    assert "token_hash" not in public
    assert "authorization_context" not in public


def test_bundle_content_change_is_rejected_and_does_not_rewrite_frozen_draft_batch(
    tmp_path,
    monkeypatch,
):
    case = _create_frozen_plan_batch_via_api(tmp_path, monkeypatch)
    client = case["client"]
    created_snapshot = copy.deepcopy(case["frozen"])
    created_task = copy.deepcopy(case["task"])

    changed_payload = copy.deepcopy(case["plan_payload"])
    changed_payload["version"] = "2.0.0"
    changed_payload["fill_rules"]["100"]["title"] = {
        "value": "Completely Different English Product Title"
    }
    in_place = client.patch(
        f"/api/local-plan-templates/{case['plan']['id']}",
        json={"name": "禁止原地修改"},
    )
    assert in_place.status_code == 409
    assert in_place.json()["detail"]["reason_code"] == "LOCAL_PLAN_VERSION_IMMUTABLE"
    next_version = client.post(
        f"/api/local-plan-templates/{case['plan']['id']}/versions",
        json=changed_payload,
    )
    assert next_version.status_code == 201, next_version.text
    assert next_version.json()["id"] != case["plan"]["id"]

    snapshot_response = client.get(f"/api/plan-snapshots/{created_snapshot['id']}")
    task_response = client.get(f"/api/tasks/{created_task['id']}")
    assert snapshot_response.status_code == 200
    assert snapshot_response.json() == created_snapshot
    assert task_response.status_code == 200
    assert task_response.json()["payload"]["plan_snapshot"] == created_task["payload"]["plan_snapshot"]
    assert task_response.json()["payload"]["plan_snapshot"]["local_plan_template"] == {
        "id": case["plan"]["id"],
        "version": "1.0.0",
    }
    persisted = case["repository"].get_task_private(created_task["id"])
    assert persisted is not None
    assert E2PlanService().assert_task_snapshot_binding(persisted)["snapshot_hash"] == created_snapshot["snapshot_hash"]


def test_edit_batch_rejects_bundle_bound_to_a_different_scope_store(tmp_path, monkeypatch):
    case = _create_frozen_plan_batch_via_api(tmp_path, monkeypatch)
    client = case["client"]
    other_scope = client.post(
        "/api/dxm-template-refs/sync",
        json={"shop_id": "3002", "category_ids": ["100", "200"]},
    )
    assert other_scope.status_code == 201, other_scope.text
    payload = _current_plan_payload(other_scope.json()["refs"], version="2.0.0")
    payload["shop_id"] = "3001"

    response = client.post("/api/local-plan-templates", json=payload)

    assert response.status_code == 409
    assert response.json()["detail"]["reason_code"] == "DXM_TEMPLATE_REF_SCOPE_CONFLICT"
    assert len(client.get("/api/tasks?mode=batch_draft_save").json()) == 1


def test_edit_batch_freeze_revalidates_bundle_single_save_completeness(tmp_path, monkeypatch):
    case = _create_frozen_plan_batch_via_api(tmp_path, monkeypatch)
    client = case["client"]
    payload = copy.deepcopy(case["plan_payload"])
    payload["version"] = "2.0.0"
    payload["field_mappings"]["100"]["entries"] = [
        entry
        for entry in payload["field_mappings"]["100"]["entries"]
        if entry["field_key"] != "material"
    ]
    incomplete = client.post("/api/local-plan-templates", json=payload)
    assert incomplete.status_code == 201, incomplete.text
    before_tasks = client.get("/api/tasks?mode=batch_draft_save").json()

    response = client.post(
        "/api/plan-snapshots",
        json={
            **_current_snapshot_request(incomplete.json()["id"]),
            "expected_snapshot_hash": "A" * 64,
            "idempotency_key": "incomplete-plan-freeze-0001",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["reason_code"] == "PLAN_REQUIRED_FIELD_MAPPING_MISSING"
    assert client.get("/api/tasks?mode=batch_draft_save").json() == before_tasks
    with db.connection() as conn:
        assert conn.execute("SELECT COUNT(*) AS count FROM plan_snapshots").fetchone()["count"] == 1


def test_operator_can_list_draft_batches_without_loading_full_snapshots(tmp_path, monkeypatch):
    case = _create_frozen_plan_batch_via_api(tmp_path, monkeypatch)
    client = case["client"]
    created = case["task"]
    monkeypatch.setattr(
        case["repository"],
        "list_tasks",
        lambda: (_ for _ in ()).throw(AssertionError("summary must not load payload_json")),
    )

    response = client.get("/api/tasks?mode=batch_draft_save&view=summary")

    assert response.status_code == 200
    assert response.json() == [{
        "id": created["id"],
        "name": created["name"],
        "store_id": created["store_id"],
        "status": "draft",
        "mode": "batch_draft_save",
        "publish_scene": "SMT_SEMI_MANAGED_SAVE_ONLY",
        "item_count": 3,
        "completed_jobs": 0,
        "failed_jobs": 0,
        "created_at": created["created_at"],
        "updated_at": created["updated_at"],
    }]
    public = json.dumps(response.json(), ensure_ascii=False)
    assert "payload" not in public
    assert "plan_snapshot" not in public
    assert "snapshot_hash" not in public


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
        ("section_template", None),
        ("incomplete_bundle", "PLAN_REQUIRED_FIELD_MAPPING_MISSING"),
    ],
)
def test_edit_batch_rejects_non_aggregate_or_incomplete_template(
    tmp_path,
    monkeypatch,
    candidate_kind,
    reason_code,
):
    case = _create_frozen_plan_batch_via_api(tmp_path, monkeypatch)
    client = case["client"]
    if candidate_kind == "section_template":
        response = client.post(
            "/api/local-plan-templates",
            json={
                "name": "单分区不是完整铺货方案",
                "version": "2.0.0",
                "shop_id": "3001",
                "category_ids": ["100"],
                "path": "A",
                "category": {"category_keyword": "单分区"},
            },
        )
        assert response.status_code == 422
        assert response.json()["detail"]
    else:
        payload = copy.deepcopy(case["plan_payload"])
        payload["version"] = "2.0.0"
        payload["field_mappings"]["100"]["entries"] = [
            entry
            for entry in payload["field_mappings"]["100"]["entries"]
            if entry["field_key"] != "material"
        ]
        invalid_plan = client.post("/api/local-plan-templates", json=payload)
        assert invalid_plan.status_code == 201, invalid_plan.text
        response = client.post(
            "/api/plan-snapshots/preview",
            json=_current_snapshot_request(invalid_plan.json()["id"]),
        )
        assert response.status_code == 409
        assert response.json()["detail"]["reason_code"] == reason_code
    assert len(client.get("/api/tasks?mode=batch_draft_save&view=summary").json()) == 1
    with db.connection() as conn:
        assert conn.execute("SELECT COUNT(*) AS count FROM plan_snapshots").fetchone()["count"] == 1


def test_frozen_scope_order_template_and_policy_have_no_mutation_endpoint(tmp_path, monkeypatch):
    case = _create_frozen_plan_batch_via_api(tmp_path, monkeypatch)
    client = case["client"]
    before_snapshot = copy.deepcopy(case["frozen"])
    before_task = copy.deepcopy(case["task"])

    response = client.patch(
        f"/api/plan-snapshots/{before_snapshot['id']}",
        json={
            "local_plan_template_id": 999,
            "publish_allowed": True,
            "product_ids": list(reversed(before_snapshot["product_ids"])),
        },
    )

    assert response.status_code == 405
    plan_mutation = client.patch(
        f"/api/local-plan-templates/{case['plan']['id']}",
        json={"fixed_values": {"publish_allowed": True}},
    )
    assert plan_mutation.status_code == 409
    assert plan_mutation.json()["detail"]["reason_code"] == "LOCAL_PLAN_VERSION_IMMUTABLE"
    override = client.patch(
        f"/api/tasks/{before_task['id']}/config-overrides",
        json={"section": "pricing", "values": {"retail_price": 999}},
    )
    assert override.status_code == 409
    assert override.json()["detail"]["reason_code"] == "BATCH_PLAN_SNAPSHOT_IMMUTABLE"
    assert client.get(f"/api/plan-snapshots/{before_snapshot['id']}").json() == before_snapshot
    after_task = client.get(f"/api/tasks/{before_task['id']}").json()
    assert after_task["payload"]["plan_snapshot"] == before_task["payload"]["plan_snapshot"]
    assert "template_overrides" not in after_task["payload"]


def test_edit_batch_read_api_is_newest_first_and_missing_detail_is_404(tmp_path, monkeypatch):
    first = _create_frozen_plan_batch_via_api(tmp_path, monkeypatch)
    second = _create_frozen_plan_batch_via_api(
        tmp_path,
        monkeypatch,
        version="2.0.0",
        first_title="Car Phone Holder",
    )
    client = second["client"]
    listed = client.get("/api/tasks?mode=batch_draft_save&view=summary")

    assert listed.status_code == 200
    assert [batch["id"] for batch in listed.json()] == [
        second["task"]["id"],
        first["task"]["id"],
    ]
    missing_snapshot = client.get("/api/plan-snapshots/999999")
    assert missing_snapshot.status_code == 404
    assert missing_snapshot.json()["detail"]["reason_code"] == "PLAN_SNAPSHOT_NOT_FOUND"
    missing_task = client.get("/api/tasks/999999")
    assert missing_task.status_code == 404
    assert missing_task.json()["detail"] == "Task not found"


def _post_manual_approval(client, batch_id: int, **payload):
    """Split approval for the current batch_draft_save task stays closed."""
    body = {
        "approved_by": "operator@example.com",
        "confirmation": "CONFIRM_DXM_SAVE_ONLY",
    }
    body.update(payload)
    return client.post(f"/api/tasks/{batch_id}/manual-approval", json=body)


def _assert_manual_approval_requires_atomic_start(response) -> None:
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["reason_code"] == "BATCH_APPROVAL_REQUIRES_ATOMIC_START"
    assert "原子" in detail["message"] or "approve" in detail["message"].lower() or "批准" in detail["message"]


def test_manual_approval_endpoint_requires_atomic_approve_and_start(tmp_path, monkeypatch):
    """L0-C06: split /manual-approval is intentionally closed; use approve-and-start."""
    case = _create_frozen_plan_batch_via_api(tmp_path, monkeypatch)
    client = case["client"]
    batch = case["task"]
    response = _post_manual_approval(client, batch["id"])
    _assert_manual_approval_requires_atomic_start(response)
    # Batch must remain draft; no token issuance side effects via this path.
    detail = client.get(f"/api/tasks/{batch['id']}").json()
    assert detail["status"] == "draft"
    assert [job["status"] for job in detail["jobs"]] == ["pending", "pending", "pending"]
    public = json.dumps(detail, ensure_ascii=False)
    assert "approvalToken" not in public
    assert "approval_token" not in public
    assert "manual_approval" not in detail["payload"]


def test_manual_approval_closed_even_with_wrong_confirmation(tmp_path, monkeypatch):
    case = _create_frozen_plan_batch_via_api(tmp_path, monkeypatch)
    client = case["client"]
    batch = case["task"]
    response = _post_manual_approval(
        client,
        batch["id"],
        confirmation="WRONG_PHRASE",
    )
    # Endpoint short-circuits before phrase validation — atomic gate wins.
    _assert_manual_approval_requires_atomic_start(response)
    assert client.get(f"/api/tasks/{batch['id']}").json()["status"] == "draft"


def test_manual_approval_closed_rejects_client_supplied_scope_payload(tmp_path, monkeypatch):
    case = _create_frozen_plan_batch_via_api(tmp_path, monkeypatch)
    client = case["client"]
    batch = case["task"]
    response = client.post(
        f"/api/tasks/{batch['id']}/manual-approval",
        json={
            "approved_by": "operator@example.com",
            "confirmation": "CONFIRM_DXM_SAVE_ONLY",
            "scope_snapshot_json": "{}",
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]
    detail = client.get(f"/api/tasks/{batch['id']}").json()
    assert detail["status"] == "draft"
    assert "manual_approval" not in detail["payload"]


def test_manual_approval_closed_under_session_and_capture_drift_setups(tmp_path, monkeypatch):
    """Drift scenarios must not reopen split approval; gate fires first."""
    case = _create_frozen_plan_batch_via_api(tmp_path, monkeypatch)
    client = case["client"]
    batch = case["task"]
    case["source"].browser_session_id = "browser-e2-drifted"
    case["source"].schemas[0]["properties"]["title"]["maxLength"] = 199
    response = _post_manual_approval(client, batch["id"])
    _assert_manual_approval_requires_atomic_start(response)
    detail = client.get(f"/api/tasks/{batch['id']}").json()
    assert detail["status"] == "draft"
    assert "manual_approval" not in detail["payload"]


def test_manual_approval_repeated_posts_never_issue_token(tmp_path, monkeypatch):
    case = _create_frozen_plan_batch_via_api(tmp_path, monkeypatch)
    client = case["client"]
    batch = case["task"]
    first = _post_manual_approval(client, batch["id"])
    second = _post_manual_approval(client, batch["id"])
    _assert_manual_approval_requires_atomic_start(first)
    _assert_manual_approval_requires_atomic_start(second)
    body = first.json()
    assert "approvalToken" not in body
    assert "approval_token" not in str(body).lower()
    detail = client.get(f"/api/tasks/{batch['id']}").json()
    assert detail["status"] == "draft"
    assert "manual_approval" not in detail["payload"]


def test_batch_read_apis_never_leak_approval_token_without_split_approval(tmp_path, monkeypatch):
    case = _create_frozen_plan_batch_via_api(tmp_path, monkeypatch)
    client = case["client"]
    batch = case["task"]
    closed = _post_manual_approval(client, batch["id"])
    _assert_manual_approval_requires_atomic_start(closed)
    detail = client.get(f"/api/tasks/{batch['id']}").json()
    listed = client.get("/api/tasks?mode=batch_draft_save").json()
    summaries = client.get("/api/tasks?mode=batch_draft_save&view=summary").json()
    public_json = json.dumps(
        {"detail": detail, "listed": listed, "summaries": summaries},
        ensure_ascii=False,
    )
    assert "approvalToken" not in public_json
    assert "token_hash" not in public_json
    assert "approval_token_hash" not in public_json
    assert "authorization_context" not in public_json


@pytest.mark.parametrize(
    "db_suffix",
    [
        "max-items",
        "runtime-drift",
        "page-identity",
        "ordered-targets",
        "dom-digest",
        "lease-context",
        "cas-token",
        "db-facts",
    ],
)
def test_manual_approval_remains_closed_for_legacy_security_scenarios(
    tmp_path,
    monkeypatch,
    db_suffix,
):
    """Real drifted facts cannot reopen the permanently closed split approval API."""
    case = _create_frozen_plan_batch_via_api(tmp_path, monkeypatch)
    client = case["client"]
    batch = case["task"]

    if db_suffix == "max-items":
        oversized = client.post(
            "/api/plan-snapshots/preview",
            json={
                **_current_snapshot_request(case["plan"]["id"]),
                "product_ids": [str(80000 + index) for index in range(101)],
            },
        )
        assert oversized.status_code == 422
    elif db_suffix == "runtime-drift":
        case["source"].browser_session_id = "browser-runtime-drift"
    elif db_suffix == "page-identity":
        case["source"].products[0]["sourceUrl"] = "https://example.test/wrong-page"
    elif db_suffix == "ordered-targets":
        with db.connection() as conn:
            row = conn.execute("SELECT payload_json FROM tasks WHERE id=?", (batch["id"],)).fetchone()
            payload = db.loads(row["payload_json"], {})
            payload["product_ids"] = list(reversed(payload["product_ids"]))
            conn.execute(
                "UPDATE tasks SET payload_json=? WHERE id=?",
                (db.dumps(payload), batch["id"]),
            )
    elif db_suffix == "dom-digest":
        case["source"].schemas[0]["properties"]["title"]["maxLength"] = 177
    elif db_suffix == "lease-context":
        with db.connection() as conn:
            row = conn.execute("SELECT payload_json FROM tasks WHERE id=?", (batch["id"],)).fetchone()
            payload = db.loads(row["payload_json"], {})
            payload["manual_approval"] = {
                "approved": True,
                "source": "client",
                "token_hash": "F" * 64,
            }
            conn.execute(
                "UPDATE tasks SET payload_json=? WHERE id=?",
                (db.dumps(payload), batch["id"]),
            )
    elif db_suffix == "cas-token":
        with db.connection() as conn:
            conn.execute("UPDATE tasks SET status='running' WHERE id=?", (batch["id"],))
    else:
        with db.connection() as conn:
            conn.execute("UPDATE tasks SET store_id=999999 WHERE id=?", (batch["id"],))

    response = _post_manual_approval(client, batch["id"])
    _assert_manual_approval_requires_atomic_start(response)
    public = client.get(f"/api/tasks/{batch['id']}").json()
    assert "approvalToken" not in json.dumps(public, ensure_ascii=False)
    assert "token_hash" not in json.dumps(public, ensure_ascii=False)
