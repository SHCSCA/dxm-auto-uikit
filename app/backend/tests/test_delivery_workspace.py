import hashlib
import json
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from src import db
from src.main import app
from src.repository import Repository
from src.services import delivery_workspace


def _fresh_l2_created_at(offset_seconds: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)).isoformat()


def _table_signature() -> dict:
    with db.connection() as conn:
        tables = [
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        ]
        return {
            table: conn.execute(f"PRAGMA table_info({table})").fetchall()
            for table in tables
        }


def _create_delivery_fixture(
    repo: Repository,
    *,
    with_network: bool = True,
    with_verify_proof: bool = True,
    with_publish_network: bool = False,
    published_value=False,
) -> dict:
    store = repo.create_store("Dang Kang", "AliExpress")
    product = repo.create_product(
        {
            "title": "ACG Stand Product",
            "source": "test",
            "category_name": "立牌类谷子",
            "price": 7.01,
            "currency": "USD",
            "sku_count": 8,
            "image_count": 8,
            "payload": {"source_title": "ACG Stand Product"},
        }
    )
    task = repo.create_task(
        {
            "name": "交付工作台任务",
            "store_id": store["id"],
            "mode": "single_save",
            "publish_scene": "SMT_SEMI_MANAGED_SAVE_ONLY",
            "claim_mark": "AI认领",
            "product_ids": [product["id"]],
            "payload": {
                "store_name": "Dang Kang",
                "dxm_reference_templates": {
                    "freight": {"names": ["40g普货包裹"], "required": True},
                    "description": {"names": [], "required": False},
                },
            },
        }
    )
    job = repo.get_task(task["id"])["jobs"][0]
    save_result = {
        "ok": True,
        "message": "已点击保存",
        "success_text": "编辑成功",
        "published": False,
    }
    if with_network:
        network_events = [
            {
                "method": "POST",
                "url": "https://www.dianxiaomi.com/api/smt/product/save",
                "status": 200,
            }
        ]
        if with_publish_network:
            network_events.append(
                {
                    "method": "POST",
                    "url": "https://www.dianxiaomi.com/api/smt/product/publish",
                    "status": 200,
                }
            )
        save_result.update(
            {
                "network_save_result": {
                    "ok": True,
                    "method": "POST",
                    "url": "https://www.dianxiaomi.com/api/smt/product/save",
                    "code": 0,
                    "msg": "产品已保存到「待发布」",
                },
                "network_events": network_events,
                "har_summary": {
                    "save_response_seen": True,
                    "path": "data/network_logs/save.har",
                },
            }
        )

    summary = {
        "task_id": task["id"],
        "job_id": job["id"],
        "product_id": product["id"],
        "store_name": "Dang Kang",
        "source_title": "ACG Stand Product",
        "category": "立牌类谷子",
        "claim_mark": f"AI认领-{task['id']}-{job['id']}",
        "mode": "single_save",
        "status": "success",
        "filled_fields": ["base_info", "variants", "media", "compliance", "semi_goods"],
        "empty_fields": ["货品条码：配置允许留空"],
        "evidence_paths": ["data/screenshots/save.txt", "data/screenshots/not_published.txt"],
        "dxm_reference_templates_resolved": {
            "freight": {"names": ["40g普货包裹"], "required": True},
            "description": {"names": [], "required": False},
        },
        "dxm_reference_template_results": {
            "freight": {"ok": True, "section": "freight", "names": ["40g普货包裹"], "required": True},
            "description": {"ok": True, "section": "description", "names": [], "required": False},
        },
        "template_trace": [
            {
                "template_id": 1,
                "template_type": "dxm_reference",
                "template_name": "Dxm Reference",
                "binding_scope": "V1",
            }
        ],
        "workflow_actions": ["save_only", "verify_not_published"],
        "workflow_results": [
            {
                "action": "save_only",
                "ok": True,
                "save_result": save_result,
                "screenshot_url": "/artifacts/screenshots/dianxiaomi_save_only.png",
            },
            {
                "action": "verify_not_published",
                "ok": True,
                "published": published_value,
                "screenshot_url": "/artifacts/screenshots/dianxiaomi_verify_not_published.png",
            },
        ],
        "published": published_value,
    }
    if not with_verify_proof:
        summary["workflow_results"] = [item for item in summary["workflow_results"] if item["action"] != "verify_not_published"]
    repo.add_evidence(
        task["id"],
        job["id"],
        "state_snapshot",
        "data/screenshots/save.txt",
        {"state": "SAVE_ONLY", "field_domain": "save"},
    )
    repo.add_evidence(
        task["id"],
        job["id"],
        "workflow_action",
        "/artifacts/screenshots/dianxiaomi_save_only.png",
        {"state": "SAVE_ONLY", "action": "save_only", "save_result": save_result},
    )
    if with_verify_proof:
        repo.add_evidence(
            task["id"],
            job["id"],
            "workflow_action",
            "/artifacts/screenshots/dianxiaomi_verify_not_published.png",
            {"state": "VERIFY_NOT_PUBLISHED", "action": "verify_not_published", "published": published_value},
        )
    report = repo.add_report(task["id"], job["id"], product["id"], "success", False, save_result, summary)
    return {"task": task, "job": job, "report": report}


