import json

from fastapi.testclient import TestClient

from src.main import app


def test_final_delivery_check_summary_returns_not_run_when_report_missing(tmp_path, monkeypatch):
    import src.main as main

    monkeypatch.setattr(main, "FINAL_DELIVERY_CHECK_JSON", tmp_path / "missing.json")
    client = TestClient(app)

    response = client.get("/api/delivery/final-check")

    assert response.status_code == 200
    assert response.json() == {
        "status": "not_run",
        "summary_path": None,
        "json_path": str(tmp_path / "missing.json"),
    }


def test_final_delivery_check_summary_uses_env_json_path_override(tmp_path, monkeypatch):
    import src.main as main

    default_report = tmp_path / "default" / "final-delivery-check.json"
    override_report = tmp_path / "custom" / "final-delivery-check.json"
    default_report.parent.mkdir()
    override_report.parent.mkdir()
    default_report.write_text(json.dumps({
        "checkedAt": "2026-05-25T09:18:34Z",
        "localWorkbenchCheck": "FAIL",
        "realDxmWriteReadiness": "UNKNOWN",
        "sourcePackageReadiness": "DIRTY",
        "sourcePackageCheck": "NOT_REQUIRED",
        "gitHead": "default-head",
        "artifacts": {"summary": "default.md"},
    }), encoding="utf-8")
    override_report.write_text(json.dumps({
        "checkedAt": "2026-05-25T09:19:34Z",
        "localWorkbenchCheck": "IN_PROGRESS",
        "realDxmWriteReadiness": "BLOCKED",
        "sourcePackageReadiness": "DIRTY",
        "sourcePackageCheck": "NOT_REQUIRED",
        "gitHead": "override-head",
        "artifacts": {"summary": "custom.md"},
    }), encoding="utf-8")
    monkeypatch.setattr(main, "FINAL_DELIVERY_CHECK_JSON", default_report)
    monkeypatch.setenv("DXM_FINAL_DELIVERY_CHECK_JSON", str(override_report))
    monkeypatch.setattr(
        main,
        "_current_git_summary",
        lambda: {
            "head": "override-head",
            "status_short": " M scripts/final-delivery-check.ps1",
            "is_dirty": True,
        },
        raising=False,
    )
    client = TestClient(app)

    response = client.get("/api/delivery/final-check")

    assert response.status_code == 200
    payload = response.json()
    assert payload["json_path"] == str(override_report)
    assert payload["summary_path"] == "custom.md"
    assert payload["real_dxm_write_readiness"] == "BLOCKED"
    assert payload["git_head"] == "override-head"


