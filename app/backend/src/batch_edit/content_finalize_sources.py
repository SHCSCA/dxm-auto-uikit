from __future__ import annotations

from collections.abc import Mapping

from src.batch_edit.frozen_execution_contract import FrozenExecutionContractError
from src.batch_edit.scope_contract import canonical_sha256
from src.execution.e3_authority_contract import parse_strict_utc_timestamp


SOURCE_ORDER = ("FILL_BASE_INFO", "BATCH_VIDEO_SUBMIT", "BATCH_VIDEO_PLACE", "BATCH_WHOLESALE_FILL", "BATCH_TRANSLATE_EXECUTE")
_ACTIONS = {
    "FILL_BASE_INFO": "fill_editor_required_defaults",
    "BATCH_WHOLESALE_FILL": "validate_editor_wholesale",
    "BATCH_TRANSLATE_EXECUTE": "translate_editor_content",
}


def _reject(code, detail):
    raise FrozenExecutionContractError(code, detail)


def index_content_sources(records, *, task, job, candidate):
    """核对来源索引的完整性和顺序；返回值本身不表示文件或动作已验证。"""
    indexed, command_ids, positions = {}, set(), []
    session = candidate["observation"]["browser_session_id"]
    for record in records:
        if (not isinstance(record, Mapping) or record.get("schema") != "dxm.path_b_editor_source.v1"
                or canonical_sha256({key: value for key, value in record.items() if key != "source_sha256"}) != record.get("source_sha256")):
            _reject("CONTENT_FINALIZE_SOURCE_HASH_DRIFT", "动作来源摘要失配")
        command = record.get("command", {})
        result = record.get("action_result", {})
        if not isinstance(command, Mapping) or not isinstance(result, Mapping):
            _reject("CONTENT_FINALIZE_SOURCE_IDENTITY_DRIFT", "动作来源缺少结构化命令或结果")
        state = command.get("state")
        if (record.get("task_id") != task["id"] or record.get("job_id") != job["id"]
                or str(record.get("product_id")) != str(job["product_id"])
                or command.get("task_id") != task["id"] or command.get("job_id") != job["id"]
                or record.get("snapshot_sha256") != candidate["snapshot_sha256"]
                or record.get("scope_sha256") != candidate["scope_sha256"]
                or record.get("execution_payload_hash") != candidate["initial_execution_payload_hash"]):
            _reject("CONTENT_FINALIZE_SOURCE_IDENTITY_DRIFT", "动作来源不属于当前任务、商品、快照或作用域")
        if result.get("page_identity", {}).get("browser_session_id") != session:
            _reject("CONTENT_FINALIZE_SOURCE_SESSION_DRIFT", "动作来源浏览器会话不一致")
        if (state not in SOURCE_ORDER or state in indexed or not command.get("command_id")
                or command["command_id"] in command_ids):
            _reject("CONTENT_FINALIZE_SOURCE_DUPLICATE", "动作来源存在未知步骤、重复步骤或复用命令")
        if result.get("ok") is not True:
            _reject("CONTENT_FINALIZE_SOURCE_NOT_SUCCESSFUL", "失败或不确定动作不能作为最终输出来源")
        if parse_strict_utc_timestamp(record.get("created_at"), field="content source time") > parse_strict_utc_timestamp(
                candidate["observation"]["observed_at"], field="content observation time"):
            _reject("CONTENT_FINALIZE_SOURCE_ORDER_INVALID", "最终读回早于其动作来源")
        indexed[state] = record
        command_ids.add(command["command_id"])
        positions.append(SOURCE_ORDER.index(state))
    if positions != sorted(positions):
        _reject("CONTENT_FINALIZE_SOURCE_ORDER_INVALID", "动作来源未按首写、视频、批发、翻译的顺序持久化")
    return indexed


