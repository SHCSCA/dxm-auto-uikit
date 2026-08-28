import asyncio
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from src import db
from src.execution.v1_runner import V1TaskRunner
from src.repository import Repository, TerminalReportConflictError


def _repository(tmp_path, monkeypatch) -> Repository:
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "repository-terminal-transitions.db")
    db.init_db()
    return Repository()


def _create_terminal_task(repo: Repository) -> dict:
    store = repo.create_store("Dang Kang", "AliExpress")
    product = repo.create_product(
        {
            "title": "终态并发测试商品",
            "source": "manual",
            "status": "draft",
            "category_name": "测试类目",
            "price": 0,
            "currency": "USD",
            "sku_count": 1,
            "image_count": 0,
            "payload": {},
        }
    )
    return repo.create_task(
        {
            "name": "终态并发测试任务",
            "store_id": store["id"],
            "mode": "dry_run",
            "publish_scene": "READ_ONLY_PROBE",
            "product_ids": [product["id"]],
            "payload": {},
        }
    )


def test_failed_report_is_immutable_when_late_success_arrives(tmp_path, monkeypatch):
    repo = _repository(tmp_path, monkeypatch)
    task = _create_terminal_task(repo)
    job = repo.get_task_private(task["id"])["jobs"][0]
    repo.add_report(
        task["id"],
        job["id"],
        None,
        "failed",
        False,
        {"ok": False, "error_code": "E901", "message": "确认商品箱超时"},
        {"blocked_reason": "确认商品箱超时"},
    )
    reports_before = repo.list_reports(task["id"])

    with pytest.raises(TerminalReportConflictError) as raised:
        repo.add_report(
            task["id"],
            job["id"],
            99,
            "success",
            False,
            {"ok": True, "message": "晚到成功"},
            {"blocked_reason": None},
        )

    assert raised.value.conflict_code == "REPORT_TERMINAL_STATE_CONFLICT"
    assert repo.list_reports(task["id"]) == reports_before


