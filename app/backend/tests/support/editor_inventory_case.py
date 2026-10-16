"""只含仓内已知字段名的合成 Schema/DOM，不代表真实商品或生产控件证明。"""

from copy import deepcopy
from html import escape

from src.batch_edit.scope_contract import canonical_sha256
from src.services.dxm_editor_model import EDITOR_SECTIONS


URL = 'https://www.dianxiaomi.com/web/smt/edit?id=10001'
CASES = [
    ('title', 'basic_info', 'string', 'input', 'Target title', 'Original title'),
    ('sourceUrl', 'dxm_info', 'string', 'input', 'https://fixture.invalid/source', 'https://fixture.invalid/original'),
    ('attr_123', 'attribute_info', 'string', 'select', '2', '1'),
    ('productUnit', 'product_info', 'string', 'select', 'piece', 'piece'),
    ('aeopNationalQuoteConfiguration', 'regional_pricing', 'string', 'regional_pricing', '{}', '{}'),
    ('detail', 'description_info', 'string', 'input', '<p>Target</p>', '<p>Original</p>'),
    ('packageType', 'packaging_info', 'boolean', 'input', False, True),
    ('freightTemplateId', 'template_main', 'string', 'select', 'freight-2', 'freight-1'),
    ('taxType', 'template_main', 'integer', 'select', 2, 1),
    ('msrEuId', 'compliance_info', 'string', 'select', 'contact-2', 'contact-1'),
    ('summary', 'other_info', 'string', 'textarea', 'Target summary', 'Original summary'),
]


def inventory_case():
    properties, fields = {}, []
    for key, section, kind, control, target, _original in CASES:
        binding = 'dxm_attribute:123' if key == 'attr_123' else 'dxm_editor:' + key
        properties[key] = {'type': kind, 'ui_section': section, 'ui_binding': binding, 'ui_control': control}
        fields.append({'field_key': key, 'ui_label_zh': '合成字段', 'ui_binding': binding,
            'category_schema_path': '$.properties.' + key, 'resolved_value': deepcopy(target)})
    schema = {'type': 'object', 'properties': properties, 'required': list(properties)}
    category = {'normalized_schema': schema, 'schema_hash': canonical_sha256(schema)}
    payload = {'schema': 'dxm.batch_draft_save.execution_payload.v1', 'execution_path': 'B', 'save_stage': 'SAVE1',
        'product_id': '10001', 'category_id': '17', 'category_schema_hash': category['schema_hash'],
        'fields': fields, 'unresolved_fields': [], 'dxm_template_refs': [
            {'type': 'freight', 'id': 'freight-2', 'shop_id': '91', 'category_id': None, 'source_digest': 'A' * 64}]}
    return resign(payload, category)


def resign(payload, category):
    category['schema_hash'] = canonical_sha256(category['normalized_schema'])
    payload['category_schema_hash'] = category['schema_hash']
    payload['payload_hash'] = canonical_sha256({key: value for key, value in payload.items() if key != 'payload_hash'})
    return payload, category


def inventory_html():
    sections = {section['code']: [] for section in EDITOR_SECTIONS}
    for key, section, _kind, control, target, original in CASES:
        if key == 'title':
            node = '<input id="form_item_subject" name="subject" value="Original title">'
        elif key == 'packageType':
            node = '<input name="packageType" type="checkbox" checked>'
        elif control == 'select':
            values = list(dict.fromkeys([str(original), str(target)]))
            options = ''.join(f'<option value="{escape(value)}" {"selected" if value == str(original) else ""}>{escape(value)}</option>' for value in values)
            node = f'<select name="{key}">{options}</select>'
        elif control == 'textarea':
            node = f'<textarea name="{key}">{escape(str(original))}</textarea>'
        else:
            node = f'<input name="{key}" value="{escape(str(original), quote=True)}">'
        sections[section].append(node)
    blocks = ''.join(f'<div id="{section["anchor"]}">{"".join(sections[section["code"]])}</div>' for section in EDITOR_SECTIONS)
    return '<meta charset="utf-8"><style>div,input,textarea,select{min-height:14px;min-width:14px}</style><div class="product-add-wrapper">' + blocks + '</div>'
