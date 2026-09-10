"""Isolated Path B closed-loop: real FastAPI + Dang Kang fixtures + website replay.

This test wires the production FastAPI, snapshot compiler, V1TaskRunner and
BrowserAgent pipeline to a closed-loop website replay adapter. The adapter
stands in for dianxiaomi.com so the full editor + semi-managed flow runs
without a real browser.

The test deliberately stops before the SAVE_ONLY mutation dispatch because
that boundary requires the production ``real_dxm_write_scope`` /
``real_dxm_write_approval`` ledger, which is a security boundary that must
not be silently bypassed for the isolated closed-loop run.
"""

from __future__ import annotations

import asyncio
import json
from typing import Mapping

import pytest
from fastapi.testclient import TestClient

from src.execution.closed_loop_replay_adapter import (
    CATEGORY_ID,
    PRODUCT_IDS,
    SHOP_ID,
    SHOP_NAME,
    session_ref,
)


PATH_B_PRE_SAVE_ACTIONS = (
    "check_login_state",
    "open_draft_box",
    "open_editor",
    "verify_edit_ownership",
    "fill_editor_required_defaults",
    "fill_editor_variants",
    "fill_media_assets",
    "fill_compliance_defaults",
    "enable_semi_managed",
)


def _plan_payload(refs: list[dict]) -> dict:
    ref_ids = [
        {"ref_id": item["id"], "source_digest": item["source_digest"]}
        for item in refs
    ]
    return {
        "name": "Dang Kang 普货闭环",
        "version": "1.0.0",
        "shop_id": SHOP_ID,
        "category_ids": [CATEGORY_ID],
        "path": "B",
        "configuration_contract": "local_plan_template.v3",
        "status": "ready",
        "scope_contract": "single_target_category.v2",
        "semi_managed": {
            "enabled": True,
            "countries": ["DE", "FR"],
            "goods_config": {"packaging": "general_cargo"},
            "variant_config": {"jit": True},
        },
        "fixed_values": {
            "publish_allowed": False,
            "field_values": {CATEGORY_ID: {}},
        },
        "fill_rules": {
            CATEGORY_ID: {
                "title": {"value": "Car Phone Holder Stand"},
                "material": {"value": "ABS"},
                "semi_packaging": {"value": "general_cargo"},
            }
        },
        "dxm_template_refs": ref_ids,
        "field_mappings": {
            CATEGORY_ID: {
                "mapping_version": "zh-map-100-closed-loop",
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
                        "ui_binding": "dxm_attribute:1001",
                    },
                    {
                        "ui_label_zh": "半托管包装",
                        "field_key": "semi_packaging",
                        "category_schema_path": "$.properties.semi_packaging",
                        "ui_binding": "dxm_editor:semi_packaging",
                    },
                ],
            }
        },
        "validation_policy": {
            "required_fields": "fail_closed",
            "natural_language": "english_before_save",
        },
        "exception_policy": {"unknown": "stop_batch"},
        "provenance": "closed_loop_replay",
    }


@pytest.fixture
def closed_loop_client(tmp_path, monkeypatch):
    data_dir = tmp_path / "closed-loop-data"
    monkeypatch.setenv("DXM_PATH_B_CLOSED_LOOP", "1")
    monkeypatch.setenv("DXM_DATA_DIR", str(data_dir))
    import src.core.config as config

    monkeypatch.setattr(config, "DATA_DIR", data_dir)
    monkeypatch.setattr(config, "SQLITE_DIR", data_dir / "sqlite")
    monkeypatch.setattr(config, "EVIDENCE_DIR", data_dir / "evidences")
    monkeypatch.setattr(config, "SCREENSHOT_DIR", data_dir / "screenshots")
    monkeypatch.setattr(config, "SESSION_DIR", data_dir / "sessions")
    monkeypatch.setattr(config, "AI_DIR", data_dir / "ai")
    from src import db
    from src.execution import closed_loop_replay_adapter as closed_loop_module
    from src.execution import v1_runner as v1_runner_module
    from src.execution.closed_loop_replay_adapter import ClosedLoopReplayAdapter

    db_path = data_dir / "sqlite" / "dxm_auto_uikit.db"
    data_dir.joinpath("sqlite").mkdir(parents=True)
    data_dir.joinpath("screenshots").mkdir(parents=True)
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setattr(v1_runner_module, "SCREENSHOT_DIR", data_dir / "screenshots")
    monkeypatch.setattr(closed_loop_module, "SCREENSHOT_DIR", data_dir / "screenshots")
    db.init_db()
    import src.main as main
    from src.repository import Repository

    adapter = ClosedLoopReplayAdapter()
    repo = Repository()
    monkeypatch.setattr(main, "repo", repo)
    monkeypatch.setattr(main, "workflow_adapter", adapter)
    main.runner.workflow_adapter = adapter
    main.runner.repo = repo
    try:
        main.browser_agent_runtime.reset(adapter)
    except Exception:
        main.browser_agent_runtime.adapter = adapter
    with db.connection() as conn:
        conn.execute(
            """
            INSERT INTO stores (id, name, platform, status, created_at, updated_at)
            VALUES (?, ?, 'AliExpress', 'connected', datetime('now'), datetime('now'))
            """,
            (int(SHOP_ID), SHOP_NAME),
        )
    return TestClient(main.app), main, adapter


