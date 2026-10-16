"""从当前 owner thread 页面独立读取最终值；不生成内容、不修改字段、不宣称完整能力。"""

import time
import uuid
from copy import deepcopy

from src.batch_edit.content_observation_contract import command_binding, validate_observation
from src.batch_edit.frozen_execution_contract import validate_frozen_execution_defaults
from src.batch_edit.scope_contract import canonical_sha256
from src.core.config import SCREENSHOT_DIR
from src.execution.content_observation_guard import ContentObservationGuard
from src.execution.editor_readonly_inspection import EDITOR_READONLY_FORM_SCRIPT


def observe_content_finalize(flow, *, defaults, product_query, store_name, shop_id, target_identity):
    payload = validate_frozen_execution_defaults(defaults)
    target, target_hash = flow._normalize_frozen_target_identity(target_identity, store_name=store_name)
    context = flow._execution_evidence_context or {}
    page, browser_id = flow._page, flow.browser_session_id()
    if (page is None or payload.get('execution_path') != 'B' or payload.get('save_stage', 'SAVE1') != 'SAVE1'
            or context.get('state') != 'BATCH_TRANSLATE_EXECUTE' or context.get('command_action') != 'observe_content_finalize'
            or context.get('mode') != 'batch_draft_save' or context.get('browser_session_id') != browser_id
            or not isinstance(shop_id, str) or not shop_id.isdecimal()):
        raise RuntimeError('CONTENT_OBSERVATION_CONTEXT_INVALID')
    page_url = str(page.url)
    started = flow._evidence_observed_at()
    schema_input = {**payload, 'category_id': payload.get('target_category', {}).get('category_id', payload['category_id'])}

    def read():
        if (flow._page is not page or str(page.url) != page_url or flow.browser_session_id() != browser_id
                or time.monotonic() >= context.get('deadline_monotonic', 0)):
            raise RuntimeError('CONTENT_OBSERVATION_SESSION_OR_DEADLINE_DRIFT')
        flow._require_frozen_product_page_identity(page, target_identity=target, store_name=store_name, phase='最终独立零写读回')
        if page.locator('[role="dialog"]:visible,.ant-modal:visible').count():
            raise RuntimeError('CONTENT_OBSERVATION_MODAL_PRESENT')
        form = page.locator('.product-add-wrapper')
        if form.count() != 1:
            raise RuntimeError('CONTENT_OBSERVATION_FORM_NOT_UNIQUE')
        schema = flow._capture_current_editor_category_schema(page, schema_input, phase='content_finalize_observation', reject_redirects=True)
        observed = flow._capture_frozen_execution_values(page, payload, phase='content_finalize_observation')
        if schema.get('ok') is not True or observed.get('ok') is not True:
            raise RuntimeError('CONTENT_OBSERVATION_BINDINGS_OR_SCHEMA_UNPROVEN')
        return {'values': {field['field_key']: field['value'] for field in observed['values']},
                'bindings': {field['field_key']: field['ui_binding'] for field in payload['fields']},
                'category_schema': schema, 'form_sha256': canonical_sha256(form.evaluate(EDITOR_READONLY_FORM_SCRIPT))}

    with ContentObservationGuard(page, schema_input['category_id']) as guard:
        before = read()
        screenshot = SCREENSHOT_DIR / f'content-finalize-observation-{uuid.uuid4().hex}.png'
        page.screenshot(path=str(screenshot), full_page=True)
        after = read()
        if flow._page is not page or str(page.url) != page_url or flow.browser_session_id() != browser_id:
            raise RuntimeError('CONTENT_OBSERVATION_FINAL_IDENTITY_DRIFT')
        flow._require_frozen_product_page_identity(page, target_identity=target, store_name=store_name, phase='最终读回截图后身份复核')
    effects = guard.facts()
    completed = flow._evidence_observed_at()
    observation = {'product_id': payload['product_id'], 'shop_id': shop_id, 'browser_session_id': browser_id,
        'page_url': page_url, 'target_identity_sha256': target_hash, 'observed_at': completed,
        'values': deepcopy(after['values']), 'bindings': deepcopy(after['bindings']),
        'write_attempted': False, 'evidence_ref': flow._evidence_descriptor(screenshot)}
    wrapper = {'schema': 'dxm.content_finalize_observation.v1', 'command': command_binding(context),
        'execution_payload_hash': payload['payload_hash'], 'started_at': started, 'completed_at': completed,
        'before': before, 'after': after, 'effect_facts': effects, 'observation': observation}
    validated = validate_observation(wrapper, payload=payload, target_identity=target, shop_id=shop_id, context=context)
    return {'ok': True, 'stage': 'content_finalize_observed', 'page_url': page_url,
        'store_name': store_name, 'target_identity': target, 'write_attempted': False,
        'content_finalize_observation': validated, 'evidence_ref': observation['evidence_ref']}
