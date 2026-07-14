import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from src.services import desktop_parent_channel as parent_channel


class BlockingLineStream:
    def __init__(self, *lines: bytes):
        self._lines = queue.Queue()
        for line in lines:
            self._lines.put(line)

    def put(self, line: bytes) -> None:
        self._lines.put(line)

    def readline(self, _limit: int = -1) -> bytes:
        return self._lines.get(timeout=2)


class ServerStub:
    should_exit = False


@pytest.fixture(autouse=True)
def reset_process_channel():
    parent_channel._reset_armed_channel_for_tests()
    yield
    parent_channel._reset_armed_channel_for_tests()


def test_environment_request_is_not_an_armed_parent_channel(monkeypatch):
    monkeypatch.setenv("DXM_DESKTOP_PARENT_CHANNEL", "stdin-v1")
    monkeypatch.setenv("DXM_BACKEND_INSTANCE_ID", "requested-only")

    with pytest.raises(parent_channel.DesktopParentChannelError, match="not armed"):
        parent_channel.require_armed_desktop_parent_channel("requested-only")


def test_exact_start_arms_the_process_global_channel():
    stream = BlockingLineStream(b"START exact-instance\n")

    channel = parent_channel.arm_desktop_parent_channel(
        stream,
        expected_instance_id="exact-instance",
        hard_exit=lambda _code: None,
    )

    assert channel.instance_id == "exact-instance"
    assert parent_channel.require_armed_desktop_parent_channel("exact-instance") is channel
    stream.put(b"SHUTDOWN\n")
    assert channel.wait_for_reader(1)


@pytest.mark.parametrize(
    ("first_line", "message"),
    [
        (b"", "EOF"),
        (b"BEGIN exact-instance\n", "START"),
        (b"START exact-instance", "START"),
        (b"START exact-instance\r\n", "START"),
        (b"A" * 65, "exceeds"),
    ],
)
def test_invalid_or_oversized_first_line_fails_before_arming(first_line, message):
    class OneLineStream:
        def readline(self, _limit=-1):
            return first_line

    with pytest.raises(parent_channel.DesktopParentChannelError, match=message):
        parent_channel.arm_desktop_parent_channel(
            OneLineStream(),
            expected_instance_id="exact-instance",
            max_line_bytes=64,
            hard_exit=lambda _code: None,
        )

    with pytest.raises(parent_channel.DesktopParentChannelError, match="not armed"):
        parent_channel.require_armed_desktop_parent_channel("exact-instance")


def test_start_instance_mismatch_fails_before_arming():
    stream = BlockingLineStream(b"START wrong-instance\n")

    with pytest.raises(parent_channel.DesktopParentChannelError, match="instance mismatch"):
        parent_channel.arm_desktop_parent_channel(
            stream,
            expected_instance_id="expected-instance",
            hard_exit=lambda _code: None,
        )


def test_second_channel_cannot_replace_the_exact_armed_fact():
    first_stream = BlockingLineStream(b"START first\n")
    second_stream = BlockingLineStream(b"START second\n")
    first = parent_channel.arm_desktop_parent_channel(
        first_stream,
        expected_instance_id="first",
        hard_exit=lambda _code: None,
    )

    with pytest.raises(parent_channel.DesktopParentChannelError, match="already armed"):
        parent_channel.arm_desktop_parent_channel(
            second_stream,
            expected_instance_id="second",
            hard_exit=lambda _code: None,
        )

    assert parent_channel.require_armed_desktop_parent_channel("first") is first
    first_stream.put(b"SHUTDOWN\n")
    assert first.wait_for_reader(1)


def test_shutdown_marks_pending_sets_attached_server_and_reader_returns_with_writer_open(tmp_path):
    read_fd, write_fd = os.pipe()
    reader = os.fdopen(read_fd, "rb", buffering=0)
    writer = os.fdopen(write_fd, "wb", buffering=0)
    try:
        writer.write(b"START pipe-instance\n")
        writer.flush()
        channel = parent_channel.arm_desktop_parent_channel(
            reader,
            expected_instance_id="pipe-instance",
            hard_exit=lambda _code: None,
        )
        server = ServerStub()
        channel.attach_server(server)

        writer.write(b"SHUTDOWN\n")
        writer.flush()

        assert channel.wait_for_reader(1)
        assert channel.shutdown_pending
        assert server.should_exit is True
        os.fstat(writer.fileno())
    finally:
        writer.close()
        reader.close()