def test_closed_loop_reader_only_returns_dang_kang(closed_loop_client):
    """Reader API returns Dang Kang shop and three drafts from isolated DB."""
    client, _main, _adapter = closed_loop_client
    shops = client.get("/api/dxm/draft-reader/shops")
    assert shops.status_code == 200, shops.text
    body = shops.json()
    assert [shop["name"] for shop in body["shops"]] == [SHOP_NAME]
    assert body["session_ref"] == session_ref()
    products = client.get(
        "/api/dxm/draft-reader/products",
        params={"shop_id": SHOP_ID, "page_no": 1, "page_size": 100},
    )
    assert products.status_code == 200, products.text
    assert [item["id"] for item in products.json()["items"]] == list(PRODUCT_IDS)


def test_closed_loop_runs_path_b_through_real_fastapi_runner(closed_loop_client):
    """Path B runs through real FastAPI + Runner up to the SAVE dispatch gate.

    The closed-loop replay adapter substitutes dianxiaomi.com only; FastAPI,
    snapshot compiler, plan templates, BrowserAgent pipeline, V1TaskRunner
    and the publish guard remain production code. The runner walks every
    pre-save action, emits the four mandatory capability receipts and reaches
    the SAVE_ONLY mutation dispatch boundary, which is gated by the
    ``real_dxm_write_scope`` / ``real_dxm_write_approval`` ledger and is
    intentionally not bypassed for the isolated closed-loop run.
    """
    client, main, adapter = closed_loop_client

    synced = client.post(
        "/api/dxm-template-refs/sync",
        json={"shop_id": SHOP_ID, "category_ids": [CATEGORY_ID]},
    )
    assert synced.status_code == 201, synced.text

    created = client.post(
        "/api/local-plan-templates",
        json=_plan_payload(synced.json()["refs"]),
    )
    assert created.status_code == 201, created.text
    template_id = created.json()["id"]

    request = {
        "local_plan_template_id": template_id,
        "shop_id": SHOP_ID,
        "session_ref": session_ref(),
        "product_ids": list(PRODUCT_IDS),
        "target_category_id": CATEGORY_ID,
        "target_category_name": "General Cargo",
        "target_category_match": "General Cargo",
    }
    preview = client.post("/api/plan-snapshots/preview", json=request)
    assert preview.status_code == 200, preview.text
    assert preview.json()["path"] == "B"

    frozen = client.post(
        "/api/plan-snapshots",
        json={
            **request,
            "expected_snapshot_hash": preview.json()["snapshot_hash"],
            "idempotency_key": f"closed-loop-{preview.json()['snapshot_hash'][:24].lower()}",
        },
    )
    assert frozen.status_code == 201, frozen.text

    task_resp = client.post(f"/api/plan-snapshots/{frozen.json()['id']}/tasks")
    assert task_resp.status_code == 201, task_resp.text
    task_id = task_resp.json()["id"]

    started = client.post(
        f"/api/tasks/{task_id}/approve-and-start",
        json={"approved_by": "closed-loop", "confirmation": "CONFIRM_DXM_SAVE_ONLY"},
    )
    assert started.status_code == 200, started.text

    import src.db as _db

    with _db.connection() as conn:
        conn.execute(
            "UPDATE tasks SET payload_json = json_set(payload_json, '$.runner_dispatch', json_object()) "
            "WHERE id = ?",
            (task_id,),
        )

    asyncio.run(main.runner.run_task(task_id))

    assert adapter.calls[: len(PATH_B_PRE_SAVE_ACTIONS)] == list(PATH_B_PRE_SAVE_ACTIONS), (
        "closed-loop replay must walk every pre-save action in canonical order; "
        f"got {adapter.calls!r}"
    )

    pre_save_observations = [
        envelope.get("evidence_observations") or envelope.get("evidence", {}).get("observations") or {}
        for envelope in adapter.envelopes
    ]
    capability_receipts: dict[str, dict] = {}
    for observations in pre_save_observations:
        receipts = observations.get("mandatory_capability_receipts")
        if isinstance(receipts, Mapping):
            capability_receipts.update(receipts)
    for required in ("video", "wholesale", "translation", "rollbackPreparation"):
        assert required in capability_receipts, (
            f"mandatory capability {required} missing from closed-loop observations; "
            f"got {sorted(capability_receipts)!r}"
        )

    section_receipts: dict[str, dict] = {}
    for observations in pre_save_observations:
        sections = observations.get("path_b_section_receipts")
        if isinstance(sections, Mapping):
            section_receipts.update(sections)
    for required in ("basic_info", "attribute_info"):
        assert required in section_receipts, (
            f"section receipt {required} missing from closed-loop observations; "
            f"got {sorted(section_receipts)!r}"
        )

    private = main.repo.get_task_private(task_id)
    assert private["status"] in {"needs_manual_review", "failed"}, (
        "closed-loop runner is expected to stop at the SAVE dispatch gate; "
        "a 'completed' status would imply the scope/approval ledger was "
        "silently bypassed"
    )
    failing_job = private["jobs"][0]
    assert failing_job["status"] in {"failed", "needs_manual_review"}
    assert "AUTH_SNAPSHOT_ROW_AUTHORITY_MISMATCH" in (failing_job["error_message"] or ""), (
        "expected the runner to stop exactly at the mutation scope authority gate; "
        f"got: {failing_job['error_message']!r}"
    )

    closed_loop_calls = sum(
        1 for call in adapter.calls if call in PATH_B_PRE_SAVE_ACTIONS
    )
    assert closed_loop_calls == len(PATH_B_PRE_SAVE_ACTIONS)
    assert adapter.calls.count("save_only") == 0, (
        "closed-loop must not actually dispatch SAVE_ONLY without real mutation scope"
    )

    accepted = json.loads(json.dumps(adapter.accepted_session_refs))
    assert accepted, "closed-loop must have at least one accepted session_ref"
    assert all(ref == session_ref() for ref in accepted)
