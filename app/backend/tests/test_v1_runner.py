import asyncio
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from src import db
from src.execution.v1_runner import V1TaskRunner
from src.repository import Repository


class DummyManager:
    def __init__(self):
        self.events = []

    async def broadcast(self, task_id, payload):
        self.events.append((task_id, payload))


class FakeWorkflowAdapter:
    def __init__(
        self,
        fail_action: str | None = None,
        note_verified: bool = True,
        save_result: dict | None = None,
        include_save_result: bool = True,
    ):
        self.calls = []
        self.fail_action = fail_action
        self.note_verified = note_verified
        self.save_result = save_result or {"ok": True, "code": 0, "msg": "真实保存成功", "published": False}
        self.include_save_result = include_save_result
        self.live_hud_calls = []

    def check_login_state(self):
        return self._record("check_login_state")

    def open_draft_box(self):
        return self._record("open_draft_box")

    def open_data_acquisition(self):
        return self._record("open_data_acquisition")

    def claim_from_data_acquisition(
        self,
        claim_mark,
        product_query=None,
        category_name=None,
        store_name=None,
        target_source_urls=None,
    ):
        return self._record(
            "claim_from_data_acquisition",
            claim_mark,
            product_query,
            category_name,
            store_name,
            target_source_urls,
        )

    def verify_draft_box_claim(
        self,
        claim_mark,
        product_query=None,
        category_name=None,
        store_name=None,
        target_source_urls=None,
    ):
        return self._record(
            "verify_draft_box_claim",
            claim_mark,
            product_query,
            category_name,
            store_name,
            target_source_urls,
        )

    def claim_product(self, note_text, product_query=None, store_name=None, target_source_urls=None):
        return self._record("claim_product", note_text, product_query, store_name, target_source_urls)

    def open_editor(self, product_query=None, store_name=None, note_text=None):
        return self._record("open_editor", product_query, store_name, note_text)

    def verify_edit_ownership(self, product_query=None, store_name=None):
        return self._record("verify_edit_ownership", product_query, store_name)

    def fill_editor_required_defaults(self, defaults=None, product_query=None, store_name=None):
        return self._record("fill_editor_required_defaults", defaults, product_query, store_name)

    def fill_editor_variants(self, defaults=None, product_query=None, store_name=None):
        return self._record("fill_editor_variants", defaults, product_query, store_name)

    def fill_media_assets(self, defaults=None, product_query=None, store_name=None):
        return self._record("fill_media_assets", defaults, product_query, store_name)

    def fill_compliance_defaults(self, defaults=None, product_query=None, store_name=None):
        return self._record("fill_compliance_defaults", defaults, product_query, store_name)

    def enable_semi_managed(self, product_query=None, store_name=None):
        return self._record("enable_semi_managed", product_query, store_name)

    def open_semi_managed_page(self, defaults=None, product_query=None, store_name=None):
        return self._record("open_semi_managed_page", defaults, product_query, store_name)

    def fill_semi_managed_defaults(self, defaults=None, product_query=None, store_name=None):
        return self._record("fill_semi_managed_defaults", defaults, product_query, store_name)

    def save_only(self, defaults=None, product_query=None, store_name=None):
        return self._record("save_only", defaults, product_query, store_name)

    def verify_not_published(self, product_query=None, store_name=None):
        return self._record("verify_not_published", product_query, store_name)

    def update_live_hud(self, hud):
        self.live_hud_calls.append(hud)
        return {
            "ok": True,
            "updated": True,
            "reason": "live_browser_hud_updated",
            "current_url": "https://www.dianxiaomi.com/web/smt/edit",
            "page_title": "店小秘--编辑速卖通产品",
            "hud": hud,
            "updated_at": "2026-05-22T00:00:02+00:00",
        }

    def _record(self, action, *args):
        self.calls.append((action, *args))
        evidence = {"action": action}
        if action == "claim_product":
            evidence["note_verified"] = self.note_verified
        if action == "verify_draft_box_claim":
            evidence["claimed_product"] = {
                "title": args[1] or "ACG Stand Product 1",
                "category_name": args[2] or "立牌类谷子",
                "source_url": "https://detail.1688.com/offer/from-acquisition.html",
                "row_text": "采集箱商品行 ACG Stand Product 1 AI认领",
            }
            evidence["claim_target"] = {
                "matchedBy": "source_url",
                "rowText": "数据采集商品行 ACG Stand Product 1 认领",
                "sourceUrls": ["https://detail.1688.com/offer/from-acquisition.html"],
            }
            evidence["search_result"] = {
                "query": "https://detail.1688.com/offer/from-acquisition.html",
                "query_source": "target_source_url",
                "filled": True,
                "clicked_search": True,
            }
        if action == "fill_editor_required_defaults" and args:
            defaults = args[0] if isinstance(args[0], dict) else {}
            resolved = defaults.get("dxm_reference_templates_resolved") or {}
            applied = {
                section: {"ok": True, "section": section, **config}
                for section, config in resolved.items()
            }
            evidence["dxm_reference_template_results"] = applied
        if action == "save_only" and self.include_save_result:
            evidence["save_result"] = self.save_result
        result = {
            "ok": action != self.fail_action,
            "action": action,
            "stage": f"{action}_stage",
            "page_title": "速卖通采集箱",
            "page_url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft",
            "screenshot_url": f"/artifacts/{action}.png",
            "product_query": args[-2] if len(args) >= 2 else None,
            "store_name": args[-1] if len(args) >= 1 else None,
            "evidence": evidence,
        }
        if action == "save_only" and self.include_save_result:
            result["save_result"] = self.save_result
        if "dxm_reference_template_results" in evidence:
            result["dxm_reference_template_results"] = evidence["dxm_reference_template_results"]
        return result


class ThreadRecordingWorkflowAdapter(FakeWorkflowAdapter):
    def __init__(self):
        super().__init__()
        self.thread_names = []
        self.hud_thread_names = []

    def _record(self, action, *args):
        self.thread_names.append(threading.current_thread().name)
        return super()._record(action, *args)

    def update_live_hud(self, hud):
        self.hud_thread_names.append(threading.current_thread().name)
        return super().update_live_hud(hud)


