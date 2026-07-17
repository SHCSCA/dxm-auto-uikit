from __future__ import annotations

import hashlib
import hmac
import re
import zlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_EVIDENCE_REF_KEYS = frozenset({"path", "sha256", "size"})


def validate_evidence_ref(
    value: Any,
    *,
    screenshot_root: Path,
) -> dict[str, Any]:
    """Validate an immutable screenshot descriptor against its live file."""
    if not isinstance(value, Mapping) or set(value) != _EVIDENCE_REF_KEYS:
        return _invalid("EVIDENCE_REF_SHAPE_INVALID")

    path_value = value.get("path")
    sha256_value = value.get("sha256")
    size_value = value.get("size")
    if not isinstance(path_value, str) or not path_value.strip():
        return _invalid("EVIDENCE_REF_PATH_INVALID")
    if (
        not isinstance(sha256_value, str)
        or re.fullmatch(r"[0-9a-fA-F]{64}", sha256_value) is None
    ):
        return _invalid("EVIDENCE_REF_SHA256_INVALID")
    if isinstance(size_value, bool) or not isinstance(size_value, int) or size_value <= 0:
        return _invalid("EVIDENCE_REF_SIZE_INVALID")

    raw_path = Path(path_value).expanduser()
    if not raw_path.is_absolute():
        return _invalid("EVIDENCE_REF_PATH_NOT_ABSOLUTE")
    if ".." in raw_path.parts:
        return _invalid("EVIDENCE_REF_PATH_TRAVERSAL")

    try:
        root = Path(screenshot_root).expanduser().resolve(strict=True)
        evidence_path = raw_path.resolve(strict=True)
    except (OSError, RuntimeError):
        return _invalid("EVIDENCE_REF_FILE_UNAVAILABLE")
    try:
        evidence_path.relative_to(root)
    except ValueError:
        return _invalid("EVIDENCE_REF_OUTSIDE_SCREENSHOT_DIR")
    if evidence_path.suffix.casefold() != ".png":
        return _invalid("EVIDENCE_REF_EXTENSION_INVALID")
    if not evidence_path.is_file():
        return _invalid("EVIDENCE_REF_NOT_REGULAR_FILE")

    try:
        content = evidence_path.read_bytes()
    except OSError:
        return _invalid("EVIDENCE_REF_FILE_UNREADABLE")
    if len(content) != size_value:
        return _invalid("EVIDENCE_REF_SIZE_MISMATCH")
    if not content.startswith(PNG_SIGNATURE):
        return _invalid("EVIDENCE_REF_PNG_SIGNATURE_INVALID")
    actual_sha256 = hashlib.sha256(content).hexdigest()
    if not hmac.compare_digest(actual_sha256.casefold(), sha256_value.casefold()):
        return _invalid("EVIDENCE_REF_SHA256_MISMATCH")
    png_error = _validate_png_chunk_stream(content)
    if png_error is not None:
        return _invalid(png_error)
    return {
        "ok": True,
        "reason_code": "OK",
        "path": str(evidence_path),
        "sha256": actual_sha256.upper(),
        "size": len(content),
    }


def _invalid(reason_code: str) -> dict[str, Any]:
    return {"ok": False, "reason_code": reason_code}


def _validate_png_chunk_stream(content: bytes) -> str | None:
    """Return a stable reason code unless the complete PNG chunk stream is valid."""
    offset = len(PNG_SIGNATURE)
    chunk_index = 0
    saw_idat = False
    while offset < len(content):
        if len(content) - offset < 12:
            return "EVIDENCE_REF_PNG_STRUCTURE_INVALID"

        length = int.from_bytes(content[offset : offset + 4], "big")
        chunk_type = content[offset + 4 : offset + 8]
        data_start = offset + 8
        data_end = data_start + length
        chunk_end = data_end + 4
        if data_end < data_start or chunk_end > len(content):
            return "EVIDENCE_REF_PNG_STRUCTURE_INVALID"

        chunk_data = content[data_start:data_end]
        expected_crc = int.from_bytes(content[data_end:chunk_end], "big")
        actual_crc = zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            return "EVIDENCE_REF_PNG_CRC_INVALID"

        if chunk_index == 0:
            if chunk_type != b"IHDR" or length != 13:
                return "EVIDENCE_REF_PNG_STRUCTURE_INVALID"
            width = int.from_bytes(chunk_data[0:4], "big")
            height = int.from_bytes(chunk_data[4:8], "big")
            if width <= 0 or height <= 0:
                return "EVIDENCE_REF_PNG_DIMENSIONS_INVALID"
        elif chunk_type == b"IHDR":
            return "EVIDENCE_REF_PNG_STRUCTURE_INVALID"

        if chunk_type == b"IDAT":
            saw_idat = True
        if chunk_type == b"IEND":
            if length != 0 or not saw_idat:
                return "EVIDENCE_REF_PNG_STRUCTURE_INVALID"
            if chunk_end != len(content):
                return "EVIDENCE_REF_PNG_TRAILING_DATA"
            return None

        offset = chunk_end
        chunk_index += 1

    return "EVIDENCE_REF_PNG_STRUCTURE_INVALID"