def test_final_delivery_check_summary_reads_latest_report(tmp_path, monkeypatch):
    import src.main as main

    report_path = tmp_path / "final-delivery-check.json"
    report_path.write_text(json.dumps({
        "checkedAt": "2026-05-25T09:18:34Z",
        "localWorkbenchCheck": "PASS",
        "realDxmWriteReadiness": "BLOCKED",
        "productionRealWriteReady": False,
        "realDxmWriteBlockedReason": "L2 gate is failed; real DXM writes require data_acquisition and draft_box real readonly pass in the same run.",
        "l3EvidenceReadiness": {"ready": False, "missing": ["L3 manual canary evidence missing"]},
        "sourcePackageReadiness": "CLEAN",
        "sourcePackageCheck": "PASS",
        "okScope": "local_workbench_only",
        "realDxmMutationAllowed": False,
        "realModeReleasePlan": {
            "schema": "dxm_real_mode_release_plan.v1",
            "scope": "controlled_single_save_only",
            "publishAllowed": False,
            "batchUnattendedPublishAllowed": False,
            "allowedModes": ["single_save"],
            "blockedModes": ["claim_only", "batch_save"],
            "modes": [
                {"mode": "single_save", "allowed": True},
                {"mode": "claim_only", "allowed": False},
                {"mode": "batch_save", "allowed": False},
            ],
        },
        "expectedRealDxmWriteReadiness": "BLOCKED",
        "realDxmWriteReadinessMatchesExpected": True,
        "requireCleanWorktree": True,
        "gitHead": "abc123",
        "browserQa": {
            "ok": True,
            "checkedAt": "2026-05-25T09:18:33Z",
            "manifest": {"gitHead": "abc123", "gitStatusShort": ""},
            "screenshotHashes": {"qa-report-center.png": "hash"},
        },
        "postFinalReportQa": {
            "ok": True,
            "checkedAt": "2026-05-25T09:18:44Z",
            "screenshotHashes": {"qa-report-center-final.png": "final-hash"},
        },
        "l2AllowlistReviewTemplate": {
            "reviewState": "pending",
            "candidates": [{"decision": "pending"}],
        },
        "l2AllowlistReviewTemplateHashes": {
            "markdown_sha256": "m" * 64,
            "json_sha256": "j" * 64,
        },
        "qaServices": {"isolated": True, "backendPort": 18000, "frontendPort": 15173},
        "artifacts": {
            "summary": "outputs/final-delivery-check/final-delivery-check.md",
            "finalReportCenterScreenshot": "outputs/final-delivery-check/browser-checks/qa-report-center-final.png",
            "postFinalReportQaJson": "outputs/final-delivery-check/browser-checks/qa-final-report-check.json",
            "l2AllowlistReviewTemplateMarkdown": "outputs/final-delivery-check/l2-allowlist-review-template.md",
            "l2AllowlistReviewTemplateJson": "outputs/final-delivery-check/l2-allowlist-review-template.json",
        },
        "gates": {"l2": {"status": "failed"}, "l3": {"status": "blocked"}},
    }), encoding="utf-8")
    monkeypatch.setattr(main, "FINAL_DELIVERY_CHECK_JSON", report_path)
    monkeypatch.setattr(
        main,
        "_current_git_summary",
        lambda: {
            "head": "abc123",
            "status_short": "",
            "is_dirty": False,
        },
        raising=False,
    )
    client = TestClient(app)

    response = client.get("/api/delivery/final-check")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "available"
    assert payload["local_workbench_check"] == "PASS"
    assert payload["real_dxm_write_readiness"] == "BLOCKED"
    assert payload["production_real_write_ready"] is False
    assert payload["real_dxm_write_blocked_reason"].startswith("L2 gate is failed")
    assert payload["l3_evidence_readiness"]["ready"] is False
    assert payload["source_package_readiness"] == "CLEAN"
    assert payload["source_package_check"] == "PASS"
    assert payload["ok_scope"] == "local_workbench_only"
    assert payload["real_dxm_mutation_allowed"] is False
    assert payload["real_mode_release_plan"]["scope"] == "controlled_single_save_only"
    assert payload["real_mode_release_plan"]["blockedModes"] == ["claim_only", "batch_save"]
    assert payload["expected_real_dxm_write_readiness"] == "BLOCKED"
    assert payload["real_dxm_write_readiness_matches_expected"] is True
    assert payload["browser_qa_ok"] is True
    assert payload["browser_qa_checked_at"] == "2026-05-25T09:18:33Z"
    assert payload["browser_qa_git_head"] == "abc123"
    assert payload["browser_qa_git_status_short"] == ""
    assert payload["browser_qa_matches_report_git_head"] is True
    assert payload["browser_qa_screenshot_hashes"] == {"qa-report-center.png": "hash"}
    assert payload["post_final_report_qa_ok"] is True
    assert payload["post_final_report_qa_checked_at"] == "2026-05-25T09:18:44Z"
    assert payload["post_final_report_qa_screenshot_hashes"] == {"qa-report-center-final.png": "final-hash"}
    assert payload["final_report_center_screenshot_path"] == "outputs/final-delivery-check/browser-checks/qa-report-center-final.png"
    assert payload["post_final_report_qa_json_path"] == "outputs/final-delivery-check/browser-checks/qa-final-report-check.json"
    assert payload["l2_allowlist_review_template_state"] == "pending"
    assert payload["l2_allowlist_review_template_candidate_count"] == 1
    assert payload["l2_allowlist_review_template_markdown_path"] == "outputs/final-delivery-check/l2-allowlist-review-template.md"
    assert payload["l2_allowlist_review_template_json_path"] == "outputs/final-delivery-check/l2-allowlist-review-template.json"
    assert payload["l2_allowlist_review_template_markdown_sha256"] == "m" * 64
    assert payload["l2_allowlist_review_template_json_sha256"] == "j" * 64
    assert payload["qa_services"]["isolated"] is True
    assert payload["gates"]["l2"]["status"] == "failed"
    assert payload["summary_path"] == "outputs/final-delivery-check/final-delivery-check.md"
    assert payload["final_check_matches_current_worktree"] is True
    assert payload["final_check_freshness"] == "current"
    assert payload["final_check_runtime_gate_freshness"] in {"current", "stale_gate", "unknown"}


