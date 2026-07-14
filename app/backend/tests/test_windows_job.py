from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from pathlib import Path

import pytest

import src.services.windows_job as windows_job
from src.services.windows_job import (
    HANDLE_FLAG_INHERIT,
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
    JobObjectExtendedLimitInformation,
    WindowsJobError,
    WindowsJobOwner,
    create_backend_job_owner,
)


class FakeWin32JobApi:
    def __init__(self, *, fail_stage: str | None = None, error_code: int = 5) -> None:
        self.fail_stage = fail_stage
        self.error_code = error_code
        self.calls: list[tuple[object, ...]] = []
        self.information = None

    def create_job_object(self):
        self.calls.append(("CreateJobObjectW", None, None))
        return 0 if self.fail_stage == "CreateJobObjectW" else 0xBEEF

    def set_handle_information(self, handle, mask, flags):
        self.calls.append(("SetHandleInformation", handle, mask, flags))
        return self.fail_stage != "SetHandleInformation"

    def set_extended_limit_information(self, handle, information):
        self.calls.append(
            (
                "SetInformationJobObject",
                handle,
                JobObjectExtendedLimitInformation,
                ctypes.sizeof(information),
            )
        )
        self.information = information
        return self.fail_stage != "SetInformationJobObject"

    def get_current_process(self):
        self.calls.append(("GetCurrentProcess",))
        return 0xCAFE

    def assign_process_to_job(self, job_handle, process_handle):
        self.calls.append(("AssignProcessToJobObject", job_handle, process_handle))
        return self.fail_stage != "AssignProcessToJobObject"

    def get_last_error(self):
        self.calls.append(("GetLastError",))
        return self.error_code

    def close_handle(self, handle):
        self.calls.append(("CloseHandle", handle))
        # A cleanup call is allowed to overwrite the thread error slot. The
        # wrapper must already have captured the failing API's error.
        self.error_code = 6
        return True


def test_job_structure_and_successful_call_order_are_exact():
    api = FakeWin32JobApi()

    owner = create_backend_job_owner(api=api)

    assert owner.handle == 0xBEEF
    assert api.calls == [
        ("CreateJobObjectW", None, None),
        ("SetHandleInformation", 0xBEEF, HANDLE_FLAG_INHERIT, 0),
        (
            "SetInformationJobObject",
            0xBEEF,
            JobObjectExtendedLimitInformation,
            ctypes.sizeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION),
        ),
        ("GetCurrentProcess",),
        ("AssignProcessToJobObject", 0xBEEF, 0xCAFE),
    ]
    assert ctypes.sizeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION) == (
        144 if ctypes.sizeof(ctypes.c_void_p) == 8 else 112
    )
    assert api.information.BasicLimitInformation.LimitFlags == JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    assert api.information.ProcessMemoryLimit == 0
    assert api.information.JobMemoryLimit == 0
    assert not hasattr(owner, "close")
    assert not hasattr(owner, "__enter__")
    assert not hasattr(owner, "__del__")


@pytest.mark.skipif(os.name != "nt", reason="Windows process-global owner contract")
def test_production_owner_is_process_global_and_never_recreated(monkeypatch):
    created = []
    owner = WindowsJobOwner(handle=0x1234)

    def fake_create():
        created.append(owner)
        return owner

    monkeypatch.setattr(windows_job, "_PROCESS_JOB_OWNER", None)
    monkeypatch.setattr(windows_job, "create_backend_job_owner", fake_create)

    assert windows_job.ensure_backend_job_owner() is owner
    assert windows_job.ensure_backend_job_owner() is owner
    assert created == [owner]


@pytest.mark.parametrize(
    ("stage", "expects_cleanup"),
    [
        ("CreateJobObjectW", False),
        ("SetHandleInformation", True),
        ("SetInformationJobObject", True),
        ("AssignProcessToJobObject", True),
    ],
)
def test_every_failure_reports_stage_and_preserved_get_last_error(stage, expects_cleanup):
    api = FakeWin32JobApi(fail_stage=stage, error_code=1234)

    with pytest.raises(WindowsJobError) as captured:
        create_backend_job_owner(api=api)

    assert captured.value.stage == stage
    assert captured.value.error_code == 1234
    assert stage in str(captured.value)
    assert "GetLastError=1234" in str(captured.value)
    close_calls = [call for call in api.calls if call[0] == "CloseHandle"]
    assert close_calls == ([("CloseHandle", 0xBEEF)] if expects_cleanup else [])


