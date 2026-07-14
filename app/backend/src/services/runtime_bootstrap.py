"""Fail-closed process ownership bootstrap for every backend host."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from types import MappingProxyType
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
_SIGNATURE_ENV_KEYS = (
    "DXM_RUNTIME_OWNER",
    "DXM_DESKTOP",
    "DXM_DESKTOP_PARENT_CHANNEL",
    "DXM_BACKEND_INSTANCE_ID",
    "DXM_DATA_DIR",
    "DXM_RESOURCE_ROOT",
    "DXM_WORKFLOW_PROFILE_DIR",
    "DXM_BUILD_MANIFEST_JSON",
    "DXM_PACKAGE_SHA256",
)


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


@dataclass(frozen=True, slots=True)
class _OwnerFacts:
    name: str
    instance_id: str | None


@dataclass(frozen=True, slots=True, eq=False)
class _DependencyIdentity:
    target: Any | None
    bound_owner: Any | None
    bound_function: Any | None

    @classmethod
    def from_callable(cls, value: Any) -> _DependencyIdentity:
        bound_owner = getattr(value, "__self__", None)
        bound_function = getattr(value, "__func__", None)
        if bound_owner is not None and bound_function is not None:
            return cls(
                target=None,
                bound_owner=bound_owner,
                bound_function=bound_function,
            )
        return cls(target=value, bound_owner=None, bound_function=None)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, _DependencyIdentity):
            return NotImplemented
        if self.bound_function is not None or other.bound_function is not None:
            return (
                self.bound_owner is other.bound_owner
                and self.bound_function is other.bound_function
            )
        return self.target is other.target


@dataclass(frozen=True, slots=True)
class _ResolvedDependencies:
    parent_channel_getter: Callable[[str], Any]
    identity_factory: Callable[..., RuntimeIdentity]
    data_root_creator: Callable[[Path], None]
    lease_factory: Callable[..., Any]
    job_owner_factory: Callable[[], Any]
    remaining_directories_creator: Callable[[], None] | None
    default_remaining_directories_creator: Callable[[Path], None]
    signature_facts: tuple[tuple[str, str, _DependencyIdentity], ...]


@dataclass(frozen=True, slots=True)
class _RequestSignature:
    data_dir: str
    repo_root: str
    package_version: str
    platform_name: str
    environment_facts: tuple[tuple[str, Any], ...]
    dependency_facts: tuple[tuple[str, str, _DependencyIdentity], ...]


@dataclass(frozen=True, slots=True)
class _PreparedRequest:
    canonical_data_dir: Path
    canonical_data_text: str
    canonical_repo_root: Path
    package_version: str
    environment: Mapping[str, str]
    platform_name: str
    owner_facts: _OwnerFacts
    dependencies: _ResolvedDependencies
    signature: _RequestSignature


class _BootstrapPhase(Enum):
    EMPTY = auto()
    INITIALIZING = auto()
    READY = auto()
    FAILED = auto()


def _parse_owner_facts(environ: Mapping[str, str]) -> _OwnerFacts:
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
        return _OwnerFacts(name=owner, instance_id=None)

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
    return _OwnerFacts(name=owner, instance_id=instance_id)


def _validate_owner_facts(
    environ: Mapping[str, str],
    *,
    parent_channel_getter: Callable[[str], Any],
) -> _ValidatedOwner:
    owner_facts = _parse_owner_facts(environ)
    return _acquire_owner_parent(
        owner_facts,
        parent_channel_getter=parent_channel_getter,
    )


def _acquire_owner_parent(
    owner_facts: _OwnerFacts,
    *,
    parent_channel_getter: Callable[[str], Any],
) -> _ValidatedOwner:
    if owner_facts.name != "electron_desktop":
        return _ValidatedOwner(name=owner_facts.name, parent_channel=None)

    instance_id = owner_facts.instance_id
    if instance_id is None:  # pragma: no cover - guarded by _parse_owner_facts
        raise RuntimeBootstrapError("electron_desktop instance identity is missing")
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
    return _ValidatedOwner(name=owner_facts.name, parent_channel=parent_channel)


def _create_data_root(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)


def _resolve_dependencies(
    *,
    identity_factory: Callable[..., RuntimeIdentity] | None,
    parent_channel_getter: Callable[[str], Any] | None,
    data_root_creator: Callable[[Path], None] | None,
    lease_factory: Callable[..., Any] | None,
    job_owner_factory: Callable[[], Any] | None,
    remaining_directories_creator: Callable[[], None] | None,
) -> _ResolvedDependencies:
    dependency_facts: list[tuple[str, str, _DependencyIdentity]] = []

    def resolve(name: str, provided: Any, default: Any) -> Any:
        mode = "default" if provided is None else "injected"
        effective = default if provided is None else provided
        dependency_facts.append(
            (name, mode, _DependencyIdentity.from_callable(effective))
        )
        return effective

    resolved_parent = resolve(
        "parent_channel_getter",
        parent_channel_getter,
        require_armed_desktop_parent_channel,
    )
    resolved_identity = resolve(
        "identity_factory",
        identity_factory,
        RuntimeIdentity.from_environment,
    )
    resolved_root = resolve("data_root_creator", data_root_creator, _create_data_root)
    resolved_lease = resolve("lease_factory", lease_factory, RuntimeDataLease.acquire)
    resolved_job = resolve("job_owner_factory", job_owner_factory, ensure_backend_job_owner)
    default_remaining = ensure_runtime_directories
    resolved_remaining = resolve(
        "remaining_directories_creator",
        remaining_directories_creator,
        default_remaining,
    )

    return _ResolvedDependencies(
        parent_channel_getter=resolved_parent,
        identity_factory=resolved_identity,
        data_root_creator=resolved_root,
        lease_factory=resolved_lease,
        job_owner_factory=resolved_job,
        remaining_directories_creator=(
            None if remaining_directories_creator is None else resolved_remaining
        ),
        default_remaining_directories_creator=default_remaining,
        signature_facts=tuple(dependency_facts),
    )


def _canonical_path(value: str | os.PathLike[str], *, field_name: str) -> Path:
    try:
        return Path(value).expanduser().resolve(strict=False)
    except (OSError, TypeError, ValueError) as exc:
        raise RuntimeBootstrapError(f"{field_name} must be a valid filesystem path") from exc


def _prepare_runtime_bootstrap(
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
) -> _PreparedRequest:
    platform = os.name if platform_name is None else platform_name
    if platform not in {"nt", "posix"}:
        raise RuntimeBootstrapError(f"unsupported runtime bootstrap platform: {platform!r}")

    source_environment = os.environ if environ is None else environ
    environment_copy = dict(source_environment)
    owner_facts = _parse_owner_facts(environment_copy)
    dependencies = _resolve_dependencies(
        identity_factory=identity_factory,
        parent_channel_getter=parent_channel_getter,
        data_root_creator=data_root_creator,
        lease_factory=lease_factory,
        job_owner_factory=job_owner_factory,
        remaining_directories_creator=remaining_directories_creator,
    )

    canonical_data_dir = _canonical_path(data_dir, field_name="data_dir")
    canonical_data_text = str(canonical_data_dir)
    if "DXM_DATA_DIR" in environment_copy:
        explicit_data_dir = _canonical_path(
            environment_copy["DXM_DATA_DIR"],
            field_name="DXM_DATA_DIR",
        )
        if str(explicit_data_dir) != canonical_data_text:
            raise RuntimeBootstrapError(
                "explicit DXM_DATA_DIR does not match the configured canonical data directory"
            )

    canonical_repo_root = _canonical_path(repo_root, field_name="repo_root")
    environment_copy["DXM_DATA_DIR"] = canonical_data_text
    frozen_environment = MappingProxyType(environment_copy)
    resolved_package_version = str(package_version)
    signature = _RequestSignature(
        data_dir=canonical_data_text,
        repo_root=str(canonical_repo_root),
        package_version=resolved_package_version,
        platform_name=platform,
        environment_facts=tuple(
            (key, frozen_environment.get(key)) for key in _SIGNATURE_ENV_KEYS
        ),
        dependency_facts=dependencies.signature_facts,
    )
    return _PreparedRequest(
        canonical_data_dir=canonical_data_dir,
        canonical_data_text=canonical_data_text,
        canonical_repo_root=canonical_repo_root,
        package_version=resolved_package_version,
        environment=frozen_environment,
        platform_name=platform,
        owner_facts=owner_facts,
        dependencies=dependencies,
        signature=signature,
    )


def _build_prepared_runtime_bootstrap(prepared: _PreparedRequest) -> RuntimeBootstrapState:
    dependencies = prepared.dependencies
    validated_owner = _acquire_owner_parent(
        prepared.owner_facts,
        parent_channel_getter=dependencies.parent_channel_getter,
    )
    identity = dependencies.identity_factory(
        data_dir=prepared.canonical_data_dir,
        repo_root=prepared.canonical_repo_root,
        env=prepared.environment,
        package_version=prepared.package_version,
    )
    identity_data_text = identity.as_dict().get("dataDir")
    if (
        not isinstance(identity_data_text, str)
        or identity_data_text != prepared.canonical_data_text
    ):
        raise RuntimeBootstrapError(
            "runtime identity dataDir does not match the exact canonical data directory"
        )
    if validated_owner.name == "electron_desktop":
        expected_instance_id = prepared.owner_facts.instance_id
        if identity.instance_id != expected_instance_id:
            raise RuntimeBootstrapError(
                "runtime identity instanceId does not match the armed desktop parent channel"
            )

    dependencies.data_root_creator(prepared.canonical_data_dir)
    lease = dependencies.lease_factory(
        prepared.canonical_data_dir,
        metadata={
            "owner": validated_owner.name,
            "runtimeIdentity": identity.as_dict(),
        },
    )
    if lease is None or bool(getattr(lease, "released", False)):
        raise RuntimeBootstrapError("runtime lease factory returned no live lease")

    job_owner = None
    if validated_owner.name == "electron_desktop" and prepared.platform_name == "nt":
        job_owner = dependencies.job_owner_factory()
        if job_owner is None:
            raise RuntimeBootstrapError("Windows Job owner factory returned no owner")

    if dependencies.remaining_directories_creator is None:
        dependencies.default_remaining_directories_creator(prepared.canonical_data_dir)
    else:
        dependencies.remaining_directories_creator()

    return RuntimeBootstrapState(
        owner=validated_owner.name,
        data_dir=prepared.canonical_data_dir,
        runtime_identity=identity,
        lease=lease,
        parent_channel=validated_owner.parent_channel,
        windows_job_owner=job_owner,
    )


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
    prepared = _prepare_runtime_bootstrap(
        data_dir=data_dir,
        repo_root=repo_root,
        package_version=package_version,
        environ=environ,
        platform_name=platform_name,
        identity_factory=identity_factory,
        parent_channel_getter=parent_channel_getter,
        data_root_creator=data_root_creator,
        lease_factory=lease_factory,
        job_owner_factory=job_owner_factory,
        remaining_directories_creator=remaining_directories_creator,
    )
    return _build_prepared_runtime_bootstrap(prepared)


_PROCESS_BOOTSTRAP_LOCK = threading.RLock()
_PROCESS_BOOTSTRAP_PHASE = _BootstrapPhase.EMPTY
_PROCESS_BOOTSTRAP_STATE: RuntimeBootstrapState | None = None
_PROCESS_BOOTSTRAP_SIGNATURE: _RequestSignature | None = None
_PROCESS_BOOTSTRAP_FAILURE: BaseException | None = None


def ensure_runtime_bootstrap(**kwargs: Any) -> RuntimeBootstrapState:
    """Create and permanently retain the one production process bootstrap."""

    global _PROCESS_BOOTSTRAP_FAILURE
    global _PROCESS_BOOTSTRAP_PHASE
    global _PROCESS_BOOTSTRAP_SIGNATURE
    global _PROCESS_BOOTSTRAP_STATE
    with _PROCESS_BOOTSTRAP_LOCK:
        if _PROCESS_BOOTSTRAP_PHASE is _BootstrapPhase.FAILED:
            error = RuntimeBootstrapError(
                "runtime bootstrap previously failed; process restart required"
            )
            raise error from _PROCESS_BOOTSTRAP_FAILURE
        if _PROCESS_BOOTSTRAP_PHASE is _BootstrapPhase.INITIALIZING:
            raise RuntimeBootstrapError(
                "runtime bootstrap initialization is already in progress; process restart required"
            )
        if _PROCESS_BOOTSTRAP_PHASE is _BootstrapPhase.READY:
            prepared = _prepare_runtime_bootstrap(**kwargs)
            if prepared.signature != _PROCESS_BOOTSTRAP_SIGNATURE:
                raise RuntimeBootstrapError(
                    "runtime bootstrap request mismatch: process is already READY "
                    "with a different ownership contract"
                )
            if _PROCESS_BOOTSTRAP_STATE is None:  # pragma: no cover - invariant guard
                raise RuntimeBootstrapError("runtime bootstrap READY state is missing")
            return _PROCESS_BOOTSTRAP_STATE

        _PROCESS_BOOTSTRAP_PHASE = _BootstrapPhase.INITIALIZING
        try:
            prepared = _prepare_runtime_bootstrap(**kwargs)
            state = _build_prepared_runtime_bootstrap(prepared)
        except BaseException as exc:
            _PROCESS_BOOTSTRAP_STATE = None
            _PROCESS_BOOTSTRAP_SIGNATURE = None
            _PROCESS_BOOTSTRAP_FAILURE = exc
            _PROCESS_BOOTSTRAP_PHASE = _BootstrapPhase.FAILED
            raise

        _PROCESS_BOOTSTRAP_STATE = state
        _PROCESS_BOOTSTRAP_SIGNATURE = prepared.signature
        _PROCESS_BOOTSTRAP_FAILURE = None
        _PROCESS_BOOTSTRAP_PHASE = _BootstrapPhase.READY
        return state


def _reset_runtime_bootstrap_for_tests() -> RuntimeBootstrapState | None:
    """Drop a fake/isolated test state; production code must never call this."""

    global _PROCESS_BOOTSTRAP_FAILURE
    global _PROCESS_BOOTSTRAP_PHASE
    global _PROCESS_BOOTSTRAP_SIGNATURE
    global _PROCESS_BOOTSTRAP_STATE
    with _PROCESS_BOOTSTRAP_LOCK:
        previous = _PROCESS_BOOTSTRAP_STATE
        _PROCESS_BOOTSTRAP_PHASE = _BootstrapPhase.EMPTY
        _PROCESS_BOOTSTRAP_STATE = None
        _PROCESS_BOOTSTRAP_SIGNATURE = None
        _PROCESS_BOOTSTRAP_FAILURE = None
        return previous


__all__ = [
    "RUNTIME_OWNERS",
    "RuntimeBootstrapError",
    "RuntimeBootstrapState",
    "build_runtime_bootstrap",
    "ensure_runtime_bootstrap",
]
