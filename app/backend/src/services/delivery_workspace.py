from __future__ import annotations

import json
import hashlib
from collections import defaultdict
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from src.core.config import DATA_DIR
from src.execution.v1_runner import MODE_LAST_STATE, V1_STEPS
from src.repository import Repository
from src.services.publish_guard import PublishGuardService


REFERENCE_SECTION_LABELS = {
    "attribute_info": "属性信息",
    "description": "详情描述",
    "freight": "运费模板",
    "service": "服务模板",
    "eu_responsible": "欧盟责任人",
    "manufacturer": "制造商",
    "compliance": "合规模板",
    "semi_managed": "半托管模板",
}

ROOT = Path(__file__).resolve().parents[4]
L1_REPLAY_DIR = ROOT / "data" / "l1_selector_replay"
L2_RUNTIME_PROBE_DIR = DATA_DIR / "l2_readonly_probe"
L2_PROBE_DIR = ROOT / "data" / "l2_readonly_probe"
L2_PROBE_SCRIPT = "tools\\probes\\l2_readonly_probe.py"
L2_PROBE_PYTHON = "app\\backend\\.venv\\Scripts\\python.exe"
L2_PROBE_COOKIE_FILE = "data\\sessions\\dianxiaomi_cookies.json"
L2_PROBE_OUTPUT_DIR = "data\\l2_readonly_probe"
L2_PROBE_ALLOWLIST_FILE = "config\\l2_readonly_allowlist.json"
REQUIRED_L2_TARGETS = ("data_acquisition", "draft_box")
L2_TARGET_PATH_HINTS = {
    "data_acquisition": "/web/productcrawl/dataacquisition",
    "draft_box": "/web/smt/smtproductlist/draft",
}
L2_ZERO_NETWORK_COUNTERS = (
    "write_request_count",
    "non_read_request_count",
    "blocked_request_count",
    "forbidden_keyword_request_count",
    "websocket_count",
)
L2_READ_METHODS = {"GET", "HEAD", "OPTIONS"}
L2_ACTIVE_RESOURCE_TYPES = {"xhr", "fetch", "eventsource", "websocket"}
L2_REAL_TARGET_MAX_SKEW_SECONDS = 30 * 60
L2_REAL_TARGET_MAX_AGE_SECONDS = 2 * 60 * 60

ACTION_TO_STATES = {
    "check_login_state": ("PRECHECK_SESSION",),
    "open_draft_box": ("OPEN_DRAFT_LIST",),
    "claim_product": ("CLAIM_PRODUCT",),
    "open_editor": ("OPEN_EDIT_PAGE",),
    "verify_edit_ownership": ("VERIFY_EDIT_OWNERSHIP",),
    "fill_editor_required_defaults": ("FILL_BASE_INFO",),
    "fill_editor_variants": ("FILL_VARIANTS",),
    "fill_media_assets": ("FILL_MEDIA",),
    "fill_compliance_defaults": ("FILL_COMPLIANCE",),
    "enable_semi_managed": ("ENABLE_SEMI_MANAGED",),
    "open_semi_managed_page": ("OPEN_SEMI_MANAGED_PAGE",),
    "fill_semi_managed_defaults": ("FILL_SEMI_GOODS", "FILL_SEMI_VARIANTS"),
    "save_only": ("SAVE_ONLY",),
    "verify_not_published": ("VERIFY_NOT_PUBLISHED",),
}


def build_delivery_workspace(repo: Repository, task_id: int | None = None) -> dict[str, Any] | None:
    tasks = _visible_operator_tasks(repo, repo.list_tasks())
    requested_task_id = task_id
    requested_task_missing = False
    if task_id is None:
        if not tasks:
            return _empty_delivery_workspace(repo)
        task_id = _default_delivery_task_id(repo, tasks)

    task = repo.get_task(task_id)
    if task and _is_legacy_fixture_single_save_task(repo, task):
        task = None
    if not task:
        requested_task_missing = requested_task_id is not None
        if not tasks:
            return _empty_delivery_workspace(repo, requested_task_id=requested_task_id, requested_task_missing=requested_task_missing)
        task_id = _default_delivery_task_id(repo, tasks)
        task = repo.get_task(task_id)
        if task and _is_legacy_fixture_single_save_task(repo, task):
            return _empty_delivery_workspace(repo, requested_task_id=requested_task_id, requested_task_missing=True)
        if not task:
            return _empty_delivery_workspace(repo, requested_task_id=requested_task_id, requested_task_missing=requested_task_missing)

    reports = repo.list_reports(task_id)
    evidences = repo.list_evidences(task_id)
    logs = repo.list_logs(task_id)
    exceptions = [
        item for item in repo.list_exceptions()
        if item.get("task_id") == task_id
    ]
    latest_report = _latest_report(reports)
    extracted = _extract_delivery_evidence(reports, evidences)
    l2_gate = _l2_probe_gate()
    delivery_readiness = _delivery_readiness(task, reports, evidences)

    workspace = {
        "baseline": _baseline(),
        "current_task": _current_task(task),
        "stores": repo.list_stores(),
        "templates": repo.list_templates(),
        "products": repo.list_products(),
        "tasks": tasks,
        "steps": _steps(task, reports, evidences),
        "evidences": evidences,
        "evidence_points": _evidence_points(evidences, reports, task_id),
        "reports": reports,
        "report_summary": _report_summary(reports, extracted),
        "template_resolution": _template_resolution(latest_report),
        "dxmReferenceTemplates": _dxm_reference_sections(latest_report),
        "publish_guard_state": _publish_guard_state(reports, extracted),
        "evidence_grade": _evidence_grade(extracted, l2_gate, delivery_readiness),
        "regression_gates": _regression_gates(extracted, l2_gate, delivery_readiness),
        "delivery_readiness": delivery_readiness,
        "real_mode_release_plan": _real_mode_release_plan(l2_gate, delivery_readiness),
        "acceptanceGaps": _acceptance_gaps(exceptions, extracted, l2_gate, delivery_readiness),
        "safety": _safety_state(extracted, l2_gate, delivery_readiness),
        "l2_probe_plan": _l2_probe_plan(),
        "logs": logs,
        "exceptions": exceptions,
    }
    if requested_task_missing:
        workspace["requested_task_missing"] = True
        workspace["requested_task_id"] = requested_task_id
    return workspace


def _empty_delivery_workspace(
    repo: Repository,
    *,
    requested_task_id: int | None = None,
    requested_task_missing: bool = False,
) -> dict[str, Any]:
    extracted = _extract_delivery_evidence([], [])
    l2_gate = _l2_probe_gate()
    delivery_readiness = {
        "ready": False,
        "has_l3_evidence": False,
        "total_job_count": 0,
        "complete_job_count": 0,
        "jobs": [],
    }
    workspace = {
        "baseline": _baseline(),
        "current_task": None,
        "stores": repo.list_stores(),
        "templates": repo.list_templates(),
        "products": repo.list_products(),
        "tasks": [],
        "steps": [],
        "evidences": [],
        "evidence_points": [],
        "reports": [],
        "report_summary": _report_summary([], extracted),
        "template_resolution": _template_resolution(None),
        "dxmReferenceTemplates": _dxm_reference_sections(None),
        "publish_guard_state": _publish_guard_state([], extracted),
        "evidence_grade": _evidence_grade(extracted, l2_gate, delivery_readiness),
        "regression_gates": _regression_gates(extracted, l2_gate, delivery_readiness),
        "delivery_readiness": delivery_readiness,
        "real_mode_release_plan": _real_mode_release_plan(l2_gate, delivery_readiness),
        "acceptanceGaps": [
            {
                "id": "empty-workspace",
                "title": "还没有可执行任务",
                "severity": "blocker",
                "owner": "task_selection",
                "detail": "请先在“数据采集认领”或“采集箱编辑保存”中创建任务；没有任务时不会启动真实保存。",
                "evidenceLevel": "C",
            }
        ],
        "safety": _safety_state(extracted, l2_gate, delivery_readiness),
        "l2_probe_plan": _l2_probe_plan(),
        "logs": [],
        "exceptions": [],
    }
    if requested_task_missing:
        workspace["requested_task_missing"] = True
        workspace["requested_task_id"] = requested_task_id
    return workspace


_FIXTURE_TASK_MARKERS = (
    "qa guarded",
    "fixture",
    "测试商品",
    "示例商品",
    "本地演示",
)


