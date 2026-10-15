"""每条浏览器命令固定配置，并在异常退出时记录统一日志。"""

from functools import wraps

from src.core.config_bus import configuration_scope
from src.services.structured_logging import get_logger, log_exception


logger = get_logger("browser_action")


def configured_action(function):
    @wraps(function)
    def execute(adapter, action, params=None):
        with configuration_scope():
            try:
                return function(adapter, action, params)
            except Exception as exc:
                log_exception(logger, "browser_action_failed", exc, action=action)
                raise
    return execute
