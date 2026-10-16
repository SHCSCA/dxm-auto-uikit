"""数据库身份、原 Schema、证据时序漂移均拒绝，不追加任何授权事实。"""

from copy import deepcopy
from dataclasses import replace

import pytest

from src import db
from src.batch_edit import editor_inventory_source as source
from src.batch_edit.scope_contract import canonical_sha256
from tests.support.editor_inventory_source_case import inventory_source_case, persist, records, require_source


@pytest.mark.parametrize('change', ['extra_schema_metadata', 'ui_section', 'required', 'schema_hash', 'extra_param', 'wrong_shop'])
def test_reservation_requires_the_entire_original_db_schema_and_exact_params(inventory_source_case, change):
    case = inventory_source_case; command = case['command'].to_payload()
    category = command['params']['category_schema']
    if change == 'extra_schema_metadata':
        category['caller_metadata'] = 'unreviewed'
    elif change == 'ui_section':
        category['normalized_schema']['properties']['title']['ui_section'] = 'other_info'
    elif change == 'required':
        category['normalized_schema']['required'] = []
    elif change == 'schema_hash':
        category['schema_hash'] = 'A'*64
    elif change == 'extra_param':
        command['params']['live_schema'] = deepcopy(category)
    else:
        command['params']['shop_id'] = '999'
    with pytest.raises(ValueError):
        case['repository'].reserve_editor_control_inventory(case['task']['id'], case['job']['id'], command)
    assert not records(source.COMMAND_TYPE) and not records(source.SOURCE_TYPE)


@pytest.mark.parametrize('change', ['step', 'status', 'scope', 'approval', 'queue', 'completed_count', 'snapshot', 'provenance', 'session'])
def test_current_authority_drift_rejects_an_existing_source(inventory_source_case, change):
    case = inventory_source_case; _, _, record = persist(case)
    with db.connection() as conn:
        if change == 'step':
            conn.execute("UPDATE jobs SET current_step_code='FILL_BASE_INFO' WHERE id=?", (case['job']['id'],))
        elif change == 'status':
            conn.execute("UPDATE tasks SET status='paused' WHERE id=?", (case['task']['id'],))
        elif change == 'scope':
            conn.execute("UPDATE real_dxm_write_scopes SET status='unknown'")
        elif change == 'approval':
            payload = deepcopy(case['task']['payload']); payload['manual_approval']['consumed'] = False
            conn.execute('UPDATE tasks SET payload_json=? WHERE id=?', (db.dumps(payload), case['task']['id']))
        elif change == 'queue':
            conn.execute("UPDATE jobs SET status='running' WHERE id=?", (case['task']['jobs'][1]['id'],))
        elif change == 'completed_count':
            conn.execute('UPDATE tasks SET completed_jobs=1 WHERE id=?', (case['task']['id'],))
        elif change == 'snapshot':
            conn.execute("UPDATE plan_snapshots SET snapshot_hash='changed'")
        elif change == 'provenance':
            conn.execute('DELETE FROM plan_snapshot_idempotency_keys')
        else:
            row = conn.execute('SELECT scope_json FROM real_dxm_write_scopes').fetchone()
            scope = db.loads(row['scope_json'], {}); scope['runtime']['browserSessionId'] = 'changed-session'
            conn.execute('UPDATE real_dxm_write_scopes SET scope_json=?', (db.dumps(scope),))
    with pytest.raises(ValueError):
        require_source(case, record)
    assert len(records(source.SOURCE_TYPE)) == 1


@pytest.mark.parametrize('kind', ['reservation_time', 'source_time', 'source_observation', 'reservation_command', 'duplicate'])
def test_rehashed_stored_evidence_still_requires_original_reservation_files_and_time(inventory_source_case, kind):
    case = inventory_source_case; _, _, record = persist(case)
    evidence_type = source.COMMAND_TYPE if kind.startswith('reservation') else source.SOURCE_TYPE
    digest_key = 'reservation_sha256' if evidence_type == source.COMMAND_TYPE else 'source_sha256'
    with db.connection() as conn:
        row = conn.execute('SELECT * FROM job_evidences WHERE evidence_type=?', (evidence_type,)).fetchone()
        value = db.loads(row['meta_json'], {})
        if kind == 'duplicate':
            conn.execute('INSERT INTO job_evidences(task_id,job_id,evidence_type,file_path,meta_json,created_at) VALUES(?,?,?,?,?,?)',
                tuple(row[key] for key in ('task_id', 'job_id', 'evidence_type', 'file_path', 'meta_json', 'created_at')))
        else:
            if kind == 'reservation_time':
                value['reserved_at'] = '2026-08-31T00:02:00Z'
            elif kind == 'source_time':
                value['created_at'] = '2026-08-31T00:00:01Z'
            elif kind == 'source_observation':
                value['observation']['after']['required_fields_complete'] = True
            else:
                value['command']['command_id'] = 'd'*32
            value[digest_key] = canonical_sha256({key: item for key, item in value.items() if key != digest_key})
            if evidence_type == source.SOURCE_TYPE:
                record['source_sha256'] = value[digest_key]
            conn.execute('UPDATE job_evidences SET meta_json=?,created_at=? WHERE id=?',
                (db.dumps(value), value.get('created_at', value.get('reserved_at')), row['id']))
    with pytest.raises(ValueError):
        require_source(case, record)


def test_other_worker_session_cannot_be_persisted_under_the_original_scope(inventory_source_case):
    case = inventory_source_case; repo = case['repository']; command = case['command'].to_payload()
    repo.reserve_editor_control_inventory(case['task']['id'], case['job']['id'], command)
    case['flow'].session = 'another-synthetic-session'
    result = case['runtime'].run(case['command'], timeout_seconds=10)
    with pytest.raises(ValueError):
        repo.persist_editor_control_inventory(case['task']['id'], case['job']['id'], command, result)
    assert not records(source.SOURCE_TYPE)


def test_expired_read_command_never_reserves(inventory_source_case):
    case = inventory_source_case
    command = replace(case['command'], deadline='2026-08-31T00:00:00Z')
    with pytest.raises(ValueError):
        case['repository'].reserve_editor_control_inventory(case['task']['id'], case['job']['id'], command.to_payload())
    assert not records(source.COMMAND_TYPE)
