from __future__ import annotations

import re
import uuid

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from src.services.structured_logging import get_logger, log_event, log_exception


_LOGGER = get_logger("http")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


def _request_context(request: Request) -> dict[str, str]:
    candidate = request.headers.get("x-request-id", "")
    return {
        "request_id": candidate if _REQUEST_ID.fullmatch(candidate) else uuid.uuid4().hex,
        "method": request.method,
        "path": request.url.path,
    }


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        context = _request_context(request)
        log_event(_LOGGER, "http_request_rejected", level="WARNING", status_code=exc.status_code,
                  detail=exc.detail, **context)
        return JSONResponse({"detail": jsonable_encoder(exc.detail)}, status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        context = _request_context(request)
        # 只保留字段定位和规则，避免把密码等原始请求值回显到日志或响应。
        errors = [{key: value for key, value in error.items() if key in {"type", "loc", "msg"}}
                  for error in exc.errors()]
        log_event(_LOGGER, "http_request_validation_failed", level="WARNING", errors=errors, **context)
        return JSONResponse({"detail": jsonable_encoder(errors)}, status_code=422)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        context = _request_context(request)
        log_exception(_LOGGER, "http_unhandled_exception", exc, **context)
        # 此处只处理 HTTP 边界；派发账本、UNKNOWN 和重试裁决仍由原有执行链负责。
        return JSONResponse({"detail": {
            "reason_code": "UNEXPECTED_SERVER_ERROR",
            "message": "本机服务处理失败，操作结果未确认，请刷新状态并核对真实页面。",
            "request_id": context["request_id"],
        }}, status_code=500)
