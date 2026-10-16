"""沿现有受管页面首次打开视频浮层并独立读回；不选择选项、不生成或投放。"""

import re
import time
import uuid
from copy import deepcopy

from src.batch_edit.native_video_observation_contract import ACTION, STATE, SCHEMA, command_binding, validate_observation
from src.batch_edit.frozen_execution_contract import validate_frozen_execution_defaults
from src.batch_edit.scope_contract import canonical_sha256
from src.core.config import SCREENSHOT_DIR
from src.execution.editor_readonly_inspection import (
    EDITOR_DIALOG_REVEAL_BINDINGS, EDITOR_VIDEO_SURFACE_BINDING, EDITOR_READONLY_FORM_SCRIPT,
)
from src.execution.native_video_observation_guard import NativeVideoObservationGuard
from src.execution.native_video_value_bindings import collect_native_video_value_bindings, validate_value_bindings


def _context(flow, defaults, target_identity, store_name, shop_id):
    payload = validate_frozen_execution_defaults(defaults)
    target, target_hash = flow._normalize_frozen_target_identity(target_identity, store_name=store_name)
    context = deepcopy(flow._execution_evidence_context or {})
    owner = getattr(flow, '_native_video_lifetime', None)
    if (context.get('state') != STATE or context.get('command_action') != ACTION
            or context.get('mode') != 'batch_draft_save' or payload.get('execution_path') != 'B'
            or context.get('browser_session_id') != flow.browser_session_id()
            or owner is None or owner.page is not flow._page or owner.session_id != flow.browser_session_id()
            or not isinstance(shop_id, str) or not shop_id.isdecimal()):
        raise RuntimeError('VIDEO_INPUT_OBSERVATION_CONTEXT_INVALID')
    policy = payload.get('editor_actions', {}).get('video', {})
    if (policy.get('enabled') is not True or policy.get('failure_strategy') != 'pause'
            or policy.get('generation_rule') != {'image_selection': 'native_default',
                'transition': {'mode': 'native_default'}, 'music': {'mode': 'native_default'}}):
        raise RuntimeError('VIDEO_INPUT_FROZEN_POLICY_INVALID')
    return payload, target, target_hash, context, owner


def _require_owner(flow, owner, context):
    if (owner is None or getattr(flow, '_native_video_lifetime', None) is not owner
            or flow._page is not owner.page or owner.session_id != flow.browser_session_id()
            or owner.closed or owner.invalid or not owner.started or owner.navigation_count != 1
            or owner.page.main_frame is not owner.frame or str(owner.page.url) != owner.page_url
            or flow._execution_evidence_context != context
            or time.monotonic() >= context.get('deadline_monotonic', 0)):
        raise RuntimeError('VIDEO_INPUT_OBSERVATION_SESSION_OR_DEADLINE_DRIFT')


