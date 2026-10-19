"""Reader HTTP 失败的脱敏诊断；关联标识与时间均不提供业务或会话资格。"""

import logging
from datetime import datetime, timezone
from uuid import uuid4

from src.services.structured_logging import StructuredLogFormatter, get_logger, log_event


_LOGGER = get_logger('reader.http')
_OPERATIONS = frozenset({'draft_reader', 'authenticated_user_info'})
_FALLBACK = logging.Logger('dxm.reader.http.fallback')
_FALLBACK.propagate = False
_HANDLER = logging.StreamHandler()
_HANDLER.setFormatter(StructuredLogFormatter())
_HANDLER.handleError = lambda _record: None
_FALLBACK.addHandler(_HANDLER)


def _exception_type(exc):
    for kind in (AttributeError, TypeError, ValueError, RuntimeError, OSError):
        if isinstance(exc, kind):
            return kind.__name__
    return 'Exception'


def log_reader_diagnostic(event, **fields):
    """调用方只传固定脱敏字段；日志出口失败不得遮蔽原读取结果。"""
    try:
        log_event(_LOGGER, event, level='WARNING', **fields)
    except Exception as exc:
        try:
            _FALLBACK.warning('reader_http_observation_log_failed',
                extra={'event_fields': {'exception_type': _exception_type(exc)}})
        except Exception:
            pass  # 所有日志出口失效时仍须保留原 Reader 失败与清理路径。


def _cached_value(response, name, valid, *, request_id, operation):
    try:
        value = getattr(response, name)
        if not valid(value):
            raise TypeError()
        return value, False
    except Exception as exc:
        log_reader_diagnostic('reader_http_observation_property_failed', request_id=request_id,
            operation=operation, property=name, exception_type=_exception_type(exc))
        return None, True


def observe_reader_http_failure(response, *, operation='draft_reader'):
    """只读缓存属性；调用方仍须执行原 HTTP 校验并抛出原 Reader 错误。"""
    facts = {'operation': 'unknown', 'request_id': None, 'observed_at': None,
        'http_status': None, 'ok': None, 'read_error_count': 0}
    try:
        facts['request_id'] = uuid4().hex
        facts['observed_at'] = datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
        if type(operation) is str and operation in _OPERATIONS:
            facts['operation'] = operation
        else:
            log_reader_diagnostic('reader_http_observation_operation_invalid', request_id=facts['request_id'])
        common = {'request_id': facts['request_id'], 'operation': facts['operation']}
        # APIResponse 的 status/ok 为缓存属性；禁止扩展到响应体或网络读取方法。
        facts['http_status'], status_failed = _cached_value(response, 'status',
            lambda value: type(value) is int and 100 <= value <= 599, **common)
        facts['ok'], ok_failed = _cached_value(response, 'ok',
            lambda value: type(value) is bool, **common)
        facts['read_error_count'] = int(status_failed) + int(ok_failed)
        log_reader_diagnostic('reader_http_failure_observed', **facts)
    except Exception as exc:
        log_reader_diagnostic('reader_http_observation_failed', request_id=facts['request_id'],
            operation=facts['operation'], exception_type=_exception_type(exc))
    return facts