def test_final_delivery_check_summary_marks_ready_report_stale_when_live_l2_expired(tmp_path, monkeypatch):
    import src.main as main

    report_path = tmp_path / "final-delivery-check.json"
    report_path.write_text(json.dumps({
        "checkedAt": "2026-05-25T09:18:34Z",
        "localWorkbenchCheck": "PASS",
        "realDxmWriteReadiness": "READY",
        "realDxmMutationAllowed": True,
        "realDxmMutationScope": "controlled_single_save_only",
        "controlledSingleSaveReady": True,
        "sourcePackageReadiness": "CLEAN",
        "sourcePackageCheck": "PASS",
        "requireCleanWorktree": True,
        "gitHead": "abc123",
        "browserQa": {"ok": True, "manifest": {"gitHead": "abc123", "gitStatusShort": ""}},
        "artifacts": {"summary": "outputs/final-delivery-check/final-delivery-check.md"},
    }), encoding="utf-8")
    monkeypatch.setattr(main, "FINAL_DELIVERY_CHECK_JSON", report_path)
    monkeypatch.setattr(
        main,
        "_current_git_summary",
        lambda: {
            "head": "abc123",
            "status_short": "",
            "is_dirty": False,
        },
        raising=False,
    )
    monkeypatch.setattr(
        main,
        "_current_real_dxm_gate_summary",
        lambda: {
            "readiness": "BLOCKED",
            "blocked_reason": "L2 gate is failed; latest evidence is expired.",
            "l2_status": "failed",
            "l3_status": "blocked",
            "delivery_ready": False,
        },
        raising=False,
    )
    client = TestClient(app)

    response = client.get("/api/delivery/final-check")

    assert response.status_code == 200
    payload = response.json()
    assert payload["real_dxm_write_readiness"] == "READY"
    assert payload["final_check_matches_current_worktree"] is True
    assert payload["final_check_freshness"] == "current"
    assert payload["current_real_dxm_write_readiness"] == "BLOCKED"
    assert payload["final_check_runtime_gate_matches_report"] is False
    assert payload["final_check_runtime_gate_freshness"] == "stale_gate"
    assert payload["effective_real_dxm_write_readiness"] == "BLOCKED"
    assert payload["effective_real_dxm_write_blocked_reason"].startswith("L2 gate is failed")
    assert payload["effective_real_dxm_mutation_allowed"] is False
    assert payload["effective_real_dxm_mutation_scope"] == "none"
    assert payload["effective_real_dxm_write_readiness_matches_expected"] is False


