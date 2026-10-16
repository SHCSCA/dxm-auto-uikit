"""局部来源链使用真实 Worker 文件；隔离首写前序不代表生产全链通过。"""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from src import db
from src.batch_edit import native_video_input_source as source
from src.batch_edit.scope_contract import canonical_sha256
from src.execution.browser_agent_protocol import validate_browser_agent_command
from tests.support.native_video_input_source_case import (
    count, isolated_first_fill, persist, rewrite, video_source_case,
)


def require_source(case, record):
    return case['repository'].require_native_video_inputs(case['task']['id'], case['job']['id'],
        source_sha256=record['source_sha256'])


def test_real_first_fill_predecessor_is_required_before_reservation(video_source_case):
    case = video_source_case
    with pytest.raises(ValueError, match='VIDEO_INPUT_FIRST_FILL_SOURCE_REQUIRED'):
        case['repository'].reserve_native_video_inputs(case['task']['id'], case['job']['id'], case['command'].to_payload())
    assert count(source.COMMAND_TYPE) == count(source.SOURCE_TYPE) == 0


def test_isolated_source_layer_uses_real_worker_files_and_keeps_snapshot_immutable(isolated_first_fill):
    case = isolated_first_fill; original = deepcopy(case['task']['payload']['plan_snapshot'])
    reservation, result, record = persist(case)
    assert reservation['command'] == case['command'].to_payload()
    assert result == record['action_result'] and record['observation']['observation']['inputs']['images']
    assert record['first_fill_source_sha256'] == case['isolated_parent']['source_sha256']
    assert case['flow'].observer_thread.startswith('dxm-browser-agent')
    originals = {key: Path(record['artifacts'][key]['path']).read_bytes() for key in ('request', 'result')}
    assert require_source(case, record) == record
    assert {key: Path(record['artifacts'][key]['path']).read_bytes() for key in originals} == originals
    assert case['repository'].get_task_private(case['task']['id'])['payload']['plan_snapshot'] == original
    assert count(source.COMMAND_TYPE) == count(source.SOURCE_TYPE) == 1
    with db.connection() as conn:
        assert conn.execute('SELECT COUNT(*) AS n FROM mutation_dispatch_ledger').fetchone()['n'] == 0
        assert conn.execute('SELECT COUNT(*) AS n FROM canonical_receipts').fetchone()['n'] == 0


def test_unreserved_result_and_duplicate_operations_cannot_append(isolated_first_fill):
    case = isolated_first_fill; repo = case['repository']; task, job, command = case['task']['id'], case['job']['id'], case['command'].to_payload()
    result = case['runtime'].run(case['command'], timeout_seconds=10)
    with pytest.raises(ValueError, match='COMMAND_NOT_RESERVED'):
        repo.persist_native_video_inputs(task, job, command, result)
    repo.reserve_native_video_inputs(task, job, command)
    with pytest.raises(ValueError, match='ALREADY_RESERVED'):
        repo.reserve_native_video_inputs(task, job, command)
    repo.persist_native_video_inputs(task, job, command, result)
    with pytest.raises(ValueError, match='ALREADY_RECORDED'):
        repo.persist_native_video_inputs(task, job, command, result)
    assert count(source.COMMAND_TYPE) == count(source.SOURCE_TYPE) == 1


