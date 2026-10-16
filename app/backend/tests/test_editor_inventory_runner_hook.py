"""实际执行 V1 的步骤循环；其它阶段显式隔离，任何用例均不证明完整商品成功。"""

import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from src.execution import v1_runner as module
from src.execution.closed_loop_replay_adapter import ClosedLoopReplayAdapter
from src.execution.v1_runner import V1ExecutionError
from src.state_machine.contracts import StateName
from tests.support.editor_inventory_runner_case import inventory_runner_case


def isolated_hook(case, monkeypatch, tmp_path, *, mode='batch_draft_save', path='B', replay=False, failed=False):
    runner, repo = case['runner'], case['repository']
    task, job, events = deepcopy(case['task']), deepcopy(case['job']), []
    task['mode'] = mode; task['payload']['plan_snapshot']['path'] = path
    state_file = tmp_path / 'synthetic-state.json'; state_file.write_text('{}', encoding='utf8')
    runner.manager = SimpleNamespace(broadcast=lambda *_args: asyncio.sleep(0))
    if replay:
        runner.workflow_adapter = object.__new__(ClosedLoopReplayAdapter)
    monkeypatch.setattr(runner, '_execution_defaults', lambda *_args, **_kwargs: {})
    monkeypatch.setattr(runner, '_product', lambda *_args: None)
    monkeypatch.setattr(runner, '_steps_for_mode', lambda *_args, **_kwargs: [
        (StateName.PREPARE_ROLLBACK, '合成回滚准备', 'rollback_preparation')])
    monkeypatch.setattr(runner, '_guard_path_b_phase_before_state', lambda *_args: None)
    monkeypatch.setattr(runner, '_require_task_writer_fence', lambda *_args: None)
    monkeypatch.setattr(runner, '_guard_step', lambda *_args: None)
    monkeypatch.setattr(runner, '_write_evidence', lambda *_args: state_file)
    monkeypatch.setattr(runner, '_sync_agent_console', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runner, '_sync_live_browser_hud', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runner, '_build_summary', lambda *_args, **_kwargs: {'scope': 'synthetic_hook_only'})

    async def observe(actual, **ids):
        assert actual is runner and ids == {'task_id': task['id'], 'job_id': job['id']}
        current = repo.get_task_private(task['id'])['jobs'][0]
        assert current['status'] == 'running' and current['current_step_code'] == 'PREPARE_ROLLBACK'
        events.append('inventory')
        if failed:
            raise V1ExecutionError('UNKNOWN', '合成来源失败', 'synthetic_inventory_rejected')
        return {'source_sha256': 'E' * 64, 'executionAllowed': False, 'capabilityCertified': False}

    async def rollback(_task, _job, state, _defaults, *, prior_results):
        assert state is StateName.PREPARE_ROLLBACK and prior_results == []
        events.append('original_rollback')
        # 有意保留原动作失败，不能用只读观察替代其完整能力证明。
        raise V1ExecutionError('UNKNOWN', '原回滚仍未完成', 'synthetic_original_rollback_blocked')

    monkeypatch.setattr(module, 'run_editor_control_inventory_observation', observe)
    monkeypatch.setattr(runner, '_run_workflow_action_async', rollback)
    return runner, repo, task, job, events


def test_actual_step_loop_sets_prepare_state_then_observes_then_calls_original_rollback(inventory_runner_case, monkeypatch, tmp_path):
    runner, repo, task, job, events = isolated_hook(inventory_runner_case, monkeypatch, tmp_path)
    assert asyncio.run(runner._run_job(task, job, 'batch_draft_save')) is False
    assert events == ['inventory', 'original_rollback']
    actual = repo.get_task_private(task['id'])['jobs'][0]
    assert actual['error_code'] == 'UNKNOWN' and 'synthetic_original_rollback_blocked' in actual['error_message']


def test_inventory_failure_stops_actual_loop_without_calling_original_rollback(inventory_runner_case, monkeypatch, tmp_path):
    runner, repo, task, job, events = isolated_hook(inventory_runner_case, monkeypatch, tmp_path, failed=True)
    assert asyncio.run(runner._run_job(task, job, 'batch_draft_save')) is False
    assert events == ['inventory']
    actual = repo.get_task_private(task['id'])['jobs'][0]
    assert actual['error_code'] == 'UNKNOWN' and 'synthetic_inventory_rejected' in actual['error_message']


@pytest.mark.parametrize('mode,path,replay', [('single_save', 'A', False), ('batch_draft_save', 'A', False),
    ('single_save', 'B', False), ('batch_draft_save', 'B', True)])
def test_historical_paths_and_closed_loop_do_not_gain_a_new_inventory_success(inventory_runner_case, monkeypatch, tmp_path, mode, path, replay):
    runner, repo, task, job, events = isolated_hook(inventory_runner_case, monkeypatch, tmp_path,
        mode=mode, path=path, replay=replay)
    assert asyncio.run(runner._run_job(task, job, mode)) is False
    assert events == ['original_rollback']
    assert repo.get_task_private(task['id'])['jobs'][0]['error_code'] == 'UNKNOWN'