def test_final_delivery_check_summary_flags_stale_report_git_head(tmp_path, monkeypatch):
    import src.main as main

    report_path = tmp_path / "final-delivery-check.json"
    report_path.write_text(json.dumps({
        "checkedAt": "2026-05-25T09:18:34Z",
        "localWorkbenchCheck": "PASS",
        "realDxmWriteReadiness": "BLOCKED",
        "sourcePackageReadiness": "CLEAN",
        "sourcePackageCheck": "PASS",
        "requireCleanWorktree": True,
        "gitHead": "old-head",
        "browserQa": {"ok": True},
        "artifacts": {"summary": "outputs/final-delivery-check/final-delivery-check.md"},
    }), encoding="utf-8")
    monkeypatch.setattr(main, "FINAL_DELIVERY_CHECK_JSON", report_path)
    monkeypatch.setattr(
        main,
        "_current_git_summary",
        lambda: {
            "head": "new-head",
            "status_short": "",
            "is_dirty": False,
        },
        raising=False,
    )
    client = TestClient(app)

    response = client.get("/api/delivery/final-check")

    assert response.status_code == 200
    payload = response.json()
    assert payload["git_head"] == "old-head"
    assert payload["current_git_head"] == "new-head"
    assert payload["current_git_is_dirty"] is False
    assert payload["final_check_matches_current_worktree"] is False
    assert payload["final_check_freshness"] == "stale_head"


def test_final_delivery_check_summary_blocks_effective_ready_when_report_git_head_is_stale(tmp_path, monkeypatch):
    import src.main as main

    report_path = tmp_path / "final-delivery-check.json"
    report_path.write_text(json.dumps({
        "checkedAt": "2026-05-25T09:18:34Z",
        "localWorkbenchCheck": "PASS",
        "realDxmWriteReadiness": "READY",
        "realDxmMutationAllowed": True,
        "realDxmMutationScope": "controlled_single_save_only",
        "sourcePackageReadiness": "CLEAN",
        "sourcePackageCheck": "PASS",
        "requireCleanWorktree": True,
        "gitHead": "old-head",
        "browserQa": {"ok": True, "manifest": {"gitHead": "old-head", "gitStatusShort": ""}},
        "artifacts": {"summary": "outputs/final-delivery-check/final-delivery-check.md"},
    }), encoding="utf-8")
    monkeypatch.setattr(main, "FINAL_DELIVERY_CHECK_JSON", report_path)
    monkeypatch.setattr(
        main,
        "_current_git_summary",
        lambda: {
            "head": "new-head",
            "status_short": "",
            "is_dirty": False,
        },
        raising=False,
    )
    monkeypatch.setattr(
        main,
        "_current_real_dxm_gate_summary",
        lambda: {
            "readiness": "READY",
            "blocked_reason": "",
            "l2_status": "passed",
            "l3_status": "passed",
            "delivery_ready": True,
        },
        raising=False,
    )
    client = TestClient(app)

    response = client.get("/api/delivery/final-check")

    assert response.status_code == 200
    payload = response.json()
    assert payload["real_dxm_write_readiness"] == "READY"
    assert payload["current_real_dxm_write_readiness"] == "READY"
    assert payload["final_check_matches_current_worktree"] is False
    assert payload["final_check_freshness"] == "stale_head"
    assert payload["effective_real_dxm_write_readiness"] == "BLOCKED"
    assert payload["effective_real_dxm_mutation_allowed"] is False
    assert payload["effective_real_dxm_mutation_scope"] == "none"
    assert "最终验收未覆盖当前代码" in payload["effective_real_dxm_write_blocked_reason"]