def _create_delivery_fixture_with_missing_second_job(repo: Repository) -> dict:
    store = repo.create_store("Dang Kang", "AliExpress")
    products = [
        repo.create_product(
            {
                "title": f"ACG Stand Product {index}",
                "source": "test",
                "category_name": "立牌类谷子",
                "price": 7.01,
                "currency": "USD",
                "sku_count": 8,
                "image_count": 8,
                "payload": {"source_title": f"ACG Stand Product {index}"},
            }
        )
        for index in range(2)
    ]
    task = repo.create_task(
        {
            "name": "交付工作台批量任务",
            "store_id": store["id"],
            "mode": "batch_save",
            "publish_scene": "SMT_SEMI_MANAGED_SAVE_ONLY",
            "claim_mark": "AI认领",
            "product_ids": [product["id"] for product in products],
            "payload": {"store_name": "Dang Kang"},
        }
    )
    first_job = repo.get_task(task["id"])["jobs"][0]
    save_result = {
        "ok": True,
        "message": "已点击保存",
        "success_text": "编辑成功",
        "published": False,
        "network_save_result": {
            "ok": True,
            "method": "POST",
            "url": "https://www.dianxiaomi.com/api/smt/product/save",
            "code": 0,
            "msg": "产品已保存到「待发布」",
        },
        "har_summary": {"save_response_seen": True, "path": "data/network_logs/save.har"},
    }
    summary = {
        "task_id": task["id"],
        "job_id": first_job["id"],
        "product_id": products[0]["id"],
        "mode": "batch_save",
        "status": "success",
        "workflow_results": [
            {"action": "save_only", "ok": True, "save_result": save_result, "screenshot_url": "/artifacts/screenshots/save.png"},
            {"action": "verify_not_published", "ok": True, "published": False, "screenshot_url": "/artifacts/screenshots/not_published.png"},
        ],
        "published": False,
    }
    repo.add_evidence(
        task["id"],
        first_job["id"],
        "workflow_action",
        "/artifacts/screenshots/save.png",
        {"state": "SAVE_ONLY", "action": "save_only", "save_result": save_result},
    )
    repo.add_evidence(
        task["id"],
        first_job["id"],
        "workflow_action",
        "/artifacts/screenshots/not_published.png",
        {"state": "VERIFY_NOT_PUBLISHED", "action": "verify_not_published", "published": False},
    )
    repo.add_report(task["id"], first_job["id"], products[0]["id"], "success", False, save_result, summary)
    return {"task": task, "first_job": first_job}


def _client_with_temp_repo(tmp_path, monkeypatch):
    db_path = tmp_path / "delivery-workspace.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setattr(delivery_workspace, "L1_REPLAY_DIR", tmp_path / "l1_selector_replay")
    monkeypatch.setattr(delivery_workspace, "L2_PROBE_DIR", tmp_path / "l2_readonly_probe")
    db.init_db()
    repo = Repository()
    import src.main as main

    monkeypatch.setattr(main, "repo", repo)
    return TestClient(app), repo