def test_concurrent_add_report_keeps_one_row_per_task_job(tmp_path, monkeypatch):
    repo = _repository(tmp_path, monkeypatch)
    task = _create_terminal_task(repo)
    job = repo.get_task_private(task["id"])["jobs"][0]
    ready = threading.Barrier(2)

    def write_report(writer: str):
        ready.wait(timeout=5)
        return Repository().add_report(
            task["id"],
            job["id"],
            None,
            "success",
            False,
            {"ok": True, "writer": writer},
            {"writer": writer},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        reports = list(pool.map(write_report, ("left", "right")))

    persisted = repo.list_reports(task["id"])
    assert len(persisted) == 1
    assert {report["id"] for report in reports} == {persisted[0]["id"]}


def test_finalize_job_failure_is_atomic_and_preserves_manual_review_task(tmp_path, monkeypatch):
    repo = _repository(tmp_path, monkeypatch)
    task = _create_terminal_task(repo)
    job = repo.get_task_private(task["id"])["jobs"][0]
    assert repo.try_update_task_status(task["id"], "running", expected_statuses=("draft",))
    repo.update_job(job["id"], status="running")
    assert repo.try_update_task_status(
        task["id"],
        "needs_manual_review",
        expected_statuses=("running",),
    )

    result = repo.finalize_job_failure(
        task["id"],
        job["id"],
        None,
        error_code="E901",
        field_domain="v1_executor",
        title="执行失败",
        detail="保存结果未知",
        suggestion="人工核对店小秘页面。",
        save_result={"ok": False, "error_code": "E901", "message": "保存结果未知"},
        summary={"blocked_reason": "保存结果未知"},
    )

    refreshed = repo.get_task_private(task["id"])
    assert result.applied is True
    assert refreshed["status"] == "needs_manual_review"
    assert refreshed["completed_jobs"] == 0
    assert refreshed["failed_jobs"] == 1
    assert refreshed["jobs"][0]["status"] == "failed"
    assert refreshed["jobs"][0]["error_code"] == "E901"
    reports = repo.list_reports(task["id"])
    assert len(reports) == 1
    assert reports[0]["status"] == "failed"
    exceptions = repo.list_task_exceptions(task["id"])
    assert len(exceptions) == 1
    assert exceptions[0]["error_code"] == "E901"


def test_finalize_job_failure_rolls_back_report_job_and_exception_together(tmp_path, monkeypatch):
    repo = _repository(tmp_path, monkeypatch)
    task = _create_terminal_task(repo)
    job = repo.get_task_private(task["id"])["jobs"][0]
    assert repo.try_update_task_status(task["id"], "running", expected_statuses=("draft",))
    repo.update_job(job["id"], status="running")
    with db.connection() as conn:
        conn.execute(
            """
            CREATE TRIGGER reject_terminal_exception
            BEFORE INSERT ON exceptions
            BEGIN
                SELECT RAISE(ABORT, 'forced atomic rollback');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="forced atomic rollback"):
        repo.finalize_job_failure(
            task["id"],
            job["id"],
            None,
            error_code="E901",
            field_domain="v1_executor",
            title="执行失败",
            detail="保存结果未知",
            suggestion="人工核对店小秘页面。",
            save_result={"ok": False, "error_code": "E901", "message": "保存结果未知"},
            summary={"blocked_reason": "保存结果未知"},
        )

    refreshed = repo.get_task_private(task["id"])
    assert refreshed["status"] == "running"
    assert refreshed["jobs"][0]["status"] == "running"
    assert repo.list_reports(task["id"]) == []
    assert repo.list_task_exceptions(task["id"]) == []


def test_concurrent_job_failure_beats_success_and_task_cannot_revive(tmp_path, monkeypatch):
    repo = _repository(tmp_path, monkeypatch)
    task = _create_terminal_task(repo)
    job = repo.get_task_private(task["id"])["jobs"][0]
    assert repo.try_update_task_status(task["id"], "running", expected_statuses=("draft",))
    repo.update_job(job["id"], status="running")
    ready = threading.Barrier(2)

    def finalize_success():
        ready.wait(timeout=5)
        return Repository().finalize_job_success(
            task["id"],
            job["id"],
            None,
            published=False,
            save_result={"ok": True, "message": "晚到成功"},
            summary={"blocked_reason": None},
        )

    def finalize_failure():
        ready.wait(timeout=5)
        return Repository().finalize_job_failure(
            task["id"],
            job["id"],
            None,
            error_code="E901",
            field_domain="v1_executor",
            title="执行失败",
            detail="保存结果未知",
            suggestion="人工核对店小秘页面。",
            save_result={"ok": False, "error_code": "E901", "message": "保存结果未知"},
            summary={"blocked_reason": "保存结果未知"},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        success_future = pool.submit(finalize_success)
        failure_future = pool.submit(finalize_failure)
        success_result = success_future.result(timeout=10)
        failure_result = failure_future.result(timeout=10)

    refreshed = repo.get_task_private(task["id"])
    assert failure_result.applied is True
    assert refreshed["status"] == "failed"
    assert refreshed["jobs"][0]["status"] == "failed"
    reports = repo.list_reports(task["id"])
    assert len(reports) == 1
    assert reports[0]["status"] == "failed"
    assert repo.try_update_task_status(
        task["id"],
        "completed",
        expected_statuses=("running",),
    ) is False
    late_success = repo.finalize_job_success(
        task["id"],
        job["id"],
        None,
        published=False,
        save_result={"ok": True, "message": "更晚的成功"},
        summary={"blocked_reason": None},
    )
    assert late_success.applied is False
    assert success_result.applied in {True, False}


def test_failure_after_completed_epilogue_reconciles_task_counters(tmp_path, monkeypatch):
    repo = _repository(tmp_path, monkeypatch)
    task = _create_terminal_task(repo)
    job = repo.get_task_private(task["id"])["jobs"][0]
    assert repo.try_update_task_status(task["id"], "running", expected_statuses=("draft",))
    repo.update_job(job["id"], status="running")
    success = repo.finalize_job_success(
        task["id"],
        job["id"],
        None,
        published=False,
        save_result={"ok": True, "message": "先到成功"},
        summary={"blocked_reason": None},
    )
    assert success.applied is True
    assert repo.try_update_task_status(
        task["id"],
        "completed",
        expected_statuses=("running",),
        completed_jobs=1,
        failed_jobs=0,
    )

    failure = repo.finalize_job_failure(
        task["id"],
        job["id"],
        None,
        error_code="E901",
        field_domain="v1_executor",
        title="执行失败",
        detail="成功终结后确认保存结果未知",
        suggestion="人工核对店小秘页面。",
        save_result={"ok": False, "error_code": "E901", "message": "保存结果未知"},
        summary={"blocked_reason": "保存结果未知"},
    )

    refreshed = repo.get_task_private(task["id"])
    assert failure.applied is True
    assert refreshed["status"] == "failed"
    assert refreshed["completed_jobs"] == 0
    assert refreshed["failed_jobs"] == 1
    assert refreshed["jobs"][0]["status"] == "failed"
    assert repo.list_reports(task["id"])[0]["status"] == "failed"


class _RecordingManager:
    def __init__(self) -> None:
        self.events: list[tuple[int, dict]] = []

    async def broadcast(self, task_id, payload):
        self.events.append((task_id, payload))


def test_runner_persists_stable_failure_when_success_report_hits_terminal_report(tmp_path, monkeypatch):
    repo = _repository(tmp_path, monkeypatch)
    import src.execution.v1_runner as v1_runner

    screenshot_dir = tmp_path / "report-conflict-screenshots"
    screenshot_dir.mkdir()
    monkeypatch.setattr(v1_runner, "SCREENSHOT_DIR", screenshot_dir)
    store = repo.create_store("Dang Kang", "AliExpress")
    product = repo.create_product(
        {
            "title": "只读探测商品",
            "source": "manual",
            "status": "draft",
            "category_name": "测试类目",
            "price": 0,
            "currency": "USD",
            "sku_count": 1,
            "image_count": 0,
            "payload": {},
        }
    )
    task = repo.create_task(
        {
            "name": "只读探测任务",
            "store_id": store["id"],
            "mode": "probe",
            "publish_scene": "READ_ONLY_PROBE",
            "product_ids": [product["id"]],
            "payload": {},
        }
    )
    job = repo.get_task_private(task["id"])["jobs"][0]
    repo.add_report(
        task["id"],
        job["id"],
        product["id"],
        "failed",
        False,
        {"ok": False, "error_code": "E901", "message": "既有失败"},
        {"blocked_reason": "既有失败"},
    )
    failed_report = repo.list_reports(task["id"])[0]
    manager = _RecordingManager()

    asyncio.run(V1TaskRunner(repo, manager).run_task(task["id"]))

    refreshed = repo.get_task_private(task["id"])
    assert refreshed["status"] == "failed"
    assert refreshed["jobs"][0]["status"] == "failed"
    assert repo.list_reports(task["id"]) == [failed_report]
    exception = repo.list_exceptions()[0]
    assert exception["error_code"] == "REPORT_TERMINAL_STATE_CONFLICT"
    assert not any(payload.get("status") == "completed" for _, payload in manager.events)