def test_final_delivery_check_summary_blocks_effective_ready_when_current_worktree_is_dirty(tmp_path, monkeypatch):
    import src.main as main

    report_path = tmp_path / "final-delivery-check.json"
    report_path.write_text(json.dumps({
        "checkedAt": "2026-05-25T09:18:34Z",
        "localWorkbenchCheck": "PASS",
        "realDxmWriteReadiness": "READY",
        "realDxmMutationAllowed": True,
        "realDxmMutationScope": "controlled_single_save_only",
        "sourcePackageReadiness": "CLEAN",
        "sourcePackageCheck": "PASS",
        "requireCleanWorktree": True,
        "gitHead": "abc123",
        "browserQa": {"ok": True, "manifest": {"gitHead": "abc123", "gitStatusShort": ""}},
        "artifacts": {"summary": "outputs/final-delivery-check/final-delivery-check.md"},
    }), encoding="utf-8")
    monkeypatch.setattr(main, "FINAL_DELIVERY_CHECK_JSON", report_path)
    monkeypatch.setattr(
        main,
        "_current_git_summary",
        lambda: {
            "head": "abc123",
            "status_short": " M app/frontend/src/App.tsx",
            "is_dirty": True,
        },
        raising=False,
    )
    monkeypatch.setattr(
        main,
        "_current_real_dxm_gate_summary",
        lambda: {
            "readiness": "READY",
            "blocked_reason": "",
            "l2_status": "passed",
            "l3_status": "passed",
            "delivery_ready": True,
        },
        raising=False,
    )
    client = TestClient(app)

    response = client.get("/api/delivery/final-check")

    assert response.status_code == 200
    payload = response.json()
    assert payload["final_check_matches_current_worktree"] is False
    assert payload["final_check_freshness"] == "dirty_worktree"
    assert payload["effective_real_dxm_write_readiness"] == "BLOCKED"
    assert payload["effective_real_dxm_mutation_allowed"] is False
    assert "最终验收未覆盖当前代码" in payload["effective_real_dxm_write_blocked_reason"]


def test_final_delivery_check_summary_keeps_local_ready_when_dirty_source_package_not_required(tmp_path, monkeypatch):
    import src.main as main

    report_path = tmp_path / "final-delivery-check.json"
    report_path.write_text(json.dumps({
        "checkedAt": "2026-05-25T09:18:34Z",
        "localWorkbenchCheck": "PASS",
        "realDxmWriteReadiness": "READY",
        "realDxmMutationAllowed": True,
        "realDxmMutationScope": "controlled_single_save_only",
        "controlledSingleSaveReady": True,
        "okScope": "local_workbench_and_controlled_single_save_ready",
        "sourcePackageReadiness": "DIRTY",
        "sourcePackageCheck": "NOT_REQUIRED",
        "requireCleanWorktree": False,
        "gitHead": "abc123",
        "browserQa": {"ok": True, "manifest": {"gitHead": "abc123", "gitStatusShort": " M app/frontend/src/App.tsx"}},
        "artifacts": {"summary": "outputs/final-delivery-check/final-delivery-check.md"},
    }), encoding="utf-8")
    monkeypatch.setattr(main, "FINAL_DELIVERY_CHECK_JSON", report_path)
    monkeypatch.setattr(
        main,
        "_current_git_summary",
        lambda: {
            "head": "abc123",
            "status_short": " M app/frontend/src/App.tsx",
            "is_dirty": True,
        },
        raising=False,
    )
    monkeypatch.setattr(
        main,
        "_current_real_dxm_gate_summary",
        lambda: {
            "readiness": "READY",
            "blocked_reason": "",
            "l2_status": "passed",
            "l3_status": "passed",
            "delivery_ready": True,
        },
        raising=False,
    )
    client = TestClient(app)

    response = client.get("/api/delivery/final-check")

    assert response.status_code == 200
    payload = response.json()
    assert payload["final_check_matches_current_worktree"] is False
    assert payload["final_check_freshness"] == "dirty_worktree"
    assert payload["source_package_check"] == "NOT_REQUIRED"
    assert payload["effective_real_dxm_write_readiness"] == "READY"
    assert payload["effective_real_dxm_mutation_allowed"] is True
    assert payload["effective_real_dxm_mutation_scope"] == "controlled_single_save_only"
    assert payload["effective_real_dxm_write_blocked_reason"] in (None, "")
