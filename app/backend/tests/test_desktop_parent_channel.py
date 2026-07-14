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


class PausedFirstReadStream:
    def __init__(self, first_line: bytes):
        self.first_line = first_line
        self.read_started = threading.Event()
        self.release_first_read = threading.Event()
        self._remaining = queue.Queue()
        self.read_count = 0

    def put(self, line: bytes) -> None:
        self._remaining.put(line)

    def readline(self, _limit: int = -1) -> bytes:
        self.read_count += 1
        if self.read_count == 1:
            self.read_started.set()
            if not self.release_first_read.wait(2):
                raise TimeoutError("test did not release first START read")
            return self.first_line
        return self._remaining.get(timeout=2)


class CountingLineStream:
    def __init__(self, *lines: bytes):
        self._lines = iter(lines)
        self.read_count = 0

    def readline(self, _limit: int = -1) -> bytes:
        self.read_count += 1
        return next(self._lines, b"")


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


def test_arm_reserves_singleton_before_blocking_start_read_and_second_arm_does_not_read():
    first_stream = PausedFirstReadStream(b"START first-blocked\n")
    second_stream = CountingLineStream(b"START second-must-not-read\n", b"SHUTDOWN\n")
    first_result = []
    first_errors = []

    def arm_first():
        try:
            first_result.append(
                parent_channel.arm_desktop_parent_channel(
                    first_stream,
                    expected_instance_id="first-blocked",
                    hard_exit=lambda _code: None,
                )
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            first_errors.append(exc)

    worker = threading.Thread(target=arm_first)
    worker.start()
    assert first_stream.read_started.wait(1)
    try:
        with pytest.raises(parent_channel.DesktopParentChannelError, match="already arming"):
            parent_channel.arm_desktop_parent_channel(
                second_stream,
                expected_instance_id="second-must-not-read",
                hard_exit=lambda _code: None,
            )
        assert second_stream.read_count == 0
    finally:
        first_stream.release_first_read.set()
        worker.join(2)

    assert first_errors == []
    assert len(first_result) == 1
    assert parent_channel.require_armed_desktop_parent_channel("first-blocked") is first_result[0]
    first_stream.put(b"SHUTDOWN\n")
    assert first_result[0].wait_for_reader(1)


def test_require_cannot_observe_channel_until_reader_start_completes(monkeypatch):
    stream = BlockingLineStream(b"START publish-after-reader\n")
    start_entered = threading.Event()
    release_start = threading.Event()
    result = []
    errors = []
    original_start_reader = parent_channel.DesktopParentChannel.start_reader

    def blocked_start_reader(channel):
        start_entered.set()
        if not release_start.wait(2):
            raise TimeoutError("test did not release reader start")
        original_start_reader(channel)

    monkeypatch.setattr(
        parent_channel.DesktopParentChannel,
        "start_reader",
        blocked_start_reader,
    )

    def arm_channel():
        try:
            result.append(
                parent_channel.arm_desktop_parent_channel(
                    stream,
                    expected_instance_id="publish-after-reader",
                    hard_exit=lambda _code: None,
                )
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    worker = threading.Thread(target=arm_channel)
    worker.start()
    assert start_entered.wait(1)
    try:
        with pytest.raises(parent_channel.DesktopParentChannelError, match="not armed"):
            parent_channel.require_armed_desktop_parent_channel("publish-after-reader")
    finally:
        release_start.set()
        worker.join(2)

    assert errors == []
    assert len(result) == 1
    assert result[0].reader_alive is True
    assert parent_channel.require_armed_desktop_parent_channel("publish-after-reader") is result[0]
    stream.put(b"SHUTDOWN\n")
    assert result[0].wait_for_reader(1)


def test_reader_start_failure_atomically_restores_empty_singleton(monkeypatch):
    first_stream = BlockingLineStream(b"START failed-start\n")
    original_start_reader = parent_channel.DesktopParentChannel.start_reader
    monkeypatch.setattr(
        parent_channel.DesktopParentChannel,
        "start_reader",
        lambda _channel: (_ for _ in ()).throw(RuntimeError("reader start failed")),
    )

    with pytest.raises(RuntimeError, match="reader start failed"):
        parent_channel.arm_desktop_parent_channel(
            first_stream,
            expected_instance_id="failed-start",
            hard_exit=lambda _code: None,
        )
    with pytest.raises(parent_channel.DesktopParentChannelError, match="not armed"):
        parent_channel.require_armed_desktop_parent_channel("failed-start")

    monkeypatch.setattr(
        parent_channel.DesktopParentChannel,
        "start_reader",
        original_start_reader,
    )
    retry_stream = BlockingLineStream(b"START retry-after-failure\n")
    retry = parent_channel.arm_desktop_parent_channel(
        retry_stream,
        expected_instance_id="retry-after-failure",
        hard_exit=lambda _code: None,
    )
    assert parent_channel.require_armed_desktop_parent_channel("retry-after-failure") is retry
    retry_stream.put(b"SHUTDOWN\n")
    assert retry.wait_for_reader(1)


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


def test_run_edge_can_only_be_claimed_once_sequentially():
    channel = parent_channel.DesktopParentChannel(
        stream=object(),
        instance_id="single-run",
        hard_exit=lambda _code: None,
        max_line_bytes=64,
    )
    calls = []

    assert channel.run_if_not_shutdown(lambda: calls.append("first")) is True
    assert channel.run_if_not_shutdown(lambda: calls.append("duplicate")) is False
    assert calls == ["first"]


def test_concurrent_duplicate_run_claim_executes_exactly_one_callback_across_repeated_rounds():
    for round_index in range(50):
        channel = parent_channel.DesktopParentChannel(
            stream=object(),
            instance_id=f"concurrent-run-{round_index}",
            hard_exit=lambda _code: None,
            max_line_bytes=64,
        )
        start = threading.Barrier(3)
        results = []
        calls = []

        def claim(label):
            start.wait(timeout=1)
            results.append(channel.run_if_not_shutdown(lambda: calls.append(label)))

        workers = [
            threading.Thread(target=claim, args=("a",)),
            threading.Thread(target=claim, args=("b",)),
        ]
        for worker in workers:
            worker.start()
        start.wait(timeout=1)
        for worker in workers:
            worker.join(1)
            assert worker.is_alive() is False

        assert sorted(results) == [False, True]
        assert len(calls) == 1


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
