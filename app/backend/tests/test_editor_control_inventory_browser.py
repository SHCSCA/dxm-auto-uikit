"""真实本机 Chromium 执行合成 DOM；结果不证明生产控件、恢复或填写能力。"""

import json

import pytest
from playwright.sync_api import sync_playwright

from src.execution.editor_control_inventory import SECTION_CODES, collect_editor_control_inventory, editor_control_inventory_summary
from tests.support.editor_inventory_case import URL, inventory_case, inventory_html, resign


@pytest.fixture(scope='module')
def browser():
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(headless=True)
        yield instance
        instance.close()


@pytest.fixture
def case(browser):
    context = browser.new_context()
    context.route('**/*', lambda route: route.fulfill(status=200, content_type='text/html', body=inventory_html()))
    page = context.new_page(); page.goto(URL)
    payload, category = inventory_case()
    yield page, payload, category
    context.close()


def collect(case):
    return collect_editor_control_inventory(*case)


def row(result, key):
    return next(field for field in result['fields'] if field['field_key'] == key)


def test_private_native_values_preserve_types_and_targets_but_old_model_never_becomes_eleven_complete(case):
    result = collect(case)
    assert result['collected'] and result['stable']
    assert tuple(section['code'] for section in result['sections']) == SECTION_CODES
    assert row(result, 'title')['raw_value'] == row(result, 'title')['original_value'] == 'Original title'
    assert row(result, 'title')['target_value'] == 'Target title'
    assert row(result, 'packageType')['original_value'] is True and row(result, 'packageType')['target_value'] is False
    assert row(result, 'taxType')['original_value'] == 1 and row(result, 'taxType')['section'] == 'template_main'
    tax = next(section for section in result['sections'] if section['code'] == 'template_tax')
    assert tax['state'] == 'MISSING' and tax['anchor'] is None
    assert result['templates'][0]['application_state'] == 'UNOBSERVED'
    assert 'TEMPLATE_APPLICATION_NOT_PROVEN' in result['missing']
    assert all(result[key] is False for key in ('executionAllowed', 'capabilityCertified', 'required_fields_complete', 'inputFreezeAllowed'))
    assert 'Original title' not in json.dumps(editor_control_inventory_summary(result))


@pytest.mark.parametrize('change,key,reason', [
    ("document.querySelector('[name=sourceUrl]').remove()", 'sourceUrl', 'CONTROL_NATIVE_IDENTITY_MISSING'),
    ("document.querySelector('[name=sourceUrl]').after(document.querySelector('[name=sourceUrl]').cloneNode(true))", 'sourceUrl', 'CONTROL_IDENTITY_AMBIGUOUS'),
    ("document.querySelector('[name=sourceUrl]').style.display='none'", 'sourceUrl', 'CONTROL_NOT_VISIBLE'),
    ("document.querySelector('[name=sourceUrl]').disabled=true", 'sourceUrl', 'CONTROL_DISABLED'),
    ("(()=>{const field=document.querySelector('[name=sourceUrl]'),group=document.createElement('fieldset');group.disabled=true;field.before(group);group.append(field)})()", 'sourceUrl', 'CONTROL_DISABLED'),
    ("document.querySelector('[name=sourceUrl]').readOnly=true", 'sourceUrl', 'CONTROL_READ_ONLY'),
    ("document.querySelector('[name=sourceUrl]').type='date'", 'sourceUrl', 'CONTROL_TYPE_UNREVIEWED'),
    ("document.querySelector('#dxmInfo').removeAttribute('id')", 'sourceUrl', 'SECTION_CONTROL_BOUNDARY_UNPROVEN'),
    ("document.querySelector('[name=msrEuId] option').disabled=true", 'msrEuId', 'TARGET_OR_ORIGINAL_OPTION_NOT_RESTORABLE'),
    ("document.querySelector('[name=msrEuId]').append(document.querySelector('[name=msrEuId] option').cloneNode(true))", 'msrEuId', 'OPTION_VALUE_IDENTITY_AMBIGUOUS'),
])
def test_missing_unknown_duplicate_or_unrestorable_control_is_explicitly_blocked(case, change, key, reason):
    case[0].evaluate(change)
    result = collect(case)
    assert result['collected'] and reason in row(result, key)['missing']
    assert row(result, key)['recovery_boundary'] == 'UNVERIFIED'
    assert result['required_fields_complete'] is False


def test_labels_data_markers_and_json_equality_are_not_native_control_identity(case):
    page = case[0]
    page.evaluate('''()=>{
      document.querySelector('[name=sourceUrl]').remove();
      const node=document.createElement('div');node.textContent='来源 URL';
      node.dataset.uiBinding='dxm_editor:sourceUrl';node.dataset.resolvedJson='"https://fixture.invalid/source"';
      document.querySelector('#dxmInfo').append(node);
    }''')
    result = collect(case)
    assert row(result, 'sourceUrl')['value_observed'] is False
    assert 'CONTROL_NATIVE_IDENTITY_MISSING' in row(result, 'sourceUrl')['missing']
    assert 'STRUCTURED_CONTROL_BINDING_REQUIRED' in row(result, 'detail')['missing']


def test_unknown_section_and_missing_required_fields_cannot_be_invented_from_field_names(case):
    page, payload, category = case
    category['normalized_schema']['properties']['title']['ui_section'] = 'unreviewed_section'
    payload['fields'] = [field for field in payload['fields'] if field['field_key'] != 'taxType']
    resign(payload, category)
    result = collect(case)
    assert 'SECTION_SCHEMA_IDENTITY_UNKNOWN' in row(result, 'title')['missing']
    assert result['unfrozen_required_fields'] == ['taxType']
    assert 'FROZEN_REQUIRED_FIELD_COVERAGE_INCOMPLETE' in result['missing']