def _write_l2_probe_result(
    directory,
    target: str,
    *,
    target_url: str,
    final_url: str | None = None,
    ok: bool = True,
    created_at: str | None = None,
    network: dict | None = None,
    run_id: str | None = "run-20260526T000000Z",
    script_sha256: str | None = "a" * 64,
    git_head: str | None = "b" * 40,
    cookie_file_sha256: str | None = "c" * 64,
):
    directory.mkdir(parents=True, exist_ok=True)
    created_at = created_at or _fresh_l2_created_at()
    network_payload = {
        "request_count": 1,
        "write_request_count": 0,
        "non_read_request_count": 0,
        "blocked_request_count": 0,
        "forbidden_keyword_request_count": 0,
        "websocket_count": 0,
    }
    if network:
        network_payload.update(network)
    screenshot_path = directory / f"{target}.png"
    dom_path = directory / f"{target}.html"
    screenshot_path.write_bytes(f"{target} screenshot evidence".encode("utf-8"))
    dom_path.write_text(f"<html><body>{target} dom evidence</body></html>", encoding="utf-8")
    path = directory / f"{target}_{created_at.replace(':', '').replace('-', '')}.json"
    payload = {
                "schema": "dxm_l2_readonly_probe.v1",
                "ok": ok,
                "target": target,
                "target_url": target_url,
                "final_url": final_url or target_url,
                "created_at": created_at,
                "markdown_path": f"data/l2_readonly_probe/{target}.md",
                "screenshot_path": str(screenshot_path),
                "screenshot_sha256": hashlib.sha256(screenshot_path.read_bytes()).hexdigest(),
                "dom_path": str(dom_path),
                "dom_sha256": hashlib.sha256(dom_path.read_bytes()).hexdigest(),
                "network": network_payload,
                "login_state": {
                    "required": True,
                    "cookies_loaded": True,
                    "suspected_login_page": False,
                    "signals": [],
                },
                "safety": {
                    "ok": ok,
                    "mode": "L2_READ_ONLY",
                    "reasons": [] if ok else ["blocked by test"],
                },
    }
    if run_id is not None:
        payload["run_id"] = run_id
    if script_sha256 is not None:
        payload["script_sha256"] = script_sha256
    if git_head is not None:
        payload["git_head"] = git_head
    if cookie_file_sha256 is not None:
        payload["cookie_file_sha256"] = cookie_file_sha256
    if any(payload.get(field) is not None for field in ("run_id", "script_sha256", "git_head", "cookie_file_sha256")):
        payload["evidence_binding"] = {
            "schema": "dxm_l2_evidence_binding.v1",
            "run_id": payload.get("run_id"),
            "target_set": ["data_acquisition", "draft_box"],
            "session_fingerprint_sha256": payload.get("cookie_file_sha256"),
            "script_path": "tools/probes/l2_readonly_probe.py",
            "script_sha256": payload.get("script_sha256"),
            "git_head": payload.get("git_head"),
            "git_dirty": False,
            "git_diff_sha256": None,
        }
    path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def test_delivery_workspace_returns_frontend_contract(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    fixture = _create_delivery_fixture(repo, with_network=True)

    response = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}")

    assert response.status_code == 200
    data = response.json()
    assert set(data) >= {
        "baseline",
        "current_task",
        "stores",
        "templates",
        "products",
        "tasks",
        "steps",
        "evidences",
        "evidence_points",
        "reports",
        "report_summary",
        "template_resolution",
        "dxmReferenceTemplates",
        "publish_guard_state",
        "evidence_grade",
        "regression_gates",
        "acceptanceGaps",
        "safety",
        "l2_probe_plan",
    }
    assert data["baseline"]["schema"] == "delivery_workspace.v1"
    assert data["current_task"]["id"] == fixture["task"]["id"]
    assert any(step["state"] == "SAVE_ONLY" and step["has_evidence"] and step["has_workflow_result"] for step in data["steps"])
    assert data["report_summary"]["latest_report"]["save_result"]["ok"] is True
    assert data["report_summary"]["latest_report"]["published"] is False
    assert any(point["kind"] == "network_save_result" for point in data["evidence_points"])
    assert any(point["kind"] == "published_proof" for point in data["evidence_points"])
    for kind in ("save_result", "published_proof", "network_save_result"):
        point = next(point for point in data["evidence_points"] if point["kind"] == kind)
        assert point["task_id"] == fixture["task"]["id"]
        assert point["report_id"] == data["reports"][0]["id"]
    assert data["evidence_grade"]["grade"] == "C"
    assert data["evidence_grade"]["raw_evidence_grade"] == "A"
    assert [gate["level"] for gate in data["regression_gates"]] == ["L0", "L1", "L2", "L3"]
    assert data["regression_gates"][1]["status"] == "not_run"
    assert data["regression_gates"][2]["status"] == "not_run"
    assert data["regression_gates"][3]["status"] == "blocked"
    assert data["safety"]["evidenceGrade"] == "C"
    assert data["dxmReferenceTemplates"][2]["section"] == "freight"
    assert data["dxmReferenceTemplates"][2]["templateNames"] == ["40g普货包裹"]


def test_delivery_workspace_exposes_canonical_l2_probe_plan(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    fixture = _create_delivery_fixture(repo, with_network=False, with_verify_proof=False)

    response = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}")

    assert response.status_code == 200
    plan = response.json()["l2_probe_plan"]
    assert plan["schema"] == "dxm_l2_readonly_probe_plan.v1"
    assert plan["requiresApproval"] is True
    assert plan["runIdCommand"].startswith('$runId = "l2-real-"')
    assert plan["outputDir"] == r"data\l2_readonly_probe"
    assert plan["cookieFile"] == r"data\sessions\dianxiaomi_cookies.json"
    assert [target["id"] for target in plan["targets"]] == ["data_acquisition", "draft_box"]
    assert any("--target data_acquisition" in command and "--run-id $runId" in command for command in plan["commands"])
    assert any("--target draft_box" in command and "--run-id $runId" in command for command in plan["commands"])
    assert all("--cookie-file data\\sessions\\dianxiaomi_cookies.json" in command for command in plan["commands"][1:])
    assert all("--output-dir data\\l2_readonly_probe" in command for command in plan["commands"][1:])
    assert any("同一 run-id" in item for item in plan["acceptanceCriteria"])
    assert any("不自动放行 L3" in item for item in plan["safetyNotes"])


