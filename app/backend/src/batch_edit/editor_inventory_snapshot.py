"""复核私有控件清单与原冻结字段，不把诊断候选提升为恢复或填写资格。"""

import math
import re
from copy import deepcopy

from src.batch_edit.plan_schema_contract import active_required_fields
from src.batch_edit.scope_contract import canonical_sha256
from src.execution.editor_control_inventory import SECTION_CODES, _row
from src.services.dxm_editor_model import EDITOR_SECTIONS


FALSE_FLAGS = ('executionAllowed', 'capabilityCertified', 'required_fields_complete', 'inputFreezeAllowed', 'write_attempted')
RAW_KEYS = {'field_key', 'ui_binding', 'match_count', 'control', 'raw_value', 'value_observed',
            'value_kind', 'options', 'section_bound', 'missing'}
DERIVED_CODES = frozenset({'SECTION_SCHEMA_IDENTITY_UNKNOWN', 'FIELD_SCHEMA_TYPE_UNREVIEWED',
    'STRUCTURED_CONTROL_BINDING_REQUIRED', 'FROZEN_FIELD_READ_ONLY', 'TARGET_SCHEMA_TYPE_UNPROVEN',
    'ORIGINAL_WIRE_TYPE_UNPROVEN', 'TARGET_OR_ORIGINAL_OPTION_NOT_RESTORABLE', 'CONTROL_SCHEMA_TYPE_MISMATCH'})


def require(condition, code):
    if not condition:
        raise ValueError(code)


def codes(value):
    return (isinstance(value, list) and len(set(value)) == len(value)
        and all(isinstance(code, str) and re.fullmatch('[A-Z][A-Z0-9_]{0,119}', code) for code in value))


def _native_facts(row, field):
    control, missing = row['control'], set(row['missing'])
    empty = row['raw_value'] is None and row['value_observed'] is False
    if row['match_count'] != 1:
        code = 'CONTROL_IDENTITY_AMBIGUOUS' if row['match_count'] else 'CONTROL_NATIVE_IDENTITY_MISSING'
        require(code in missing and control is None and empty and row['value_kind'] is None
            and row['options'] is None and row['section_bound'] is False, 'INVENTORY_NATIVE_MATCH_FACTS_DRIFT')
        return
    require(control is not None and all(control[key] is None or isinstance(control[key], str) for key in ('id', 'name', 'type')),
        'INVENTORY_NATIVE_CONTROL_INVALID')
    key = field['field_key']; identities = {key, 'form_item_'+key}
    if key == 'title':
        identities.update({'subject', 'form_item_subject'})
    require(control['id'] in identities or control['name'] == key or key == 'title' and control['name'] == 'subject',
        'INVENTORY_NATIVE_IDENTITY_DRIFT')
    tag, kind = control['tag'], (control['type'] or 'text').lower()
    require(isinstance(tag, str) and re.fullmatch('[a-z][a-z0-9-]*', tag)
        and (tag in {'input', 'textarea', 'select'} or control['content_editable'] is True),
        'INVENTORY_NATIVE_TAG_UNREVIEWED')
    if not control['visible']:
        require('CONTROL_NOT_VISIBLE' in missing and empty and row['value_kind'] is None
            and row['options'] is None and row['section_bound'] is False, 'INVENTORY_NATIVE_VISIBILITY_DRIFT')
        return
    for flag, code in (('disabled', 'CONTROL_DISABLED'), ('read_only', 'CONTROL_READ_ONLY')):
        require(not control[flag] or code in missing, 'INVENTORY_NATIVE_BLOCKED_FACTS_DRIFT')
    # 绑定只能消费实际布尔事实；不通过字段 id 推断 DOM 父子关系。
    require(row['section_bound'] or 'SECTION_CONTROL_BOUNDARY_UNPROVEN' in missing, 'INVENTORY_NATIVE_SECTION_FACTS_DRIFT')
    if tag == 'input' and kind not in {'checkbox', 'text', 'search', 'url', 'tel', 'email', 'number'}:
        require('CONTROL_TYPE_UNREVIEWED' in missing and empty and row['value_kind'] is None and row['options'] is None,
            'INVENTORY_NATIVE_TYPE_FACTS_DRIFT')
        return
    if tag == 'select' and row['options'] is None:
        require('CONTROL_OPTION_LIMIT_EXCEEDED' in missing and empty and row['value_kind'] is None,
            'INVENTORY_NATIVE_OPTION_LIMIT_DRIFT')
        return
    if tag not in {'input', 'textarea', 'select'} and row['value_kind'] is None:
        require('RICH_CONTENT_RESTORE_UNPROVEN' in missing and empty and row['options'] is None,
            'INVENTORY_NATIVE_RICH_CONTENT_DRIFT')
        return
    expected = ('checkbox_boolean' if kind == 'checkbox' else 'native_input_value') if tag == 'input' else (
        'native_textarea_value' if tag == 'textarea' else 'plain_contenteditable_text')
    if tag == 'select':
        require(row['value_kind'] in {'native_select_value', 'native_multi_select_values'}, 'INVENTORY_NATIVE_VALUE_KIND_DRIFT')
        values = [option['value'] for option in row['options']]
        require(len(values) == len(set(values)) or 'OPTION_VALUE_IDENTITY_AMBIGUOUS' in missing,
            'INVENTORY_NATIVE_OPTION_IDENTITY_DRIFT')
    else:
        require(row['value_kind'] == expected and row['options'] is None, 'INVENTORY_NATIVE_VALUE_KIND_DRIFT')
    if not row['value_observed']:
        require('CONTROL_VALUE_LIMIT_EXCEEDED' in missing and row['raw_value'] is None, 'INVENTORY_NATIVE_UNOBSERVED_VALUE_UNEXPLAINED')
        return
    value = row['raw_value']
    if tag == 'select':
        selected = [option['value'] for option in row['options'] if option['selected']]
        expected = selected if row['value_kind'] == 'native_multi_select_values' else selected[0] if selected else ''
        require((row['value_kind'] != 'native_select_value' or len(selected) <= 1)
            and canonical_sha256(value) == canonical_sha256(expected), 'INVENTORY_NATIVE_SELECTED_VALUE_DRIFT')
    else:
        require(type(value) is bool if row['value_kind'] == 'checkbox_boolean' else isinstance(value, str),
            'INVENTORY_NATIVE_VALUE_TYPE_DRIFT')


