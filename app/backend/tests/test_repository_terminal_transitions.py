import asyncio
import base64
import hashlib
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from src import db
from src.core import config
from src.execution.v1_runner import V1TaskRunner
from src.repository import Repository, TerminalReportConflictError
from tests.test_v1_runner import _canonical_test_action_result


_MINIMAL_VALID_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _evidence_ref(name: str) -> dict:
    config.SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = (config.SCREENSHOT_DIR / name).resolve()
    path.write_bytes(_MINIMAL_VALID_PNG)
    return {
        "path": str(path),
        "sha256": hashlib.sha256(_MINIMAL_VALID_PNG).hexdigest().upper(),
        "size": len(_MINIMAL_VALID_PNG),
    }


def _repository(tmp_path, monkeypatch) -> Repository:
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "repository-terminal-transitions.db")
    db.init_db()
    return Repository()


def test_failed_report_is_immutable_when_late_success_arrives(tmp_path, monkeypatch):
    repo = _repository(tmp_path, monkeypatch)
    store = repo.create_store("Dang Kang", "AliExpress")
    task = repo.create_acquisition_claim_request(
        {
            "store_id": store["id"],
            "source_url": "https://detail.1688.com/offer/1013604102950.html",
            "keyword": "真实待认领商品 A",
            "category_name": "立牌类谷子",
            "claim_mark": "AI-OPS",
            "template_id": None,
        }
    )
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
    store = repo.create_store("Dang Kang", "AliExpress")
    task = repo.create_acquisition_claim_request(
        {
            "store_id": store["id"],
            "source_url": "https://detail.1688.com/offer/1013604102950.html",
            "keyword": "真实待认领商品 A",
            "category_name": "立牌类谷子",
            "claim_mark": "AI-OPS",
            "template_id": None,
        }
    )
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
    store = repo.create_store("Dang Kang", "AliExpress")
    task = repo.create_acquisition_claim_request(
        {
            "store_id": store["id"],
            "source_url": "https://detail.1688.com/offer/1013604102950.html",
            "keyword": "真实待认领商品 A",
            "category_name": "立牌类谷子",
            "claim_mark": "AI-OPS",
            "template_id": None,
        }
    )
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
    store = repo.create_store("Dang Kang", "AliExpress")
    task = repo.create_acquisition_claim_request(
        {
            "store_id": store["id"],
            "source_url": "https://detail.1688.com/offer/1013604102950.html",
            "keyword": "真实待认领商品 A",
            "category_name": "立牌类谷子",
            "claim_mark": "AI-OPS",
            "template_id": None,
        }
    )
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
    store = repo.create_store("Dang Kang", "AliExpress")
    task = repo.create_acquisition_claim_request(
        {
            "store_id": store["id"],
            "source_url": "https://detail.1688.com/offer/1013604102950.html",
            "keyword": "真实待认领商品 A",
            "category_name": "立牌类谷子",
            "claim_mark": "AI-OPS",
            "template_id": None,
        }
    )
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
    store = repo.create_store("Dang Kang", "AliExpress")
    task = repo.create_acquisition_claim_request(
        {
            "store_id": store["id"],
            "source_url": "https://detail.1688.com/offer/1013604102950.html",
            "keyword": "真实待认领商品 A",
            "category_name": "立牌类谷子",
            "claim_mark": "AI-OPS",
            "template_id": None,
        }
    )
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


