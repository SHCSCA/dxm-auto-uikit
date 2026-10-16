"""冻结字段到实际控件的私有诊断清单；不签发填写、恢复或能力授权。"""

import math
import re
from copy import deepcopy
from urllib.parse import parse_qs, urlsplit

from src.batch_edit.plan_schema_contract import active_required_fields, normalize_wire_value
from src.batch_edit.scope_contract import canonical_sha256
from src.core.config_bus import get_config_bus
from src.execution.editor_control_inventory_script import EDITOR_CONTROL_INVENTORY_SCRIPT
from src.services.dxm_editor_model import EDITOR_SECTIONS
from src.services.structured_logging import get_logger, log_event, log_exception


SCHEMA = 'dxm.editor_control_inventory.v1'
SECTION_CODES = ('basic_info', 'dxm_info', 'attribute_info', 'product_info', 'regional_pricing',
                 'description_info', 'packaging_info', 'template_main', 'template_tax', 'compliance_info', 'other_info')
_LOGGER = get_logger('editor.control_inventory')
_COMPONENT_FIELDS = frozenset({'detail', 'mobileDetail', 'hsCode', 'aeopNationalQuoteConfiguration',
    'aeopQualificationStructList', 'aeopAeProductSKUs', 'imageURLs', 'marketImg1', 'marketImg2', 'videoUrl'})


def _require(condition, code):
    if not condition:
        raise ValueError(code)


def _primitive_matches(value, kind):
    return ((kind == 'string' and isinstance(value, str)) or (kind == 'boolean' and type(value) is bool)
        or (kind == 'integer' and type(value) is int)
        or (kind == 'number' and type(value) in {int, float} and math.isfinite(value)))


def _prepare(payload, category_schema, limit):
    _require(isinstance(payload, dict) and payload.get('schema') == 'dxm.batch_draft_save.execution_payload.v1'
        and payload.get('execution_path') == 'B' and payload.get('save_stage', 'SAVE1') == 'SAVE1'
        and canonical_sha256({key: value for key, value in payload.items() if key != 'payload_hash'}) == payload.get('payload_hash'),
        'INVENTORY_FROZEN_PAYLOAD_INVALID')
    _require(isinstance(category_schema, dict) and isinstance(category_schema.get('normalized_schema'), dict), 'INVENTORY_FROZEN_SCHEMA_REQUIRED')
    schema = category_schema['normalized_schema']
    _require(canonical_sha256(schema) == category_schema.get('schema_hash') == payload.get('category_schema_hash'), 'INVENTORY_FROZEN_SCHEMA_DRIFT')
    properties, fields = schema.get('properties'), payload.get('fields')
    _require(isinstance(properties, dict) and isinstance(fields, list) and 0 < len(fields) <= limit
        and isinstance(payload.get('unresolved_fields'), list), 'INVENTORY_FIELD_COVERAGE_INVALID')
    descriptors, seen, bindings = [], set(), set()
    for field in fields:
        _require(isinstance(field, dict), 'INVENTORY_FIELD_INVALID')
        key, binding = field.get('field_key'), field.get('ui_binding')
        _require(isinstance(key, str) and re.fullmatch('[A-Za-z][A-Za-z0-9_]*', key) is not None
            and key not in seen and binding not in bindings and isinstance(binding, str)
            and (binding == 'dxm_editor:' + key or re.fullmatch('dxm_attribute:[1-9][0-9]{0,19}', binding) is not None)
            and field.get('category_schema_path') == '$.properties.' + key and 'resolved_value' in field,
            'INVENTORY_FROZEN_BINDING_INVALID')
        definition = properties.get(key)
        _require(isinstance(definition, dict) and definition.get('ui_binding') == binding, 'INVENTORY_FROZEN_BINDING_DRIFT')
        seen.add(key); bindings.add(binding)
        descriptors.append({'field_key': key, 'ui_binding': binding, 'section': definition.get('ui_section')})
    return schema, descriptors