def test_delivery_workspace_evidence_points_are_isolated_to_requested_task(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    requested = _create_delivery_fixture(repo, with_network=True)
    other = _create_delivery_fixture(repo, with_network=True)

    response = client.get(f"/api/delivery/workspace?task_id={requested['task']['id']}")

    assert response.status_code == 200
    data = response.json()
    assert data["current_task"]["id"] == requested["task"]["id"]
    assert data["reports"]
    assert all(report["task_id"] == requested["task"]["id"] for report in data["reports"])
    assert all(point["task_id"] == requested["task"]["id"] for point in data["evidence_points"])
    assert other["task"]["id"] not in {point["task_id"] for point in data["evidence_points"]}
    report_ids = {report["id"] for report in data["reports"]}
    for point in data["evidence_points"]:
        if point["kind"] in {"save_result", "published_proof", "network_save_result", "har_summary"}:
            assert point["report_id"] in report_ids


def test_delivery_workspace_without_task_id_uses_latest_task(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    fixture = _create_delivery_fixture(repo, with_network=True)

    response = client.get("/api/delivery/workspace")

    assert response.status_code == 200
    data = response.json()
    assert data["current_task"]["id"] == fixture["task"]["id"]
    assert data["tasks"][0]["id"] == fixture["task"]["id"]
    assert data["publish_guard_state"]["publish_allowed"] is False


def test_delivery_workspace_exposes_publish_guard_and_dxm_reference_fields(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    fixture = _create_delivery_fixture(repo, with_network=True)

    data = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}").json()

    assert data["publish_guard_state"]["published"] is False
    assert data["publish_guard_state"]["publish_allowed"] is False
    assert data["publish_guard_state"]["status"] == "safe_unpublished"
    assert data["template_resolution"]["dxm_reference_templates_resolved"]["freight"]["names"] == ["40g普货包裹"]
    assert data["template_resolution"]["dxm_reference_template_results"]["description"]["required"] is False
    assert data["report_summary"]["dxm_reference_fields"]["freight"]["resolved"]["required"] is True


def test_delivery_workspace_grades_b_without_network_or_har_save_response(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    fixture = _create_delivery_fixture(repo, with_network=False)

    data = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}").json()

    assert data["evidence_grade"]["grade"] == "C"
    assert data["evidence_grade"]["raw_evidence_grade"] == "B"
    assert data["evidence_grade"]["has_save_result"] is True
    assert data["evidence_grade"]["has_network_or_har_save_response"] is False


def test_delivery_workspace_does_not_treat_generic_ok_as_network_save_response(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    fixture = _create_delivery_fixture(repo, with_network=False)
    report = repo.list_reports(fixture["task"]["id"])[0]
    save_result = report["save_result"]
    save_result["network_save_result"] = {"ok": True}
    repo.add_report(
        fixture["task"]["id"],
        fixture["job"]["id"],
        report["product_id"],
        "success",
        False,
        save_result,
        report["summary"],
    )

    data = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}").json()

    assert data["evidence_grade"]["has_network_or_har_save_response"] is False
    assert not any(point["kind"] == "network_save_result" for point in data["evidence_points"])


def test_delivery_workspace_accepts_dxm_add_json_code_zero_as_save_response(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    fixture = _create_delivery_fixture(repo, with_network=False)
    report = repo.list_reports(fixture["task"]["id"])[0]
    save_result = report["save_result"]
    save_result["network_save_result"] = {
        "ok": True,
        "url": "https://www.dianxiaomi.com/api/popChoiceProduct/add.json",
        "method": "POST",
        "status": 200,
        "code": 0,
        "msg": "您的产品编辑保存成功！",
    }
    save_result["network_events"] = [
        {
            "url": "https://www.dianxiaomi.com/api/popChoiceProduct/add.json",
            "method": "POST",
            "resource_type": "xhr",
            "status": 200,
            "json": {"code": 0, "msg": "您的产品编辑保存成功！"},
        }
    ]
    repo.add_report(
        fixture["task"]["id"],
        fixture["job"]["id"],
        report["product_id"],
        "success",
        False,
        save_result,
        report["summary"],
    )

    data = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}").json()

    assert data["delivery_readiness"]["jobs"][0]["has_network_or_har_save_response"] is True
    assert data["evidence_grade"]["has_network_or_har_save_response"] is True
    assert any(point["kind"] == "network_save_result" for point in data["evidence_points"])


def test_delivery_workspace_marks_acceptance_blocked_when_l2_not_passed(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    fixture = _create_delivery_fixture(repo, with_network=True)

    data = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}").json()

    assert data["evidence_grade"]["grade"] == "C"
    assert data["evidence_grade"]["blocked_by_l2"] is True
    assert data["safety"]["evidenceGrade"] == "C"
    l2_gap = next(gap for gap in data["acceptanceGaps"] if gap["id"] == "gap-l2-real-probe")
    assert l2_gap["severity"] == "blocker"
    assert "L2" in l2_gap["detail"]


def test_delivery_workspace_marks_batch_incomplete_when_any_job_lacks_delivery_evidence(tmp_path, monkeypatch):
    l2_dir = tmp_path / "l2_readonly_probe"
    _write_l2_probe_result(
        l2_dir,
        "data_acquisition",
        target_url="https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
    )
    _write_l2_probe_result(
        l2_dir,
        "draft_box",
        target_url="https://www.dianxiaomi.com/web/smt/smtProductList/draft",
        created_at=_fresh_l2_created_at(-30),
    )
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(delivery_workspace, "L2_PROBE_DIR", l2_dir)
    fixture = _create_delivery_fixture_with_missing_second_job(repo)

    data = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}").json()

    assert data["delivery_readiness"]["ready"] is False
    assert data["delivery_readiness"]["complete_job_count"] == 1
    assert data["delivery_readiness"]["total_job_count"] == 2
    assert data["evidence_grade"]["grade"] == "C"
    assert data["evidence_grade"]["raw_evidence_grade"] == "A"
    l3_gate = next(gate for gate in data["regression_gates"] if gate["level"] == "L3")
    assert l3_gate["status"] == "blocked"
    assert l3_gate["evidenceLevel"] == "C"
    assert "Job" in l3_gate["detail"]
    job_gap = next(gap for gap in data["acceptanceGaps"] if gap["id"].startswith("gap-job-"))
    assert job_gap["severity"] == "blocker"
    assert "缺少" in job_gap["detail"]


def test_delivery_workspace_blocks_publish_network_signal(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    fixture = _create_delivery_fixture(repo, with_network=True, with_publish_network=True)

    data = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}").json()

    assert data["publish_guard_state"]["status"] == "blocked_published_signal"
    assert data["publish_guard_state"]["safe"] is False
    assert data["evidence_grade"]["grade"] == "C"
    assert data["evidence_grade"]["has_publish_risk"] is True


def test_delivery_workspace_ignores_ambient_publish_buttons_in_body_excerpt(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    fixture = _create_delivery_fixture(repo, with_network=True)
    report = repo.list_reports(fixture["task"]["id"])[0]
    summary = report["summary"]
    summary["workflow_results"] = [
        {
            "action": "save_only",
            "fill_result": {
                "body_excerpt": "保存并移入待发布 保存 立即发布",
            },
        }
    ]
    repo.add_report(
        fixture["task"]["id"],
        fixture["job"]["id"],
        report["product_id"],
        "success",
        False,
        report["save_result"],
        summary,
    )

    data = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}").json()

    assert data["publish_guard_state"]["status"] == "safe_unpublished"
    assert data["evidence_grade"]["has_publish_risk"] is False


def test_delivery_workspace_report_published_false_is_not_unpublished_proof_without_verify(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    fixture = _create_delivery_fixture(repo, with_network=True, with_verify_proof=False)

    data = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}").json()

    assert data["publish_guard_state"]["status"] == "waiting_for_unpublished_proof"
    assert data["publish_guard_state"]["safe"] is False
    assert data["evidence_grade"]["grade"] == "C"
    assert data["evidence_grade"]["has_published_proof"] is False


def test_delivery_workspace_parses_published_string_false_as_unpublished(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    fixture = _create_delivery_fixture(repo, with_network=True, published_value="false")

    data = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}").json()

    assert data["publish_guard_state"]["status"] == "safe_unpublished"
    assert data["publish_guard_state"]["safe"] is True
    assert data["evidence_grade"]["grade"] == "C"
    assert data["evidence_grade"]["raw_evidence_grade"] == "A"


def test_delivery_workspace_parses_published_string_true_as_blocked(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    fixture = _create_delivery_fixture(repo, with_network=True, published_value="true")

    data = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}").json()

    assert data["publish_guard_state"]["status"] == "blocked_published_signal"
    assert data["publish_guard_state"]["published"] is True
    assert data["evidence_grade"]["grade"] == "C"


def test_delivery_workspace_does_not_change_db_schema(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    fixture = _create_delivery_fixture(repo, with_network=True)
    before = _table_signature()

    response = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}")

    assert response.status_code == 200
    assert _table_signature() == before


def test_delivery_workspace_exposes_latest_l2_probe_evidence(tmp_path, monkeypatch):
    l2_dir = tmp_path / "l2_readonly_probe"
    l2_json = _write_l2_probe_result(
        l2_dir,
        "data_acquisition",
        target_url="file:///tmp/mock.html",
    )
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(delivery_workspace, "L2_PROBE_DIR", l2_dir)
    fixture = _create_delivery_fixture(repo, with_network=False, with_verify_proof=False)

    data = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}").json()

    l2_gate = next(gate for gate in data["regression_gates"] if gate["level"] == "L2")
    assert l2_gate["status"] == "mock_passed"
    assert l2_gate["evidenceLevel"] == "B"
    assert l2_gate["latest"]["mockTargets"]["data_acquisition"]["json_path"] == str(l2_json)
    assert l2_gate["latest"]["mockTargets"]["data_acquisition"]["network"]["write_request_count"] == 0


