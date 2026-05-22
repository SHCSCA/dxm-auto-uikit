import asyncio
import sqlite3

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

    def check_login_state(self):
        return self._record("check_login_state")

    def open_draft_box(self):
        return self._record("open_draft_box")

    def claim_product(self, note_text, product_query=None, store_name=None):
        return self._record("claim_product", note_text, product_query, store_name)

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

    def _record(self, action, *args):
        self.calls.append((action, *args))
        evidence = {"action": action}
        if action == "claim_product":
            evidence["note_verified"] = self.note_verified
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
        product = repo.create_product(
            {
                "title": f"ACG Stand Product {idx + 1}",
                "source": "test",
                "category_name": "立牌类谷子",
                "price": 7.01,
                "currency": "USD",
                "sku_count": 8,
                "image_count": 8,
                "payload": {
                    "source_title": f"ACG Stand Product {idx + 1}",
                    "category": {"template_category_id": f"product-cat-{idx + 1}"},
                    "image": {"eu_outer_package_filename": f"product-eu-{idx + 1}.jpg"},
                    "compliance": {"battery": "none"},
                },
            }
        )
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
        ("claim_product", f"AI认领-{task['id']}-{job_id}", "ACG Stand Product 1", "Dang Kang"),
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
    task = _create_task(repo, mode="claim_only", product_count=1)
    job_id = repo.get_task(task["id"])["jobs"][0]["id"]
    manager = DummyManager()
    adapter = FakeWorkflowAdapter()

    asyncio.run(V1TaskRunner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    assert adapter.calls == [
        ("check_login_state",),
        ("open_draft_box",),
        ("claim_product", f"AI认领-{task['id']}-{job_id}", "ACG Stand Product 1", "Dang Kang"),
    ]
    reports = repo.list_reports(task["id"])
    assert reports[0]["status"] == "success"
    assert reports[0]["published"] is False
    assert reports[0]["save_result"]["message"] == "当前模式未执行保存动作"


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
