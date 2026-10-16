"""只读命令不得借用其它阶段、调用方来源或写入权限。"""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from src.batch_edit.frozen_execution_contract import frozen_execution_defaults
from src.execution import browser_agent_worker as worker
from src.execution.browser_agent_protocol import (
    BrowserAgentCommand, MutationCommandContractError, build_frozen_product_target_identity,
    validate_browser_agent_command,
)
from tests.support.editor_inventory_case import inventory_case


@pytest.fixture
def command():
    payload, category = inventory_case()
    return BrowserAgentCommand(command_id='inventory-command', idempotency_key='inventory-read',
        deadline=(datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat(),
        expected_page='editor', runtime_id='runtime-1', task_id=1, job_id=2,
        state='PREPARE_ROLLBACK', action='observe_editor_control_inventory', execution_mode='batch_draft_save',
        params={'defaults': frozen_execution_defaults(payload), 'category_schema': category,
            'product_query': payload['product_id'], 'store_name': 'fixture-store', 'shop_id': '91',
            'target_identity': build_frozen_product_target_identity(product_id=payload['product_id'],
                store_name='fixture-store', source_urls=['https://detail.1688.com/offer/10001.html'])})


def test_inventory_is_a_zero_mutation_command_and_hud_is_deferred(command):
    assert validate_browser_agent_command(command) == {}
    assert worker._defer_page_hud_until_after_action(command) is True


@pytest.mark.parametrize('change', [
    {'state': 'FILL_BASE_INFO'}, {'expected_page': 'semi_managed'}, {'pre_dispatch_page': 'draft_box'},
    {'post_dispatch_page': 'semi_managed'}, {'execution_mode': 'single_save'},
    {'task_id': None}, {'job_id': True}, {'task_id': '01'}, {'job_id': 0},
])
def test_inventory_cannot_be_rebound_to_another_step_page_or_mode(command, change):
    with pytest.raises(MutationCommandContractError, match='只读|清单|分区'):
        validate_browser_agent_command(replace(command, **change))


@pytest.mark.parametrize('change', [
    lambda p: p.update(first_fill_source_sha256='A' * 64),
    lambda p: p.update(category_schema=None),
    lambda p: p['category_schema']['normalized_schema']['properties']['title'].update(ui_section='other_info'),
    lambda p: p['category_schema'].update(schema_hash='A' * 64),
    lambda p: p['defaults'].update(title='Caller override'),
    lambda p: p['defaults'].update(_path_a_fill_context={'caller': True}),
    lambda p: p['defaults'].update(taxType=2.0),
    lambda p: p.update(product_query='10002'),
    lambda p: p.update(product_query=10001),
    lambda p: p.update(store_name=' fixture-store'),
    lambda p: p.update(shop_id=''),
    lambda p: p.update(target_identity=None),
])
def test_unbound_schema_or_caller_parameters_never_enter_worker(command, change):
    params = deepcopy(command.params); change(params)
    with pytest.raises(MutationCommandContractError):
        validate_browser_agent_command(replace(command, params=params))


@pytest.mark.parametrize('field', ['mutation_scope_id', 'target_hash', 'authorization_fingerprint',
    'authorization_lease_id', 'authorization_lease_fingerprint', 'stage_task_facts_fingerprint',
    'execution_payload_hash'])
def test_inventory_cannot_carry_a_write_scope(command, field):
    with pytest.raises(MutationCommandContractError, match='non-mutation'):
        validate_browser_agent_command(replace(command, **{field: 'A' * 64}))


def test_worker_recognizes_pair_but_preserves_its_required_ledger_gate(command):
    runtime = worker.BrowserAgentRuntime()
    try:
        valid = replace(command, runtime_id=runtime.runtime_id)
        assert runtime.reserve_command(valid) == {'ok': False, 'reasonCode': 'MUTATION_LEDGER_REQUIRED',
            'runtimeId': runtime.runtime_id}
        with pytest.raises(MutationCommandContractError):
            runtime.reserve_command(replace(valid, state='FILL_BASE_INFO'))
    finally:
        runtime._executor.shutdown(wait=True)


def test_inventory_mutation_is_denied_before_either_authorizer_or_operation(command):
    runtime = worker.BrowserAgentRuntime()
    calls = []
    try:
        decision = runtime._authorize_mutation(None, command, {}, lambda: calls.append('operation'))
        assert decision == {'ok': False, 'executed': False,
            'reason': 'EDITOR_INVENTORY_OBSERVATION_MUTATION_FORBIDDEN', 'command_id': command.command_id}
        assert calls == []
    finally:
        runtime._executor.shutdown(wait=True)
