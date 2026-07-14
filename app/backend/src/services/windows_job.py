from __future__ import annotations

import ctypes
import os
import threading
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any, Protocol


JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JobObjectExtendedLimitInformation = 9
HANDLE_FLAG_INHERIT = 0x00000001


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
        ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class Win32JobApi(Protocol):
    def create_job_object(self) -> Any: ...

    def set_handle_information(self, handle: Any, mask: int, flags: int) -> bool: ...

    def set_extended_limit_information(
        self,
        handle: Any,
        information: JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
    ) -> bool: ...

    def get_current_process(self) -> Any: ...

    def assign_process_to_job(self, job_handle: Any, process_handle: Any) -> bool: ...

    def get_last_error(self) -> int: ...

    def close_handle(self, handle: Any) -> bool: ...


class CtypesWin32JobApi:
    def __init__(self) -> None:
        if os.name != "nt":
            raise OSError("Windows Job Objects are available only on Windows")

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetHandleInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD]
        kernel32.SetHandleInformation.restype = wintypes.BOOL
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.GetCurrentProcess.argtypes = []
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        self._kernel32 = kernel32

    def create_job_object(self):
        # A null SECURITY_ATTRIBUTES pointer makes the unnamed handle
        # non-inheritable by default. SetHandleInformation below enforces the
        # invariant explicitly as well.
        return self._kernel32.CreateJobObjectW(None, None)

    def set_handle_information(self, handle, mask: int, flags: int) -> bool:
        return bool(self._kernel32.SetHandleInformation(handle, mask, flags))

    def set_extended_limit_information(
        self,
        handle,
        information: JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
    ) -> bool:
        return bool(
            self._kernel32.SetInformationJobObject(
                handle,
                JobObjectExtendedLimitInformation,
                ctypes.byref(information),
                ctypes.sizeof(information),
            )
        )

    def get_current_process(self):
        return self._kernel32.GetCurrentProcess()

    def assign_process_to_job(self, job_handle, process_handle) -> bool:
        return bool(self._kernel32.AssignProcessToJobObject(job_handle, process_handle))

    def get_last_error(self) -> int:
        return int(ctypes.get_last_error())

    def close_handle(self, handle) -> bool:
        return bool(self._kernel32.CloseHandle(handle))


class WindowsJobError(RuntimeError):
    def __init__(self, *, stage: str, error_code: int) -> None:
        self.stage = stage
        self.error_code = int(error_code)
        super().__init__(f"Windows Job Object failed at {stage}: GetLastError={self.error_code}")


@dataclass(frozen=True, slots=True)
class WindowsJobOwner:
    handle: Any


def _raise_win32_failure(
    api: Win32JobApi,
    *,
    stage: str,
    created_handle: Any | None,
) -> None:
    # GetLastError is thread-local and may be changed by CloseHandle. Capture it
    # before best-effort cleanup so nested-Job assignment failures stay exact.
    error_code = api.get_last_error()
    if created_handle:
        api.close_handle(created_handle)
    raise WindowsJobError(stage=stage, error_code=error_code)


def create_backend_job_owner(*, api: Win32JobApi | None = None) -> WindowsJobOwner:
    win32 = api or CtypesWin32JobApi()
    handle = win32.create_job_object()
    if not handle:
        _raise_win32_failure(win32, stage="CreateJobObjectW", created_handle=None)

    if not win32.set_handle_information(handle, HANDLE_FLAG_INHERIT, 0):
        _raise_win32_failure(win32, stage="SetHandleInformation", created_handle=handle)

    information = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    information.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not win32.set_extended_limit_information(handle, information):
        _raise_win32_failure(win32, stage="SetInformationJobObject", created_handle=handle)

    process_handle = win32.get_current_process()
    if not win32.assign_process_to_job(handle, process_handle):
        _raise_win32_failure(win32, stage="AssignProcessToJobObject", created_handle=handle)

    # Deliberately no close/release/context-manager API: closing the last Job
    # handle would terminate this assigned backend and all descendants.
    return WindowsJobOwner(handle=handle)


_PROCESS_JOB_OWNER: WindowsJobOwner | None = None
_PROCESS_JOB_OWNER_LOCK = threading.Lock()


def ensure_backend_job_owner() -> WindowsJobOwner:
    global _PROCESS_JOB_OWNER
    if os.name != "nt":
        raise OSError("Windows Job Objects are available only on Windows")
    with _PROCESS_JOB_OWNER_LOCK:
        if _PROCESS_JOB_OWNER is None:
            _PROCESS_JOB_OWNER = create_backend_job_owner()
        return _PROCESS_JOB_OWNER
