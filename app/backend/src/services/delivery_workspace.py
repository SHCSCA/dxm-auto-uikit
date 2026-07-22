from __future__ import annotations

import json
import hashlib
import hmac
import html as html_lib
import re
from collections import defaultdict
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from src.core.config import DATA_DIR, SCREENSHOT_DIR
from src.execution.action_result_contract import (
    ActionResultContractError,
    validate_independent_save_verification_pair,
)
from src.execution.v1_runner import MODE_LAST_STATE, V1_STEPS
from src.repository import Repository
from src.services.evidence_ref import validate_evidence_ref
from src.services.publish_guard import PublishGuardService
from src.services.state_consistency import audit_state_consistency, combine_state_consistency


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
L2_PROBE_DESKTOP_COOKIE_FILE = "%APPDATA%\\DXM Agent Console\\data\\sessions\\dianxiaomi_cookies.json"
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
CLAIM_CANDIDATE_LIMIT = 20
CLAIM_ROW_RE = re.compile(r"<tr\b[^>]*class=\"[^\"]*\bvxe-body--row\b[^\"]*\"[^>]*>.*?</tr>", re.IGNORECASE | re.DOTALL)
TITLE_ATTR_RE = re.compile(r"class=\"[^\"]*\bno-new-line4\b[^\"]*\"[^>]*\btitle=\"([^\"]+)\"", re.IGNORECASE | re.DOTALL)
FALLBACK_TITLE_ATTR_RE = re.compile(r"class=\"[^\"]*\bno-new-line2\b[^\"]*\"[^>]*\btitle=\"([^\"]+)\"", re.IGNORECASE | re.DOTALL)
ANCHOR_RE = re.compile(r"<a\b(?=[^>]*\bhref=\"([^\"]+)\")[^>]*>(.*?)</a>", re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")
DATE_RE = re.compile(r"20\d{2}-\d{2}-\d{2}\s+\d{2}:\d{2}")
PHONE_OR_ACCOUNT_RE = re.compile(r"\b1\d{10}\b")

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
    tasks = repo.list_tasks()
    requested_task_id = task_id
    requested_task_missing = False
    if task_id is None:
        if not tasks:
            return _empty_delivery_workspace(repo)
        task_id = _default_delivery_task_id(tasks)

    task = repo.get_task(task_id)
    if not task:
        if requested_task_id is not None:
            return _empty_delivery_workspace(
                repo,
                requested_task_id=requested_task_id,
                requested_task_missing=True,
            )
        requested_task_missing = requested_task_id is not None
        if not tasks:
            return _empty_delivery_workspace(repo, requested_task_id=requested_task_id, requested_task_missing=requested_task_missing)
        task_id = _default_delivery_task_id(tasks)
        task = repo.get_task(task_id)
        if not task:
            return _empty_delivery_workspace(repo, requested_task_id=requested_task_id, requested_task_missing=requested_task_missing)

    reports = repo.list_reports(task_id)
    evidences = repo.list_evidences(task_id)
    logs = repo.list_logs(task_id)
    exceptions = repo.list_task_exceptions(task_id)
    latest_report = _latest_report(reports)
    extracted = _extract_delivery_evidence(reports, evidences)
    l2_gate = _l2_probe_gate()
    state_consistency = _workspace_state_consistency(
        repo,
        task,
        reports,
    )
    two_stage_acceptance = _two_stage_acceptance(
        repo,
        task,
        reports,
        evidences,
        extracted,
        state_consistency,
    )
    delivery_readiness = _delivery_readiness(
        task,
        reports,
        evidences,
        state_consistency,
        two_stage_acceptance,
    )
    claim_candidates = _claim_candidates_from_l2_gate(l2_gate)

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
        "evidence_grade": _evidence_grade(
            extracted, reports, l2_gate, delivery_readiness
        ),
        "regression_gates": _regression_gates(
            extracted,
            l2_gate,
            delivery_readiness,
            state_consistency,
            two_stage_acceptance,
        ),
        "state_consistency": state_consistency,
        "delivery_readiness": delivery_readiness,
        "two_stage_acceptance": two_stage_acceptance,
        "real_mode_release_plan": _real_mode_release_plan(l2_gate, delivery_readiness),
        "claim_candidates": claim_candidates,
        "acceptanceGaps": _acceptance_gaps(
            exceptions,
            extracted,
            l2_gate,
            delivery_readiness,
            state_consistency,
        ),
        "safety": _safety_state(extracted, reports, l2_gate, delivery_readiness),
        "l2_probe_plan": _l2_probe_plan(),
        "logs": logs,
        "exceptions": exceptions,
    }
    if requested_task_missing:
        workspace["requested_task_missing"] = True
        workspace["requested_task_id"] = requested_task_id
    return workspace


def _workspace_state_consistency(
    repo: Repository,
    task: Mapping[str, Any],
    reports: list[dict[str, Any]],
) -> dict[str, Any]:
    task_id = _int_or_none(task.get("id"))
    audits: list[dict[str, Any]] = []

    def append_audit(
        audited_task: Mapping[str, Any],
        audited_reports: list[dict[str, Any]],
    ) -> None:
        audited_task_id = _int_or_none(audited_task.get("id"))
        audit = audit_state_consistency(
            task=audited_task,
            jobs=list(audited_task.get("jobs") or []),
            reports=audited_reports,
            exceptions=repo.list_task_exceptions(audited_task_id),
        )
        audit["audited_task_ids"] = [audited_task_id]
        audits.append(audit)

    append_audit(task, reports)
    claim_task_id = _linked_claim_task_id(repo, task)
    if claim_task_id is not None and claim_task_id != task_id:
        claim_task = repo.get_task_private(claim_task_id)
        if claim_task:
            append_audit(claim_task, repo.list_reports(claim_task_id))

    return combine_state_consistency(audits)


def _linked_claim_task_id(repo: Repository, task: Mapping[str, Any]) -> int | None:
    payload = task.get("payload") if isinstance(task.get("payload"), Mapping) else {}
    claim_task_id = _int_or_none(payload.get("claim_task_id"))
    if claim_task_id is not None:
        return claim_task_id

    product_ids = [
        _int_or_none(payload.get("claimed_product_id")),
        *[_int_or_none(job.get("product_id")) for job in task.get("jobs") or []],
    ]
    for product_id in product_ids:
        if product_id is None:
            continue
        product = repo.get_product(product_id)
        product_payload = (
            product.get("payload")
            if isinstance((product or {}).get("payload"), Mapping)
            else {}
        )
        claim_task_id = _int_or_none(product_payload.get("claim_task_id"))
        if claim_task_id is not None:
            return claim_task_id
    return None


