"""合成页面通过真实 Runtime/Worker 原文件和 Repo 来源；不证明生产控件或完整 FILL。"""

import asyncio
from copy import deepcopy
from pathlib import Path

import pytest

from src import db
from src.batch_edit.editor_inventory_contract import ACTION, STATE
from src.batch_edit.editor_inventory_source import COMMAND_TYPE, SOURCE_TYPE
from src.batch_edit.scope_contract import canonical_sha256
from src.execution.editor_inventory_runner import run_editor_control_inventory_observation
from src.execution.v1_runner import V1ExecutionError
from tests.support.editor_inventory_source_case import inventory_source_case, records


def ready(case):
    runner = case['runner']
    runner.browser_agent_runtime = case['runtime']
    runner.workflow_adapter = case['runtime'].adapter
    runner.workflow_action_timeout_seconds = 10
    return runner


def observe(case):
    return asyncio.run(run_editor_control_inventory_observation(ready(case),
        task_id=case['task']['id'], job_id=case['job']['id']))


def test_actual_runner_helper_persists_worker_source_without_changing_snapshot_or_creating_authority(inventory_source_case):
    case = inventory_source_case; repo = case['repository']; runner = ready(case)
    before = deepcopy(repo.get_task_private(case['task']['id']))
    result = observe(case)
    source = repo.require_editor_control_inventory(case['task']['id'], case['job']['id'], source_sha256=result['source_sha256'])
    command, inventory = source['command'], source['observation']['after']
    assert command['state'] == STATE and command['action'] == ACTION and command['runtime_id'] == case['runtime'].runtime_id
    assert command['params']['category_schema'] == before['payload']['plan_snapshot']['item_snapshots'][0]['category_schema']
    assert case['flow'].observer_thread.startswith('dxm-browser-agent')
    assert all(Path(source['artifacts'][name]['path']).is_file() for name in ('request', 'result'))
    assert Path(source['observation']['observation']['evidence_ref']['path']).is_file()
    assert len(records(COMMAND_TYPE)) == len(records(SOURCE_TYPE)) == 1
    assert source['authorization_created'] is False
    assert all(inventory[key] is False and result[key] is False for key in
        ('executionAllowed', 'capabilityCertified', 'inputFreezeAllowed', 'required_fields_complete'))
    assert inventory['missing'] and next(section for section in inventory['sections'] if section['code'] == 'template_tax')['state'] == 'MISSING'
    assert runner._active_browser_agent_commands == {} and repo.get_task_private(case['task']['id']) == before
    with db.connection() as conn:
        assert conn.execute('SELECT COUNT(*) AS n FROM mutation_dispatch_ledger').fetchone()['n'] == 0
        assert conn.execute("SELECT COUNT(*) AS n FROM job_evidences WHERE evidence_type='path_b_rollback_preparation'").fetchone()['n'] == 0


def test_caller_in_memory_schema_cannot_replace_database_original(inventory_source_case):
    case = inventory_source_case
    original = deepcopy(case['category'])
    case['task']['payload']['plan_snapshot']['item_snapshots'][0]['category_schema'] = {'caller_schema': True}
    result = observe(case)
    source = case['repository'].require_editor_control_inventory(case['task']['id'], case['job']['id'], source_sha256=result['source_sha256'])
    assert source['command']['params']['category_schema'] == original


def test_forged_private_getter_cannot_bypass_original_snapshot_row_at_reservation(inventory_source_case, monkeypatch):
    case = inventory_source_case; repo = case['repository']
    forged = deepcopy(repo.get_task_private(case['task']['id']))
    category = forged['payload']['plan_snapshot']['item_snapshots'][0]['category_schema']
    category['normalized_schema']['properties']['title']['ui_section'] = 'other_info'
    category['schema_hash'] = canonical_sha256(category['normalized_schema'])
    monkeypatch.setattr(repo, 'get_task_private', lambda _task_id: deepcopy(forged))
    with pytest.raises(V1ExecutionError) as failure:
        observe(case)
    assert failure.value.error_code == 'UNKNOWN'
    assert records(COMMAND_TYPE) == records(SOURCE_TYPE) == []
    assert not hasattr(case['flow'], 'observer_thread')
    assert case['runner']._active_browser_agent_commands == {}


def test_actual_worker_provider_failure_leaves_no_persisted_success_or_original_rollback(inventory_source_case, monkeypatch):
    case = inventory_source_case; calls = []

    def unprepared(**_params):
        calls.append(True)
        raise RuntimeError('EDITOR_INVENTORY_PREPARED_TRANSPORT_REQUIRED')

    monkeypatch.setattr(case['flow'], 'observe_editor_control_inventory', unprepared)
    with pytest.raises(V1ExecutionError) as failure:
        observe(case)
    assert failure.value.error_code == 'UNKNOWN' and calls == [True]
    assert len(records(COMMAND_TYPE)) == 1 and records(SOURCE_TYPE) == []
    assert case['runner']._active_browser_agent_commands == {}
    assert list(case['screenshots'].parent.glob('workflow_worker/*.result.json'))


def test_persistence_failure_after_actual_worker_stops_without_replay(inventory_source_case, monkeypatch):
    case = inventory_source_case; calls = []

    def failed(*_args, **_kwargs):
        calls.append(True)
        raise RuntimeError('synthetic source persistence unavailable')

    monkeypatch.setattr(case['repository'], 'persist_editor_control_inventory', failed)
    with pytest.raises(V1ExecutionError) as failure:
        observe(case)
    assert failure.value.error_code == 'UNKNOWN' and calls == [True]
    assert case['flow'].observer_thread.startswith('dxm-browser-agent')
    assert len(records(COMMAND_TYPE)) == 1 and records(SOURCE_TYPE) == []
    assert case['runner']._active_browser_agent_commands == {}
