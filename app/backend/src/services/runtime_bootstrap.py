"""Fail-closed process ownership bootstrap for every backend host."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from src.core.config import ensure_runtime_directories
from src.services.desktop_parent_channel import (
    PARENT_CHANNEL_PROTOCOL,
    DesktopParentChannel,
    DesktopParentChannelError,
    require_armed_desktop_parent_channel,
)
from src.services.runtime_identity import RuntimeIdentity
from src.services.runtime_lease import RuntimeDataLease
from src.services.windows_job import WindowsJobOwner, ensure_backend_job_owner


RUNTIME_OWNERS = frozenset({"direct", "start_mvp", "package_probe", "electron_desktop"})


class RuntimeBootstrapError(RuntimeError):
    """Runtime owner facts are invalid before any data-root write is allowed."""


@dataclass(frozen=True, slots=True)
class RuntimeBootstrapState:
    owner: str
    data_dir: Path
    runtime_identity: RuntimeIdentity
    lease: RuntimeDataLease
    parent_channel: DesktopParentChannel | None
    windows_job_owner: WindowsJobOwner | None


@dataclass(frozen=True, slots=True)
class _ValidatedOwner:
    name: str
    parent_channel: Any | None


def _validate_owner_facts(
    environ: Mapping[str, str],
    *,
    parent_channel_getter: Callable[[str], Any],
) -> _ValidatedOwner:
    raw_owner = environ.get("DXM_RUNTIME_OWNER")
    owner = "direct" if raw_owner is None else str(raw_owner)
    if owner not in RUNTIME_OWNERS:
        raise RuntimeBootstrapError(
            "DXM_RUNTIME_OWNER must be one of direct, start_mvp, package_probe, electron_desktop"
        )

    desktop_value = environ.get("DXM_DESKTOP")
    raw_desktop = "" if desktop_value is None else str(desktop_value)
    if raw_desktop not in {"", "0", "1"}:
        raise RuntimeBootstrapError("DXM_DESKTOP must be unset, 0, or 1")
    desktop_requested = raw_desktop == "1"
    channel_value = environ.get("DXM_DESKTOP_PARENT_CHANNEL")
    requested_channel = "" if channel_value is None else str(channel_value)

    if owner != "electron_desktop":
        if desktop_requested:
            raise RuntimeBootstrapError(
                "DXM_DESKTOP=1 requires DXM_RUNTIME_OWNER=electron_desktop"
            )
        if requested_channel:
            raise RuntimeBootstrapError(
                f"{owner} must not request a desktop parent channel"
            )
        return _ValidatedOwner(name=owner, parent_channel=None)

    if not desktop_requested:
        raise RuntimeBootstrapError("electron_desktop requires DXM_DESKTOP=1")
    if requested_channel != PARENT_CHANNEL_PROTOCOL:
        raise RuntimeBootstrapError(
            f"electron_desktop requires DXM_DESKTOP_PARENT_CHANNEL={PARENT_CHANNEL_PROTOCOL}"
        )
    instance_id = str(environ.get("DXM_BACKEND_INSTANCE_ID") or "")
    if not instance_id or any(character.isspace() for character in instance_id):
        raise RuntimeBootstrapError(
            "electron_desktop requires one exact DXM_BACKEND_INSTANCE_ID token"
        )
    try:
        parent_channel = parent_channel_getter(instance_id)
    except DesktopParentChannelError as exc:
        raise RuntimeBootstrapError(
            f"electron_desktop parent channel is not armed for {instance_id!r}: {exc}"
        ) from exc
    if parent_channel is None:
        raise RuntimeBootstrapError(
            f"electron_desktop has no armed parent channel for {instance_id!r}"
        )
    return _ValidatedOwner(name=owner, parent_channel=parent_channel)


def _create_data_root(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)


def build_runtime_bootstrap(
    *,
    data_dir: str | os.PathLike[str],
    repo_root: str | os.PathLike[str],
    package_version: str = "0.1.0",
    environ: Mapping[str, str] | None = None,
    platform_name: str | None = None,
    identity_factory: Callable[..., RuntimeIdentity] | None = None,
    parent_channel_getter: Callable[[str], Any] | None = None,
    data_root_creator: Callable[[Path], None] | None = None,
    lease_factory: Callable[..., Any] | None = None,
    job_owner_factory: Callable[[], Any] | None = None,
    remaining_directories_creator: Callable[[], None] | None = None,
) -> RuntimeBootstrapState:
    """Build one ownership state in the required no-write-to-ready order."""

    env = os.environ if environ is None else environ
    platform = os.name if platform_name is None else platform_name
    if platform not in {"nt", "posix"}:
        raise RuntimeBootstrapError(f"unsupported runtime bootstrap platform: {platform!r}")

    # This complete owner/channel validation is deliberately before identity
    # creation and before the first filesystem mutation.
    validated_owner = _validate_owner_facts(
        env,
        parent_channel_getter=parent_channel_getter or require_armed_desktop_parent_channel,
    )
    create_identity = identity_factory or RuntimeIdentity.from_environment
    identity = create_identity(
        data_dir=data_dir,
        repo_root=repo_root,
        env=env,
        package_version=package_version,
    )
    canonical_data_dir = Path(identity.as_dict()["dataDir"]).expanduser().resolve(strict=False)
    requested_data_dir = Path(data_dir).expanduser().resolve(strict=False)
    if canonical_data_dir != requested_data_dir:
        raise RuntimeBootstrapError(
            "runtime identity dataDir does not match the configured canonical data directory"
        )
    if validated_owner.name == "electron_desktop":
        expected_instance_id = str(env["DXM_BACKEND_INSTANCE_ID"])
        if identity.instance_id != expected_instance_id:
            raise RuntimeBootstrapError(
                "runtime identity instanceId does not match the armed desktop parent channel"
            )

    create_data_root = data_root_creator or _create_data_root
    create_data_root(canonical_data_dir)
    acquire_lease = lease_factory or RuntimeDataLease.acquire
    lease = acquire_lease(
        canonical_data_dir,
        metadata={
            "owner": validated_owner.name,
            "runtimeIdentity": identity.as_dict(),
        },
    )
    if lease is None or bool(getattr(lease, "released", False)):
        raise RuntimeBootstrapError("runtime lease factory returned no live lease")
    job_owner = None
    if validated_owner.name == "electron_desktop" and platform == "nt":
        create_job_owner = job_owner_factory or ensure_backend_job_owner
        job_owner = create_job_owner()
        if job_owner is None:
            raise RuntimeBootstrapError("Windows Job owner factory returned no owner")

    create_remaining = remaining_directories_creator
    if create_remaining is None:
        create_remaining = lambda: ensure_runtime_directories(canonical_data_dir)
    create_remaining()

    return RuntimeBootstrapState(
        owner=validated_owner.name,
        data_dir=canonical_data_dir,
        runtime_identity=identity,
        lease=lease,
        parent_channel=validated_owner.parent_channel,
        windows_job_owner=job_owner,
    )


_PROCESS_BOOTSTRAP_LOCK = threading.Lock()
_PROCESS_BOOTSTRAP_STATE: RuntimeBootstrapState | None = None


def ensure_runtime_bootstrap(**kwargs: Any) -> RuntimeBootstrapState:
    """Create and permanently retain the one production process bootstrap."""

    global _PROCESS_BOOTSTRAP_STATE
    with _PROCESS_BOOTSTRAP_LOCK:
        if _PROCESS_BOOTSTRAP_STATE is None:
            _PROCESS_BOOTSTRAP_STATE = build_runtime_bootstrap(**kwargs)
        return _PROCESS_BOOTSTRAP_STATE


def _reset_runtime_bootstrap_for_tests() -> RuntimeBootstrapState | None:
    """Drop a fake/isolated test state; production code must never call this."""

    global _PROCESS_BOOTSTRAP_STATE
    with _PROCESS_BOOTSTRAP_LOCK:
        previous = _PROCESS_BOOTSTRAP_STATE
        _PROCESS_BOOTSTRAP_STATE = None
        return previous


__all__ = [
    "RUNTIME_OWNERS",
    "RuntimeBootstrapError",
    "RuntimeBootstrapState",
    "build_runtime_bootstrap",
    "ensure_runtime_bootstrap",
]
