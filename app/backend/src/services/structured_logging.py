from __future__ import annotations

import json
import logging
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

from src.services.log_redaction import redact_log_value, redact_text


SCHEMA_VERSION = "dxm.log.v1"


def build_log_record(event: str, *, component: str, level: str = "INFO", **fields: Any) -> dict[str, Any]:
    return {
        "schema": SCHEMA_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "level": level.upper(),
        "component": component,
        "event": redact_text(event),
        "fields": redact_log_value(fields),
    }


class StructuredLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        fields = dict(getattr(record, "event_fields", {}))
        if record.exc_info:
            exc = record.exc_info[1]
            fields.update(exception_type=type(exc).__name__, exception_message=str(exc))
            fields["traceback"] = "".join(traceback.format_exception(*record.exc_info))
        payload = build_log_record(record.getMessage(), component=record.name, level=record.levelname, **fields)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO", stream: TextIO | None = None) -> logging.Handler:
    root = logging.getLogger()
    handler = next((item for item in root.handlers if getattr(item, "dxm_managed", False)), None)
    if handler is None:
        handler = logging.StreamHandler(stream or sys.stderr)
        handler.dxm_managed = True
        root.addHandler(handler)
    elif stream is not None:
        handler.setStream(stream)
    handler.setFormatter(StructuredLogFormatter())
    handler.setLevel(level)
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        for server_handler in logging.getLogger(name).handlers:
            server_handler.setFormatter(StructuredLogFormatter())
    return handler


def get_logger(component: str) -> logging.Logger:
    return logging.getLogger(f"dxm.{component}")


def log_event(logger: logging.Logger, event: str, *, level: str = "INFO", **fields: Any) -> None:
    logger.log(logging._nameToLevel[level.upper()], event, extra={"event_fields": fields})


def log_exception(logger: logging.Logger, event: str, exc: BaseException, **fields: Any) -> None:
    logger.error(event, extra={"event_fields": fields}, exc_info=(type(exc), exc, exc.__traceback__))


def structured_log_level(line: str) -> str | None:
    if not line.startswith("{"):
        return None
    try:
        payload = json.loads(line)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA_VERSION:
        return None
    level = str(payload.get("level", "")).lower()
    return {"debug": "info", "critical": "error"}.get(level, level if level in {"info", "warning", "error"} else None)


def append_structured_log(path: Path, event: str, *, component: str, level: str = "INFO", **fields: Any) -> bool:
    payload = build_log_record(event, component=component, level=level, **fields)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
        return True
    except OSError as exc:
        # 日志失败不能改变业务结果，但必须向托管进程的 stderr 留下可追踪事实。
        diagnostic = build_log_record("log_write_failed", component=component, level="ERROR",
                                      exception_type=type(exc).__name__, exception_message=str(exc))
        sys.stderr.write(json.dumps(diagnostic, ensure_ascii=False) + "\n")
        return False