def test_delivery_workspace_l2_fails_when_latest_real_targets_fail(tmp_path, monkeypatch):
    l2_dir = tmp_path / "l2_readonly_probe"
    failed_json = _write_l2_probe_result(
        l2_dir,
        "data_acquisition",
        target_url="https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
        final_url="https://www.dianxiaomi.com/web/home?redirected=1",
        ok=False,
        network={"write_request_count": 1, "non_read_request_count": 1, "blocked_request_count": 21},
    )
    failed_payload = json.loads(failed_json.read_text(encoding="utf-8"))
    failed_payload["diagnostics"] = {
        "navigation": {
            "requested_target_path": "/web/productCrawl/dataAcquisition",
            "final_path": "/web/home",
            "left_target_path": True,
            "final_path_class": "home",
        },
        "blocked_request_groups": [
            {
                "count": 21,
                "method": "GET",
                "host": "www.dianxiaomi.com",
                "path": "/api/userInfo.json",
                "resource_type": "xhr",
                "reasons": ["active_or_unknown_resource_type:xhr"],
                "keyword_hits": [],
            }
        ],
    }
    failed_json.write_text(json.dumps(failed_payload), encoding="utf-8")
    _write_l2_probe_result(
        l2_dir,
        "draft_box",
        target_url="https://www.dianxiaomi.com/web/smt/smtProductList/draft",
        ok=False,
        created_at=_fresh_l2_created_at(-30),
        network={"blocked_request_count": 25, "forbidden_keyword_request_count": 5},
    )
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(delivery_workspace, "L2_PROBE_DIR", l2_dir)
    fixture = _create_delivery_fixture(repo, with_network=False, with_verify_proof=False)

    data = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}").json()

    l2_gate = next(gate for gate in data["regression_gates"] if gate["level"] == "L2")
    assert l2_gate["status"] == "failed"
    assert l2_gate["evidenceLevel"] == "C"
    assert set(l2_gate["latest"]["failedTargets"]) == {"data_acquisition", "draft_box"}
    assert l2_gate["latest"]["realTargets"]["data_acquisition"]["network"]["write_request_count"] == 1
    diagnostics = l2_gate["latest"]["realTargets"]["data_acquisition"]["diagnostics"]
    assert diagnostics["navigation"]["left_target_path"] is True
    assert diagnostics["blocked_request_groups"][0]["path"] == "/api/userInfo.json"
    assert diagnostics["allowlist_review_candidates"] == [
        {
            "count": 21,
            "method": "GET",
            "host": "www.dianxiaomi.com",
            "path": "/api/userInfo.json",
            "resource_type": "xhr",
            "reasons": ["active_or_unknown_resource_type:xhr"],
            "keyword_hits": [],
            "review_only": True,
            "allowlist_applied": False,
        }
    ]


