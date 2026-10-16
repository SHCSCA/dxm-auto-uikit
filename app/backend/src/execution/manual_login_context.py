"""在现有 Chrome 中建立全新手动登录生命周期；旧上下文永不获得新来源身份。"""

import threading

from src.core.config_bus import get_config_bus
from src.execution.browser_page_focus import bring_controlled_page_to_front
from src.execution.managed_browser_context import create_managed_browser_context
from src.execution.native_video_lifetime import close_native_video_lifetime
from src.services.structured_logging import get_logger, log_exception
from src.utils import now_iso


LOGIN_URL = 'https://www.dianxiaomi.com/'
_LOGGER = get_logger('manual_login.context')


class ManualLoginContext:
    def __init__(self, browser, owner_thread):
        self.browser, self.owner_thread = browser, owner_thread
        self.context = None
        self.session_id = None
        self.stopped = False

    def require_context(self, flow):
        if (self.stopped or self.context is None or flow._context is not self.context
                or flow._browser is not self.browser or flow._browser_session_thread_id != self.owner_thread
                or (flow._page is not None and getattr(flow._page, 'context', None) is not self.context)
                or self.session_id is None or flow.browser_session_id() != self.session_id
                or threading.get_ident() != self.owner_thread
                or flow._is_playwright_object_closed(self.context)
                or not flow._is_browser_connected(self.browser)):
            self.stopped = True
            flow._clear_browser_context_generation()
            raise RuntimeError('MANAGED_MANUAL_LOGIN_STOPPED')
        return self.context

    def _closed(self, *_args):
        self.stopped = True


def _state(flow, *, opened, opening=False):
    state = {**flow._default_state(), 'ok': opened,
        'stage': 'manual_login_required' if opened else 'manual_login_stopped',
        'reason_code': 'MANAGED_MANUAL_LOGIN_REQUIRED' if opened else 'MANAGED_MANUAL_LOGIN_OPEN_FAILED',
        'label': '请在新窗口手动登录' if opened else '受管登录窗口未建立',
        'message': '已建立全新受管窗口，请手动完成登录。' if opened else '本次建立失败，执行已停止；原窗口保持原状。',
        'next_action': '在新窗口完成登录后回到工作台检测。' if opened else '检查错误后重新建立受管登录窗口。',
        'logged_in': False, 'reader_ready': False, 'requires_user_action': True,
        'browser_session_id': flow.browser_session_id() if opened else None,
        'browser_visible': opened, 'page_url': LOGIN_URL if opened else None,
        'executionAllowed': False, 'capabilityCertified': False, 'updated_at': now_iso()}
    if opening:
        state.update(stage='manual_login_opening', reason_code='MANAGED_MANUAL_LOGIN_OPENING',
            label='正在建立受管登录窗口', message='旧登录资格已撤销，正在建立新窗口。',
            next_action='等待窗口建立完成；当前没有登录或执行资格。')
    return state


def _validate_owner(flow):
    if flow._is_headless():
        raise RuntimeError('MANAGED_MANUAL_LOGIN_VISIBLE_BROWSER_REQUIRED')
    owner_thread = flow._browser_session_thread_id
    if owner_thread is not None and owner_thread != threading.get_ident():
        raise RuntimeError('MANAGED_MANUAL_LOGIN_OWNER_THREAD_MISMATCH')
    if flow._browser is not None and (owner_thread is None or not flow._is_browser_connected(flow._browser)):
        raise RuntimeError('MANAGED_MANUAL_LOGIN_BROWSER_UNAVAILABLE')
    previous = getattr(flow, '_managed_manual_login', None)
    if previous is not None and not previous.stopped:
        raise RuntimeError('MANAGED_MANUAL_LOGIN_ALREADY_OPEN')


def open_managed_manual_login(flow):
    """调用者须先排除批次、lease 和 takeover；只由现有会话 owner 线程执行。"""
    try:
        _validate_owner(flow)
    except Exception as exc:
        log_exception(_LOGGER, 'managed_manual_login_precondition_failed', exc)
        raise

    previous_pin = flow._managed_manual_login
    owner = ManualLoginContext(flow._browser, threading.get_ident())
    bootstrap_complete = flow._browser is not None
    try:
        flow.clear_mutation_authorizer()
        flow.clear_execution_evidence_context()
        flow._clear_browser_context_generation()
        # 先持久撤销旧资格，再进入任何可能绑定新 session 的引导或 RPC。
        flow._write_state(_state(flow, opened=False, opening=True))
        close_native_video_lifetime(flow)
        if flow._browser is None:
            # 仅冷启动借用既有 Chrome 引导；不向旧页恢复 Cookie 或注入任务 HUD。
            if previous_pin is not None and previous_pin.stopped:
                # 只有显式重开可卸下已停止的 pin；引导失败必须恢复原拒绝边界。
                flow._managed_manual_login = None
            previous_hud = flow._latest_live_hud
            flow._latest_live_hud = None
            try:
                flow._ensure_page()
                _validate_owner(flow)
                bootstrap_complete = True
            finally:
                flow._latest_live_hud = previous_hud
                if not bootstrap_complete:
                    flow._managed_manual_login = previous_pin
        owner.browser = flow._browser
        flow._managed_manual_login = owner
        flow._clear_browser_context_generation()
        flow._context = flow._page = None
        owner.context = create_managed_browser_context(owner.browser)
        owner.context.on('close', owner._closed)
        flow._context = owner.context
        flow._page = owner.context.new_page()
        owner.session_id = flow._bind_browser_context_generation(owner.context)
        owner.require_context(flow)
        timeout = get_config_bus().integer('DXM_MANUAL_LOGIN_NAVIGATION_TIMEOUT_MS', 45000,
            minimum=1000, maximum=60000)
        flow._goto_sterile(flow._page, LOGIN_URL, wait_until='domcontentloaded', timeout=timeout)
        owner.require_context(flow)
        if not bring_controlled_page_to_front(flow._page):
            raise RuntimeError('MANAGED_MANUAL_LOGIN_FOCUS_FAILED')
        owner.require_context(flow)
        state = _state(flow, opened=True)
        flow._write_state(state)
        _LOGGER.info('managed_manual_login_window_opened')
        return state
    except Exception as exc:
        owner.stopped = True
        flow._managed_manual_login = previous_pin if not bootstrap_complete and previous_pin is not None else owner
        log_exception(_LOGGER, 'managed_manual_login_open_failed', exc)
        flow._clear_browser_context_generation()
        flow._context = flow._page = None
        if owner.context is not None:
            try:
                owner.context.close()
            except Exception as cleanup_exc:
                log_exception(_LOGGER, 'managed_manual_login_new_context_cleanup_failed', cleanup_exc)
        try:
            flow._write_state(_state(flow, opened=False))
        except Exception as state_exc:
            log_exception(_LOGGER, 'managed_manual_login_failure_state_failed', state_exc)
        raise RuntimeError('MANAGED_MANUAL_LOGIN_OPEN_FAILED') from exc
