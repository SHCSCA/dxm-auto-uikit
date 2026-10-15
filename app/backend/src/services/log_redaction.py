from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any


REDACTED = "[REDACTED]"
_SECRET_KEY = re.compile(r"password|passwd|passphrase|cookie|authorization|token|csrf|xsrf|secret|api[_-]?key|sessionid", re.I)
_RAW_KEY = re.compile(r"^(html|raw_html|raw_response|raw_body|page_source)$", re.I)
_AUTH = re.compile(r"\bBearer\s+[^\s,;\"']+", re.I)
_HEADERS = re.compile(r"\b(cookie|set-cookie|authorization)(\s*[:=]\s*)[^\r\n]+", re.I)
_QUOTED_SECRET = re.compile(
    r"\b(password|passwd|cookie|authorization|token|csrf|xsrf|secret|api[_-]?key|sessionid)"
    r"([\"']?\s*[:=]\s*)(\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*')", re.I | re.S,
)
_SECRET_PREFIX = re.compile(
    r"\b(password|passwd|cookie|set-cookie|authorization|token|csrf|xsrf|secret|api[_-]?key|sessionid)"
    r"((?:\\*[\"'])?\s*[:=]\s*)", re.I,
)
_PRIVATE_KEY = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}")
_URL_QUERY = re.compile(r"(https?://[^\s?#\"']+)\?[^\s\"']+", re.I)


def redact_text(value: str, *, depth: int = 0) -> str:
    if depth > 12:
        return "[DEPTH_LIMIT]"
    result = _redact_embedded_json(value, depth=depth)
    for match in _SECRET_PREFIX.finditer(result):
        if not result[match.end():].lstrip("\\\"'").startswith(REDACTED):
            # 非结构化或未闭合秘密的边界不可信，保守丢弃其后全部文本。
            result = result[:match.end()] + REDACTED
            break
    result = _HEADERS.sub(lambda match: match[1] + match[2] + REDACTED, result)
    result = _QUOTED_SECRET.sub(lambda match: match[1] + match[2] + match[3][0] + REDACTED + match[3][0], result)
    result = _AUTH.sub("Bearer " + REDACTED, result)
    result = _PRIVATE_KEY.sub(REDACTED, result)
    result = _URL_QUERY.sub(r"\1?[REDACTED]", result)
    return result


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
        if isinstance(parsed, (dict, list, str)):
            parts.extend((value[cursor:index], json.dumps(redact_log_value(parsed, depth=depth + 1), ensure_ascii=False)))
            cursor = index = end
        else:
            index += 1
    parts.append(value[cursor:])
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
