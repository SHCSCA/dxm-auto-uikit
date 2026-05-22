from fastapi.testclient import TestClient

from src import db
from src.main import app
from src.repository import Repository
from src.services import delivery_workspace


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
    }
    assert data["baseline"]["schema"] == "delivery_workspace.v1"
    assert data["current_task"]["id"] == fixture["task"]["id"]
    assert any(step["state"] == "SAVE_ONLY" and step["has_evidence"] and step["has_workflow_result"] for step in data["steps"])
    assert data["report_summary"]["latest_report"]["save_result"]["ok"] is True
    assert data["report_summary"]["latest_report"]["published"] is False
    assert any(point["kind"] == "network_save_result" for point in data["evidence_points"])
    assert any(point["kind"] == "published_proof" for point in data["evidence_points"])
    assert data["evidence_grade"]["grade"] == "A"
    assert [gate["level"] for gate in data["regression_gates"]] == ["L0", "L1", "L2", "L3"]
    assert data["regression_gates"][1]["status"] == "not_run"
    assert data["regression_gates"][2]["status"] == "not_run"
    assert data["regression_gates"][3]["status"] == "passed"
    assert data["safety"]["evidenceGrade"] == "A"
    assert data["dxmReferenceTemplates"][2]["section"] == "freight"
    assert data["dxmReferenceTemplates"][2]["templateNames"] == ["40g普货包裹"]


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

    assert data["evidence_grade"]["grade"] == "B"
    assert data["evidence_grade"]["has_save_result"] is True
    assert data["evidence_grade"]["has_network_or_har_save_response"] is False


def test_delivery_workspace_blocks_publish_network_signal(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    fixture = _create_delivery_fixture(repo, with_network=True, with_publish_network=True)

    data = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}").json()

    assert data["publish_guard_state"]["status"] == "blocked_published_signal"
    assert data["publish_guard_state"]["safe"] is False
    assert data["evidence_grade"]["grade"] == "C"
    assert data["evidence_grade"]["has_publish_risk"] is True


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
    assert data["evidence_grade"]["grade"] == "A"


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
    l2_dir.mkdir()
    l2_json = l2_dir / "data_acquisition_20260522T010203Z.json"
    l2_json.write_text(
        """
        {
          "schema": "dxm_l2_readonly_probe.v1",
          "ok": true,
          "target": "data_acquisition",
          "target_url": "file:///tmp/mock.html",
          "final_url": "file:///tmp/mock.html",
          "created_at": "2026-05-22T01:02:03+00:00",
          "markdown_path": "data/l2_readonly_probe/probe.md",
          "screenshot_path": "data/l2_readonly_probe/probe.png",
          "screenshot_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          "dom_path": "data/l2_readonly_probe/probe.html",
          "dom_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
          "network": {
            "request_count": 1,
            "write_request_count": 0,
            "non_read_request_count": 0,
            "blocked_request_count": 0,
            "forbidden_keyword_request_count": 0,
            "websocket_count": 0
          },
          "safety": {"ok": true, "mode": "L2_READ_ONLY", "reasons": []}
        }
        """,
        encoding="utf-8",
    )
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(delivery_workspace, "L2_PROBE_DIR", l2_dir)
    fixture = _create_delivery_fixture(repo, with_network=False, with_verify_proof=False)

    data = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}").json()

    l2_gate = next(gate for gate in data["regression_gates"] if gate["level"] == "L2")
    assert l2_gate["status"] == "mock_passed"
    assert l2_gate["evidenceLevel"] == "B"
    assert l2_gate["latest"]["json_path"] == str(l2_json)
    assert l2_gate["latest"]["network"]["write_request_count"] == 0


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
