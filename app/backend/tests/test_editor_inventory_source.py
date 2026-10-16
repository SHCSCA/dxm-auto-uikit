"""原快照与实际 Worker 文件往返；诊断成功不证明生产填写或可恢复。"""

from copy import deepcopy
from pathlib import Path

import pytest

from src import db
from src.batch_edit import editor_inventory_source as source
from src.batch_edit.scope_contract import canonical_sha256
from tests.support.editor_inventory_source_case import inventory_source_case, persist, records, require_source


def protected_state():
    with db.connection() as conn:
        names = {'plan_snapshots', 'plan_snapshot_idempotency_keys', 'tasks', 'jobs', 'real_dxm_write_scopes',
            'mutation_dispatch_ledger', 'canonical_receipts'}
        names.update(row['name'] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%lease%'").fetchall())
        return {**{name: conn.execute('SELECT * FROM ' + name + ' ORDER BY rowid').fetchall() for name in sorted(names)},
            'rollback': conn.execute("SELECT * FROM job_evidences WHERE evidence_type LIKE 'path_b_rollback%' ORDER BY id").fetchall()}


def test_actual_worker_source_roundtrip_keeps_authority_and_snapshot_immutable(inventory_source_case):
    case = inventory_source_case; original = protected_state()
    reservation, result, record = persist(case)
    assert case['flow'].observer_thread.startswith('dxm-browser-agent')
    assert record['action_result'] == result and record['reservation_sha256'] == reservation['reservation_sha256']
    assert record['authorization_created'] is False
    assert require_source(case, record) == record
    assert protected_state() == original
    assert len(records(source.COMMAND_TYPE)) == len(records(source.SOURCE_TYPE)) == 1
    assert all(Path(record['artifacts'][kind]['path']).is_file() for kind in ('request', 'result'))
    assert result['after_values']['editor_control_inventory']['section_count'] == 11
    assert result['after_values']['editor_control_inventory']['required_fields_complete'] is False
    assert 'FULL_FILL_EXECUTION_SOURCE_NOT_BOUND' in record['observation']['after']['missing']


def test_missing_native_control_remains_persisted_diagnostic_without_authority(inventory_source_case):
    case = inventory_source_case
    case['flow']._page.missing_key = case['payload']['fields'][0]['field_key']
    _, result, record = persist(case)
    assert 'CONTROL_NATIVE_IDENTITY_MISSING' in record['observation']['after']['missing']
    assert result['ok'] is True and record['authorization_created'] is False
    assert require_source(case, record) == record


def test_control_schema_mismatch_is_diagnostic_and_cannot_create_a_rollback_receipt(inventory_source_case):
    case = inventory_source_case; original = protected_state()
    case['flow']._page.checkbox_key = 'title'
    _, _, record = persist(case)
    assert 'CONTROL_SCHEMA_TYPE_MISMATCH' in record['observation']['after']['missing']
    assert require_source(case, record)['authorization_created'] is False
    assert protected_state() == original


def test_unreserved_and_duplicate_operations_never_append_an_extra_source(inventory_source_case):
    case = inventory_source_case; repo = case['repository']; command = case['command'].to_payload()
    task, job = case['task']['id'], case['job']['id']
    result = case['runtime'].run(case['command'], timeout_seconds=10)
    with pytest.raises(ValueError, match='NOT_RESERVED'):
        repo.persist_editor_control_inventory(task, job, command, result)
    repo.reserve_editor_control_inventory(task, job, command)
    with pytest.raises(ValueError, match='ALREADY_RESERVED'):
        repo.reserve_editor_control_inventory(task, job, command)
    repo.persist_editor_control_inventory(task, job, command, result)
    with pytest.raises(ValueError, match='ALREADY_RECORDED'):
        repo.persist_editor_control_inventory(task, job, command, result)
    assert len(records(source.COMMAND_TYPE)) == len(records(source.SOURCE_TYPE)) == 1


@pytest.mark.parametrize('kind', ['request', 'result', 'screenshot'])
def test_reread_refuses_changed_original_worker_files_or_screenshot(inventory_source_case, kind):
    case = inventory_source_case; _, _, record = persist(case)
    path = record['observation']['observation']['evidence_ref']['path'] if kind == 'screenshot' else record['artifacts'][kind]['path']
    Path(path).write_bytes(b'changed synthetic evidence')
    with pytest.raises(ValueError):
        require_source(case, record)
    assert len(records(source.SOURCE_TYPE)) == 1


def test_failed_post_insert_transaction_rolls_back_only_new_source(inventory_source_case, monkeypatch):
    case = inventory_source_case; repo = case['repository']; task, job = case['task']['id'], case['job']['id']
    command = case['command'].to_payload(); actual = source.persist_inventory
    repo.reserve_editor_control_inventory(task, job, command)
    result = case['runtime'].run(case['command'], timeout_seconds=10)
    original = protected_state()

    def fail(*args, **kwargs):
        actual(*args, **kwargs)
        raise RuntimeError('synthetic source transaction failure')

    monkeypatch.setattr(source, 'persist_inventory', fail)
    with pytest.raises(RuntimeError, match='transaction failure'):
        repo.persist_editor_control_inventory(task, job, command, result)
    assert not records(source.SOURCE_TYPE) and len(records(source.COMMAND_TYPE)) == 1
    assert protected_state() == original
