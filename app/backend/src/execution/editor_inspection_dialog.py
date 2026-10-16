"""只打开唯一已审入口并核对表单；不选择图片、音乐、语言或生成动作。"""

import re
from types import SimpleNamespace

from src.batch_edit.scope_contract import canonical_sha256
from src.core.config_bus import get_config_bus
from src.execution.editor_readonly_inspection import (
    EDITOR_DIALOG_REVEAL_BINDINGS, EDITOR_READONLY_DOM_SCRIPT, EDITOR_READONLY_FORM_SCRIPT,
    EDITOR_READONLY_OVERLAYS_SCRIPT, EDITOR_TRANSLATION_SURFACE_BINDING, EDITOR_VIDEO_SURFACE_BINDING,
    EDITOR_CONTENT_ACTION_SURFACE_SCRIPT, wait_editor_form_stable,
)
from src.execution.editor_inspection_video import observe_inspection_video
from src.services.structured_logging import get_logger, log_exception


def reveal_inspection_dialog(owner, scope, action, *, ready, screenshot_dir, describe_evidence):
    page, rpc = owner.page, owner.rpc
    dom = rpc(page.evaluate, EDITOR_READONLY_DOM_SCRIPT)
    result = {'dialogObservation': {'requested': action, 'clickAttempted': False, 'clickCompleted': False,
        'ok': False, 'reasonCode': 'EDITOR_DIALOG_NOT_OBSERVED'}, 'beforeDom': dom}
    observed = result['dialogObservation']
    existing_dialogs, main_form = page.locator('[role="dialog"]:visible,.ant-modal:visible'), page.locator('.product-add-wrapper')
    if not ready or rpc(main_form.count) != 1:
        observed['reasonCode'] = 'EDITOR_DIALOG_PAGE_NOT_READY'
        return result
    if rpc(existing_dialogs.count) != 0:
        observed['reasonCode'] = 'EDITOR_DIALOG_ALREADY_VISIBLE'
        return result
    checked_page = SimpleNamespace(wait_for_timeout=lambda value: rpc(page.wait_for_timeout, value))
    checked_form = SimpleNamespace(evaluate=lambda script: rpc(main_form.evaluate, script))
    stability = wait_editor_form_stable(checked_page, checked_form)
    observed['formStability'] = {key: value for key, value in stability.items() if key != 'snapshot'}
    main_form_before = stability['snapshot']
    result['beforeDom'] = rpc(page.evaluate, EDITOR_READONLY_DOM_SCRIPT)
    selector, button_name = EDITOR_DIALOG_REVEAL_BINDINGS[action]
    button = page.locator(selector)
    entry_probe = {'containerCount': rpc(button.count)}
    if entry_probe['containerCount'] == 1:
        entry_probe['accessibility'] = rpc(button.aria_snapshot, timeout=get_config_bus().integer(
            'DXM_INSPECTION_ENTRY_TIMEOUT_MS', 5000, minimum=100, maximum=30000))
    if action == 'video':
        button = button.locator('button')
    entry_probe['namedCount'] = rpc(button.count)
    entry_probe['candidates'] = rpc(button.evaluate_all,
        "els=>els.map(el=>({text:el.textContent,disabled:!!el.disabled,tag:el.tagName,className:el.className}))")
    button = button.filter(has_text=re.compile('^' + re.escape(button_name) + '$'))
    entry_probe['filteredCount'] = rpc(button.count)
    result['entryProbe'] = entry_probe
    try:
        if stability['ok'] is not True:
            raise RuntimeError('EDITOR_DIALOG_FORM_NOT_STABLE')
        if rpc(button.count) != 1 or not rpc(button.is_visible) or not rpc(button.is_enabled):
            raise RuntimeError('EDITOR_DIALOG_ENTRY_NOT_UNIQUE_VISIBLE')
        if action == 'video':
            result['videoInitialLifetime'] = scope.open_video_window()
        observed['clickAttempted'] = True
        rpc(button.click, timeout=get_config_bus().integer('DXM_INSPECTION_ENTRY_TIMEOUT_MS', 5000, minimum=100, maximum=30000))
        observed['clickCompleted'] = True
        surface = page.locator(EDITOR_TRANSLATION_SURFACE_BINDING) if action == 'translation' else page.locator(EDITOR_VIDEO_SURFACE_BINDING)
        rpc(surface.wait_for, state='visible', timeout=get_config_bus().integer(
            'DXM_INSPECTION_SURFACE_TIMEOUT_MS', 10000, minimum=100, maximum=30000))
        rpc(page.wait_for_load_state, 'networkidle', timeout=get_config_bus().integer(
            'DXM_INSPECTION_DIALOG_IDLE_TIMEOUT_MS', 5000, minimum=100, maximum=30000))
        observed['dialogCount'] = rpc(surface.count)
        observed['ok'] = observed['dialogCount'] == 1
        observed['reasonCode'] = 'EDITOR_DIALOG_OBSERVED' if observed['ok'] else 'EDITOR_DIALOG_NOT_UNIQUE'
    except Exception as exc:
        log_exception(get_logger('editor.inspection'), 'editor_inspection_reveal_failed', exc)
        observed.update(ok=False, reasonCode='EDITOR_DIALOG_REVEAL_FAILED', errorType=type(exc).__name__)
        owner.require_document()
    main_form_after = rpc(main_form.evaluate, EDITOR_READONLY_FORM_SCRIPT)
    unchanged = canonical_sha256(main_form_after) == canonical_sha256(main_form_before)
    observed.update(mainFormBeforeSha256=canonical_sha256(main_form_before), mainFormAfterSha256=canonical_sha256(main_form_after),
        mainFormUnchanged=unchanged)
    if not unchanged:
        observed.update(ok=False, reasonCode='EDITOR_DIALOG_UNEXPECTED_EFFECT')
    owner.require_document()
    result.update(dom=rpc(page.evaluate, EDITOR_READONLY_DOM_SCRIPT), overlayDom=rpc(page.evaluate, EDITOR_READONLY_OVERLAYS_SCRIPT),
        contentSurface=rpc(page.evaluate, EDITOR_CONTENT_ACTION_SURFACE_SCRIPT, action))
    if action == 'video' and observed['ok']:
        result['videoInputDiagnostic'] = observe_inspection_video(owner, screenshot_dir=screenshot_dir,
            describe_evidence=describe_evidence)
    return result
