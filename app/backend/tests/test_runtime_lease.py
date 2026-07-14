from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _lease_api():
    try:
        from src.services.runtime_lease import RuntimeDataLease, RuntimeLeaseConflictError
    except ModuleNotFoundError as exc:
        pytest.fail(f"runtime lease service is not implemented: {exc}")
    return RuntimeDataLease, RuntimeLeaseConflictError


def _subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(BACKEND_ROOT), existing) if part
    )
    return env


def _attempt_in_subprocess(data_dir: Path, metadata: dict[str, object]) -> subprocess.CompletedProcess[str]:
    script = r"""
import json
import sys

from src.services.runtime_lease import RuntimeDataLease, RuntimeLeaseConflictError

data_dir = sys.argv[1]
metadata = json.loads(sys.argv[2])
try:
    lease = RuntimeDataLease.acquire(data_dir, metadata=metadata)
except RuntimeLeaseConflictError as exc:
    print(json.dumps({
        "kind": "conflict",
        "message": str(exc),
        "data_dir": str(exc.data_dir),
        "owner_metadata": exc.owner_metadata,
    }, sort_keys=True))
    raise SystemExit(23)
else:
    print(json.dumps({"kind": "acquired", "data_dir": str(lease.data_dir)}, sort_keys=True))
    lease.release()
"""
    return subprocess.run(
        [sys.executable, "-c", script, str(data_dir), json.dumps(metadata)],
        cwd=BACKEND_ROOT,
        env=_subprocess_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
        check=False,
    )


def test_acquire_creates_only_canonical_root_and_permanent_lock_with_non_inheritable_fd(tmp_path):
    RuntimeDataLease, _ = _lease_api()
    requested = tmp_path / "parent" / "child" / ".." / "runtime-data"

    lease = RuntimeDataLease.acquire(requested, metadata={"instanceId": "owner-one"})
    canonical = requested.resolve(strict=False)

    assert lease.data_dir == canonical
    assert lease.lock_path == canonical / ".dxm-runtime.lock"
    assert lease.lock_path.is_file()
    assert os.get_inheritable(lease.file_descriptor) is False
    assert sorted(path.name for path in canonical.iterdir()) == [".dxm-runtime.lock"]

    lease.release()
    assert lease.lock_path.is_file()


def test_same_canonical_directory_conflicts_across_real_processes_with_non_authoritative_metadata(tmp_path):
    RuntimeDataLease, RuntimeLeaseConflictError = _lease_api()
    requested = tmp_path / "data" / ".." / "data"
    lease = RuntimeDataLease.acquire(
        requested,
        metadata={"instanceId": "live-owner", "role": "test"},
    )

    result = _attempt_in_subprocess(
        requested.resolve(strict=False),
        {"instanceId": "contender"},
    )

    assert result.returncode == 23, result.stderr
    payload = json.loads(result.stdout)
    assert payload["kind"] == "conflict"
    assert payload["data_dir"] == str(requested.resolve(strict=False))
    assert payload["owner_metadata"]["owner"]["instanceId"] == "live-owner"
    assert "non-authoritative" in payload["message"]
    assert "may be stale" in payload["message"]
    assert str(requested.resolve(strict=False)) in payload["message"]
    assert issubclass(RuntimeLeaseConflictError, RuntimeError)

    lease.release()


def test_different_directories_can_be_leased_concurrently_across_processes(tmp_path):
    RuntimeDataLease, _ = _lease_api()
    first = RuntimeDataLease.acquire(tmp_path / "first", metadata={"instanceId": "first"})

    result = _attempt_in_subprocess(tmp_path / "second", {"instanceId": "second"})

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["kind"] == "acquired"
    first.release()


@pytest.mark.skipif(os.name != "nt", reason="requires the real Windows msvcrt byte-range lock")
def test_windows_different_length_metadata_still_contends_on_fixed_byte_zero(tmp_path):
    RuntimeDataLease, _ = _lease_api()
    lease = RuntimeDataLease.acquire(
        tmp_path / "data",
        metadata={"instanceId": "x"},
    )

    result = _attempt_in_subprocess(
        tmp_path / "data",
        {"instanceId": "contender-" + ("very-long-" * 200)},
    )

    assert result.returncode == 23, result.stderr
    assert json.loads(result.stdout)["kind"] == "conflict"
    lease.release()


def test_diagnostic_metadata_starts_after_authority_byte(tmp_path):
    RuntimeDataLease, _ = _lease_api()
    lease = RuntimeDataLease.acquire(
        tmp_path / "data",
        metadata={"instanceId": "metadata-owner"},
    )
    lock_path = lease.lock_path
    lease.release()

    raw = lock_path.read_bytes()
    assert raw[:1] == b"\x00"
    diagnostic = json.loads(raw[1:].decode("utf-8"))
    assert diagnostic["schemaVersion"] == "dxm.runtime.lease.v1"
    assert diagnostic["dataDir"] == str((tmp_path / "data").resolve(strict=False))
    assert diagnostic["owner"] == {"instanceId": "metadata-owner"}


def test_stale_file_without_live_lock_is_reused_not_deleted(tmp_path):
    RuntimeDataLease, _ = _lease_api()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    lock_path = data_dir / ".dxm-runtime.lock"
    lock_path.write_bytes(b"\x00" + json.dumps({"owner": {"instanceId": "stale"}}).encode("utf-8"))
    original_file_id = lock_path.stat().st_ino

    lease = RuntimeDataLease.acquire(data_dir, metadata={"instanceId": "new-owner"})

    assert lock_path.stat().st_ino == original_file_id
    lease.release()
    assert lock_path.is_file()


def test_explicit_release_allows_a_later_owner(tmp_path):
    RuntimeDataLease, _ = _lease_api()
    data_dir = tmp_path / "data"
    first = RuntimeDataLease.acquire(data_dir, metadata={"instanceId": "first"})

    first.release()
    first.release()
    second = RuntimeDataLease.acquire(data_dir, metadata={"instanceId": "second"})

    assert second.data_dir == data_dir.resolve(strict=False)
    second.release()


def test_process_exit_releases_os_lock_without_deleting_permanent_file(tmp_path):
    RuntimeDataLease, _ = _lease_api()
    data_dir = tmp_path / "data"
    script = r"""
import sys
from src.services.runtime_lease import RuntimeDataLease

PROCESS_LEASE = RuntimeDataLease.acquire(sys.argv[1], metadata={"instanceId": "short-lived"})
print("READY", flush=True)
sys.stdin.buffer.read()
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(data_dir)],
        cwd=BACKEND_ROOT,
        env=_subprocess_env(),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    try:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == "READY"

        live_contender = _attempt_in_subprocess(data_dir, {"instanceId": "while-live"})
        assert live_contender.returncode == 23, live_contender.stderr

        assert process.stdin is not None
        process.stdin.close()
        assert process.wait(timeout=10) == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)

    lock_path = data_dir / ".dxm-runtime.lock"
    assert lock_path.is_file()

    later = RuntimeDataLease.acquire(data_dir, metadata={"instanceId": "later"})

    later.release()