class FakeAgentConsole:
    def __init__(self, fail: bool = False):
        self.calls = []
        self.action_calls = []
        self.fail = fail
        self.start_calls = []

    def update_task_step(self, **payload):
        if self.fail:
            raise RuntimeError("console unavailable")
        self.calls.append(payload)
        return {
            "ok": True,
            "updated": True,
            "reason": "updated",
            "active": True,
            "session_id": "agent-test",
            "task_id": payload.get("task_id"),
            "job_id": payload.get("job_id"),
            "product_id": payload.get("product_id"),
            "browser_visible": False,
            "current_url": "about:blank",
            "last_step_code": payload.get("step_code"),
            "last_step_name": payload.get("step_name"),
            "hud": {
                "title": payload.get("step_name"),
                "state": payload.get("step_code"),
                "action": payload.get("field_domain"),
                "next_step": payload.get("next_step"),
                "store_name": payload.get("store_name"),
                "guard": "只保存不发布",
            },
            "screenshot": None,
            "updated_at": "2026-05-22T00:00:00+00:00",
            "last_error": None,
        }

    def record_action_event(self, **payload):
        if self.fail:
            raise RuntimeError("console unavailable")
        self.action_calls.append(payload)
        return {
            "ok": True,
            "updated": True,
            "reason": "action_recorded",
            "active": True,
            "session_id": "agent-test",
            "task_id": payload.get("task_id"),
            "job_id": payload.get("job_id"),
            "product_id": payload.get("product_id"),
            "browser_visible": False,
            "current_url": payload.get("page_url") or "about:blank",
            "last_step_code": payload.get("step_code") or payload.get("state"),
            "last_step_name": payload.get("label") or payload.get("action"),
            "hud": {
                "title": payload.get("label") or payload.get("action"),
                "state": payload.get("step_code") or payload.get("state"),
                "action": payload.get("action"),
                "next_step": None,
                "store_name": payload.get("store_name"),
                "guard": "只保存不发布",
            },
            "action_events": [payload],
            "screenshot": payload.get("screenshot_url"),
            "updated_at": "2026-05-22T00:00:01+00:00",
            "last_error": None,
        }


@pytest.fixture()
def v1_db(tmp_path, monkeypatch):
    db_path = tmp_path / "v1-runner.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.init_db()
    return db_path