def test_delivery_workspace_l2_passes_only_when_both_real_targets_are_clean(tmp_path, monkeypatch):
    l2_dir = tmp_path / "l2_readonly_probe"
    _write_l2_probe_result(
        l2_dir,
        "data_acquisition",
        target_url="https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
    )
    _write_l2_probe_result(
        l2_dir,
        "draft_box",
        target_url="https://www.dianxiaomi.com/web/smt/smtProductList/draft",
        created_at=_fresh_l2_created_at(-30),
    )
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(delivery_workspace, "L2_PROBE_DIR", l2_dir)
    fixture = _create_delivery_fixture(repo, with_network=False, with_verify_proof=False)

    data = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}").json()

    l2_gate = next(gate for gate in data["regression_gates"] if gate["level"] == "L2")
    assert l2_gate["status"] == "passed"
    assert l2_gate["evidenceLevel"] == "A"
    assert set(l2_gate["latest"]["targets"]) == {"data_acquisition", "draft_box"}
    assert l2_gate["latest"]["missingTargets"] == []


def test_delivery_workspace_l2_uses_latest_complete_bound_probe_run(tmp_path, monkeypatch):
    l2_dir = tmp_path / "l2_readonly_probe"
    _write_l2_probe_result(
        l2_dir,
        "data_acquisition",
        target_url="https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
        created_at=_fresh_l2_created_at(-120),
        run_id="run-complete",
    )
    _write_l2_probe_result(
        l2_dir,
        "draft_box",
        target_url="https://www.dianxiaomi.com/web/smt/smtProductList/draft",
        created_at=_fresh_l2_created_at(-90),
        run_id="run-complete",
    )
    _write_l2_probe_result(
        l2_dir,
        "data_acquisition",
        target_url="https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
        created_at=_fresh_l2_created_at(-10),
        run_id="run-partial",
    )
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(delivery_workspace, "L2_PROBE_DIR", l2_dir)
    fixture = _create_delivery_fixture(repo, with_network=False, with_verify_proof=False)

    data = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}").json()

    l2_gate = next(gate for gate in data["regression_gates"] if gate["level"] == "L2")
    assert l2_gate["status"] == "passed"
    assert l2_gate["latest"]["runBinding"]["runIds"] == ["run-complete"]
    assert l2_gate["latest"]["realTargets"]["data_acquisition"]["run_id"] == "run-complete"


