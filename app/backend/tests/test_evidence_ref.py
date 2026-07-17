import hashlib
import struct
import zlib
from pathlib import Path

import pytest

from src.services.evidence_ref import validate_evidence_ref


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _descriptor(path: Path) -> dict:
    content = path.read_bytes()
    return {
        "path": str(path.resolve()),
        "sha256": hashlib.sha256(content).hexdigest().upper(),
        "size": len(content),
    }


def _chunk(chunk_type: bytes, data: bytes, *, crc: int | None = None) -> bytes:
    checksum = zlib.crc32(chunk_type + data) & 0xFFFFFFFF if crc is None else crc
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", checksum)


def _ihdr(*, width: int = 1, height: int = 1, data: bytes | None = None) -> bytes:
    payload = data if data is not None else struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return _chunk(b"IHDR", payload)


def _valid_png() -> bytes:
    scanline = b"\x00\x00\x00\x00\x00"
    return PNG_SIGNATURE + _ihdr() + _chunk(b"IDAT", zlib.compress(scanline)) + _chunk(b"IEND", b"")


def _validate_bytes(tmp_path: Path, content: bytes) -> dict:
    screenshot_root = tmp_path / "screenshots"
    screenshot_root.mkdir(exist_ok=True)
    path = screenshot_root / "proof.png"
    path.write_bytes(content)
    return validate_evidence_ref(
        _descriptor(path),
        screenshot_root=screenshot_root,
    )


def test_validate_evidence_ref_accepts_complete_png_chunk_stream(tmp_path):
    result = _validate_bytes(tmp_path, _valid_png())

    assert result["ok"] is True
    assert result["reason_code"] == "OK"


def test_validate_evidence_ref_rejects_signature_only_fake_png(tmp_path):
    result = _validate_bytes(tmp_path, PNG_SIGNATURE + b"not-a-png-chunk-stream")

    assert result == {
        "ok": False,
        "reason_code": "EVIDENCE_REF_PNG_STRUCTURE_INVALID",
    }


@pytest.mark.parametrize(
    ("content", "reason_code"),
    [
        (
            PNG_SIGNATURE + _chunk(b"IDAT", zlib.compress(b"\x00")) + _chunk(b"IEND", b""),
            "EVIDENCE_REF_PNG_STRUCTURE_INVALID",
        ),
        (
            PNG_SIGNATURE + _ihdr(data=b"\x00" * 12) + _chunk(b"IDAT", zlib.compress(b"\x00")) + _chunk(b"IEND", b""),
            "EVIDENCE_REF_PNG_STRUCTURE_INVALID",
        ),
        (
            PNG_SIGNATURE + _ihdr(width=0) + _chunk(b"IDAT", zlib.compress(b"\x00")) + _chunk(b"IEND", b""),
            "EVIDENCE_REF_PNG_DIMENSIONS_INVALID",
        ),
        (
            PNG_SIGNATURE + _ihdr() + _chunk(b"IEND", b""),
            "EVIDENCE_REF_PNG_STRUCTURE_INVALID",
        ),
        (
            PNG_SIGNATURE + _ihdr() + _chunk(b"IDAT", zlib.compress(b"\x00")),
            "EVIDENCE_REF_PNG_STRUCTURE_INVALID",
        ),
        (
            PNG_SIGNATURE + struct.pack(">I", 100) + b"IHDR" + b"short",
            "EVIDENCE_REF_PNG_STRUCTURE_INVALID",
        ),
        (
            PNG_SIGNATURE + _chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0), crc=0)
            + _chunk(b"IDAT", zlib.compress(b"\x00"))
            + _chunk(b"IEND", b""),
            "EVIDENCE_REF_PNG_CRC_INVALID",
        ),
        (
            PNG_SIGNATURE + _ihdr() + _chunk(b"IDAT", zlib.compress(b"\x00")) + _chunk(b"IEND", b"x"),
            "EVIDENCE_REF_PNG_STRUCTURE_INVALID",
        ),
        (
            _valid_png() + b"trailing",
            "EVIDENCE_REF_PNG_TRAILING_DATA",
        ),
    ],
)
def test_validate_evidence_ref_rejects_malformed_png_chunk_stream(
    tmp_path,
    content,
    reason_code,
):
    result = _validate_bytes(tmp_path, content)

    assert result == {"ok": False, "reason_code": reason_code}
