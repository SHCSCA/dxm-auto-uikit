"""在当前 owner 页面独立采集冻结字段清单，不导航、不填写、不恢复。"""

import threading
import time
import uuid
from copy import deepcopy

from src.batch_edit.editor_inventory_contract import ACTION, STATE, SCHEMA, command_binding, validate_observation
from src.batch_edit.frozen_execution_contract import validate_frozen_execution_defaults
from src.batch_edit.scope_contract import canonical_sha256
from src.core.config import SCREENSHOT_DIR
from src.core.config_bus import get_config_bus
from src.execution.editor_control_inventory import collect_editor_control_inventory
from src.execution.editor_inventory_guard import EditorInventoryGuard
from src.services.structured_logging import get_logger, log_exception


_LOGGER = get_logger('editor.inventory_flow')


class _ReadOnlyPage:
    def __init__(self, page, require_identity, require_owner):
        self.page, self.require_identity, self.require_owner = page, require_identity, require_owner

    @property
    def main_frame(self):
        return self.page.main_frame

    @property
    def url(self):
        return self.page.url

    def is_closed(self):
        return self.page.is_closed()

    def evaluate(self, script, args):
        self.require_identity()
        result = self.page.evaluate(script, args)
        self.require_identity()
        return result

    def on(self, event, handler):
        self.require_owner()
        self.page.on(event, handler)
        self.require_owner()

    def remove_listener(self, event, handler):
        # 失效后也先撤监听，再报告 owner 漂移，避免留下部分采集器。
        self.page.remove_listener(event, handler)
        self.require_owner()


def observe_editor_control_inventory(flow, *, defaults, category_schema, product_query, store_name, shop_id, target_identity):
    try:
        return _observe(flow, defaults=defaults, category_schema=category_schema, product_query=product_query,
            store_name=store_name, shop_id=shop_id, target_identity=target_identity)
    except Exception as exc:
        log_exception(_LOGGER, 'editor_inventory_observation_failed', exc)
        raise


def _observe(flow, *, defaults, category_schema, product_query, store_name, shop_id, target_identity):
    payload = validate_frozen_execution_defaults(defaults)
    category = deepcopy(category_schema)
    target, target_hash = flow._normalize_frozen_target_identity(target_identity, store_name=store_name)
    command = deepcopy(flow._execution_evidence_context or {})
    page, context, browser = flow._page, flow._context, flow._browser
    session, thread = flow.browser_session_id(), threading.get_ident()
    if (page is None or context is None or browser is None or not session
            or flow._browser_session_thread_id != thread or page.context is not context
            or command.get('state') != STATE or command.get('command_action') != ACTION
            or command.get('mode') != 'batch_draft_save' or command.get('browser_session_id') != session
            or payload.get('execution_path') != 'B' or payload.get('save_stage', 'SAVE1') != 'SAVE1'
            or product_query != str(payload.get('product_id'))
            or target['stable_identity']['kind'] != 'product_id' or target['stable_identity']['value'] != product_query
            or not isinstance(shop_id, str) or not shop_id.isdecimal() or int(shop_id) <= 0
            or not isinstance(category, dict) or not isinstance(category.get('normalized_schema'), dict)
            or canonical_sha256(category['normalized_schema']) != category.get('schema_hash')
            or category['schema_hash'] != payload.get('category_schema_hash')):
        raise RuntimeError('EDITOR_INVENTORY_CONTEXT_OR_FROZEN_SCHEMA_INVALID')
    frame, url = page.main_frame, str(page.url)
    guard = None

    def require_owner():
        deadline = command.get('deadline_monotonic')
        if (threading.get_ident() != thread or flow._browser_session_thread_id != thread
                or flow._page is not page or flow._context is not context or flow._browser is not browser
                or page.context is not context or page.main_frame is not frame or str(page.url) != url or page.is_closed()
                or flow.browser_session_id() != session or flow._execution_evidence_context != command
                or type(deadline) not in {int, float} or not time.monotonic() < deadline
                or category_schema != category):
            raise RuntimeError('EDITOR_INVENTORY_OWNER_SESSION_OR_DEADLINE_DRIFT')

    def require_identity():
        require_owner()
        guard.require_live()
        flow._require_frozen_product_page_identity(page, target_identity=target, store_name=store_name, phase='编辑控件清单只读观察')
        require_owner()
        guard.require_live()

    require_owner()
    started = flow._evidence_observed_at()
    with EditorInventoryGuard(page, require_owner) as guard:
        require_identity()
        if page.locator('[role="dialog"]:visible,.ant-modal:visible').count():
            raise RuntimeError('EDITOR_INVENTORY_MODAL_PRESENT')
        require_identity()
        view = _ReadOnlyPage(page, require_identity, require_owner)
        before = collect_editor_control_inventory(view, payload, category)
        require_identity()
        if before.get('collected') is not True or before.get('stable') is not True:
            raise RuntimeError('EDITOR_INVENTORY_READ_INCOMPLETE')
        screenshot = SCREENSHOT_DIR / f'editor-inventory-{uuid.uuid4().hex}.png'
        timeout = get_config_bus().integer('DXM_EDITOR_INVENTORY_SCREENSHOT_TIMEOUT_MS', 10000, minimum=100, maximum=60000)
        page.screenshot(path=str(screenshot), full_page=True, timeout=timeout, caret='initial')
        require_identity()
        after = collect_editor_control_inventory(view, payload, category)
        require_identity()
        if after.get('collected') is not True or after.get('stable') is not True:
            raise RuntimeError('EDITOR_INVENTORY_READ_INCOMPLETE')
        if before != after:
            raise RuntimeError('EDITOR_INVENTORY_READBACK_DRIFT')
    effects = guard.facts()
    require_owner()
    completed = flow._evidence_observed_at()
    observation = {'product_id': payload['product_id'], 'shop_id': shop_id, 'browser_session_id': session,
        'page_url': url, 'target_identity_sha256': target_hash, 'observed_at': completed,
        'inventory_sha256': after.get('inventory_sha256'), 'evidence_ref': flow._evidence_descriptor(screenshot), 'write_attempted': False}
    require_owner()
    wrapper = {'schema': SCHEMA, 'command': command_binding(command), 'execution_payload_hash': payload['payload_hash'],
        'category_schema_hash': category['schema_hash'], 'started_at': started, 'completed_at': completed,
        'before': before, 'after': after, 'effect_facts': effects, 'observation': observation}
    checked = validate_observation(wrapper, payload=payload, category_schema=category, target_identity=target,
        shop_id=shop_id, context=command)
    return {'ok': True, 'stage': 'editor_control_inventory_observed', 'page_url': url,
        'store_name': store_name, 'target_identity': target, 'write_attempted': False,
        'editor_inventory_observation': checked, 'evidence_ref': observation['evidence_ref']}