def test_delivery_workspace_l2_rejects_missing_or_mismatched_evidence_files(tmp_path, monkeypatch):
    l2_dir = tmp_path / "l2_readonly_probe"
    bad_json = _write_l2_probe_result(
        l2_dir,
        "data_acquisition",
        target_url="https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
    )
    payload = json.loads(bad_json.read_text(encoding="utf-8"))
    payload["screenshot_sha256"] = "0" * 64
    bad_json.write_text(json.dumps(payload), encoding="utf-8")
    _write_l2_probe_result(
        l2_dir,
        "draft_box",
        target_url="https://www.dianxiaomi.com/web/smt/smtProductList/draft",
        created_at=_fresh_l2_created_at(-30),
    )
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(delivery_workspace, "L2_PROBE_DIR", l2_dir)
    fixture = _create_delivery_fixture(repo, with_network=False, with_verify_proof=False)

    data = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}").json()

    l2_gate = next(gate for gate in data["regression_gates"] if gate["level"] == "L2")
    assert l2_gate["status"] == "failed"
    assert l2_gate["latest"]["failedTargets"] == ["data_acquisition"]


def test_delivery_workspace_l3_waits_for_approval_before_evidence_exists(tmp_path, monkeypatch):
    l2_dir = tmp_path / "l2_readonly_probe"
    _write_l2_probe_result(
        l2_dir,
        "data_acquisition",
        target_url="https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
    )
    _write_l2_probe_result(
        l2_dir,
        "draft_box",
        target_url="https://www.dianxiaomi.com/web/smt/smtProductList/draft",
        created_at=_fresh_l2_created_at(-30),
    )
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(delivery_workspace, "L2_PROBE_DIR", l2_dir)
    store = repo.create_store("Dang Kang", "AliExpress")
    product = repo.create_product(
        {
            "title": "Draft Product",
            "source": "test",
            "category_name": "立牌类谷子",
            "price": 7.01,
            "currency": "USD",
            "sku_count": 1,
            "image_count": 1,
            "payload": {},
        }
    )
    task = repo.create_task(
        {
            "name": "未启动真实保存任务",
            "store_id": store["id"],
            "mode": "single_save",
            "publish_scene": "SMT_SEMI_MANAGED_SAVE_ONLY",
            "claim_mark": "AI认领",
            "product_ids": [product["id"]],
            "payload": {"store_name": "Dang Kang"},
        }
    )

    data = client.get(f"/api/delivery/workspace?task_id={task['id']}").json()

    assert data["delivery_readiness"]["has_l3_evidence"] is False
    assert data["evidence_grade"]["blocked_by_job_readiness"] is False
    l3_gate = next(gate for gate in data["regression_gates"] if gate["level"] == "L3")
    assert l3_gate["status"] == "approval_required"


def test_delivery_workspace_l2_rejects_clean_targets_from_different_probe_windows(tmp_path, monkeypatch):
    l2_dir = tmp_path / "l2_readonly_probe"
    _write_l2_probe_result(
        l2_dir,
        "data_acquisition",
        target_url="https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
        created_at=_fresh_l2_created_at(-7200),
    )
    _write_l2_probe_result(
        l2_dir,
        "draft_box",
        target_url="https://www.dianxiaomi.com/web/smt/smtProductList/draft",
        created_at=_fresh_l2_created_at(-30),
    )
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(delivery_workspace, "L2_PROBE_DIR", l2_dir)
    fixture = _create_delivery_fixture(repo, with_network=False, with_verify_proof=False)

    data = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}").json()

    l2_gate = next(gate for gate in data["regression_gates"] if gate["level"] == "L2")
    assert l2_gate["status"] == "failed"
    assert l2_gate["evidenceLevel"] == "C"
    assert "时效要求" in l2_gate["detail"]
    assert l2_gate["latest"]["timeWindow"]["ok"] is False


def test_delivery_workspace_l2_rejects_clean_real_targets_from_different_probe_runs(tmp_path, monkeypatch):
    l2_dir = tmp_path / "l2_readonly_probe"
    _write_l2_probe_result(
        l2_dir,
        "data_acquisition",
        target_url="https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
        run_id="run-a",
    )
    _write_l2_probe_result(
        l2_dir,
        "draft_box",
        target_url="https://www.dianxiaomi.com/web/smt/smtProductList/draft",
        created_at=_fresh_l2_created_at(-30),
        run_id="run-b",
    )
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(delivery_workspace, "L2_PROBE_DIR", l2_dir)
    fixture = _create_delivery_fixture(repo, with_network=False, with_verify_proof=False)

    data = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}").json()

    l2_gate = next(gate for gate in data["regression_gates"] if gate["level"] == "L2")
    assert l2_gate["status"] == "failed"
    assert "同轮次" in l2_gate["detail"]
    assert l2_gate["latest"]["runBinding"]["ok"] is False
    assert l2_gate["latest"]["runBinding"]["runIds"] == ["run-a", "run-b"]


