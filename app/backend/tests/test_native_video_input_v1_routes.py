"""实际 V1 入口复用只读来源链；不证明真实首写或生产能力已闭合。"""

import asyncio
from copy import deepcopy

import pytest

from src import db
from src.batch_edit.native_video_input_freeze import FREEZE_TYPE
from src.batch_edit.native_video_input_source import COMMAND_TYPE, SOURCE_TYPE
from src.batch_edit.scope_contract import canonical_sha256
from src.execution.v1_runner import BATCH_PATH_B_STEPS, PATH_B_SAVE1_DISCOVERY_STEPS, V1ExecutionError
from src.state_machine.contracts import StateName
from tests.support.native_video_input_source_case import NOW, count, isolated_first_fill, video_source_case


def _runner(case):
    runner = case['runner']
    runner.browser_agent_runtime = case['runtime']
    runner.workflow_action_timeout_seconds = 10
    return runner


def _first_reference(case):
    # 仅提供仓储引用选择样例；首写业务来源由显式隔离 fixture 单独替代。
    value = {'schema': 'dxm.path_b_editor_source.v1', 'task_id': case['task']['id'],
        'job_id': case['job']['id'], 'product_id': case['job']['product_id'],
        'command': {'state': 'FILL_BASE_INFO'}, 'created_at': NOW}
    value['source_sha256'] = canonical_sha256(value)
    case['repository'].add_evidence(case['task']['id'], case['job']['id'], 'path_b_editor_source', None, value)
    case['isolated_parent']['source_sha256'] = value['source_sha256']
    return value['source_sha256']


def _forbid_other_routes(runner, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail('SELECT 不得进入通用 spec 或历史执行路径')
    for name in ('_workflow_action_worker_request', '_run_workflow_action_process', '_run_workflow_action'):
        monkeypatch.setattr(runner, name, unexpected)


def _run(runner, case, route):
    args = (case['task'], case['job'], StateName.BATCH_VIDEO_SELECT, {'caller_override': 'ignored'})
    if route == 'sync':
        return runner._run_workflow_action_browser_agent(*args)
    return asyncio.run(runner._run_workflow_action_async(*args))


@pytest.mark.parametrize(('route', 'setting'), [('sync', 'process'), ('async', 'process'),
    ('async', 'thread'), ('async', 'browser_agent')])
def test_v1_select_uses_actual_worker_and_frozen_source_even_without_legacy_adapter(
    isolated_first_fill, monkeypatch, route, setting
):
    case = isolated_first_fill; runner = _runner(case)
    reference = _first_reference(case)
    _forbid_other_routes(runner, monkeypatch)
    monkeypatch.setenv('DXM_WORKFLOW_ACTION_RUNTIME', setting)
    before = deepcopy(case['repository'].get_task_private(case['task']['id']))
    assert runner.workflow_adapter is None
    result = _run(runner, case, route)
    command = result['browser_agent_command']
    assert result['ok'] is True and result['workflow_runtime'] == 'browser_agent'
    assert command['action'] == 'observe_native_video_inputs' and command['expected_page'] == 'editor'
    assert command['params']['first_fill_source_sha256'] == reference
    assert 'caller_override' not in command['params']['defaults']
    freeze = case['repository'].require_native_video_input_freeze(case['task']['id'], case['job']['id'],
        freeze_sha256=result['native_video_input_freeze_sha256'])
    assert freeze['observation_source_sha256'] == result['native_video_input_source_sha256']
    assert freeze['write_authorization_created'] is False and freeze['live_recheck_required'] is True
    assert case['repository'].get_task_private(case['task']['id']) == before
    assert count(COMMAND_TYPE) == count(SOURCE_TYPE) == count(FREEZE_TYPE) == 1
    with db.connection() as conn:
        assert conn.execute('SELECT COUNT(*) AS n FROM mutation_dispatch_ledger').fetchone()['n'] == 0
    assert runner._expected_page_for_state(StateName.BATCH_VIDEO_SELECT, mode='batch_draft_save') == 'editor'
    assert all(StateName.BATCH_VIDEO_SELECT not in {step[0] for step in steps}
               for steps in (BATCH_PATH_B_STEPS, PATH_B_SAVE1_DISCOVERY_STEPS))
    if route == 'async':
        logs = case['repository'].list_logs(case['task']['id'])
        assert any(row['level'] == 'success' and row['context']['state'] == 'BATCH_VIDEO_SELECT' for row in logs)


@pytest.mark.parametrize(('route', 'setting'), [('sync', 'process'), ('async', 'process'),
    ('async', 'thread'), ('async', 'browser_agent')])
def test_v1_select_without_runtime_is_logged_unknown_before_any_source_reservation(
    isolated_first_fill, monkeypatch, caplog, route, setting
):
    case = isolated_first_fill; runner = _runner(case)
    _first_reference(case)
    runner.browser_agent_runtime = None
    _forbid_other_routes(runner, monkeypatch)
    monkeypatch.setenv('DXM_WORKFLOW_ACTION_RUNTIME', setting)
    with pytest.raises(V1ExecutionError) as failure:
        _run(runner, case, route)
    assert failure.value.error_code == 'UNKNOWN'
    assert 'VIDEO_INPUT_BROWSER_AGENT_REQUIRED' in failure.value.detail
    assert any(record.message == 'native_video_input_observation_failed' for record in caplog.records)
    assert not hasattr(case['flow'], 'observer_thread') and runner._active_browser_agent_commands == {}
    assert count(COMMAND_TYPE) == count(SOURCE_TYPE) == count(FREEZE_TYPE) == 0
    if route == 'async':
        logs = case['repository'].list_logs(case['task']['id'])
        assert any(row['level'] == 'error' and row['context']['error_code'] == 'UNKNOWN' for row in logs)


def test_v1_async_select_keeps_real_missing_first_fill_closed(video_source_case, monkeypatch):
    case = video_source_case; runner = _runner(case)
    _forbid_other_routes(runner, monkeypatch)
    with pytest.raises(V1ExecutionError) as failure:
        _run(runner, case, 'async')
    assert failure.value.error_code == 'UNKNOWN'
    assert 'VIDEO_INPUT_FIRST_FILL_SOURCE_REQUIRED' in failure.value.detail
    assert not hasattr(case['flow'], 'observer_thread')
    assert count(COMMAND_TYPE) == count(SOURCE_TYPE) == count(FREEZE_TYPE) == 0