def _row(field, definition, raw):
    result = {**deepcopy(raw), 'target_value': deepcopy(field['resolved_value']),
        'section': definition.get('ui_section'), 'original_value': None, 'original_normalized': False,
        'recovery_boundary': 'UNVERIFIED', 'executionAllowed': False}
    missing = result['missing']
    if result['section'] not in SECTION_CODES:
        missing.append('SECTION_SCHEMA_IDENTITY_UNKNOWN')
    if definition.get('type') not in {'string', 'number', 'integer', 'boolean', 'array', 'object'}:
        missing.append('FIELD_SCHEMA_TYPE_UNREVIEWED')
    if (field['field_key'] in _COMPONENT_FIELDS or definition.get('type') in {'array', 'object'}
            or definition.get('ui_control', 'input') not in {'input', 'textarea', 'select', 'checkbox'}):
        missing.append('STRUCTURED_CONTROL_BINDING_REQUIRED')
    if definition.get('readOnly') is True or definition.get('read_only') is True:
        missing.append('FROZEN_FIELD_READ_ONLY')
    if definition.get('type') in {'string', 'number', 'integer', 'boolean'} and not _primitive_matches(field['resolved_value'], definition['type']):
        missing.append('TARGET_SCHEMA_TYPE_UNPROVEN')
    if raw['value_observed'] and definition.get('type') in {'string', 'number', 'integer', 'boolean'}:
        try:
            original = normalize_wire_value(raw['raw_value'], definition, field_key=field['field_key'])
            _require(_primitive_matches(original, definition['type']), 'ORIGINAL_WIRE_TYPE_UNPROVEN')
            result['original_value'] = original
            result['original_normalized'] = True
        except Exception as exc:
            log_exception(_LOGGER, 'editor_inventory_wire_value_unproven', exc, field_key=field['field_key'])
            missing.append('ORIGINAL_WIRE_TYPE_UNPROVEN')
    options = raw.get('options')
    if options is not None:
        target = field['resolved_value']
        desired = target if isinstance(target, list) else [target]
        original = raw['raw_value'] if isinstance(raw['raw_value'], list) else [raw['raw_value']]
        if any(len([option for option in options if option['value'] == str(value) and not option['disabled']]) != 1 for value in [*desired, *original]):
            missing.append('TARGET_OR_ORIGINAL_OPTION_NOT_RESTORABLE')
    if raw['value_kind'] == 'checkbox_boolean' and definition.get('type') != 'boolean':
        missing.append('CONTROL_SCHEMA_TYPE_MISMATCH')
    if not missing and result['original_normalized']:
        result['recovery_boundary'] = 'NATIVE_PRIMITIVE_CANDIDATE_ONLY'
    return result


