import queue

import pytest

from src import desktop_server
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


@pytest.fixture(autouse=True)
def reset_process_channel():
    parent_channel._reset_armed_channel_for_tests()
    yield
    parent_channel._reset_armed_channel_for_tests()


def _desktop_env(**overrides):
    env = {
        "DXM_DESKTOP_PARENT_CHANNEL": "stdin-v1",
        "DXM_BACKEND_INSTANCE_ID": "desktop-instance",
        "DXM_BACKEND_PORT": "8000",
    }
    env.update(overrides)
    return env


def test_invalid_protocol_fails_before_channel_or_server_construction():
    calls = []

    with pytest.raises(desktop_server.DesktopServerConfigurationError, match="stdin-v1"):
        desktop_server.run_desktop_server(
            environ=_desktop_env(DXM_DESKTOP_PARENT_CHANNEL="pid-polling"),
            input_stream=object(),
            arm_channel=lambda *_args, **_kwargs: calls.append("arm"),
            config_factory=lambda *_args, **_kwargs: calls.append("config"),
            server_factory=lambda *_args, **_kwargs: calls.append("server"),
        )

    assert calls == []


@pytest.mark.parametrize("instance_id", [None, "", "has whitespace", "line\nbreak"])
def test_invalid_expected_instance_fails_before_channel_or_server(instance_id):
    env = _desktop_env()
    if instance_id is None:
        env.pop("DXM_BACKEND_INSTANCE_ID")
    else:
        env["DXM_BACKEND_INSTANCE_ID"] = instance_id
    calls = []

    with pytest.raises(desktop_server.DesktopServerConfigurationError, match="INSTANCE_ID"):
        desktop_server.run_desktop_server(
            environ=env,
            input_stream=object(),
            arm_channel=lambda *_args, **_kwargs: calls.append("arm"),
            config_factory=lambda *_args, **_kwargs: calls.append("config"),
            server_factory=lambda *_args, **_kwargs: calls.append("server"),
        )

    assert calls == []


def test_host_arms_before_building_fixed_production_target_and_runs_server():
    calls = []
    attached = []

    class Channel:
        def attach_server(self, server):
            calls.append("attach")
            attached.append(server)

        def run_if_not_shutdown(self, callback):
            calls.append("gate")
            callback()
            return True

    channel = Channel()

    class Server:
        should_exit = False

        def __init__(self, config):
            self.config = config

        def run(self):
            calls.append("run")

    def arm(stream, *, expected_instance_id, hard_exit):
        assert stream == "stdin-sentinel"
        assert expected_instance_id == "desktop-instance"
        assert callable(hard_exit)
        calls.append("arm")
        return channel

    def build_config(target, **kwargs):
        calls.append("config")
        assert target == "src.main:app"
        assert kwargs == {"host": "127.0.0.1", "port": 8000, "log_level": "info"}
        return {"target": target, **kwargs}

    result = desktop_server.run_desktop_server(
        environ=_desktop_env(DXM_DESKTOP_APP_TARGET="evil.module:app"),
        input_stream="stdin-sentinel",
        hard_exit=lambda _code: None,
        arm_channel=arm,
        config_factory=build_config,
        server_factory=Server,
    )

    assert result == 0
    assert calls == ["arm", "config", "attach", "gate", "run"]
    assert len(attached) == 1


def test_early_shutdown_never_calls_server_run_or_import_sentinel():
    stream = BlockingLineStream(b"START desktop-instance\n")
    channel = parent_channel.arm_desktop_parent_channel(
        stream,
        expected_instance_id="desktop-instance",
        hard_exit=lambda _code: None,
    )
    stream.put(b"SHUTDOWN\n")
    assert channel.wait_for_reader(1)
    calls = []

    class Config:
        def load(self):
            calls.append("config-load-import-app")

    class Server:
        should_exit = False

        def __init__(self, config):
            self.config = config

        def run(self):
            calls.append("import-app-and-bind-port")

    result = desktop_server.run_desktop_server(
        environ=_desktop_env(),
        input_stream=object(),
        hard_exit=lambda _code: None,
        arm_channel=lambda *_args, **_kwargs: channel,
        config_factory=lambda _target, **_kwargs: Config(),
        server_factory=Server,
    )

    assert result == 0
    assert calls == []


def test_importing_desktop_host_does_not_import_production_app():
    import subprocess
    import sys
    from pathlib import Path

    backend_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import src.desktop_server; print('src.main' in sys.modules)",
        ],
        cwd=backend_root,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == "False"


def test_shutdown_after_attach_sets_programmatic_server_should_exit():
    stream = BlockingLineStream(b"START desktop-instance\n")
    server_holder = []
    run_entered = __import__("threading").Event()
    shutdown_seen = __import__("threading").Event()

    class Server:
        should_exit = False

        def __init__(self, _config):
            server_holder.append(self)

        def run(self):
            run_entered.set()
            assert shutdown_seen.wait(1)

    def send_shutdown_after_run():
        assert run_entered.wait(1)
        stream.put(b"SHUTDOWN\n")
        channel = parent_channel.require_armed_desktop_parent_channel("desktop-instance")
        assert channel.wait_for_reader(1)
        shutdown_seen.set()

    worker = __import__("threading").Thread(target=send_shutdown_after_run)
    worker.start()
    result = desktop_server.run_desktop_server(
        environ=_desktop_env(),
        input_stream=stream,
        hard_exit=lambda _code: None,
        config_factory=lambda target, **kwargs: (target, kwargs),
        server_factory=Server,
    )
    worker.join(1)

    assert result == 0
    assert server_holder[0].should_exit is True


@pytest.mark.parametrize("raw_port", ["", "0", "65536", "not-a-port", "8000.0"])
def test_invalid_backend_port_fails_without_constructing_server(raw_port):
    stream = BlockingLineStream(b"START desktop-instance\n")
    calls = []

    with pytest.raises(desktop_server.DesktopServerConfigurationError, match="BACKEND_PORT"):
        desktop_server.run_desktop_server(
            environ=_desktop_env(DXM_BACKEND_PORT=raw_port),
            input_stream=stream,
            hard_exit=lambda _code: None,
            config_factory=lambda *_args, **_kwargs: calls.append("config"),
            server_factory=lambda *_args, **_kwargs: calls.append("server"),
        )

    assert calls == []
    stream.put(b"SHUTDOWN\n")
    channel = parent_channel.require_armed_desktop_parent_channel("desktop-instance")
    assert channel.wait_for_reader(1)
