from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any


REDACTED = "[REDACTED]"
_SECRET_NAMES = r"password|passwd|passphrase|cookie|set-cookie|authorization|token|csrf|xsrf|secret|api[_-]?key|sessionid"
_SECRET_KEY = re.compile(_SECRET_NAMES, re.I)
_RAW_KEY = re.compile(r"^(html|raw_html|raw_response|raw_body|page_source)$", re.I)
_AUTH = re.compile(r"\bBearer\s+[^\s,;\"']+", re.I)
_SECRET_PREFIX = re.compile(
    rf"\b({_SECRET_NAMES})"
    r"((?:\\*[\"'])?\s*[:=]\s*)", re.I,
)
_PRIVATE_KEY = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}")
_URL_QUERY = re.compile(r"(https?://[^\s?#\"']+)\?[^\s\"']+", re.I)


def redact_text(value: str, *, depth: int = 0) -> str:
    if depth > 12:
        return "[DEPTH_LIMIT]"
    return _redact_embedded_json(value, depth=depth)


def _redact_plain_text(value: str) -> tuple[str, bool]:
    match = _SECRET_PREFIX.search(value)
    # 文本里的脱敏标记也可能是秘密前缀；边界不可信时丢弃后续所有片段。
    result = value[:match.end()] + REDACTED if match else value
    result = _AUTH.sub("Bearer " + REDACTED, result)
    result = _PRIVATE_KEY.sub(REDACTED, result)
    result = _URL_QUERY.sub(r"\1?[REDACTED]", result)
    return result, match is not None


def _redact_embedded_json(value: str, *, depth: int) -> str:
    decoder = json.JSONDecoder()
    parts, cursor, index = [], 0, 0
    while index < len(value):
        if value[index] not in '{["':
            index += 1
            continue
        try:
            parsed, end = decoder.raw_decode(value, index)
        except (ValueError, RecursionError):
            index += 1
            continue
        if isinstance(parsed, str) and not parsed.lstrip().startswith(('{', '[', '"')) and (
            value[:index].strip() or value[end:].strip()
        ):
            # 不把损坏对象里的单独键名隔离出去，避免切断秘密键和值的关联。
            index += 1
            continue
        if isinstance(parsed, (dict, list, str)):
            plain, truncated = _redact_plain_text(value[cursor:index])
            parts.append(plain)
            if truncated:
                return "".join(parts)
            # 已解析片段只在值上脱敏，不再跨 JSON 边界运行文本正则。
            parts.append(json.dumps(redact_log_value(parsed, depth=depth + 1), ensure_ascii=False))
            cursor = index = end
        else:
            index += 1
    parts.append(_redact_plain_text(value[cursor:])[0])
    return "".join(parts)


def redact_log_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 12:
        return "[DEPTH_LIMIT]"
    if isinstance(value, Mapping):
        return {
            str(key): REDACTED if _SECRET_KEY.search(str(key)) else "[OMITTED]" if _RAW_KEY.fullmatch(str(key))
            else redact_log_value(item, depth=depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_log_value(item, depth=depth + 1) for item in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact_text(str(value), depth=depth + 1)
