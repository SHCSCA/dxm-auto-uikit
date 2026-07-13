import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.services.runtime_identity import (
    BUILD_MANIFEST_SCHEMA_VERSION,
    RUNTIME_IDENTITY_SCHEMA_VERSION,
    RuntimeIdentity,
    canonical_json,
    fingerprint_payload,
    normalize_identity_path,
)


FIXTURE = Path(__file__).parent / "fixtures" / "runtime_identity_golden_vector.json"
PATH_CASES = json.loads(FIXTURE.read_text(encoding="utf-8"))["pathCases"]


def _manifest(**overrides):
    payload = {
        "schemaVersion": BUILD_MANIFEST_SCHEMA_VERSION,
        "gitHead": "1234567890abcdef1234567890abcdef12345678",
        "gitDirty": False,
        "buildId": "desktop-build-01",
        "packageVersion": "0.1.0",
        "builtAt": "2026-07-13T03:00:00.000Z",
    }
    payload.update(overrides)
    return {**payload, "fingerprint": fingerprint_payload(payload)}


def _build_identity(tmp_path, *, env=None, pid=2468, instance_id="direct-fixed", git_probe=None):
    return RuntimeIdentity.from_environment(
        env={} if env is None else env,
        data_dir=tmp_path / "data" / ".." / "data",
        repo_root=tmp_path / "repo" / ".." / "repo",
        pid=pid,
        now=lambda: datetime(2026, 7, 13, 3, 4, 5, 678000, tzinfo=timezone.utc),
        instance_id_factory=lambda: instance_id,
        git_probe=git_probe or (lambda _root: ("abcdef0123456789abcdef0123456789abcdef01", False)),
        package_version="0.1.0",
    )


def test_canonical_json_matches_cross_language_golden_vector():
    vector = json.loads(FIXTURE.read_text(encoding="utf-8"))

    assert canonical_json(vector["identity"]) == vector["canonicalJson"]
    assert fingerprint_payload(vector["identity"]) == vector["fingerprint"]


@pytest.mark.parametrize(
    "case",
    PATH_CASES,
    ids=lambda case: f"{case['platform']}:{case['input']}",
)
def test_identity_paths_match_cross_language_lexical_golden_cases(case):
    assert normalize_identity_path(case["input"], platform=case["platform"]) == case["expected"]


def test_identity_paths_reject_relative_values():

    with pytest.raises(ValueError, match="absolute"):
        normalize_identity_path("relative/path", platform="posix")
    with pytest.raises(ValueError, match="absolute"):
        normalize_identity_path("relative\\path", platform="win32")


def test_direct_identity_is_non_null_unique_frozen_and_truthful(tmp_path):
    generated = iter(("direct-one", "direct-two"))
    kwargs = {
        "env": {},
        "data_dir": tmp_path / "data",
        "repo_root": tmp_path / "repo",
        "pid": 9753,
        "now": lambda: datetime(2026, 7, 13, 3, 4, 5, tzinfo=timezone.utc),
        "instance_id_factory": lambda: next(generated),
        "git_probe": lambda _root: ("abcdef0123456789abcdef0123456789abcdef01", False),
        "package_version": "0.1.0",
    }

    first = RuntimeIdentity.from_environment(**kwargs)
    second = RuntimeIdentity.from_environment(**kwargs)
    payload = first.as_dict()

    assert payload["schemaVersion"] == RUNTIME_IDENTITY_SCHEMA_VERSION
    assert payload["instanceId"] == "direct-one"
    assert second.as_dict()["instanceId"] == "direct-two"
    assert payload["backendPid"] == 9753
    assert payload["browserAgentPid"] == 9753
    assert payload["browserExecutionModel"] == "in_process_thread"
    assert payload["packageSha256"] is None
    assert payload["fingerprint"] == fingerprint_payload({k: v for k, v in payload.items() if k != "fingerprint"})
    with pytest.raises(TypeError):
        first.payload["instanceId"] = "mutated"


def test_direct_fallback_is_fail_closed_when_git_lookup_fails(tmp_path):
    def unavailable(_root):
        raise OSError("git unavailable")

    identity = _build_identity(tmp_path, instance_id="no-git", git_probe=unavailable).as_dict()

    assert identity["gitHead"] == "unknown"
    assert identity["gitDirty"] is True
    assert identity["buildId"] == "direct-no-git"