def test_declared_tax_section_still_requires_an_actually_reviewed_native_boundary(case):
    page, payload, category = case
    category['normalized_schema']['properties']['taxType']['ui_section'] = 'template_tax'
    resign(payload, category)
    result = collect(case)
    assert row(result, 'taxType')['section'] == 'template_tax'
    assert 'SECTION_CONTROL_BOUNDARY_UNPROVEN' in row(result, 'taxType')['missing']
    assert result['required_fields_complete'] is False


def test_password_or_hidden_control_values_are_never_read(case):
    page = case[0]
    page.evaluate('''()=>{
      const element=document.querySelector('[name=sourceUrl]');element.type='password';
      Object.defineProperty(element,'value',{get(){throw Error('secret read forbidden')}});
    }''')
    result = collect(case)
    assert result['collected'] and row(result, 'sourceUrl')['value_observed'] is False
    assert row(result, 'sourceUrl')['raw_value'] is None


def test_collector_never_writes_dom_calls_handlers_or_initiates_requests(case):
    page = case[0]; requests = []
    page.on('request', lambda request: requests.append(request.url))
    page.evaluate('''()=>{
      window.mutations=[];window.watch=new MutationObserver(records=>mutations.push(...records));
      watch.observe(document.body,{subtree:true,attributes:true,childList:true,characterData:true});
      const reject=()=>{throw Error('unexpected write')};
      window.fetch=reject;window.XMLHttpRequest=reject;Element.prototype.click=reject;
      Element.prototype.setAttribute=reject;Element.prototype.dispatchEvent=reject;
    }''')
    assert collect(case)['collected'] is True
    assert page.evaluate('mutations.length') == 0 and requests == []


@pytest.mark.parametrize('change', ["document.querySelector('.product-add-wrapper').remove()",
    "document.body.append(document.querySelector('.product-add-wrapper').cloneNode(true))"])
def test_missing_or_duplicate_editor_root_cannot_produce_candidate_rows(case, change):
    case[0].evaluate(change)
    result = collect(case)
    assert result['collected'] is False and result['fields'] == []


@pytest.mark.parametrize('kind,reason', [('unreviewed', 'FIELD_SCHEMA_TYPE_UNREVIEWED'), ('array', 'STRUCTURED_CONTROL_BINDING_REQUIRED')])
def test_unknown_or_structured_schema_does_not_invent_an_original_value(case, kind, reason):
    _page, payload, category = case
    category['normalized_schema']['properties']['title']['type'] = kind
    resign(payload, category)
    result = collect(case)
    assert reason in row(result, 'title')['missing']
    assert row(result, 'title')['original_value'] is None
    assert row(result, 'title')['original_normalized'] is False


def test_schema_primitive_mismatch_does_not_certify_checkbox_as_string(case):
    _page, payload, category = case
    category['normalized_schema']['properties']['packageType']['type'] = 'string'
    resign(payload, category)
    result = collect(case)
    assert {'ORIGINAL_WIRE_TYPE_UNPROVEN', 'CONTROL_SCHEMA_TYPE_MISMATCH', 'TARGET_SCHEMA_TYPE_UNPROVEN'} <= set(row(result, 'packageType')['missing'])
    assert row(result, 'packageType')['original_normalized'] is False


def test_native_template_id_equal_to_target_still_does_not_prove_application(case):
    case[0].evaluate("document.querySelector('[name=freightTemplateId]').value='freight-2'")
    result = collect(case)
    assert row(result, 'freightTemplateId')['original_value'] == row(result, 'freightTemplateId')['target_value']
    assert result['templates'][0]['application_state'] == 'UNOBSERVED'
    assert 'TEMPLATE_APPLICATION_NOT_PROVEN' in result['missing']


def test_changed_value_between_readbacks_rejects_all_candidates(case, monkeypatch):
    page = case[0]; evaluate = page.evaluate; count = 0

    def changed(script, args):
        nonlocal count
        count += 1
        if count == 2:
            evaluate("document.querySelector('[name=sourceUrl]').value='changed'")
        return evaluate(script, args)

    monkeypatch.setattr(page, 'evaluate', changed)
    result = collect(case)
    assert result['collected'] is False and result['fields'] == []


@pytest.mark.parametrize('exit_kind', ['close', 'same_url_reload', 'cleanup_exception'])
def test_late_document_change_or_cleanup_failure_drops_candidate_hash(case, monkeypatch, exit_kind, caplog):
    page = case[0]; remove = page.remove_listener

    def cleanup(event, callback):
        if exit_kind == 'same_url_reload':
            page.reload()
        remove(event, callback)
        if exit_kind == 'close':
            page.close()
        elif exit_kind == 'cleanup_exception':
            raise RuntimeError('synthetic cleanup failure')

    monkeypatch.setattr(page, 'remove_listener', cleanup)
    result = collect(case)
    assert result['collected'] is False and result['fields'] == [] and 'inventory_sha256' not in result
    assert 'editor_inventory_listener_cleanup_failed' in caplog.text or 'editor_inventory_document_changed' in caplog.text


def test_evaluate_error_is_logged_and_listener_removed(case, monkeypatch, caplog):
    page = case[0]; on = page.on; remove = page.remove_listener; handlers = []

    def added(event, handler):
        handlers.append(handler); return on(event, handler)

    def removed(event, handler):
        handlers.remove(handler); return remove(event, handler)

    def failed(_script, _args):
        raise RuntimeError('synthetic read failure')

    monkeypatch.setattr(page, 'on', added); monkeypatch.setattr(page, 'remove_listener', removed)
    monkeypatch.setattr(page, 'evaluate', failed)
    assert collect(case)['collected'] is False and handlers == []
    assert 'editor_control_inventory_failed' in caplog.text
