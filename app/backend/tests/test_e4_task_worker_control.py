"""E4: task pause/resume/stop = request + worker ack (MVP §5.4 / §7.5)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from src import db
from src.execution.task_worker_control import (
    job_is_dispatchable,
    job_should_skip_on_resume,
    public_worker_control,
)
from src.execution.v1_runner import V1TaskRunner
from src.repository import Repository


class _NullManager:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def broadcast(self, task_id: int, payload: dict) -> None:
        self.events.append({"task_id": task_id, **payload})


def _repo(tmp_path: Path, monkeypatch) -> Repository:
    db_path = tmp_path / "e4-control.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.init_db()
    return Repository()


def _create_batch_task(repo: Repository, *, product_count: int = 3, mode: str = "dry_run") -> dict:
    store = repo.create_store("E4 Shop", "AliExpress")
    product_ids: list[int] = []
    for index in range(product_count):
        product = repo.create_product(
            {
                "title": f"E4 Product {index + 1}",
                "source": "manual",
                "status": "draft",
                "category_name": "Cutting Dies",
                "price": 1.0,
                "currency": "USD",
                "sku_count": 1,
                "image_count": 1,
                "payload": {
                    "store_id": store["id"],
                    "dxm_product_id": f"13065834071222302{index}",
                },
            }
        )
        product_ids.append(product["id"])
    return repo.create_task(
        {
            "name": "E4 control batch",
            "store_id": store["id"],
            "mode": mode,
            "publish_scene": "SMT_SEMI_MANAGED_SAVE_ONLY",
            "product_ids": product_ids,
            "claim_mark": "AI认领",
            "payload": {"execution_mode": mode, "publish_allowed": False},
        }
    )


def test_pause_request_is_not_paused_until_worker_ack(tmp_path, monkeypatch):
    repo = _repo(tmp_path, monkeypatch)
    task = _create_batch_task(repo)
    assert repo.update_task_status(task["id"], "running") is True

    requested = repo.request_pause_task(task["id"])
    assert requested.ok is True
    assert requested.status == "pause_requested"
    assert requested.worker_control["request"] == "pause"
    assert requested.worker_control["ack"] is None
    assert repo.get_task(task["id"])["status"] == "pause_requested"

    # Second pause is idempotent request, still not acked.
    again = repo.request_pause_task(task["id"])
    assert again.ok is True
    assert again.idempotent is True
    assert again.status == "pause_requested"

    acked = repo.acknowledge_pause_task(task["id"], completed_jobs=1, failed_jobs=0)
    assert acked.ok is True
    assert acked.status == "paused"
    assert acked.worker_control["ack"] == "paused"
    assert acked.worker_control["request"] is None
    stored = repo.get_task_private(task["id"])
    assert stored["status"] == "paused"
    assert stored["completed_jobs"] == 1
    public = public_worker_control(stored["payload"].get("worker_control"))
    assert public["pending"] is False
    assert public["ack"] == "paused"


def test_resume_rejects_until_paused_then_rediscovers_runner(tmp_path, monkeypatch):
    repo = _repo(tmp_path, monkeypatch)
    task = _create_batch_task(repo)
    repo.update_task_status(task["id"], "running")
    repo.request_pause_task(task["id"])

    blocked = repo.request_resume_task(task["id"])
    assert blocked.ok is False
    assert blocked.reason_code == "PAUSE_ACK_REQUIRED"

    repo.acknowledge_pause_task(task["id"], completed_jobs=1)
    resumed = repo.request_resume_task(task["id"])
    assert resumed.ok is True
    assert resumed.status == "running"
    private = repo.get_task_private(task["id"])
    assert private["status"] == "running"
    dispatch = private["payload"].get("runner_dispatch") or {}
    assert dispatch.get("claimed") is False


def test_stop_request_acks_without_dispatching_remaining_jobs(tmp_path, monkeypatch):
    repo = _repo(tmp_path, monkeypatch)
    task = _create_batch_task(repo, product_count=3)
    repo.update_task_status(task["id"], "running")
    jobs = repo.get_task(task["id"])["jobs"]
    # First job already saved.
    repo.update_job(jobs[0]["id"], status="completed", current_step_code="DONE", current_step_name="已保存")

    stop = repo.request_stop_task(task["id"])
    assert stop.ok is True
    assert stop.status == "stop_requested"

    ack = repo.acknowledge_stop_task(task["id"], completed_jobs=1, failed_jobs=0)
    assert ack.ok is True
    assert ack.status == "stopped"
    final = repo.get_task(task["id"])
    assert final["status"] == "stopped"
    assert final["completed_jobs"] == 1
    remaining = [job for job in final["jobs"] if job["id"] != jobs[0]["id"]]
    assert all(job["status"] == "pending" for job in remaining)
    assert all((job.get("current_step_name") or "").startswith("已停止") or job["status"] == "pending" for job in remaining)


def test_job_skip_helpers_for_resume():
    assert job_should_skip_on_resume({"status": "completed"}) is True
    assert job_should_skip_on_resume({"status": "succeeded"}) is True
    assert job_should_skip_on_resume({"status": "failed"}) is True
    assert job_should_skip_on_resume({"status": "unknown"}) is True
    assert job_should_skip_on_resume({"status": "pending"}) is False
    assert job_is_dispatchable({"status": "pending"}) is True
    assert job_is_dispatchable({"status": "running"}) is True
    assert job_is_dispatchable({"status": "completed"}) is False


def test_runner_safe_point_pause_ack_and_resume_skips_completed(tmp_path, monkeypatch):
    repo = _repo(tmp_path, monkeypatch)
    task = _create_batch_task(repo, product_count=3, mode="dry_run")
    task_id = task["id"]
    repo.update_task_status(task_id, "running")
    jobs = repo.get_task(task_id)["jobs"]
    repo.update_job(jobs[0]["id"], status="completed", current_step_code="DONE", current_step_name="已保存")
    repo.update_task_status(task_id, "running", completed_jobs=1, failed_jobs=0)

    manager = _NullManager()
    runner = V1TaskRunner(repo=repo, manager=manager, workflow_adapter=None)

    # Simulate operator pause while runner is between products.
    assert repo.request_pause_task(task_id).ok is True
    status = asyncio.run(
        runner._apply_worker_control_at_safe_point(
            task_id,
            completed_jobs=1,
            failed_jobs=0,
        )
    )
    assert status == "paused"
    assert repo.get_task(task_id)["status"] == "paused"
    assert any(event.get("workerAck") == "paused" for event in manager.events)

    # Resume; completed job must be skipped.
    assert repo.request_resume_task(task_id).ok is True

    ran_job_ids: list[int] = []

    async def _fake_run_job(task_obj, job, mode):
        ran_job_ids.append(job["id"])
        repo.update_job(job["id"], status="completed", current_step_code="DONE", current_step_name="已保存")
        return True

    monkeypatch.setattr(runner, "_run_job", _fake_run_job)
    asyncio.run(runner.run_task(task_id))

    assert jobs[0]["id"] not in ran_job_ids
    assert set(ran_job_ids) == {jobs[1]["id"], jobs[2]["id"]}
    final = repo.get_task(task_id)
    assert final["status"] == "completed"
    assert final["completed_jobs"] == 3


def test_runner_stop_at_safe_point_does_not_run_remaining(tmp_path, monkeypatch):
    repo = _repo(tmp_path, monkeypatch)
    task = _create_batch_task(repo, product_count=3, mode="dry_run")
    task_id = task["id"]
    repo.update_task_status(task_id, "running")
    jobs = repo.get_task(task_id)["jobs"]

    manager = _NullManager()
    runner = V1TaskRunner(repo=repo, manager=manager, workflow_adapter=None)

    ran_job_ids: list[int] = []

    async def _fake_run_job(task_obj, job, mode):
        ran_job_ids.append(job["id"])
        repo.update_job(job["id"], status="completed", current_step_code="DONE", current_step_name="已保存")
        # After first product, operator requests stop.
        if len(ran_job_ids) == 1:
            assert repo.request_stop_task(task_id).ok is True
        return True

    monkeypatch.setattr(runner, "_run_job", _fake_run_job)
    asyncio.run(runner.run_task(task_id))

    assert ran_job_ids == [jobs[0]["id"]]
    final = repo.get_task(task_id)
    assert final["status"] == "stopped"
    assert final["completed_jobs"] == 1
    pending = [job for job in final["jobs"] if job["id"] != jobs[0]["id"]]
    assert all(job["status"] == "pending" for job in pending)
    assert any(event.get("workerAck") == "stopped" for event in manager.events)