class _LateClaimResultAdapter:
    def __init__(self, repo: Repository, task_id: int, job_id: int, manager: _RecordingManager) -> None:
        self.repo = repo
        self.task_id = task_id
        self.job_id = job_id
        self.manager = manager
        self.failure_snapshot: dict | None = None
        self.reports_snapshot: list[dict] | None = None
        self.exceptions_snapshot: list[dict] | None = None
        self.event_count_at_failure = 0

    def check_login_state(self):
        return self._result("check_login_state")

    def open_data_acquisition(self):
        return self._result("open_data_acquisition")

    def claim_from_data_acquisition(self, claim_mark, **_kwargs):
        return self._result("claim_from_data_acquisition")

    def verify_draft_box_claim(self, claim_mark, **kwargs):
        self.repo.update_task_status(self.task_id, "failed", completed_jobs=0, failed_jobs=1)
        self.repo.update_job(
            self.job_id,
            status="failed",
            current_step_code="FAILED",
            current_step_name="执行失败",
            error_code="E901",
            error_message="确认商品箱超时",
        )
        self.repo.add_exception(
            self.task_id,
            self.job_id,
            "E901",
            "v1_executor",
            "确认商品箱超时",
            "确认商品箱超时",
            "保留现场后重试。",
        )
        self.repo.add_report(
            self.task_id,
            self.job_id,
            None,
            "failed",
            False,
            {"ok": False, "error_code": "E901", "message": "确认商品箱超时"},
            {"blocked_reason": "确认商品箱超时"},
        )
        self.failure_snapshot = self.repo.get_task_private(self.task_id)
        self.reports_snapshot = self.repo.list_reports(self.task_id)
        self.exceptions_snapshot = self.repo.list_exceptions()
        self.event_count_at_failure = len(self.manager.events)
        evidence_ref = _evidence_ref(f"terminal-claim-{self.task_id}.png")
        return self._result(
            "verify_draft_box_claim",
            evidence={
                "claimed_product": {
                    "title": kwargs.get("product_query") or "真实待认领商品 A",
                    "category_name": kwargs.get("category_name") or "立牌类谷子",
                    "source_url": "https://detail.1688.com/offer/1013604102950.html",
                    "row_text": "商品箱商品行",
                },
                "claim_target": {
                    "matchedBy": "source_url",
                    "rowText": "已有待认领商品行",
                    "sourceUrls": ["https://detail.1688.com/offer/1013604102950.html"],
                },
                "draft_box_match": {
                    "matched_by": "source_url",
                    "matched_value": "https://detail.1688.com/offer/1013604102950.html",
                    "raw_matched_by": "source_url",
                    "row_text": f"商品箱商品行 真实待认领商品 A 立牌类谷子 {kwargs.get('store_name') or 'Dang Kang'}",
                    "source_urls": ["https://detail.1688.com/offer/1013604102950.html"],
                    "store_name": kwargs.get("store_name") or "Dang Kang",
                    "store_evidence": {
                        "store_name": kwargs.get("store_name") or "Dang Kang",
                        "cell_text": f"「{kwargs.get('store_name') or 'Dang Kang'}」",
                        "source": "structured_store_cell",
                    },
                    "store_observation": {
                        "observed_store_name": kwargs.get("store_name") or "Dang Kang",
                        "selected": True,
                        "selected_store_names": [kwargs.get("store_name") or "Dang Kang"],
                        "selection_evidence": {"input_checked": True},
                        "draft_box_cell_evidence": {
                            "store_name": kwargs.get("store_name") or "Dang Kang",
                            "cell_text": f"「{kwargs.get('store_name') or 'Dang Kang'}」",
                            "source": "structured_store_cell",
                        },
                    },
                },
                "evidence_ref": evidence_ref,
            },
        )

    def _result(self, action: str, *, evidence: dict | None = None):
        legacy_result = {
            "ok": True,
            "action": action,
            "stage": f"{action}_stage",
            "page_title": "店小秘",
            "page_url": (
                "https://www.dianxiaomi.com/web/smt/smtProductList/draft"
                if action == "verify_draft_box_claim"
                else "https://www.dianxiaomi.com/web/productCrawl/dataAcquisition"
            ),
            "screenshot_url": f"/artifacts/{action}.png",
            "evidence": evidence or {"action": action},
            "product_query": "真实待认领商品 A",
            "store_name": "Dang Kang",
        }
        return _canonical_test_action_result(action, legacy_result)