def validate_content_sources(conn, *, task, job, candidate, records, screenshot_root, snapshot_authority):
    """复核当前已审阅的生产来源；视频和最终读回未绑定时始终关闭封存。"""
    from src.execution.action_result_contract import validate_action_result_envelope
    from src.execution.browser_agent_protocol import BrowserAgentCommand
    from src.execution.browser_agent_worker import load_browser_agent_action_source
    from src.services.evidence_ref import validate_evidence_ref

    indexed = index_content_sources(records, task=task, job=job, candidate=candidate)
    for state, action in _ACTIONS.items():
        record = indexed.get(state)
        if record is None:
            _reject("CONTENT_FINALIZE_SOURCE_MISSING", f"缺少已持久化的 {state} 来源")
        command = BrowserAgentCommand(**record["command"])
        session = candidate["observation"]["browser_session_id"]
        if (command.state != state or command.action != action or command.execution_mode != "batch_draft_save"
                or record.get("snapshot_row_authority_sha256") != canonical_sha256(snapshot_authority)):
            _reject("CONTENT_FINALIZE_SOURCE_AUTHORITY_DRIFT", "动作命令或快照行权威不一致")
        artifacts = load_browser_agent_action_source(record["command"], record["action_result"], browser_session_id=session)
        if record.get("artifacts") != artifacts:
            _reject("CONTENT_FINALIZE_SOURCE_FILE_DRIFT", "Worker 原始文件已变化")
        envelope = validate_action_result_envelope(record["action_result"], expected_state=state, expected_action=action,
            expected_page="editor", execution_mode="batch_draft_save", expected_runtime_id=command.runtime_id,
            expected_browser_session_id=session,
            expected_execution_payload=command.params.get("defaults", {}).get("_frozen_execution_payload"))
        refs = envelope["evidence"]["refs"]
        if not refs or any(validate_evidence_ref({key: ref[key] for key in ("path", "sha256", "size")},
                screenshot_root=screenshot_root).get("ok") is not True for ref in refs):
            _reject("CONTENT_FINALIZE_SOURCE_SCREENSHOT_DRIFT", "动作截图缺失或失去完整性")
        if state == "BATCH_WHOLESALE_FILL":
            from src.batch_edit.wholesale_filler import validate_wholesale_first_fill_source
            parent = indexed["FILL_BASE_INFO"]
            validate_wholesale_first_fill_source(envelope["evidence"]["observations"]["wholesale_observation"]["writer"],
                {"browser_agent_command": parent["command"], "action_result": parent["action_result"]},
                command=record["command"], browser_session_id=session)
        elif state == "BATCH_TRANSLATE_EXECUTE":
            _validate_translation_source(conn, record, indexed["BATCH_WHOLESALE_FILL"], candidate, snapshot_authority)
        if state != "FILL_BASE_INFO":
            capability = "wholesale" if state == "BATCH_WHOLESALE_FILL" else "translation"
            receipt = envelope["evidence"]["observations"].get("mandatory_capability_receipts", {}).get(capability)
            if receipt != candidate["receipts"][capability]:
                _reject("CONTENT_FINALIZE_RECEIPT_SOURCE_DRIFT", "候选回执不是已持久化命令实际产生的回执")
    require_reviewed_video_source(indexed)


def require_reviewed_video_source(indexed):
    # 不能仅凭步骤名、候选回执或手填来源，把尚未审阅的生产视频语义升级为成功。
    _reject("CONTENT_FINALIZE_VIDEO_SOURCE_NOT_BOUND", "真实视频生成与投放来源尚未绑定，不能追加最终输出封存")


def _validate_translation_source(conn, record, predecessor, candidate, snapshot_authority):
    from src.batch_edit.translator import validate_translation_wholesale_source
    from src.execution.browser_agent_protocol import BrowserAgentCommand
    from src.execution.content_action_authority import validate_current_translation_authority
    from src.execution.mutation_dispatch_ledger import MutationDispatchLedger

    observed = record["action_result"]["evidence"]["observations"]["translation_observation"]
    session = candidate["observation"]["browser_session_id"]
    validate_translation_wholesale_source(observed,
        {"browser_agent_command": predecessor["command"], "action_result": predecessor["action_result"]},
        command=record["command"], browser_session_id=session)
    rows = conn.execute("SELECT * FROM mutation_dispatch_ledger WHERE command_id=?", (record["command"]["command_id"],)).fetchall()
    if len(rows) != 1:
        _reject("CONTENT_FINALIZE_LEDGER_NOT_UNIQUE", "翻译派发账本不是唯一来源")
    row = dict(rows[0])
    binding = record.get("translation_dispatch_source", {})
    if (binding.get("row") != row or binding.get("row_sha256") != canonical_sha256(row)
            or binding.get("predecessor_source_sha256") != predecessor["source_sha256"]):
        _reject("CONTENT_FINALIZE_LEDGER_DRIFT", "翻译账本或批发前序来源已变化")
    authority = MutationDispatchLedger.validate_translation_source(row, BrowserAgentCommand(**record["command"]),
        observed, snapshot_row_authority_sha256=canonical_sha256(snapshot_authority))
    if validate_current_translation_authority(conn, authority,
            command=BrowserAgentCommand(**record["command"]), observation=observed).ok is not True:
        _reject("CONTENT_FINALIZE_SOURCE_AUTHORITY_DRIFT", "翻译派发权威不再成立")
