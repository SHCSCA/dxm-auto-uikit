"""
Real adapter for one-click translation in batch edit workflow.

Translates title, attributes, description (PC + mobile), custom name.
Records before/after values and evidence.
Dispatch uncertain → execution_state=UNKNOWN.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit

from src.batch_edit.path_a_section_templates import AutoTranslateConfig


# Native smt/edit content identities from the current public translation component.
# These labels verify the selected scope; they never identify product fields to write.
_NATIVE_TRANSLATION_LABELS = {
    'title': '标题', 'attributes': '自定义属性', 'custom_name': '自定义名称',
    'description_pc': 'PC端描述', 'description_mobile': '无线端描述',
}


def _require_native_translation_config(config):
    from src.batch_edit.plan_template_contract import validate_editor_actions

    validate_editor_actions({'translation': config})
    if config['translate_type'] != 'normal':
        raise ValueError('TRANSLATION_NATIVE_MODE_NOT_BOUND')


def validate_native_translation_surface(surface, config):
    """Verify native selections against the shared rule, not popup defaults or a toast."""
    _require_native_translation_config(config)
    if (not isinstance(surface, dict) or surface.get('schema') != 'dxm.editor_content_surface.v1'
            or surface.get('action') != 'translation' or type(surface.get('surface_match_count')) is not int
            or surface['surface_match_count'] != 1 or surface.get('write_attempted') is not False
            or surface.get('execution_allowed') is not False):
        raise ValueError('TRANSLATION_SURFACE_NOT_UNIQUE')
    types = surface.get('types', {}).get('matches', [])
    selected = [item for item in types if item.get('selected') is True or item.get('checked') is True]
    if (len(selected) != 1 or selected[0].get('value') != '1'
            or selected[0].get('text') != '普通翻译' or selected[0].get('input_match_count') != 1
            or any(selected[0].get(key) is not True for key in ('visible', 'selected', 'checked'))
            or selected[0].get('disabled') is not False):
        raise ValueError('TRANSLATION_NORMAL_MODE_NOT_SELECTED')
    content = surface.get('content', {}).get('matches', [])
    expected = {_NATIVE_TRANSLATION_LABELS[key] for key in config['apply_to']}
    if len(content) != 1 or content[0].get('visible') is not True or not isinstance(content[0].get('text'), str):
        raise ValueError('TRANSLATION_CONTENT_NOT_UNIQUE')
    labels = [label.strip() for label in content[0]['text'].split('、')]
    if len(labels) != len(expected) or set(labels) != expected:
        raise ValueError('TRANSLATION_SHARED_SCOPE_MISMATCH')
    languages = [item for item in surface.get('languages', {}).get('matches', [])
                 if item.get('titles') == ['中文 → 英文']]
    if (len(languages) != 1 or languages[0].get('visible') is not True
            or languages[0].get('disabled') is not False
            or languages[0].get('descriptions') != ['点击该行即执行；将翻译：' + content[0]['text']]):
        raise ValueError('TRANSLATION_LANGUAGE_SCOPE_MISMATCH')
    return surface


def prepare_native_translation(page, config):
    """Open and verify native controls only. Never click a language or certify translation.

    The production caller must retain its page/identity checks, then revalidate
    this surface inside ControlledMutationDispatch before the separate language click.
    """
    from src.execution.editor_readonly_inspection import (
        EDITOR_CONTENT_ACTION_SURFACE_SCRIPT, EDITOR_DIALOG_REVEAL_BINDINGS,
        EDITOR_TRANSLATION_SURFACE_BINDING,
    )

    _require_native_translation_config(config)
    selector, name = EDITOR_DIALOG_REVEAL_BINDINGS['translation']
    entry = page.locator(selector).filter(has_text=re.compile('^' + re.escape(name) + '$'))
    if entry.count() != 1 or not entry.is_visible() or not entry.is_enabled():
        raise ValueError('TRANSLATION_ENTRY_NOT_UNIQUE_VISIBLE')
    entry.click(timeout=5000)
    panel = page.locator(EDITOR_TRANSLATION_SURFACE_BINDING)
    panel.wait_for(state='visible', timeout=10000)
    if panel.count() != 1:
        raise ValueError('TRANSLATION_SURFACE_NOT_UNIQUE')
    normal = panel.locator('.panel-translate-type .ant-radio-button-wrapper:has(input[type="radio"][value="1"])')
    if (normal.count() != 1 or not normal.is_visible() or not normal.is_enabled()
            or normal.inner_text().strip() != '普通翻译'):
        raise ValueError('TRANSLATION_NORMAL_CONTROL_NOT_UNIQUE')
    observed = page.evaluate(EDITOR_CONTENT_ACTION_SURFACE_SCRIPT, 'translation')
    choices = [item for item in observed.get('types', {}).get('matches', []) if item.get('value') == '1']
    if (len(choices) != 1 or choices[0].get('input_match_count') != 1
            or choices[0].get('visible') is not True or choices[0].get('disabled') is not False):
        raise ValueError('TRANSLATION_NORMAL_CONTROL_NOT_UNIQUE')
    if choices[0].get('selected') is not True or choices[0].get('checked') is not True:
        normal.click(timeout=5000)
    return validate_native_translation_surface(
        page.evaluate(EDITOR_CONTENT_ACTION_SURFACE_SCRIPT, 'translation'), config)


class NativeTranslationNetwork:
    """Observe browser-originated translation only; never issue HTTP requests.

    Arm inside the existing authorized language-click operation. Keep a sealed
    route after success/failure so delayed native fallbacks cannot escape. The
    owning Flow closes it only when retiring that operation/page.
    """

    URL = 'https://www.dianxiaomi.com/aliYunTranslate/freeBatchTranslate.json'
    _HAN = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]')

    def __init__(self, page, *, allowed_texts, readonly_requests):
        if (not isinstance(allowed_texts, list) or not allowed_texts
                or any(not isinstance(value, str) or not value.strip() for value in allowed_texts)):
            raise ValueError('TRANSLATION_SOURCE_TEXT_REQUIRED')
        self.page = page
        self.allowed_texts = tuple(allowed_texts)
        self.readonly_requests = frozenset(readonly_requests)
        self.failure_code = None
        self._armed = self._sealed = False
        self._events, self._requests, self._listeners = [], {}, []
        self._route_installed = False

    @staticmethod
    def _json(raw):
        def unique_pairs(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('TRANSLATION_DUPLICATE_JSON_KEY')
                result[key] = value
            return result
        if not isinstance(raw, bytes) or not raw:
            raise ValueError('TRANSLATION_BODY_UNAVAILABLE')
        return json.loads(raw.decode('utf-8-sig'), object_pairs_hook=unique_pairs)

    def _fail(self, code):
        if self.failure_code is None:
            self.failure_code = code

    def install(self):
        if self._route_installed or self._listeners:
            raise ValueError('TRANSLATION_OBSERVER_ALREADY_INSTALLED')
        try:
            self.page.context.route('**/*', self._route)
            self._route_installed = True
            for event, listener in (('response', self._response), ('requestfailed', self._request_failed)):
                self.page.on(event, listener)
                self._listeners.append((event, listener))
        except Exception:
            self.close()
            raise

    def arm(self):
        if not self._route_installed or len(self._listeners) != 2 or self._armed or self._sealed or self.failure_code:
            raise ValueError('TRANSLATION_OBSERVER_NOT_ARMABLE')
        self._armed = True

    def _route(self, route):
        from src.batch_edit.scope_contract import canonical_sha256

        request = route.request
        try:
            parts = urlsplit(request.url)
            translation = ('translate' in parts.path.casefold()
                           or parts.hostname in {'translate.volcengine.com', 'translate.dianxiaomi.com'})
            # Once sealed, preserve other stages' own network/dispatch guards.
            if self._sealed and not translation:
                route.fallback()
                return
            if translation:
                if self._sealed:
                    raise ValueError('TRANSLATION_REQUEST_AFTER_SEAL')
                if not self._armed:
                    raise ValueError('TRANSLATION_REQUEST_BEFORE_AUTHORIZATION')
                if self.failure_code:
                    raise ValueError(self.failure_code)
                if request.url != self.URL or request.method != 'POST':
                    raise ValueError('TRANSLATION_NATIVE_FALLBACK_FORBIDDEN')
                if request.frame.page is not self.page or request.resource_type not in {'xhr', 'fetch'}:
                    raise ValueError('TRANSLATION_REQUEST_PAGE_MISMATCH')
                raw = request.post_data_buffer
                body = self._json(raw)
                if (not isinstance(body, dict)
                        or set(body) != {'module', 'textList', 'sourceLanguage', 'targetLanguage'}
                        or body['module'] != '速卖通产品' or body['sourceLanguage'] != 'zh'
                        or body['targetLanguage'] != 'en' or not isinstance(body['textList'], list)
                        or not body['textList'] or any(not isinstance(text, str) or not text.strip()
                            or not self._HAN.search(text)
                            or not any(text in source for source in self.allowed_texts) for text in body['textList'])):
                    raise ValueError('TRANSLATION_REQUEST_SCOPE_MISMATCH')
                if id(request) in self._requests:
                    raise ValueError('TRANSLATION_REQUEST_ALREADY_OBSERVED')
                event = {'sequence': len(self._events) + 1, 'url': request.url, 'method': request.method,
                         'request': body, 'request_sha256': canonical_sha256(body),
                         'request_body_sha256': hashlib.sha256(raw).hexdigest(), 'completed': False}
                self._requests[id(request)] = (request, event)
                self._events.append(event)
                route.fallback()
                return
            if (request.method, request.url) in self.readonly_requests:
                route.fallback()
                return
            if (request.method == 'GET' and parts.scheme == 'https'
                    and request.resource_type in {'image', 'stylesheet', 'script', 'font', 'media'}):
                route.fallback()
                return
            raise ValueError('TRANSLATION_UNEXPECTED_REQUEST')
        except Exception as exc:
            code = str(exc) if isinstance(exc, ValueError) and str(exc).startswith('TRANSLATION_') else 'TRANSLATION_REQUEST_UNPROVEN'
            self._fail(code)
            route.abort()

    def _response(self, response):
        from src.batch_edit.scope_contract import canonical_sha256

        entry = self._requests.get(id(response.request))
        if entry is None:
            return
        event = entry[1]
        try:
            if event['completed']:
                raise ValueError('TRANSLATION_RESPONSE_DUPLICATE')
            raw = response.body()
            body = self._json(raw)
            event.update(status=response.status, response=body, response_sha256=canonical_sha256(body),
                         response_body_sha256=hashlib.sha256(raw).hexdigest(), completed=True)
            if (response.url != event['url'] or type(response.status) is not int or response.status != 200
                    or not isinstance(body, dict) or type(body.get('code')) is not int or body['code'] != 0
                    or not isinstance(body.get('data'), list) or len(body['data']) != len(event['request']['textList'])
                    or any(not isinstance(text, str) or not text.strip() or self._HAN.search(text) for text in body['data'])):
                raise ValueError('TRANSLATION_BUSINESS_RESULT_UNPROVEN')
        except Exception as exc:
            event['completed'] = True
            self._fail(str(exc) if isinstance(exc, ValueError) and str(exc).startswith('TRANSLATION_')
                       else 'TRANSLATION_RESPONSE_UNPROVEN')

    def _request_failed(self, request):
        entry = self._requests.get(id(request))
        if entry is not None:
            entry[1]['completed'] = True
            self._fail('TRANSLATION_REQUEST_FAILED')

    @property
    def pending_count(self):
        return sum(event['completed'] is not True for event in self._events)

    def evidence(self):
        if self.failure_code:
            raise ValueError(self.failure_code)
        if self.pending_count:
            raise ValueError('TRANSLATION_NETWORK_PENDING')
        if not self._armed or not self._events:
            raise ValueError('TRANSLATION_NETWORK_MISSING')
        return {'request_count': len(self._events), 'events': deepcopy(self._events)}

    def seal(self):
        self._sealed = True

    def close(self):
        self.seal()
        for event, listener in self._listeners:
            self.page.remove_listener(event, listener)
        self._listeners.clear()
        if self._route_installed:
            self.page.context.unroute('**/*', self._route)
            self._route_installed = False


def native_translation_fields(payload):
    """Project readback fields only; this never replaces the frozen command payload."""
    from src.batch_edit.scope_contract import canonical_sha256

    policy = payload.get('content_finalize_policy', {})
    if (payload.get('execution_path') != 'B' or policy.get('schema') != 'dxm.content_finalize_policy.v1'
            or canonical_sha256({k: v for k, v in policy.items() if k != 'policy_sha256'}) != policy.get('policy_sha256')):
        raise ValueError('TRANSLATION_FROZEN_POLICY_INVALID')
    owners = {item['field_key']: item for item in policy['fields']
              if item['delegated_to'] == 'content_finalize.translation'}
    fields = [item for item in payload['fields'] if item.get('delegated_to') != 'content_finalize.video']
    if not owners or set(owners) != {item['field_key'] for item in fields
                                   if item.get('delegated_to') == 'content_finalize.translation'}:
        raise ValueError('TRANSLATION_OWNER_COVERAGE_INVALID')
    return fields, owners


def native_translation_texts(value, definition):
    if definition.get('readOnly') is True or definition.get('enum'):
        return []
    if definition.get('type') == 'string' and definition.get('natural_language') is True:
        return [value] if isinstance(value, str) and value.strip() else []
    if isinstance(value, list) and definition.get('type') == 'array':
        return [text for child in value for text in native_translation_texts(child, definition.get('items', {}))]
    if isinstance(value, dict) and definition.get('type') == 'object':
        return [text for key, child in value.items()
                for text in native_translation_texts(child, definition.get('properties', {}).get(key, {}))]
    return []


def validate_native_translation_values(payload, before, after, network):
    """Require actual provider outputs in owned leaves; IDs/structure stay unchanged."""
    from src.batch_edit.plan_schema_contract import assert_value_matches_schema
    from src.batch_edit.scope_contract import canonical_sha256

    fields, owners = native_translation_fields(payload)
    expected = {item['field_key']: item['resolved_value'] for item in fields}
    if (not isinstance(before, dict) or not isinstance(after, dict) or before != expected
            or set(after) != set(expected)):
        raise ValueError('TRANSLATION_FIELD_COVERAGE_OR_PREIMAGE_DRIFT')
    texts = [text for key, owner in owners.items()
             for text in native_translation_texts(before[key], owner['property_schema'])]
    events = network.get('events') if isinstance(network, dict) else None
    if not isinstance(events, list) or not events or type(network.get('request_count')) is not int or network['request_count'] != len(events):
        raise ValueError('TRANSLATION_NETWORK_MISSING')
    pairs = {}
    for index, event in enumerate(events, 1):
        request, response = event.get('request', {}), event.get('response', {})
        if (event.get('sequence') != index or event.get('completed') is not True
                or event.get('url') != NativeTranslationNetwork.URL or event.get('method') != 'POST'
                or type(event.get('status')) is not int or event['status'] != 200
                or not isinstance(request, dict) or set(request) != {'module', 'textList', 'sourceLanguage', 'targetLanguage'}
                or request['module'] != '速卖通产品' or request['sourceLanguage'] != 'zh' or request['targetLanguage'] != 'en'
                or not isinstance(request['textList'], list) or not request['textList']
                or not isinstance(response, dict) or type(response.get('code')) is not int or response['code'] != 0
                or not isinstance(response.get('data'), list) or len(response['data']) != len(request['textList'])
                or canonical_sha256(request) != event.get('request_sha256')
                or canonical_sha256(response) != event.get('response_sha256')
                or any(re.fullmatch(r'[0-9a-fA-F]{64}', str(event.get(key, ''))) is None
                       for key in ('request_body_sha256', 'response_body_sha256'))):
            raise ValueError('TRANSLATION_NETWORK_RESULT_INVALID')
        for old, new in zip(request['textList'], response['data']):
            if (not isinstance(old, str) or not old.strip() or not NativeTranslationNetwork._HAN.search(old)
                    or not any(old in source for source in texts)
                    or not isinstance(new, str) or not new.strip() or NativeTranslationNetwork._HAN.search(new)
                    or (old in pairs and pairs[old] != new)):
                raise ValueError('TRANSLATION_RESPONSE_SCOPE_OR_VALUE_INVALID')
            pairs[old] = new

    def check(old, new, definition):
        if (definition.get('readOnly') is not True and not definition.get('enum')
                and definition.get('type') == 'string' and definition.get('natural_language') is True):
            if not isinstance(old, str) or not isinstance(new, str) or NativeTranslationNetwork._HAN.search(new):
                raise ValueError('TRANSLATION_TEXT_RESULT_INVALID')
            # Replace observed original spans once, without translating provider outputs again.
            pattern = re.compile('|'.join(re.escape(text) for text in sorted(pairs, key=len, reverse=True)))
            expected_text = pattern.sub(lambda match: pairs[match.group()], old)
            if new != expected_text:
                raise ValueError('TRANSLATION_READBACK_NOT_PROVIDER_OUTPUT')
        elif definition.get('readOnly') is not True and isinstance(old, dict) and isinstance(new, dict) and set(old) == set(new):
            for key in old:
                check(old[key], new[key], definition.get('properties', {}).get(key, {}))
        elif definition.get('readOnly') is not True and isinstance(old, list) and isinstance(new, list) and len(old) == len(new):
            for left, right in zip(old, new):
                check(left, right, definition.get('items', {}))
        elif canonical_sha256(old) != canonical_sha256(new):
            raise ValueError('TRANSLATION_NON_TEXT_OR_STRUCTURE_CHANGED')

    for key in expected:
        if key in owners:
            definition = owners[key]['property_schema']
            assert_value_matches_schema(after[key], definition, field_key=key)
            check(before[key], after[key], definition)
        elif canonical_sha256(before[key]) != canonical_sha256(after[key]):
            raise ValueError('TRANSLATION_UNOWNED_FIELD_CHANGED')
    return after


NATIVE_TRANSLATION_POSTCONDITIONS = frozenset({
    'translation_scope_exact', 'translation_business_success',
    'translation_readback_exact', 'translation_structure_preserved',
})


def validate_editor_translation_observation(observation, *, defaults, target_identity, command_context=None, expected_payload=None):
    from src.batch_edit.frozen_execution_contract import validate_frozen_execution_defaults
    from src.execution.e3_authority_contract import parse_strict_utc_timestamp

    payload = validate_frozen_execution_defaults(defaults, expected_payload=expected_payload)
    expected_keys = {'schema', 'command', 'execution_payload_hash', 'target_identity', 'page_url', 'shop_id',
                     'started_at', 'completed_at', 'surface', 'before', 'after', 'network', 'mutation_authorization',
                     'wholesale_command_id', 'evidence_ref'}
    if not isinstance(observation, dict) or set(observation) != expected_keys or observation['schema'] != 'dxm.editor_translation_observation.v1':
        raise ValueError('TRANSLATION_OBSERVATION_INVALID')
    command = observation['command']
    keys = {'command_id', 'state', 'command_action', 'task_id', 'job_id', 'runtime_id', 'browser_session_id'}
    if (not isinstance(command, dict) or set(command) != keys or any(not command[key] for key in keys)
            or command['state'] != 'BATCH_TRANSLATE_EXECUTE' or command['command_action'] != 'translate_editor_content'
            or (command_context is not None and (command_context.get('mode') != 'batch_draft_save'
                or any(command_context.get(key) != command[key] for key in keys)))):
        raise ValueError('TRANSLATION_COMMAND_CONTEXT_INVALID')
    page = urlsplit(observation['page_url'])
    from urllib.parse import parse_qs
    if (observation['execution_payload_hash'] != payload['payload_hash'] or observation['target_identity'] != target_identity
            or page.scheme != 'https' or page.netloc != 'www.dianxiaomi.com' or page.path != '/web/smt/edit'
            or parse_qs(page.query).get('id') != [payload['product_id']]
            or not isinstance(observation['shop_id'], str) or not observation['shop_id'].isdecimal()
            or not isinstance(observation['wholesale_command_id'], str) or not observation['wholesale_command_id']
            or observation['wholesale_command_id'] == command['command_id']):
        raise ValueError('TRANSLATION_IDENTITY_OR_PREDECESSOR_INVALID')
    started = parse_strict_utc_timestamp(observation['started_at'], field='translation start')
    completed = parse_strict_utc_timestamp(observation['completed_at'], field='translation completion')
    if completed < started:
        raise ValueError('TRANSLATION_TIMESTAMP_ORDER_INVALID')
    validate_native_translation_surface(observation['surface'], payload['editor_actions']['translation'])
    validate_native_translation_values(payload, observation['before'], observation['after'], observation['network'])
    auth = observation['mutation_authorization']
    if (not isinstance(auth, dict) or auth.get('ok') is not True or auth.get('executed') is not True
            or auth.get('mutation_action') != 'translate_language_click' or auth.get('mutation_status') != 'DISPATCHED'
            or auth.get('command_id') != command['command_id'] or not isinstance(auth.get('mutation_id'), str)
            or not auth['mutation_id']):
        raise ValueError('TRANSLATION_DISPATCH_UNPROVEN')
    ref = observation['evidence_ref']
    if (not isinstance(ref, dict) or set(ref) != {'path', 'sha256', 'size'}
            or not isinstance(ref['path'], str) or not ref['path'] or type(ref['size']) is not int or ref['size'] <= 0
            or re.fullmatch(r'[0-9A-Fa-f]{64}', str(ref['sha256'])) is None):
        raise ValueError('TRANSLATION_SCREENSHOT_UNPROVEN')
    return deepcopy(observation)


def validate_translation_wholesale_source(observation, predecessor, *, command, browser_session_id):
    """Bind the translation to the actual preceding wholesale command/result."""
    from src.execution.e3_authority_contract import parse_strict_utc_timestamp

    prior_command = predecessor.get('browser_agent_command', {})
    prior_result = predecessor.get('action_result', {})
    wholesale = prior_result.get('evidence', {}).get('observations', {}).get('wholesale_observation', {})
    expected = {key: prior_command.get(key) for key in ('command_id', 'action', 'state', 'task_id', 'job_id', 'runtime_id')}
    expected['browser_session_id'] = browser_session_id
    current = {key: command.get(key) for key in ('command_id', 'state', 'task_id', 'job_id', 'runtime_id')}
    current.update(command_action=command.get('action'), browser_session_id=browser_session_id)
    if (prior_command.get('state') != 'BATCH_WHOLESALE_FILL' or prior_command.get('action') != 'validate_editor_wholesale'
            or prior_command.get('execution_mode') != 'batch_draft_save' or prior_result.get('ok') is not True
            or prior_result.get('attempted_state') != prior_command['state'] or prior_result.get('action') != prior_command['action']
            or not prior_command.get('command_id') or prior_command['command_id'] == command.get('command_id')
            or command.get('state') != 'BATCH_TRANSLATE_EXECUTE' or command.get('action') != 'translate_editor_content'
            or command.get('execution_mode') != 'batch_draft_save'
            or observation.get('command') != current or wholesale.get('command') != expected
            or observation.get('wholesale_command_id') != prior_command['command_id']
            or any(prior_command.get(key) != command.get(key) for key in ('task_id', 'job_id', 'runtime_id'))
            or prior_result.get('page_identity', {}).get('browser_session_id') != browser_session_id
            or wholesale.get('page_url') != observation.get('page_url')
            or wholesale.get('target_identity') != observation.get('target_identity')
            or wholesale.get('execution_payload_hash') != observation.get('execution_payload_hash')
            or prior_command.get('params', {}).get('defaults') != command.get('params', {}).get('defaults')
            or prior_command.get('params', {}).get('shop_id') != observation.get('shop_id')
            or command.get('params', {}).get('shop_id') != observation.get('shop_id')):
        raise ValueError('TRANSLATION_WHOLESALE_SOURCE_DRIFT')
    if parse_strict_utc_timestamp(wholesale['completed_at'], field='wholesale completed_at') > parse_strict_utc_timestamp(
            observation['started_at'], field='translation started_at'):
        raise ValueError('TRANSLATION_WHOLESALE_SOURCE_ORDER_INVALID')


def build_editor_translation_receipt(observation, payload):
    from src.execution.canonical_receipt import ContentFinalizeReceipt, FieldReadback, ReceiptPhase

    fields, owners = native_translation_fields(payload)
    receipt = ContentFinalizeReceipt(phase=ReceiptPhase.CONTENT_FINALIZE_TRANSLATION,
        action_grant_id=observation['mutation_authorization']['mutation_id'], result_ok=True,
        started_at=observation['started_at'], completed_at=observation['completed_at'],
        field_readbacks=[FieldReadback(field_key=field['field_key'], field_label=field['ui_label_zh'],
            source='visible_production_runtime:native_translation', before_value=deepcopy(observation['before'][field['field_key']]),
            after_value=deepcopy(observation['after'][field['field_key']]), readback_proven=True,
            timestamp=observation['completed_at']) for field in fields if field['field_key'] in owners])
    digest = receipt.finalize()
    return {'canonical_receipt': receipt.to_dict(), 'receipt_sha256': digest}


class TranslateError(StrEnum):
    """翻译错误类型"""

    TRANSLATION_FAILED = "translation_failed"
    TIMEOUT = "timeout"
    NO_CHANGES = "no_changes"
    DISPATCH_UNCERTAIN = "dispatch_uncertain"
    FIELD_MISSING = "field_missing"


@dataclass
class TranslateResult:
    """翻译结果 (real adapter with full evidence)."""

    success: bool
    translated_fields: int = 0
    field_changes: dict[str, dict[str, str]] = field(default_factory=dict)
    error_type: TranslateError | None = None
    error_message: str | None = None
    dispatch_state: str = "unknown"
    evidence: dict[str, Any] = field(default_factory=dict)


class BatchTranslator:
    """Real one-click translation adapter for DXM batch edit workflow.

    Translates: title, attributes, description_pc, description_mobile, custom_name
    Records before/after values for every field.
    """

    DIRECTION_MAP = {
        "zh_en": ("中文", "英文"),
        "en_zh": ("英文", "中文"),
    }

    TRANSLATE_TYPE_MAP = {
        "normal": "普通翻译",
        "ai": "AI智能翻译",
    }

    def __init__(self, dxm_client: Any | None = None):
        self._dxm_client = dxm_client
        self._selector_profile = {
            "translate_btn": "[data-testid='translate-btn']",
            "translate_modal": "[data-testid='translate-modal']",
            "translate_type_normal": "[data-testid='translate-type-normal']",
            "translate_type_ai": "[data-testid='translate-type-ai']",
            "direction_zh_en": "[data-testid='direction-zh-en']",
            "direction_en_zh": "[data-testid='direction-en-zh']",
            "translate_confirm": "[data-testid='translate-confirm-btn']",
            "translate_cancel": "[data-testid='translate-cancel-btn']",
            "translate_loading": "[data-testid='translating']",
            "translate_success": "[data-testid='translate-complete']",
            "translate_error": "[data-testid='translate-error']",
            "field_title": "[data-testid='field-title'] input",
            "field_description_pc": "[data-testid='field-desc-pc'] textarea",
            "field_description_mobile": "[data-testid='field-desc-mobile'] textarea",
            "field_custom_name": "[data-testid='field-custom-name'] input",
            "field_attributes": "[data-testid='attribute-item']",
        }

    async def execute(
        self,
        page: Any,
        config: AutoTranslateConfig,
        ctx: dict[str, Any],
    ) -> TranslateResult:
        """Execute the translation pipeline.

        Args:
            page: Playwright page object
            config: AutoTranslateConfig with enabled, translate_type, direction, apply_to
            ctx: execution context with product_id, shop_id, field values

        Returns:
            TranslateResult with full evidence
        """
        if not config.enabled:
            return TranslateResult(
                success=False,
                translated_fields=0,
                error_type=TranslateError.FIELD_MISSING,
                error_message="翻译功能未启用，本步骤被跳过而非完成",
                dispatch_state="skipped",
                evidence={"skipped_reason": "config.enabled=False"},
            )

        product_id = ctx.get("product_id", "unknown")
        apply_to = config.apply_to or ["title", "attributes", "description_pc"]

        before_values = await self._capture_field_values(page, apply_to)

        modal_opened = await self._open_translate_modal(page, config)
        if not modal_opened.get("opened"):
            return TranslateResult(
                success=False,
                error_type=TranslateError.TRANSLATION_FAILED,
                error_message=modal_opened.get("error", "无法打开翻译弹窗"),
                dispatch_state="unknown",
                evidence={"modal_opened": modal_opened, "before_values": before_values},
            )

        confirmed = await self._configure_and_confirm(page, config)
        if not confirmed.get("confirmed"):
            return TranslateResult(
                success=False,
                error_type=TranslateError.TRANSLATION_FAILED,
                error_message=confirmed.get("error", "无法确认翻译"),
                dispatch_state="unknown",
                evidence={"confirmed": confirmed, "before_values": before_values},
            )

        completion_result = await self._wait_translation_complete(page)
        if not completion_result.get("completed"):
            return TranslateResult(
                success=False,
                error_type=completion_result.get("error_type", TranslateError.TIMEOUT),
                error_message=completion_result.get("error", "翻译超时"),
                dispatch_state="unknown",
                evidence={"completion_result": completion_result, "before_values": before_values},
            )

        after_values = await self._capture_field_values(page, apply_to)

        field_changes = self._compute_field_changes(before_values, after_values, apply_to)
        translated_count = len(field_changes)

        if translated_count == 0:
            return TranslateResult(
                success=True,
                translated_fields=0,
                field_changes={},
                dispatch_state="success",
                evidence={
                    "product_id": product_id,
                    "before_values": before_values,
                    "after_values": after_values,
                    "note": "no fields changed after translation",
                },
            )

        return TranslateResult(
            success=True,
            translated_fields=translated_count,
            field_changes=field_changes,
            dispatch_state="success",
            evidence={
                "product_id": product_id,
                "before_values": before_values,
                "after_values": after_values,
                "completion_result": completion_result,
            },
        )

    async def _open_translate_modal(
        self,
        page: Any,
        config: AutoTranslateConfig,
    ) -> dict[str, Any]:
        """Open the translate modal."""
        try:
            btn = await page.query_selector(self._selector_profile["translate_btn"])
            if not btn:
                return {"opened": False, "error": "翻译按钮未找到"}

            await btn.click()
            await asyncio.sleep(1)

            modal = await page.query_selector(self._selector_profile["translate_modal"])
            if not modal:
                return {"opened": False, "error": "翻译弹窗未出现"}

            return {"opened": True, "modal_visible": True}
        except Exception as exc:
            return {"opened": False, "error": str(exc)}

    async def _configure_and_confirm(
        self,
        page: Any,
        config: AutoTranslateConfig,
    ) -> dict[str, Any]:
        """Configure translate type and direction, then confirm."""
        try:
            translate_type = getattr(config, "translate_type", "normal")
            if translate_type == "ai":
                type_selector = self._selector_profile["translate_type_ai"]
            else:
                type_selector = self._selector_profile["translate_type_normal"]

            type_btn = await page.query_selector(type_selector)
            if type_btn:
                await type_btn.click()
                await asyncio.sleep(0.5)

            direction = getattr(config, "direction", "zh_en")
            if direction == "en_zh":
                dir_selector = self._selector_profile["direction_en_zh"]
            else:
                dir_selector = self._selector_profile["direction_zh_en"]

            dir_btn = await page.query_selector(dir_selector)
            if dir_btn:
                await dir_btn.click()
                await asyncio.sleep(0.5)

            confirm_btn = await page.query_selector(self._selector_profile["translate_confirm"])
            if not confirm_btn:
                return {"confirmed": False, "error": "翻译确认按钮未找到"}

            await confirm_btn.click()
            return {"confirmed": True}
        except Exception as exc:
            return {"confirmed": False, "error": str(exc)}

    async def _wait_translation_complete(self, page: Any, timeout: int = 120) -> dict[str, Any]:
        """Wait for translation to complete."""
        elapsed = 0
        interval = 3

        while elapsed < timeout:
            await asyncio.sleep(interval)
            elapsed += interval

            try:
                error_elem = await page.query_selector(self._selector_profile["translate_error"])
                if error_elem:
                    error_text = await error_elem.inner_text()
                    return {
                        "completed": False,
                        "error_type": TranslateError.TRANSLATION_FAILED,
                        "error": f"翻译失败：{error_text}",
                    }

                success_elem = await page.query_selector(self._selector_profile["translate_success"])
                if success_elem:
                    return {"completed": True, "state": "success"}

                loading_elem = await page.query_selector(self._selector_profile["translate_loading"])
                if not loading_elem:
                    any_modal = await page.query_selector(self._selector_profile["translate_modal"])
                    if not any_modal:
                        return {"completed": True, "state": "auto_closed"}

            except Exception:
                pass

        return {
            "completed": False,
            "error_type": TranslateError.TIMEOUT,
            "error": f"翻译超时（等待 {timeout} 秒）",
        }

    async def _capture_field_values(
        self,
        page: Any,
        apply_to: list[str],
    ) -> dict[str, str]:
        """Capture field values before/after translation."""
        result = {}

        if "title" in apply_to:
            try:
                elem = await page.query_selector(self._selector_profile["field_title"])
                if elem:
                    result["title"] = await elem.input_value() or await elem.inner_text() or ""
                else:
                    result["title"] = ""
            except Exception:
                result["title"] = ""

        if "description_pc" in apply_to:
            try:
                elem = await page.query_selector(self._selector_profile["field_description_pc"])
                if elem:
                    result["description_pc"] = await elem.input_value() or await elem.inner_text() or ""
                else:
                    result["description_pc"] = ""
            except Exception:
                result["description_pc"] = ""

        if "description_mobile" in apply_to:
            try:
                elem = await page.query_selector(self._selector_profile["field_description_mobile"])
                if elem:
                    result["description_mobile"] = await elem.input_value() or await elem.inner_text() or ""
                else:
                    result["description_mobile"] = ""
            except Exception:
                result["description_mobile"] = ""

        if "custom_name" in apply_to:
            try:
                elem = await page.query_selector(self._selector_profile["field_custom_name"])
                if elem:
                    result["custom_name"] = await elem.input_value() or await elem.inner_text() or ""
                else:
                    result["custom_name"] = ""
            except Exception:
                result["custom_name"] = ""

        if "attributes" in apply_to:
            try:
                attr_elems = await page.query_selector_all(self._selector_profile["field_attributes"])
                attr_values = []
                for elem in attr_elems:
                    val = await elem.inner_text() or ""
                    if val.strip():
                        attr_values.append(val.strip())
                result["attributes"] = "\n".join(attr_values)
            except Exception:
                result["attributes"] = ""

        return result

    def _compute_field_changes(
        self,
        before: dict[str, str],
        after: dict[str, str],
        apply_to: list[str],
    ) -> dict[str, dict[str, str]]:
        """Compute field changes between before and after values."""
        changes = {}
        for field_name in apply_to:
            before_val = before.get(field_name, "")
            after_val = after.get(field_name, "")
            if before_val != after_val:
                changes[field_name] = {
                    "before": before_val,
                    "after": after_val,
                }
        return changes