def _empty_delivery_workspace(
    repo: Repository,
    *,
    requested_task_id: int | None = None,
    requested_task_missing: bool = False,
) -> dict[str, Any]:
    extracted = _extract_delivery_evidence([], [])
    l2_gate = _l2_probe_gate()
    claim_candidates = _claim_candidates_from_l2_gate(l2_gate)
    delivery_readiness = {
        "schema": "dxm_delivery_readiness.v1",
        "ready": False,
        "task_completed": False,
        "blocked_by_task_status": True,
        "has_l3_evidence": False,
        "total_job_count": 0,
        "complete_job_count": 0,
        "jobs": [],
        "blocked_by_state_consistency": True,
        "state_violation_codes": ["STATE_TASK_UNAVAILABLE"],
    }
    state_consistency = {
        "schema": "dxm_state_consistency.v1",
        "consistent": False,
        "violation_codes": ["STATE_TASK_UNAVAILABLE"],
        "violations": [
            {
                "code": "STATE_TASK_UNAVAILABLE",
                "task_id": requested_task_id,
                "detail": "No task is available for consistency audit.",
            }
        ],
        "audited_task_ids": [],
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
        "evidence_grade": _evidence_grade(
            extracted, [], l2_gate, delivery_readiness
        ),
        "regression_gates": _regression_gates(extracted, l2_gate, delivery_readiness, state_consistency),
        "state_consistency": state_consistency,
        "delivery_readiness": delivery_readiness,
        "two_stage_acceptance": _empty_two_stage_acceptance(),
        "real_mode_release_plan": _real_mode_release_plan(l2_gate, delivery_readiness),
        "claim_candidates": claim_candidates,
        "acceptanceGaps": [
            {
                "id": "empty-workspace",
                "title": "还没有可执行任务",
                "severity": "blocker",
                "owner": "task_selection",
                "detail": "请先在“待认领商品”或“商品箱编辑保存”中创建任务；没有任务时不会启动真实保存。",
                "evidenceLevel": "C",
            }
        ],
        "safety": _safety_state(extracted, [], l2_gate, delivery_readiness),
        "l2_probe_plan": _l2_probe_plan(),
        "logs": [],
        "exceptions": [],
    }
    if requested_task_missing:
        workspace["requested_task_missing"] = True
        workspace["requested_task_id"] = requested_task_id
    return workspace


def _default_delivery_task_id(tasks: list[dict[str, Any]]) -> int:
    single_save_tasks = [task for task in tasks if task.get("mode") == "single_save"]
    if single_save_tasks:
        latest_single_save = max(
            single_save_tasks,
            key=lambda task: (str(task.get("created_at") or ""), int(task["id"])),
        )
        return int(latest_single_save["id"])
    return int(tasks[0]["id"])


