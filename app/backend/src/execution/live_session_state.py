"""同一会话 owner 的活体状态投影；受管失效只撤销资格，不重开窗口。"""

import json
from datetime import datetime, timezone

from src.execution.manual_login_session import ManualLoginSessionInvalidError
from src.execution.reader_http_observation import log_reader_diagnostic
from src.services.dxm_draft_reader import DxmDraftReaderError
from src.services.structured_logging import get_logger, log_event
from src.utils import now_iso


def _require_pin(flow):
    pinned = getattr(flow, '_managed_manual_login', None)
    if pinned is not None:
        pinned.require_context(flow)


def _unavailable(flow, *, reason_code, message):
    state = {
        **flow._default_state(), 'ok': False, 'stage': 'session_unavailable',
        'reason_code': reason_code, 'logged_in': False, 'reader_ready': False,
        'browser_session_id': None, 'account_ref': None,
        'message': message,
        'next_action': '当前受管会话已失效；由工作台重新建立登录窗口后再检测。',
        'requires_user_action': True, 'updated_at': now_iso(),
        'executionAllowed': False, 'capabilityCertified': False, 'inputFreezeAllowed': False,
    }
    flow._write_state(state)
    return state


def _reader_checked_at(reader_status):
    supplied = reader_status.get('checked_at')
    if supplied is None:
        return now_iso()
    try:
        if not isinstance(supplied, str):
            raise ValueError('READER_CHECK_TIME_INVALID')
        parsed = datetime.fromisoformat(supplied)
        if parsed.tzinfo is None:
            raise ValueError('READER_CHECK_TIME_ZONE_REQUIRED')
        return parsed.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
    except (TypeError, ValueError, OverflowError) as exc:
        log_reader_diagnostic('reader_check_time_invalid',
            exception_type=type(exc).__name__)
        return now_iso()


def _reader_unavailable(flow, state, page, reader_status):
    # 页面登录证据与 Reader 资格分开；失败只更新投影，不改变原受管窗口。
    negative = {
        **state, 'ok': False, 'stage': 'login_success',
        'reason_code': reader_status.get('reason_code') or 'BROWSER_SESSION_UNAVAILABLE',
        'logged_in': True, 'reader_ready': False,
        'browser_session_id': None, 'account_ref': None,
        'reader_checked_at': _reader_checked_at(reader_status),
        'page_url': str(getattr(page, 'url', '') or ''),
        'label': '已登录，但只读会话未就绪',
        'message': '页面已显示登录成功，但本次只读接口校验未通过。',
        'next_action': '保留当前真实浏览器窗口并重新检测；不要另开脚本或第二套浏览器。',
        'requires_user_action': True, 'updated_at': now_iso(),
        'executionAllowed': False, 'capabilityCertified': False, 'inputFreezeAllowed': False,
    }
    _require_pin(flow)
    try:
        flow._write_state(negative)
    except Exception as exc:
        log_reader_diagnostic('reader_negative_state_write_failed',
            exception_type=type(exc).__name__)
        raise
    log_reader_diagnostic('login_reader_unavailable',
        reason_code=negative['reason_code'], logged_in=True, reader_ready=False)
    return negative


def _get_live_state(flow):
    state = json.loads(flow.state_file.read_text(encoding='utf-8')) if flow.state_file.exists() else flow._default_state()
    if state.get('logged_in') is not True or state.get('reader_ready') is not True:
        page = flow._promote_dxm_page_from_connected_browser()
        if page is not None and flow._page_looks_logged_in(page):
            reader_status = flow._visible_reader_session_status()
            # Reader helper 可能把失效转换成 false；原 pin 仍须独立复核。
            _require_pin(flow)
            if reader_status.get('reader_ready') is True:
                verified = {
                    **state, 'ok': True, 'stage': 'login_success', 'reason_code': 'LOGIN_READER_READY',
                    'logged_in': True, 'reader_ready': True,
                    'browser_session_id': reader_status.get('browser_session_id'),
                    'account_ref': reader_status.get('account_ref'),
                    'label': '已登录', 'reader_checked_at': _reader_checked_at(reader_status),
                    'page_url': str(getattr(page, 'url', '') or ''),
                    'message': '登录成功，当前真实可见浏览器已可直接读取店铺与草稿。',
                    'next_action': '返回工作台进入采集箱选品；本阶段不会保存或发布。',
                    'requires_user_action': False, 'updated_at': now_iso(),
                }
                _require_pin(flow)
                flow._write_state(verified)
                return verified
            return _reader_unavailable(flow, state, page, reader_status)
        _require_pin(flow)
        return state
    try:
        page, _context, browser_session_id = flow._draft_reader_session()
    except DxmDraftReaderError as exc:
        revoked = {
            **state, 'ok': False, 'stage': 'session_unavailable',
            'reason_code': str(exc.reason_code or 'BROWSER_SESSION_UNAVAILABLE'),
            'logged_in': False, 'reader_ready': False, 'browser_session_id': None, 'account_ref': None,
            'message': str(exc),
            'next_action': '从工作台重新连接店小秘；登录成功后 Reader 会复用同一个真实可见会话。',
            'requires_user_action': True, 'updated_at': now_iso(),
        }
        _require_pin(flow)
        flow._write_state(revoked)
        return revoked
    verified = {
        **state, 'ok': True, 'stage': 'login_success', 'reason_code': 'LOGIN_READER_READY',
        'logged_in': True, 'reader_ready': True, 'browser_session_id': browser_session_id,
        'page_url': str(getattr(page, 'url', '') or state.get('page_url') or ''),
        'requires_user_action': False, 'updated_at': now_iso(),
    }
    _require_pin(flow)
    if verified != state:
        flow._write_state(verified)
    return verified


def get_live_session_state(flow):
    try:
        return _get_live_state(flow)
    except ManualLoginSessionInvalidError:
        flow.clear_mutation_authorizer()
        flow.clear_execution_evidence_context()
        log_event(get_logger('login.live_state'), 'managed_manual_login_status_revoked', level='WARNING',
            reason_code=ManualLoginSessionInvalidError.reason_code)
        return _unavailable(flow, reason_code=ManualLoginSessionInvalidError.reason_code,
            message='受管登录的上下文、会话或 owner 校验失效，当前没有登录或 Reader 资格。')
