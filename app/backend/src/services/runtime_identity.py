from __future__ import annotations

import hashlib
import json
import ntpath
import os
import posixpath
import re
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping


RUNTIME_IDENTITY_SCHEMA_VERSION = "dxm.runtime.identity.v1"
BUILD_MANIFEST_SCHEMA_VERSION = "dxm.desktop.build.v1"
BROWSER_EXECUTION_MODEL = "in_process_thread"
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(
        dict(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def fingerprint_payload(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest().upper()


def _normalize_sha256(value: Any, *, field_name: str, optional: bool = False) -> str | None:
    if value is None or str(value).strip() == "":
        if optional:
            return None
        raise ValueError(f"{field_name} is required")
    normalized = str(value).strip().upper()
    if not _SHA256_RE.fullmatch(normalized):
        raise ValueError(f"{field_name} must be a 64-character SHA-256 hex digest")
    return normalized


def normalize_identity_path(
    value: str | os.PathLike[str],
    *,
    platform: str | None = None,
) -> str:
    platform_name = platform or ("win32" if os.name == "nt" else "posix")
    text = str(value)
    if platform_name == "win32":
        text = text.replace("/", "\\")
        if not ntpath.isabs(text):
            raise ValueError("identity path must be absolute")
        normalized = ntpath.normpath(text)
        drive, tail = ntpath.splitdrive(normalized)
        if re.fullmatch(r"[A-Za-z]:", drive):
            drive = drive.upper()
        return f"{drive}{tail}"
    if platform_name == "posix":
        if not posixpath.isabs(text):
            raise ValueError("identity path must be absolute")
        return posixpath.normpath(text)
    raise ValueError(f"unsupported identity path platform: {platform_name}")


def _iso_utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _validate_iso_timestamp(value: Any, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must include a timezone")
    if _iso_utc(parsed) != text:
        raise ValueError(f"{field_name} must use canonical UTC milliseconds")
    return text


def _parse_build_manifest(raw: str | Mapping[str, Any]) -> dict[str, Any]:
    try:
        payload = json.loads(raw) if isinstance(raw, str) else dict(raw)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("DXM_BUILD_MANIFEST_JSON must contain valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("build manifest must be an object")
    required = {
        "schemaVersion",
        "gitHead",
        "gitDirty",
        "buildId",
        "packageVersion",
        "builtAt",
        "fingerprint",
    }
    missing = sorted(required - payload.keys())
    if missing:
        raise ValueError(f"build manifest missing fields: {', '.join(missing)}")
    unknown = sorted(payload.keys() - required)
    if unknown:
        raise ValueError(f"build manifest unknown fields: {', '.join(unknown)}")
    if payload["schemaVersion"] != BUILD_MANIFEST_SCHEMA_VERSION:
        raise ValueError("build manifest schemaVersion mismatch")
    if not isinstance(payload["gitDirty"], bool):
        raise ValueError("build manifest gitDirty must be boolean")
    for field in ("gitHead", "buildId", "packageVersion"):
        if not str(payload[field] or "").strip():
            raise ValueError(f"build manifest {field} is required")
    _validate_iso_timestamp(payload["builtAt"], field_name="build manifest builtAt")
    unsigned = {key: value for key, value in payload.items() if key != "fingerprint"}
    expected = fingerprint_payload(unsigned)
    actual = _normalize_sha256(payload["fingerprint"], field_name="build manifest fingerprint")
    if actual != expected:
        raise ValueError("build manifest fingerprint mismatch")
    return {
        "schemaVersion": BUILD_MANIFEST_SCHEMA_VERSION,
        "gitHead": str(payload["gitHead"]).strip(),
        "gitDirty": payload["gitDirty"],
        "buildId": str(payload["buildId"]).strip(),
        "packageVersion": str(payload["packageVersion"]).strip(),
        "builtAt": str(payload["builtAt"]).strip(),
        "fingerprint": actual,
    }


def _probe_git(repo_root: Path) -> tuple[str, bool]:
    git_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()
    dirty_output = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=normal"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    if not git_head:
        raise ValueError("git HEAD is empty")
    return git_head, bool(dirty_output.strip())


@dataclass(frozen=True)
class RuntimeIdentity:
    payload: Mapping[str, Any]

    @classmethod
    def from_environment(
        cls,
        *,
        data_dir: str | os.PathLike[str],
        repo_root: str | os.PathLike[str],
        env: Mapping[str, str] | None = None,
        pid: int | None = None,
        now: Callable[[], datetime] | None = None,
        instance_id_factory: Callable[[], str] | None = None,
        git_probe: Callable[[Path], tuple[str, bool]] | None = None,
        package_version: str = "0.1.0",
    ) -> RuntimeIdentity:
        env_map = os.environ if env is None else env
        process_pid = os.getpid() if pid is None else int(pid)
        if process_pid <= 0:
            raise ValueError("backend pid must be positive")
        create_instance_id = instance_id_factory or (lambda: uuid.uuid4().hex)
        instance_id = str(env_map.get("DXM_BACKEND_INSTANCE_ID") or create_instance_id()).strip()
        if not instance_id:
            raise ValueError("runtime instanceId must be non-empty")

        root_value = env_map.get("DXM_RESOURCE_ROOT") or repo_root
        data_value = env_map.get("DXM_DATA_DIR") or data_dir
        root_text = normalize_identity_path(root_value)
        data_text = normalize_identity_path(data_value)
        path_module = ntpath if os.name == "nt" else posixpath
        profile_value = env_map.get("DXM_WORKFLOW_PROFILE_DIR") or path_module.join(
            data_text,
            "browser_profiles",
            "dxm_workflow",
        )
        profile_text = normalize_identity_path(profile_value)
        root_path = Path(root_text)

        raw_manifest = env_map.get("DXM_BUILD_MANIFEST_JSON")
        if raw_manifest:
            manifest = _parse_build_manifest(raw_manifest)
            git_head = manifest["gitHead"]
            git_dirty = manifest["gitDirty"]
            build_id = manifest["buildId"]
            resolved_package_version = manifest["packageVersion"]
        else:
            probe = git_probe or _probe_git
            try:
                git_head, git_dirty = probe(root_path)
                git_head = str(git_head or "").strip() or "unknown"
                git_dirty = bool(git_dirty)
            except Exception:
                git_head = "unknown"
                git_dirty = True
            build_id = f"direct-{instance_id}"
            resolved_package_version = str(package_version or "").strip() or "unknown"

        fields = {
            "schemaVersion": RUNTIME_IDENTITY_SCHEMA_VERSION,
            "instanceId": instance_id,
            "gitHead": git_head,
            "gitDirty": git_dirty,
            "buildId": build_id,
            "packageVersion": resolved_package_version,
            "packageSha256": _normalize_sha256(
                env_map.get("DXM_PACKAGE_SHA256"),
                field_name="DXM_PACKAGE_SHA256",
                optional=True,
            ),
            "backendPid": process_pid,
            "browserAgentPid": process_pid,
            "browserExecutionModel": BROWSER_EXECUTION_MODEL,
            "dataDir": data_text,
            "workflowProfileDir": profile_text,
            "resourceRoot": root_text,
            "startedAt": _iso_utc((now or (lambda: datetime.now(timezone.utc)))()),
        }
        frozen = MappingProxyType({**fields, "fingerprint": fingerprint_payload(fields)})
        return cls(payload=frozen)

    @property
    def instance_id(self) -> str:
        return str(self.payload["instanceId"])

    def as_dict(self) -> dict[str, Any]:
        return dict(self.payload)
