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


def test_final_delivery_check_summary_reads_latest_report(tmp_path, monkeypatch):
    import src.main as main

    report_path = tmp_path / "final-delivery-check.json"
    report_path.write_text(json.dumps({
        "checkedAt": "2026-05-25T09:18:34Z",
        "localWorkbenchCheck": "PASS",
        "realDxmWriteReadiness": "BLOCKED",
        "sourcePackageReadiness": "CLEAN",
        "sourcePackageCheck": "PASS",
        "requireCleanWorktree": True,
        "gitHead": "abc123",
        "browserQa": {
            "ok": True,
            "checkedAt": "2026-05-25T09:18:33Z",
            "manifest": {"gitHead": "abc123", "gitStatusShort": ""},
            "screenshotHashes": {"qa-report-center.png": "hash"},
        },
        "qaServices": {"isolated": True, "backendPort": 18000, "frontendPort": 15173},
        "artifacts": {"summary": "outputs/final-delivery-check/final-delivery-check.md"},
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
    assert payload["source_package_readiness"] == "CLEAN"
    assert payload["source_package_check"] == "PASS"
    assert payload["browser_qa_ok"] is True
    assert payload["browser_qa_checked_at"] == "2026-05-25T09:18:33Z"
    assert payload["browser_qa_git_head"] == "abc123"
    assert payload["browser_qa_git_status_short"] == ""
    assert payload["browser_qa_matches_report_git_head"] is True
    assert payload["browser_qa_screenshot_hashes"] == {"qa-report-center.png": "hash"}
    assert payload["qa_services"]["isolated"] is True
    assert payload["gates"]["l2"]["status"] == "failed"
    assert payload["summary_path"] == "outputs/final-delivery-check/final-delivery-check.md"
    assert payload["final_check_matches_current_worktree"] is True
    assert payload["final_check_freshness"] == "current"


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
