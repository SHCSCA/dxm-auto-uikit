"""统一受管上下文的创建与失败清理；不追认外部接入的既有上下文。"""

from src.execution.native_video_transport import prepare_native_video_transport
from src.services.structured_logging import get_logger, log_exception


def create_managed_browser_context(browser):
    context = None
    logger = get_logger('browser.context')
    try:
        context = browser.new_context(ignore_https_errors=True, viewport={'width': 1440, 'height': 1024},
            service_workers='block', accept_downloads=False)
        prepare_native_video_transport(context)
        return context
    except Exception as exc:
        log_exception(logger, 'managed_browser_context_creation_failed', exc)
        if context is not None:
            try:
                context.close()
            except Exception as cleanup_exc:
                log_exception(logger, 'managed_browser_context_cleanup_failed', cleanup_exc)
        raise
