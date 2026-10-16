"""既有 Runner 的薄入口只追加可信引用，不修改步骤或自动重试。"""

from copy import deepcopy

import pytest

from src import db
from src.batch_edit.native_video_input_source import COMMAND_TYPE, SOURCE_TYPE
from src.batch_edit.native_video_input_freeze import FREEZE_TYPE
from src.batch_edit.scope_contract import canonical_sha256
from src.execution.native_video_input_runner import run_native_video_input_observation
from src.execution.v1_runner import V1ExecutionError
from tests.support.native_video_input_source_case import NOW, count, isolated_first_fill, video_source_case


def ready_runner(case):
    runner = case['runner']; runner.browser_agent_runtime = case['runtime']
    runner.workflow_action_timeout_seconds = 10
    return runner


def test_existing_runner_drives_actual_worker_files_and_freeze_without_advancing_queue(isolated_first_fill):
    case = isolated_first_fill; runner = ready_runner(case)
    before = deepcopy(case['repository'].get_task_private(case['task']['id']))
    # 此记录仅验证默认仓储引用选择；首写业务证明仍由显式隔离的提供器替代。
    first = {'schema': 'dxm.path_b_editor_source.v1', 'task_id': case['task']['id'], 'job_id': case['job']['id'],
        'product_id': case['job']['product_id'], 'command': {'state': 'FILL_BASE_INFO'}, 'created_at': NOW}
    first['source_sha256'] = canonical_sha256(first)
    case['repository'].add_evidence(case['task']['id'], case['job']['id'], 'path_b_editor_source', None, first)
    case['isolated_parent']['source_sha256'] = first['source_sha256']
    result = run_native_video_input_observation(runner, task=case['task'], job=case['job'])
    assert result['ok'] is True and result['action'] == 'observe_native_video_inputs'
    assert result['browser_agent_command']['state'] == 'BATCH_VIDEO_SELECT'
    assert result['browser_agent_command']['params']['first_fill_source_sha256'] == first['source_sha256']
    record = case['repository'].require_native_video_input_freeze(case['task']['id'], case['job']['id'],
        freeze_sha256=result['native_video_input_freeze_sha256'])
    assert record['observation_source_sha256'] == result['native_video_input_source_sha256']
    assert record['write_authorization_created'] is False and record['live_recheck_required'] is True
    assert case['repository'].get_task_private(case['task']['id']) == before
    assert runner._active_browser_agent_commands == {}
    assert count(COMMAND_TYPE) == count(SOURCE_TYPE) == count(FREEZE_TYPE) == 1
    with db.connection() as conn:
        assert conn.execute('SELECT COUNT(*) AS n FROM mutation_dispatch_ledger').fetchone()['n'] == 0


@pytest.mark.parametrize('reference', [None, {'source_sha256': 'D'*64}])
def test_missing_persisted_reference_or_caller_map_cannot_start_worker(video_source_case, reference):
    case = video_source_case; runner = ready_runner(case)
    with pytest.raises(V1ExecutionError) as failure:
        run_native_video_input_observation(runner, task=case['task'], job=case['job'], first_fill_source_sha256=reference)
    assert failure.value.error_code == 'UNKNOWN'
    assert not hasattr(case['flow'], 'observer_thread') and runner._active_browser_agent_commands == {}
    assert count(COMMAND_TYPE) == count(SOURCE_TYPE) == count(FREEZE_TYPE) == 0


def test_failed_freeze_stops_once_and_leaves_existing_worker_source_for_review(isolated_first_fill, monkeypatch):
    case = isolated_first_fill; runner = ready_runner(case); attempts = []
    def rejected(*args, **kwargs):
        attempts.append('freeze')
        raise ValueError('isolated freeze failure')
    monkeypatch.setattr(case['repository'], 'persist_native_video_input_freeze', rejected)
    with pytest.raises(V1ExecutionError) as failure:
        run_native_video_input_observation(runner, task=case['task'], job=case['job'],
            first_fill_source_sha256=case['isolated_parent']['source_sha256'])
    assert failure.value.error_code == 'UNKNOWN' and attempts == ['freeze']
    assert count(COMMAND_TYPE) == count(SOURCE_TYPE) == 1 and count(FREEZE_TYPE) == 0
    assert runner._active_browser_agent_commands == {}
