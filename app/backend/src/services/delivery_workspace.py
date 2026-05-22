from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import Any

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
L2_PROBE_DIR = ROOT / "data" / "l2_readonly_probe"

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
    if task_id is None:
        if not tasks:
            return None
        task_id = int(tasks[0]["id"])

    task = repo.get_task(task_id)
    if not task:
        return None

    reports = repo.list_reports(task_id)
    evidences = repo.list_evidences(task_id)
    logs = repo.list_logs(task_id)
    exceptions = [
        item for item in repo.list_exceptions()
        if item.get("task_id") == task_id
    ]
    latest_report = _latest_report(reports)
    extracted = _extract_delivery_evidence(reports, evidences)

    return {
        "baseline": _baseline(),
        "current_task": _current_task(task),
        "stores": repo.list_stores(),
        "templates": repo.list_templates(),
        "products": repo.list_products(),
        "tasks": tasks,
        "steps": _steps(task, reports, evidences),
        "evidences": evidences,
        "evidence_points": _evidence_points(evidences, extracted),
        "reports": reports,
        "report_summary": _report_summary(reports, extracted),
        "template_resolution": _template_resolution(latest_report),
        "dxmReferenceTemplates": _dxm_reference_sections(latest_report),
        "publish_guard_state": _publish_guard_state(reports, extracted),
        "evidence_grade": _evidence_grade(extracted),
        "regression_gates": _regression_gates(extracted),
        "acceptanceGaps": _acceptance_gaps(exceptions, extracted),
        "safety": _safety_state(extracted),
        "logs": logs,
        "exceptions": exceptions,
    }


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


def _evidence_points(evidences: list[dict[str, Any]], extracted: dict[str, Any]) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for evidence in evidences:
        meta = evidence.get("meta") or {}
        points.append(
            {
                "kind": evidence.get("evidence_type"),
                "id": evidence.get("id"),
                "job_id": evidence.get("job_id"),
                "state": meta.get("state"),
                "action": meta.get("action"),
                "file_path": evidence.get("file_path"),
                "file_path_url": evidence.get("file_path_url"),
                "created_at": evidence.get("created_at"),
                "ok": meta.get("ok"),
            }
        )
    for save_result in extracted["save_results"]:
        points.append({"kind": "save_result", "save_result": save_result})
    for proof in extracted["published_proofs"]:
        points.append({"kind": "published_proof", **proof})
    for network_result in extracted["network_save_results"]:
        points.append({"kind": "network_save_result", "network_save_result": network_result})
    for har_summary in extracted["har_summaries"]:
        points.append({"kind": "har_summary", "har_summary": har_summary})
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


def _evidence_grade(extracted: dict[str, Any]) -> dict[str, Any]:
    has_save_result = bool(extracted["save_results"])
    has_published_proof = bool(extracted["published_proofs"])
    has_network_or_har = bool(extracted["network_save_results"] or extracted["har_summaries"])
    has_publish_risk = bool(extracted["publish_risk"]["reasons"])
    if has_publish_risk:
        grade = "C"
    elif has_save_result and has_published_proof and has_network_or_har:
        grade = "A"
    elif has_save_result and has_published_proof:
        grade = "B"
    else:
        grade = "C"
    return {
        "grade": grade,
        "has_save_result": has_save_result,
        "has_published_proof": has_published_proof,
        "has_network_or_har_save_response": has_network_or_har,
        "has_publish_risk": has_publish_risk,
        "criteria": "A requires save_result, verified published=false proof, network/HAR save response, and no publish signal; B allows missing network/HAR; C is incomplete or blocked.",
    }


def _regression_gates(extracted: dict[str, Any]) -> list[dict[str, Any]]:
    latest_l1 = _latest_schema_result(L1_REPLAY_DIR, "dxm_l1_selector_replay.v1")
    latest_l2 = _latest_l2_probe_result()
    has_l3_save_proof = bool(extracted["save_results"] and extracted["published_proofs"])
    has_l3_network = bool(extracted["network_save_results"] or extracted["har_summaries"])
    l2_status = "not_run"
    l2_level = "C"
    l2_detail = "尚未运行 L2 只读 probe；真实 L2 需要用户明确批准。"
    if latest_l2:
        l2_ok = latest_l2.get("ok") is True
        target_url = str(latest_l2.get("target_url") or "")
        is_real_target = "dianxiaomi.com" in target_url
        if l2_ok and is_real_target:
            l2_status = "passed"
            l2_level = "A"
            l2_detail = "最新真实店小秘 L2 只读 probe 通过。"
        elif l2_ok:
            l2_status = "mock_passed"
            l2_level = "B"
            l2_detail = "最新 L2 离线/mock probe 通过；真实页面仍待批准执行。"
        else:
            l2_status = "failed"
            l2_level = "C"
            l2_detail = "最新 L2 probe 未通过，需查看证据报告。"

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
            "status": l2_status,
            "evidenceLevel": l2_level,
            "requiresApproval": True,
            "command": "tools/probes/l2_readonly_probe.py --target data_acquisition|draft_box",
            "detail": l2_detail,
            "latest": latest_l2,
        },
        {
            "level": "L3",
            "title": "单商品 save-only 金丝雀",
            "status": "passed" if has_l3_save_proof else "approval_required",
            "evidenceLevel": "A" if has_l3_save_proof and has_l3_network else "B" if has_l3_save_proof else "C",
            "requiresApproval": True,
            "command": "single_save with manual approval token",
            "detail": (
                "已找到保存结果、未发布证明和网络/HAR 保存证据。"
                if has_l3_save_proof and has_l3_network
                else "已找到保存结果和未发布证明；缺少网络/HAR 保存证据。"
                if has_l3_save_proof
                else "真实写操作必须由用户明确批准，只能操作 Dang Kang 已备注归属商品。"
            ),
        },
    ]


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
                "screenshot_path": data.get("screenshot_path"),
                "screenshot_sha256": data.get("screenshot_sha256"),
                "dom_path": data.get("dom_path"),
                "dom_sha256": data.get("dom_sha256"),
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
            }
        )
    return summary


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
    if payload.get("ok") is True:
        return True
    url = str(payload.get("url") or "").lower()
    return "save" in url and _status_2xx_or_3xx(payload.get("status"))


def _network_event_save_response_seen(payload: Mapping[str, Any]) -> bool:
    url = str(payload.get("url") or "").lower()
    return "save" in url and _status_2xx_or_3xx(payload.get("status"))


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
            "target_text",
            "button_text",
            "button_label",
            "label",
            "text",
            "message",
            "reason",
            "body_excerpt",
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


def _acceptance_gaps(exceptions: list[dict[str, Any]], extracted: dict[str, Any]) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
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
                "detail": "真实 single_save 写操作必须在用户明确批准后执行。",
                "evidenceLevel": "C",
            }
        )
    return gaps


def _safety_state(extracted: dict[str, Any]) -> dict[str, Any]:
    grade = _evidence_grade(extracted)
    return {
        "mode": "single_save / batch_save / claim_only / dry_run / probe",
        "guarantee": "只保存不发布：工作台不提供任何发布动作入口，后端发布隔离固定开启。",
        "forbiddenActions": ["发布", "继续发布", "保存并发布", "移入待发布"],
        "lastCheckedAt": "runtime aggregation",
        "evidenceGrade": grade["grade"],
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