def test_explicit_manifest_precedes_runtime_git_lookup_and_freezes_paths(tmp_path):
    manifest = _manifest(gitHead="fedcba9876543210fedcba9876543210fedcba98", gitDirty=True)

    def must_not_probe(_root):
        raise AssertionError("runtime git lookup must not run when explicit manifest is injected")

    identity = _build_identity(
        tmp_path,
        env={
            "DXM_BUILD_MANIFEST_JSON": json.dumps(manifest),
            "DXM_BACKEND_INSTANCE_ID": "desktop-manifest-instance",
            "DXM_DATA_DIR": str(tmp_path / "injected-data" / ".." / "injected-data"),
            "DXM_RESOURCE_ROOT": str(tmp_path / "resource-root" / ".." / "resource-root"),
            "DXM_WORKFLOW_PROFILE_DIR": str(tmp_path / "profiles" / ".." / "profiles" / "workflow"),
        },
        git_probe=must_not_probe,
    ).as_dict()

    assert identity["instanceId"] == "desktop-manifest-instance"
    assert identity["gitHead"] == manifest["gitHead"]
    assert identity["gitDirty"] is True
    assert identity["buildId"] == manifest["buildId"]
    assert identity["packageVersion"] == manifest["packageVersion"]
    assert identity["dataDir"] == str((tmp_path / "injected-data").resolve())
    assert identity["resourceRoot"] == str((tmp_path / "resource-root").resolve())
    assert identity["workflowProfileDir"] == str((tmp_path / "profiles" / "workflow").resolve())


def test_direct_mode_never_loads_stale_outputs_manifest_without_explicit_env(tmp_path):
    stale = tmp_path / "repo" / "outputs" / "build-metadata" / "desktop-build-manifest.json"
    stale.parent.mkdir(parents=True)
    stale.write_text(json.dumps(_manifest(buildId="stale-build")), encoding="utf-8")

    identity = _build_identity(tmp_path, env={}, instance_id="fresh-direct").as_dict()

    assert identity["buildId"] == "direct-fresh-direct"
    assert identity["buildId"] != "stale-build"


def test_package_sha_is_optional_validated_and_normalized(tmp_path):
    lower_sha = "a1" * 32
    with_sha = _build_identity(tmp_path, env={"DXM_PACKAGE_SHA256": lower_sha}).as_dict()
    without_sha = _build_identity(tmp_path, env={}).as_dict()

    assert with_sha["packageSha256"] == lower_sha.upper()
    assert without_sha["packageSha256"] is None

    with pytest.raises(ValueError, match="DXM_PACKAGE_SHA256"):
        _build_identity(tmp_path, env={"DXM_PACKAGE_SHA256": "not-a-sha"})


def test_manifest_fingerprint_is_validated_before_identity_is_created(tmp_path):
    manifest = _manifest()
    manifest["gitDirty"] = not manifest["gitDirty"]

    with pytest.raises(ValueError, match="fingerprint"):
        _build_identity(tmp_path, env={"DXM_BUILD_MANIFEST_JSON": json.dumps(manifest)})


def test_manifest_built_at_requires_canonical_utc_milliseconds(tmp_path):
    manifest = _manifest(builtAt="2026-07-13T11:00:00+08:00")

    with pytest.raises(ValueError, match="builtAt"):
        _build_identity(tmp_path, env={"DXM_BUILD_MANIFEST_JSON": json.dumps(manifest)})


def test_manifest_rejects_unknown_fields_even_with_a_matching_fingerprint(tmp_path):
    manifest = _manifest()
    manifest["futureField"] = "must-not-drift-v1"
    manifest["fingerprint"] = fingerprint_payload({key: value for key, value in manifest.items() if key != "fingerprint"})

    with pytest.raises(ValueError, match="unknown"):
        _build_identity(tmp_path, env={"DXM_BUILD_MANIFEST_JSON": json.dumps(manifest)})


@pytest.mark.parametrize("raw_manifest", ("[]", '"text"', "null"))
def test_manifest_rejects_valid_json_that_is_not_an_object(tmp_path, raw_manifest):
    with pytest.raises(ValueError, match="build manifest must be an object"):
        _build_identity(tmp_path, env={"DXM_BUILD_MANIFEST_JSON": raw_manifest})