def collect_editor_control_inventory(page, execution_payload, category_schema):
    """只读双采样；完整冻结 Schema 必须由原快照提供，调用方数据不形成权威。"""
    result = {'schema': SCHEMA, 'collected': False, 'stable': False, 'fields': [], 'sections': [], 'templates': [],
        'missing': [], 'executionAllowed': False, 'capabilityCertified': False, 'required_fields_complete': False,
        'inputFreezeAllowed': False, 'write_attempted': False, 'coverage': 'frozen_fields_only'}
    navigations, listener_added, frame = [], False, None

    def navigated(observed):
        try:
            if observed is frame or observed is page.main_frame:
                navigations.append('main_frame_navigation')
        except Exception as exc:
            navigations.append('navigation_observation_failed')
            log_exception(_LOGGER, 'editor_inventory_navigation_observation_failed', exc)

    try:
        bus = get_config_bus()
        limits = {'max_options': bus.integer('DXM_EDITOR_INVENTORY_MAX_OPTIONS', 512, minimum=1, maximum=4096),
            'max_value_chars': bus.integer('DXM_EDITOR_INVENTORY_MAX_VALUE_CHARS', 65536, minimum=256, maximum=1048576)}
        max_fields = bus.integer('DXM_EDITOR_INVENTORY_MAX_FIELDS', 256, minimum=1, maximum=1024)
        payload, category = deepcopy(execution_payload), deepcopy(category_schema)
        schema, fields = _prepare(payload, category, max_fields)
        frame, url = page.main_frame, str(page.url)
        parts = urlsplit(url)
        _require(parts.scheme == 'https' and parts.netloc == 'www.dianxiaomi.com' and parts.path == '/web/smt/edit'
            and not parts.fragment and parse_qs(parts.query) == {'id': [str(payload['product_id'])]}, 'INVENTORY_PAGE_IDENTITY_INVALID')
        anchors = {item['code']: item['anchor'] for item in EDITOR_SECTIONS}
        sections = [{'code': code, 'anchor': anchors.get(code)} for code in SECTION_CODES]
        args = {'fields': fields, 'sections': sections, 'limits': limits}
        listener_added = True
        page.on('framenavigated', navigated)
        before = page.evaluate(EDITOR_CONTROL_INVENTORY_SCRIPT, args)
        after = page.evaluate(EDITOR_CONTROL_INVENTORY_SCRIPT, args)
        _require(not navigations and not page.is_closed() and frame is page.main_frame and url == str(page.url) and before == after,
            'INVENTORY_DOCUMENT_OR_READBACK_DRIFT')
        _require(isinstance(after, dict) and after.get('schema') == 'dxm.editor_control_dom.v1'
            and after.get('url') == url and after.get('collected') is True and after.get('missing') == []
            and after.get('root_count') == 1 and type(after.get('document_time_origin')) in {int, float}
            and math.isfinite(after['document_time_origin']) and after['document_time_origin'] > 0
            and isinstance(after.get('fields'), list) and len(after['fields']) == len(fields)
            and isinstance(after.get('sections'), list)
            and [(row['code'], row['anchor']) for row in after['sections']] == [(row['code'], row['anchor']) for row in sections],
            'INVENTORY_DOM_COLLECTION_INCOMPLETE')
        _require([row['field_key'] for row in after['fields']] == [field['field_key'] for field in fields], 'INVENTORY_DOM_FIELD_COVERAGE_DRIFT')
        result.update(collected=True, stable=True, execution_payload_sha256=payload['payload_hash'],
            category_schema_sha256=category['schema_hash'], page_url=url, document_time_origin=after['document_time_origin'])
        result['fields'] = [_row(field, schema['properties'][field['field_key']], raw) for field, raw in zip(payload['fields'], after['fields'])]
        for section in after['sections']:
            rows = [row for row in result['fields'] if row['section'] == section['code']]
            missing = []
            if not rows:
                missing.append('SECTION_FROZEN_COVERAGE_MISSING')
            if section['anchor'] is None:
                missing.append('SECTION_NATIVE_ANCHOR_UNREVIEWED')
            elif section['match_count'] != 1 or section['visible_count'] != 1:
                missing.append('SECTION_NOT_UNIQUE_VISIBLE')
            result['sections'].append({**section, 'field_keys': [row['field_key'] for row in rows], 'missing': missing,
                'state': 'MISSING' if missing else 'BLOCKED' if any(row['missing'] for row in rows) else 'OBSERVED_CANDIDATES'})
        targets = {field['field_key']: field['resolved_value'] for field in payload['fields']}
        result['unfrozen_required_fields'] = sorted(active_required_fields(schema, targets) - set(targets))
        if result['unfrozen_required_fields'] or payload['unresolved_fields']:
            result['missing'].append('FROZEN_REQUIRED_FIELD_COVERAGE_INCOMPLETE')
        refs = payload.get('dxm_template_refs', [])
        _require(isinstance(refs, list) and all(isinstance(ref, dict) for ref in refs), 'INVENTORY_TEMPLATE_REFERENCES_INVALID')
        result['templates'] = [{'frozen_reference': deepcopy(ref), 'application_state': 'UNOBSERVED',
            'missing': ['TEMPLATE_APPLICATION_NOT_PROVEN']} for ref in refs]
        if not refs:
            result['missing'].append('FROZEN_TEMPLATE_REFERENCE_COVERAGE_UNPROVEN')
        result['missing'].extend(['TEMPLATE_APPLICATION_NOT_PROVEN', 'FULL_FILL_EXECUTION_SOURCE_NOT_BOUND'])
        result['missing'] = sorted(set(result['missing'] + [code for row in [*result['fields'], *result['sections']] for code in row['missing']]))
        result['inventory_sha256'] = canonical_sha256(result)
        log_event(_LOGGER, 'editor_control_inventory_collected', level='WARNING', field_count=len(result['fields']), missing_codes=result['missing'])
    except Exception as exc:
        log_exception(_LOGGER, 'editor_control_inventory_failed', exc)
        result.update(collected=False, stable=False, fields=[], sections=[], templates=[], missing=['EDITOR_CONTROL_INVENTORY_UNVERIFIED'])
        result.pop('inventory_sha256', None)
    finally:
        if listener_added:
            try:
                page.remove_listener('framenavigated', navigated)
                _require(not page.is_closed() and frame is page.main_frame and url == str(page.url), 'INVENTORY_DOCUMENT_OR_READBACK_DRIFT')
            except Exception as exc:
                log_exception(_LOGGER, 'editor_inventory_listener_cleanup_failed', exc)
                result.update(collected=False, stable=False, fields=[], sections=[], templates=[], missing=['INVENTORY_LISTENER_CLEANUP_UNPROVEN'])
                result.pop('inventory_sha256', None)
        if navigations:
            log_event(_LOGGER, 'editor_inventory_document_changed', level='WARNING')
            result.update(collected=False, stable=False, fields=[], sections=[], templates=[], missing=['INVENTORY_DOCUMENT_OR_READBACK_DRIFT'])
            result.pop('inventory_sha256', None)
    return result


def editor_control_inventory_summary(value):
    """公共投影仅允许摘要哈希和缺证码，不导出原值、目标值或页面业务内容。"""
    summary = {'schema': SCHEMA + '.summary', 'inventory_sha256': None, 'execution_payload_sha256': None,
        'category_schema_sha256': None, 'collected': False, 'stable': False, 'field_count': 0, 'section_count': 0,
        'missing': ['INVENTORY_PUBLIC_SUMMARY_UNVERIFIED'], 'executionAllowed': False,
        'capabilityCertified': False, 'inputFreezeAllowed': False, 'required_fields_complete': False}
    try:
        _require(isinstance(value, dict) and all(isinstance(value.get(key, []), list) for key in ('fields', 'sections', 'missing')),
            'INVENTORY_PUBLIC_SUMMARY_INVALID')
        for key in ('inventory_sha256', 'execution_payload_sha256', 'category_schema_sha256'):
            digest = value.get(key)
            summary[key] = digest if isinstance(digest, str) and re.fullmatch('[a-fA-F0-9]{64}', digest) else None
        summary.update(collected=value.get('collected') is True, stable=value.get('stable') is True,
            field_count=len(value.get('fields', [])), section_count=len(value.get('sections', [])),
            missing=sorted({code for code in value.get('missing', []) if isinstance(code, str) and re.fullmatch('[A-Z][A-Z0-9_]{0,119}', code)}))
    except Exception as exc:
        log_exception(_LOGGER, 'editor_inventory_summary_failed', exc)
    return summary
