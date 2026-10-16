"""临时数据库与真实 Worker 验证派发前取消，不启动浏览器或声明生产能力。"""

import asyncio
from threading import Event

import pytest

from src.batch_edit.editor_inventory_source import COMMAND_TYPE, SOURCE_TYPE
from src.execution import editor_inventory_runner as module
from src.execution.editor_inventory_runner import run_editor_control_inventory_observation
from src.execution.v1_runner import V1ExecutionError
from tests.support.editor_inventory_source_case import inventory_source_case, records


@pytest.mark.parametrize('phase', ['source_reservation', 'before_reserve', 'after_reserve', 'active_registration', 'before_run'])
def test_cancel_before_worker_dispatch_prevents_actual_observer(inventory_source_case, monkeypatch, phase):
    case = inventory_source_case
    runner, runtime, flow = case['runner'], case['runtime'], case['flow']
    runner.browser_agent_runtime, runner.workflow_adapter = runtime, runtime.adapter
    runner.workflow_action_timeout_seconds = 5
    entered, release, finished = Event(), Event(), Event()
    cancelled = []
    original_cancel, original_reserve, original_run, original_observe = (
        runtime.cancel_command, runtime.reserve_command, runtime.run, module._observe)
    original_source_reserve = case['repository'].reserve_editor_control_inventory

    def barrier():
        entered.set()
        assert release.wait(5)

    class DispatchBarrier(dict):
        def setdefault(self, key, value):
            result = super().setdefault(key, value)
            if phase == 'active_registration':
                barrier()
            return result

    def reserve(*args):
        if phase == 'before_reserve':
            barrier()
        result = original_reserve(*args)
        if phase == 'after_reserve':
            barrier()
        return result

    def source_reserve(*args):
        result = original_source_reserve(*args)
        if phase == 'source_reservation':
            barrier()
        return result

    def run(*args, **kwargs):
        if phase == 'before_run':
            barrier()
        return original_run(*args, **kwargs)

    def observe(*args):
        try:
            return original_observe(*args)
        finally:
            finished.set()

    def cancel(*args):
        result = original_cancel(*args)
        cancelled.append(result)
        return result

    runner._active_browser_agent_commands = DispatchBarrier()
    monkeypatch.setattr(runtime, 'cancel_command', cancel)
    monkeypatch.setattr(runtime, 'reserve_command', reserve)
    monkeypatch.setattr(runtime, 'run', run)
    monkeypatch.setattr(module, '_observe', observe)
    monkeypatch.setattr(case['repository'], 'reserve_editor_control_inventory', source_reserve)

    async def scenario():
        pending = asyncio.create_task(run_editor_control_inventory_observation(runner,
            task_id=case['task']['id'], job_id=case['job']['id']))
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            pending.cancel()
            with pytest.raises(V1ExecutionError) as failure:
                await pending
            assert failure.value.error_code == 'UNKNOWN'
            assert not hasattr(flow, 'observer_thread')
        finally:
            release.set()
        assert await asyncio.to_thread(finished.wait, 5)
        assert runner._active_browser_agent_commands == {}
        assert runtime.status()['reservedCommandCount'] == 0
        assert not hasattr(flow, 'observer_thread'), '取消返回后不得迟到执行只读观察'
        assert records(SOURCE_TYPE) == [] and len(records(COMMAND_TYPE)) == 1
        if phase == 'source_reservation':
            assert cancelled[0]['reasonCode'] == 'BROWSER_AGENT_COMMAND_NOT_ACTIVE'
        else:
            assert any(result.get('ok') is True and result.get('status') == 'cancelled_before_start' for result in cancelled)

    asyncio.run(scenario())


