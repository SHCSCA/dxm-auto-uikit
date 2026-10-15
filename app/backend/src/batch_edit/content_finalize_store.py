from __future__ import annotations

from src.batch_edit.content_finalize_sources import validate_content_sources
from src.batch_edit.frozen_execution_contract import FrozenExecutionContractError, build_content_finalize_stage_freeze
from src.batch_edit.scope_contract import canonical_sha256
from src.db import dumps, loads
from src.services.evidence_ref import validate_evidence_ref


EVIDENCE_TYPE = "path_b_content_finalize_freeze"


def _reject(code, detail):
    raise FrozenExecutionContractError(code, detail)


def _candidate_sources(conn, *, task, job, observation, receipts, screenshot_root):
    from src.execution.batch_dispatch_authority import snapshot_row_authority_in_transaction

    if (not task or not job or task.get("mode") != "batch_draft_save"
            or task.get("payload", {}).get("plan_snapshot", {}).get("path") != "B"
            or job.get("task_id") != task.get("id")):
        _reject("CONTENT_FINALIZE_TASK_IDENTITY_INVALID", "最终输出必须绑定同一 Path B 任务与商品")
    candidate = build_content_finalize_stage_freeze(task, job, observation=observation, receipts=receipts)
    if validate_evidence_ref(candidate["observation"]["evidence_ref"], screenshot_root=screenshot_root).get("ok") is not True:
        _reject("CONTENT_FINALIZE_SCREENSHOT_DRIFT", "最终读回截图缺失或摘要不符")
    scope_row = conn.execute("SELECT * FROM real_dxm_write_scopes WHERE scope_sha256=?", (candidate["scope_sha256"],)).fetchone()
    if not scope_row or scope_row["task_id"] != task["id"] or scope_row["status"] != "consumed":
        _reject("CONTENT_FINALIZE_SCOPE_NOT_CONSUMED", "最终输出没有绑定已消费的同任务作用域")
    from src.real_dxm_write_scope import validate_real_dxm_write_scope
    scope = validate_real_dxm_write_scope(loads(scope_row["scope_json"], {}), now=observation["observed_at"])
    if (scope["scopeSha256"] != candidate["scope_sha256"] or scope["snapshot"] != {
            "snapshotId": task["payload"]["plan_snapshot_id"], "snapshotSha256": candidate["snapshot_sha256"], "taskId": task["id"]}
            or str(scope["shop"]["shopId"]) != str(task["store_id"])
            or scope["runtime"]["browserSessionId"] != observation["browser_session_id"]):
        _reject("CONTENT_FINALIZE_SCOPE_IDENTITY_DRIFT", "最终输出与已消费作用域的快照、店铺或会话不一致")
    authority = snapshot_row_authority_in_transaction(conn, task["id"])
    records = [loads(row["meta_json"], {}) for row in conn.execute(
        "SELECT meta_json FROM job_evidences WHERE task_id=? AND job_id=? AND evidence_type='path_b_editor_source' ORDER BY id",
        (task["id"], job["id"])).fetchall()]
    if any(source.get("command", {}).get("runtime_id") != scope["runtime"]["browserRuntimeId"] for source in records):
        _reject("CONTENT_FINALIZE_SOURCE_IDENTITY_DRIFT", "动作来源不属于已批准的浏览器运行时")
    validate_content_sources(conn, task=task, job=job, candidate=candidate, records=records,
                             screenshot_root=screenshot_root, snapshot_authority=authority)
    return candidate, records


def append_content_finalize_stage(conn, *, task, job, observation, receipts, screenshot_root, now):
    """仅在同一事务内重新核实所有实际来源后追加封存；不改原快照与原值。"""
    if not task or not job or task.get("status") != "running" or job.get("status") != "running" or job.get("current_step_code") != "BATCH_TRANSLATE_EXECUTE":
        _reject("CONTENT_FINALIZE_STATE_INVALID", "最终输出只能在真实翻译完成的同一运行商品中封存")
    existing = conn.execute("SELECT id FROM job_evidences WHERE task_id=? AND job_id=? AND evidence_type=?",
                            (task["id"], job["id"], EVIDENCE_TYPE)).fetchall()
    if existing:
        _reject("CONTENT_FINALIZE_STAGE_ALREADY_RECORDED", "最终输出封存不允许覆盖或重复追加")
    candidate, sources = _candidate_sources(conn, task=task, job=job, observation=observation, receipts=receipts,
                                            screenshot_root=screenshot_root)
    body = {"schema": "dxm.persisted_content_finalize.v1", "candidate": candidate,
            "source_sha256s": [source["source_sha256"] for source in sources], "created_at": now}
    record = {**body, "record_sha256": canonical_sha256(body)}
    conn.execute("INSERT INTO job_evidences(task_id,job_id,evidence_type,file_path,meta_json,created_at) VALUES(?,?,?,?,?,?)",
                 (task["id"], job["id"], EVIDENCE_TYPE, observation["evidence_ref"]["path"], dumps(record), now))
    return record


def require_content_finalize_stage(conn, *, task, job, browser_session_id, screenshot_root):
    """消费时重新读取持久记录与原始证据，调用方提供的候选 map 不参与权威。"""
    if not task or not job:
        _reject("CONTENT_FINALIZE_STAGE_NOT_FROZEN", "SAVE1 requires persisted, independently verified generated outputs")
    rows = conn.execute("SELECT meta_json FROM job_evidences WHERE task_id=? AND job_id=? AND evidence_type=? ORDER BY id",
                        (task["id"], job["id"], EVIDENCE_TYPE)).fetchall()
    if not rows:
        _reject("CONTENT_FINALIZE_STAGE_NOT_FROZEN", "SAVE1 requires persisted, independently verified generated outputs")
    if len(rows) != 1:
        _reject("CONTENT_FINALIZE_STAGE_DUPLICATE", "同商品出现多条最终封存记录")
    record = loads(rows[0]["meta_json"], {})
    if (not isinstance(record, dict) or set(record) != {"schema", "candidate", "source_sha256s", "created_at", "record_sha256"}
            or record["schema"] != "dxm.persisted_content_finalize.v1"
            or canonical_sha256({key: value for key, value in record.items() if key != "record_sha256"}) != record["record_sha256"]):
        _reject("CONTENT_FINALIZE_STAGE_RECORD_DRIFT", "持久最终输出记录的结构或摘要已改变")
    candidate = record["candidate"]
    if not isinstance(candidate, dict) or candidate.get("observation", {}).get("browser_session_id") != browser_session_id:
        _reject("CONTENT_FINALIZE_SOURCE_SESSION_DRIFT", "最终输出不是当前浏览器会话产生")
    expected, sources = _candidate_sources(conn, task=task, job=job, observation=candidate.get("observation"),
        receipts=candidate.get("receipts"), screenshot_root=screenshot_root)
    if expected != candidate or record["source_sha256s"] != [source["source_sha256"] for source in sources]:
        _reject("CONTENT_FINALIZE_STAGE_RECORD_DRIFT", "最终输出或动作前序来源在封存后变化")
    return record