class _NonTerminalStateConflictAdapter(_LateClaimResultAdapter):
    def verify_draft_box_claim(self, claim_mark, **kwargs):
        self.repo.update_task_status(self.task_id, "paused", completed_jobs=0, failed_jobs=0)
        self.event_count_at_failure = len(self.manager.events)
        evidence_ref = _evidence_ref(f"terminal-paused-claim-{self.task_id}.png")
        return self._result(
            "verify_draft_box_claim",
            evidence={
                "claimed_product": {
                    "title": kwargs.get("product_query") or "真实待认领商品 A",
                    "category_name": kwargs.get("category_name") or "立牌类谷子",
                    "source_url": "https://detail.1688.com/offer/1013604102950.html",
                    "row_text": "商品箱商品行",
                },
                "claim_target": {
                    "matchedBy": "source_url",
                    "rowText": "已有待认领商品行",
                    "sourceUrls": ["https://detail.1688.com/offer/1013604102950.html"],
                },
                "draft_box_match": {
                    "matched_by": "source_url",
                    "matched_value": "https://detail.1688.com/offer/1013604102950.html",
                    "raw_matched_by": "source_url",
                    "row_text": f"商品箱商品行 真实待认领商品 A 立牌类谷子 {kwargs.get('store_name') or 'Dang Kang'}",
                    "source_urls": ["https://detail.1688.com/offer/1013604102950.html"],
                    "store_name": kwargs.get("store_name") or "Dang Kang",
                    "store_evidence": {
                        "store_name": kwargs.get("store_name") or "Dang Kang",
                        "cell_text": f"「{kwargs.get('store_name') or 'Dang Kang'}」",
                        "source": "structured_store_cell",
                    },
                    "store_observation": {
                        "observed_store_name": kwargs.get("store_name") or "Dang Kang",
                        "selected": True,
                        "selected_store_names": [kwargs.get("store_name") or "Dang Kang"],
                        "selection_evidence": {"input_checked": True},
                        "draft_box_cell_evidence": {
                            "store_name": kwargs.get("store_name") or "Dang Kang",
                            "cell_text": f"「{kwargs.get('store_name') or 'Dang Kang'}」",
                            "source": "structured_store_cell",
                        },
                    },
                },
                "evidence_ref": evidence_ref,
            },
        )


def test_claim_runner_stops_without_success_epilogue_when_terminal_transition_rejects(tmp_path, monkeypatch):
    repo = _repository(tmp_path, monkeypatch)
    monkeypatch.setenv("DXM_WORKFLOW_ACTION_RUNTIME", "thread")
    import src.execution.v1_runner as v1_runner

    screenshot_dir = tmp_path / "screenshots"
    screenshot_dir.mkdir()
    monkeypatch.setattr(v1_runner, "SCREENSHOT_DIR", screenshot_dir)
    monkeypatch.setattr(config, "SCREENSHOT_DIR", screenshot_dir)
    store = repo.create_store("Dang Kang", "AliExpress")
    task = repo.create_acquisition_claim_request(
        {
            "store_id": store["id"],
            "source_url": "https://detail.1688.com/offer/1013604102950.html",
            "keyword": "真实待认领商品 A",
            "category_name": "立牌类谷子",
            "claim_mark": "AI-OPS",
            "template_id": None,
        }
    )
    job = repo.get_task_private(task["id"])["jobs"][0]
    manager = _RecordingManager()
    adapter = _LateClaimResultAdapter(repo, task["id"], job["id"], manager)
    products_before = repo.list_products(include_fixtures=True)

    asyncio.run(
        V1TaskRunner(
            repo,
            manager,
            workflow_adapter=adapter,
            authorization_verifier=lambda *_args: {"ok": True, "reason_code": "OK"},
        ).run_task(task["id"])
    )

    assert adapter.failure_snapshot is not None, {
        "task": repo.get_task_private(task["id"]),
        "reports": repo.list_reports(task["id"]),
        "logs": repo.list_logs(task["id"]),
    }
    assert repo.list_products(include_fixtures=True) == products_before
    assert repo.get_task_private(task["id"]) == adapter.failure_snapshot
    assert repo.list_reports(task["id"]) == adapter.reports_snapshot
    assert repo.list_exceptions() == adapter.exceptions_snapshot
    post_rejection_events = [payload for _, payload in manager.events[adapter.event_count_at_failure :]]
    assert not any(
        payload.get("type") == "job_completed" or payload.get("status") == "completed"
        for payload in post_rejection_events
    )
    assert not any(log.get("message") == "V1 商品流程完成" for log in repo.list_logs(task["id"]))


