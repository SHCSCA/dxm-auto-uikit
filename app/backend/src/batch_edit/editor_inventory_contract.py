"""控件观察的只读来源合同；成功只说明采样闭合，不证明填写或恢复完成。"""

from copy import deepcopy
import re
from urllib.parse import parse_qs, urlsplit

from src.batch_edit.editor_inventory_snapshot import require, validate_inventory
from src.batch_edit.scope_contract import canonical_sha256
from src.execution.e3_authority_contract import parse_strict_utc_timestamp
from src.services.structured_logging import get_logger, log_exception


SCHEMA = 'dxm.editor_inventory_observation.v1'
STATE = 'PREPARE_ROLLBACK'
ACTION = 'observe_editor_control_inventory'
POSTCONDITIONS = ('editor_inventory_observed', 'editor_inventory_stable', 'editor_inventory_zero_write_proven')
PARAMS = frozenset({'defaults', 'category_schema', 'product_query', 'store_name', 'shop_id', 'target_identity'})


def command_binding(context):
    return {**{key: context.get(key) for key in ('command_id', 'state', 'task_id', 'job_id', 'runtime_id', 'browser_session_id')},
            'action': context.get('command_action')}


def validate_observation(value, *, payload, category_schema, target_identity, shop_id, context):
    try:
        return _validate(value, payload=payload, category_schema=category_schema,
            target_identity=target_identity, shop_id=shop_id, context=context)
    except Exception as exc:
        log_exception(get_logger('editor.inventory_contract'), 'editor_inventory_contract_rejected', exc)
        raise


def _validate(value, *, payload, category_schema, target_identity, shop_id, context):
    require(isinstance(value, dict) and set(value) == {'schema', 'command', 'execution_payload_hash', 'category_schema_hash',
        'started_at', 'completed_at', 'before', 'after', 'effect_facts', 'observation'}, 'EDITOR_INVENTORY_WRAPPER_INVALID')
    require(context.get('state') == STATE and context.get('command_action') == ACTION and context.get('mode') == 'batch_draft_save'
        and all(context.get(key) for key in ('command_id', 'runtime_id', 'browser_session_id'))
        and all(type(context.get(key)) in {int, str} and re.fullmatch('[1-9][0-9]*', str(context[key]))
            for key in ('task_id', 'job_id'))
        and value['schema'] == SCHEMA and value['command'] == command_binding(context), 'EDITOR_INVENTORY_COMMAND_DRIFT')
    require(isinstance(category_schema, dict) and isinstance(category_schema.get('normalized_schema'), dict)
        and canonical_sha256(category_schema['normalized_schema']) == category_schema.get('schema_hash')
        == payload.get('category_schema_hash') == value['category_schema_hash']
        and canonical_sha256({key: item for key, item in payload.items() if key != 'payload_hash'}) == payload.get('payload_hash')
        == value['execution_payload_hash'] and payload.get('execution_path') == 'B' and payload.get('save_stage', 'SAVE1') == 'SAVE1',
        'EDITOR_INVENTORY_FROZEN_SCHEMA_DRIFT')
    start = parse_strict_utc_timestamp(value['started_at'], field='inventory start')
    end = parse_strict_utc_timestamp(value['completed_at'], field='inventory end')
    require(start <= end and canonical_sha256(value['before']) == canonical_sha256(value['after']), 'EDITOR_INVENTORY_READBACK_DRIFT')
    inventory = validate_inventory(value['after'], payload=payload, category_schema=category_schema)
    require(inventory['document_time_origin'] <= start.timestamp()*1000, 'EDITOR_INVENTORY_DOCUMENT_TIME_DRIFT')
    observation = value['observation']
    require(isinstance(observation, dict) and set(observation) == {'product_id', 'shop_id', 'browser_session_id', 'page_url',
        'target_identity_sha256', 'observed_at', 'inventory_sha256', 'evidence_ref', 'write_attempted'}, 'EDITOR_INVENTORY_OBSERVATION_INVALID')
    product_id = str(payload['product_id']); page = urlsplit(observation['page_url'])
    require(target_identity['stable_identity']['kind'] == 'product_id' and target_identity['stable_identity']['value'] == product_id
        and str(observation['product_id']) == product_id and str(observation['shop_id']) == str(shop_id)
        and observation['browser_session_id'] == context['browser_session_id']
        and observation['target_identity_sha256'] == canonical_sha256(target_identity)
        and observation['inventory_sha256'] == inventory['inventory_sha256']
        and inventory['page_url'] == observation['page_url'] and observation['observed_at'] == value['completed_at']
        and observation['write_attempted'] is False and page.scheme == 'https' and page.netloc == 'www.dianxiaomi.com'
        and page.path == '/web/smt/edit' and not page.fragment and parse_qs(page.query) == {'id': [product_id]},
        'EDITOR_INVENTORY_IDENTITY_OR_TIME_DRIFT')
    require(value['effect_facts'] == {'request_facts': [], 'unexpected_effects': []}, 'EDITOR_INVENTORY_ZERO_REQUEST_UNPROVEN')
    ref = observation['evidence_ref']
    require(isinstance(ref, dict) and set(ref) == {'path', 'sha256', 'size'} and isinstance(ref['path'], str)
        and bool(ref['path']) and type(ref['size']) is int and ref['size'] > 0
        and isinstance(ref['sha256'], str) and len(ref['sha256']) == 64
        and all(character in '0123456789ABCDEF' for character in ref['sha256']), 'EDITOR_INVENTORY_SCREENSHOT_INVALID')
    return deepcopy(value)