@pytest.mark.parametrize('tamper', ['request', 'result', 'screenshot', 'source_map', 'source_time', 'reservation_time', 'parent_time'])
def test_persisted_source_rechecks_files_screenshot_reserved_time_and_predecessor(isolated_first_fill, tamper):
    case = isolated_first_fill; _, _, record = persist(case)
    if tamper in {'request', 'result'}:
        Path(record['artifacts'][tamper]['path']).write_text('{}', encoding='utf-8')
    elif tamper == 'screenshot':
        Path(record['observation']['observation']['evidence_ref']['path']).write_bytes(b'changed')
    elif tamper == 'parent_time':
        case['isolated_parent']['created_at'] = '2026-08-31T00:01:01Z'
    else:
        kind = source.COMMAND_TYPE if tamper == 'reservation_time' else source.SOURCE_TYPE
        def change(value):
            if tamper == 'source_map':
                value['observation']['observation']['inputs']['transition'] = 2
            else:
                value['reserved_at' if tamper == 'reservation_time' else 'created_at'] = '2026-08-31T00:02:00Z'
            digest_key = 'reservation_sha256' if kind == source.COMMAND_TYPE else 'source_sha256'
            value[digest_key] = canonical_sha256({key: item for key, item in value.items() if key != digest_key})
            if kind == source.SOURCE_TYPE:
                record['source_sha256'] = value[digest_key]
        rewrite(kind, change)
    with pytest.raises(ValueError):
        require_source(case, record)
    assert count(source.SOURCE_TYPE) == 1


@pytest.mark.parametrize('change', ['step', 'task_status', 'scope', 'approval', 'queue', 'snapshot'])
def test_current_authority_drift_rejects_persisted_source(isolated_first_fill, change):
    case = isolated_first_fill; _, _, record = persist(case)
    with db.connection() as conn:
        if change == 'step':
            conn.execute("UPDATE jobs SET current_step_code='FIRST_SAVE_INTENT' WHERE id=?", (case['job']['id'],))
        elif change == 'task_status':
            conn.execute("UPDATE tasks SET status='paused' WHERE id=?", (case['task']['id'],))
        elif change == 'scope':
            conn.execute("UPDATE real_dxm_write_scopes SET status='unknown'")
        elif change == 'approval':
            payload = deepcopy(case['task']['payload']); payload['manual_approval']['approved'] = False
            conn.execute('UPDATE tasks SET payload_json=? WHERE id=?', (db.dumps(payload), case['task']['id']))
        elif change == 'queue':
            conn.execute("UPDATE jobs SET status='running' WHERE id=?", (case['task']['jobs'][1]['id'],))
        else:
            conn.execute("UPDATE plan_snapshots SET snapshot_hash='changed'")
    with pytest.raises(ValueError):
        require_source(case, record)


@pytest.mark.parametrize('changes', [{'state': 'BATCH_VIDEO_SUBMIT'}, {'action': 'submit_editor_video'},
    {'authorization_lease_id': 'caller'}, {'execution_payload_hash': 'A'*64},
    {'params': {'defaults': {}}}])
def test_readonly_command_cannot_carry_dispatch_authority_or_change_action(video_source_case, changes):
    with pytest.raises(ValueError):
        validate_browser_agent_command(replace(video_source_case['command'], **changes))


def test_worker_refuses_mutation_callback_before_authorizer_or_operation(video_source_case):
    called = []; command = video_source_case['command']
    decision = video_source_case['runtime']._authorize_mutation(SimpleNamespace(), command,
        {'mutation_action': 'video_generate_click'}, lambda: called.append('operation'))
    assert decision['executed'] is False and called == []
    with db.connection() as conn:
        assert conn.execute('SELECT COUNT(*) AS n FROM mutation_dispatch_ledger').fetchone()['n'] == 0


def test_failed_post_insert_transaction_does_not_leave_a_source(isolated_first_fill, monkeypatch):
    case = isolated_first_fill; repo = case['repository']; actual = source.persist_inputs
    repo.reserve_native_video_inputs(case['task']['id'], case['job']['id'], case['command'].to_payload())
    result = case['runtime'].run(case['command'], timeout_seconds=10)
    def rejected(*args, **kwargs):
        actual(*args, **kwargs)
        raise RuntimeError('isolated failure after source insertion')
    monkeypatch.setattr(source, 'persist_inputs', rejected)
    with pytest.raises(RuntimeError, match='after source insertion'):
        repo.persist_native_video_inputs(case['task']['id'], case['job']['id'], case['command'].to_payload(), result)
    assert count(source.SOURCE_TYPE) == 0 and count(source.COMMAND_TYPE) == 1