def _field(row, field, definition):
    require(isinstance(row, dict) and set(row) == RAW_KEYS | {'target_value', 'section', 'original_value',
        'original_normalized', 'recovery_boundary', 'executionAllowed'} and codes(row['missing']), 'INVENTORY_ROW_SHAPE_INVALID')
    require(type(row['match_count']) is int and row['match_count'] >= 0
        and type(row['value_observed']) is bool and type(row['section_bound']) is bool
        and row['executionAllowed'] is False and row['value_kind'] in {None, 'checkbox_boolean', 'native_input_value',
            'native_textarea_value', 'native_multi_select_values', 'native_select_value', 'plain_contenteditable_text'},
        'INVENTORY_ROW_FLAGS_INVALID')
    control = row['control']
    require(control is None or isinstance(control, dict) and set(control) == {'tag', 'id', 'name', 'type',
        'visible', 'disabled', 'read_only', 'content_editable'} and all(type(control[key]) is bool
        for key in ('visible', 'disabled', 'read_only', 'content_editable')), 'INVENTORY_CONTROL_SHAPE_INVALID')
    require(not row['value_observed'] or control is not None and row['match_count'] == 1 and control['visible'] is True,
        'INVENTORY_CONTROL_OBSERVATION_INVALID')
    options = row['options']
    require(options is None or isinstance(options, list) and all(isinstance(option, dict)
        and set(option) == {'value', 'selected', 'disabled'} and isinstance(option['value'], str)
        and type(option['selected']) is bool and type(option['disabled']) is bool for option in options),
        'INVENTORY_OPTIONS_INVALID')
    require(row['field_key'] == field['field_key'] and row['ui_binding'] == field['ui_binding'], 'INVENTORY_FIELD_BINDING_DRIFT')
    _native_facts(row, field)
    # 只复用既有纯派生逻辑；原始缺项保留，不能从候选原值推导可恢复。
    raw = {key: deepcopy(row[key]) for key in RAW_KEYS}
    raw['missing'] = [code for code in raw['missing'] if code not in DERIVED_CODES]
    expected = _row(field, definition, raw)
    require(canonical_sha256(expected) == canonical_sha256(row), 'INVENTORY_FIELD_DERIVATION_DRIFT')


