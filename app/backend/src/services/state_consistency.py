from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


TASK_COMPLETED_HAS_FAILED_JOB = "STATE_TASK_COMPLETED_HAS_FAILED_JOB"
FAILED_JOB_HAS_SUCCESS_REPORT = "STATE_FAILED_JOB_HAS_SUCCESS_REPORT"
SUCCEEDED_JOB_HAS_FAILED_REPORT = "STATE_SUCCEEDED_JOB_HAS_FAILED_REPORT"
SUCCESS_HAS_OPEN_EXCEPTION = "STATE_SUCCESS_HAS_OPEN_EXCEPTION"
TASK_COUNTER_MISMATCH = "STATE_TASK_COUNTER_MISMATCH"
SUCCESS_REPORT_REQUIRES_SUCCEEDED_JOB = "STATE_SUCCESS_REPORT_REQUIRES_SUCCEEDED_JOB"
COMPLETED_TASK_REQUIRES_ALL_JOBS_SUCCEEDED = (
    "STATE_COMPLETED_TASK_REQUIRES_ALL_JOBS_SUCCEEDED"
)
FAILED_TASK_REQUIRES_ALL_JOBS_FAILED = "STATE_FAILED_TASK_REQUIRES_ALL_JOBS_FAILED"
PARTIAL_SUCCESS_REQUIRES_MIXED_TERMINAL_JOBS = (
    "STATE_PARTIAL_SUCCESS_REQUIRES_MIXED_TERMINAL_JOBS"
)
REPORT_REFERENCES_UNKNOWN_JOB = "STATE_REPORT_REFERENCES_UNKNOWN_JOB"
EXCEPTION_REFERENCES_UNKNOWN_JOB = "STATE_EXCEPTION_REFERENCES_UNKNOWN_JOB"
NONTERMINAL_TASK_HAS_ALL_TERMINAL_JOBS = (
    "STATE_NONTERMINAL_TASK_HAS_ALL_TERMINAL_JOBS"
)
SUCCESS_JOB_STATUSES = frozenset({"succeeded", "completed"})
TERMINAL_JOB_STATUSES = SUCCESS_JOB_STATUSES | {"failed"}
TERMINAL_TASK_STATUSES = frozenset(
    {
        "completed",
        "failed",
        "partial_success",
        "needs_manual_review",
        "cancelled",
        "canceled",
    }
)


