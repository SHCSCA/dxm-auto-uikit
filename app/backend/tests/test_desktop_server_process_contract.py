from __future__ import annotations

import ctypes
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from src.services.runtime_lease import RuntimeDataLease, RuntimeLeaseConflictError
from src.services.runtime_identity import BUILD_MANIFEST_SCHEMA_VERSION, fingerprint_payload


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parents[1]
WINDOWS_EOF_PROBE = Path(__file__).resolve().parent / "fixtures" / "desktop_server_windows_eof_probe.py"
SHUTDOWN_MARKER = "DXM backend runtime stopping; closing visible browser sessions"
PROCESS_PROOF_TIMEOUT_SECONDS = 5
DESCENDANT_MINIMUM_TTL_SECONDS = 120


def _reserve_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _frozen_proof_manifest(instance_id: str) -> str:
    unsigned = {
        "schemaVersion": BUILD_MANIFEST_SCHEMA_VERSION,
        "gitHead": "A" * 40,
        "gitDirty": True,
        "buildId": f"process-proof-{instance_id}",
        "packageVersion": "0.1.0",
        "builtAt": "2026-07-14T00:00:00.000Z",
    }
    manifest = {**unsigned, "fingerprint": fingerprint_payload(unsigned)}
    return json.dumps(manifest, separators=(",", ":"), sort_keys=True)