@pytest.mark.parametrize('phase', ['replaced_runtime', 'reservation_raised', 'registration_raised', 'registration_conflict'])
def test_failed_registration_releases_only_original_worker_reservation(inventory_source_case, monkeypatch, phase):
    case = inventory_source_case; runner, runtime, flow = case['runner'], case['runtime'], case['flow']
    runner.browser_agent_runtime, runner.workflow_adapter = runtime, runtime.adapter
    runner.workflow_action_timeout_seconds = 5
    original_reserve = runtime.reserve_command
    foreign_command = object()

    class FailedRegistration(dict):
        def setdefault(self, key, value):
            result = super().setdefault(key, value)
            if phase == 'registration_raised':
                raise RuntimeError('synthetic registration failure')
            return result

    runner._active_browser_agent_commands = FailedRegistration()

    def reserve(command):
        result = original_reserve(command)
        if phase == 'replaced_runtime':
            runner.browser_agent_runtime = object()
        elif phase == 'reservation_raised':
            raise RuntimeError('synthetic reservation completion failure')
        elif phase == 'registration_conflict':
            runner._active_browser_agent_commands[(command.task_id, command.job_id, command.state)] = foreign_command
        return result

    monkeypatch.setattr(runtime, 'reserve_command', reserve)
    with pytest.raises(V1ExecutionError) as failure:
        asyncio.run(run_editor_control_inventory_observation(runner, task_id=case['task']['id'], job_id=case['job']['id']))
    assert failure.value.error_code == 'UNKNOWN'
    assert runtime.status()['reservedCommandCount'] == 0 and not hasattr(flow, 'observer_thread')
    assert records(SOURCE_TYPE) == [] and len(records(COMMAND_TYPE)) == 1
    assert list(runner._active_browser_agent_commands.values()) == ([foreign_command] if phase == 'registration_conflict' else [])


@pytest.mark.parametrize('decision', [None, {'ok': False, 'reasonCode': 'BROWSER_AGENT_SESSION_BUSY'}, {'ok': 1}])
def test_runtime_reservation_rejection_never_enters_worker(inventory_source_case, monkeypatch, decision):
    case = inventory_source_case; runner, runtime = case['runner'], case['runtime']
    runner.browser_agent_runtime, runner.workflow_adapter = runtime, runtime.adapter
    monkeypatch.setattr(runtime, 'reserve_command', lambda _command: decision)
    with pytest.raises(V1ExecutionError) as failure:
        asyncio.run(run_editor_control_inventory_observation(runner, task_id=case['task']['id'], job_id=case['job']['id']))
    assert failure.value.error_code == 'UNKNOWN' and 'EDITOR_INVENTORY_RESERVATION_REJECTED' in str(failure.value)
    if isinstance(decision, dict) and decision.get('reasonCode'):
        assert decision['reasonCode'] in str(failure.value)
    assert runtime.status()['reservedCommandCount'] == 0 and not hasattr(case['flow'], 'observer_thread')
    assert records(SOURCE_TYPE) == [] and runner._active_browser_agent_commands == {}


@pytest.mark.parametrize('change', ['commandId', 'runtimeId', 'not_ok', 'unknown_status', 'boolean_alias', 'missing'])
def test_cleanup_does_not_consume_unknown_or_different_owner_reservation(inventory_source_case, monkeypatch, caplog, change):
    case = inventory_source_case; runner, runtime = case['runner'], case['runtime']
    runner.browser_agent_runtime, runner.workflow_adapter = runtime, runtime.adapter
    original_reserve, original_cancel = runtime.reserve_command, runtime.cancel_command
    runs = []

    def reserve(command):
        result = original_reserve(command)
        runner.browser_agent_runtime = object()
        return result

    def cancel(*args):
        result = original_cancel(*args)
        if change in {'commandId', 'runtimeId'}:
            return {**result, change: 'different-owner'}
        if change == 'not_ok':
            return {**result, 'ok': False}
        if change == 'unknown_status':
            return {**result, 'status': 'unknown'}
        if change == 'boolean_alias':
            return {**result, 'ok': 1}
        return None

    monkeypatch.setattr(runtime, 'reserve_command', reserve)
    monkeypatch.setattr(runtime, 'cancel_command', cancel)
    monkeypatch.setattr(runtime, 'run', lambda *_args, **_kwargs: runs.append(True))
    with pytest.raises(V1ExecutionError):
        asyncio.run(run_editor_control_inventory_observation(runner, task_id=case['task']['id'], job_id=case['job']['id']))
    assert not runs and not hasattr(case['flow'], 'observer_thread')
    assert runtime.status()['reservedCommandCount'] == 1 and records(SOURCE_TYPE) == []
    assert 'editor_inventory_reservation_release_failed' in caplog.text
