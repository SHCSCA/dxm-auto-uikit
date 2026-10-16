"""重签不能隐藏原生身份、基础缺证或不可能的值；仍不授予恢复资格。"""

from copy import deepcopy

import pytest

from src.execution.editor_control_inventory import _row
from tests.test_editor_inventory_contract import observation_case, resign, validate


def rebuild(case, wrapper):
    inventory = wrapper['after']; field = case['payload']['fields'][0]
    row = inventory['fields'][0]
    raw = {key: deepcopy(row[key]) for key in ('field_key', 'ui_binding', 'match_count', 'control', 'raw_value',
        'value_observed', 'value_kind', 'options', 'section_bound', 'missing')}
    inventory['fields'][0] = _row(field, case['category_schema']['normalized_schema']['properties'][field['field_key']], raw)
    for section in inventory['sections']:
        rows = [row for row in inventory['fields'] if row['section'] == section['code']]
        section['state'] = 'MISSING' if section['missing'] else 'BLOCKED' if any(row['missing'] for row in rows) else 'OBSERVED_CANDIDATES'
    inventory['missing'] = sorted({'TEMPLATE_APPLICATION_NOT_PROVEN', 'FULL_FILL_EXECUTION_SOURCE_NOT_BOUND',
        *(code for row in [*inventory['fields'], *inventory['sections']] for code in row['missing'])})
    resign(wrapper)


@pytest.mark.parametrize('change', ['tag', 'identity', 'section', 'disabled', 'read_only', 'missing',
    'visible', 'checkbox_value', 'select_selection', 'text_value', 'unobserved_no_reason', 'wrong_kind', 'peer_combined', 'uppercase_tag'])
def test_self_consistent_resigned_native_facts_cannot_hide_missing_or_impossible_observations(observation_case, change):
    case = observation_case; wrapper = deepcopy(case['wrapper']); row = wrapper['after']['fields'][0]
    if change == 'tag':
        row['control']['tag'] = 'script'
    elif change == 'identity':
        row['control'].update(id='unrelated', name='unrelated')
    elif change == 'section':
        row['section_bound'] = False
    elif change in {'disabled', 'read_only'}:
        row['control'][change] = True
    elif change == 'missing':
        row.update(match_count=0, control=None, section_bound=False, value_observed=False, value_kind=None, raw_value=None)
    elif change == 'visible':
        row['control']['visible'] = False
        row.update(value_observed=False, value_kind=None, raw_value=None, section_bound=False)
    elif change == 'checkbox_value':
        row['control']['type'] = 'checkbox'; row.update(value_kind='checkbox_boolean', raw_value='yes')
    elif change == 'select_selection':
        row['control']['tag'] = 'select'
        row.update(value_kind='native_select_value', raw_value='missing-selection', options=[
            {'value': 'actual-selection', 'selected': True, 'disabled': False}])
    elif change == 'text_value':
        row['raw_value'] = 1
    elif change == 'unobserved_no_reason':
        row.update(value_observed=False, raw_value=None)
    elif change == 'wrong_kind':
        row['value_kind'] = 'native_textarea_value'
    elif change == 'uppercase_tag':
        row['control'].update(tag='DIV', content_editable=True); row['value_kind'] = 'plain_contenteditable_text'
    else:
        row['control'].update(tag='script', id='unrelated', name='unrelated', disabled=True, read_only=True)
        row['section_bound'] = False
    rebuild(case, wrapper)
    with pytest.raises(ValueError):
        validate(case, wrapper)


@pytest.mark.parametrize('attribute, code', [('disabled', 'CONTROL_DISABLED'), ('read_only', 'CONTROL_READ_ONLY'),
    ('section_bound', 'SECTION_CONTROL_BOUNDARY_UNPROVEN')])
def test_truthful_basic_missing_facts_stay_diagnostic_without_native_candidate(observation_case, attribute, code):
    case = observation_case; wrapper = deepcopy(case['wrapper']); row = wrapper['after']['fields'][0]
    if attribute == 'section_bound':
        row[attribute] = False
    else:
        row['control'][attribute] = True
    row['missing'].append(code); rebuild(case, wrapper)
    result = validate(case, wrapper)
    assert result['after']['fields'][0]['recovery_boundary'] == 'UNVERIFIED'
    assert result['after']['required_fields_complete'] is False


def test_title_subject_alias_is_native_identity_without_inventing_parent_binding(observation_case):
    case = observation_case; wrapper = deepcopy(case['wrapper'])
    wrapper['after']['fields'][0]['control'].update(id='form_item_subject', name='subject')
    rebuild(case, wrapper)
    assert validate(case, wrapper)['after']['executionAllowed'] is False


@pytest.mark.parametrize('kind', ['missing', 'ambiguous', 'invisible', 'unsupported_type', 'rich_content',
    'option_limit', 'value_limit', 'multi_select', 'single_select', 'plain_contenteditable'])
def test_actual_script_missing_and_native_value_paths_remain_diagnostic(observation_case, kind):
    case = observation_case; wrapper = deepcopy(case['wrapper']); row = wrapper['after']['fields'][0]
    if kind in {'missing', 'ambiguous', 'invisible', 'unsupported_type', 'rich_content', 'option_limit', 'value_limit'}:
        row.update(raw_value=None, value_observed=False, value_kind=None)
        if kind in {'missing', 'ambiguous'}:
            row.update(match_count=0 if kind == 'missing' else 2, control=None, section_bound=False,
                missing=['CONTROL_NATIVE_IDENTITY_MISSING' if kind == 'missing' else 'CONTROL_IDENTITY_AMBIGUOUS'])
        elif kind == 'invisible':
            row['control']['visible'] = False; row['section_bound'] = False; row['missing'] = ['CONTROL_NOT_VISIBLE']
        elif kind == 'unsupported_type':
            row['control']['type'] = 'file'; row['missing'] = ['CONTROL_TYPE_UNREVIEWED']
        elif kind == 'rich_content':
            row['control'].update(tag='div', content_editable=True); row['missing'] = ['RICH_CONTENT_RESTORE_UNPROVEN']
        elif kind == 'option_limit':
            row['control']['tag'] = 'select'; row['missing'] = ['CONTROL_OPTION_LIMIT_EXCEEDED']
        else:
            row['value_kind'] = 'native_input_value'; row['missing'] = ['CONTROL_VALUE_LIMIT_EXCEEDED']
    elif kind in {'multi_select', 'single_select'}:
        row['control'].update(tag='select', type=None)
        row['value_kind'] = 'native_multi_select_values' if kind == 'multi_select' else 'native_select_value'
        row['options'] = [{'value': 'Original', 'selected': True, 'disabled': False},
            {'value': case['payload']['fields'][0]['resolved_value'], 'selected': False, 'disabled': False}]
        row['raw_value'] = ['Original'] if kind == 'multi_select' else 'Original'
    else:
        row['control'].update(tag='div', content_editable=True); row['value_kind'] = 'plain_contenteditable_text'
    rebuild(case, wrapper)
    result = validate(case, wrapper)
    assert result['after']['executionAllowed'] is False
    assert result['after']['required_fields_complete'] is False
