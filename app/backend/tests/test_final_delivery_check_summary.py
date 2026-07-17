import copy
import json

from fastapi.testclient import TestClient

from src.main import app


def _strict_ready_recorded_contracts() -> dict:
    acceptance = {
        "schema": "dxm_two_stage_acceptance.v1",
        "passed": True,
        "status": "passed",
        "claim_task_id": 7,
        "save_task_id": 8,
        "claimed_product_id": 9,
        "missing_codes": [],
        "state_violation_codes": [],
        "checks": {
            "claim_task_present": True,
            "claim_completed": True,
            "save_task_completed": True,
            "claimed_product_present": True,
            "claim_provenance_valid": True,
            "single_save_claim_snapshot_valid": True,
            "claim_product_matches": True,
            "draft_box_verified": True,
            "single_save_linked_to_claim": True,
            "save_success": True,
            "unpublished_proof": True,
            "save_evidence_integrity": True,
            "unpublished_evidence_integrity": True,
            "publish_guard_safe": True,
            "state_consistent": True,
        },
    }
    state_consistency = {
        "schema": "dxm_state_consistency.v1",
        "consistent": True,
        "violation_codes": [],
        "violations": [],
        "audited_task_ids": [7, 8],
    }
    return {
        "schema": "dxm_final_delivery_check.v1",
        "twoStageAcceptance": acceptance,
        "twoStageAcceptanceReadiness": {
            "ready": True,
            "status": "passed",
            "missing": [],
            "acceptance": acceptance,
        },
        "stateConsistency": state_consistency,
        "stateConsistencyReadiness": {
            "ready": True,
            "missing": [],
            "stateConsistency": state_consistency,
        },
    }


def test_current_real_dxm_gate_summary_blocks_ready_when_two_stage_is_false(monkeypatch):
    import src.main as main

    monkeypatch.setattr(
        main,
        "build_delivery_workspace",
        lambda _repo: {
            "regression_gates": [
                {"level": "L2", "status": "passed"},
                {"level": "L3", "status": "passed"},
            ],
            "delivery_readiness": {"ready": True},
            "two_stage_acceptance": {"passed": False, "status": "missing_save_stage"},
        },
    )

    summary = main._current_real_dxm_gate_summary()

    assert summary["readiness"] == "BLOCKED"
    assert summary["two_stage_ready"] is False
    assert summary["two_stage_status"] == "missing_save_stage"
    assert "Two-stage acceptance is not passed" in summary["blocked_reason"]


def test_current_real_dxm_gate_summary_blocks_ready_on_state_contradiction(monkeypatch):
    import src.main as main

    monkeypatch.setattr(
        main,
        "build_delivery_workspace",
        lambda _repo: {
            "regression_gates": [
                {"level": "L2", "status": "passed"},
                {"level": "L3", "status": "passed"},
            ],
            "delivery_readiness": {"ready": True},
            "two_stage_acceptance": {"passed": True, "status": "passed"},
            "state_consistency": {
                "consistent": False,
                "violation_codes": ["STATE_FAILED_JOB_HAS_SUCCESS_REPORT"],
            },
        },
    )

    summary = main._current_real_dxm_gate_summary()

    assert summary["readiness"] == "BLOCKED"
    assert summary["state_consistent"] is False
    assert summary["state_violation_codes"] == [
        "STATE_FAILED_JOB_HAS_SUCCESS_REPORT"
    ]
    assert "STATE_FAILED_JOB_HAS_SUCCESS_REPORT" in summary["blocked_reason"]


