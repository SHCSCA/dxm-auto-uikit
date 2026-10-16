"""构造与派发前各自复验持久来源；通过消费也不能生成或证明视频成功。"""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from src import db, repository as repository_module
from src.batch_edit.native_video_input_freeze import FREEZE_TYPE
from src.core.config_bus import configuration_scope
from src.execution.browser_action_dispatch import execute_browser_agent_action
from src.execution.v1_runner import V1ExecutionError
from tests.support.native_video_generation_binding_case import (
    build_submit, configure_main, generation_input_case, isolated_first_fill, ledger_count, video_source_case,
)


def test_builder_selects_only_the_persisted_freeze_and_preserves_original_approval(generation_input_case):
    case = generation_input_case
    before = deepcopy(case['repository'].get_task_private(case['task']['id'])['payload'])
    command = build_submit(case)
    assert command.params['native_video_input_freeze_sha256'] == case['input_freeze']['freeze_sha256']
    assert case['repository'].require_native_video_input_freeze(case['task']['id'], case['job']['id'],
        freeze_sha256=command.params['native_video_input_freeze_sha256'], generation_command=command.to_payload()) == case['input_freeze']
    assert case['repository'].get_task_private(case['task']['id'])['payload'] == before
    assert ledger_count() == 0
    with pytest.raises(ValueError, match='Unsupported Browser Agent action'):
        execute_browser_agent_action(case['runtime'].adapter, command.action, command.params)


def test_builder_refuses_missing_freeze_before_any_worker_or_ledger(video_source_case):
    with pytest.raises(V1ExecutionError) as failure:
        build_submit(video_source_case)
    assert failure.value.error_code == 'UNKNOWN' and ledger_count() == 0
    assert not hasattr(video_source_case['flow'], 'observer_thread')


@pytest.mark.parametrize('params', [
    {'native_video_input_freeze_sha256': 'F'*64},
    {'native_video_input_freeze_sha256': {'freeze_sha256': 'F'*64}},
    {'native_video_inputs': {'transition': 0}}, {'inputs': {'images': []}},
    {'observation': {'write_attempted': False}},
])
def test_caller_reference_or_value_maps_never_supply_generation_inputs(generation_input_case, params):
    with pytest.raises(V1ExecutionError) as failure:
        build_submit(generation_input_case, params=params)
    assert failure.value.error_code == 'UNKNOWN' and ledger_count() == 0


def test_full_transaction_rejects_duplicate_freeze_hidden_beyond_public_history_limit(generation_input_case):
    case = generation_input_case; repo = case['repository']
    repo.add_evidence(case['task']['id'], case['job']['id'], FREEZE_TYPE, None, case['input_freeze'])
    with db.connection() as conn:
        conn.executemany('INSERT INTO job_evidences(task_id,job_id,evidence_type,meta_json,created_at) VALUES(?,?,?,?,?)',
            [(case['task']['id'], case['job']['id'], 'synthetic_history', '{}', '2026-08-31T00:01:00Z')]*201)
    assert all(row['evidence_type'] != FREEZE_TYPE for row in repo.list_evidences(case['task']['id']))
    with pytest.raises(V1ExecutionError) as failure:
        build_submit(case)
    assert failure.value.error_code == 'UNKNOWN' and ledger_count() == 0


def test_select_step_cannot_consume_inputs_as_a_generation_command(generation_input_case):
    with pytest.raises(V1ExecutionError) as failure:
        build_submit(generation_input_case, step='BATCH_VIDEO_SELECT')
    assert failure.value.error_code == 'UNKNOWN' and ledger_count() == 0


def test_another_jobs_freeze_cannot_supply_the_current_command(generation_input_case):
    case = generation_input_case
    with db.connection() as conn:
        conn.execute('UPDATE job_evidences SET job_id=? WHERE evidence_type=?',
            (case['task']['jobs'][1]['id'], FREEZE_TYPE))
    with pytest.raises(V1ExecutionError) as failure:
        build_submit(case)
    assert failure.value.error_code == 'UNKNOWN' and ledger_count() == 0


def test_actual_main_jit_revalidates_the_consumed_parent_and_worker_sources(generation_input_case, monkeypatch):
    case = generation_input_case; command = build_submit(case)
    main = configure_main(case, monkeypatch)
    assert main._authorize_browser_mutation(command, {'mutation_action': 'video_generate_click'}) == {
        'ok': True, 'reason_code': 'OK'}
    assert ledger_count() == 0


@pytest.mark.parametrize('change', ['result', 'screenshot', 'reference', 'duplicate', 'age'])
def test_main_jit_rechecks_changes_after_command_construction(generation_input_case, monkeypatch, caplog, change):
    case = generation_input_case; command = build_submit(case)
    main = configure_main(case, monkeypatch)
    if change in {'result', 'screenshot'}:
        path = (case['input_source']['artifacts']['result']['path'] if change == 'result'
            else case['input_source']['observation']['observation']['evidence_ref']['path'])
        Path(path).write_bytes(b'changed after construction')
    elif change == 'reference':
        command = replace(command, params={**command.params, 'native_video_input_freeze_sha256': 'F'*64})
    elif change == 'duplicate':
        case['repository'].add_evidence(case['task']['id'], case['job']['id'], FREEZE_TYPE, None, case['input_freeze'])
    else:
        monkeypatch.setattr(repository_module, 'now_iso', lambda: '2026-08-31T00:01:02Z')
    with configuration_scope({'DXM_NATIVE_VIDEO_INPUT_MAX_AGE_SECONDS': '1'}):
        decision = main._authorize_browser_mutation(command, {'mutation_action': 'video_generate_click'})
    assert decision == {'ok': False, 'reason_code': 'AUTH_VIDEO_INPUT_FREEZE_UNPROVEN'}
    assert ledger_count() == 0
    assert any(record.message == 'native_video_generation_input_jit_rejected' for record in caplog.records)


@pytest.mark.parametrize('change', ['scope', 'step'])
def test_main_jit_keeps_current_scope_and_queue_guards_after_binding(generation_input_case, monkeypatch, change):
    case = generation_input_case; command = build_submit(case)
    main = configure_main(case, monkeypatch)
    if change == 'scope':
        with db.connection() as conn:
            conn.execute("UPDATE real_dxm_write_scopes SET status='prepared'")
    else:
        case['repository'].update_job(case['job']['id'], current_step_code='BATCH_VIDEO_PLACE')
    assert main._authorize_browser_mutation(command, {'mutation_action': 'video_generate_click'})['ok'] is False
    assert ledger_count() == 0
