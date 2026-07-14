"""Programmatic uvicorn host for the exact Electron-owned backend."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Mapping
from typing import Any, BinaryIO

from src.services.desktop_parent_channel import (
    PARENT_CHANNEL_PROTOCOL,
    arm_desktop_parent_channel,
)


PRODUCTION_APP_TARGET = "src.main:app"
LOOPBACK_HOST = "127.0.0.1"
DEFAULT_BACKEND_PORT = 8000


class DesktopServerConfigurationError(RuntimeError):
    """The desktop host environment does not satisfy stdin-v1."""


def _required_instance_id(environ: Mapping[str, str]) -> str:
    instance_id = environ.get("DXM_BACKEND_INSTANCE_ID")
    if not instance_id or any(char.isspace() for char in instance_id):
        raise DesktopServerConfigurationError(
            "DXM_BACKEND_INSTANCE_ID must be one non-empty token"
        )
    return instance_id


def _backend_port(environ: Mapping[str, str]) -> int:
    raw_port = environ.get("DXM_BACKEND_PORT", str(DEFAULT_BACKEND_PORT))
    try:
        port = int(raw_port)
    except (TypeError, ValueError) as exc:
        raise DesktopServerConfigurationError(
            "DXM_BACKEND_PORT must be an integer from 1 through 65535"
        ) from exc
    if isinstance(raw_port, str) and raw_port != str(port):
        raise DesktopServerConfigurationError(
            "DXM_BACKEND_PORT must use canonical integer syntax"
        )
    if not 1 <= port <= 65535:
        raise DesktopServerConfigurationError(
            "DXM_BACKEND_PORT must be an integer from 1 through 65535"
        )
    return port


def run_desktop_server(
    *,
    environ: Mapping[str, str] | None = None,
    input_stream: BinaryIO | Any | None = None,
    hard_exit: Callable[[int], object] | None = None,
    arm_channel: Callable[..., Any] = arm_desktop_parent_channel,
    config_factory: Callable[..., Any] | None = None,
    server_factory: Callable[[Any], Any] | None = None,
) -> int:
    """Arm exact stdin ownership before any server can import ``src.main``."""

    env = os.environ if environ is None else environ
    if env.get("DXM_DESKTOP_PARENT_CHANNEL") != PARENT_CHANNEL_PROTOCOL:
        raise DesktopServerConfigurationError(
            f"DXM_DESKTOP_PARENT_CHANNEL must be {PARENT_CHANNEL_PROTOCOL!r}"
        )
    instance_id = _required_instance_id(env)
    stream = sys.stdin.buffer if input_stream is None else input_stream

    channel_kwargs: dict[str, object] = {"expected_instance_id": instance_id}
    if hard_exit is not None:
        channel_kwargs["hard_exit"] = hard_exit
    channel = arm_channel(stream, **channel_kwargs)

    # Parse remaining server inputs only after the START proof, but still before
    # constructing uvicorn.Config or importing the application target.
    port = _backend_port(env)
    if config_factory is None or server_factory is None:
        import uvicorn

        if config_factory is None:
            config_factory = uvicorn.Config
        if server_factory is None:
            server_factory = uvicorn.Server

    config = config_factory(
        PRODUCTION_APP_TARGET,
        host=LOOPBACK_HOST,
        port=port,
        log_level="info",
    )
    server = server_factory(config)
    channel.attach_server(server)
    channel.run_if_not_shutdown(server.run)
    return 0


def main() -> int:
    return run_desktop_server()


if __name__ == "__main__":
    raise SystemExit(main())
