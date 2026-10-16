"""追加输入冻结必须复验真实来源；数据库消费仍不等于活页面或点击授权。"""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from src import db, repository as repository_module
from src.batch_edit import native_video_input_freeze as subject
from src.batch_edit.frozen_execution_contract import FrozenExecutionContractError, compile_frozen_execution_payload
from src.batch_edit.native_video_input_source import SOURCE_TYPE
from src.batch_edit.scope_contract import canonical_sha256
from src.core.config_bus import ConfigurationError, configuration_scope
from tests.support.native_video_input_source_case import (
    count, freeze, generation, isolated_first_fill, rewrite, video_source_case,
)


def require_freeze(case, record, command=None):
    return case['repository'].require_native_video_input_freeze(case['task']['id'], case['job']['id'],
        freeze_sha256=record['freeze_sha256'], generation_command=command.to_payload() if command else None)


def test_isolated_source_layer_freezes_only_persisted_inputs_and_preserves_original_scope(isolated_first_fill):
    case = isolated_first_fill; snapshot = deepcopy(case['task']['payload']['plan_snapshot'])
    source, record = freeze(case)
    assert record['observation_source_sha256'] == source['source_sha256']
    assert record['inputs'] == source['observation']['observation']['inputs']
    assert record['lifecycle'] == source['observation']['lifecycle']
    assert record['lifecycle']['owner_observation_id'] == 'a'*32
    assert record['write_authorization_created'] is False and record['live_recheck_required'] is True
    assert require_freeze(case, record) == record
    task = case['repository'].get_task_private(case['task']['id'])
    assert task['payload']['plan_snapshot'] == snapshot
    assert task['payload']['real_dxm_write_authorization']['save_leases'] == case['original_leases']
    with db.connection() as conn:
        assert conn.execute('SELECT COUNT(*) AS n FROM mutation_dispatch_ledger').fetchone()['n'] == 0
        assert conn.execute('SELECT COUNT(*) AS n FROM canonical_receipts').fetchone()['n'] == 0
    with pytest.raises(FrozenExecutionContractError) as failure:
        compile_frozen_execution_payload(task, task['jobs'][0], for_save=True)
    assert failure.value.reason_code == 'CONTENT_FINALIZE_STAGE_NOT_FROZEN'


def test_freeze_rejects_missing_source_duplicate_append_and_caller_values(isolated_first_fill):
    case = isolated_first_fill; repo = case['repository']; ids = case['task']['id'], case['job']['id']
    with pytest.raises(ValueError, match='PERSISTED_SOURCE_REQUIRED'):
        repo.persist_native_video_input_freeze(*ids, source_sha256='D'*64)
    source, _ = freeze(case)
    with pytest.raises(ValueError, match='FREEZE_ALREADY_RECORDED'):
        repo.persist_native_video_input_freeze(*ids, source_sha256=source['source_sha256'])
    with pytest.raises(TypeError):
        repo.persist_native_video_input_freeze(*ids, source_sha256=source['source_sha256'], inputs={'transition': 0})
    assert count(subject.FREEZE_TYPE) == 1


@pytest.mark.parametrize('field', ['inputs', 'lifecycle', 'source_ref', 'time'])
def test_resigned_freeze_map_cannot_replace_actual_source(isolated_first_fill, field):
    case = isolated_first_fill; _, record = freeze(case)
    def changed(value):
        if field == 'inputs':
            value['inputs']['transition'] = 2; value['inputs_sha256'] = canonical_sha256(value['inputs'])
        elif field == 'lifecycle':
            value['lifecycle']['owner_observation_id'] = 'c'*32; value['lifecycle_sha256'] = canonical_sha256(value['lifecycle'])
        elif field == 'source_ref':
            value['observation_source_sha256'] = 'E'*64
        else:
            value['frozen_at'] = '2026-08-31T00:02:00Z'
        value['freeze_sha256'] = canonical_sha256({key: item for key, item in value.items() if key != 'freeze_sha256'})
        record['freeze_sha256'] = value['freeze_sha256']
    rewrite(subject.FREEZE_TYPE, changed)
    with pytest.raises(ValueError):
        require_freeze(case, record)