def audit_state_consistency(
    *,
    task: Mapping[str, Any],
    jobs: Sequence[Mapping[str, Any]],
    reports: Sequence[Mapping[str, Any]],
    exceptions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Return deterministic contradictions across one task's persisted facts."""

    violations: list[dict[str, Any]] = []
    task_id = task.get("id")
    jobs_by_id = {
        job.get("id"): job
        for job in jobs
        if job.get("id") is not None and job.get("task_id") == task_id
    }
    task_status = str(task.get("status") or "").lower()
    job_statuses = [str(job.get("status") or "").lower() for job in jobs]
    if (
        task_status not in TERMINAL_TASK_STATUSES
        and job_statuses
        and all(status in TERMINAL_JOB_STATUSES for status in job_statuses)
    ):
        violations.append(
            {
                "code": NONTERMINAL_TASK_HAS_ALL_TERMINAL_JOBS,
                "task_id": task.get("id"),
                "detail": "Non-terminal task contains only terminal jobs.",
            }
        )
    if task_status == "completed":
        for job in jobs:
            if str(job.get("status") or "").lower() == "failed":
                violations.append(
                    {
                        "code": TASK_COMPLETED_HAS_FAILED_JOB,
                        "task_id": task.get("id"),
                        "job_id": job.get("id"),
                        "detail": "Completed task contains a failed job.",
                    }
                )
        if any(
            str(job.get("status") or "").lower()
            not in SUCCESS_JOB_STATUSES | {"failed"}
            for job in jobs
        ):
            violations.append(
                {
                    "code": COMPLETED_TASK_REQUIRES_ALL_JOBS_SUCCEEDED,
                    "task_id": task.get("id"),
                    "detail": "Completed task requires every job to be succeeded.",
                }
            )
    if task_status == "failed" and (
        not jobs
        or any(str(job.get("status") or "").lower() != "failed" for job in jobs)
    ):
        violations.append(
            {
                "code": FAILED_TASK_REQUIRES_ALL_JOBS_FAILED,
                "task_id": task.get("id"),
                "detail": "Failed task requires every job to be failed.",
            }
        )
    if task_status == "partial_success":
        job_status_set = set(job_statuses)
        has_success = bool(job_status_set & SUCCESS_JOB_STATUSES)
        has_failure = "failed" in job_status_set
        all_terminal = job_status_set <= TERMINAL_JOB_STATUSES
        if not jobs or not has_success or not has_failure or not all_terminal:
            violations.append(
                {
                    "code": PARTIAL_SUCCESS_REQUIRES_MIXED_TERMINAL_JOBS,
                    "task_id": task.get("id"),
                    "detail": "Partial-success task requires both succeeded and failed terminal jobs.",
                }
            )

    for report in reports:
        job = jobs_by_id.get(report.get("job_id"))
        if report.get("task_id") != task_id:
            job = None
        job_status = str((job or {}).get("status") or "").lower()
        report_status = str(report.get("status") or "").lower()
        if job is None:
            violations.append(
                {
                    "code": REPORT_REFERENCES_UNKNOWN_JOB,
                    "task_id": task.get("id"),
                    "job_id": report.get("job_id"),
                    "report_id": report.get("id"),
                    "detail": "Report references a job outside the audited task.",
                }
            )
        if (
            job
            and job_status == "failed"
            and report_status == "success"
        ):
            violations.append(
                {
                    "code": FAILED_JOB_HAS_SUCCESS_REPORT,
                    "task_id": task.get("id"),
                    "job_id": job.get("id"),
                    "report_id": report.get("id"),
                    "detail": "Failed job has a success report.",
                }
            )
        if (
            job
            and job_status in SUCCESS_JOB_STATUSES
            and report_status == "failed"
        ):
            violations.append(
                {
                    "code": SUCCEEDED_JOB_HAS_FAILED_REPORT,
                    "task_id": task.get("id"),
                    "job_id": job.get("id"),
                    "report_id": report.get("id"),
                    "detail": "Succeeded job has a failed report.",
                }
            )
        if (
            job
            and report_status == "success"
            and job_status not in SUCCESS_JOB_STATUSES | {"failed"}
        ):
            violations.append(
                {
                    "code": SUCCESS_REPORT_REQUIRES_SUCCEEDED_JOB,
                    "task_id": task.get("id"),
                    "job_id": job.get("id"),
                    "report_id": report.get("id"),
                    "detail": "Success report requires a succeeded job.",
                }
            )

    successful_job_ids = {
        job_id
        for job_id, job in jobs_by_id.items()
        if str(job.get("status") or "").lower() in SUCCESS_JOB_STATUSES
    }
    successful_job_ids.update(
        report.get("job_id")
        for report in reports
        if str(report.get("status") or "").lower() == "success"
        and report.get("job_id") is not None
        and report.get("task_id") == task_id
        and report.get("job_id") in jobs_by_id
    )
    for exception in exceptions:
        job_id = exception.get("job_id")
        exact_job_binding = (
            job_id is not None
            and job_id in jobs_by_id
            and exception.get("task_id") == task_id
        )
        if not exact_job_binding:
            violations.append(
                {
                    "code": EXCEPTION_REFERENCES_UNKNOWN_JOB,
                    "task_id": task.get("id"),
                    "job_id": job_id,
                    "exception_id": exception.get("id"),
                    "detail": "Exception does not reference a job in the audited task.",
                }
            )
        if str(exception.get("status") or "open").lower() != "open":
            continue
        has_success = (
            task_status == "completed"
            or (job_id is not None and job_id in successful_job_ids)
        )
        if has_success:
            violations.append(
                {
                    "code": SUCCESS_HAS_OPEN_EXCEPTION,
                    "task_id": task.get("id"),
                    "job_id": job_id,
                    "exception_id": exception.get("id"),
                    "detail": "Successful state still has an open exception.",
                }
            )

    expected_counters = {
        "total_jobs": len(jobs),
        "completed_jobs": sum(
            1
            for job in jobs
            if str(job.get("status") or "").lower() in SUCCESS_JOB_STATUSES
        ),
        "failed_jobs": sum(
            1 for job in jobs if str(job.get("status") or "").lower() == "failed"
        ),
    }
    actual_counters = {
        key: _int_or_none(task.get(key)) for key in expected_counters
    }
    if actual_counters != expected_counters:
        violations.append(
            {
                "code": TASK_COUNTER_MISMATCH,
                "task_id": task.get("id"),
                "expected": expected_counters,
                "actual": actual_counters,
                "detail": "Task counters do not match persisted jobs.",
            }
        )

    return {
        "schema": "dxm_state_consistency.v1",
        "consistent": not violations,
        "violation_codes": list(dict.fromkeys(item["code"] for item in violations)),
        "violations": violations,
        "audited_task_ids": [task.get("id")] if task.get("id") is not None else [],
    }


def combine_state_consistency(
    audits: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Combine per-task audits without losing the task identity of a violation."""

    violations = [
        dict(violation)
        for audit in audits
        for violation in audit.get("violations") or []
        if isinstance(violation, Mapping)
    ]
    audited_task_ids = list(
        dict.fromkeys(
            task_id
            for audit in audits
            for task_id in audit.get("audited_task_ids") or []
            if task_id is not None
        )
    )
    return {
        "schema": "dxm_state_consistency.v1",
        "consistent": bool(audits) and not violations,
        "violation_codes": list(dict.fromkeys(item["code"] for item in violations)),
        "violations": violations,
        "audited_task_ids": audited_task_ids,
    }


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