def test_shutdown_before_attach_prevents_run_and_is_applied_to_server():
    stream = BlockingLineStream(b"START early\n")
    channel = parent_channel.arm_desktop_parent_channel(
        stream,
        expected_instance_id="early",
        hard_exit=lambda _code: None,
    )
    stream.put(b"SHUTDOWN\n")
    assert channel.wait_for_reader(1)
    server = ServerStub()
    called = []

    channel.attach_server(server)

    assert channel.run_if_not_shutdown(lambda: called.append("run")) is False
    assert called == []
    assert server.should_exit is True


def test_shutdown_after_run_gate_sets_server_exit_without_blocking_callback():
    stream = BlockingLineStream(b"START running\n")
    channel = parent_channel.arm_desktop_parent_channel(
        stream,
        expected_instance_id="running",
        hard_exit=lambda _code: None,
    )
    server = ServerStub()
    channel.attach_server(server)
    entered = threading.Event()
    release = threading.Event()
    result = []

    worker = threading.Thread(
        target=lambda: result.append(
            channel.run_if_not_shutdown(lambda: (entered.set(), release.wait(1)))
        )
    )
    worker.start()
    assert entered.wait(1)
    stream.put(b"SHUTDOWN\n")
    assert channel.wait_for_reader(1)
    assert server.should_exit is True
    release.set()
    worker.join(1)

    assert result == [True]


def test_parent_eof_calls_injected_hard_exit_immediately():
    read_fd, write_fd = os.pipe()
    reader = os.fdopen(read_fd, "rb", buffering=0)
    writer = os.fdopen(write_fd, "wb", buffering=0)
    exit_codes = []
    exited = threading.Event()
    try:
        writer.write(b"START eof-instance\n")
        writer.flush()
        channel = parent_channel.arm_desktop_parent_channel(
            reader,
            expected_instance_id="eof-instance",
            hard_exit=lambda code: (exit_codes.append(code), exited.set()),
        )

        writer.close()

        assert exited.wait(1)
        assert channel.wait_for_reader(1)
        assert exit_codes == [parent_channel.PARENT_CHANNEL_HARD_EXIT_CODE]
    finally:
        if not writer.closed:
            writer.close()
        reader.close()


@pytest.mark.parametrize("terminal_line", [b"UNKNOWN\n", b"X" * 65])
def test_unknown_or_oversized_terminal_command_fails_hard(terminal_line):
    stream = BlockingLineStream(b"START terminal-instance\n")
    exit_codes = []
    exited = threading.Event()
    channel = parent_channel.arm_desktop_parent_channel(
        stream,
        expected_instance_id="terminal-instance",
        max_line_bytes=64,
        hard_exit=lambda code: (exit_codes.append(code), exited.set()),
    )

    stream.put(terminal_line)

    assert exited.wait(1)
    assert channel.wait_for_reader(1)
    assert exit_codes == [parent_channel.PARENT_CHANNEL_HARD_EXIT_CODE]


def test_safe_child_closes_after_shutdown_while_parent_writer_stays_open():
    backend_root = Path(__file__).resolve().parents[1]
    script = """
import sys
from src.services.desktop_parent_channel import arm_desktop_parent_channel

channel = arm_desktop_parent_channel(sys.stdin.buffer, expected_instance_id='child-instance')
if not channel.wait_for_reader(2):
    raise SystemExit(9)
print('reader-returned', flush=True)
"""
    child = subprocess.Popen(
        [sys.executable, "-c", script],
        cwd=backend_root,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert child.stdin is not None
    assert child.stdout is not None
    try:
        child.stdin.write(b"START child-instance\nSHUTDOWN\n")
        child.stdin.flush()

        assert child.stdout.readline().strip() == b"reader-returned"
        assert child.wait(timeout=2) == 0
        assert child.stdin.closed is False
    finally:
        if child.stdin and not child.stdin.closed:
            child.stdin.close()
        if child.poll() is None:
            child.kill()
            child.wait(timeout=2)