def _desktop_environment(data_dir: Path, port: int, instance_id: str) -> dict[str, str]:
    environment = dict(os.environ)
    contract_keys = {
        "DXM_RUNTIME_OWNER",
        "DXM_DESKTOP",
        "DXM_DESKTOP_PARENT_CHANNEL",
        "DXM_BACKEND_INSTANCE_ID",
        "DXM_BACKEND_PORT",
        "DXM_BACKEND_URL",
        "DXM_DATA_DIR",
        "DXM_RESOURCE_ROOT",
        "DXM_WORKFLOW_PROFILE_DIR",
        "DXM_BUILD_MANIFEST_JSON",
        "DXM_PACKAGE_SHA256",
        "DXM_LAUNCHER_LOG_FILE",
        "DXM_RUNTIME_CONTROL_COMMAND_FILE",
    }
    for key in tuple(environment):
        if key.upper() in contract_keys:
            environment.pop(key)
    environment.update(
        {
            "DXM_RUNTIME_OWNER": "electron_desktop",
            "DXM_DESKTOP": "1",
            "DXM_DESKTOP_PARENT_CHANNEL": "stdin-v1",
            "DXM_BACKEND_INSTANCE_ID": instance_id,
            "DXM_BACKEND_PORT": str(port),
            "DXM_BACKEND_URL": f"http://127.0.0.1:{port}",
            "DXM_DATA_DIR": str(data_dir),
            "DXM_RESOURCE_ROOT": str(REPO_ROOT),
            "DXM_WORKFLOW_PROFILE_DIR": str(data_dir / "browser_profiles" / "dxm_workflow"),
            "DXM_BUILD_MANIFEST_JSON": _frozen_proof_manifest(instance_id),
            "DXM_LAUNCHER_LOG_FILE": str(data_dir / "desktop-main.log"),
            "DXM_PROOF_PYTEST_PID": str(os.getpid()),
            "PYTHONUNBUFFERED": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    venv_site_packages = Path(sys.prefix) / "Lib" / "site-packages"
    environment["PYTHONPATH"] = os.pathsep.join(
        part
        for part in (
            str(BACKEND_ROOT),
            str(venv_site_packages),
            environment.get("PYTHONPATH", ""),
        )
        if part
    )
    return environment


def _read_process_output(output_path: Path) -> str:
    try:
        return output_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _wait_for_health(
    process: subprocess.Popen[bytes],
    *,
    port: int,
    instance_id: str,
    output_path: Path,
    timeout: float = 45,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    last_error = "health was not attempted"
    url = f"http://127.0.0.1:{port}/health"
    while time.monotonic() < deadline:
        return_code = process.poll()
        if return_code is not None:
            pytest.fail(
                f"desktop_server exited before health: rc={return_code} "
                f"output={_read_process_output(output_path)!r}"
            )
        try:
            with urllib.request.urlopen(url, timeout=0.5) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if payload.get("status") == "ok" and payload.get("instanceId") == instance_id:
                return payload
            last_error = f"unexpected payload: {payload!r}"
        except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError) as exc:
            last_error = repr(exc)
        time.sleep(0.05)
    pytest.fail(
        f"desktop_server did not prove exact health within {timeout}s: {last_error}; "
        f"output={_read_process_output(output_path)!r}"
    )


def _assert_port_occupied(port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as contender:
        if os.name == "nt":
            contender.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        with pytest.raises(OSError) as captured:
            contender.bind(("127.0.0.1", port))
        if os.name == "nt":
            assert captured.value.winerror == 10048


def _reacquire_port(port: int, timeout: float = PROCESS_PROOF_TIMEOUT_SECONDS) -> None:
    deadline = time.monotonic() + timeout
    last_error: OSError | None = None
    while time.monotonic() < deadline:
        contender = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if os.name == "nt":
                contender.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                contender.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            contender.bind(("127.0.0.1", port))
            contender.listen(1)
            return
        except OSError as exc:
            last_error = exc
            time.sleep(0.05)
        finally:
            contender.close()
    raise AssertionError(f"loopback port {port} was not released: {last_error}")


def _assert_live_lease(data_dir: Path) -> None:
    with pytest.raises(RuntimeLeaseConflictError):
        RuntimeDataLease.acquire(data_dir, metadata={"proof": "must-conflict"})


def _reacquire_lease(data_dir: Path) -> None:
    lease = RuntimeDataLease.acquire(data_dir, metadata={"proof": "reacquired"})
    try:
        assert lease.released is False
    finally:
        lease.release()
    assert lease.released is True


def _start_desktop_process(
    *,
    command: list[str],
    environment: dict[str, str],
    output_path: Path,
) -> tuple[subprocess.Popen[bytes], object]:
    output_handle = output_path.open("wb")
    process = subprocess.Popen(
        command,
        cwd=BACKEND_ROOT,
        env=environment,
        stdin=subprocess.PIPE,
        stdout=output_handle,
        stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return process, output_handle


def _wait_for_json_report(path: Path, process: subprocess.Popen[bytes], timeout: float = 45) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    last_error: BaseException | None = None
    while time.monotonic() < deadline:
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                last_error = exc
        if process.poll() is not None:
            break
        time.sleep(0.05)
    pytest.fail(
        f"Windows EOF probe did not publish readiness: rc={process.poll()} "
        f"report_error={last_error!r}"
    )


def _open_exact_process_handle(pid: int):
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    handle = kernel32.OpenProcess(0x00100000 | 0x0001, False, pid)
    if not handle:
        raise AssertionError(
            "OpenProcess(SYNCHRONIZE | PROCESS_TERMINATE) failed: "
            f"pid={pid} GetLastError={ctypes.get_last_error()}"
        )
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.WaitForSingleObject.restype = ctypes.c_uint32
    kernel32.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.TerminateProcess.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    return kernel32, handle


def test_real_desktop_server_shutdown_keeps_parent_writer_open_until_cleanup_close_and_releases_authority(tmp_path):
    data_dir = tmp_path / "graceful-data"
    output_path = tmp_path / "graceful-output.log"
    port = _reserve_loopback_port()
    instance_id = "graceful-real-desktop"
    process, output_handle = _start_desktop_process(
        command=[sys.executable, "-u", "-m", "src.desktop_server"],
        environment=_desktop_environment(data_dir, port, instance_id),
        output_path=output_path,
    )
    marker_seen = threading.Event()
    marker_seen_while_alive: list[bool] = []
    watcher: threading.Thread | None = None
    try:
        assert process.stdin is not None
        process.stdin.write(f"START {instance_id}\n".encode("utf-8"))
        process.stdin.flush()
        health = _wait_for_health(
            process,
            port=port,
            instance_id=instance_id,
            output_path=output_path,
        )
        assert int(health["runtimeIdentity"]["backendPid"]) > 0
        assert int(health["runtimeIdentity"]["backendPid"]) != os.getpid()
        _assert_live_lease(data_dir)
        _assert_port_occupied(port)

        def watch_cleanup_marker() -> None:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                try:
                    if SHUTDOWN_MARKER in (data_dir / "backend.log").read_text(
                        encoding="utf-8", errors="replace"
                    ):
                        marker_seen_while_alive.append(process.poll() is None)
                        marker_seen.set()
                        return
                except OSError:
                    pass
                time.sleep(0.002)

        watcher = threading.Thread(target=watch_cleanup_marker, daemon=True)
        watcher.start()
        process.stdin.write(b"SHUTDOWN\n")
        process.stdin.flush()

        assert marker_seen.wait(15), _read_process_output(output_path)
        assert marker_seen_while_alive == [True]
        assert process.stdin.closed is False
        os.fstat(process.stdin.fileno())
        assert process.wait(timeout=15) == 0
        assert SHUTDOWN_MARKER in (data_dir / "backend.log").read_text(encoding="utf-8")
        _reacquire_lease(data_dir)
        _reacquire_port(port)
    finally:
        if process.stdin is not None and not process.stdin.closed:
            process.stdin.close()
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        if watcher is not None:
            watcher.join(timeout=1)
        output_handle.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows parent EOF + Job Object integration proof")
def test_real_desktop_server_parent_eof_kills_job_descendant_and_releases_lease_and_port(tmp_path):
    assert WINDOWS_EOF_PROBE.exists(), f"missing real desktop_server probe: {WINDOWS_EOF_PROBE}"
    data_dir = tmp_path / "forced-eof-data"
    output_path = tmp_path / "forced-eof-output.log"
    report_path = tmp_path / "forced-eof-report.json"
    port = _reserve_loopback_port()
    instance_id = "forced-eof-real-desktop"
    process, output_handle = _start_desktop_process(
        command=[sys.executable, "-u", str(WINDOWS_EOF_PROBE), str(report_path)],
        environment=_desktop_environment(data_dir, port, instance_id),
        output_path=output_path,
    )
    kernel32 = None
    backend_handle = None
    descendant_handle = None
    cleanup_used = False
    try:
        assert process.stdin is not None
        process.stdin.write(f"START {instance_id}\n".encode("utf-8"))
        process.stdin.flush()
        health = _wait_for_health(
            process,
            port=port,
            instance_id=instance_id,
            output_path=output_path,
        )
        report = _wait_for_json_report(report_path, process)
        assert report["status"] == "ready", report
        assert report["pytestPid"] == os.getpid()
        assert report["ownerPid"] != os.getpid()
        assert health["runtimeIdentity"]["backendPid"] == report["ownerPid"]
        assert report["runtimeOwner"] == "electron_desktop"
        assert report["jobOwnerBound"] is True
        assert report["bootstrapUsesProcessJobOwner"] is True
        assert report["parentChannelInstance"] == instance_id
        assert report["backendInJob"] is True
        assert report["descendantInJob"] is True
        assert report["pytestParentInJob"] is False

        descendant_pid = int(report["descendantPid"])
        ttl_seconds = int(report["descendantTtlSeconds"])
        started_at_unix_ms = int(report["descendantStartedAtUnixMs"])
        assert ttl_seconds >= DESCENDANT_MINIMUM_TTL_SECONDS
        natural_deadline = (started_at_unix_ms / 1000) + ttl_seconds
        assert natural_deadline - time.time() >= 100

        kernel32, backend_handle = _open_exact_process_handle(int(report["ownerPid"]))
        descendant_kernel32, descendant_handle = _open_exact_process_handle(descendant_pid)
        assert descendant_kernel32 is kernel32 or descendant_kernel32._handle == kernel32._handle
        assert kernel32.WaitForSingleObject(backend_handle, 0) == 0x00000102
        assert kernel32.WaitForSingleObject(descendant_handle, 0) == 0x00000102
        _assert_live_lease(data_dir)
        _assert_port_occupied(port)

        eof_started = time.monotonic()
        process.stdin.close()
        assert kernel32.WaitForSingleObject(backend_handle, PROCESS_PROOF_TIMEOUT_SECONDS * 1000) == 0x00000000
        assert process.wait(timeout=1) == 72
        assert kernel32.WaitForSingleObject(descendant_handle, PROCESS_PROOF_TIMEOUT_SECONDS * 1000) == 0x00000000
        assert time.monotonic() - eof_started <= PROCESS_PROOF_TIMEOUT_SECONDS + 0.5
        assert time.time() < natural_deadline - 60
        _reacquire_lease(data_dir)
        _reacquire_port(port)
    finally:
        if process.stdin is not None and not process.stdin.closed:
            process.stdin.close()
        if process.poll() is None:
            cleanup_used = True
            process.kill()
            process.wait(timeout=5)
        if descendant_handle and kernel32:
            if kernel32.WaitForSingleObject(descendant_handle, 0) == 0x00000102:
                cleanup_used = True
                kernel32.TerminateProcess(descendant_handle, 0xEE)
                kernel32.WaitForSingleObject(descendant_handle, 5_000)
            kernel32.CloseHandle(descendant_handle)
        if backend_handle and kernel32:
            kernel32.CloseHandle(backend_handle)
        output_handle.close()
    assert cleanup_used is False