def _baseline() -> dict[str, Any]:
    return {
        "schema": "delivery_workspace.v1",
        "contract_version": 1,
        "commit_baseline": "current backend aggregation capability",
        "test_baseline": [
            "python -m pytest tests/test_delivery_workspace.py -q",
            "python -m pytest tests/test_v1_runner.py tests/test_publish_guard.py -q",
        ],
        "db_schema": "reports.published is tri-state: true / verified false / unknown null",
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
        "fresh same-run L2 existing-claim-list and draft-box proof",
        "server-side manual approval token",
        "task runner evidence chain only; direct mutation endpoint remains forbidden",
        "publish guard must prove no publish, continue publish, save-and-publish, or move-to-publish action",
    ]
    l2_status = str((l2_gate or {}).get("status") or "")
    l2_passed = l2_status == "passed"
    claim_only_currently_allowed = l2_passed
    single_save_currently_allowed = l2_passed
    controlled_batch_currently_allowed = l2_passed
    claim_only_status = "released_controlled" if claim_only_currently_allowed else "blocked_stale_l2"
    single_save_status = "released_controlled" if single_save_currently_allowed else "blocked_stale_l2"
    controlled_batch_status = (
        "released_controlled" if controlled_batch_currently_allowed else "blocked_stale_l2"
    )
    claim_only_blockers = [] if claim_only_currently_allowed else [
        str((l2_gate or {}).get("detail") or "fresh same-run L2 existing-claim-list and draft-box proof is required before real claim_only can start")
    ]
    single_save_blockers = [] if single_save_currently_allowed else [
        str((l2_gate or {}).get("detail") or "fresh same-run L2 existing-claim-list and draft-box proof is required before real single_save can start")
    ]
    controlled_batch_blockers = [] if controlled_batch_currently_allowed else [
        str(
            (l2_gate or {}).get("detail")
            or "fresh same-run L2 proof is required before a controlled edit batch can start"
        )
    ]
    current_delivery_ready = bool(delivery_readiness) and delivery_readiness.get("ready") is True
    current_delivery_status = "passed" if current_delivery_ready else "missing"
    current_delivery_blocker = None if current_delivery_ready else "current task has no complete L3 evidence chain"
    l2_check_status = "passed" if l2_passed else "blocked"
    l2_check_blocker = None if l2_passed else "fresh L2 existing-claim-list and draft-box readonly proof is missing or stale"
    return {
        "schema": "dxm_real_mode_release_plan.v1",
        "scope": "controlled_claim_single_save_and_edit_batch",
        "publish_allowed": False,
        "batch_unattended_publish_allowed": False,
        "modes": [
            {
                "mode": "single_save",
                "label": "受控单商品只保存",
                "status": single_save_status,
                "allowed": single_save_currently_allowed,
                "release_scope": "single product save-only canary",
                "required_evidence": [
                    "L2 existing-claim-list and draft-box readonly proof",
                    "L3 save_result code=0",
                    "published=false proof",
                    "save and unpublished screenshots or paths",
                    "network/HAR save response evidence",
                ],
                "required_controls": shared_controls,
                "blockers": single_save_blockers,
                "readiness_checklist": [
                    checklist("l2_dual_target", "已有待认领列表和商品箱只读检查", status=l2_check_status, evidence_source="L2 gate", blocker=l2_check_blocker),
                    checklist(
                        "l3_single_canary",
                        "当前任务完整保存与未发布证据",
                        status=current_delivery_status,
                        evidence_source="current task delivery readiness",
                        blocker=current_delivery_blocker,
                    ),
                    checklist(
                        "publish_guard",
                        "当前任务发布隔离证据完整",
                        status=current_delivery_status,
                        evidence_source="current task delivery readiness",
                        blocker=current_delivery_blocker,
                    ),
                ],
            },
            {
                "mode": "claim_only",
                "label": "受控待认领入箱",
                "status": claim_only_status,
                "allowed": claim_only_currently_allowed,
                "release_scope": "controlled claim to draft box",
                "required_evidence": [
                    "L2 existing-claim-list and draft-box readonly proof",
                    "unique existing claimable product proof",
                    "claim to draft box proof",
                    "no editor open and no save request proof",
                ],
                "required_controls": [
                    "fresh same-run L2 existing-claim-list and draft-box proof",
                    "task runner evidence chain only; direct mutation endpoint remains forbidden",
                    "claim_only must not open editor, save, publish, or move to pending publish",
                    "manual recovery path for wrong target claim",
                ],
                "blockers": claim_only_blockers,
                "readiness_checklist": [
                    checklist("l2_dual_target", "已有待认领列表和商品箱只读检查", status=l2_check_status, evidence_source="L2 gate", blocker=l2_check_blocker),
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
                "mode": "controlled_edit_batch",
                "label": "受控整批编辑",
                "status": controlled_batch_status,
                "allowed": controlled_batch_currently_allowed,
                "release_scope": "frozen visible draft-box scope; serial save-only execution",
                "required_evidence": [
                    "fresh L2 readonly proof bound to approval and every item dispatch",
                    "immutable ordered scope and store-level template bundle",
                    "per-item exact identity and required-field readback",
                    "per-item exact SAVE receipt and independent unpublished proof",
                    "UNKNOWN stop and manual reconciliation evidence",
                ],
                "required_controls": [
                    "one atomic approve-and-start operation for the frozen batch",
                    "global concurrency one and strict serial dispatch",
                    "60-second one-time item mutation grant",
                    "pre-save zero-write failures may isolate; dispatch uncertainty stops the batch",
                    "legacy unattended task mode remains forbidden",
                ],
                "blockers": controlled_batch_blockers,
                "readiness_checklist": [
                    checklist(
                        "l2_batch_binding",
                        "L2 与整批批准及逐商品派发绑定",
                        status=l2_check_status,
                        evidence_source="L2 gate",
                        blocker=l2_check_blocker,
                    ),
                    checklist(
                        "immutable_scope",
                        "当前可见商品箱范围与顺序冻结",
                        status="enforced_by_runtime",
                        evidence_source="edit-batch contract",
                    ),
                    checklist(
                        "serial_jit_dispatch",
                        "全局单并发与逐商品即时授权",
                        status="enforced_by_runtime",
                        evidence_source="edit-batch runtime",
                    ),
                    checklist(
                        "unknown_manual_reconciliation",
                        "UNKNOWN 停批且禁止自动重试",
                        status="enforced_by_runtime",
                        evidence_source="mutation dispatch ledger",
                    ),
                ],
            },
            {
                "mode": "batch_save",
                "label": "旧批量任务模式",
                "status": "blocked_unreleased",
                "allowed": False,
                "release_scope": "not released",
                "required_evidence": [
                    "not applicable; use controlled_edit_batch instead",
                ],
                "required_controls": [
                    "task mode batch_save stays blocked",
                    "unattended scheduling stays blocked",
                ],
                "blockers": [
                    "legacy batch_save is outside the release surface",
                ],
                "readiness_checklist": [
                    checklist(
                        "legacy_mode_blocked",
                        "旧 batch_save 不进入真实写入路径",
                        status="blocked",
                        blocker="use controlled_edit_batch",
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
    save_reports = [
        report
        for report in reports
        if report.get("status") == "success"
        and (
            _payload_has_save_result(report.get("save_result"))
            or _payload_has_save_result(report.get("summary"))
        )
    ]
    verified_save_reports = [
        report for report in save_reports if _report_has_successful_save(report)
    ]
    has_unpublished_proof = bool(save_reports) and len(verified_save_reports) == len(
        save_reports
    )
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
        "published": (
            True
            if has_published_true
            else False if has_unpublished_proof else None
        ),
        "publish_allowed": False,
        "report_published_all_false": bool(save_reports)
        and all(report.get("published") is False for report in save_reports),
        "has_unpublished_proof": has_unpublished_proof,
        "reasons": [
            *(["published=true signal found"] if has_published_true else []),
            *publish_risk["reasons"],
        ],
    }


def _evidence_grade(
    extracted: dict[str, Any],
    reports: list[dict[str, Any]],
    l2_gate: Mapping[str, Any] | None = None,
    delivery_readiness: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    save_reports = [
        report
        for report in reports
        if report.get("status") == "success"
        and (
            _payload_has_save_result(report.get("save_result"))
            or _payload_has_save_result(report.get("summary"))
        )
    ]
    verified_save_reports = [
        report for report in save_reports if _report_has_successful_save(report)
    ]
    has_save_result = bool(save_reports)
    has_published_proof = bool(save_reports) and len(verified_save_reports) == len(
        save_reports
    )
    has_network_or_har = bool(save_reports) and all(
        _payload_has_network_or_har(report.get("save_result"))
        or _payload_has_network_or_har(report.get("summary"))
        for report in save_reports
    )
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
    state_consistency: Mapping[str, Any] | None = None,
    two_stage_acceptance: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    latest_l1 = _latest_schema_result(L1_REPLAY_DIR, "dxm_l1_selector_replay.v1")
    l2_gate = dict(l2_gate or _l2_probe_gate())
    l2_passed = l2_gate["status"] == "passed"
    delivery_scope_complete = not (
        delivery_readiness
        and delivery_readiness.get("has_l3_evidence") is True
        and delivery_readiness.get("ready") is not True
    )
    has_l3_save_proof = bool(
        delivery_scope_complete
        and extracted["save_results"]
        and extracted["published_proofs"]
    )
    has_l3_network = bool(
        delivery_scope_complete
        and (extracted["network_save_results"] or extracted["har_summaries"])
    )
    state_consistent = bool(state_consistency) and state_consistency.get("consistent") is True
    two_stage_checks = (two_stage_acceptance or {}).get("checks") or {}
    claim_provenance_invalid = (
        (delivery_readiness or {}).get("two_stage_required") is True
        and (
            two_stage_checks.get("claim_provenance_valid") is False
            or two_stage_checks.get("single_save_claim_snapshot_valid") is False
        )
    )
    if not state_consistent:
        l3_status = "blocked"
        l3_level = "C"
        codes = ", ".join(str(code) for code in (state_consistency or {}).get("violation_codes") or [])
        l3_detail = f"持久化状态互相矛盾，L3 禁止 READY：{codes or 'state consistency unavailable'}。"
    elif not l2_passed:
        l3_status = "blocked"
        l3_level = "C"
        l3_detail = f"L2 未通过（当前：{l2_gate['status']}），真实 claim_only、single_save 与受控整批编辑入口关闭。"
    elif claim_provenance_invalid:
        l3_status = "blocked"
        l3_level = "C"
        missing_codes = ", ".join(
            str(code) for code in (two_stage_acceptance or {}).get("missing_codes") or []
        )
        l3_detail = f"两段式认领来源或保存任务快照无效，L3 禁止 READY：{missing_codes or 'claim provenance invalid'}。"
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
            else "真实写操作必须由用户明确批准，只能操作当前任务绑定店铺中已确认归属的商品。"
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
            "title": "保存前安全检查",
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
    desktop_cookie_command = '$desktopCookieFile = Join-Path $env:APPDATA "DXM Agent Console\\data\\sessions\\dianxiaomi_cookies.json"'
    cookie_file_command = f'$cookieFile = if (Test-Path $desktopCookieFile) {{ $desktopCookieFile }} else {{ "{L2_PROBE_COOKIE_FILE}" }}'
    commands = [
        run_id_command,
        desktop_cookie_command,
        cookie_file_command,
        *[
            f"{L2_PROBE_PYTHON} {L2_PROBE_SCRIPT} --target {target} --run-id $runId --cookie-file $cookieFile --output-dir {L2_PROBE_OUTPUT_DIR} --allowlist-file {L2_PROBE_ALLOWLIST_FILE} --headed"
            for target in REQUIRED_L2_TARGETS
        ],
    ]
    return {
        "schema": "dxm_l2_readonly_probe_plan.v1",
        "requiresApproval": True,
        "purpose": "真实店小秘已有待认领列表和商品箱保存前安全检查；不认领、不备注、不保存、不发布。",
        "runIdCommand": run_id_command,
        "pythonCommand": L2_PROBE_PYTHON,
        "scriptPath": L2_PROBE_SCRIPT,
        "cookieFile": L2_PROBE_COOKIE_FILE,
        "desktopCookieFile": L2_PROBE_DESKTOP_COOKIE_FILE,
        "cookieFileCommand": cookie_file_command,
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
            "运行前必须由操作者明确批准真实保存前安全检查。",
            "保存前安全检查失败或只产生 mock 证据时不自动放行真实保存。",
            "该计划只生成诊断证据，不授权 claim_only、single_save 或受控整批编辑真实写入；旧 batch_save 始终关闭。",
        ],
    }


def _delivery_readiness(
    task: Mapping[str, Any],
    reports: list[dict[str, Any]],
    evidences: list[dict[str, Any]],
    state_consistency: Mapping[str, Any],
    two_stage_acceptance: Mapping[str, Any],
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
    state_consistent = state_consistency.get("consistent") is True
    task_completed = str(task.get("status") or "").lower() == "completed"
    two_stage_required = task.get("mode") == "single_save"
    two_stage_ready = (
        not two_stage_required
        or two_stage_acceptance.get("passed") is True
    )
    return {
        "schema": "dxm_delivery_readiness.v1",
        "ready": (
            state_consistent
            and task_completed
            and two_stage_ready
            and bool(job_results)
            and complete_count == len(job_results)
        ),
        "task_completed": task_completed,
        "blocked_by_task_status": not task_completed,
        "has_l3_evidence": bool(reports or evidences),
        "total_job_count": len(job_results),
        "complete_job_count": complete_count,
        "jobs": job_results,
        "blocked_by_state_consistency": not state_consistent,
        "state_violation_codes": list(state_consistency.get("violation_codes") or []),
        "two_stage_required": two_stage_required,
        "blocked_by_two_stage_acceptance": not two_stage_ready,
        "two_stage_missing_codes": list(two_stage_acceptance.get("missing_codes") or []),
    }


def _empty_two_stage_acceptance() -> dict[str, Any]:
    return {
        "schema": "dxm_two_stage_acceptance.v1",
        "passed": False,
        "status": "no_task",
        "user_message": "请选择店小秘已有待认领商品，并确认进入商品箱后，再执行单商品只保存。",
        "claim_task_id": None,
        "save_task_id": None,
        "claimed_product_id": None,
        "missing_codes": ["task"],
        "checks": {
            "claim_task_present": False,
            "claim_completed": False,
            "save_task_completed": False,
            "claimed_product_present": False,
            "claim_provenance_valid": False,
            "single_save_claim_snapshot_valid": False,
            "draft_box_verified": False,
            "single_save_linked_to_claim": False,
            "save_success": False,
            "unpublished_proof": False,
            "save_evidence_integrity": False,
            "unpublished_evidence_integrity": False,
            "publish_guard_safe": False,
        },
    }


def _two_stage_acceptance(
    repo: Repository,
    task: Mapping[str, Any],
    reports: list[dict[str, Any]],
    evidences: list[dict[str, Any]],
    extracted: dict[str, Any],
    state_consistency: Mapping[str, Any],
) -> dict[str, Any]:
    payload = task.get("payload") if isinstance(task.get("payload"), Mapping) else {}
    jobs = list(task.get("jobs") or [])
    save_task_id = _int_or_none(task.get("id"))
    product_ids = [
        value
        for value in [_int_or_none(payload.get("claimed_product_id")), *[_int_or_none(job.get("product_id")) for job in jobs]]
        if value is not None
    ]
    claimed_product_id = product_ids[0] if product_ids else None
    product = repo.get_product(claimed_product_id) if claimed_product_id is not None else None
    product_payload = product.get("payload") if isinstance((product or {}).get("payload"), Mapping) else {}
    claim_task_id = _int_or_none(payload.get("claim_task_id")) or _int_or_none(product_payload.get("claim_task_id"))
    claim_task = repo.get_task_private(claim_task_id) if claim_task_id is not None else None
    claim_payload = claim_task.get("payload") if isinstance((claim_task or {}).get("payload"), Mapping) else {}
    claim_reports = repo.list_reports(claim_task_id) if claim_task_id is not None else []
    publish_guard = _publish_guard_state(reports, extracted)

    claim_provenance_valid = bool(product) and repo.product_has_completed_claim_provenance(product)
    claim_snapshot_error = (
        repo.single_save_claim_snapshot_error(dict(task), product)
        if product is not None
        else "claimed product is unavailable"
    )
    single_save_claim_snapshot_valid = claim_snapshot_error is None
    claim_completed = _claim_stage_completed(claim_task, claim_payload, claim_reports, claimed_product_id)
    claim_product_matches = _claim_reports_match_product(claim_reports, claimed_product_id) or (
        _int_or_none(claim_payload.get("claimed_product_id")) == claimed_product_id
    )
    product_source = str(
        payload.get("claimed_product_source")
        or product_payload.get("source")
        or ((product or {}).get("source"))
        or ""
    ).strip()
    product_status = str((product or {}).get("status") or payload.get("claimed_product_status") or "").strip()
    draft_box_verified = payload.get("draft_box_verified") is True or product_payload.get("draft_box_verified") is True
    job_product_ids = {_int_or_none(job.get("product_id")) for job in jobs}
    single_save_linked = (
        task.get("mode") == "single_save"
        and claimed_product_id is not None
        and job_product_ids == {claimed_product_id}
        and product_source == "dxm_data_acquisition"
        and product_status in {"claimed_to_draft", "ready_for_edit"}
        and draft_box_verified
    )
    save_success = any(_report_has_successful_save(report) for report in reports)
    unpublished_proof = bool(extracted.get("published_proofs"))
    save_evidence_integrity = _all_jobs_have_valid_action_evidence(
        jobs,
        evidences,
        {"save_only", "SAVE_ONLY"},
    )
    unpublished_evidence_integrity = _all_jobs_have_valid_action_evidence(
        jobs,
        evidences,
        {"verify_not_published", "VERIFY_NOT_PUBLISHED"},
    )
    publish_guard_safe = publish_guard.get("safe") is True
    state_consistent = state_consistency.get("consistent") is True
    save_task_completed = str(task.get("status") or "").lower() == "completed"

    checks = {
        "claim_task_present": claim_task is not None,
        "claim_completed": claim_completed,
        "save_task_completed": save_task_completed,
        "claimed_product_present": product is not None and claimed_product_id is not None,
        "claim_provenance_valid": claim_provenance_valid,
        "single_save_claim_snapshot_valid": single_save_claim_snapshot_valid,
        "claim_product_matches": claim_product_matches,
        "draft_box_verified": draft_box_verified,
        "single_save_linked_to_claim": single_save_linked,
        "save_success": save_success,
        "unpublished_proof": unpublished_proof,
        "save_evidence_integrity": save_evidence_integrity,
        "unpublished_evidence_integrity": unpublished_evidence_integrity,
        "publish_guard_safe": publish_guard_safe,
        "state_consistent": state_consistent,
    }
    missing_codes: list[str] = []
    if not state_consistent:
        missing_codes.append("state_consistency")
    if not save_task_completed:
        missing_codes.append("save_task_completed")
    if claim_task_id is None:
        missing_codes.append("claim_task_id")
    if claim_task is None:
        missing_codes.append("claim_task")
    if not claim_completed:
        missing_codes.append("claim_completed")
    if not claim_product_matches:
        missing_codes.append("claim_product_match")
    if product is None or claimed_product_id is None:
        missing_codes.append("claimed_product")
    if not claim_provenance_valid:
        missing_codes.append("claim_provenance")
    if not single_save_claim_snapshot_valid:
        missing_codes.append("single_save_claim_snapshot")
    if product_source != "dxm_data_acquisition":
        missing_codes.append("claimed_product_source")
    if not draft_box_verified:
        missing_codes.append("draft_box_verified")
    if not single_save_linked:
        missing_codes.append("single_save_linked_to_claim")
    if not save_success:
        missing_codes.append("save_success")
    if not unpublished_proof:
        missing_codes.append("unpublished_proof")
    if not save_evidence_integrity:
        missing_codes.append("save_evidence_integrity")
    if not unpublished_evidence_integrity:
        missing_codes.append("unpublished_evidence_integrity")
    if not publish_guard_safe:
        missing_codes.append("publish_guard_safe")

    if not state_consistent:
        status = "inconsistent_state"
        user_message = "任务、Job、报告或异常状态互相矛盾，已阻止 READY；请保留失败历史并创建新任务重试。"
    elif not missing_codes:
        status = "passed"
        user_message = "真实两段式已完成：商品已从待认领商品进入商品箱，并完成单商品只保存且未发布。"
    elif any(code in missing_codes for code in ("claim_task_id", "claim_task", "claim_completed", "claim_product_match")):
        status = "missing_claim_stage"
        user_message = "还没有完整的待认领入箱证据。请先从店小秘已有待认领列表把真实商品放进商品箱，再创建单商品只保存任务。"
    elif any(code in missing_codes for code in ("claim_provenance", "single_save_claim_snapshot")):
        status = "invalid_claim_provenance"
        user_message = "认领来源或保存任务中的两段式快照已失配，已阻止 READY；请从有效商品箱商品重新创建单商品只保存任务。"
    elif any(code in missing_codes for code in ("claimed_product", "claimed_product_source", "draft_box_verified", "single_save_linked_to_claim")):
        status = "missing_draft_box_stage"
        user_message = "商品箱商品链路不完整。请确认本次保存任务选择的是刚进入商品箱的真实商品。"
    elif "save_task_completed" in missing_codes or "save_success" in missing_codes:
        status = "missing_save_stage"
        user_message = "商品箱编辑保存还没有成功证据。请启动单商品只保存，并等待保存成功。"
    elif "unpublished_proof" in missing_codes or "publish_guard_safe" in missing_codes:
        status = "missing_unpublished_proof"
        user_message = "保存后还缺少未发布证明，或检测到发布风险。请确认只保存成功且商品没有发布。"
    elif any(
        code in missing_codes
        for code in ("save_evidence_integrity", "unpublished_evidence_integrity")
    ):
        status = "invalid_l3_evidence"
        user_message = "保存或未发布截图的文件、大小或哈希已失配，已阻止 READY；请重新执行本次单商品只保存。"
    else:
        status = "incomplete"
        user_message = "两段式验收证据不完整，请按页面提示补齐后重试。"

    return {
        "schema": "dxm_two_stage_acceptance.v1",
        "passed": status == "passed",
        "status": status,
        "user_message": user_message,
        "claim_task_id": claim_task_id,
        "save_task_id": save_task_id,
        "claimed_product_id": claimed_product_id,
        "missing_codes": missing_codes,
        "checks": checks,
        "claim_snapshot_error": claim_snapshot_error,
        "claim_report_count": len(claim_reports),
        "save_report_count": len(reports),
        "evidence_count": len(evidences),
        "state_violation_codes": list(state_consistency.get("violation_codes") or []),
    }


def _claim_stage_completed(
    claim_task: Mapping[str, Any] | None,
    claim_payload: Mapping[str, Any],
    claim_reports: list[dict[str, Any]],
    claimed_product_id: int | None,
) -> bool:
    if not claim_task or claimed_product_id is None:
        return False
    if claim_task.get("mode") != "claim_only":
        return False
    claim_payload_product_id = _int_or_none(claim_payload.get("claimed_product_id"))
    claim_payload_complete = (
        claim_task.get("status") == "completed"
        and claim_payload.get("status") == "completed"
        and claim_payload.get("stage") == "claimed_to_draft"
        and claim_payload.get("draft_box_verified") is True
        and claim_payload_product_id == claimed_product_id
    )
    if not claim_payload_complete:
        return False
    if not claim_reports:
        return True
    return any(report.get("status") == "success" and _claim_report_mentions_product(report, claimed_product_id) for report in claim_reports)


def _claim_reports_match_product(claim_reports: list[dict[str, Any]], claimed_product_id: int | None) -> bool:
    return any(_claim_report_mentions_product(report, claimed_product_id) for report in claim_reports)


def _claim_report_mentions_product(report: Mapping[str, Any], claimed_product_id: int | None) -> bool:
    if claimed_product_id is None:
        return False
    if _int_or_none(report.get("product_id")) == claimed_product_id:
        return True
    for payload in (report.get("save_result"), report.get("summary")):
        if _payload_mentions_product(payload, claimed_product_id):
            return True
    return False


def _payload_mentions_product(payload: Any, product_id: int) -> bool:
    if isinstance(payload, Mapping):
        if _int_or_none(payload.get("claimed_product_id")) == product_id:
            return True
        if _int_or_none(payload.get("product_id")) == product_id:
            return True
        nested = payload.get("claimed_product")
        if isinstance(nested, Mapping) and _int_or_none(nested.get("id")) == product_id:
            return True
        return any(_payload_mentions_product(value, product_id) for value in payload.values())
    if isinstance(payload, list):
        return any(_payload_mentions_product(item, product_id) for item in payload)
    return False


def _report_has_successful_save(report: Mapping[str, Any]) -> bool:
    if report.get("status") != "success" or _parse_bool(report.get("published")) is not False:
        return False
    payloads = (report.get("save_result"), report.get("summary"))
    return bool(
        any(_payload_has_save_result(payload) for payload in payloads)
        and any(
            _payload_has_unpublished_proof(payload, "report") for payload in payloads
        )
        and any(_payload_has_network_or_har(payload) for payload in payloads)
        and _report_has_independent_save_verification_pair(report)
    )


def _report_has_independent_save_verification_pair(report: Mapping[str, Any]) -> bool:
    """Require the canonical same-target SAVE -> VERIFY proof pair from this report."""

    envelopes: list[Mapping[str, Any]] = []

    def collect(value: Any) -> None:
        if isinstance(value, Mapping):
            if (
                value.get("schema_version") == "dxm.action-result.v1"
                and isinstance(value.get("attempted_state"), str)
                and isinstance(value.get("action"), str)
            ):
                envelopes.append(value)
                return
            for nested in value.values():
                collect(nested)
        elif isinstance(value, list):
            for nested in value:
                collect(nested)

    collect(report.get("save_result"))
    collect(report.get("summary"))
    saves = [item for item in envelopes if item.get("attempted_state") == "SAVE_ONLY"]
    verifications = [
        item
        for item in envelopes
        if item.get("attempted_state") == "VERIFY_NOT_PUBLISHED"
    ]
    for save in saves:
        for verification in verifications:
            try:
                validate_independent_save_verification_pair(save, verification)
            except ActionResultContractError:
                continue
            return True
    return False


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _payload_has_save_result(payload: Any) -> bool:
    if isinstance(payload, Mapping):
        nested = payload.get("save_result")
        if isinstance(nested, Mapping) and _looks_like_save_result(nested):
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
    meta = evidence.get("meta") or {}
    if not isinstance(meta, Mapping):
        return False
    if not (
        str(meta.get("action") or "") in accepted
        or str(meta.get("state") or "") in accepted
    ):
        return False
    return _evidence_ref_is_current(meta.get("evidence_ref"))


def _all_jobs_have_valid_action_evidence(
    jobs: list[Mapping[str, Any]],
    evidences: list[Mapping[str, Any]],
    accepted: set[str],
) -> bool:
    if not jobs:
        return False
    for job in jobs:
        job_id = _int_or_none(job.get("id"))
        if job_id is None:
            return False
        if not any(
            _int_or_none(evidence.get("job_id")) == job_id
            and _evidence_file_for_action(evidence, accepted)
            for evidence in evidences
        ):
            return False
    return True


def _evidence_ref_is_current(value: Any) -> bool:
    return validate_evidence_ref(
        value,
        screenshot_root=SCREENSHOT_DIR,
    ).get("ok") is True


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
            "detail": "已有待认领列表与商品箱保存前安全检查均通过，且写入、拦截、禁词、WebSocket 计数全为 0。",
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


def _claim_candidates_from_l2_gate(l2_gate: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(l2_gate, Mapping) or l2_gate.get("status") != "passed":
        return []
    latest = l2_gate.get("latest")
    if not isinstance(latest, Mapping):
        return []
    targets = latest.get("targets") or latest.get("realTargets")
    if not isinstance(targets, Mapping):
        return []
    data_acquisition = targets.get("data_acquisition")
    if not isinstance(data_acquisition, Mapping) or data_acquisition.get("ok") is not True:
        return []
    dom_path = _resolve_l2_evidence_path(data_acquisition.get("dom_path"))
    if dom_path is None or not dom_path.is_file():
        return []
    try:
        raw_html = dom_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    return _extract_claim_candidates_from_html(
        raw_html,
        dom_path=str(dom_path),
        run_id=str(data_acquisition.get("run_id") or ""),
        captured_at=str(data_acquisition.get("created_at") or ""),
    )


def _extract_claim_candidates_from_html(
    raw_html: str,
    *,
    dom_path: str = "",
    run_id: str = "",
    captured_at: str = "",
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in CLAIM_ROW_RE.findall(raw_html):
        row_text = _clean_html_text(row, limit=900)
        if "认领" not in row_text:
            continue
        title = _claim_candidate_title(row)
        if not title:
            continue
        source_url, source_label = _claim_candidate_source(row)
        identity = (source_url or "", title)
        if identity in seen:
            continue
        seen.add(identity)
        store_account = _first_regex_match(PHONE_OR_ACCOUNT_RE, row_text)
        created_at = _first_regex_match(DATE_RE, row_text)
        candidates.append(
            {
                "id": f"{run_id or 'l2-readonly'}:{len(candidates) + 1}",
                "title": title,
                "source": source_label or "",
                "source_url": source_url or "",
                "store_account": store_account or "",
                "created_at": created_at or "",
                "category_hint": _claim_candidate_category_hint(title, row_text),
                "text_excerpt": row_text[:260],
                "run_id": run_id,
                "captured_at": captured_at,
                "dom_path": dom_path,
                "readonly": True,
            }
        )
        if len(candidates) >= CLAIM_CANDIDATE_LIMIT:
            break
    return candidates


def _claim_candidate_title(row_html: str) -> str:
    for pattern in (TITLE_ATTR_RE, FALLBACK_TITLE_ATTR_RE):
        for match in pattern.findall(row_html):
            title = _clean_plain_text(match, limit=160)
            if title and not title.startswith("品牌:"):
                return title
    return ""


def _claim_candidate_source(row_html: str) -> tuple[str, str]:
    fallback_url = ""
    fallback_label = ""
    for href, label_html in ANCHOR_RE.findall(row_html):
        url = _clean_plain_text(href, limit=2000)
        label = _clean_html_text(label_html, limit=40)
        if not url.lower().startswith(("http://", "https://")):
            continue
        if not fallback_url:
            fallback_url, fallback_label = url, label
        if _looks_like_source_platform_label(label) or _looks_like_marketplace_url(url):
            return url, label
    return fallback_url, fallback_label


def _looks_like_source_platform_label(label: str) -> bool:
    normalized = label.lower()
    return any(token in normalized for token in ("1688", "拼多多", "淘宝", "天猫", "temu", "amazon", "aliexpress", "wish", "shopee"))


def _looks_like_marketplace_url(url: str) -> bool:
    normalized = url.lower()
    return any(token in normalized for token in ("1688.com", "yangkeduo.com", "taobao.com", "tmall.com", "aliexpress.com", "amazon.", "wish.com", "shopee."))


def _claim_candidate_category_hint(title: str, row_text: str) -> str:
    text = f"{title} {row_text}"
    if any(token in text for token in ("立牌", "亚克力")):
        return "立牌类谷子"
    if any(token in text for token in ("棉花娃娃", "毛绒", "玩偶")):
        return "毛绒玩偶"
    if any(token in text for token in ("钥匙扣", "挂件", "徽章", "胸针")):
        return "钥匙扣/挂件"
    return ""


def _clean_html_text(value: Any, *, limit: int = 500) -> str:
    return _clean_plain_text(TAG_RE.sub(" ", str(value or "")), limit=limit)


def _clean_plain_text(value: Any, *, limit: int = 500) -> str:
    text = html_lib.unescape(str(value or "")).replace("\xa0", " ")
    text = " ".join(text.split())
    return text[:limit]


def _first_regex_match(pattern: re.Pattern[str], value: str) -> str:
    match = pattern.search(value)
    return match.group(0) if match else ""


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
    if (
        payload.get("ok") is not True
        or payload.get("published") is not False
        or payload.get("exact_save_target") is not True
        or payload.get("save_click_dispatched") is not True
        or payload.get("clicked") is not True
        or payload.get("publish_action_clicked") is not False
        or str(payload.get("text") or "") != "保存"
        or payload.get("exact_save_count") != 1
        or payload.get("click_method") not in {"native_exact_save", "dom_exact_save"}
        or payload.get("network_save_success") is not True
        or payload.get("page_save_success") is not True
    ):
        return False

    authorization = payload.get("mutation_authorization")
    if not isinstance(authorization, Mapping) or not (
        authorization.get("ok") is True
        and authorization.get("executed") is True
        and authorization.get("mutation_action") == "save_only_click"
        and authorization.get("mutation_status") == "DISPATCHED"
        and bool(str(authorization.get("mutation_id") or "").strip())
    ):
        return False

    pre_dispatch = payload.get("pre_dispatch_readback")
    if not isinstance(pre_dispatch, Mapping) or not (
        pre_dispatch.get("ok") is True
        and pre_dispatch.get("required_readback_complete") is True
        and pre_dispatch.get("write_attempted") is False
        and pre_dispatch.get("phase") == "before_ledger_begin_dispatch"
    ):
        return False
    exact_save_target = pre_dispatch.get("exact_save_target")
    if not isinstance(exact_save_target, Mapping) or not (
        exact_save_target.get("ok") is True
        and exact_save_target.get("text") == "保存"
        and exact_save_target.get("exact_save_count") == 1
    ):
        return False
    identity = pre_dispatch.get("identity")
    if not isinstance(identity, Mapping) or any(
        identity.get(key) is not True
        for key in (
            "ok",
            "product_identity_match",
            "store_identity_match",
            "source_identity_match",
        )
    ):
        return False
    if re.fullmatch(
        r"[0-9A-Fa-f]{64}", str(identity.get("target_identity_sha256") or "").strip()
    ) is None:
        return False
    frozen_target = identity.get("target_identity")
    if not isinstance(frozen_target, Mapping) or not frozen_target:
        return False
    try:
        frozen_target_digest = hashlib.sha256(
            json.dumps(
                dict(frozen_target),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
    except (TypeError, ValueError):
        return False
    if not hmac.compare_digest(
        frozen_target_digest,
        str(identity.get("target_identity_sha256") or "").strip().casefold(),
    ):
        return False
    if not str(identity.get("expected_store_name") or "").strip():
        return False
    baseline = pre_dispatch.get("baseline_field_integrity")
    current = pre_dispatch.get("current_field_integrity")
    if not isinstance(baseline, Mapping) or not isinstance(current, Mapping):
        return False
    integrity_keys = ("kind", "field_count", "nonempty_field_count", "sha256")
    for snapshot in (baseline, current):
        if (
            snapshot.get("ok") is not True
            or snapshot.get("kind") != "structured_nonempty_form_state"
            or type(snapshot.get("field_count")) is not int
            or snapshot.get("field_count") <= 0
            or snapshot.get("nonempty_field_count") != snapshot.get("field_count")
            or re.fullmatch(
                r"[0-9A-Fa-f]{64}", str(snapshot.get("sha256") or "").strip()
            )
            is None
        ):
            return False
    if any(baseline.get(key) != current.get(key) for key in integrity_keys):
        return False

    network = payload.get("network_save_result")
    audit = payload.get("network_audit")
    publish_signal = payload.get("publish_signal")
    if not isinstance(network, Mapping) or not _network_save_result_seen(network):
        return False
    if not isinstance(audit, Mapping) or not (
        audit.get("scope") == "same_origin_write_window"
        and audit.get("complete") is True
        and audit.get("window_closed") is True
        and type(audit.get("registered_listener_count")) is int
        and audit.get("registered_listener_count") == 2
        and type(audit.get("removed_listener_count")) is int
        and audit.get("removed_listener_count") == 2
        and type(audit.get("mutation_request_count")) is int
        and audit.get("mutation_request_count") == 1
        and type(audit.get("save_request_count")) is int
        and audit.get("save_request_count") == 1
        and type(audit.get("other_mutation_request_count")) is int
        and audit.get("other_mutation_request_count") == 0
        and type(audit.get("publish_request_count")) is int
        and audit.get("publish_request_count") == 0
    ):
        return False
    if not isinstance(publish_signal, Mapping) or not (
        publish_signal.get("detected") is False
        and publish_signal.get("kind") == "network_route_classification"
        and type(publish_signal.get("request_count")) is int
        and publish_signal.get("request_count") == 0
    ):
        return False

    page = payload.get("page_save_result")
    transition = page.get("status_transition") if isinstance(page, Mapping) else None
    if not isinstance(page, Mapping) or not isinstance(transition, Mapping) or not (
        page.get("ok") is True
        and str(page.get("success_text") or "").strip()
        and transition.get("kind") == "new_or_changed_structured_save_status"
        and isinstance(transition.get("entry"), Mapping)
        and transition.get("entry")
    ):
        return False
    return payload.get("save_decision") == {
        "ok": True,
        "rule": "page_success_and_network_success",
        "page_ok": True,
        "network_ok": True,
        "network_receipt_ok": True,
        "network_audit_ok": True,
    }


def _network_save_result_seen(payload: Mapping[str, Any]) -> bool:
    url = str(payload.get("url") or "").lower()
    return bool(
        payload.get("ok") is True
        and payload.get("receipt_complete") is True
        and type(payload.get("receipt_count")) is int
        and payload.get("receipt_count") == 1
        and _looks_like_save_network_response(payload, url)
        and _status_2xx(payload.get("status"))
    )


def _network_event_save_response_seen(payload: Mapping[str, Any]) -> bool:
    url = str(payload.get("url") or "").lower()
    return _looks_like_save_network_response(payload, url) and _status_2xx(payload.get("status"))


def _looks_like_save_network_response(payload: Mapping[str, Any], url: str) -> bool:
    save_add_endpoints = (
        "/api/popchoiceproduct/add.json",
        "/api/smtproduct/add.json",
    )
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    hostname = str(parsed.hostname or "").casefold()
    if hostname != "dianxiaomi.com" and not hostname.endswith(".dianxiaomi.com"):
        return False
    if str(parsed.path or "").casefold() not in save_add_endpoints:
        return False
    if str(payload.get("method") or "").upper() != "POST":
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
    """Accept only a target-bound structured readback, never a text label.

    Older reports frequently contained ``published=false`` on failed or
    non-saving steps.  A filename/action containing ``verify_not_published``
    therefore cannot be evidence by itself.
    """

    del source
    if payload.get("ok") is not True or payload.get("published") is not False:
        return False
    if payload.get("proof_kind") != "structured_unpublished_status":
        return False
    status = "".join(str(payload.get("status_text") or "").split())
    if status not in {"待发布", "草稿", "未发布", "待完善"}:
        return False
    if (
        payload.get("verified_on_current_page") is not True
        or payload.get("status_scope_unique") is not True
        or type(payload.get("bound_candidate_count")) is not int
        or payload.get("bound_candidate_count") != 1
        or type(payload.get("structured_candidate_count")) is not int
        or payload.get("structured_candidate_count") != 1
        or payload.get("target_bound") is not True
        or payload.get("product_matched") is not True
        or payload.get("store_matched") is not True
        or payload.get("source_identity_match") is not True
        or payload.get("identity_binding_kind")
        != "frozen_target_structured_page_readback"
        or payload.get("publish_risk_term") not in (None, "")
    ):
        return False
    identity = payload.get("identity_readback")
    if not isinstance(identity, Mapping) or any(
        identity.get(key) is not True
        for key in (
            "product_identity_match",
            "store_identity_match",
            "source_identity_match",
        )
    ):
        return False
    target_digest = str(payload.get("target_identity_sha256") or "").strip()
    if re.fullmatch(r"[0-9A-Fa-f]{64}", target_digest) is None:
        return False
    try:
        page = urlsplit(str(payload.get("page_url") or ""))
    except ValueError:
        return False
    hostname = str(page.hostname or "").casefold()
    return bool(
        (hostname == "dianxiaomi.com" or hostname.endswith(".dianxiaomi.com"))
        and str(page.path or "").rstrip("/").casefold()
        == "/web/smt/editfromsmt"
    )


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
    url = str(payload.get("url") or "")
    if _looks_like_save_network_response(payload, url) and _status_2xx(payload.get("status")):
        return True
    for key in ("events", "entries", "responses"):
        values = payload.get(key)
        if isinstance(values, list) and any(
            isinstance(item, Mapping) and _network_event_save_response_seen(item)
            for item in values
        ):
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
    state_consistency: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    if not state_consistency or state_consistency.get("consistent") is not True:
        codes = ", ".join(
            str(code) for code in (state_consistency or {}).get("violation_codes") or []
        )
        gaps.append(
            {
                "id": "gap-state-consistency",
                "title": "任务状态事实互相矛盾",
                "severity": "blocker",
                "owner": "state_consistency",
                "detail": f"READY 已阻止：{codes or 'state consistency unavailable'}。",
                "evidenceLevel": "A",
            }
        )
    l2_status = (l2_gate or {}).get("status")
    if l2_gate and l2_status != "passed":
        gaps.append(
            {
                "id": "gap-l2-real-probe",
                "title": "L2 真实只读门禁未通过",
                "severity": "blocker",
                "owner": "l2_readonly_probe",
                "detail": str(l2_gate.get("detail") or f"L2 当前状态为 {l2_status}，禁止进入真实 claim_only、single_save 与受控整批编辑。"),
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
                "detail": "真实 claim_only、single_save 与受控整批编辑必须在用户明确批准后执行；旧 batch_save 仍关闭。",
                "evidenceLevel": "C",
            }
        )
    return gaps


def _safety_state(
    extracted: dict[str, Any],
    reports: list[dict[str, Any]],
    l2_gate: Mapping[str, Any] | None = None,
    delivery_readiness: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    grade = _evidence_grade(extracted, reports, l2_gate, delivery_readiness)
    return {
        "mode": "controlled_edit_batch / single_save / claim_only / dry_run / probe",
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


def _status_2xx(value: Any) -> bool:
    try:
        status = int(value or 0)
    except (TypeError, ValueError):
        return False
    return 200 <= status < 300


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
