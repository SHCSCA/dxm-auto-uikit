"""受管登录的失效边界只记录布尔事实，不恢复旧上下文。"""

import threading

from src.services.structured_logging import get_logger, log_event


class ManualLoginSessionInvalidError(RuntimeError):
    reason_code = 'MANAGED_MANUAL_LOGIN_STOPPED'

    def __init__(self):
        super().__init__(self.reason_code)


def require_manual_login_context(owner, flow):
    context = owner.context
    checks = {
        'not_stopped': not owner.stopped,
        'context_present': context is not None,
        'context_current': flow._context is context,
        'browser_current': flow._browser is owner.browser,
        'flow_thread_current': flow._browser_session_thread_id == owner.owner_thread,
        'page_context_current': flow._page is None or getattr(flow._page, 'context', None) is context,
        'session_present': owner.session_id is not None,
        'session_current': flow.browser_session_id() == owner.session_id,
        'calling_thread_current': threading.get_ident() == owner.owner_thread,
        'context_open': context is not None and not flow._is_playwright_object_closed(context),
        'browser_connected': owner.browser is not None and flow._is_browser_connected(owner.browser),
    }
    if not all(checks.values()):
        # 撤销前保留首次边界，避免后续轮询只看到已停止或已清空的代次。
        if getattr(owner, '_first_invalid_checks', None) is None:
            owner._first_invalid_checks = dict(checks)
            log_event(get_logger('manual_login.context'), 'managed_manual_login_context_invalid',
                level='WARNING', checks=checks,
                failed_checks=[name for name, valid in checks.items() if not valid])
        owner.stopped = True
        flow._clear_browser_context_generation()
        raise ManualLoginSessionInvalidError()
    return context