def test_delivery_workspace_l2_rejects_clean_real_targets_without_probe_run_metadata(tmp_path, monkeypatch):
    l2_dir = tmp_path / "l2_readonly_probe"
    _write_l2_probe_result(
        l2_dir,
        "data_acquisition",
        target_url="https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
        run_id=None,
    )
    _write_l2_probe_result(
        l2_dir,
        "draft_box",
        target_url="https://www.dianxiaomi.com/web/smt/smtProductList/draft",
        created_at=_fresh_l2_created_at(-30),
        run_id=None,
    )
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(delivery_workspace, "L2_PROBE_DIR", l2_dir)
    fixture = _create_delivery_fixture(repo, with_network=False, with_verify_proof=False)

    data = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}").json()

    l2_gate = next(gate for gate in data["regression_gates"] if gate["level"] == "L2")
    assert l2_gate["status"] == "failed"
    assert "同轮次" in l2_gate["detail"]
    assert l2_gate["latest"]["runBinding"]["ok"] is False
    assert set(l2_gate["latest"]["runBinding"]["missing"]) == {
        "data_acquisition.run_id",
        "draft_box.run_id",
    }


def test_delivery_workspace_l2_rejects_success_without_safety_login_or_target_path(tmp_path, monkeypatch):
    l2_dir = tmp_path / "l2_readonly_probe"
    unsafe = _write_l2_probe_result(
        l2_dir,
        "data_acquisition",
        target_url="https://www.dianxiaomi.com/web/home",
    )
    payload = json.loads(unsafe.read_text(encoding="utf-8"))
    payload.pop("login_state")
    unsafe.write_text(json.dumps(payload), encoding="utf-8")
    _write_l2_probe_result(
        l2_dir,
        "draft_box",
        target_url="https://www.dianxiaomi.com/web/smt/smtProductList/draft",
        created_at=_fresh_l2_created_at(-30),
    )
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(delivery_workspace, "L2_PROBE_DIR", l2_dir)
    fixture = _create_delivery_fixture(repo, with_network=False, with_verify_proof=False)

    data = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}").json()

    l2_gate = next(gate for gate in data["regression_gates"] if gate["level"] == "L2")
    assert l2_gate["status"] == "failed"
    assert l2_gate["latest"]["failedTargets"] == ["data_acquisition"]


def test_delivery_workspace_l2_rejects_success_when_final_url_leaves_target_path(tmp_path, monkeypatch):
    l2_dir = tmp_path / "l2_readonly_probe"
    _write_l2_probe_result(
        l2_dir,
        "data_acquisition",
        target_url="https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
        final_url="https://www.dianxiaomi.com/web/home?redirected=1",
    )
    _write_l2_probe_result(
        l2_dir,
        "draft_box",
        target_url="https://www.dianxiaomi.com/web/smt/smtProductList/draft",
        created_at=_fresh_l2_created_at(-30),
    )
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(delivery_workspace, "L2_PROBE_DIR", l2_dir)
    fixture = _create_delivery_fixture(repo, with_network=False, with_verify_proof=False)

    data = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}").json()

    l2_gate = next(gate for gate in data["regression_gates"] if gate["level"] == "L2")
    assert l2_gate["status"] == "failed"
    assert l2_gate["latest"]["failedTargets"] == ["data_acquisition"]


def test_delivery_workspace_l2_partial_when_only_one_real_target_is_clean(tmp_path, monkeypatch):
    l2_dir = tmp_path / "l2_readonly_probe"
    _write_l2_probe_result(
        l2_dir,
        "data_acquisition",
        target_url="https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
    )
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(delivery_workspace, "L2_PROBE_DIR", l2_dir)
    fixture = _create_delivery_fixture(repo, with_network=False, with_verify_proof=False)

    data = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}").json()

    l2_gate = next(gate for gate in data["regression_gates"] if gate["level"] == "L2")
    assert l2_gate["status"] == "partial"
    assert l2_gate["evidenceLevel"] == "C"
    assert l2_gate["latest"]["missingTargets"] == ["draft_box"]


def test_delivery_workspace_exposes_latest_l1_replay_evidence(tmp_path, monkeypatch):
    l1_dir = tmp_path / "l1_selector_replay"
    l1_dir.mkdir()
    l1_json = l1_dir / "l1_selector_replay_20260522T010203Z.json"
    l1_json.write_text(
        """
        {
          "schema": "dxm_l1_selector_replay.v1",
          "ok": true,
          "created_at": "2026-05-22T01:02:03+00:00",
          "markdown_path": "data/l1_selector_replay/replay.md",
          "manifest_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          "case_count": 3,
          "passed_count": 3,
          "failed_count": 0,
          "cases": [
            {"id": "draft", "page_key": "smt_draft_list", "ok": true, "failures": []}
          ]
        }
        """,
        encoding="utf-8",
    )
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(delivery_workspace, "L1_REPLAY_DIR", l1_dir)
    fixture = _create_delivery_fixture(repo, with_network=False, with_verify_proof=False)

    data = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}").json()

    l1_gate = next(gate for gate in data["regression_gates"] if gate["level"] == "L1")
    assert l1_gate["status"] == "passed"
    assert l1_gate["evidenceLevel"] == "B"
    assert l1_gate["latest"]["json_path"] == str(l1_json)
    assert l1_gate["latest"]["passed_count"] == 3
