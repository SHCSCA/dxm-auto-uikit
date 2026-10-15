from copy import deepcopy
from dataclasses import replace

import pytest

from src import db
from src.batch_edit.content_finalize_sources import _validate_translation_source
from src.batch_edit.frozen_execution_contract import compile_frozen_execution_payload, frozen_execution_defaults
from src.batch_edit.scope_contract import canonical_sha256
from src.execution.batch_dispatch_authority import (
    snapshot_row_authority_in_transaction, validate_current_task_against_frozen_authority,
)
from src.execution.content_action_authority import validate_current_translation_authority
from src.state_machine.contracts import StateName
from tests.support.content_authority_case import NOW, content_dispatch_case


@pytest.fixture()
def translation_source(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "content-authority.db")
    db.init_db()
    case = content_dispatch_case(monkeypatch)
    repo, runner, dispatch = case["repository"], case["runner"], case["dispatch"]
    task = repo.get_task_private(case["task"]["id"])
    job = task["jobs"][0]
    state = StateName.BATCH_TRANSLATE_EXECUTE
    assert repo.update_job(job["id"], status="running", current_step_code=state.value, current_step_name="翻译合同")
    task = repo.get_task_private(task["id"])
    job = task["jobs"][0]
    defaults = frozen_execution_defaults(compile_frozen_execution_payload(task, job))
    spec = runner._workflow_action_worker_request(task, job, state, defaults)
    command = runner._build_browser_agent_command(task, job, state, spec[0], spec[3])
    identity = {"browser_session_id": case["live"].browser_session_id, "page_kind": "editor",
        "page_url": f'https://www.dianxiaomi.com/web/smt/edit?id={job["product_id"]}', "target_hash": command.target_hash}
    # 只通过真实 ledger 状态机准备来源，不执行浏览器动作，也不声称业务或保存成功。
    assert dispatch.reserve_command(command).ok
    begun = dispatch.begin_dispatch(command, "translate_language_click", identity)
    assert begun.ok, begun.reason_code
    assert dispatch.mark_dispatched(command, "translate_language_click", {"contract_callback_returned": True}).ok
    with db.connection() as conn:
        row = dict(conn.execute("SELECT * FROM mutation_dispatch_ledger WHERE command_id=?", (command.command_id,)).fetchone())
    authority = db.loads(row["save_authority_json"], {})
    observed_command = {key: command.to_payload()[key] for key in ("command_id", "state", "task_id", "job_id", "runtime_id")}
    observed_command.update(command_action=command.action, browser_session_id=identity["browser_session_id"])
    observed = {"command": observed_command, "page_url": identity["page_url"], "started_at": NOW,
        "completed_at": NOW, "mutation_authorization": {"mutation_id": row["mutation_id"]}}
    return {**case, "task": task, "job": job, "command": command, "row": row, "authority": authority,
            "observation": observed}


def validate(case, *, command=None, authority=None, observation=None):
    with db.connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        before = conn.total_changes
        decision = validate_current_translation_authority(conn, authority or case["authority"],
            command=command or case["command"], observation=observation or case["observation"])
        assert conn.total_changes == before
        return decision


def test_actual_dispatched_translation_consumes_only_its_derived_save1_grant(translation_source):
    case = translation_source
    decision = validate(case)
    assert decision.ok, decision.reason_code
    grant = decision.authority["authorization"]["lease_authority"]
    assert grant["action_state"] == "BATCH_TRANSLATE_EXECUTE"
    assert grant["parent_lease_id"] == case["original_leases"][0]["lease_id"]
    assert grant["save_stage"] == "SAVE1"
    assert grant["lease_id"] not in {lease["lease_id"] for lease in case["original_leases"]}
    with db.connection() as conn:
        assert conn.execute("SELECT count(*) AS n FROM canonical_receipts").fetchone()["n"] == 0
        assert conn.execute("SELECT count(*) AS n FROM mutation_dispatch_ledger").fetchone()["n"] == 1
    assert case["repository"].get_task_private(case["task"]["id"])["payload"]["real_dxm_write_authorization"]["save_leases"] == case["original_leases"]


def test_save_verification_still_rejects_a_content_state(translation_source):
    with db.connection() as conn:
        result = validate_current_task_against_frozen_authority(conn, translation_source["authority"])
    assert not result.ok and result.reason_code == "AUTH_CURRENT_QUEUE_DRIFT"


@pytest.mark.parametrize("changes", [
    {"state": "BATCH_VIDEO_SUBMIT", "action": "submit_editor_video"},
    {"state": "SAVE_ONLY", "action": "save_only"},
    {"action": "validate_editor_wholesale"},
    {"execution_mode": "single_save"},
    {"expected_page": "semi_managed"},
])
def test_another_action_or_save_cannot_use_translation_source_validation(translation_source, changes):
    result = validate(translation_source, command=replace(translation_source["command"], **changes))
    assert not result.ok and result.reason_code == "AUTH_CONTENT_SOURCE_COMMAND_INVALID"


