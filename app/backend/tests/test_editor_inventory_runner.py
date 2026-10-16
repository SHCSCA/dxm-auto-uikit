"""只验证 Runner 调度与失败边界；来源权威由独立真实 Worker 集成用例验证。"""

import asyncio
from copy import deepcopy
from threading import Event

import pytest

from src.batch_edit.editor_inventory_contract import ACTION, PARAMS, STATE
from src.batch_edit.scope_contract import canonical_sha256
from src.execution.editor_inventory_runner import run_editor_control_inventory_observation
from src.execution.v1_runner import V1ExecutionError
from tests.support.editor_inventory_runner_case import InventoryRuntimeSpy, inventory_runner_case


def observe(case):
    return asyncio.run(run_editor_control_inventory_observation(case['runner'],
        task_id=case['task']['id'], job_id=case['job']['id']))


def test_only_ids_select_fresh_database_schema_and_no_capability_is_created(inventory_runner_case):
    case = inventory_runner_case
    before = deepcopy(case['repository'].get_task_private(case['task']['id']))
    case['task']['payload']['plan_snapshot']['item_snapshots'][0]['category_schema'] = {'caller_changed': True}
    result = observe(case)
    command = case['runtime'].calls[0]
    schema = before['payload']['plan_snapshot']['item_snapshots'][0]['category_schema']
    assert command.state == STATE and command.action == ACTION and command.expected_page == 'editor'
    assert set(command.params) == PARAMS and command.execution_payload_hash is None
    assert command.params['category_schema'] == schema
    assert canonical_sha256(schema['normalized_schema']) == command.params['defaults']['_frozen_execution_payload']['category_schema_hash']
    assert case['events'] == ['reserve', 'persist'] and len(case['runtime'].calls) == 1
    assert result == {'source_sha256': 'E' * 64, 'executionAllowed': False, 'capabilityCertified': False,
        'inputFreezeAllowed': False, 'required_fields_complete': False}
    assert case['repository'].get_task_private(case['task']['id']) == before
    assert case['runner']._active_browser_agent_commands == {}


@pytest.mark.parametrize('change', ['missing_runtime', 'unhealthy', 'wrong_step', 'missing_job', 'schema_drift', 'duplicate_item'])
def test_unprepared_or_changed_input_stops_unknown_before_reservation(inventory_runner_case, monkeypatch, caplog, change):
    case = inventory_runner_case; repo = case['repository']; original = repo.get_task_private
    if change == 'missing_runtime':
        case['runner'].browser_agent_runtime = None
    elif change == 'unhealthy':
        case['runtime'].healthy = False
    else:
        current = original(case['task']['id'])
        if change == 'wrong_step': current['jobs'][0]['current_step_code'] = 'FILL_BASE_INFO'
        elif change == 'missing_job': current['jobs'] = []
        elif change == 'schema_drift':
            current['payload']['plan_snapshot']['item_snapshots'][0]['category_schema']['normalized_schema']['properties']['title']['type'] = 'integer'
        else:
            current['payload']['plan_snapshot']['item_snapshots'].append(deepcopy(current['payload']['plan_snapshot']['item_snapshots'][0]))
        monkeypatch.setattr(repo, 'get_task_private', lambda _task_id: deepcopy(current))
    with pytest.raises(V1ExecutionError) as failure:
        observe(case)
    assert failure.value.error_code == 'UNKNOWN'
    assert case['events'] == [] and case['runtime'].calls == []
    assert case['runner']._active_browser_agent_commands == {}
    assert 'editor_inventory_observation_failed' in caplog.text


@pytest.mark.parametrize('phase', ['reserve', 'worker', 'persist'])
def test_each_failure_stops_once_cancels_and_never_falls_back(inventory_runner_case, monkeypatch, phase):
    case = inventory_runner_case

    def failed(*_args, **_kwargs):
        raise RuntimeError('synthetic ' + phase + ' failure')

    if phase == 'worker': case['runtime'].on_run = failed
    else: monkeypatch.setattr(case['repository'], phase + '_editor_control_inventory', failed)
    with pytest.raises(V1ExecutionError) as failure:
        observe(case)
    assert failure.value.error_code == 'UNKNOWN'
    assert len(case['runtime'].calls) == (0 if phase == 'reserve' else 1)
    assert len(case['runtime'].cancelled) == 1
    assert case['runner']._active_browser_agent_commands == {}


@pytest.mark.parametrize('phase', ['reserve', 'worker'])
def test_runtime_replacement_cannot_move_the_command_to_a_second_owner(inventory_runner_case, monkeypatch, phase):
    case = inventory_runner_case; original = case['repository'].reserve_editor_control_inventory
    replacement = InventoryRuntimeSpy('replacement')

    def replaced(*args):
        if phase == 'reserve': original(*args)
        case['runner'].browser_agent_runtime = replacement
        return {'synthetic_orchestration_result': True}

    if phase == 'reserve': monkeypatch.setattr(case['repository'], 'reserve_editor_control_inventory', replaced)
    else: case['runtime'].on_run = replaced
    with pytest.raises(V1ExecutionError) as failure:
        observe(case)
    assert failure.value.error_code == 'UNKNOWN'
    assert 'persist' not in case['events'] and case['runner']._active_browser_agent_commands == {}
    assert len(case['runtime'].cancelled) == 1 and replacement.cancelled == [] and replacement.calls == []


def test_existing_active_command_is_preserved_instead_of_overwritten(inventory_runner_case):
    case = inventory_runner_case; runner = case['runner']
    key = (case['task']['id'], case['job']['id'], STATE); original = object()
    runner._active_browser_agent_commands[key] = original
    with pytest.raises(V1ExecutionError) as failure:
        observe(case)
    assert failure.value.error_code == 'UNKNOWN'
    assert runner._active_browser_agent_commands[key] is original and case['events'] == []
    runner._active_browser_agent_commands.clear()


def test_private_schema_copy_is_not_shared_with_repository_or_reservation(inventory_runner_case):
    case = inventory_runner_case; before = deepcopy(case['repository'].get_task_private(case['task']['id']))

    def changed(command):
        command.params['category_schema']['normalized_schema']['properties']['title']['type'] = 'integer'
        return {'synthetic_orchestration_result': True}

    case['runtime'].on_run = changed
    with pytest.raises(V1ExecutionError):
        observe(case)
    assert case['repository'].get_task_private(case['task']['id']) == before
    assert case['commands'][0]['params']['category_schema'] == before['payload']['plan_snapshot']['item_snapshots'][0]['category_schema']


def test_cancelled_wait_keeps_owner_until_finalization_and_rejects_late_persistence(inventory_runner_case):
    case = inventory_runner_case; entered, release = Event(), Event()

    def held(_command):
        entered.set()
        assert release.wait(5)
        return {'synthetic_orchestration_result': True}

    case['runtime'].on_run = held

    async def scenario():
        pending = asyncio.create_task(run_editor_control_inventory_observation(case['runner'],
            task_id=case['task']['id'], job_id=case['job']['id']))
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            pending.cancel()
            with pytest.raises(V1ExecutionError) as failure:
                await pending
            assert failure.value.error_code == 'UNKNOWN'
            assert case['runtime'].cancelled and case['runner']._active_browser_agent_commands
        finally:
            release.set()
        for _attempt in range(100):
            if not case['runner']._active_browser_agent_commands:
                break
            await asyncio.sleep(0.01)
        assert case['runner']._active_browser_agent_commands == {} and 'persist' not in case['events']

    asyncio.run(scenario())
