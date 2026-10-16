"""公开 Reader 身份下的临时编辑页检查；不签发命令、快照或业务执行资格。"""

import json
import uuid

from playwright.sync_api import TimeoutError

from src.batch_edit.scope_contract import canonical_sha256
from src.core.config import DATA_DIR, SCREENSHOT_DIR
from src.core.config_bus import get_config_bus
from src.execution.editor_inspection_dialog import reveal_inspection_dialog
from src.execution.editor_inspection_owner import EditorInspectionOwner
from src.execution.editor_inspection_scope import EditorInspectionScope
from src.execution.editor_inspection_video import finalize_inspection_video
from src.execution.editor_readonly_inspection import (
    EDITOR_DIALOG_REVEAL_BINDINGS, EDITOR_READONLY_READY_SCRIPT, EDITOR_READONLY_HYDRATED_SCRIPT, EDITOR_READONLY_DOM_SCRIPT,
)
from src.execution.native_video_diagnostic import video_diagnostic_summary
from src.services.dxm_draft_reader import DxmDraftReaderError
from src.services.dxm_plan_reader import DxmPlanReader, DxmPlanReaderError
from src.services.structured_logging import get_logger, log_exception


def _cleanup(owner, page, *, failed):
    failures = []
    for operation in ([owner.close] if owner is not None else []) + ([page.close] if page is not None else []):
        try:
            operation()
        except Exception as exc:
            failures.append(exc)
            if owner is not None and owner.binding is not None:
                owner.binding.transport.invalid = True
            log_exception(get_logger('editor.inspection'), 'editor_inspection_cleanup_failed', exc)
    if failures and not failed:
        raise RuntimeError('EDITOR_INSPECTION_FINAL_CLEANUP_FAILED') from failures[0]


