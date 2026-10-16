"""持久观察层正例显式隔离尚未成立的生产前序，不证明完整 FILL/视频链。"""

from copy import deepcopy
from pathlib import Path

import pytest

from src import db
from src.batch_edit import content_observation_source as source
from src.batch_edit.content_finalize_store import _candidate_sources, append_content_finalize_stage
from src.batch_edit.frozen_execution_contract import FrozenExecutionContractError, compile_frozen_execution_payload
from src.batch_edit.scope_contract import canonical_sha256
from tests.test_content_observation_flow import observation_case


@pytest.fixture
def isolated_reviewed_predecessor_provider(observation_case, monkeypatch):
    # 只隔离前序提供器；真实前序尚无成功 FILL 合同，不以此正例宣称生产全链通过。
    parent = {'source_sha256': 'D'*64, 'created_at': '2026-08-31T00:01:00Z'}
    monkeypatch.setattr(source, '_translation', lambda *args, **kwargs: deepcopy(parent))
    return {**observation_case, 'isolated_parent': parent}


def persisted(case):
    repo, task, job, command = case['repository'], case['task'], case['job'], case['command']
    reservation = repo.reserve_content_observation(task['id'], job['id'], command.to_payload())
    result = case['runtime'].run(command, timeout_seconds=10)
    record = repo.persist_content_observation(task['id'], job['id'], command.to_payload(), result)
    return reservation, result, record


def evidence_count(kind):
    with db.connection() as conn:
        return conn.execute('SELECT COUNT(*) AS n FROM job_evidences WHERE evidence_type=?', (kind,)).fetchone()['n']


def test_isolated_observation_layer_reserves_then_reloads_real_worker_files_before_append(isolated_reviewed_predecessor_provider):
    case = isolated_reviewed_predecessor_provider
    reservation, result, record = persisted(case)
    assert reservation['command'] == case['command'].to_payload()
    assert record['action_result'] == result
    assert record['observation']['values'] == case['flow']._page.values
    assert record['translation_source_sha256'] == case['isolated_parent']['source_sha256']
    original = {key: Path(record['artifacts'][key]['path']).read_bytes() for key in ('request', 'result')}
    assert case['repository'].require_content_observation(case['task']['id'], case['job']['id'], source_sha256=record['source_sha256']) == record
    assert {key: Path(record['artifacts'][key]['path']).read_bytes() for key in original} == original
    assert evidence_count(source.COMMAND_TYPE) == evidence_count(source.SOURCE_TYPE) == 1
    assert evidence_count('path_b_content_finalize_freeze') == 0
    with db.connection() as conn:
        assert conn.execute('SELECT COUNT(*) AS n FROM mutation_dispatch_ledger').fetchone()['n'] == 0


@pytest.mark.parametrize('tamper', ['request', 'result', 'screenshot', 'source', 'reservation', 'parent_time'])
def test_persisted_observation_reloads_files_and_rejects_resigned_or_external_drift(isolated_reviewed_predecessor_provider, tamper):
    case = isolated_reviewed_predecessor_provider
    _, _, record = persisted(case)
    if tamper in ('request', 'result'):
        Path(record['artifacts'][tamper]['path']).write_text('{}', encoding='utf-8')
    elif tamper == 'screenshot':
        Path(record['observation']['evidence_ref']['path']).write_bytes(b'tampered')
    elif tamper == 'parent_time':
        case['isolated_parent']['created_at'] = '2026-08-31T00:01:01Z'
    else:
        kind = source.SOURCE_TYPE if tamper == 'source' else source.COMMAND_TYPE
        with db.connection() as conn:
            row = conn.execute('SELECT id,meta_json FROM job_evidences WHERE evidence_type=?', (kind,)).fetchone()
            value = db.loads(row['meta_json'], {})
            if tamper == 'source':
                value['observation']['values']['title'] = 'Caller replacement'
                value['source_sha256'] = canonical_sha256({key: item for key, item in value.items() if key != 'source_sha256'})
                record['source_sha256'] = value['source_sha256']
            else:
                value['reserved_at'] = '2026-08-31T00:02:00Z'
                value['reservation_sha256'] = canonical_sha256({key: item for key, item in value.items() if key != 'reservation_sha256'})
            conn.execute('UPDATE job_evidences SET meta_json=? WHERE id=?', (db.dumps(value), row['id']))
    with pytest.raises(ValueError):
        case['repository'].require_content_observation(case['task']['id'], case['job']['id'], source_sha256=record['source_sha256'])
    assert evidence_count(source.SOURCE_TYPE) == 1


def test_missing_actual_predecessor_rejects_before_command_reservation_and_rolls_back(observation_case):
    case = observation_case
    with pytest.raises(FrozenExecutionContractError) as failure:
        case['repository'].reserve_content_observation(case['task']['id'], case['job']['id'], case['command'].to_payload())
    assert failure.value.reason_code == 'CONTENT_FINALIZE_SOURCE_MISSING'
    assert evidence_count(source.COMMAND_TYPE) == evidence_count(source.SOURCE_TYPE) == 0


