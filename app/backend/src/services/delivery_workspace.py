from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
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