@pytest.mark.parametrize('kind', ['request', 'result', 'screenshot'])
def test_freeze_consumption_reloads_worker_and_screenshot_files(isolated_first_fill, kind):
    case = isolated_first_fill; source, record = freeze(case)
    path = (source['observation']['observation']['evidence_ref']['path'] if kind == 'screenshot'
            else source['artifacts'][kind]['path'])
    Path(path).write_bytes(b'changed')
    with pytest.raises(ValueError):
        require_freeze(case, record)


def test_generation_consumes_exact_reference_and_existing_grant_without_writing_ledger(isolated_first_fill):
    case = isolated_first_fill; _, record = freeze(case); command = generation(case, record)
    result = require_freeze(case, record, command)
    assert result == record and result['live_recheck_required'] is True
    assert result['write_authorization_created'] is False
    with db.connection() as conn:
        assert conn.execute('SELECT COUNT(*) AS n FROM mutation_dispatch_ledger').fetchone()['n'] == 0
    with pytest.raises(ValueError, match='CURRENT_STEP_INVALID'):
        require_freeze(case, record)


@pytest.mark.parametrize('kind', ['reference', 'action', 'parent_lease', 'stage_facts', 'runtime'])
def test_generation_cannot_reuse_another_command_or_unbound_grant(isolated_first_fill, kind):
    case = isolated_first_fill; _, record = freeze(case); command = generation(case, record)
    if kind == 'reference':
        command = replace(command, params={**command.params, 'native_video_input_freeze_sha256': 'F'*64})
    elif kind == 'action':
        command = replace(command, action='place_editor_video', state='BATCH_VIDEO_PLACE')
    elif kind == 'parent_lease':
        command = replace(command, authorization_lease_fingerprint='F'*64)
    elif kind == 'stage_facts':
        command = replace(command, stage_task_facts_fingerprint='F'*64)
    else:
        command = replace(command, runtime_id='other-runtime')
    with pytest.raises(ValueError):
        require_freeze(case, record, command)
    with db.connection() as conn:
        assert conn.execute('SELECT COUNT(*) AS n FROM mutation_dispatch_ledger').fetchone()['n'] == 0


def test_generation_freshness_is_config_bus_bound_and_never_extends_parent_approval(isolated_first_fill, monkeypatch):
    case = isolated_first_fill; _, record = freeze(case); command = generation(case, record)
    monkeypatch.setattr(repository_module, 'now_iso', lambda: '2026-08-31T00:01:02Z')
    with configuration_scope({'DXM_NATIVE_VIDEO_INPUT_MAX_AGE_SECONDS': '1'}), pytest.raises(ValueError, match='SOURCE_STALE'):
        require_freeze(case, record, command)
    with configuration_scope({'DXM_NATIVE_VIDEO_INPUT_MAX_AGE_SECONDS': '3'}):
        assert require_freeze(case, record, command) == record
    with configuration_scope({'DXM_NATIVE_VIDEO_INPUT_MAX_AGE_SECONDS': '0'}), pytest.raises(ConfigurationError):
        require_freeze(case, record, command)
    monkeypatch.setattr(repository_module, 'now_iso', lambda: '2026-08-31T00:05:00Z')
    with configuration_scope({'DXM_NATIVE_VIDEO_INPUT_MAX_AGE_SECONDS': '600'}), pytest.raises(ValueError):
        require_freeze(case, record, command)


def test_revalidation_failure_rolls_back_append_without_creating_a_freeze(isolated_first_fill, monkeypatch):
    from tests.support.native_video_input_source_case import persist
    case = isolated_first_fill; _, _, source = persist(case)
    actual = subject.append_input_freeze
    def failed(*args, **kwargs):
        actual(*args, **kwargs)
        raise RuntimeError('isolated failure after freeze insertion')
    monkeypatch.setattr(subject, 'append_input_freeze', failed)
    with pytest.raises(RuntimeError, match='after freeze insertion'):
        case['repository'].persist_native_video_input_freeze(case['task']['id'], case['job']['id'], source_sha256=source['source_sha256'])
    assert count(subject.FREEZE_TYPE) == 0 and count(SOURCE_TYPE) == 1
