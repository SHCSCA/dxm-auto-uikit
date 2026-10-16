"""被动采集的范围和摘要；完整采集也不表示原生门已放行。"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urlsplit

from src.core.config_bus import get_config_bus


class NativeGateCaptureError(ValueError):
    def __init__(self, reason):
        self.reason_code = reason if reason in _REASONS else "NATIVE_GATE_CAPTURE_OBSERVATION_FAILED"
        super().__init__(self.reason_code)


_REASONS = frozenset("NATIVE_GATE_CAPTURE_" + value for value in (
    "SCOPE_INVALID", "PAGE_INVALID", "HEADERS_UNAVAILABLE", "BODY_SIZE_INVALID", "BODY_UNAVAILABLE",
    "BODY_TOO_LARGE", "BODY_LENGTH_UNPROVEN", "BODY_NOT_FINISHED", "BODY_FORMAT_UNREVIEWED",
    "WIRE_BODY_UNPROVEN", "JSON_DUPLICATE_KEY", "JSON_INVALID", "TIME_INVALID",
    "CONFIGURATION_INVALID", "SCOPE_DRIFT", "TIME_REGRESSION", "WINDOW_EXPIRED", "WINDOW_REUSED",
    "PAGE_DRIFT", "START_FAILED", "EVENT_LIMIT", "REQUEST_SCOPE_INVALID", "OBSERVATION_FAILED",
    "DUPLICATE_REQUEST", "ORPHAN_RESPONSE", "DUPLICATE_RESPONSE", "RESPONSE_INVALID", "HTTP_NON_SUCCESS",
    "REQUEST_FAILED", "CALLER_FAILED", "CLOSE_FAILED", "LISTENER_REMOVAL_UNAVAILABLE",
    "LISTENER_REMOVAL_FAILED", "WINDOW_OPEN", "LISTENERS_INCOMPLETE", "PAIR_NOT_UNIQUE", "DUPLICATE_FINISH",
))


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class NativeGateCaptureLimits:
    max_body_bytes: int
    max_events: int
    max_window_seconds: float

    @classmethod
    def from_config_bus(cls):
        bus = get_config_bus()
        return cls(
            bus.integer("DXM_NATIVE_GATE_CAPTURE_MAX_BODY_BYTES", 65536, minimum=128, maximum=1048576),
            bus.integer("DXM_NATIVE_GATE_CAPTURE_MAX_EVENTS", 16, minimum=3, maximum=128),
            bus.number("DXM_NATIVE_GATE_CAPTURE_MAX_WINDOW_SECONDS", 60, minimum=1, maximum=300),
        )


@dataclass(frozen=True)
class NativeGateCaptureScope:
    task_id: int
    job_id: int
    product_id: str
    entry_handshake_id: str
    first_save_command_id: str
    browser_session_id: str
    target_identity_sha256: str
    snapshot_sha256: str
    scope_sha256: str
    source_page_url: str

    def validate(self):
        if any(type(value) is not int or value <= 0 for value in (self.task_id, self.job_id)):
            raise NativeGateCaptureError("NATIVE_GATE_CAPTURE_SCOPE_INVALID")
        if any(not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > 256
               for value in (self.product_id, self.entry_handshake_id, self.first_save_command_id, self.browser_session_id)):
            raise NativeGateCaptureError("NATIVE_GATE_CAPTURE_SCOPE_INVALID")
        if re.fullmatch(r"[1-9][0-9]*", self.product_id) is None:
            raise NativeGateCaptureError("NATIVE_GATE_CAPTURE_SCOPE_INVALID")
        if any(not isinstance(value, str) or re.fullmatch(r"[0-9a-fA-F]{64}", value) is None
               for value in (self.target_identity_sha256, self.snapshot_sha256, self.scope_sha256)):
            raise NativeGateCaptureError("NATIVE_GATE_CAPTURE_SCOPE_INVALID")
        parts = urlsplit(self.source_page_url)
        query = parse_qs(parts.query, keep_blank_values=True)
        if (parts.scheme != "https" or parts.netloc != "www.dianxiaomi.com" or parts.path != "/web/smt/edit"
                or parts.fragment or query != {"id": [self.product_id]}):
            raise NativeGateCaptureError("NATIVE_GATE_CAPTURE_PAGE_INVALID")
        return asdict(self)


@dataclass(frozen=True)
class NativeGateCaptureStamp:
    wall_time: datetime
    monotonic_seconds: float

    def timestamp(self):
        if (not isinstance(self.wall_time, datetime) or self.wall_time.utcoffset() is None
                or self.wall_time.utcoffset().total_seconds() != 0):
            raise NativeGateCaptureError("NATIVE_GATE_CAPTURE_TIME_INVALID")
        return self.wall_time.isoformat(timespec="microseconds").replace("+00:00", "Z")


def capture_clock():
    return NativeGateCaptureStamp(datetime.now(timezone.utc), time.monotonic())


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise NativeGateCaptureError("NATIVE_GATE_CAPTURE_JSON_DUPLICATE_KEY")
        result[key] = value
    return result


def body_facts(owner, kind, limit):
    """仅导出摘要；未知格式或超限不补正文、不补 canonical hash。"""
    headers = owner.headers
    if not isinstance(headers, dict):
        raise NativeGateCaptureError("NATIVE_GATE_CAPTURE_HEADERS_UNAVAILABLE")
    headers = {str(key).lower(): value for key, value in headers.items()}
    declared = headers.get("content-length")
    if declared is not None and (not isinstance(declared, str) or re.fullmatch(r"[0-9]+", declared) is None or int(declared) > limit):
        raise NativeGateCaptureError("NATIVE_GATE_CAPTURE_BODY_SIZE_INVALID")
    empty = {"raw_body_sha256": None, "wire_body_sha256": None, "canonical_body_sha256": None,
             "body_source": "playwright_response_body", "body_size": None, "body_format": "unreviewed"}
    if kind == "response" and declared is None:
        return empty, "NATIVE_GATE_CAPTURE_BODY_LENGTH_UNPROVEN"
    if kind == "response" and str(headers.get("content-encoding", "identity")).lower() != "identity":
        return empty, "NATIVE_GATE_CAPTURE_WIRE_BODY_UNPROVEN"
    raw = owner.post_data_buffer if kind == "request" else owner.body()
    if not isinstance(raw, bytes):
        raise NativeGateCaptureError("NATIVE_GATE_CAPTURE_BODY_UNAVAILABLE")
    if len(raw) > limit:
        raise NativeGateCaptureError("NATIVE_GATE_CAPTURE_BODY_TOO_LARGE")
    raw_hash = hashlib.sha256(raw).hexdigest()
    # 压缩响应提前关闭正文读取；仅 identity 正文可同时导出 raw 与 wire 摘要。
    result = {"raw_body_sha256": raw_hash, "wire_body_sha256": raw_hash,
              "body_source": "playwright_post_data_buffer" if kind == "request" else "playwright_response_body",
              "body_size": len(raw),
              "canonical_body_sha256": None, "body_format": "unreviewed"}
    if str(headers.get("content-type", "")).split(";", 1)[0].strip().lower() != "application/json":
        return result, "NATIVE_GATE_CAPTURE_BODY_FORMAT_UNREVIEWED"
    try:
        def reject_constant(_value):
            raise NativeGateCaptureError("NATIVE_GATE_CAPTURE_JSON_INVALID")
        parsed = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_object, parse_constant=reject_constant)
        if not isinstance(parsed, dict):
            return result, "NATIVE_GATE_CAPTURE_BODY_FORMAT_UNREVIEWED"
        result.update(canonical_body_sha256=canonical_digest(parsed), body_format="json_object")
    except NativeGateCaptureError as exc:
        return result, str(exc)
    except (UnicodeError, ValueError, RecursionError):
        return result, "NATIVE_GATE_CAPTURE_JSON_INVALID"
    return result, None
