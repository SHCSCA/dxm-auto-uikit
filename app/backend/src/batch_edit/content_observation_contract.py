"""独立最终读回的结构约束；通过不表示动作完成或允许保存。"""

from copy import deepcopy
from urllib.parse import parse_qs, urlsplit

from src.batch_edit.scope_contract import canonical_sha256
from src.execution.e3_authority_contract import parse_strict_utc_timestamp


ACTION = 'observe_content_finalize'
STATE = 'BATCH_TRANSLATE_EXECUTE'
POSTCONDITIONS = ('content_fields_observed', 'content_readback_stable', 'content_zero_write_proven')
OBSERVATION_KEYS = {'product_id', 'shop_id', 'browser_session_id', 'page_url', 'target_identity_sha256',
                    'observed_at', 'values', 'bindings', 'write_attempted', 'evidence_ref'}


def command_binding(context):
    return {**{key: context.get(key) for key in ('command_id', 'state', 'task_id', 'job_id', 'runtime_id', 'browser_session_id')},
            'action': context.get('command_action')}


def validate_observation(value, *, payload, target_identity, shop_id, context):
    def require(condition, code):
        if not condition:
            raise ValueError(code)

    require(isinstance(value, dict) and set(value) == {'schema', 'command', 'execution_payload_hash', 'started_at',
        'completed_at', 'before', 'after', 'effect_facts', 'observation'}, 'CONTENT_OBSERVATION_SHAPE_INVALID')
    require(context.get('state') == STATE and context.get('command_action') == ACTION
            and context.get('mode') == 'batch_draft_save' and bool(context.get('command_id'))
            and bool(context.get('runtime_id')) and bool(context.get('browser_session_id')),
            'CONTENT_OBSERVATION_COMMAND_INVALID')
    require(value['schema'] == 'dxm.content_finalize_observation.v1' and value['command'] == command_binding(context)
            and payload.get('execution_path') == 'B' and payload.get('save_stage', 'SAVE1') == 'SAVE1'
            and value['execution_payload_hash'] == payload['payload_hash'], 'CONTENT_OBSERVATION_COMMAND_DRIFT')
    start = parse_strict_utc_timestamp(value['started_at'], field='content observation start')
    end = parse_strict_utc_timestamp(value['completed_at'], field='content observation end')
    require(start <= end, 'CONTENT_OBSERVATION_TIME_INVALID')
    observation = value['observation']
    require(isinstance(observation, dict) and set(observation) == OBSERVATION_KEYS, 'CONTENT_OBSERVATION_VALUES_INVALID')
    page = urlsplit(observation['page_url'])
    product_id = str(payload['product_id'])
    require(target_identity['stable_identity'].get('kind') == 'product_id'
            and target_identity['stable_identity'].get('value') == product_id
            and str(observation['product_id']) == product_id and str(observation['shop_id']) == str(shop_id)
            and observation['browser_session_id'] == context['browser_session_id']
            and observation['target_identity_sha256'] == canonical_sha256(target_identity)
            and page.scheme == 'https' and page.netloc == 'www.dianxiaomi.com' and page.path == '/web/smt/edit'
            and not page.fragment and parse_qs(page.query).get('id') == [product_id], 'CONTENT_OBSERVATION_IDENTITY_DRIFT')
    require(observation['write_attempted'] is False and observation['observed_at'] == value['completed_at'],
            'CONTENT_OBSERVATION_WRITE_OR_TIME_DRIFT')
    fields = payload['fields']
    bindings = {field['field_key']: field['ui_binding'] for field in fields}
    require(len(bindings) == len(fields) and observation['bindings'] == bindings
            and isinstance(observation['values'], dict) and set(observation['values']) == set(bindings),
            'CONTENT_OBSERVATION_COVERAGE_INVALID')
    require(value['before'] == value['after'], 'CONTENT_OBSERVATION_READBACK_DRIFT')
    snapshot = value['before']
    require(isinstance(snapshot, dict) and set(snapshot) == {'values', 'bindings', 'category_schema', 'form_sha256'}
            and snapshot['values'] == observation['values'] and snapshot['bindings'] == bindings,
            'CONTENT_OBSERVATION_SNAPSHOT_INVALID')
    category = payload.get('target_category', {}).get('category_id', payload['category_id'])
    schema = snapshot['category_schema']
    require(isinstance(schema, dict) and schema.get('ok') is True
            and schema.get('observed_category_id') == str(category)
            and schema.get('expected_category_id') == str(category)
            and schema.get('observed_category_schema_hash') == payload['category_schema_hash']
            and schema.get('expected_category_schema_hash') == payload['category_schema_hash'], 'CONTENT_OBSERVATION_SCHEMA_DRIFT')
    facts = value['effect_facts']
    require(isinstance(facts, dict) and set(facts) == {'request_facts', 'unexpected_effects'}
            and facts['unexpected_effects'] == [] and isinstance(facts['request_facts'], list)
            and len(facts['request_facts']) >= 2, 'CONTENT_OBSERVATION_EFFECT_UNPROVEN')
    for request in facts['request_facts']:
        require(isinstance(request, dict) and set(request) == {'method', 'path', 'request_sha256', 'allowed'}
                and request['allowed'] is True and request['method'] == 'POST'
                and request['path'] in {'/api/smtCategory/attributeList.json', '/api/smtCategory/childAttributeList.json'},
                'CONTENT_OBSERVATION_REQUEST_FORBIDDEN')
    for digest in [snapshot['form_sha256'], *(request['request_sha256'] for request in facts['request_facts'])]:
        require(isinstance(digest, str) and len(digest) == 64 and all(c in '0123456789ABCDEF' for c in digest),
                'CONTENT_OBSERVATION_HASH_INVALID')
    ref = observation['evidence_ref']
    require(isinstance(ref, dict) and set(ref) == {'path', 'sha256', 'size'} and isinstance(ref['path'], str)
            and bool(ref['path']) and type(ref['size']) is int and ref['size'] > 0
            and isinstance(ref['sha256'], str) and len(ref['sha256']) == 64, 'CONTENT_OBSERVATION_SCREENSHOT_INVALID')
    return deepcopy(value)
