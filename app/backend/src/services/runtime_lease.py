from __future__ import annotations

import errno
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping


LEASE_FILE_NAME = ".dxm-runtime.lock"
LEASE_SCHEMA_VERSION = "dxm.runtime.lease.v1"
_MAX_DIAGNOSTIC_BYTES = 64 * 1024


class RuntimeLeaseConflictError(RuntimeError):
    """Raised when another process owns the live OS lease for a data root."""

    def __init__(self, data_dir: Path, owner_metadata: dict[str, object] | None) -> None:
        self.data_dir = data_dir
        self.owner_metadata = owner_metadata
        rendered_metadata = (
            json.dumps(owner_metadata, ensure_ascii=False, sort_keys=True, default=str)
            if owner_metadata is not None
            else "unavailable"
        )
        super().__init__(
            "runtime data directory is already leased: "
            f"{data_dir}; diagnostic owner metadata is non-authoritative and may be stale: "
            f"{rendered_metadata}"
        )


class _AuthorityByteLockContention(RuntimeError):
    """Internal marker for a write rejected by a live byte-range lock."""


class RuntimeDataLease:
    """Owns a process-lifetime OS lock on one canonical runtime data directory.

    Production callers must retain the returned object until process teardown.
    ``release`` is intentionally an explicit API for isolated tests and owners
    whose complete lifetime is controlled by their caller; FastAPI lifespan
    cleanup must not call it for the production bootstrap lease.
    """

    def __init__(
        self,
        *,
        data_dir: Path,
        lock_path: Path,
        file_descriptor: int,
        diagnostic_metadata: dict[str, object],
    ) -> None:
        self.data_dir = data_dir
        self.lock_path = lock_path
        self._file_descriptor = file_descriptor
        self.diagnostic_metadata = diagnostic_metadata

    @classmethod
    def acquire(
        cls,
        data_dir: str | os.PathLike[str],
        *,
        metadata: Mapping[str, object] | None = None,
    ) -> RuntimeDataLease:
        canonical_data_dir = Path(data_dir).expanduser().resolve(strict=False)
        canonical_data_dir.mkdir(parents=True, exist_ok=True)
        lock_path = canonical_data_dir / LEASE_FILE_NAME
        descriptor = _open_non_inheritable(lock_path)
        locked = False
        try:
            try:
                _ensure_authority_byte(descriptor)
            except _AuthorityByteLockContention as exc:
                owner_metadata = _read_diagnostic_metadata(descriptor)
                raise RuntimeLeaseConflictError(canonical_data_dir, owner_metadata) from exc
            try:
                _lock_authority_byte(descriptor)
                locked = True
            except OSError as exc:
                owner_metadata = _read_diagnostic_metadata(descriptor)
                if _is_lock_contention(exc):
                    raise RuntimeLeaseConflictError(canonical_data_dir, owner_metadata) from exc
                raise

            diagnostic_metadata = _build_diagnostic_metadata(canonical_data_dir, metadata)
            _write_diagnostic_metadata(descriptor, diagnostic_metadata)
            return cls(
                data_dir=canonical_data_dir,
                lock_path=lock_path,
                file_descriptor=descriptor,
                diagnostic_metadata=diagnostic_metadata,
            )
        except BaseException as primary_error:
            cleanup_errors: list[tuple[str, BaseException]] = []
            if locked:
                try:
                    _unlock_authority_byte(descriptor)
                except BaseException as cleanup_error:
                    cleanup_errors.append(("unlock", cleanup_error))
            try:
                os.close(descriptor)
            except BaseException as cleanup_error:
                cleanup_errors.append(("close", cleanup_error))
            for stage, cleanup_error in cleanup_errors:
                primary_error.add_note(
                    "runtime lease cleanup "
                    f"{stage} failed: {type(cleanup_error).__name__}: {cleanup_error}"
                )
            raise

    @property
    def file_descriptor(self) -> int:
        if self._file_descriptor < 0:
            raise RuntimeError("runtime data lease has already been released")
        return self._file_descriptor

    @property
    def released(self) -> bool:
        return self._file_descriptor < 0

    def release(self) -> None:
        """Release this exact lease; intended for isolated owner tests only."""

        descriptor = self._file_descriptor
        if descriptor < 0:
            return
        self._file_descriptor = -1
        try:
            _unlock_authority_byte(descriptor)
        finally:
            os.close(descriptor)


def _open_non_inheritable(lock_path: Path) -> int:
    flags = os.O_RDWR | os.O_CREAT
    flags |= getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOINHERIT", 0)
    descriptor = os.open(lock_path, flags, 0o600)
    try:
        os.set_inheritable(descriptor, False)
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _ensure_authority_byte(descriptor: int) -> None:
    if os.fstat(descriptor).st_size >= 1:
        return
    os.lseek(descriptor, 0, os.SEEK_SET)
    try:
        written = os.write(descriptor, b"\x00")
    except OSError as exc:
        if _is_lock_contention(exc):
            raise _AuthorityByteLockContention from exc
        raise
    if written != 1:
        raise OSError(errno.EIO, "failed to create runtime lease authority byte")
    os.fsync(descriptor)


def _lock_authority_byte(descriptor: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        return

    import fcntl

    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_authority_byte(descriptor: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(descriptor, fcntl.LOCK_UN)


def _is_lock_contention(exc: OSError) -> bool:
    if exc.errno in {errno.EACCES, errno.EAGAIN}:
        return True
    return os.name == "nt" and getattr(exc, "winerror", None) in {32, 33, 36}


def _build_diagnostic_metadata(
    data_dir: Path,
    owner_metadata: Mapping[str, object] | None,
) -> dict[str, object]:
    return {
        "schemaVersion": LEASE_SCHEMA_VERSION,
        "pid": os.getpid(),
        "dataDir": str(data_dir),
        "acquiredAt": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
            "+00:00", "Z"
        ),
        "owner": dict(owner_metadata or {}),
    }


def _write_diagnostic_metadata(descriptor: int, metadata: Mapping[str, object]) -> None:
    encoded = json.dumps(
        dict(metadata),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    os.lseek(descriptor, 1, os.SEEK_SET)
    remaining = memoryview(encoded)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise OSError("failed to write runtime lease diagnostic metadata")
        remaining = remaining[written:]
    os.ftruncate(descriptor, 1 + len(encoded))
    os.fsync(descriptor)


def _read_diagnostic_metadata(descriptor: int) -> dict[str, object] | None:
    try:
        available = max(0, os.fstat(descriptor).st_size - 1)
        remaining = min(available, _MAX_DIAGNOSTIC_BYTES)
        os.lseek(descriptor, 1, os.SEEK_SET)
        chunks: list[bytes] = []
        while remaining:
            chunk = os.read(descriptor, min(remaining, 8192))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        if not chunks:
            return None
        payload = json.loads(b"".join(chunks).decode("utf-8"))
        return payload if isinstance(payload, dict) else None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


__all__ = [
    "LEASE_FILE_NAME",
    "LEASE_SCHEMA_VERSION",
    "RuntimeDataLease",
    "RuntimeLeaseConflictError",
]
