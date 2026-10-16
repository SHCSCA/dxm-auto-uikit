"""冻结输入与错误边界验证；不把调用方 Schema 或字段配置当生产权威。"""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from src.batch_edit.scope_contract import canonical_sha256
from src.core.config_bus import configuration_scope
from src.execution.editor_control_inventory import collect_editor_control_inventory, editor_control_inventory_summary
from tests.support.editor_inventory_case import inventory_case, resign


@pytest.mark.parametrize('change', [
    lambda payload, category: payload.update(payload_hash='A' * 64),
    lambda payload, category: category['normalized_schema']['properties']['title'].update(ui_section='other_info'),
    lambda payload, category: payload['fields'].append(deepcopy(payload['fields'][0])),
    lambda payload, category: payload['fields'][0].update(ui_binding='label:产品标题'),
    lambda payload, category: payload['fields'][0].update(category_schema_path='$.other.title'),
    lambda payload, category: payload.update(fields=[]),
])
def test_invalid_or_changed_frozen_input_never_touches_a_page(change, caplog):
    payload, category = inventory_case()
    change(payload, category)
    if payload.get('payload_hash') != 'A' * 64 and payload['category_schema_hash'] == category['schema_hash']:
        payload['payload_hash'] = canonical_sha256(
            {key: value for key, value in payload.items() if key != 'payload_hash'})
    result = collect_editor_control_inventory(SimpleNamespace(), payload, category)
    assert result['collected'] is False and result['missing'] == ['EDITOR_CONTROL_INVENTORY_UNVERIFIED']
    assert all(result[key] is False for key in ('executionAllowed', 'capabilityCertified', 'required_fields_complete', 'inputFreezeAllowed'))
    assert 'editor_control_inventory_failed' in caplog.text


def test_field_limit_is_read_through_configuration_bus_before_page_access():
    payload, category = inventory_case()
    with configuration_scope({'DXM_EDITOR_INVENTORY_MAX_FIELDS': '1'}):
        result = collect_editor_control_inventory(SimpleNamespace(), payload, category)
    assert result['collected'] is False


@pytest.mark.parametrize('url', ['https://other.invalid/web/smt/edit?id=10001',
    'http://www.dianxiaomi.com/web/smt/edit?id=10001', 'https://www.dianxiaomi.com/web/smt/edit?id=10002'])
def test_wrong_editor_identity_is_rejected_without_evaluating(url):
    payload, category = inventory_case()
    result = collect_editor_control_inventory(SimpleNamespace(url=url, main_frame=object()), payload, category)
    assert result['collected'] is False


def test_public_summary_does_not_expose_private_fields_targets_refs_or_business_url():
    private = {'inventory_sha256': 'A' * 64, 'execution_payload_sha256': 'B' * 64, 'category_schema_sha256': 'C' * 64,
        'collected': True, 'stable': True, 'page_url': 'private-business-url', 'fields': [
            {'original_value': 'private-original', 'target_value': 'private-target'}], 'sections': [
            {'field_keys': ['private-key']}], 'templates': [{'id': 'private-template'}], 'missing': ['SOME_MISSING', 'private value'],
        'executionAllowed': True, 'capabilityCertified': True, 'required_fields_complete': True}
    summary = editor_control_inventory_summary(private)
    assert not any(secret in json.dumps(summary) for secret in ['private-', 'private value'])
    assert summary['missing'] == ['SOME_MISSING']
    assert all(summary[key] is False for key in ('executionAllowed', 'capabilityCertified', 'required_fields_complete', 'inputFreezeAllowed'))


@pytest.mark.parametrize('value', [None, {'fields': None}, {'sections': {}}, {'missing': 'private text'}])
def test_malformed_summary_is_closed_and_logged(value, caplog):
    summary = editor_control_inventory_summary(value)
    assert summary['collected'] is False and summary['stable'] is False
    assert summary['missing'] == ['INVENTORY_PUBLIC_SUMMARY_UNVERIFIED']
    assert 'editor_inventory_summary_failed' in caplog.text


def test_summary_hash_slots_cannot_export_arbitrary_private_text():
    summary = editor_control_inventory_summary({'inventory_sha256': 'private-original',
        'execution_payload_sha256': 'https://private.invalid/product', 'category_schema_sha256': 123})
    assert all(summary[key] is None for key in ('inventory_sha256', 'execution_payload_sha256', 'category_schema_sha256'))
    assert 'private' not in json.dumps(summary)


def test_same_url_navigation_during_second_read_is_not_a_stable_inventory(caplog):
    payload, category = inventory_case()
    handlers = []
    frame = object()

    def evaluate(_script, _args):
        for handler in handlers:
            handler(frame)
        return {'schema': 'dxm.editor_control_dom.v1'}

    page = SimpleNamespace(url='https://www.dianxiaomi.com/web/smt/edit?id=10001', main_frame=frame,
        on=lambda _event, handler: handlers.append(handler), remove_listener=lambda _event, handler: handlers.remove(handler),
        evaluate=evaluate, is_closed=lambda: False)
    result = collect_editor_control_inventory(page, payload, category)
    assert not handlers and result['collected'] is False
    assert 'editor_control_inventory_failed' in caplog.text