def _visible_operator_tasks(repo: Repository, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [task for task in tasks if not _is_legacy_fixture_single_save_task(repo, task)]


def _is_legacy_fixture_single_save_task(repo: Repository, task: Mapping[str, Any]) -> bool:
    if task.get("mode") != "single_save":
        return False
    payload = task.get("payload") if isinstance(task.get("payload"), Mapping) else {}
    if _looks_like_fixture_text(task.get("name")) or _looks_like_fixture_text(payload):
        return True
    for product_id in _task_product_ids(task):
        product = repo.get_product(product_id)
        if product and _looks_like_fixture_product(product):
            return True
    return False


def _task_product_ids(task: Mapping[str, Any]) -> list[int]:
    payload = task.get("payload") if isinstance(task.get("payload"), Mapping) else {}
    raw_values = payload.get("product_ids")
    if not isinstance(raw_values, list):
        raw_values = []
    jobs = task.get("jobs")
    if isinstance(jobs, list):
        raw_values = [*raw_values, *(job.get("product_id") for job in jobs if isinstance(job, Mapping))]
    product_ids: list[int] = []
    for value in raw_values:
        try:
            product_id = int(value)
        except (TypeError, ValueError):
            continue
        if product_id > 0:
            product_ids.append(product_id)
    return list(dict.fromkeys(product_ids))


def _looks_like_fixture_product(product: Mapping[str, Any]) -> bool:
    payload = product.get("payload") if isinstance(product.get("payload"), Mapping) else {}
    return _looks_like_fixture_text(
        [
            product.get("title"),
            product.get("category_name"),
            product.get("source"),
            payload,
        ]
    )


def _looks_like_fixture_text(value: Any) -> bool:
    if isinstance(value, Mapping):
        text = " ".join(str(item or "") for item in value.values())
    elif isinstance(value, (list, tuple, set)):
        text = " ".join(str(item or "") for item in value)
    else:
        text = str(value or "")
    normalized = text.casefold()
    return any(marker in normalized for marker in _FIXTURE_TASK_MARKERS)


def _default_delivery_task_id(repo: Repository, tasks: list[dict[str, Any]]) -> int:
    latest_delivery_report_task_id: int | None = None
    for report in repo.list_reports():
        if _report_has_delivery_evidence(report):
            latest_delivery_report_task_id = int(report["task_id"])
            break

    for task in tasks:
        if _is_active_delivery_task(task):
            return int(task["id"])
    for task in tasks:
        if _is_draft_delivery_task(task):
            if latest_delivery_report_task_id is None or int(task["id"]) > latest_delivery_report_task_id:
                return int(task["id"])
            break
    if latest_delivery_report_task_id is not None:
        return latest_delivery_report_task_id
    for task in tasks:
        if _is_draft_delivery_task(task):
            return int(task["id"])
    return int(tasks[0]["id"])


def _is_active_delivery_task(task: Mapping[str, Any]) -> bool:
    if task.get("mode") != "single_save":
        return False
    return str(task.get("status") or "").lower() in {"running", "paused", "needs_manual_review"}


def _is_draft_delivery_task(task: Mapping[str, Any]) -> bool:
    if task.get("mode") != "single_save":
        return False
    return str(task.get("status") or "").lower() == "draft"


def _report_has_delivery_evidence(report: Mapping[str, Any]) -> bool:
    if str(report.get("status") or "").lower() != "success":
        return False
    extracted = _extract_delivery_evidence([dict(report)], [])
    return bool(extracted["save_results"] and extracted["published_proofs"])


def _baseline() -> dict[str, Any]:
    return {
        "schema": "delivery_workspace.v1",
        "contract_version": 1,
        "commit_baseline": "current backend aggregation capability",
        "test_baseline": [
            "python -m pytest tests/test_delivery_workspace.py -q",
            "python -m pytest tests/test_v1_runner.py tests/test_publish_guard.py -q",
        ],
        "db_schema": "unchanged",
        "capabilities": [
            "read tasks/jobs/reports/evidences/logs/templates/exceptions",
            "extract save result, unpublished proof, network and HAR summary",
            "grade delivery evidence without publishing",
        ],
    }


def _real_mode_release_plan(
    l2_gate: Mapping[str, Any] | None = None,
    delivery_readiness: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    def checklist(
        item_id: str,
        label: str,
        *,
        required: bool = True,
        status: str = "missing",
        evidence_source: str = "mode-specific evidence",
        blocker: str | None = None,
        detail: str = "",
    ) -> dict[str, Any]:
        return {
            "id": item_id,
            "label": label,
            "required": required,
            "status": status,
            "evidence_source": evidence_source,
            "blocker": blocker,
            "detail": detail,
        }

    shared_controls = [
        "fresh same-run L2 data_acquisition and draft_box proof",
        "server-side manual approval token",
        "task runner evidence chain only; direct mutation endpoint remains forbidden",
        "publish guard must prove no publish, continue publish, save-and-publish, or move-to-publish action",
    ]
    l2_status = str((l2_gate or {}).get("status") or "")
    l2_passed = l2_status == "passed"
    readiness_ready = bool(delivery_readiness and delivery_readiness.get("ready") is True)
    claim_only_currently_allowed = l2_passed
    single_save_currently_allowed = l2_passed and readiness_ready
    claim_only_status = "released_controlled" if claim_only_currently_allowed else "blocked_stale_l2"
    single_save_status = "released_controlled" if single_save_currently_allowed else "blocked_stale_l2"
    claim_only_blockers = [] if claim_only_currently_allowed else [
        str((l2_gate or {}).get("detail") or "fresh same-run L2 data_acquisition and draft_box proof is required before real claim_only can start")
    ]
    single_save_blockers = [] if single_save_currently_allowed else [
        str((l2_gate or {}).get("detail") or "fresh same-run L2 data_acquisition and draft_box proof is required before real single_save can start")
    ]
    l2_check_status = "passed" if l2_passed else "blocked"
    l2_check_blocker = None if l2_passed else "fresh L2 dual-target readonly proof is missing or stale"
    return {
        "schema": "dxm_real_mode_release_plan.v1",
        "scope": "controlled_claim_and_single_save",
        "publish_allowed": False,
        "batch_unattended_publish_allowed": False,
        "modes": [
            {
                "mode": "single_save",
                "label": "受控 single_save",
                "status": single_save_status,
                "allowed": single_save_currently_allowed,
                "release_scope": "single product save-only canary",
                "required_evidence": [
                    "L2 dual-target readonly proof",
                    "L3 save_result code=0",
                    "published=false proof",
                    "save and unpublished screenshots or paths",
                    "network/HAR save response evidence",
                ],
                "required_controls": shared_controls,
                "blockers": single_save_blockers,
                "readiness_checklist": [
                    checklist("l2_dual_target", "L2 dual-target readonly proof", status=l2_check_status, evidence_source="L2 gate", blocker=l2_check_blocker),
                    checklist("l3_single_canary", "historical single_save canary save evidence", status="passed", evidence_source="L3 task 70"),
                    checklist("published_false", "published=false proof", status="passed", evidence_source="report summary"),
                    checklist("publish_guard", "publish guard clean", status="passed", evidence_source="delivery workspace aggregation"),
                ],
            },
            {
                "mode": "claim_only",
                "label": "受控 claim_only",
                "status": claim_only_status,
                "allowed": claim_only_currently_allowed,
                "release_scope": "controlled claim to draft box",
                "required_evidence": [
                    "L2 dual-target readonly proof",
                    "unique acquisition product proof",
                    "claim to draft box proof",
                    "no editor open and no save request proof",
                ],
                "required_controls": [
                    "fresh same-run L2 data_acquisition and draft_box proof",
                    "task runner evidence chain only; direct mutation endpoint remains forbidden",
                    "claim_only must not open editor, save, publish, or move to pending publish",
                    "manual recovery path for wrong target claim",
                ],
                "blockers": claim_only_blockers,
                "readiness_checklist": [
                    checklist("l2_dual_target", "L2 dual-target readonly proof", status=l2_check_status, evidence_source="L2 gate", blocker=l2_check_blocker),
                    checklist(
                        "claim_ownership_proof",
                        "Claim ownership proof",
                        status="passed" if claim_only_currently_allowed else "blocked",
                        blocker=None if claim_only_currently_allowed else "missing L2 gate",
                        detail="Runner verifies the claimed product can be traced to store, product query/category, and source URL when available.",
                    ),
                    checklist(
                        "no_editor_or_save",
                        "No editor open and no save request proof",
                        status="passed",
                        detail="claim_only must not open the editor or issue save/add.json requests.",
                    ),
                    checklist(
                        "rollback_release",
                        "Ownership release or manual rollback path",
                        status="operator_required",
                        detail="Operator must have a documented recovery path before claim_only can be released.",
                    ),
                ],
            },
            {
                "mode": "batch_save",
                "label": "batch_save",
                "status": "blocked_unreleased",
                "allowed": False,
                "release_scope": "not released",
                "required_evidence": [
                    "dedicated L2/L3 run for batch_save",
                    "batch size limit proof",
                    "per-job save_result code=0",
                    "per-job published=false proof",
                    "per-job network/HAR save response evidence",
                    "partial failure report and retry boundary proof",
                ],
                "required_controls": [
                    *shared_controls,
                    "small batch cap before any unattended execution",
                    "stop-on-first-publish-risk policy",
                    "rollback and manual handoff procedure",
                ],
                "blockers": [
                    "cannot reuse single_save evidence",
                    "batch failure isolation and rollback are not yet accepted",
                    "unattended execution remains forbidden",
                ],
                "readiness_checklist": [
                    checklist(
                        "dedicated_l2_l3",
                        "Dedicated batch_save L2/L3 evidence",
                        blocker="cannot reuse single_save evidence",
                        detail="Batch behavior must be proven separately from one controlled single_save canary.",
                    ),
                    checklist(
                        "batch_size_limit",
                        "Batch size limit proof",
                        blocker="missing batch size cap acceptance",
                        detail="The runner and UI must enforce a small batch cap before any batch_save release.",
                    ),
                    checklist(
                        "per_job_save_and_unpublished",
                        "Per-job save result and published=false proof",
                        blocker="missing per-job evidence",
                        detail="Every job needs save_result code=0, unpublished proof, and report linkage.",
                    ),
                    checklist(
                        "partial_failure_rollback",
                        "Partial failure report plus rollback/manual handoff",
                        blocker="missing partial failure rollback proof",
                        detail="A failed item must stop safely with a visible handoff path and no publish action.",
                    ),
                ],
            },
        ],
    }


def _current_task(task: Mapping[str, Any]) -> dict[str, Any]:
    jobs = list(task.get("jobs") or [])
    return {
        "id": task.get("id"),
        "name": task.get("name"),
        "status": task.get("status"),
        "mode": task.get("mode"),
        "publish_scene": task.get("publish_scene"),
        "store_id": task.get("store_id"),
        "total_jobs": task.get("total_jobs"),
        "completed_jobs": task.get("completed_jobs"),
        "failed_jobs": task.get("failed_jobs"),
        "payload": task.get("payload") or {},
        "jobs": jobs,
        "created_at": task.get("created_at"),
        "updated_at": task.get("updated_at"),
    }


def _steps(task: Mapping[str, Any], reports: list[dict[str, Any]], evidences: list[dict[str, Any]]) -> list[dict[str, Any]]:
    mode = str(task.get("mode") or (task.get("payload") or {}).get("execution_mode") or "single_save")
    step_defs = _step_defs_for_mode(mode)
    evidences_by_state: dict[str, list[dict[str, Any]]] = defaultdict(list)
    workflow_states: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for evidence in evidences:
        meta = evidence.get("meta") or {}
        state = meta.get("state")
        if state:
            evidences_by_state[str(state)].append(evidence)
        action = meta.get("action")
        if evidence.get("evidence_type") == "workflow_action" and action:
            for mapped_state in ACTION_TO_STATES.get(str(action), ()):
                workflow_states[mapped_state].append(meta)

    for result in _workflow_results(reports):
        action = result.get("action")
        for mapped_state in ACTION_TO_STATES.get(str(action), ()):
            workflow_states[mapped_state].append(result)

    report_states = {"WRITE_REPORT"} if reports else set()
    if reports and any(report.get("status") == "success" for report in reports):
        report_states.add("RELEASE_LOCK")

    job_states = {
        str(job.get("current_step_code")): job
        for job in task.get("jobs") or []
        if job.get("current_step_code")
    }

    output = []
    for state_name, label, field_domain in step_defs:
        state = state_name.value
        state_evidences = evidences_by_state.get(state, [])
        state_results = workflow_states.get(state, [])
        status = "pending"
        if state in report_states or state_evidences or state_results:
            status = "completed"
        if state in job_states:
            status = "failed" if job_states[state].get("status") == "failed" else "running"
        output.append(
            {
                "state": state,
                "label": label,
                "field_domain": field_domain,
                "status": status,
                "has_evidence": bool(state_evidences),
                "evidence_count": len(state_evidences),
                "has_workflow_result": bool(state_results),
                "workflow_actions": _unique(
                    item.get("action")
                    for item in state_results
                    if isinstance(item, Mapping)
                ),
                "evidence_ids": [item.get("id") for item in state_evidences],
            }
        )
    return output


def _step_defs_for_mode(mode: str):
    last_state = MODE_LAST_STATE.get(mode)
    if last_state is None:
        return V1_STEPS
    selected = []
    for item in V1_STEPS:
        selected.append(item)
        if item[0] == last_state:
            break
    return selected


def _evidence_points(
    evidences: list[dict[str, Any]],
    reports: list[dict[str, Any]],
    task_id: int,
) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for evidence in evidences:
        meta = evidence.get("meta") or {}
        points.append(
            {
                "kind": evidence.get("evidence_type"),
                "id": evidence.get("id"),
                "task_id": evidence.get("task_id"),
                "job_id": evidence.get("job_id"),
                "state": meta.get("state"),
                "action": meta.get("action"),
                "file_path": evidence.get("file_path"),
                "file_path_url": evidence.get("file_path_url"),
                "created_at": evidence.get("created_at"),
                "ok": meta.get("ok"),
            }
        )
    for report in reports:
        report_id = report.get("id")
        report_extracted = _extract_delivery_evidence([report], [])
        for save_result in report_extracted["save_results"]:
            points.append({"kind": "save_result", "task_id": task_id, "report_id": report_id, "save_result": save_result})
        for proof in report_extracted["published_proofs"]:
            points.append({"kind": "published_proof", "task_id": task_id, "report_id": report_id, **proof})
        for network_result in report_extracted["network_save_results"]:
            points.append({"kind": "network_save_result", "task_id": task_id, "report_id": report_id, "network_save_result": network_result})
        for har_summary in report_extracted["har_summaries"]:
            points.append({"kind": "har_summary", "task_id": task_id, "report_id": report_id, "har_summary": har_summary})
    return points


def _report_summary(reports: list[dict[str, Any]], extracted: dict[str, Any]) -> dict[str, Any]:
    latest_report = _latest_report(reports)
    published_count = sum(1 for report in reports if report.get("published") is True)
    return {
        "total_reports": len(reports),
        "success_count": sum(1 for report in reports if report.get("status") == "success"),
        "failed_count": sum(1 for report in reports if report.get("status") == "failed"),
        "published_count": published_count,
        "latest_report": latest_report,
        "save_results": extracted["save_results"],
        "network_save_results": extracted["network_save_results"],
        "har_summaries": extracted["har_summaries"],
        "published_proofs": extracted["published_proofs"],
        "dxm_reference_fields": _dxm_reference_fields(latest_report),
    }


def _template_resolution(latest_report: dict[str, Any] | None) -> dict[str, Any]:
    summary = (latest_report or {}).get("summary") or {}
    return {
        "template_trace": summary.get("template_trace") or [],
        "dxm_reference_templates_resolved": summary.get("dxm_reference_templates_resolved") or {},
        "dxm_reference_template_results": summary.get("dxm_reference_template_results") or {},
        "resolved_defaults": summary.get("resolved_defaults") or {},
    }


def _publish_guard_state(reports: list[dict[str, Any]], extracted: dict[str, Any]) -> dict[str, Any]:
    published_values = extracted["published_values"]
    has_published_true = any(value is True for value in published_values)
    has_unpublished_proof = bool(extracted["published_proofs"])
    publish_risk = extracted["publish_risk"]
    if publish_risk["reasons"]:
        status = "blocked_published_signal"
    elif has_published_true:
        status = "blocked_published_signal"
    elif has_unpublished_proof:
        status = "safe_unpublished"
    else:
        status = "waiting_for_unpublished_proof"
    return {
        "status": status,
        "safe": not has_published_true and not publish_risk["reasons"] and has_unpublished_proof,
        "published": True if has_published_true else False,
        "publish_allowed": False,
        "report_published_all_false": bool(reports) and all(report.get("published") is False for report in reports),
        "has_unpublished_proof": has_unpublished_proof,
        "reasons": [
            *(["published=true signal found"] if has_published_true else []),
            *publish_risk["reasons"],
        ],
    }


def _evidence_grade(
    extracted: dict[str, Any],
    l2_gate: Mapping[str, Any] | None = None,
    delivery_readiness: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    has_save_result = bool(extracted["save_results"])
    has_published_proof = bool(extracted["published_proofs"])
    has_network_or_har = bool(extracted["network_save_results"] or extracted["har_summaries"])
    has_publish_risk = bool(extracted["publish_risk"]["reasons"])
    l2_status = (l2_gate or {}).get("status")
    blocked_by_l2 = bool(l2_gate) and l2_status != "passed"
    blocked_by_job_readiness = (
        bool(delivery_readiness)
        and delivery_readiness.get("has_l3_evidence") is True
        and delivery_readiness.get("ready") is False
    )
    if has_publish_risk:
        grade = "C"
    elif has_save_result and has_published_proof and has_network_or_har:
        grade = "A"
    elif has_save_result and has_published_proof:
        grade = "B"
    else:
        grade = "C"
    raw_grade = grade
    if blocked_by_l2 or blocked_by_job_readiness:
        grade = "C"
    return {
        "grade": grade,
        "raw_evidence_grade": raw_grade,
        "has_save_result": has_save_result,
        "has_published_proof": has_published_proof,
        "has_network_or_har_save_response": has_network_or_har,
        "has_publish_risk": has_publish_risk,
        "blocked_by_l2": blocked_by_l2,
        "blocked_by_job_readiness": blocked_by_job_readiness,
        "l2_status": l2_status,
        "criteria": "A requires save_result, verified published=false proof, network/HAR save response, and no publish signal; B allows missing network/HAR; C is incomplete or blocked.",
    }


def _regression_gates(
    extracted: dict[str, Any],
    l2_gate: Mapping[str, Any] | None = None,
    delivery_readiness: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    latest_l1 = _latest_schema_result(L1_REPLAY_DIR, "dxm_l1_selector_replay.v1")
    l2_gate = dict(l2_gate or _l2_probe_gate())
    l2_passed = l2_gate["status"] == "passed"
    has_l3_save_proof = bool(extracted["save_results"] and extracted["published_proofs"])
    has_l3_network = bool(extracted["network_save_results"] or extracted["har_summaries"])
    if not l2_passed:
        l3_status = "blocked"
        l3_level = "C"
        l3_detail = f"L2 未通过（当前：{l2_gate['status']}），真实 claim_only/single_save/batch_save 启动入口关闭。"
    elif (
        delivery_readiness
        and delivery_readiness.get("has_l3_evidence") is True
        and delivery_readiness.get("ready") is False
    ):
        l3_status = "blocked"
        l3_level = "C"
        missing_jobs = [
            f"Job #{item.get('job_id')} 缺少 {', '.join(str(value) for value in item.get('missing') or [])}"
            for item in delivery_readiness.get("jobs") or []
            if not item.get("ready")
        ][:3]
        l3_detail = "任务级交付证据不完整；" + "；".join(missing_jobs)
    else:
        l3_status = "passed" if has_l3_save_proof else "approval_required"
        l3_level = "A" if has_l3_save_proof and has_l3_network else "B" if has_l3_save_proof else "C"
        l3_detail = (
            "已找到保存结果、未发布证明和网络/HAR 保存证据。"
            if has_l3_save_proof and has_l3_network
            else "已找到保存结果和未发布证明；缺少网络/HAR 保存证据。"
            if has_l3_save_proof
            else "真实写操作必须由用户明确批准，只能操作 Dang Kang 已备注归属商品。"
        )

    return [
        {
            "level": "L0",
            "title": "单测与 fake adapter",
            "status": "ready",
            "evidenceLevel": "B",
            "requiresApproval": False,
            "command": "app/backend/.venv/Scripts/python.exe -m pytest app/backend/tests -q",
            "detail": "不访问店小秘，验证配置、发布隔离、runner、报告聚合和前端契约。",
        },
        {
            "level": "L1",
            "title": "离线 DOM/fixture replay",
            "status": "passed" if latest_l1 and latest_l1.get("ok") else "failed" if latest_l1 else "not_run",
            "evidenceLevel": "B" if latest_l1 and latest_l1.get("ok") else "C",
            "requiresApproval": False,
            "command": "tools/probes/l1_selector_replay.py",
            "detail": (
                f"最新 L1 replay 通过：{latest_l1.get('passed_count')}/{latest_l1.get('case_count')}。"
                if latest_l1 and latest_l1.get("ok")
                else "最新 L1 replay 未通过，需查看 Markdown 证据。"
                if latest_l1
                else "尚未运行 L1 离线 DOM/fixture replay。"
            ),
            "latest": latest_l1,
        },
        {
            "level": "L2",
            "title": "真实登录态只读 probe",
            "status": l2_gate["status"],
            "evidenceLevel": l2_gate["evidenceLevel"],
            "requiresApproval": True,
            "command": "tools/probes/l2_readonly_probe.py --target data_acquisition|draft_box --allowlist-file config\\l2_readonly_allowlist.json",
            "detail": l2_gate["detail"],
            "latest": l2_gate["latest"],
        },
        {
            "level": "L3",
            "title": "单商品 save-only 金丝雀",
            "status": l3_status,
            "evidenceLevel": l3_level,
            "requiresApproval": True,
            "command": "single_save with manual approval token",
            "detail": l3_detail,
        },
    ]


def _l2_probe_plan() -> dict[str, Any]:
    run_id_command = '$runId = "l2-real-" + (Get-Date -Format "yyyyMMddTHHmmssZ")'
    commands = [
        run_id_command,
        *[
            f"{L2_PROBE_PYTHON} {L2_PROBE_SCRIPT} --target {target} --run-id $runId --cookie-file {L2_PROBE_COOKIE_FILE} --output-dir {L2_PROBE_OUTPUT_DIR} --allowlist-file {L2_PROBE_ALLOWLIST_FILE} --headed"
            for target in REQUIRED_L2_TARGETS
        ],
    ]
    return {
        "schema": "dxm_l2_readonly_probe_plan.v1",
        "requiresApproval": True,
        "purpose": "真实店小秘双目标 L2 页面核验；不领取、不备注、不保存、不发布。",
        "runIdCommand": run_id_command,
        "pythonCommand": L2_PROBE_PYTHON,
        "scriptPath": L2_PROBE_SCRIPT,
        "cookieFile": L2_PROBE_COOKIE_FILE,
        "outputDir": L2_PROBE_OUTPUT_DIR,
        "allowlistFile": L2_PROBE_ALLOWLIST_FILE,
        "targets": [
            {
                "id": target,
                "url": url,
                "required": True,
            }
            for target, url in (
                ("data_acquisition", "https://www.dianxiaomi.com/web/productCrawl/dataAcquisition"),
                ("draft_box", "https://www.dianxiaomi.com/web/smt/smtProductList/draft"),
            )
        ],
        "commands": commands,
        "acceptanceCriteria": [
            "两个目标必须使用同一 run-id。",
            "两个目标必须共享同一 session fingerprint、script_sha256 和 git_head。",
            "write_request_count、non_read_request_count、blocked_request_count、forbidden_keyword_request_count 与 websocket_count 必须全为 0。",
            "目标 URL 与最终 URL 必须停留在对应真实店小秘目标路径，且不得疑似登录页。",
        ],
        "safetyNotes": [
            "运行前必须由操作者明确批准真实 L2 只读探测。",
            "L2 只读探测失败或只产生 mock 证据时不自动放行 L3。",
            "该计划只生成诊断证据，不授权 claim_only、single_save 或 batch_save 真实写入。",
        ],
    }


def _delivery_readiness(
    task: Mapping[str, Any],
    reports: list[dict[str, Any]],
    evidences: list[dict[str, Any]],
) -> dict[str, Any]:
    jobs = list(task.get("jobs") or [])
    reports_by_job: dict[int, list[dict[str, Any]]] = defaultdict(list)
    evidences_by_job: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for report in reports:
        job_id = report.get("job_id")
        if job_id is not None:
            reports_by_job[int(job_id)].append(report)
    for evidence in evidences:
        job_id = evidence.get("job_id")
        if job_id is not None:
            evidences_by_job[int(job_id)].append(evidence)

    job_results = []
    for job in jobs:
        job_id = int(job["id"])
        payloads: list[tuple[str, Any]] = []
        for report in reports_by_job.get(job_id, []):
            payloads.append((f"report:{report.get('id')}.save_result", report.get("save_result")))
            payloads.append((f"report:{report.get('id')}.summary", report.get("summary")))
        for evidence in evidences_by_job.get(job_id, []):
            payloads.append((f"evidence:{evidence.get('id')}", evidence.get("meta")))

        has_save_result = any(_payload_has_save_result(payload) for _, payload in payloads)
        has_unpublished_proof = any(_payload_has_unpublished_proof(payload, source) for source, payload in payloads)
        has_network_or_har = any(_payload_has_network_or_har(payload) for _, payload in payloads)
        has_save_evidence_file = any(_evidence_file_for_action(item, {"save_only", "SAVE_ONLY"}) for item in evidences_by_job.get(job_id, []))
        has_unpublished_evidence_file = any(_evidence_file_for_action(item, {"verify_not_published", "VERIFY_NOT_PUBLISHED"}) for item in evidences_by_job.get(job_id, []))
        missing = []
        if not has_save_result:
            missing.append("save_result")
        if not has_unpublished_proof:
            missing.append("published=false proof")
        if not has_network_or_har:
            missing.append("network/HAR save response")
        if not has_save_evidence_file:
            missing.append("save screenshot/path")
        if not has_unpublished_evidence_file:
            missing.append("unpublished screenshot/path")
        job_results.append(
            {
                "job_id": job_id,
                "product_id": job.get("product_id"),
                "ready": not missing,
                "has_save_result": has_save_result,
                "has_unpublished_proof": has_unpublished_proof,
                "has_network_or_har_save_response": has_network_or_har,
                "has_save_evidence_file": has_save_evidence_file,
                "has_unpublished_evidence_file": has_unpublished_evidence_file,
                "missing": missing,
            }
        )

    complete_count = sum(1 for item in job_results if item["ready"])
    return {
        "ready": bool(job_results) and complete_count == len(job_results),
        "has_l3_evidence": bool(reports or evidences),
        "total_job_count": len(job_results),
        "complete_job_count": complete_count,
        "jobs": job_results,
    }


def _payload_has_save_result(payload: Any) -> bool:
    if isinstance(payload, Mapping):
        nested = payload.get("save_result")
        if isinstance(nested, Mapping) and (_looks_like_save_result(nested) or nested.get("ok") is True):
            return True
        if _looks_like_save_result(payload):
            return True
        return any(_payload_has_save_result(value) for value in payload.values())
    if isinstance(payload, list):
        return any(_payload_has_save_result(item) for item in payload)
    return False


def _payload_has_unpublished_proof(payload: Any, source: str) -> bool:
    if isinstance(payload, Mapping):
        published = _parse_bool(payload.get("published")) if "published" in payload else None
        if published is False and _is_unpublished_proof_payload(payload, source):
            return True
        return any(_payload_has_unpublished_proof(value, source) for value in payload.values())
    if isinstance(payload, list):
        return any(_payload_has_unpublished_proof(item, source) for item in payload)
    return False


def _payload_has_network_or_har(payload: Any) -> bool:
    if isinstance(payload, Mapping):
        network_save_result = payload.get("network_save_result")
        if isinstance(network_save_result, Mapping) and _network_save_result_seen(network_save_result):
            return True
        har_summary = payload.get("har_summary") or payload.get("har")
        if isinstance(har_summary, Mapping) and _har_save_response_seen(har_summary):
            return True
        network_events = payload.get("network_events")
        if isinstance(network_events, list) and any(
            isinstance(event, Mapping) and _network_event_save_response_seen(event)
            for event in network_events
        ):
            return True
        return any(_payload_has_network_or_har(value) for value in payload.values())
    if isinstance(payload, list):
        return any(_payload_has_network_or_har(item) for item in payload)
    return False


def _evidence_file_for_action(evidence: Mapping[str, Any], accepted: set[str]) -> bool:
    if not evidence.get("file_path"):
        return False
    meta = evidence.get("meta") or {}
    return str(meta.get("action") or "") in accepted or str(meta.get("state") or "") in accepted


def l2_real_probe_gate() -> dict[str, Any]:
    return _l2_probe_gate()


def _l2_probe_gate(now: datetime | None = None) -> dict[str, Any]:
    grouped = _latest_l2_probe_results_by_target()
    real_targets = grouped["real"]
    mock_targets = grouped["mock"]
    latest = {
        "requiredTargets": list(REQUIRED_L2_TARGETS),
        "targets": real_targets if real_targets else mock_targets,
        "realTargets": real_targets,
        "mockTargets": mock_targets,
        "missingTargets": [
            target for target in REQUIRED_L2_TARGETS
            if target not in real_targets
        ],
        "probeResultDirs": grouped.get("probeResultDirs", []),
        "selectedProbeResultDir": grouped.get("selectedProbeResultDir"),
    }

    if real_targets:
        failed_targets = [
            target for target, result in real_targets.items()
            if not _l2_result_is_strict_pass(result, require_real_target_path=True)
        ]
        if failed_targets:
            latest["failedTargets"] = failed_targets
            return {
                "status": "failed",
                "evidenceLevel": "C",
                "detail": f"真实 L2 只读 probe 未通过：{', '.join(failed_targets)}；禁止进入 L3。",
                "latest": latest,
            }
        missing_targets = latest["missingTargets"]
        if missing_targets:
            return {
                "status": "partial",
                "evidenceLevel": "C",
                "detail": f"真实 L2 只读 probe 只覆盖部分目标，缺少：{', '.join(missing_targets)}；禁止进入 L3。",
                "latest": latest,
            }
        time_window = _l2_real_targets_time_window(real_targets, now=now)
        latest["timeWindow"] = time_window
        if time_window["ok"] is not True:
            return {
                "status": "failed",
                "evidenceLevel": "C",
                "detail": f"真实 L2 双目标证据不满足时效要求：{time_window['detail']}；禁止进入 L3。",
                "latest": latest,
            }
        run_binding = _l2_real_targets_run_binding(real_targets)
        latest["runBinding"] = run_binding
        if run_binding["ok"] is not True:
            return {
                "status": "failed",
                "evidenceLevel": "C",
                "detail": f"真实 L2 双目标证据不满足同轮次要求：{run_binding['detail']}；禁止进入 L3。",
                "latest": latest,
            }
        return {
            "status": "passed",
            "evidenceLevel": "A",
            "detail": "data_acquisition 与 draft_box 真实 L2 只读 probe 均通过，且写入、拦截、禁词、WebSocket 计数全为 0。",
            "latest": latest,
        }

    if mock_targets:
        failed_mock_targets = [
            target for target, result in mock_targets.items()
            if not _l2_result_is_strict_pass(result, require_real_target_path=False)
        ]
        if failed_mock_targets:
            latest["failedTargets"] = failed_mock_targets
            return {
                "status": "failed",
                "evidenceLevel": "C",
                "detail": f"L2 离线/mock probe 未通过：{', '.join(failed_mock_targets)}。",
                "latest": latest,
            }
        return {
            "status": "mock_passed",
            "evidenceLevel": "B",
            "detail": "仅发现离线/mock L2 证据；不满足真实页面 L2 放行条件。",
            "latest": latest,
        }

    return {
        "status": "not_run",
        "evidenceLevel": "C",
        "detail": "尚未运行 L2 只读 probe；真实 L2 需要用户明确批准。",
        "latest": None,
    }


def _latest_l2_probe_results_by_target() -> dict[str, Any]:
    probe_dirs = _l2_probe_result_dir_statuses()
    for directory in _l2_probe_result_dirs():
        if not directory.exists():
            continue
        candidates = sorted(
            directory.rglob("*.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        grouped = _group_l2_probe_results_by_target(candidates)
        if grouped["real"] or grouped["mock"]:
            grouped["probeResultDirs"] = probe_dirs
            grouped["selectedProbeResultDir"] = str(directory)
            return grouped
    return {"real": {}, "mock": {}, "probeResultDirs": probe_dirs, "selectedProbeResultDir": None}


def _l2_probe_result_dir_statuses() -> list[dict[str, Any]]:
    return [
        {
            "path": str(directory),
            "exists": directory.exists(),
        }
        for directory in _l2_probe_result_dirs()
    ]


def _group_l2_probe_results_by_target(candidates: list[Path]) -> dict[str, dict[str, dict[str, Any]]]:
    grouped: dict[str, dict[str, dict[str, Any]]] = {"real": {}, "mock": {}}
    real_candidates: list[dict[str, Any]] = []
    mock_candidates: list[dict[str, Any]] = []
    for path in candidates:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("schema") != "dxm_l2_readonly_probe.v1":
            continue
        result = _summarize_probe_result(data, path)
        target = str(result.get("target") or "")
        if target not in REQUIRED_L2_TARGETS:
            continue
        bucket = "real" if _is_real_l2_target(result) else "mock"
        if bucket == "real":
            real_candidates.append(result)
        else:
            mock_candidates.append(result)
    grouped["real"] = _latest_complete_l2_real_target_group(real_candidates) or _latest_l2_results_by_target(real_candidates)
    grouped["mock"] = _latest_l2_results_by_target(mock_candidates)
    return grouped


def _l2_probe_result_dirs() -> list[Path]:
    directories = [L2_RUNTIME_PROBE_DIR, L2_PROBE_DIR]
    unique: list[Path] = []
    seen: set[str] = set()
    for directory in directories:
        try:
            key = str(directory.resolve())
        except OSError:
            key = str(directory)
        if key in seen:
            continue
        seen.add(key)
        unique.append(directory)
    return unique


def _latest_l2_results_by_target(results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for result in results:
        target = str(result.get("target") or "")
        if target in REQUIRED_L2_TARGETS:
            latest.setdefault(target, result)
    return latest


def _latest_complete_l2_real_target_group(results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    groups: dict[tuple[str, str, str, str], dict[str, dict[str, Any]]] = {}
    for result in results:
        key = _l2_complete_binding_key(result)
        if key is None:
            continue
        target = str(result.get("target") or "")
        group = groups.setdefault(key, {})
        group.setdefault(target, result)
        if all(required in group for required in REQUIRED_L2_TARGETS):
            return {target: group[target] for target in REQUIRED_L2_TARGETS}
    return {}


def _l2_complete_binding_key(result: Mapping[str, Any]) -> tuple[str, str, str, str] | None:
    values = [
        _l2_binding_value(result, "run_id"),
        _l2_binding_value(result, "cookie_file_sha256"),
        _l2_binding_value(result, "script_sha256"),
        _l2_binding_value(result, "git_head"),
    ]
    if all(isinstance(value, str) and value.strip() for value in values):
        return tuple(str(value).strip() for value in values)
    return None


def _l2_real_targets_time_window(
    real_targets: Mapping[str, Mapping[str, Any]],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = _aware_utc(now or datetime.now(timezone.utc))
    parsed_times = []
    missing = []
    for target in REQUIRED_L2_TARGETS:
        result = real_targets.get(target)
        parsed = _parse_probe_created_at(result.get("created_at") if result else None)
        if parsed is None:
            missing.append(target)
        else:
            parsed_times.append(parsed)
    if missing:
        return {
            "ok": False,
            "detail": f"缺少 created_at：{', '.join(missing)}",
            "maxSkewSeconds": L2_REAL_TARGET_MAX_SKEW_SECONDS,
        }
    earliest = min(parsed_times)
    latest = max(parsed_times)
    skew_seconds = int((latest - earliest).total_seconds())
    newest_age_seconds = int((now - latest).total_seconds())
    if newest_age_seconds < 0:
        return {
            "ok": False,
            "detail": f"created_at 晚于当前时间 {abs(newest_age_seconds)}s",
            "skewSeconds": skew_seconds,
            "maxSkewSeconds": L2_REAL_TARGET_MAX_SKEW_SECONDS,
            "ageSeconds": newest_age_seconds,
            "maxAgeSeconds": L2_REAL_TARGET_MAX_AGE_SECONDS,
            "earliest": earliest.isoformat(),
            "latest": latest.isoformat(),
            "now": now.isoformat(),
        }
    return {
        "ok": skew_seconds <= L2_REAL_TARGET_MAX_SKEW_SECONDS and newest_age_seconds <= L2_REAL_TARGET_MAX_AGE_SECONDS,
        "detail": f"双目标时间差 {skew_seconds}s，上限 {L2_REAL_TARGET_MAX_SKEW_SECONDS}s；最新证据年龄 {newest_age_seconds}s，上限 {L2_REAL_TARGET_MAX_AGE_SECONDS}s",
        "skewSeconds": skew_seconds,
        "maxSkewSeconds": L2_REAL_TARGET_MAX_SKEW_SECONDS,
        "ageSeconds": newest_age_seconds,
        "maxAgeSeconds": L2_REAL_TARGET_MAX_AGE_SECONDS,
        "earliest": earliest.isoformat(),
        "latest": latest.isoformat(),
        "now": now.isoformat(),
    }


def _l2_real_targets_run_binding(real_targets: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    fields = ("run_id", "script_sha256", "git_head", "cookie_file_sha256")
    values_by_field: dict[str, list[str]] = {field: [] for field in fields}
    missing: list[str] = []
    for target in REQUIRED_L2_TARGETS:
        result = real_targets.get(target) or {}
        for field in fields:
            value = _l2_binding_value(result, field)
            if isinstance(value, str) and value.strip():
                values_by_field[field].append(value.strip())
            else:
                missing.append(f"{target}.{field}")

    distinct = {field: sorted(set(values)) for field, values in values_by_field.items()}
    mismatched = [field for field, values in distinct.items() if len(values) > 1]
    ok = not missing and not mismatched
    detail_parts = []
    if missing:
        detail_parts.append(f"缺少 run metadata：{', '.join(missing)}")
    if mismatched:
        detail_parts.append(f"run metadata 不一致：{', '.join(mismatched)}")
    return {
        "ok": ok,
        "detail": "；".join(detail_parts) if detail_parts else "双目标 run_id、session fingerprint、script_sha256 与 git_head 一致。",
        "runIds": distinct["run_id"],
        "scriptSha256": distinct["script_sha256"],
        "gitHeads": distinct["git_head"],
        "cookieFileSha256": distinct["cookie_file_sha256"],
        "missing": missing,
        "mismatched": mismatched,
    }


def _l2_binding_value(result: Mapping[str, Any], field: str) -> Any:
    binding = result.get("evidence_binding")
    if isinstance(binding, Mapping):
        if field == "cookie_file_sha256":
            return binding.get("session_fingerprint_sha256") or binding.get("cookie_file_sha256")
        return binding.get(field)
    return result.get(field)


def _parse_probe_created_at(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return _aware_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _is_real_l2_target(result: Mapping[str, Any]) -> bool:
    return _is_dianxiaomi_url(result.get("target_url")) or _is_dianxiaomi_url(result.get("final_url"))


def _is_dianxiaomi_url(value: Any) -> bool:
    if not value:
        return False
    try:
        parsed = urlsplit(str(value))
    except ValueError:
        return False
    hostname = parsed.hostname or ""
    return hostname == "dianxiaomi.com" or hostname.endswith(".dianxiaomi.com")


def _l2_result_is_strict_pass(result: Mapping[str, Any], *, require_real_target_path: bool) -> bool:
    if result.get("ok") is not True:
        return False
    safety = result.get("safety")
    if not isinstance(safety, Mapping) or safety.get("ok") is not True:
        return False
    if require_real_target_path:
        login_state = result.get("login_state")
        if not isinstance(login_state, Mapping):
            return False
        if login_state.get("required") is not True:
            return False
        if login_state.get("cookies_loaded") is not True:
            return False
        if login_state.get("suspected_login_page") is not False:
            return False
    for key in ("screenshot_path", "screenshot_sha256", "dom_path", "dom_sha256"):
        if not result.get(key):
            return False
    if not _l2_evidence_files_match_hashes(result):
        return False
    target = str(result.get("target") or "")
    if require_real_target_path:
        if not _l2_target_url_matches(target, result.get("target_url")):
            return False
        if not _l2_target_url_matches(target, result.get("final_url")):
            return False
    network = result.get("network")
    if not isinstance(network, Mapping):
        return False
    return all(_counter_is_zero(network.get(key)) for key in L2_ZERO_NETWORK_COUNTERS)


def _l2_evidence_files_match_hashes(result: Mapping[str, Any]) -> bool:
    return _l2_file_hash_matches(result.get("screenshot_path"), result.get("screenshot_sha256")) and _l2_file_hash_matches(
        result.get("dom_path"),
        result.get("dom_sha256"),
    )


def _l2_file_hash_matches(path_value: Any, expected_hash: Any) -> bool:
    expected = str(expected_hash or "").lower()
    if len(expected) != 64:
        return False
    path = _resolve_l2_evidence_path(path_value)
    if path is None or not path.is_file():
        return False
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    return actual == expected


def _resolve_l2_evidence_path(path_value: Any) -> Path | None:
    if not path_value:
        return None
    raw = Path(str(path_value))
    path = raw if raw.is_absolute() else ROOT / raw
    try:
        resolved = path.resolve()
    except OSError:
        return None
    allowed_roots = [ROOT / "data", L2_PROBE_DIR, L2_RUNTIME_PROBE_DIR]
    if any(_path_is_relative_to(resolved, root) for root in allowed_roots):
        return resolved
    return None


def _path_is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _l2_target_url_matches(target: str, url: Any) -> bool:
    if not _is_dianxiaomi_url(url):
        return False
    try:
        parsed = urlsplit(str(url))
    except ValueError:
        return False
    hint = L2_TARGET_PATH_HINTS.get(target)
    return bool(hint and parsed.path.lower().startswith(hint))


def _counter_is_zero(value: Any) -> bool:
    if value is None:
        return False
    try:
        return int(value) == 0
    except (TypeError, ValueError):
        return False


def _latest_l2_probe_result() -> dict[str, Any] | None:
    data = _latest_schema_result(L2_PROBE_DIR, "dxm_l2_readonly_probe.v1")
    if not data:
        return None
    return {
        key: data.get(key)
        for key in (
            "ok",
            "target",
            "target_url",
            "final_url",
            "created_at",
            "run_id",
            "script_sha256",
            "git_head",
            "cookie_file_sha256",
            "evidence_binding",
            "json_path",
            "markdown_path",
            "screenshot_path",
            "screenshot_sha256",
            "dom_path",
            "dom_sha256",
            "network",
            "safety",
        )
    }


def _latest_schema_result(directory: Path, schema: str) -> dict[str, Any] | None:
    if not directory.exists():
        return None
    candidates = sorted(directory.rglob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    for path in candidates:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("schema") != schema:
            continue
        result = _summarize_probe_result(data, path)
        return result
    return None


def _summarize_probe_result(data: Mapping[str, Any], path: Path) -> dict[str, Any]:
    summary = {
        "ok": data.get("ok") is True,
        "created_at": data.get("created_at"),
        "json_path": str(path),
        "markdown_path": data.get("markdown_path"),
    }
    if data.get("schema") == "dxm_l1_selector_replay.v1":
        summary.update(
            {
                "case_count": data.get("case_count"),
                "passed_count": data.get("passed_count"),
                "failed_count": data.get("failed_count"),
                "manifest_sha256": data.get("manifest_sha256"),
                "failed_cases": [
                    {
                        "id": case.get("id"),
                        "page_key": case.get("page_key"),
                        "failures": case.get("failures") or [],
                    }
                    for case in data.get("cases") or []
                    if not case.get("ok")
                ][:10],
            }
        )
    elif data.get("schema") == "dxm_l2_readonly_probe.v1":
        summary.update(
            {
                "target": data.get("target"),
                "target_url": data.get("target_url"),
                "final_url": data.get("final_url"),
                "run_id": data.get("run_id"),
                "script_sha256": data.get("script_sha256"),
                "git_head": data.get("git_head"),
                "cookie_file_sha256": data.get("cookie_file_sha256"),
                "evidence_binding": data.get("evidence_binding"),
                "screenshot_path": data.get("screenshot_path"),
                "screenshot_sha256": data.get("screenshot_sha256"),
                "dom_path": data.get("dom_path"),
                "dom_sha256": data.get("dom_sha256"),
                "login_state": data.get("login_state"),
                "network": {
                    key: (data.get("network") or {}).get(key)
                    for key in (
                        "request_count",
                        "write_request_count",
                        "non_read_request_count",
                        "blocked_request_count",
                        "forbidden_keyword_request_count",
                        "websocket_count",
                    )
                },
                "safety": data.get("safety"),
                "diagnostics": _l2_probe_diagnostics(data),
            }
        )
    return summary


def _l2_probe_diagnostics(data: Mapping[str, Any]) -> dict[str, Any]:
    existing = data.get("diagnostics")
    if isinstance(existing, Mapping):
        diagnostics = dict(existing)
        blocked_groups = diagnostics.get("blocked_request_groups")
        if not isinstance(blocked_groups, list):
            blocked_groups = _l2_blocked_request_groups(data)
            diagnostics["blocked_request_groups"] = blocked_groups
        diagnostics.setdefault(
            "allowlist_review_candidates",
            _l2_allowlist_review_candidates_from_groups(blocked_groups),
        )
        return diagnostics

    blocked_groups = _l2_blocked_request_groups(data)
    return {
        "strict_pass_checks": {
            "ok": data.get("ok") is True,
            "safety_ok": isinstance(data.get("safety"), Mapping) and data["safety"].get("ok") is True,
            "target_url_matches": _l2_target_url_matches(str(data.get("target") or ""), data.get("target_url")),
            "final_url_matches": _l2_target_url_matches(str(data.get("target") or ""), data.get("final_url")),
            "cookies_loaded": isinstance(data.get("login_state"), Mapping) and data["login_state"].get("cookies_loaded") is True,
            "not_login_page": isinstance(data.get("login_state"), Mapping) and data["login_state"].get("suspected_login_page") is False,
            "zero_write": _counter_is_zero((data.get("network") or {}).get("write_request_count")),
            "zero_non_read": _counter_is_zero((data.get("network") or {}).get("non_read_request_count")),
            "zero_blocked": _counter_is_zero((data.get("network") or {}).get("blocked_request_count")),
            "zero_forbidden": _counter_is_zero((data.get("network") or {}).get("forbidden_keyword_request_count")),
            "zero_websocket": _counter_is_zero((data.get("network") or {}).get("websocket_count")),
        },
        "navigation": _l2_navigation_diagnostics(data),
        "render_state": _l2_render_state_diagnostics(data),
        "blocked_request_groups": blocked_groups,
        "allowlist_review_candidates": _l2_allowlist_review_candidates_from_groups(blocked_groups),
    }


def _l2_navigation_diagnostics(data: Mapping[str, Any]) -> dict[str, Any]:
    target = str(data.get("target") or "")
    final_url = data.get("final_url")
    final_matches = _l2_target_url_matches(target, final_url)
    return {
        "requested_target_path": _url_path(data.get("target_url")),
        "final_path": _url_path(final_url),
        "left_target_path": bool(_is_dianxiaomi_url(data.get("target_url")) and not final_matches),
        "final_path_class": _l2_final_path_class(target, final_url),
    }


def _l2_render_state_diagnostics(data: Mapping[str, Any]) -> dict[str, Any]:
    body = str(data.get("body_preview") or "")
    visible_matches = data.get("visible_matches") or []
    return {
        "body_text_length": len(body),
        "visible_match_count": len(visible_matches) if isinstance(visible_matches, list) else 0,
        "loading_screen_detected": any(marker in body for marker in ("加载", "loading", "Loading")),
        "app_shell_only": len(body.strip()) < 200 and not visible_matches,
    }


def _l2_blocked_request_groups(data: Mapping[str, Any]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], dict[str, Any]] = {}
    for item in (data.get("network") or {}).get("blocked_requests") or []:
        parts = _split_url(str(item.get("url") or ""))
        reasons = tuple(item.get("reasons") or [])
        keyword_hits = tuple(item.get("forbidden_keyword_hits") or [])
        key = (
            item.get("method"),
            parts["host"],
            parts["path"],
            item.get("resource_type"),
            reasons,
            keyword_hits,
        )
        current = grouped.setdefault(key, {
            "count": 0,
            "method": item.get("method"),
            "host": parts["host"],
            "path": parts["path"],
            "resource_type": item.get("resource_type"),
            "reasons": list(reasons),
            "keyword_hits": list(keyword_hits),
            "sample_url": item.get("url"),
        })
        current["count"] += 1
    return sorted(grouped.values(), key=lambda group: (-int(group["count"]), str(group["host"]), str(group["path"])))[:25]


def _l2_allowlist_review_candidates_from_groups(groups: Any) -> list[dict[str, Any]]:
    candidates = []
    if not isinstance(groups, list):
        return candidates

    for group in groups:
        if not isinstance(group, Mapping):
            continue
        reasons = group.get("reasons") or []
        if not isinstance(reasons, list):
            reasons = [reasons]
        if (
            str(group.get("method") or "").upper() in L2_READ_METHODS
            and str(group.get("resource_type") or "").lower() in L2_ACTIVE_RESOURCE_TYPES
            and not group.get("keyword_hits")
            and all(str(reason).startswith("active_or_unknown_resource_type:") for reason in reasons)
        ):
            candidate = dict(group)
            candidate["review_only"] = True
            candidate["allowlist_applied"] = False
            candidates.append(candidate)
    return candidates[:20]


def _l2_final_path_class(target: str, url: Any) -> str:
    path = _url_path(url).lower()
    if not path:
        return "unknown"
    if not _is_dianxiaomi_url(url):
        return "mock_or_external"
    if "login" in str(url).lower() or "passport" in str(url).lower():
        return "login"
    if path.startswith("/web/home"):
        return "home"
    if _l2_target_url_matches(target, url):
        return "target"
    return "other"


def _url_path(url: Any) -> str:
    try:
        return urlsplit(str(url or "")).path
    except ValueError:
        return ""


def _split_url(url: str) -> dict[str, str]:
    try:
        parts = urlsplit(url)
    except ValueError:
        return {"host": "", "path": ""}
    return {"host": parts.netloc, "path": parts.path}


def _extract_delivery_evidence(reports: list[dict[str, Any]], evidences: list[dict[str, Any]]) -> dict[str, Any]:
    save_results: list[dict[str, Any]] = []
    network_save_results: list[dict[str, Any]] = []
    har_summaries: list[dict[str, Any]] = []
    published_proofs: list[dict[str, Any]] = []
    published_values: list[bool] = []
    publish_scan = {"network_urls": [], "visible_texts": [], "modal_texts": []}

    for report in reports:
        report_published = _parse_bool(report.get("published")) if "published" in report else None
        if report_published is not None:
            published_values.append(report_published)
        _collect_from_payload(report.get("save_result"), "report.save_result", save_results, network_save_results, har_summaries, published_proofs, published_values, publish_scan)
        _collect_from_payload(report.get("summary"), "report.summary", save_results, network_save_results, har_summaries, published_proofs, published_values, publish_scan)

    for evidence in evidences:
        _collect_from_payload(
            evidence.get("meta"),
            f"evidence:{evidence.get('id')}",
            save_results,
            network_save_results,
            har_summaries,
            published_proofs,
            published_values,
            publish_scan,
        )

    return {
        "save_results": _unique_dicts(save_results),
        "network_save_results": _unique_dicts(network_save_results),
        "har_summaries": _unique_dicts(har_summaries),
        "published_proofs": _unique_dicts(published_proofs),
        "published_values": published_values,
        "publish_risk": PublishGuardService().check(
            visible_texts=publish_scan["visible_texts"],
            modal_texts=publish_scan["modal_texts"],
            network_urls=publish_scan["network_urls"],
        ),
    }


def _collect_from_payload(
    payload: Any,
    source: str,
    save_results: list[dict[str, Any]],
    network_save_results: list[dict[str, Any]],
    har_summaries: list[dict[str, Any]],
    published_proofs: list[dict[str, Any]],
    published_values: list[bool],
    publish_scan: dict[str, list[str]],
) -> None:
    if isinstance(payload, Mapping):
        _collect_publish_scan_inputs(payload, publish_scan)
        if isinstance(payload.get("save_result"), Mapping):
            save_results.append(dict(payload["save_result"]))
        if _looks_like_save_result(payload):
            save_results.append(dict(payload))
        network_save_result = payload.get("network_save_result")
        if isinstance(network_save_result, Mapping) and _network_save_result_seen(network_save_result):
            network_save_results.append(dict(network_save_result))
        har_summary = payload.get("har_summary") or payload.get("har")
        if isinstance(har_summary, Mapping) and _har_save_response_seen(har_summary):
            har_summaries.append(dict(har_summary))
        network_events = payload.get("network_events")
        if isinstance(network_events, list):
            for event in network_events:
                if isinstance(event, Mapping) and _network_event_save_response_seen(event):
                    network_save_results.append(dict(event))
        published = _parse_bool(payload.get("published")) if "published" in payload else None
        if published is not None:
            published_values.append(published)
            if published is False and _is_unpublished_proof_payload(payload, source):
                published_proofs.append({"source": source, "published": False})
        for value in payload.values():
            _collect_from_payload(value, source, save_results, network_save_results, har_summaries, published_proofs, published_values, publish_scan)
    elif isinstance(payload, list):
        for item in payload:
            _collect_from_payload(item, source, save_results, network_save_results, har_summaries, published_proofs, published_values, publish_scan)


def _looks_like_save_result(payload: Mapping[str, Any]) -> bool:
    return (
        payload.get("ok") is True
        and (
            "success_text" in payload
            or "network_save_result" in payload
            or "clicked" in payload
            or "message" in payload
        )
        and "published" in payload
    )


def _network_save_result_seen(payload: Mapping[str, Any]) -> bool:
    if payload.get("save_response_seen") is True:
        return True
    url = str(payload.get("url") or "").lower()
    status = payload.get("status")
    if status is None and payload.get("ok") is True:
        status = 200
    return _looks_like_save_network_response(payload, url) and _status_2xx_or_3xx(status)


def _network_event_save_response_seen(payload: Mapping[str, Any]) -> bool:
    url = str(payload.get("url") or "").lower()
    return _looks_like_save_network_response(payload, url) and _status_2xx_or_3xx(payload.get("status"))


def _looks_like_save_network_response(payload: Mapping[str, Any], url: str) -> bool:
    if "save" in url:
        return True
    save_add_endpoints = (
        "/api/popchoiceproduct/add.json",
        "/api/smtproduct/add.json",
    )
    if not any(url.endswith(endpoint) for endpoint in save_add_endpoints):
        return False
    response_codes = _strings_from_value(payload.get("code"))
    response_text_values = _strings_from_value(payload.get("msg")) + _strings_from_value(payload.get("message"))
    nested_json = payload.get("json")
    if isinstance(nested_json, Mapping):
        response_codes.extend(_strings_from_value(nested_json.get("code")))
        response_text_values.extend(_strings_from_value(nested_json.get("msg")) + _strings_from_value(nested_json.get("message")))
        nested_data = nested_json.get("data")
        if isinstance(nested_data, Mapping):
            response_codes.extend(_strings_from_value(nested_data.get("code")))
            response_text_values.extend(_strings_from_value(nested_data.get("msg")) + _strings_from_value(nested_data.get("message")))
    response_text = " ".join(response_text_values)
    success_text_seen = any(term in response_text for term in ("保存成功", "编辑保存成功", "编辑成功"))
    return "0" in {str(code) for code in response_codes} and success_text_seen


def _collect_publish_scan_inputs(payload: Mapping[str, Any], publish_scan: dict[str, list[str]]) -> None:
    for key, value in payload.items():
        key_text = str(key).lower()
        if key_text in {"url", "current_url", "request_url", "response_url"}:
            publish_scan["network_urls"].extend(_strings_from_value(value))
        elif key_text in {"network_urls"}:
            publish_scan["network_urls"].extend(_strings_from_value(value))
        elif key_text in {"modal_text", "modal_texts", "dialog_text", "dialog_texts"}:
            publish_scan["modal_texts"].extend(_strings_from_value(value))
        elif key_text in {
            "action",
            "intended_action",
            "target_action",
            "target_text",
            "button_text",
            "button_label",
            "clicked_text",
            "label",
            "reason",
        }:
            publish_scan["visible_texts"].extend(_strings_from_value(value))
    network_events = payload.get("network_events")
    if isinstance(network_events, list):
        for event in network_events:
            if isinstance(event, Mapping):
                publish_scan["network_urls"].extend(_strings_from_value(event.get("url")))


def _is_unpublished_proof_payload(payload: Mapping[str, Any], source: str) -> bool:
    proof_text = " ".join(
        _strings_from_value(
            [
                source,
                payload.get("action"),
                payload.get("state"),
                payload.get("proof_type"),
                payload.get("screenshot_url"),
                payload.get("file_path"),
                payload.get("message"),
            ]
        )
    ).lower()
    return "verify_not_published" in proof_text or "verify not published" in proof_text


def _strings_from_value(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (int, float, bool)):
        return [str(value)]
    if isinstance(value, list):
        return [item for child in value for item in _strings_from_value(child)]
    if isinstance(value, Mapping):
        return [item for child in value.values() for item in _strings_from_value(child)]
    return []


def _har_save_response_seen(payload: Mapping[str, Any]) -> bool:
    if payload.get("save_response_seen") is True:
        return True
    if payload.get("ok") is True and "save" in str(payload.get("url") or payload.get("path") or "").lower():
        return True
    return False


def _workflow_results(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for report in reports:
        summary = report.get("summary") or {}
        workflow_results = summary.get("workflow_results")
        if isinstance(workflow_results, list):
            results.extend(item for item in workflow_results if isinstance(item, dict))
    return results


def _latest_report(reports: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not reports:
        return None
    return sorted(reports, key=lambda item: item.get("id") or 0)[-1]


def _dxm_reference_fields(latest_report: dict[str, Any] | None) -> dict[str, Any]:
    summary = (latest_report or {}).get("summary") or {}
    resolved = summary.get("dxm_reference_templates_resolved") or {}
    results = summary.get("dxm_reference_template_results") or {}
    sections = sorted(set(resolved) | set(results))
    return {
        section: {
            "resolved": resolved.get(section),
            "result": results.get(section),
        }
        for section in sections
    }


def _dxm_reference_sections(latest_report: dict[str, Any] | None) -> list[dict[str, Any]]:
    summary = (latest_report or {}).get("summary") or {}
    resolved = summary.get("dxm_reference_templates_resolved") or {}
    results = summary.get("dxm_reference_template_results") or {}
    output = []
    for section, label in REFERENCE_SECTION_LABELS.items():
        config = resolved.get(section) if isinstance(resolved, Mapping) else {}
        result = results.get(section) if isinstance(results, Mapping) else {}
        config_map = config if isinstance(config, Mapping) else {}
        result_map = result if isinstance(result, Mapping) else {}
        names = _names_from_value(
            config_map.get("names")
            or config_map.get("templates")
            or config_map.get("template_names")
            or result_map.get("selected")
            or result_map.get("matched_template")
            or result_map.get("template_name")
        )
        output.append(
            {
                "section": section,
                "label": label,
                "templateNames": names,
                "required": bool(config_map.get("required", True)),
                "source": "new" if names else "fallback",
                "result": result_map,
            }
        )
    return output


def _acceptance_gaps(
    exceptions: list[dict[str, Any]],
    extracted: dict[str, Any],
    l2_gate: Mapping[str, Any] | None = None,
    delivery_readiness: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    l2_status = (l2_gate or {}).get("status")
    if l2_gate and l2_status != "passed":
        gaps.append(
            {
                "id": "gap-l2-real-probe",
                "title": "L2 真实只读门禁未通过",
                "severity": "blocker",
                "owner": "l2_readonly_probe",
                "detail": str(l2_gate.get("detail") or f"L2 当前状态为 {l2_status}，禁止进入真实 claim_only/single_save/batch_save。"),
                "evidenceLevel": "C",
            }
        )
    if (
        delivery_readiness
        and delivery_readiness.get("has_l3_evidence") is True
        and delivery_readiness.get("ready") is False
    ):
        for item in (delivery_readiness.get("jobs") or [])[:6]:
            if item.get("ready"):
                continue
            gaps.append(
                {
                    "id": f"gap-job-{item.get('job_id')}-delivery-evidence",
                    "title": f"Job #{item.get('job_id')} 交付证据不完整",
                    "severity": "blocker",
                    "owner": "delivery_readiness",
                    "detail": "缺少：" + "、".join(str(value) for value in item.get("missing") or []),
                    "evidenceLevel": "A",
                }
            )
    if not extracted["save_results"]:
        gaps.append(
            {
                "id": "gap-save-result",
                "title": "缺少保存结果",
                "severity": "blocker",
                "owner": "save_result",
                "detail": "报告或证据中尚未找到 save_result。",
                "evidenceLevel": "A",
            }
        )
    if not extracted["published_proofs"]:
        gaps.append(
            {
                "id": "gap-unpublished-proof",
                "title": "缺少未发布证明",
                "severity": "blocker",
                "owner": "publish_guard",
                "detail": "报告或证据中尚未找到 published=false 证明。",
                "evidenceLevel": "A",
            }
        )
    if not (extracted["network_save_results"] or extracted["har_summaries"]):
        gaps.append(
            {
                "id": "gap-network-save-response",
                "title": "保存接口响应未捕获",
                "severity": "risk",
                "owner": "network_evidence",
                "detail": "缺少保存 request/response 或 HAR 摘要时，证据等级最高为 B。",
                "evidenceLevel": "B",
            }
        )
    for item in exceptions[:4]:
        gaps.append(
            {
                "id": f"exception-{item.get('id')}",
                "title": item.get("title") or item.get("error_code"),
                "severity": "risk",
                "owner": item.get("field_domain") or "exception",
                "detail": item.get("detail") or item.get("suggestion") or "",
                "evidenceLevel": "B",
            }
        )
    if not gaps:
        gaps.append(
            {
                "id": "gap-l3-approval",
                "title": "L3 金丝雀需人工批准",
                "severity": "watch",
                "owner": "ops-review",
                "detail": "真实 claim_only/single_save/batch_save 写操作必须在用户明确批准后执行。",
                "evidenceLevel": "C",
            }
        )
    return gaps


def _safety_state(
    extracted: dict[str, Any],
    l2_gate: Mapping[str, Any] | None = None,
    delivery_readiness: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    grade = _evidence_grade(extracted, l2_gate, delivery_readiness)
    return {
        "mode": "single_save / batch_save / claim_only / dry_run / probe",
        "guarantee": "只保存不发布：工作台不提供任何发布动作入口，后端发布隔离固定开启。",
        "forbiddenActions": ["发布", "继续发布", "保存并发布", "移入待发布"],
        "lastCheckedAt": "runtime aggregation",
        "evidenceGrade": grade["grade"],
        "blockedByL2": grade["blocked_by_l2"],
        "l2Status": grade["l2_status"],
    }


def _names_from_value(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, (int, float)):
        return [str(value)]
    if isinstance(value, list):
        return _unique(name for item in value for name in _names_from_value(item))
    if isinstance(value, Mapping):
        return _names_from_value(
            value.get("names")
            or value.get("templates")
            or value.get("template_names")
            or value.get("templateName")
            or value.get("template_name")
            or value.get("name")
        )
    return []


def _status_2xx_or_3xx(value: Any) -> bool:
    try:
        status = int(value or 0)
    except (TypeError, ValueError):
        return False
    return 200 <= status < 400


def _parse_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y"}:
            return True
        if normalized in {"false", "0", "no", "n"}:
            return False
    return None


def _unique(values) -> list[Any]:
    output = []
    for value in values:
        if value is not None and value not in output:
            output.append(value)
    return output


def _unique_dicts(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        key = repr(sorted(value.items()))
        if key in seen:
            continue
        seen.add(key)
        output.append(value)
    return output
