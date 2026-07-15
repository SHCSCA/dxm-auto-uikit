from __future__ import annotations

import json
import ctypes
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from src import desktop_server
from src.services import windows_job
from src.services.desktop_parent_channel import require_armed_desktop_parent_channel


DESCENDANT_TTL_SECONDS = 120
_DESCENDANT: subprocess.Popen[bytes] | None = None


def _publish(path: Path, payload: dict[str, object]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _wait_for_exact_health(port: int, instance_id: str, timeout: float = 45) -> None:
    deadline = time.monotonic() + timeout
    last_error: BaseException | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=0.5) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if payload.get("status") == "ok" and payload.get("instanceId") == instance_id:
                return
            last_error = RuntimeError(f"unexpected health payload: {payload!r}")
        except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError) as exc:
            last_error = exc
        time.sleep(0.05)
    raise TimeoutError(f"exact desktop health was not ready: {last_error!r}")


def _is_process_in_job(pid: int, job_handle: object) -> bool:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.argtypes = []
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.IsProcessInJob.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
    kernel32.IsProcessInJob.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int

    close_process_handle = False
    if pid == os.getpid():
        process_handle = kernel32.GetCurrentProcess()
    else:
        process_handle = kernel32.OpenProcess(0x1000, False, pid)
        close_process_handle = True
        if not process_handle:
            raise OSError(
                ctypes.get_last_error(),
                f"OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION) failed for pid={pid}",
            )
    try:
        result = ctypes.c_int(0)
        if not kernel32.IsProcessInJob(process_handle, job_handle, ctypes.byref(result)):
            raise OSError(
                ctypes.get_last_error(),
                f"IsProcessInJob failed for pid={pid}",
            )
        return bool(result.value)
    finally:
        if close_process_handle:
            kernel32.CloseHandle(process_handle)


def _publish_job_descendant_proof(report_path: Path) -> None:
    global _DESCENDANT
    try:
        deadline = time.monotonic() + 45
        owner = None
        while time.monotonic() < deadline:
            owner = windows_job._PROCESS_JOB_OWNER
            if owner is not None:
                break
            time.sleep(0.01)
        if owner is None:
            raise TimeoutError("process-global Windows Job owner was not bound")

        instance_id = os.environ["DXM_BACKEND_INSTANCE_ID"]
        port = int(os.environ["DXM_BACKEND_PORT"])
        _wait_for_exact_health(port, instance_id)
        runtime_main = sys.modules.get("src.main")
        if runtime_main is None:
            raise RuntimeError("real src.main was not imported by desktop_server")
        bootstrap = runtime_main.runtime_bootstrap_state
        channel = require_armed_desktop_parent_channel(instance_id)
        if bootstrap.windows_job_owner is not owner:
            raise RuntimeError("runtime bootstrap does not retain the process-global Job owner")

        started_at_unix_ms = int(time.time() * 1000)
        _DESCENDANT = subprocess.Popen(
            [
                sys._base_executable,
                "-c",
                f"import time; time.sleep({DESCENDANT_TTL_SECONDS})",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        pytest_pid = int(os.environ["DXM_PROOF_PYTEST_PID"])
        backend_in_job = _is_process_in_job(os.getpid(), owner.handle)
        descendant_in_job = _is_process_in_job(_DESCENDANT.pid, owner.handle)
        pytest_parent_in_job = _is_process_in_job(pytest_pid, owner.handle)
        _publish(
            report_path,
            {
                "status": "ready",
                "ownerPid": os.getpid(),
                "pytestPid": pytest_pid,
                "descendantPid": _DESCENDANT.pid,
                "descendantTtlSeconds": DESCENDANT_TTL_SECONDS,
                "descendantStartedAtUnixMs": started_at_unix_ms,
                "runtimeOwner": bootstrap.owner,
                "jobOwnerBound": windows_job._PROCESS_JOB_OWNER is owner,
                "bootstrapUsesProcessJobOwner": bootstrap.windows_job_owner is owner,
                "parentChannelInstance": channel.instance_id,
                "mainImported": "src.main" in sys.modules,
                "backendInJob": backend_in_job,
                "descendantInJob": descendant_in_job,
                "pytestParentInJob": pytest_parent_in_job,
            },
        )
    except BaseException as exc:
        cleanup_used = False
        if _DESCENDANT is not None and _DESCENDANT.poll() is None:
            cleanup_used = True
            _DESCENDANT.terminate()
            try:
                _DESCENDANT.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _DESCENDANT.kill()
                _DESCENDANT.wait(timeout=5)
        _publish(
            report_path,
            {
                "status": "error",
                "ownerPid": os.getpid(),
                "errorType": type(exc).__name__,
                "error": str(exc),
                "cleanupUsed": cleanup_used,
            },
        )


def main() -> int:
    if os.name != "nt":
        raise SystemExit("desktop_server_windows_eof_probe requires Windows")
    if len(sys.argv) != 2:
        raise SystemExit("usage: desktop_server_windows_eof_probe.py <report-path>")
    report_path = Path(sys.argv[1]).resolve(strict=False)
    watcher = threading.Thread(
        target=_publish_job_descendant_proof,
        args=(report_path,),
        name="desktop-server-job-descendant-proof",
        daemon=True,
    )
    watcher.start()
    return desktop_server.main()


if __name__ == "__main__":
    raise SystemExit(main())