def test_current_real_dxm_gate_summary_fails_closed_when_workspace_is_unreadable(monkeypatch):
    import src.main as main

    def unreadable_workspace(_repo):
        raise RuntimeError("workspace unavailable")

    monkeypatch.setattr(main, "build_delivery_workspace", unreadable_workspace)

    summary = main._current_real_dxm_gate_summary()

    assert summary["readiness"] == "BLOCKED"
    assert summary["delivery_ready"] is False
    assert summary["two_stage_ready"] is False
    assert summary["state_consistent"] is False
    assert "不可读取" in summary["blocked_reason"]


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
        "realDxmWriteBlockedReason": "L2 gate is failed; real DXM writes require existing-claim-list and draft-box readonly pass in the same run.",
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
        "stateConsistency": {"consistent": True, "violation_codes": []},
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
        "stateConsistency": {"consistent": True, "violation_codes": []},
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
        "stateConsistency": {"consistent": True, "violation_codes": []},
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
        **_strict_ready_recorded_contracts(),
        "localWorkbenchCheck": "PASS",
        "realDxmWriteReadiness": "READY",
        "realDxmMutationAllowed": True,
        "realDxmMutationScope": "controlled_single_save_only",
        "controlledSingleSaveReady": True,
        "realDxmTwoStageEndToEnd": "passed",
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
            "two_stage_ready": True,
            "two_stage_status": "passed",
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


