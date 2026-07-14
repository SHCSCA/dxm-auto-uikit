"""Exact Electron-parent lifetime channel for the desktop backend.

The environment can request this protocol, but only a successfully validated
``START`` command on the inherited stdin pipe creates the process-global proof.
"""

from __future__ import annotations

import os
import threading
from typing import BinaryIO, Callable, Protocol, TypeVar


PARENT_CHANNEL_PROTOCOL = "stdin-v1"
PARENT_CHANNEL_HARD_EXIT_CODE = 72
DEFAULT_MAX_LINE_BYTES = 4096


class DesktopParentChannelError(RuntimeError):
    """The exact desktop parent channel could not be validated or armed."""


class _Server(Protocol):
    should_exit: bool


_Result = TypeVar("_Result")


def _read_bounded_line(stream: BinaryIO, max_line_bytes: int) -> bytes:
    if not isinstance(max_line_bytes, int) or isinstance(max_line_bytes, bool) or max_line_bytes < 1:
        raise DesktopParentChannelError("parent channel max line length must be a positive integer")
    try:
        line = stream.readline(max_line_bytes + 1)
    except Exception as exc:  # pragma: no cover - exact stream failures vary by platform
        raise DesktopParentChannelError(f"parent channel read failed: {exc}") from exc
    if not isinstance(line, (bytes, bytearray)):
        raise DesktopParentChannelError("parent channel must be a binary stdin stream")
    result = bytes(line)
    if len(result) > max_line_bytes:
        raise DesktopParentChannelError(
            f"parent channel line exceeds the {max_line_bytes}-byte limit"
        )
    return result


def _validate_instance_id(instance_id: str) -> str:
    if not isinstance(instance_id, str) or not instance_id or any(char.isspace() for char in instance_id):
        raise DesktopParentChannelError("expected backend instance ID must be one non-empty token")
    return instance_id


def _validate_start_line(line: bytes, expected_instance_id: str) -> None:
    if line == b"":
        raise DesktopParentChannelError("parent channel reached EOF before START")

    expected = f"START {expected_instance_id}\n".encode("utf-8")
    if line == expected:
        return

    if line.startswith(b"START ") and line.endswith(b"\n"):
        actual = line[len(b"START ") : -1]
        try:
            actual_instance_id = actual.decode("utf-8")
        except UnicodeDecodeError:
            actual_instance_id = "<invalid-utf8>"
        raise DesktopParentChannelError(
            "parent channel START instance mismatch: "
            f"expected {expected_instance_id!r}, received {actual_instance_id!r}"
        )

    raise DesktopParentChannelError(
        "parent channel first command must be exactly START <expected-instance-id> followed by LF"
    )


class DesktopParentChannel:
    """An armed stdin-v1 channel bound to one expected Electron instance."""

    def __init__(
        self,
        *,
        stream: BinaryIO,
        instance_id: str,
        hard_exit: Callable[[int], object],
        max_line_bytes: int,
    ) -> None:
        self.instance_id = instance_id
        self.protocol = PARENT_CHANNEL_PROTOCOL
        self._stream = stream
        self._hard_exit = hard_exit
        self._max_line_bytes = max_line_bytes
        self._lock = threading.Lock()
        self._shutdown_pending = False
        self._run_claimed = False
        self._terminal_received = False
        self._server: _Server | None = None
        self._reader = threading.Thread(
            target=self._reader_main,
            name=f"dxm-parent-channel-{instance_id}",
            daemon=True,
        )

    @property
    def shutdown_pending(self) -> bool:
        with self._lock:
            return self._shutdown_pending

    @property
    def reader_alive(self) -> bool:
        return self._reader.is_alive()

    def start_reader(self) -> None:
        self._reader.start()

    def wait_for_reader(self, timeout: float | None = None) -> bool:
        self._reader.join(timeout)
        return not self._reader.is_alive()

    def attach_server(self, server: _Server) -> None:
        with self._lock:
            if self._server is not None and self._server is not server:
                raise DesktopParentChannelError("a different server is already attached to the parent channel")
            self._server = server
            if self._shutdown_pending:
                server.should_exit = True

    def run_if_not_shutdown(self, callback: Callable[[], _Result]) -> bool:
        """Claim the run edge unless SHUTDOWN already won the channel lock.

        The lock establishes a single ordering point between an early SHUTDOWN
        and the decision to invoke ``callback``. A later SHUTDOWN targets the
        already-attached server through ``should_exit``.
        """

        with self._lock:
            if self._shutdown_pending:
                return False
            self._run_claimed = True
        callback()
        return True

    def _request_shutdown(self) -> None:
        with self._lock:
            self._terminal_received = True
            self._shutdown_pending = True
            if self._server is not None:
                self._server.should_exit = True

    def _exit_for_lost_parent(self) -> None:
        with self._lock:
            if self._terminal_received:
                return
            self._terminal_received = True
        self._hard_exit(PARENT_CHANNEL_HARD_EXIT_CODE)

    def _reader_main(self) -> None:
        try:
            line = _read_bounded_line(self._stream, self._max_line_bytes)
        except DesktopParentChannelError:
            self._exit_for_lost_parent()
            return

        if line == b"SHUTDOWN\n":
            self._request_shutdown()
            return
        if line == b"":
            self._exit_for_lost_parent()
            return

        # Any malformed, unknown, or oversized terminal command breaks the
        # fail-closed ownership contract just like losing the exact writer.
        self._exit_for_lost_parent()


_ARMED_LOCK = threading.Lock()
_ARMED_CHANNEL: DesktopParentChannel | None = None


def arm_desktop_parent_channel(
    stream: BinaryIO,
    *,
    expected_instance_id: str,
    hard_exit: Callable[[int], object] | None = None,
    max_line_bytes: int = DEFAULT_MAX_LINE_BYTES,
) -> DesktopParentChannel:
    """Synchronously validate START, publish the proof, then arm the watchdog."""

    global _ARMED_CHANNEL
    instance_id = _validate_instance_id(expected_instance_id)
    with _ARMED_LOCK:
        if _ARMED_CHANNEL is not None:
            raise DesktopParentChannelError("desktop parent channel is already armed")

    line = _read_bounded_line(stream, max_line_bytes)
    _validate_start_line(line, instance_id)
    channel = DesktopParentChannel(
        stream=stream,
        instance_id=instance_id,
        hard_exit=os._exit if hard_exit is None else hard_exit,
        max_line_bytes=max_line_bytes,
    )

    with _ARMED_LOCK:
        if _ARMED_CHANNEL is not None:
            raise DesktopParentChannelError("desktop parent channel is already armed")
        _ARMED_CHANNEL = channel
    try:
        channel.start_reader()
    except BaseException:
        with _ARMED_LOCK:
            if _ARMED_CHANNEL is channel:
                _ARMED_CHANNEL = None
        raise
    return channel


def require_armed_desktop_parent_channel(expected_instance_id: str) -> DesktopParentChannel:
    """Return the in-process proof only when it matches the frozen instance."""

    with _ARMED_LOCK:
        channel = _ARMED_CHANNEL
    if channel is None:
        raise DesktopParentChannelError("desktop parent channel is not armed")
    if channel.instance_id != expected_instance_id:
        raise DesktopParentChannelError(
            "armed parent channel instance mismatch: "
            f"expected {expected_instance_id!r}, armed {channel.instance_id!r}"
        )
    return channel


def _reset_armed_channel_for_tests() -> None:
    """Drop only the process-global test reference; production never calls this."""

    global _ARMED_CHANNEL
    with _ARMED_LOCK:
        _ARMED_CHANNEL = None