@pytest.mark.parametrize('tamper', ['wrong_task', 'hash'])
def test_real_predecessor_validator_rejects_wrong_or_tampered_source_without_reserving(observation_case, tamper):
    case = observation_case
    value = {'schema': 'dxm.path_b_editor_source.v1', 'task_id': case['task']['id'], 'job_id': case['job']['id'],
        'command': {}, 'action_result': {}, 'created_at': '2026-08-31T00:01:00Z'}
    value['source_sha256'] = canonical_sha256(value)
    if tamper == 'wrong_task':
        value['task_id'] += 1
        value['source_sha256'] = canonical_sha256({key: item for key, item in value.items() if key != 'source_sha256'})
    else:
        value['created_at'] = 'tampered'
    with db.connection() as conn:
        conn.execute('INSERT INTO job_evidences(task_id,job_id,evidence_type,meta_json,created_at) VALUES(?,?,?,?,?)',
            (case['task']['id'], case['job']['id'], 'path_b_editor_source', db.dumps(value), value['created_at']))
    with pytest.raises(ValueError):
        case['repository'].reserve_content_observation(case['task']['id'], case['job']['id'], case['command'].to_payload())
    assert evidence_count(source.COMMAND_TYPE) == evidence_count(source.SOURCE_TYPE) == 0


def test_unreserved_result_and_changed_job_cannot_append_observation(isolated_reviewed_predecessor_provider):
    case = isolated_reviewed_predecessor_provider
    result = case['runtime'].run(case['command'], timeout_seconds=10)
    with pytest.raises(ValueError, match='CONTENT_OBSERVATION_COMMAND_NOT_RESERVED'):
        case['repository'].persist_content_observation(case['task']['id'], case['job']['id'], case['command'].to_payload(), result)
    case['repository'].reserve_content_observation(case['task']['id'], case['job']['id'], case['command'].to_payload())
    case['repository'].update_job(case['job']['id'], current_step_code='FIRST_SAVE_INTENT')
    with pytest.raises(ValueError, match='SOURCE_STATE_INVALID'):
        case['repository'].persist_content_observation(case['task']['id'], case['job']['id'], case['command'].to_payload(), result)
    assert evidence_count(source.SOURCE_TYPE) == 0


def test_repository_transaction_rolls_back_even_if_insert_succeeds_then_producer_raises(isolated_reviewed_predecessor_provider, monkeypatch):
    case = isolated_reviewed_predecessor_provider
    actual = source.persist_observation
    case['repository'].reserve_content_observation(case['task']['id'], case['job']['id'], case['command'].to_payload())
    result = case['runtime'].run(case['command'], timeout_seconds=10)
    def rejected_after_insert(*args, **kwargs):
        actual(*args, **kwargs)
        raise RuntimeError('isolated post-insert fault')
    monkeypatch.setattr(source, 'persist_observation', rejected_after_insert)
    with pytest.raises(RuntimeError, match='post-insert fault'):
        case['repository'].persist_content_observation(case['task']['id'], case['job']['id'], case['command'].to_payload(), result)
    assert evidence_count(source.SOURCE_TYPE) == 0
    assert evidence_count(source.COMMAND_TYPE) == 1


def test_caller_map_is_never_an_authoritative_observation(observation_case):
    case = observation_case
    with db.connection() as conn, pytest.raises(FrozenExecutionContractError) as failure:
        _candidate_sources(conn, task=case['task'], job=case['job'], observation={'values': {'title': 'caller'}},
            observation_source_sha256='D'*64, receipts={}, screenshot_root=case['screenshots'])
    assert failure.value.reason_code == 'CONTENT_FINALIZE_OBSERVATION_SOURCE_REQUIRED'
    with pytest.raises(FrozenExecutionContractError) as failure:
        compile_frozen_execution_payload(case['task'], case['job'], for_save=True)
    assert failure.value.reason_code == 'CONTENT_FINALIZE_STAGE_NOT_FROZEN'


def test_finalize_insert_uses_verified_candidate_path_when_caller_observation_is_none(observation_case, monkeypatch):
    from src.batch_edit import content_finalize_store
    case = observation_case
    candidate = {'observation': {'evidence_ref': {'path': 'isolated_verified_source.png'}}}
    # 仅验证不可达封存分支的参数接线，不授予该隔离候选任何生产权威。
    monkeypatch.setattr(content_finalize_store, '_candidate_sources', lambda *args, **kwargs: (candidate, []))
    with db.connection() as conn:
        record = append_content_finalize_stage(conn, task=case['task'], job=case['job'], observation=None,
            observation_source_sha256='D'*64, receipts={}, screenshot_root=case['screenshots'], now='2026-08-31T00:01:00Z')
        row = conn.execute("SELECT file_path FROM job_evidences WHERE evidence_type='path_b_content_finalize_freeze'").fetchone()
        assert row['file_path'] == candidate['observation']['evidence_ref']['path']
        assert record['observation_source_sha256'] == 'D'*64