def _inspect(flow, *, shop_id, product_id, session_ref, guard, observe_dialog):
    if observe_dialog is not None and observe_dialog not in EDITOR_DIALOG_REVEAL_BINDINGS:
        raise DxmDraftReaderError('EDITOR_INSPECTION_DIALOG_INVALID', '只允许观察翻译或视频入口弹窗。')
    shop_id, product_id = (flow._positive_reader_id(value, label=label)
        for value, label in ((shop_id, '店铺'), (product_id, '商品')))
    before = flow.read_e2_product_details(shop_id=shop_id, product_ids=[product_id])
    browser_id, account_ref, payload = DxmPlanReader._validated_envelope(before)
    if DxmPlanReader._session_ref(browser_id, account_ref) != session_ref:
        raise DxmDraftReaderError('DXM_PLAN_SESSION_MISMATCH', '只读检查会话已变化。')
    products = payload.get('products')
    if not isinstance(products, list) or len(products) != 1:
        raise DxmDraftReaderError('PRODUCT_IDENTITY_CONFLICT', '只读检查缺少唯一草稿。')
    observed_id, detail = DxmPlanReader._validated_product_detail(products[0], shop_id=shop_id)
    if observed_id != product_id:
        raise DxmDraftReaderError('PRODUCT_IDENTITY_CONFLICT', '只读检查草稿身份不符。')
    primary, context, current_browser_id = flow._draft_reader_session()
    if current_browser_id != browser_id:
        raise DxmDraftReaderError('BROWSER_SESSION_MISMATCH', '只读检查浏览器已变化。')
    page = None
    owner, failed, video_sources = None, True, None
    result = None
    try:
        if flow._context is not context or flow._page is not primary or flow.browser_session_id() != browser_id:
            raise RuntimeError('EDITOR_INSPECTION_NEW_PAGE_OWNER_DRIFT')
        owner = EditorInspectionOwner(flow, None, f'https://www.dianxiaomi.com/web/smt/edit?id={product_id}',
            video=observe_dialog == 'video')
        owner.start()
        page = owner.page
        with EditorInspectionScope(owner, guard) as scope:
            rpc, bus = owner.rpc, get_config_bus()
            rpc(page.goto, owner.url, wait_until='domcontentloaded', timeout=bus.integer(
                'DXM_INSPECTION_NAVIGATION_TIMEOUT_MS', 30000, minimum=1000, maximum=60000))
            owner.require_document()
            title_loaded = form_loaded = False
            try:
                rpc(page.wait_for_function, EDITOR_READONLY_READY_SCRIPT, arg=detail.get('subject'), timeout=bus.integer(
                    'DXM_INSPECTION_TITLE_TIMEOUT_MS', 20000, minimum=100, maximum=60000))
                title_loaded = True
                rpc(page.wait_for_function, EDITOR_READONLY_HYDRATED_SCRIPT, arg=detail.get('sourceUrl'), timeout=bus.integer(
                    'DXM_INSPECTION_FORM_TIMEOUT_MS', 30000, minimum=100, maximum=60000))
                form_loaded = True
                rpc(page.wait_for_load_state, 'networkidle', timeout=bus.integer(
                    'DXM_INSPECTION_IDLE_TIMEOUT_MS', 15000, minimum=100, maximum=30000))
            except TimeoutError as exc:
                log_exception(get_logger('editor.inspection'), 'editor_inspection_form_timeout', exc)
                owner.require_document()
            result = {'schemaVersion': 'dxm.editor.readonly_inspection.v1', 'source': 'visible_production_editor_readonly',
                'createdAt': flow._evidence_observed_at(), 'sessionRef': session_ref, 'shopId': shop_id, 'productId': product_id,
                'categoryId': str(detail.get('categoryId') or ''), 'titleLoaded': title_loaded, 'formLoaded': form_loaded,
                'pageErrors': [], 'dom': rpc(page.evaluate, EDITOR_READONLY_DOM_SCRIPT),
                'ok': title_loaded and form_loaded, 'executionAllowed': False, 'capabilityCertified': False,
                'inputFreezeAllowed': False, 'write_attempted': False}
            if observe_dialog is not None:
                result.update(reveal_inspection_dialog(owner, scope, observe_dialog, ready=title_loaded and form_loaded,
                    screenshot_dir=SCREENSHOT_DIR, describe_evidence=flow._evidence_descriptor))
                result['ok'] = result['ok'] and result['dialogObservation']['ok']
            video_sources = owner.seal_profile()
            owner.require_document()
            if 'videoInputDiagnostic' in result:
                finalize_inspection_video(owner, result['videoInputDiagnostic'], video_sources)
                result['videoInputSummary'] = video_diagnostic_summary(result['videoInputDiagnostic'])
        result['network'] = scope.summary()
        result['ok'] = result['ok'] and not any(result['network'].get(key) for key in (
            'blocked_request_count', 'write_request_count', 'non_read_request_count',
            'forbidden_keyword_request_count', 'websocket_count', 'allowlist_error_count', 'unexpected_effects'))
        if video_sources is not None:
            result['videoStaticSources'] = video_sources
        failed = False
    finally:
        _cleanup(owner, owner.page if owner is not None else page, failed=failed)
    after = flow.read_e2_product_details(shop_id=shop_id, product_ids=[product_id])
    if canonical_sha256(after) != canonical_sha256(before):
        raise DxmDraftReaderError('EDITOR_INSPECTION_DATA_DRIFT', '只读检查期间商品或会话变化，不能用作执行依据。')
    path = DATA_DIR / 'editor_readonly_inspection' / f'{uuid.uuid4().hex}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    private = {'dom', 'beforeDom', 'overlayDom', 'entryProbe', 'contentSurface', 'videoInputDiagnostic', 'videoInitialLifetime'}
    return {key: value for key, value in result.items() if key not in private} | {'artifact': flow._evidence_descriptor(path)}


def inspect_editor_readonly(flow, *, shop_id, product_id, session_ref, guard, observe_dialog=None):
    try:
        return _inspect(flow, shop_id=shop_id, product_id=product_id, session_ref=session_ref,
            guard=guard, observe_dialog=observe_dialog)
    except (DxmDraftReaderError, DxmPlanReaderError) as exc:
        log_exception(get_logger('editor.inspection'), 'editor_readonly_inspection_failed', exc)
        raise
    except Exception as exc:
        log_exception(get_logger('editor.inspection'), 'editor_readonly_inspection_failed', exc)
        raise DxmDraftReaderError('EDITOR_INSPECTION_UNVERIFIED',
            '本次只读取证的页面、传输或清理未能核实，已停止；没有执行、能力或冻结资格。') from exc
