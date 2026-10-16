"""完整私有清单的纯合同反例；合成字段与截图不证明生产可执行。"""

from copy import deepcopy

import pytest

from src.batch_edit.editor_inventory_contract import ACTION, PARAMS, STATE, validate_observation
from src.batch_edit.scope_contract import canonical_sha256
from src.execution.browser_agent_protocol import build_frozen_product_target_identity
from tests.support.editor_inventory_case import inventory_case
from tests.support.editor_inventory_source_case import InventoryFlow


@pytest.fixture
def observation_case(tmp_path):
    payload, category = inventory_case()
    target = build_frozen_product_target_identity(product_id=payload['product_id'], store_name='Synthetic Shop',
        source_urls=['https://detail.1688.com/offer/10001.html'])
    context = {'command_id': 'a'*32, 'state': STATE, 'command_action': ACTION, 'mode': 'batch_draft_save',
        'task_id': 1, 'job_id': 1, 'runtime_id': 'synthetic-runtime', 'browser_session_id': 'synthetic-session'}
    flow = InventoryFlow(payload, category, session=context['browser_session_id'])
    flow.screenshot_root = tmp_path; flow.set_execution_evidence_context(context)
    params = {'defaults': {'_frozen_execution_payload': payload}, 'category_schema': category,
        'target_identity': target, 'shop_id': '91', 'product_query': payload['product_id'], 'store_name': 'Synthetic Shop'}
    wrapper = flow.observe_editor_control_inventory(**params)['editor_inventory_observation']
    return {'wrapper': wrapper, 'payload': payload, 'category_schema': category, 'target_identity': target,
        'shop_id': '91', 'context': context}


def validate(case, wrapper=None):
    return validate_observation(case['wrapper'] if wrapper is None else wrapper,
        **{key: case[key] for key in ('payload', 'category_schema', 'target_identity', 'shop_id', 'context')})


def resign(wrapper):
    inventory = wrapper['after']
    inventory['inventory_sha256'] = canonical_sha256({key: item for key, item in inventory.items() if key != 'inventory_sha256'})
    wrapper['before'] = deepcopy(inventory)
    wrapper['observation']['inventory_sha256'] = inventory['inventory_sha256']


def test_complete_inventory_binds_all_eleven_sections_and_frozen_template_references(observation_case):
    case = observation_case; result = validate(case)
    assert len(result['after']['sections']) == 11
    assert result['after']['templates'][0]['frozen_reference'] == case['payload']['dxm_template_refs'][0]
    assert result['after']['templates'][0]['application_state'] == 'UNOBSERVED'
    assert 'FULL_FILL_EXECUTION_SOURCE_NOT_BOUND' in result['after']['missing']
    assert result is not case['wrapper'] and len(PARAMS) == 6


@pytest.mark.parametrize('change', ['executionAllowed', 'capabilityCertified', 'required_fields_complete', 'inputFreezeAllowed',
    'write_attempted', 'field_execution', 'field_target', 'field_section', 'fields', 'sections', 'template', 'missing', 'unfrozen'])
def test_resigned_candidate_cannot_remove_missing_diagnostics_or_claim_authority(observation_case, change):
    case = observation_case; wrapper = deepcopy(case['wrapper']); inventory = wrapper['after']
    if change in {'executionAllowed', 'capabilityCertified', 'required_fields_complete', 'inputFreezeAllowed', 'write_attempted'}:
        inventory[change] = True
    elif change == 'field_execution':
        inventory['fields'][0]['executionAllowed'] = True
    elif change == 'field_target':
        inventory['fields'][0]['target_value'] = 'Changed target'
    elif change == 'field_section':
        inventory['fields'][0]['section'] = 'other_info'
    elif change == 'fields':
        inventory['fields'].pop()
    elif change == 'sections':
        inventory['sections'].pop()
    elif change == 'template':
        inventory['templates'][0]['application_state'] = 'APPLIED'
    elif change == 'missing':
        inventory['missing'].remove('FULL_FILL_EXECUTION_SOURCE_NOT_BOUND')
    else:
        inventory['unfrozen_required_fields'] = ['forged_required_field']
    resign(wrapper)
    with pytest.raises(ValueError):
        validate(case, wrapper)


@pytest.mark.parametrize('change', ['readback', 'command', 'schema', 'payload', 'session', 'page', 'effects', 'time', 'ref'])
def test_wrapper_cannot_cross_command_schema_document_or_observation_window(observation_case, change):
    case = observation_case; wrapper = deepcopy(case['wrapper'])
    if change == 'readback':
        wrapper['before']['document_time_origin'] += 1
    elif change == 'command':
        wrapper['command']['action'] = 'prepare_rollback'
    elif change == 'schema':
        wrapper['category_schema_hash'] = 'A'*64
    elif change == 'payload':
        wrapper['execution_payload_hash'] = 'A'*64
    elif change == 'session':
        wrapper['observation']['browser_session_id'] = 'changed-session'
    elif change == 'page':
        wrapper['observation']['page_url'] += '&other=1'
    elif change == 'effects':
        wrapper['effect_facts']['request_facts'] = [{'allowed': True}]
    elif change == 'time':
        wrapper['started_at'] = '2026-08-31T00:02:00Z'
    else:
        wrapper['observation']['evidence_ref']['size'] = True
    with pytest.raises(ValueError):
        validate(case, wrapper)


@pytest.mark.parametrize('field', ['task_id', 'job_id'])
@pytest.mark.parametrize('value', [None, True, 0, '01'])
def test_self_consistent_wrapper_cannot_omit_or_alias_canonical_task_and_job_ids(observation_case, field, value):
    case = observation_case
    case['context'][field] = value
    case['wrapper']['command'][field] = value
    with pytest.raises(ValueError, match='COMMAND_DRIFT'):
        validate(case)


def test_resigned_future_document_origin_cannot_precede_observation(observation_case):
    case = observation_case; wrapper = deepcopy(case['wrapper'])
    wrapper['after']['document_time_origin'] = 9999999999999
    resign(wrapper)
    with pytest.raises(ValueError, match='DOCUMENT_TIME_DRIFT'):
        validate(case, wrapper)