def validate_inventory(value, *, payload, category_schema):
    require(isinstance(value, dict) and set(value) == {'schema', 'collected', 'stable', 'fields', 'sections', 'templates',
        'missing', *FALSE_FLAGS, 'coverage', 'execution_payload_sha256', 'category_schema_sha256', 'page_url',
        'document_time_origin', 'unfrozen_required_fields', 'inventory_sha256'}, 'INVENTORY_SNAPSHOT_SHAPE_INVALID')
    require(value['schema'] == 'dxm.editor_control_inventory.v1' and value['collected'] is True and value['stable'] is True
        and all(value[key] is False for key in FALSE_FLAGS) and value['coverage'] == 'frozen_fields_only'
        and codes(value['missing']) and value['inventory_sha256'] == canonical_sha256(
            {key: item for key, item in value.items() if key != 'inventory_sha256'}), 'INVENTORY_SNAPSHOT_FLAGS_OR_HASH_INVALID')
    require(value['execution_payload_sha256'] == payload['payload_hash']
        and value['category_schema_sha256'] == category_schema['schema_hash'] == payload['category_schema_hash'],
        'INVENTORY_SNAPSHOT_FROZEN_HASH_DRIFT')
    origin = value['document_time_origin']
    require(type(origin) in {int, float} and math.isfinite(origin) and origin > 0, 'INVENTORY_DOCUMENT_ORIGIN_INVALID')
    fields, schema = payload['fields'], category_schema['normalized_schema']
    require(isinstance(value['fields'], list) and len(value['fields']) == len(fields), 'INVENTORY_FIELD_COVERAGE_DRIFT')
    for row, field in zip(value['fields'], fields):
        _field(row, field, schema['properties'][field['field_key']])
    require(isinstance(value['sections'], list) and len(value['sections']) == len(SECTION_CODES), 'INVENTORY_SECTION_COVERAGE_DRIFT')
    anchors = {section['code']: section['anchor'] for section in EDITOR_SECTIONS}
    for section, code in zip(value['sections'], SECTION_CODES):
        require(isinstance(section, dict) and set(section) == {'code', 'anchor', 'match_count', 'visible_count',
            'field_keys', 'missing', 'state'} and section['code'] == code and section['anchor'] == anchors.get(code)
            and codes(section['missing']) and type(section['match_count']) is int and section['match_count'] >= 0
            and type(section['visible_count']) is int and 0 <= section['visible_count'] <= section['match_count'],
            'INVENTORY_SECTION_BINDING_DRIFT')
        rows = [row for row in value['fields'] if row['section'] == code]
        missing = ([] if rows else ['SECTION_FROZEN_COVERAGE_MISSING'])
        if section['anchor'] is None:
            missing.append('SECTION_NATIVE_ANCHOR_UNREVIEWED')
        elif section['match_count'] != 1 or section['visible_count'] != 1:
            missing.append('SECTION_NOT_UNIQUE_VISIBLE')
        state = 'MISSING' if missing else 'BLOCKED' if any(row['missing'] for row in rows) else 'OBSERVED_CANDIDATES'
        require(section['field_keys'] == [row['field_key'] for row in rows] and section['missing'] == missing
            and section['state'] == state, 'INVENTORY_SECTION_DERIVATION_DRIFT')
    refs = payload.get('dxm_template_refs', [])
    require(value['templates'] == [{'frozen_reference': ref, 'application_state': 'UNOBSERVED',
        'missing': ['TEMPLATE_APPLICATION_NOT_PROVEN']} for ref in refs], 'INVENTORY_TEMPLATE_COVERAGE_DRIFT')
    targets = {field['field_key']: field['resolved_value'] for field in fields}
    unfrozen = sorted(active_required_fields(schema, targets) - set(targets))
    missing = ['TEMPLATE_APPLICATION_NOT_PROVEN', 'FULL_FILL_EXECUTION_SOURCE_NOT_BOUND']
    if unfrozen or payload['unresolved_fields']:
        missing.append('FROZEN_REQUIRED_FIELD_COVERAGE_INCOMPLETE')
    if not refs:
        missing.append('FROZEN_TEMPLATE_REFERENCE_COVERAGE_UNPROVEN')
    missing += [code for row in [*value['fields'], *value['sections']] for code in row['missing']]
    require(value['unfrozen_required_fields'] == unfrozen and value['missing'] == sorted(set(missing)),
        'INVENTORY_MISSING_DIAGNOSTICS_DRIFT')
    return deepcopy(value)
