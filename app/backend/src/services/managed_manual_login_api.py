"""受控手动登录的窄 API；只调用既有会话 owner，不接受凭证或业务写入。"""

from collections.abc import Mapping

from fastapi import APIRouter, HTTPException

from src.services.structured_logging import get_logger, log_event, log_exception


def _require_idle(status, *, owner_acquired=False):
    flags = ('active', 'manualTakeover', 'needsRestart', 'executionLeaseActive')
    if (not isinstance(status, Mapping) or status.get('status') not in {'idle', 'stopped'}
            or any(status.get(flag) is not False for flag in flags)
            or status.get('sessionOperationActive') is not owner_acquired
            or type(status.get('reservedCommandCount')) is not int or status['reservedCommandCount'] != 0):
        raise HTTPException(status_code=409, detail={'reason_code': 'MANAGED_MANUAL_LOGIN_RUNTIME_BUSY',
            'message': '当前浏览器仍被执行、预约或人工接管占用，不能替换登录会话。'})


def make_managed_manual_login_router(*, ensure_idle, run_session, adapter_provider, runtime_status, normalize):
    router = APIRouter()
    logger = get_logger('api.managed_manual_login')

    @router.post('/api/dxm/workflow/manual-login')
    def manual_login():
        try:
            ensure_idle()
            _require_idle(runtime_status())
            def owned_operation():
                # 排队期间任务状态可能变化，取得会话 owner 后再核验一次。
                ensure_idle()
                _require_idle(runtime_status(), owner_acquired=True)
                return adapter_provider().open_managed_manual_login()

            result = run_session(owned_operation)
            if (not isinstance(result, Mapping) or result.get('ok') is not True
                    or result.get('stage') != 'manual_login_required'
                    or result.get('reason_code') != 'MANAGED_MANUAL_LOGIN_REQUIRED'
                    or result.get('logged_in') is not False or result.get('reader_ready') is not False
                    or result.get('browser_visible') is not True):
                raise RuntimeError('MANAGED_MANUAL_LOGIN_RESULT_UNPROVEN')
            return normalize(dict(result))
        except HTTPException as exc:
            log_event(logger, 'managed_manual_login_api_rejected', level='WARNING', status_code=exc.status_code)
            raise
        except Exception as exc:
            log_exception(logger, 'managed_manual_login_api_failed', exc)
            raise HTTPException(status_code=409, detail={'reason_code': 'MANAGED_MANUAL_LOGIN_FAILED',
                'message': '受控登录窗口未能建立，详细原因已记录。当前没有新的登录或执行资格。'}) from exc

    return router