@pytest.mark.parametrize("step", ["BATCH_VIDEO_SUBMIT", "BATCH_WHOLESALE_FILL", "FIRST_SAVE_INTENT", "SAVE2_ONLY"])
def test_translation_source_requires_its_exact_current_step(translation_source, step):
    case = translation_source
    assert case["repository"].update_job(case["job"]["id"], current_step_code=step)
    result = validate(case)
    assert not result.ok and result.reason_code == "AUTH_CURRENT_QUEUE_DRIFT"


@pytest.mark.parametrize("sql", [
    "UPDATE mutation_dispatch_ledger SET status='UNKNOWN', unknown_at='2026-08-31T00:01:00Z'",
    "UPDATE mutation_dispatch_ledger SET status='RESERVED'",
    "UPDATE mutation_dispatch_ledger SET command_sha256='changed'",
    "UPDATE mutation_dispatch_ledger SET save_authority_sha256='changed'",
    "UPDATE mutation_dispatch_ledger SET snapshot_row_authority_sha256='changed'",
    "DELETE FROM mutation_dispatch_ledger",
])
def test_uncertain_unissued_or_changed_ledger_never_supplies_a_content_source(translation_source, sql):
    with db.connection() as conn:
        conn.execute(sql)
    result = validate(translation_source)
    assert not result.ok


def test_current_shared_policy_drift_is_rejected(translation_source):
    case = translation_source
    payload = deepcopy(case["task"]["payload"])
    payload["plan_snapshot"]["item_snapshots"][0]["content_finalize_policy"]["order"].reverse()
    with db.connection() as conn:
        conn.execute("UPDATE tasks SET payload_json=? WHERE id=?", (db.dumps(payload), case["task"]["id"]))
    result = validate(case)
    assert not result.ok and result.reason_code == "AUTH_CURRENT_TASK_DRIFT"


def test_caller_cannot_replace_frozen_execution_policy(translation_source):
    authority = deepcopy(translation_source["authority"])
    authority["execution"]["payload"]["content_finalize_policy"]["source_sha256"] = "F" * 64
    result = validate(translation_source, authority=authority)
    assert not result.ok and result.reason_code == "AUTH_CONTENT_SOURCE_POLICY_DRIFT"


def test_derived_grant_cannot_name_another_save1_parent(translation_source):
    authority = deepcopy(translation_source["authority"])
    authority["authorization"]["lease_authority"]["parent_lease_id"] = "F" * 64
    result = validate(translation_source, authority=authority)
    assert not result.ok and result.reason_code == "AUTH_FROZEN_AUTHORITY_INVALID"


def test_revoked_real_scope_cannot_be_consumed_as_a_translation_source(translation_source):
    with db.connection() as conn:
        conn.execute("UPDATE real_dxm_write_scopes SET status='prepared'")
    result = validate(translation_source)
    assert not result.ok and result.reason_code == "AUTH_REAL_WRITE_SCOPE_BINDING_MISMATCH"


def test_content_source_consumer_accepts_actual_translation_dispatch_lineage(translation_source):
    case, command = translation_source, translation_source["command"]
    parent_command = {**command.to_payload(), "command_id": "preceding-wholesale",
                      "state": "BATCH_WHOLESALE_FILL", "action": "validate_editor_wholesale"}
    session = case["live"].browser_session_id
    wholesale_command = {key: parent_command[key] for key in ("command_id", "action", "state", "task_id", "job_id", "runtime_id")}
    wholesale_command["browser_session_id"] = session
    observed = {**case["observation"], "wholesale_command_id": parent_command["command_id"],
                "shop_id": command.params["shop_id"]}
    parent = {"command": parent_command, "source_sha256": "E" * 64,
        "action_result": {"ok": True, "attempted_state": "BATCH_WHOLESALE_FILL", "action": "validate_editor_wholesale",
            "page_identity": {"browser_session_id": session}, "evidence": {"observations": {
                "wholesale_observation": {"command": wholesale_command, "page_url": observed["page_url"], "completed_at": NOW}}}}}
    record = {"command": command.to_payload(),
        "action_result": {"evidence": {"observations": {"translation_observation": observed}}},
        "translation_dispatch_source": {"row": case["row"], "row_sha256": canonical_sha256(case["row"]),
                                       "predecessor_source_sha256": parent["source_sha256"]}}
    # 此处只验证来源连接层；完整业务回执、文件和视频封存仍由上层独立门禁验证。
    with db.connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        snapshot = snapshot_row_authority_in_transaction(conn, case["task"]["id"])
        before = conn.total_changes
        _validate_translation_source(conn, record, parent,
            {"observation": {"browser_session_id": session}}, snapshot)
        assert conn.total_changes == before