def _readline_with_timeout(process: subprocess.Popen[str], timeout: float) -> str:
    assert process.stdout is not None
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(process.stdout.readline)
        try:
            return future.result(timeout=timeout)
        except FutureTimeoutError:
            process.kill()
            process.wait(timeout=5)
            raise AssertionError("job_owner did not report readiness within the deadline")


def _open_exact_process_handle(pid: int):
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    # SYNCHRONIZE proves exit. PROCESS_TERMINATE permits cleanup through this
    # already-held exact handle if the kill-on-close assertion fails.
    handle = kernel32.OpenProcess(0x00100000 | 0x0001, False, pid)
    if not handle:
        raise AssertionError(
            "OpenProcess(SYNCHRONIZE | PROCESS_TERMINATE) failed: "
            f"GetLastError={ctypes.get_last_error()}"
        )
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.WaitForSingleObject.restype = ctypes.c_uint32
    kernel32.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.TerminateProcess.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    return kernel32, handle


@pytest.mark.skipif(os.name != "nt", reason="required guarded Windows Job Object proof")
def test_isolated_owner_exit_kills_its_waiting_descendant():
    backend_root = Path(__file__).resolve().parents[1]
    owner_helper = Path(__file__).resolve().parent / "fixtures" / "windows_job_owner.py"
    child_env = dict(os.environ)
    child_env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(backend_root), child_env.get("PYTHONPATH", "")) if part
    )
    owner = subprocess.Popen(
        [sys._base_executable, "-u", str(owner_helper)],
        cwd=backend_root,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=child_env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    descendant_handle = None
    kernel32 = None
    try:
        line = _readline_with_timeout(owner, 15)
        if not line:
            stderr = owner.stderr.read() if owner.stderr is not None else ""
            pytest.fail(f"job_owner exited before readiness: rc={owner.poll()} stderr={stderr}")
        report = json.loads(line)
        if report.get("status") != "ready":
            pytest.fail(
                "job_owner failed closed while binding its own nested Job: "
                f"stage={report.get('stage')} GetLastError={report.get('errorCode')}"
            )

        descendant_pid = int(report["descendantPid"])
        assert int(report["ownerPid"]) == owner.pid
        kernel32, descendant_handle = _open_exact_process_handle(descendant_pid)
        assert kernel32.WaitForSingleObject(descendant_handle, 0) == 0x00000102  # WAIT_TIMEOUT

        ttl_seconds = report.get("descendantTtlSeconds")
        started_at_unix_ms = report.get("descendantStartedAtUnixMs")
        assert isinstance(ttl_seconds, int) and ttl_seconds >= 120, (
            "proof descendant TTL must be at least 120s; a 20s fixture can "
            "naturally expire inside the test's readiness/wait windows"
        )
        assert isinstance(started_at_unix_ms, int) and started_at_unix_ms > 0
        natural_deadline = (started_at_unix_ms / 1000) + ttl_seconds
        assert natural_deadline - time.time() >= 100, (
            f"descendant PID {descendant_pid} is too close to natural TTL for a valid Job proof"
        )

        assert owner.stdin is not None
        owner.stdin.write("EXIT\n")
        owner.stdin.flush()
        owner.wait(timeout=10)
        signal_wait_started = time.monotonic()
        wait_result = kernel32.WaitForSingleObject(descendant_handle, 5_000)
        signal_wait_seconds = time.monotonic() - signal_wait_started
        assert wait_result == 0x00000000, (
            f"descendant PID {descendant_pid} survived exact owner PID {owner.pid} exit; "
            f"WaitForSingleObject={wait_result}"
        )
        assert signal_wait_seconds <= 5.5
        assert time.time() < natural_deadline - 60, (
            f"descendant PID {descendant_pid} signaled too near its natural TTL"
        )
    finally:
        if owner.poll() is None:
            owner.kill()
            owner.wait(timeout=5)
        if descendant_handle and kernel32:
            if kernel32.WaitForSingleObject(descendant_handle, 0) == 0x00000102:
                terminated = kernel32.TerminateProcess(descendant_handle, 0xEE)
                terminate_error = ctypes.get_last_error()
                cleanup_wait = kernel32.WaitForSingleObject(descendant_handle, 5_000)
                assert cleanup_wait == 0x00000000, (
                    "exact descendant cleanup failed: "
                    f"TerminateProcess={terminated} GetLastError={terminate_error} "
                    f"WaitForSingleObject={cleanup_wait}"
                )
            kernel32.CloseHandle(descendant_handle)