def observe_native_video_inputs(flow, *, defaults, product_query, store_name, shop_id, target_identity):
    payload, target, target_hash, context, owner = _context(flow, defaults, target_identity, store_name, shop_id)
    owner.observation = None
    page = owner.page
    started = flow._evidence_observed_at()
    def require_identity():
        _require_owner(flow, owner, context)
        flow._require_frozen_product_page_identity(page, target_identity=target, store_name=store_name, phase='视频输入只读观察')
        _require_owner(flow, owner, context)

    require_identity()
    initial = owner.read()
    if any(initial[key] != 0 for key in ('reveal_count', 'entry_click_count', 'visible_count')):
        raise RuntimeError('VIDEO_INPUT_MODAL_NOT_INITIAL')
    if page.locator('[role="dialog"]:visible,.ant-modal:visible').count():
        raise RuntimeError('VIDEO_INPUT_BLOCKING_MODAL_PRESENT')
    form = page.locator('.product-add-wrapper')
    if form.count() != 1:
        raise RuntimeError('VIDEO_INPUT_MAIN_FORM_NOT_UNIQUE')
    with NativeVideoObservationGuard(page) as guard:
        form_before = form.evaluate(EDITOR_READONLY_FORM_SCRIPT)
        selector, label = EDITOR_DIALOG_REVEAL_BINDINGS['video']
        entry = page.locator(selector).locator('button').filter(has_text=re.compile('^' + re.escape(label) + '$'))
        if entry.count() != 1 or not entry.is_visible() or not entry.is_enabled():
            raise RuntimeError('VIDEO_INPUT_ENTRY_NOT_UNIQUE_VISIBLE')
        entry.click(timeout=5000)
        page.locator(EDITOR_VIDEO_SURFACE_BINDING).wait_for(state='visible', timeout=10000)
        page.wait_for_load_state('networkidle', timeout=5000)
        require_identity()
        source_profile = owner.profile.snapshot()
        before = collect_native_video_value_bindings(page)
        validate_value_bindings(before)
        screenshot = SCREENSHOT_DIR / f'native-video-inputs-{uuid.uuid4().hex}.png'
        page.screenshot(path=str(screenshot), full_page=True)
        after = collect_native_video_value_bindings(page)
        validate_value_bindings(after)
        lifetime = owner.read()
        if form.evaluate(EDITOR_READONLY_FORM_SCRIPT) != form_before:
            raise RuntimeError('VIDEO_INPUT_MAIN_FORM_CHANGED')
        require_identity()
        if owner.profile.snapshot() != source_profile:
            raise RuntimeError('VIDEO_INPUT_OBSERVATION_SOURCE_DRIFT')
        require_identity()
    effects = guard.facts()
    require_identity()
    lifetime = owner.read()
    if owner.profile.snapshot() != source_profile:
        raise RuntimeError('VIDEO_INPUT_OBSERVATION_SOURCE_DRIFT')
    require_identity()
    completed = flow._evidence_observed_at()
    inputs = validate_value_bindings(after)
    wrapper = {'schema': SCHEMA, 'command': command_binding(context), 'execution_payload_hash': payload['payload_hash'],
        'started_at': started, 'completed_at': completed, 'source_profile': source_profile,
        'lifecycle': {'page_lifetime_observed': owner.started, 'document_navigation_count': owner.navigation_count,
            'same_document': not owner.invalid, 'reveal_count': lifetime['reveal_count'], 'visible_before': initial['visible_count'],
            'visible_after': lifetime['visible_count'], 'interaction_count': lifetime['entry_click_count'],
            'unexpected_interactions': lifetime['unexpected_interactions'], 'native_defaults': True,
            'native_component_uid': after['instance']['uid'], 'owner_observation_id': owner.owner_id,
            'document_time_origin': lifetime['document_time_origin']}, 'before': before, 'after': after, 'effect_facts': effects,
        'observation': {'product_id': payload['product_id'], 'shop_id': shop_id, 'browser_session_id': owner.session_id,
            'page_url': str(page.url), 'target_identity_sha256': target_hash, 'observed_at': completed,
            'inputs': inputs, 'evidence_ref': flow._evidence_descriptor(screenshot), 'write_attempted': False}}
    checked = validate_observation(wrapper, payload=payload, target_identity=target, shop_id=shop_id, context=context)
    owner.observation = deepcopy(checked)
    return {'ok': True, 'stage': 'native_video_inputs_observed', 'page_url': str(page.url),
        'store_name': store_name, 'target_identity': target, 'write_attempted': False,
        'native_video_input_observation': checked, 'evidence_ref': wrapper['observation']['evidence_ref']}


def require_live_native_video_inputs(flow, freeze):
    owner = getattr(flow, '_native_video_lifetime', None)
    context = deepcopy(flow._execution_evidence_context or {})
    frozen = deepcopy(freeze)
    observed = deepcopy(owner.observation) if owner is not None else None
    _require_owner(flow, owner, context)
    if (owner is None or owner.page is not flow._page or owner.session_id != flow.browser_session_id()
            or owner.observation is None or freeze.get('lifecycle') != owner.observation['lifecycle']
            or freeze.get('lifecycle', {}).get('owner_observation_id') != owner.owner_id
            or owner.profile.snapshot() != owner.observation['source_profile']
            or freeze.get('inputs') != owner.observation['observation']['inputs']):
        raise RuntimeError('VIDEO_INPUT_LIVE_OWNER_REQUIRED')
    _require_owner(flow, owner, context)
    lifetime = owner.read()
    if (lifetime['reveal_count'] != 1 or lifetime['entry_click_count'] != 1 or lifetime['visible_count'] != 1
            or lifetime['document_time_origin'] != freeze['lifecycle']['document_time_origin']):
        raise RuntimeError('VIDEO_INPUT_LIVE_LIFECYCLE_DRIFT')
    raw = collect_native_video_value_bindings(owner.page)
    if (raw != owner.observation['after'] or validate_value_bindings(raw) != freeze['inputs']
            or canonical_sha256(freeze['inputs']) != freeze.get('inputs_sha256')):
        raise RuntimeError('VIDEO_INPUT_LIVE_VALUES_DRIFT')
    _require_owner(flow, owner, context)
    owner.read()
    if (freeze != frozen or owner.observation != observed
            or owner.profile.snapshot() != observed['source_profile']):
        raise RuntimeError('VIDEO_INPUT_LIVE_AUTHORITY_DRIFT')
    _require_owner(flow, owner, context)
    return True