def _create_task(repo: Repository, mode: str = "single_save", product_count: int = 1):
    store = repo.create_store("Dang Kang", "AliExpress")
    dxm_reference_templates = {
        "attribute_info": {"names": ["立牌类谷子"]},
        "description": {"names": ["详情模板"]},
        "freight": {"names": ["40g普货包裹"]},
        "service": {"names": ["Service Template for New Sellers"]},
        "eu_responsible": {"names": ["Jacqueiline Marti"]},
        "manufacturer": {"names": ["jiyang county thunder"]},
        "compliance": {"names": ["合规模板"]},
        "semi_managed": {"names": ["半托管模板"]},
    }
    template_payloads = {
        "category": {
            "category_name": "模板类目",
            "dxm_reference_templates": dxm_reference_templates,
            "category": {
                "template_category_id": "tmpl-cat",
            },
        },
        "sku": {"stock": "100", "sku": {"template_sku_rule": "tmpl-sku"}},
        "pricing": {"price": "9.99", "pricing": {"currency": "USD"}},
        "logistics": {
            "weight": "0.03",
            "logistics": {
                "length": "10",
                "width": "10",
                "height": "2",
            },
        },
        "image": {
            "image": {
                "eu_outer_package_filename": "template-eu.jpg",
                "marketing_images_strategy": "generate",
            },
        },
        "compliance": {"compliance": {"material": "PVC"}},
        "semi_managed": {
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
    }
    for template_type, template_payload in template_payloads.items():
        repo.create_template(
            {
                "template_type": template_type,
                "template_name": f"{template_type} template",
                "binding_scope": "V1",
                "payload": template_payload,
                "is_enabled": True,
            }
        )
    product_ids = []
    for idx in range(product_count):
        source_url = f"https://detail.1688.com/offer/test-{idx + 1}.html"
        claim_task = None
        if mode == "single_save":
            claim_task = repo.create_acquisition_claim_request(
                {
                    "store_id": store["id"],
                    "source_url": source_url,
                    "keyword": f"ACG Stand Product {idx + 1}",
                    "category_name": "立牌类谷子",
                    "claim_mark": "AI认领",
                    "template_id": None,
                }
            )
        product = repo.create_product(
            {
                "title": f"ACG Stand Product {idx + 1}",
                "source": "dxm_data_acquisition" if mode == "single_save" else "test",
                "status": "claimed_to_draft" if mode == "single_save" else "draft",
                "category_name": "立牌类谷子",
                "price": 7.01,
                "currency": "USD",
                "sku_count": 8,
                "image_count": 8,
                "payload": {
                    "source": "dxm_data_acquisition" if mode == "single_save" else "test",
                    "source_title": f"ACG Stand Product {idx + 1}",
                    "source_url": source_url,
                    "source_urls": [source_url],
                    "claim_task_id": claim_task["id"] if claim_task else None,
                    "draft_box_verified": mode == "single_save",
                    "store_name": "Dang Kang",
                    "category": {"template_category_id": f"product-cat-{idx + 1}"},
                    "image": {"eu_outer_package_filename": f"product-eu-{idx + 1}.jpg"},
                    "compliance": {"battery": "none"},
                },
            }
        )
        if claim_task:
            repo.mark_acquisition_claim_completed(claim_task["id"], product)
        product_ids.append(product["id"])
    return repo.create_task(
        {
            "name": "V1 半托管保存任务",
            "store_id": store["id"],
            "mode": mode,
            "publish_scene": "SMT_SEMI_MANAGED_SAVE_ONLY",
            "claim_mark": "AI认领",
            "product_ids": product_ids,
            "payload": {
                "store_name": "Dang Kang",
                "category_name": "任务类目",
                "template_overrides": {"logistics": {"weight": "0.05"}},
                "image": {"alt_text": "任务图片说明"},
                "compliance": {"material": "ABS"},
                "semi_managed": {"supply_price": "5.60"},
            },
        }
    )


def test_single_save_generates_success_report_and_never_publishes(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    job_id = repo.get_task(task["id"])["jobs"][0]["id"]
    manager = DummyManager()

    adapter = FakeWorkflowAdapter()

    asyncio.run(V1TaskRunner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    reports = repo.list_reports(task["id"])
    refreshed = repo.get_task(task["id"])
    assert refreshed["status"] == "completed"
    assert len(reports) == 1
    assert reports[0]["status"] == "success"
    assert reports[0]["published"] is False
    assert reports[0]["save_result"]["msg"] == "真实保存成功"
    assert reports[0]["summary"]["claim_mark"] == f"AI认领-{task['id']}-{job_id}"
    assert "semi_goods" in reports[0]["summary"]["filled_fields"]


def test_create_task_preserves_payload_overrides(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)

    assert task["payload"]["store_name"] == "Dang Kang"
    assert task["payload"]["category_name"] == "任务类目"
    assert task["payload"]["template_overrides"]["logistics"]["weight"] == "0.05"
    assert task["payload"]["image"]["alt_text"] == "任务图片说明"
    assert task["payload"]["compliance"]["material"] == "ABS"
    assert task["payload"]["semi_managed"]["supply_price"] == "5.60"


def test_single_save_calls_workflow_adapter_in_complete_save_order(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    job_id = repo.get_task(task["id"])["jobs"][0]["id"]
    manager = DummyManager()
    adapter = FakeWorkflowAdapter()

    asyncio.run(V1TaskRunner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    assert adapter.calls == [
        ("check_login_state",),
        ("open_draft_box",),
        ("claim_product", f"AI认领-{task['id']}-{job_id}", "ACG Stand Product 1", "Dang Kang", ["https://detail.1688.com/offer/test-1.html"]),
        ("open_editor", "ACG Stand Product 1", "Dang Kang", f"AI认领-{task['id']}-{job_id}"),
        ("verify_edit_ownership", "ACG Stand Product 1", "Dang Kang"),
        ("fill_editor_required_defaults", adapter.calls[5][1], "ACG Stand Product 1", "Dang Kang"),
        ("fill_editor_variants", adapter.calls[6][1], "ACG Stand Product 1", "Dang Kang"),
        ("fill_media_assets", adapter.calls[7][1], "ACG Stand Product 1", "Dang Kang"),
        ("fill_compliance_defaults", adapter.calls[8][1], "ACG Stand Product 1", "Dang Kang"),
        ("enable_semi_managed", "ACG Stand Product 1", "Dang Kang"),
        ("open_semi_managed_page", adapter.calls[10][1], "ACG Stand Product 1", "Dang Kang"),
        ("fill_semi_managed_defaults", adapter.calls[11][1], "ACG Stand Product 1", "Dang Kang"),
        ("fill_semi_managed_defaults", adapter.calls[12][1], "ACG Stand Product 1", "Dang Kang"),
        ("save_only", adapter.calls[13][1], "ACG Stand Product 1", "Dang Kang"),
        ("verify_not_published", "ACG Stand Product 1", "Dang Kang"),
    ]
    defaults = adapter.calls[5][1]
    assert defaults["category_name"] == "任务类目"
    assert defaults["category"]["template_category_id"] == "product-cat-1"
    assert defaults["logistics"]["weight"] == "0.05"
    assert defaults["image"]["eu_outer_package_filename"] == "product-eu-1.jpg"
    assert defaults["image"]["alt_text"] == "任务图片说明"
    assert defaults["compliance"]["material"] == "ABS"
    assert defaults["compliance"]["battery"] == "none"
    assert defaults["semi_managed"]["supply_price"] == "5.60"
    assert adapter.calls[10][1] == defaults
    reports = repo.list_reports(task["id"])
    assert reports[0]["published"] is False
    assert reports[0]["summary"]["workflow_actions"] == [
        "check_login_state",
        "open_draft_box",
        "claim_product",
        "open_editor",
        "verify_edit_ownership",
        "fill_editor_required_defaults",
        "fill_editor_variants",
        "fill_media_assets",
        "fill_compliance_defaults",
        "enable_semi_managed",
        "open_semi_managed_page",
        "fill_semi_managed_defaults",
        "fill_semi_managed_defaults",
        "save_only",
        "verify_not_published",
    ]
    assert reports[0]["summary"]["workflow_results"][-1]["product_query"] == "ACG Stand Product 1"
    assert reports[0]["summary"]["workflow_results"][-1]["store_name"] == "Dang Kang"
    assert reports[0]["summary"]["category"] == "立牌类谷子"
    assert reports[0]["summary"]["template_trace"]
    assert "_template_trace" not in reports[0]["summary"]["resolved_defaults"]


def test_single_save_syncs_agent_console_hud_without_changing_workflow_order(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    manager = DummyManager()
    adapter = FakeWorkflowAdapter()
    console = FakeAgentConsole()

    asyncio.run(V1TaskRunner(repo, manager, workflow_adapter=adapter, agent_console=console).run_task(task["id"]))

    states = [call["step_code"] for call in console.calls]
    assert "PRECHECK_CONFIG" in states
    assert "PRECHECK_PUBLISH_GUARD" in states
    assert "SELECT_CATEGORY" in states
    assert "SAVE_ONLY" in states
    assert "VERIFY_NOT_PUBLISHED" in states
    assert "WRITE_REPORT" in states
    assert "RELEASE_LOCK" in states
    precheck_config = next(call for call in console.calls if call["step_code"] == "PRECHECK_CONFIG")
    open_draft = next(call for call in console.calls if call["step_code"] == "OPEN_DRAFT_LIST")
    find_product = next(call for call in console.calls if call["step_code"] == "FIND_PRODUCT")
    open_editor = next(call for call in console.calls if call["step_code"] == "OPEN_EDIT_PAGE")
    base_info = next(call for call in console.calls if call["step_code"] == "FILL_BASE_INFO")
    variants = next(call for call in console.calls if call["step_code"] == "FILL_VARIANTS")
    media = next(call for call in console.calls if call["step_code"] == "FILL_MEDIA")
    semi_goods = next(call for call in console.calls if call["step_code"] == "FILL_SEMI_GOODS")
    select_category = next(call for call in console.calls if call["step_code"] == "SELECT_CATEGORY")
    save_only = next(call for call in console.calls if call["step_code"] == "SAVE_ONLY")
    verify_not_published = next(call for call in console.calls if call["step_code"] == "VERIFY_NOT_PUBLISHED")
    release_lock = next(call for call in console.calls if call["step_code"] == "RELEASE_LOCK")
    assert precheck_config["human_title"] == "开始任务"
    assert precheck_config["phase"] == "准备执行"
    assert open_draft["human_title"] == "正在打开采集箱"
    assert open_draft["human_action"] == "进入店小秘采集箱"
    assert find_product["human_title"] == "正在定位商品"
    assert open_editor["human_title"] == "正在打开编辑页"
    assert base_info["human_title"] == "正在编辑商品"
    assert base_info["human_action"] == "正在填写标题"
    assert base_info["human_next"] == "继续填写价格、图片和物流信息"
    assert select_category["human_title"] == "正在选择分类"
    assert select_category["human_action"] == "确认商品分类和属性"
    assert select_category["progress_index"] == 6
    assert select_category["progress_total"] == 12
    assert variants["human_action"] == "正在填写价格、库存和 SKU"
    assert media["human_action"] == "正在处理图片"
    assert semi_goods["human_title"] == "正在设置包装物流"
    assert save_only["human_title"] == "正在只保存"
    assert save_only["human_action"] == "只点击保存，不发布"
    assert verify_not_published["human_title"] == "正在检查结果"
    assert verify_not_published["human_action"] == "确认商品没有发布"
    assert release_lock["human_title"] == "任务完成"
    assert release_lock["progress_index"] == 12
    assert release_lock["progress_total"] == 12
    operator_phrases = [
        "开始任务",
        "进入店小秘采集箱",
        "查找本次要编辑保存的商品",
        "进入采集箱商品编辑页",
        "正在填写标题",
        "确认商品分类和属性",
        "正在填写价格、库存和 SKU",
        "正在处理图片",
        "填写重量、尺寸和物流信息",
        "只点击保存，不发布",
        "确认商品没有发布",
        "任务完成",
    ]
    hud_text = "\n".join(
        str(call.get(key) or "")
        for call in console.calls
        for key in ("phase", "human_title", "human_action", "human_next")
    )
    for phrase in operator_phrases:
        assert phrase in hud_text
    assert all(call["progress_total"] == 12 for call in console.calls if call.get("progress_total"))
    compact_progress = []
    for call in console.calls:
        progress = call.get("progress_index")
        if not progress or progress == (compact_progress[-1] if compact_progress else None):
            continue
        compact_progress.append(progress)
    assert compact_progress == list(range(1, 13))
    assert all(call["severity"] == "running" for call in console.calls)
    assert all(call["requires_user_action"] is False for call in console.calls)
    assert all(call["store_name"] == "Dang Kang" for call in console.calls)
    assert console.start_calls == []
    assert [call["action"] for call in console.action_calls] == [call[0] for call in adapter.calls]
    assert next(call for call in console.action_calls if call["action"] == "fill_editor_required_defaults")["type"] == "fill"
    assert next(call for call in console.action_calls if call["action"] == "fill_media_assets")["type"] == "upload"
    save_action = next(call for call in console.action_calls if call["action"] == "save_only")
    assert save_action["type"] == "save"
    assert save_action["save_result"]["published"] is False
    assert [call[0] for call in adapter.calls].count("save_only") == 1
    assert [call[0] for call in adapter.calls].index("save_only") < [call[0] for call in adapter.calls].index("verify_not_published")

    report = repo.list_reports(task["id"])[0]
    assert report["published"] is False
    assert report["save_result"]["published"] is False
    assert report["summary"]["agent_console"]["session_id"] == "agent-test"
    assert report["summary"]["agent_console"]["hud"]["guard"] == "只保存不发布"
    assert report["summary"]["agent_console"]["last_step_code"] == "RELEASE_LOCK"
    assert report["summary"]["agent_action_events"][-1]["action"] == "verify_not_published"
    assert any(event["action"] == "save_only" and event["type"] == "save" for event in report["summary"]["agent_action_events"])
    assert any(
        evidence["meta"].get("agent_console", {}).get("hud", {}).get("guard") == "只保存不发布"
        for evidence in repo.list_evidences(task["id"])
    )
    assert any(
        evidence["evidence_type"] == "workflow_action"
        and evidence["meta"].get("agent_action", {}).get("action") == "save_only"
        for evidence in repo.list_evidences(task["id"])
    )


def test_single_save_updates_live_browser_hud_without_agent_console(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    manager = DummyManager()
    adapter = FakeWorkflowAdapter()

    asyncio.run(V1TaskRunner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    states = [call["step_code"] for call in adapter.live_hud_calls]
    assert "PRECHECK_CONFIG" in states
    assert "FILL_BASE_INFO" in states
    assert "SELECT_CATEGORY" in states
    assert "SAVE_ONLY" in states
    assert "VERIFY_NOT_PUBLISHED" in states
    select_category = next(call for call in adapter.live_hud_calls if call["step_code"] == "SELECT_CATEGORY")
    assert select_category["human_title"] == "正在选择分类"
    assert select_category["human_action"] == "确认商品分类和属性"
    assert select_category["progress_index"] == 6
    assert select_category["progress_total"] == 12
    save_only = next(call for call in adapter.live_hud_calls if call["step_code"] == "SAVE_ONLY")
    assert save_only["human_title"] == "正在只保存"
    assert save_only["human_action"] == "只点击保存，不发布"
    assert save_only["progress_total"] == 12
    assert save_only["store_name"] == "Dang Kang"
    assert save_only["requires_user_action"] is False

    report = repo.list_reports(task["id"])[0]
    assert report["summary"]["agent_console_events"] == []
    assert report["summary"]["agent_console"] is None
    assert report["summary"]["live_browser_hud_events"]
    assert report["summary"]["live_browser_hud"]["last_step_code"] == "RELEASE_LOCK"
    assert report["summary"]["live_browser_hud"]["hud"]["guard"] == "只保存不发布"
    assert any(
        evidence["meta"].get("live_browser_hud", {}).get("hud", {}).get("human_title") == "正在只保存"
        for evidence in repo.list_evidences(task["id"])
    )


def test_agent_console_sync_failure_does_not_fail_save_flow(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    manager = DummyManager()
    adapter = FakeWorkflowAdapter()
    console = FakeAgentConsole(fail=True)

    asyncio.run(V1TaskRunner(repo, manager, workflow_adapter=adapter, agent_console=console).run_task(task["id"]))

    refreshed = repo.get_task(task["id"])
    report = repo.list_reports(task["id"])[0]
    assert refreshed["status"] == "completed"
    assert report["status"] == "success"
    assert report["published"] is False
    assert report["summary"]["agent_console"]["reason"] == "agent_console_exception"
    assert "console unavailable" in report["summary"]["agent_console"]["last_error"]


def test_execution_defaults_task_payload_overrides_stale_product_media_slots(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    product = repo.list_products()[0]
    product["payload"]["image"]["slots"] = [
        {"slot_key": "marketing_scene_3_4", "strategy": "generate", "label": "(3:4场景图)"},
        {"slot_key": "eu_outer_package", "filename": "product-eu-1.jpg", "label": "外包装/标签实拍图-欧盟"},
    ]
    task["payload"]["image"]["slots"] = [
        {"slot_key": "marketing_scene_3_4", "strategy": "generate", "label": "(3:4场景图)", "filename": "scene-750x1000.jpg"},
        {"slot_key": "eu_outer_package", "filename": "task-eu.jpg", "label": "外包装/标签实拍图-欧盟"},
    ]

    defaults = V1TaskRunner(repo, DummyManager())._execution_defaults(task, product)

    assert defaults["image"]["slots"][0]["filename"] == "scene-750x1000.jpg"
    assert defaults["image"]["slots"][1]["filename"] == "task-eu.jpg"


def test_execution_defaults_only_applies_matching_template_bindings():
    class TemplateRepo:
        def list_templates(self):
            return [
                {
                    "id": 1,
                    "template_type": "category",
                    "template_name": "Other category",
                    "binding_scope": "store/category",
                    "payload": {
                        "binding": {"store_name": "Other Store", "category_name": "运动鞋"},
                        "category": {"category_match": "Shoes"},
                    },
                    "is_enabled": True,
                },
                {
                    "id": 2,
                    "template_type": "category",
                    "template_name": "ACG Stand",
                    "binding_scope": "store/category",
                    "payload": {
                        "binding": {"store_name": "Dang Kang", "category_name": "立牌类谷子"},
                        "category": {
                            "category_keyword": "立牌",
                            "category_match": "ACG Stand",
                            "attribute_template_priorities": ["立牌类谷子"],
                        },
                    },
                    "is_enabled": True,
                },
            ]

    runner = V1TaskRunner(TemplateRepo(), DummyManager())
    defaults = runner._execution_defaults(
        {"payload": {"store_name": "Dang Kang"}},
        {"category_name": "立牌类谷子", "payload": {}},
    )

    assert defaults["category"]["category_match"] == "ACG Stand"
    assert defaults["category"]["attribute_template_priorities"] == ["立牌类谷子"]
    assert defaults["dxm_reference_templates_resolved"]["attribute_info"] == {
        "names": ["立牌类谷子"],
        "required": True,
    }
    assert defaults["_template_trace"] == [
        {
            "template_id": 2,
            "template_type": "category",
            "template_name": "ACG Stand",
            "binding_scope": "store/category",
        }
    ]


def test_execution_defaults_resolves_new_dxm_reference_templates():
    class TemplateRepo:
        def list_templates(self):
            return [
                {
                    "id": 1,
                    "template_type": "dxm_reference",
                    "template_name": "Dxm Reference",
                    "binding_scope": "V1",
                    "payload": {
                        "dxm_reference_templates": {
                            "freight": {"names": ["40g普货包裹"]},
                            "service": {"names": [], "required": False},
                        },
                        "logistics": {
                            "freight_template_priorities": ["旧运费模板"],
                            "service_template_priorities": ["旧服务模板"],
                        },
                    },
                    "is_enabled": True,
                },
            ]

    runner = V1TaskRunner(TemplateRepo(), DummyManager())
    defaults = runner._execution_defaults({"payload": {}}, {"payload": {}})

    assert defaults["dxm_reference_templates_resolved"]["freight"] == {"names": ["40g普货包裹"], "required": True}
    assert defaults["dxm_reference_templates_resolved"]["service"] == {"names": [], "required": False}
    assert defaults["dxm_reference_templates_resolved"]["attribute_info"] == {"names": [], "required": True}


def test_single_save_missing_required_dxm_reference_template_fails_before_save(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    with db.connection() as conn:
        conn.execute(
            "UPDATE templates SET payload_json=? WHERE template_type='category'",
            (
                db.dumps(
                    {
                        "category_name": "模板类目",
                        "dxm_reference_templates": {
                            "attribute_info": {"names": ["立牌类谷子"]},
                            "description": {"names": ["详情模板"]},
                            "freight": {"names": [], "required": True},
                            "service": {"names": ["Service Template for New Sellers"]},
                            "eu_responsible": {"names": ["Jacqueiline Marti"]},
                            "manufacturer": {"names": ["jiyang county thunder"]},
                            "compliance": {"names": ["合规模板"]},
                            "semi_managed": {"names": ["半托管模板"]},
                        },
                        "category": {
                            "template_category_id": "tmpl-cat",
                        },
                    }
                ),
            ),
        )
    manager = DummyManager()
    adapter = FakeWorkflowAdapter()

    asyncio.run(V1TaskRunner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    reports = repo.list_reports(task["id"])
    refreshed = repo.get_task(task["id"])
    assert refreshed["status"] == "failed"
    assert reports[0]["status"] == "failed"
    assert "dxm_reference_templates.freight" in reports[0]["summary"]["blocked_reason"]
    assert "save_only" not in [call[0] for call in adapter.calls]


def test_single_save_report_includes_resolved_dxm_reference_templates(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    with db.connection() as conn:
        conn.execute(
            "UPDATE tasks SET payload_json=? WHERE id=?",
            (
                db.dumps(
                    {
                        **task["payload"],
                        "dxm_reference_templates": {
                            "freight": {"names": ["40g普货包裹"], "required": True},
                            "description": {"names": [], "required": False},
                        },
                    }
                ),
                task["id"],
            ),
        )
    manager = DummyManager()
    adapter = FakeWorkflowAdapter()

    asyncio.run(V1TaskRunner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    reports = repo.list_reports(task["id"])
    assert reports[0]["status"] == "success"
    resolved = reports[0]["summary"]["dxm_reference_templates_resolved"]
    assert resolved["description"] == {"names": [], "required": False}
    assert resolved["freight"] == {"names": ["40g普货包裹"], "required": True}
    reference_results = reports[0]["summary"]["dxm_reference_template_results"]
    assert set(reference_results) == {
        "attribute_info",
        "description",
        "freight",
        "service",
        "eu_responsible",
        "manufacturer",
        "compliance",
        "semi_managed",
    }
    assert reference_results["description"] == {"ok": True, "section": "description", "names": [], "required": False}
    assert reference_results["freight"] == {"ok": True, "section": "freight", "names": ["40g普货包裹"], "required": True}


def test_claim_only_calls_adapter_without_opening_editor_or_saving(v1_db):
    repo = Repository()
    store = repo.create_store("Dang Kang", "AliExpress")
    task = repo.create_acquisition_claim_request({
        "store_id": store["id"],
        "keyword": "Hazbin Hotel 立牌",
        "category_name": "立牌类谷子",
        "source_url": "https://detail.1688.com/offer/from-acquisition.html",
        "claim_mark": "AI认领",
        "template_id": "template-1",
    })
    manager = DummyManager()
    adapter = FakeWorkflowAdapter()

    asyncio.run(V1TaskRunner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    assert adapter.calls == [
        ("check_login_state",),
        ("open_data_acquisition",),
        (
            "claim_from_data_acquisition",
            f"AI认领-{task['id']}",
            "Hazbin Hotel 立牌",
            "立牌类谷子",
            "Dang Kang",
            ["https://detail.1688.com/offer/from-acquisition.html"],
        ),
        (
            "verify_draft_box_claim",
            f"AI认领-{task['id']}",
            "Hazbin Hotel 立牌",
            "立牌类谷子",
            "Dang Kang",
            ["https://detail.1688.com/offer/from-acquisition.html"],
        ),
    ]
    assert not any(call[0] in {"open_editor", "save_only"} for call in adapter.calls)
    reports = repo.list_reports(task["id"])
    assert reports[0]["status"] == "success"
    assert reports[0]["published"] is False
    assert reports[0]["save_result"]["message"] == "采集认领已完成，商品已进入采集箱"
    products = repo.list_products()
    claimed = [product for product in products if product["status"] == "claimed_to_draft"]
    assert len(claimed) == 1
    assert claimed[0]["title"] == "Hazbin Hotel 立牌"
    assert claimed[0]["source"] == "dxm_data_acquisition"
    assert claimed[0]["payload"]["store_id"] == store["id"]
    assert claimed[0]["payload"]["store_name"] == "Dang Kang"
    assert claimed[0]["payload"]["claim_task_id"] == task["id"]
    assert claimed[0]["payload"]["claim_mark"] == f"AI认领-{task['id']}"
    assert claimed[0]["payload"]["source_url"] == "https://detail.1688.com/offer/from-acquisition.html"
    assert claimed[0]["payload"]["source_urls"] == ["https://detail.1688.com/offer/from-acquisition.html"]
    assert claimed[0]["payload"]["data_acquisition_match"] == "source_url"
    assert "数据采集商品行" in claimed[0]["payload"]["data_acquisition_row_text"]
    assert "采集箱商品行" in claimed[0]["payload"]["draft_box_row_text"]
    assert claimed[0]["payload"]["acquisition_search"]["query_source"] == "target_source_url"
    assert reports[0]["product_id"] == claimed[0]["id"]
    assert reports[0]["save_result"]["claimed_product_id"] == claimed[0]["id"]
    assert reports[0]["summary"]["claimed_product"]["id"] == claimed[0]["id"]
    assert "采集箱编辑保存" in reports[0]["summary"]["next_action"]

    refreshed_task = repo.get_task_private(task["id"])
    assert refreshed_task["payload"]["stage"] == "claimed_to_draft"
    assert refreshed_task["payload"]["status"] == "completed"
    assert refreshed_task["payload"]["claimed_product_id"] == claimed[0]["id"]
    assert refreshed_task["payload"]["claimed_product_source_url"] == "https://detail.1688.com/offer/from-acquisition.html"
    assert refreshed_task["payload"]["claimed_product_category_name"] == "立牌类谷子"
    assert refreshed_task["payload"]["draft_box_verified"] is True
    assert "采集箱编辑保存" in refreshed_task["payload"]["next_step"]


def test_claim_only_failure_uses_operator_chinese_detail(v1_db):
    repo = Repository()
    store = repo.create_store("Dang Kang", "AliExpress")
    task = repo.create_acquisition_claim_request({
        "store_id": store["id"],
        "keyword": "Hazbin Hotel 立牌",
        "category_name": "立牌类谷子",
        "source_url": "https://detail.1688.com/offer/from-acquisition.html",
        "claim_mark": "AI认领",
        "template_id": "template-1",
    })
    manager = DummyManager()
    adapter = FakeWorkflowAdapter(fail_action="claim_from_data_acquisition")

    asyncio.run(V1TaskRunner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    report = repo.list_reports(task["id"])[0]
    detail = report["save_result"]["message"]
    blocked_reason = report["summary"]["blocked_reason"]
    refreshed_task = repo.get_task_private(task["id"])
    job_error = refreshed_task["jobs"][0]["error_message"]
    exception = repo.list_exceptions()[0]

    for value in [detail, blocked_reason, job_error, exception["detail"]]:
        assert "数据采集认领" in value
        assert "不会保存或发布" in value
        assert "claim_from_data_acquisition" not in value
        assert "dianxiaomi.com" not in value


def test_claim_only_does_not_record_claimed_product_without_source_url(v1_db):
    class MissingSourceUrlAdapter(FakeWorkflowAdapter):
        def _record(self, action, *args):
            result = super()._record(action, *args)
            if action == "verify_draft_box_claim":
                evidence = result.get("evidence") or {}
                claimed_product = evidence.get("claimed_product") or {}
                claimed_product.pop("source_url", None)
            return result

    repo = Repository()
    store = repo.create_store("Dang Kang", "AliExpress")
    task = repo.create_acquisition_claim_request({
        "store_id": store["id"],
        "keyword": "Hazbin Hotel 立牌",
        "category_name": "立牌类谷子",
        "claim_mark": "AI认领",
        "template_id": "template-1",
    })
    manager = DummyManager()
    adapter = MissingSourceUrlAdapter()

    asyncio.run(V1TaskRunner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    refreshed = repo.get_task_private(task["id"])
    assert refreshed["status"] == "failed"
    assert repo.list_claimed_draft_products() == []
    assert repo.list_products(include_fixtures=True) == []


def test_claim_only_uses_source_url_as_acquisition_query_when_no_keyword(v1_db):
    repo = Repository()
    store = repo.create_store("Dang Kang", "AliExpress")
    source_url = "https://detail.1688.com/offer/from-acquisition.html"
    task = repo.create_acquisition_claim_request({
        "store_id": store["id"],
        "source_url": source_url,
        "claim_mark": "AI认领",
        "template_id": "template-1",
    })
    manager = DummyManager()
    adapter = FakeWorkflowAdapter()

    asyncio.run(V1TaskRunner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    assert adapter.calls[2] == (
        "claim_from_data_acquisition",
        f"AI认领-{task['id']}",
        source_url,
        None,
        "Dang Kang",
        [source_url],
    )
    assert adapter.calls[3] == (
        "verify_draft_box_claim",
        f"AI认领-{task['id']}",
        source_url,
        None,
        "Dang Kang",
        [source_url],
    )


def test_single_save_fails_when_adapter_lacks_media_or_compliance_methods(v1_db):
    class LegacyWorkflowAdapter(FakeWorkflowAdapter):
        fill_media_assets = None
        fill_compliance_defaults = None

    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    manager = DummyManager()
    adapter = LegacyWorkflowAdapter()

    asyncio.run(V1TaskRunner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    reports = repo.list_reports(task["id"])
    assert reports[0]["status"] == "failed"
    assert reports[0]["save_result"]["ok"] is False
    assert "fill_media_assets adapter method unavailable" in reports[0]["save_result"]["message"]
    assert "fill_media_assets adapter method unavailable" in reports[0]["summary"]["blocked_reason"]
    assert "fill_compliance_defaults" not in reports[0]["summary"]["workflow_actions"]


def test_single_save_missing_eu_outer_package_image_config_fails(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    product_id = repo.get_task(task["id"])["jobs"][0]["product_id"]
    with db.connection() as conn:
        conn.execute(
            "UPDATE products SET payload_json=? WHERE id=?",
            (db.dumps({"source_title": "ACG Stand Product 1", "compliance": {"battery": "none"}}), product_id),
        )
        conn.execute(
            "UPDATE templates SET payload_json=? WHERE template_type='image'",
            (db.dumps({"image": {"alt_text": "no eu image"}}),),
        )
        conn.execute(
            "UPDATE tasks SET payload_json=? WHERE id=?",
            (
                db.dumps({
                    **task["payload"],
                    "image": {"alt_text": "task no eu image"},
                }),
                task["id"],
            ),
        )

    manager = DummyManager()
    adapter = FakeWorkflowAdapter()

    asyncio.run(V1TaskRunner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    reports = repo.list_reports(task["id"])
    assert reports[0]["status"] == "failed"
    assert "eu_outer_package" in reports[0]["summary"]["blocked_reason"]


def test_workflow_adapter_failure_fails_job_and_writes_exception_and_report(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    manager = DummyManager()
    adapter = FakeWorkflowAdapter(fail_action="open_editor")

    asyncio.run(V1TaskRunner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    refreshed = repo.get_task(task["id"])
    reports = repo.list_reports(task["id"])
    exceptions = repo.list_exceptions()
    assert refreshed["status"] == "failed"
    assert reports[0]["status"] == "failed"
    assert reports[0]["published"] is False
    assert "open_editor" in reports[0]["summary"]["blocked_reason"]
    assert exceptions[0]["error_code"] == "E901"
    assert exceptions[0]["field_domain"] == "v1_executor"


def test_claim_product_unverified_note_fails_before_open_editor(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    manager = DummyManager()
    adapter = FakeWorkflowAdapter(note_verified=False)

    asyncio.run(V1TaskRunner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    assert ("open_editor", "ACG Stand Product 1", "Dang Kang") not in adapter.calls
    reports = repo.list_reports(task["id"])
    assert reports[0]["status"] == "failed"
    assert "note_verified" in reports[0]["summary"]["blocked_reason"]


def test_save_only_false_save_result_fails_job(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    manager = DummyManager()
    adapter = FakeWorkflowAdapter(save_result={"ok": False, "message": "保存失败", "published": False})

    asyncio.run(V1TaskRunner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    reports = repo.list_reports(task["id"])
    assert reports[0]["status"] == "failed"
    assert reports[0]["published"] is False
    assert "save_result" in reports[0]["summary"]["blocked_reason"]


def test_single_save_runner_rejects_product_that_lost_claimed_status_before_browser(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    product_id = task["payload"]["product_ids"][0]
    with sqlite3.connect(v1_db) as conn:
        conn.execute("UPDATE products SET status='draft' WHERE id=?", (product_id,))
    manager = DummyManager()
    adapter = FakeWorkflowAdapter()

    asyncio.run(V1TaskRunner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    assert adapter.calls == []
    reports = repo.list_reports(task["id"])
    assert reports[0]["status"] == "failed"
    assert "已认领的采集箱商品" in reports[0]["summary"]["blocked_reason"]


def test_single_save_runner_rejects_product_without_draft_box_verification_before_browser(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    product_id = task["payload"]["product_ids"][0]
    with sqlite3.connect(v1_db) as conn:
        row = conn.execute("SELECT payload_json FROM products WHERE id=?", (product_id,)).fetchone()
        payload = json.loads(row[0])
        payload["draft_box_verified"] = False
        conn.execute("UPDATE products SET payload_json=? WHERE id=?", (json.dumps(payload, ensure_ascii=False), product_id))
    manager = DummyManager()
    adapter = FakeWorkflowAdapter()

    asyncio.run(V1TaskRunner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    assert adapter.calls == []
    reports = repo.list_reports(task["id"])
    assert reports[0]["status"] == "failed"
    assert "采集箱验证" in reports[0]["summary"]["blocked_reason"]


def test_save_only_missing_save_result_fails_job(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    manager = DummyManager()
    adapter = FakeWorkflowAdapter(include_save_result=False)

    asyncio.run(V1TaskRunner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    reports = repo.list_reports(task["id"])
    assert reports[0]["status"] == "failed"
    assert reports[0]["published"] is False
    assert "save_result" in reports[0]["summary"]["blocked_reason"]


def test_save_only_failure_report_includes_save_result_reason(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    manager = DummyManager()
    adapter = FakeWorkflowAdapter(
        fail_action="save_only",
        save_result={
            "ok": False,
            "message": "保存按钮已点击但未成功",
            "reason": "未检测到保存成功提示",
            "published": False,
            "network_save_result": {"ok": False, "reason": "未捕获保存相关接口响应"},
            "network_events": [],
        },
    )
    console = FakeAgentConsole()

    asyncio.run(V1TaskRunner(repo, manager, workflow_adapter=adapter, agent_console=console).run_task(task["id"]))

    report = repo.list_reports(task["id"])[0]
    assert report["status"] == "failed"
    assert "未检测到保存成功提示" in report["summary"]["blocked_reason"]
    assert "未捕获保存相关接口响应" in report["summary"]["blocked_reason"]
    assert "保存接口捕获 0 条" in report["summary"]["blocked_reason"]
    assert "未检测到保存成功提示" in report["save_result"]["message"]
    failure_console_call = console.calls[-1]
    assert failure_console_call["step_code"] == "TASK_FAILED"
    assert failure_console_call["severity"] == "error"
    assert failure_console_call["requires_user_action"] is True
    assert "查看结果与问题" in failure_console_call["human_next"]
    failure_live_hud = adapter.live_hud_calls[-1]
    assert failure_live_hud["step_code"] == "TASK_FAILED"
    assert failure_live_hud["severity"] == "error"
    assert failure_live_hud["requires_user_action"] is True
    assert "真实保存不会继续" in failure_live_hud["human_action"]


def test_runner_uses_injected_workflow_executor_for_thread_bound_login_flow(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    manager = DummyManager()
    adapter = ThreadRecordingWorkflowAdapter()

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="dxm-login-flow") as executor:
        asyncio.run(
            V1TaskRunner(
                repo,
                manager,
                workflow_adapter=adapter,
                workflow_executor=executor,
            ).run_task(task["id"])
        )

    assert adapter.thread_names
    assert all(name.startswith("dxm-login-flow") for name in adapter.thread_names)
    assert adapter.hud_thread_names
    assert all(name.startswith("dxm-login-flow") for name in adapter.hud_thread_names)
    assert repo.get_task(task["id"])["status"] == "completed"


def test_single_save_without_workflow_adapter_fails(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    manager = DummyManager()

    asyncio.run(V1TaskRunner(repo, manager).run_task(task["id"]))

    reports = repo.list_reports(task["id"])
    refreshed = repo.get_task(task["id"])
    assert refreshed["status"] == "failed"
    assert reports[0]["status"] == "failed"
    assert "workflow_adapter" in reports[0]["summary"]["blocked_reason"]


def test_batch_save_without_workflow_adapter_fails(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="batch_save", product_count=1)
    manager = DummyManager()

    asyncio.run(V1TaskRunner(repo, manager).run_task(task["id"]))

    reports = repo.list_reports(task["id"])
    refreshed = repo.get_task(task["id"])
    assert refreshed["status"] == "failed"
    assert reports[0]["status"] == "failed"
    assert "workflow_adapter" in reports[0]["summary"]["blocked_reason"]


def test_claim_only_without_workflow_adapter_fails(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="claim_only", product_count=1)
    manager = DummyManager()

    asyncio.run(V1TaskRunner(repo, manager).run_task(task["id"]))

    reports = repo.list_reports(task["id"])
    assert reports[0]["status"] == "failed"
    assert "workflow_adapter" in reports[0]["summary"]["blocked_reason"]


def test_batch_save_runs_jobs_serially_with_independent_reports(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="batch_save", product_count=3)
    manager = DummyManager()

    adapter = FakeWorkflowAdapter()

    asyncio.run(V1TaskRunner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    reports = repo.list_reports(task["id"])
    refreshed = repo.get_task(task["id"])
    assert refreshed["status"] == "completed"
    assert refreshed["completed_jobs"] == 3
    assert refreshed["failed_jobs"] == 0
    assert len(reports) == 3
    assert all(report["published"] is False for report in reports)


def test_forbidden_publish_mode_fails_before_actions(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="publish", product_count=1)
    manager = DummyManager()

    asyncio.run(V1TaskRunner(repo, manager).run_task(task["id"]))

    refreshed = repo.get_task(task["id"])
    exceptions = repo.list_exceptions()
    assert refreshed["status"] == "failed"
    assert exceptions[0]["error_code"] == "E999"


def test_reports_table_exists_after_init(v1_db):
    with sqlite3.connect(v1_db) as conn:
        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='reports'"
        ).fetchone()

    assert table == ("reports",)