def test_claim_runner_records_nonterminal_transition_rejection_as_failure(tmp_path, monkeypatch):
    repo = _repository(tmp_path, monkeypatch)
    monkeypatch.setenv("DXM_WORKFLOW_ACTION_RUNTIME", "thread")
    import src.execution.v1_runner as v1_runner

    screenshot_dir = tmp_path / "state-conflict-screenshots"
    screenshot_dir.mkdir()
    monkeypatch.setattr(v1_runner, "SCREENSHOT_DIR", screenshot_dir)
    monkeypatch.setattr(config, "SCREENSHOT_DIR", screenshot_dir)
    store = repo.create_store("Dang Kang", "AliExpress")
    task = repo.create_acquisition_claim_request(
        {
            "store_id": store["id"],
            "source_url": "https://detail.1688.com/offer/1013604102950.html",
            "keyword": "真实待认领商品 A",
            "category_name": "立牌类谷子",
            "claim_mark": "AI-OPS",
            "template_id": None,
        }
    )
    job = repo.get_task_private(task["id"])["jobs"][0]
    manager = _RecordingManager()
    adapter = _NonTerminalStateConflictAdapter(repo, task["id"], job["id"], manager)

    asyncio.run(
        V1TaskRunner(
            repo,
            manager,
            workflow_adapter=adapter,
            authorization_verifier=lambda *_args: {"ok": True, "reason_code": "OK"},
        ).run_task(task["id"])
    )

    refreshed = repo.get_task_private(task["id"])
    assert refreshed["status"] == "failed"
    assert refreshed["jobs"][0]["status"] == "failed"
    assert repo.list_products(include_fixtures=True) == []
    assert repo.list_reports(task["id"])[0]["status"] == "failed"
    assert repo.list_exceptions()[0]["error_code"] == "CLAIM_STATE_TRANSITION_CONFLICT"
    assert not any(payload.get("status") == "completed" for _, payload in manager.events)


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


def test_atomic_runner_claim_completion_requires_running_task_and_job(tmp_path, monkeypatch):
    repo = _repository(tmp_path, monkeypatch)
    store = repo.create_store("Dang Kang", "AliExpress")
    task = repo.create_acquisition_claim_request(
        {
            "store_id": store["id"],
            "source_url": "https://detail.1688.com/offer/1013604102950.html",
            "keyword": "真实待认领商品 A",
            "category_name": "立牌类谷子",
            "claim_mark": "AI-OPS",
            "template_id": None,
        }
    )
    task_before = repo.get_task_private(task["id"])

    result = repo.create_claimed_product_and_complete_acquisition(
        task["id"],
        {
            "title": "真实待认领商品 A",
            "source": "dxm_data_acquisition",
            "status": "claimed_to_draft",
            "category_name": "立牌类谷子",
            "price": 0,
            "currency": "USD",
            "sku_count": 1,
            "image_count": 0,
            "payload": {
                "source": "dxm_data_acquisition",
                "store_id": store["id"],
                "source_url": "https://detail.1688.com/offer/1013604102950.html",
                "claim_task_id": task["id"],
                "draft_box_verified": True,
            },
        },
    )

    assert result.applied is False
    assert result.conflict_code == "CLAIM_STATE_TRANSITION_CONFLICT"
    assert repo.get_task_private(task["id"]) == task_before
    assert repo.list_products(include_fixtures=True) == []