def test_final_delivery_check_summary_does_not_treat_single_save_ready_as_production_delivery(tmp_path, monkeypatch):
    import src.main as main

    report_path = tmp_path / "final-delivery-check.json"
    report_path.write_text(json.dumps({
        "checkedAt": "2026-06-24T09:18:34Z",
        "localWorkbenchCheck": "PASS",
        "realDxmWriteReadiness": "READY",
        "stateConsistency": {"consistent": True, "violation_codes": []},
        "realDxmMutationAllowed": True,
        "realDxmMutationScope": "controlled_single_save_only",
        "controlledSingleSaveReady": True,
        "realDxmTwoStageEndToEnd": "pending_live_dxm_validation",
        "expectedRealDxmTwoStageEndToEnd": "pending_live_dxm_validation",
        "twoStageAcceptanceMatchesExpected": True,
        "productionDeliveryReady": False,
        "twoStageAcceptance": {
            "passed": False,
            "status": "missing_claim_stage",
            "missing_codes": ["claim_task_missing"],
        },
        "twoStageAcceptanceReadiness": {
            "ready": False,
            "status": "missing_claim_stage",
            "missing": ["claim_task_missing"],
        },
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
            "readiness": "READY",
            "blocked_reason": "",
            "l2_status": "passed",
            "l3_status": "passed",
            "delivery_ready": True,
            "two_stage_ready": False,
            "two_stage_status": "missing_claim_stage",
        },
        raising=False,
    )
    client = TestClient(app)

    response = client.get("/api/delivery/final-check")

    assert response.status_code == 200
    payload = response.json()
    assert payload["effective_real_dxm_write_readiness"] == "BLOCKED"
    assert payload["effective_real_dxm_mutation_allowed"] is False
    assert "Two-stage acceptance" in payload["effective_real_dxm_write_blocked_reason"]
    assert payload["real_dxm_two_stage_end_to_end"] == "pending_live_dxm_validation"
    assert payload["expected_real_dxm_two_stage_end_to_end"] == "pending_live_dxm_validation"
    assert payload["effective_real_dxm_two_stage_end_to_end"] == "pending_live_dxm_validation"
    assert payload["two_stage_acceptance"]["passed"] is False
    assert payload["two_stage_acceptance_readiness"]["ready"] is False
    assert payload["two_stage_acceptance_matches_expected"] is True
    assert payload["current_two_stage_ready"] is False
    assert payload["current_two_stage_status"] == "missing_claim_stage"
    assert payload["production_delivery_ready"] is False
    assert payload["final_delivery_completed"] is False


def test_final_delivery_check_summary_blocks_every_two_stage_report_or_current_contradiction(tmp_path, monkeypatch):
    import src.main as main

    report_path = tmp_path / "final-delivery-check.json"
    monkeypatch.setattr(main, "FINAL_DELIVERY_CHECK_JSON", report_path)
    monkeypatch.setattr(main, "_current_git_summary", lambda: {
        "head": "abc123", "status_short": "", "is_dirty": False,
    })
    base_report = {
        "realDxmWriteReadiness": "READY",
        "realDxmMutationAllowed": True,
        "realDxmMutationScope": "controlled_single_save_only",
        "realDxmTwoStageEndToEnd": "passed",
        "twoStageAcceptance": {"passed": True, "status": "passed"},
        "twoStageAcceptanceReadiness": {"ready": True, "status": "passed"},
        "stateConsistency": {"consistent": True, "violation_codes": []},
        "gitHead": "abc123",
    }
    cases = [
        (
            base_report,
            {"two_stage_ready": False, "two_stage_status": "missing_save_stage"},
        ),
        (
            base_report,
            {"two_stage_ready": True, "two_stage_status": "missing_save_stage"},
        ),
        (
            {
                **base_report,
                "twoStageAcceptance": {"passed": True, "status": "missing_save_stage"},
            },
            {"two_stage_ready": True, "two_stage_status": "passed"},
        ),
        (
            {key: value for key, value in base_report.items() if key != "twoStageAcceptanceReadiness"},
            {"two_stage_ready": True, "two_stage_status": "passed"},
        ),
    ]

    for report, current_two_stage in cases:
        report_path.write_text(json.dumps(report), encoding="utf-8")
        monkeypatch.setattr(main, "_current_real_dxm_gate_summary", lambda current=current_two_stage: {
            "readiness": "READY",
            "blocked_reason": "",
            "l2_status": "passed",
            "l3_status": "passed",
            "delivery_ready": True,
            "state_consistent": True,
            "state_violation_codes": [],
            **current,
        })

        payload = main._read_final_delivery_check_summary()

        assert payload["effective_real_dxm_write_readiness"] == "BLOCKED"
        assert payload["effective_real_dxm_mutation_allowed"] is False
        assert payload["effective_real_dxm_mutation_scope"] == "none"
        assert payload["production_delivery_ready"] is False


def test_final_delivery_check_summary_blocks_legacy_incomplete_ready_report(tmp_path, monkeypatch):
    import src.main as main

    report_path = tmp_path / "final-delivery-check.json"
    report_path.write_text(json.dumps({
        "checkedAt": "2026-06-24T09:18:34Z",
        "localWorkbenchCheck": "PASS",
        "realDxmWriteReadiness": "READY",
        "stateConsistency": {"consistent": True, "violation_codes": []},
        "realDxmMutationAllowed": True,
        "realDxmMutationScope": "controlled_single_save_only",
        "controlledSingleSaveReady": True,
        "realDxmTwoStageEndToEnd": "passed",
        "expectedRealDxmTwoStageEndToEnd": "passed",
        "twoStageAcceptanceMatchesExpected": True,
        "productionDeliveryReady": True,
        "twoStageAcceptance": {
            "passed": True,
            "status": "passed",
            "missing_codes": [],
        },
        "twoStageAcceptanceReadiness": {
            "ready": True,
            "status": "passed",
            "missing": [],
        },
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
            "readiness": "READY",
            "blocked_reason": "",
            "l2_status": "passed",
            "l3_status": "passed",
            "delivery_ready": True,
            "two_stage_ready": True,
            "two_stage_status": "passed",
        },
        raising=False,
    )
    client = TestClient(app)

    response = client.get("/api/delivery/final-check")

    assert response.status_code == 200
    payload = response.json()
    assert payload["real_dxm_two_stage_end_to_end"] == "passed"
    assert payload["expected_real_dxm_two_stage_end_to_end"] == "passed"
    assert payload["effective_real_dxm_two_stage_end_to_end"] == "pending_live_dxm_validation"
    assert payload["two_stage_acceptance"]["passed"] is True
    assert payload["two_stage_acceptance_readiness"]["ready"] is True
    assert payload["two_stage_acceptance_matches_expected"] is True
    assert payload["current_two_stage_ready"] is True
    assert payload["current_two_stage_status"] == "passed"
    assert payload["effective_real_dxm_write_readiness"] == "BLOCKED"
    assert payload["effective_real_dxm_mutation_allowed"] is False
    assert payload["production_delivery_ready"] is False
    assert payload["final_delivery_completed"] is False


def test_final_delivery_check_summary_accepts_complete_strict_recorded_contracts(
    tmp_path,
    monkeypatch,
):
    import src.main as main

    report_path = tmp_path / "final-delivery-check.json"
    report_path.write_text(json.dumps({
        **_strict_ready_recorded_contracts(),
        "realDxmWriteReadiness": "READY",
        "realDxmMutationAllowed": True,
        "realDxmMutationScope": "controlled_single_save_only",
        "realDxmTwoStageEndToEnd": "passed",
        "productionDeliveryReady": True,
        "gitHead": "abc123",
    }), encoding="utf-8")
    monkeypatch.setattr(main, "FINAL_DELIVERY_CHECK_JSON", report_path)
    monkeypatch.setattr(main, "_current_git_summary", lambda: {
        "head": "abc123", "status_short": "", "is_dirty": False,
    })
    monkeypatch.setattr(main, "_current_real_dxm_gate_summary", lambda: {
        "readiness": "READY",
        "blocked_reason": "",
        "l2_status": "passed",
        "l3_status": "passed",
        "delivery_ready": True,
        "two_stage_ready": True,
        "two_stage_status": "passed",
        "state_consistent": True,
        "state_violation_codes": [],
    })

    payload = main._read_final_delivery_check_summary()

    assert payload["effective_real_dxm_write_readiness"] == "READY"
    assert payload["effective_real_dxm_mutation_allowed"] is True
    assert payload["effective_real_dxm_two_stage_end_to_end"] == "passed"
    assert payload["production_delivery_ready"] is True
    assert payload["final_delivery_completed"] is True


def test_final_delivery_check_summary_blocks_each_incomplete_or_contradictory_recorded_contract(
    tmp_path,
    monkeypatch,
):
    import src.main as main

    report_path = tmp_path / "final-delivery-check.json"
    monkeypatch.setattr(main, "FINAL_DELIVERY_CHECK_JSON", report_path)
    monkeypatch.setattr(main, "_current_git_summary", lambda: {
        "head": "abc123", "status_short": "", "is_dirty": False,
    })
    monkeypatch.setattr(main, "_current_real_dxm_gate_summary", lambda: {
        "readiness": "READY",
        "blocked_reason": "",
        "l2_status": "passed",
        "l3_status": "passed",
        "delivery_ready": True,
        "two_stage_ready": True,
        "two_stage_status": "passed",
        "state_consistent": True,
        "state_violation_codes": [],
    })
    base_report = {
        **_strict_ready_recorded_contracts(),
        "realDxmWriteReadiness": "READY",
        "realDxmMutationAllowed": True,
        "realDxmMutationScope": "controlled_single_save_only",
        "realDxmTwoStageEndToEnd": "passed",
        "productionDeliveryReady": True,
        "gitHead": "abc123",
    }
    missing = object()
    cases = [
        ("final schema", ("schema",), "wrong.v1"),
        ("two-stage schema", ("twoStageAcceptance", "schema"), "wrong.v1"),
        ("two-stage passed type", ("twoStageAcceptance", "passed"), "true"),
        ("two-stage status", ("twoStageAcceptance", "status"), "incomplete"),
        ("two-stage missing codes", ("twoStageAcceptance", "missing_codes"), ["missing"]),
        ("two-stage state codes", ("twoStageAcceptance", "state_violation_codes"), ["STATE_X"]),
        ("claim task id", ("twoStageAcceptance", "claim_task_id"), 0),
        ("save task id", ("twoStageAcceptance", "save_task_id"), True),
        ("claimed product id", ("twoStageAcceptance", "claimed_product_id"), -1),
        ("two-stage readiness", ("twoStageAcceptanceReadiness", "ready"), "true"),
        ("two-stage readiness status", ("twoStageAcceptanceReadiness", "status"), "missing"),
        ("two-stage readiness missing", ("twoStageAcceptanceReadiness", "missing"), ["missing"]),
        ("two-stage readiness acceptance", ("twoStageAcceptanceReadiness", "acceptance"), missing),
        ("state schema", ("stateConsistency", "schema"), "wrong.v1"),
        ("state consistent type", ("stateConsistency", "consistent"), 1),
        ("state violation codes", ("stateConsistency", "violation_codes"), ["STATE_X"]),
        ("state violations", ("stateConsistency", "violations"), [{"code": "STATE_X"}]),
        ("state audited ids empty", ("stateConsistency", "audited_task_ids"), []),
        ("state audited ids invalid", ("stateConsistency", "audited_task_ids"), [0]),
        ("state readiness", ("stateConsistencyReadiness", "ready"), False),
        ("state readiness missing", ("stateConsistencyReadiness", "missing"), ["missing"]),
        ("state readiness snapshot", ("stateConsistencyReadiness", "stateConsistency"), missing),
        ("two-stage end-to-end", ("realDxmTwoStageEndToEnd",), missing),
    ]
    for check_name in _strict_ready_recorded_contracts()["twoStageAcceptance"]["checks"]:
        cases.append(
            (
                f"two-stage check {check_name}",
                ("twoStageAcceptance", "checks", check_name),
                False,
            )
        )

    for case_name, path, value in cases:
        report = copy.deepcopy(base_report)
        target = report
        for key in path[:-1]:
            target = target[key]
        if value is missing:
            target.pop(path[-1])
        else:
            target[path[-1]] = value
        report_path.write_text(json.dumps(report), encoding="utf-8")

        payload = main._read_final_delivery_check_summary()

        assert payload["effective_real_dxm_write_readiness"] == "BLOCKED", case_name
        assert payload["effective_real_dxm_mutation_allowed"] is False, case_name
        assert payload["production_delivery_ready"] is False, case_name
        assert payload["final_delivery_completed"] is False, case_name


def test_final_delivery_check_summary_blocks_ready_report_with_inconsistent_state(tmp_path, monkeypatch):
    import src.main as main

    report_path = tmp_path / "final-delivery-check.json"
    inconsistent_state = {
        "schema": "dxm_state_consistency.v1",
        "consistent": False,
        "violation_codes": ["STATE_FAILED_JOB_HAS_SUCCESS_REPORT"],
        "violations": [{"code": "STATE_FAILED_JOB_HAS_SUCCESS_REPORT"}],
        "audited_task_ids": [7, 8],
    }
    report_path.write_text(json.dumps({
        **_strict_ready_recorded_contracts(),
        "checkedAt": "2026-07-15T09:18:34Z",
        "realDxmWriteReadiness": "READY",
        "realDxmMutationAllowed": True,
        "realDxmMutationScope": "controlled_single_save_only",
        "productionDeliveryReady": True,
        "realDxmTwoStageEndToEnd": "passed",
        "stateConsistency": inconsistent_state,
        "stateConsistencyReadiness": {
            "ready": False,
            "missing": ["STATE_FAILED_JOB_HAS_SUCCESS_REPORT"],
            "stateConsistency": inconsistent_state,
        },
        "requireCleanWorktree": True,
        "sourcePackageCheck": "PASS",
        "gitHead": "abc123",
        "artifacts": {"summary": "final.md"},
    }), encoding="utf-8")
    monkeypatch.setattr(main, "FINAL_DELIVERY_CHECK_JSON", report_path)
    monkeypatch.setattr(main, "_current_git_summary", lambda: {
        "head": "abc123", "status_short": "", "is_dirty": False,
    })
    monkeypatch.setattr(main, "_current_real_dxm_gate_summary", lambda: {
        "readiness": "READY",
        "blocked_reason": "",
        "l2_status": "passed",
        "l3_status": "passed",
        "delivery_ready": True,
        "two_stage_ready": True,
        "two_stage_status": "passed",
        "state_consistent": True,
        "state_violation_codes": [],
    })

    payload = TestClient(app).get("/api/delivery/final-check").json()

    assert payload["state_consistency"]["consistent"] is False
    assert payload["effective_real_dxm_write_readiness"] == "BLOCKED"
    assert payload["effective_real_dxm_mutation_allowed"] is False
    assert payload["production_delivery_ready"] is False
    assert "STATE_FAILED_JOB_HAS_SUCCESS_REPORT" in payload["effective_real_dxm_write_blocked_reason"]


def test_final_delivery_check_summary_blocks_ready_report_without_state_consistency(tmp_path, monkeypatch):
    import src.main as main

    report_path = tmp_path / "final-delivery-check.json"
    recorded_contracts = _strict_ready_recorded_contracts()
    recorded_contracts.pop("stateConsistency")
    recorded_contracts.pop("stateConsistencyReadiness")
    report_path.write_text(json.dumps({
        **recorded_contracts,
        "realDxmWriteReadiness": "READY",
        "realDxmMutationAllowed": True,
        "productionDeliveryReady": True,
        "realDxmTwoStageEndToEnd": "passed",
        "gitHead": "abc123",
    }), encoding="utf-8")
    monkeypatch.setattr(main, "FINAL_DELIVERY_CHECK_JSON", report_path)
    monkeypatch.setattr(main, "_current_git_summary", lambda: {
        "head": "abc123", "status_short": "", "is_dirty": False,
    })
    monkeypatch.setattr(main, "_current_real_dxm_gate_summary", lambda: {
        "readiness": "READY",
        "blocked_reason": "",
        "two_stage_ready": True,
        "two_stage_status": "passed",
        "state_consistent": True,
        "state_violation_codes": [],
    })

    payload = main._read_final_delivery_check_summary()

    assert payload["effective_real_dxm_write_readiness"] == "BLOCKED"
    assert payload["effective_real_dxm_mutation_allowed"] is False
    assert payload["production_delivery_ready"] is False
    assert "state consistency unavailable" in payload["effective_real_dxm_write_blocked_reason"]


def test_final_delivery_check_summary_blocks_when_current_runtime_gate_is_unreadable(tmp_path, monkeypatch):
    import src.main as main

    report_path = tmp_path / "final-delivery-check.json"
    report_path.write_text(json.dumps({
        "realDxmWriteReadiness": "READY",
        "realDxmMutationAllowed": True,
        "realDxmMutationScope": "controlled_single_save_only",
        "productionDeliveryReady": True,
        "realDxmTwoStageEndToEnd": "passed",
        "twoStageAcceptance": {"passed": True, "status": "passed"},
        "stateConsistency": {
            "schema": "dxm_state_consistency.v1",
            "consistent": True,
            "violation_codes": [],
            "violations": [],
            "audited_task_ids": [7, 8],
        },
        "gitHead": "abc123",
    }), encoding="utf-8")
    monkeypatch.setattr(main, "FINAL_DELIVERY_CHECK_JSON", report_path)
    monkeypatch.setattr(main, "_current_git_summary", lambda: {
        "head": "abc123", "status_short": "", "is_dirty": False,
    })
    monkeypatch.setattr(main, "_current_real_dxm_gate_summary", lambda: {
        "readiness": None,
        "blocked_reason": "当前运行门禁不可读取；不可依据旧自检报告启动真实写入。",
        "l2_status": None,
        "l3_status": None,
        "delivery_ready": None,
        "two_stage_ready": None,
        "two_stage_status": None,
        "state_consistent": None,
        "state_violation_codes": [],
    })

    payload = main._read_final_delivery_check_summary()

    assert payload["effective_real_dxm_write_readiness"] == "BLOCKED"
    assert payload["effective_real_dxm_mutation_allowed"] is False
    assert payload["production_delivery_ready"] is False
    assert "当前运行门禁不可读取" in payload["effective_real_dxm_write_blocked_reason"]
