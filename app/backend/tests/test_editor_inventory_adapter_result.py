"""真实离线采集经 Adapter/Worker 封装器复验，不将合成 DOM 当生产填写成功。"""

import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
from playwright.sync_api import sync_playwright

from src.batch_edit.editor_inventory_contract import ACTION, POSTCONDITIONS, STATE
from src.execution.action_result_contract import validate_action_result_envelope
from src.execution.browser_action_dispatch import execute_browser_agent_action
from src.execution.browser_agent_protocol import BrowserAgentCommand
from src.execution.browser_agent_worker import BrowserAgentExecutionContext, BrowserAgentRuntime
from src.execution.editor_inventory_result import validate_editor_inventory_result
from tests.support.editor_inventory_flow_case import editor_inventory_flow_case


@pytest.fixture(scope='module')
def browser():
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(headless=True,
            args=['--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1'])
        yield instance
        instance.close()


@pytest.fixture
def result(browser, tmp_path, monkeypatch):
    with editor_inventory_flow_case(browser, tmp_path, monkeypatch) as case:
        command = BrowserAgentCommand(command_id=case.evidence['command_id'], idempotency_key='inventory-test',
            deadline=(datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat(), expected_page='editor',
            runtime_id=case.evidence['runtime_id'], task_id=1, job_id=2, state=STATE, action=ACTION,
            execution_mode='batch_draft_save', params=deepcopy(case.args))
        context = BrowserAgentExecutionContext(command_id=command.command_id, idempotency_key=command.idempotency_key,
            runtime_id=command.runtime_id, browser_session_id=case.flow.browser_session_id(), expected_page='editor',
            generation=0, deadline_monotonic=case.evidence['deadline_monotonic'], cancel_epoch=0, task_id=1, job_id=2,
            state=STATE, mode='batch_draft_save')
        case.adapter.set_execution_evidence_context({**dict(context.as_mapping()), 'command_action': ACTION})
        raw = execute_browser_agent_action(case.adapter, ACTION, command.params)
        runtime = BrowserAgentRuntime()
        try:
            envelope = runtime._build_action_result_envelope(case.adapter, command, context, raw)
        finally:
            runtime._executor.shutdown(wait=True)
        yield case, raw, envelope


def validate(case, envelope):
    return validate_action_result_envelope(envelope, expected_state=STATE, expected_action=ACTION, expected_page='editor',
        execution_mode='batch_draft_save', expected_runtime_id=case.evidence['runtime_id'],
        expected_browser_session_id=case.flow.browser_session_id(), expected_execution_payload=case.payload)


def test_actual_dispatch_adapter_and_worker_envelope_keep_six_inputs_and_private_readbacks(result):
    case, raw, envelope = result
    assert raw['ok'] is True and envelope['ok'] is True
    assert envelope['before_values'] == case.args
    assert set(envelope['after_values']) == {'editor_control_inventory'}
    assert envelope['postconditions'] == dict.fromkeys(POSTCONDITIONS, True)
    assert 'Original title' not in json.dumps(envelope['after_values'])
    assert 'Original title' in json.dumps(envelope['evidence']['observations']['editor_inventory_observation'])
    assert envelope['after_values']['editor_control_inventory']['required_fields_complete'] is False
    assert 'mandatory_capability_receipts' not in envelope['evidence']['observations']
    assert validate(case, envelope) == envelope


@pytest.mark.parametrize('field', ['command', 'defaults', 'extra_default', 'type_default', 'schema', 'values', 'completeness', 'postcondition', 'summary', 'receipt', 'screenshot', 'effect'])
def test_result_contract_rejects_replaced_or_overstated_observations(result, field):
    case, _raw, envelope = result
    value = deepcopy(envelope)
    observed = value['evidence']['observations']['editor_inventory_observation']
    if field == 'command':
        observed['command']['action'] = 'prepare_rollback'
    elif field == 'defaults':
        value['before_values']['defaults']['title'] = 'invented'
    elif field == 'extra_default':
        value['before_values']['defaults']['unreviewed'] = 'invented'
    elif field == 'type_default':
        value['before_values']['defaults']['taxType'] = 2.0
    elif field == 'schema':
        value['before_values']['category_schema']['normalized_schema']['properties']['title']['ui_section'] = 'other_info'
    elif field == 'values':
        observed['after']['fields'][0]['original_value'] = 'invented'
    elif field == 'completeness':
        observed['after']['required_fields_complete'] = True
    elif field == 'postcondition':
        value['postconditions']['required_fields_complete'] = True
    elif field == 'summary':
        value['after_values']['editor_control_inventory']['required_fields_complete'] = True
    elif field == 'receipt':
        value['evidence']['observations']['mandatory_capability_receipts'] = {'rollbackPreparation': {'ok': True}}
    elif field == 'screenshot':
        observed['observation']['evidence_ref']['size'] = 0
    else:
        observed['effect_facts']['request_facts'] = [{'allowed': True}]
    with pytest.raises(ValueError):
        validate_editor_inventory_result(value, execution_mode='batch_draft_save', expected_payload=case.payload)
