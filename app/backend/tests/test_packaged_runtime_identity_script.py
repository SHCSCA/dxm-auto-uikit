import base64
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
LIBRARY = REPO_ROOT / "scripts" / "lib" / "packaged-runtime-identity.ps1"
SHELL = shutil.which("powershell") or shutil.which("pwsh")
pytestmark = pytest.mark.skipif(SHELL is None, reason="需要 PowerShell 验证包内身份合同")


def fingerprint(payload):
    unsigned = {key: value for key, value in payload.items() if key != "fingerprint"}
    text = json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest().upper()


def timestamp(delta=0):
    return (datetime.now(timezone.utc) + timedelta(seconds=delta)).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def manifest():
    payload = {"schemaVersion": "dxm.desktop.build.v1", "gitHead": "a" * 40,
        "gitDirty": False, "buildId": "packaged-build-测试", "packageVersion": "0.3.0",
        "builtAt": "2026-10-15T01:02:03.456Z"}
    return {**payload, "fingerprint": fingerprint(payload)}


def identity(build):
    payload = {"schemaVersion": "dxm.runtime.identity.v1", "instanceId": "package-probe-current",
        "gitHead": build["gitHead"], "gitDirty": build["gitDirty"], "buildId": build["buildId"],
        "packageVersion": build["packageVersion"], "packageSha256": None,
        "backendPid": 4321, "browserAgentPid": 4321, "browserExecutionModel": "in_process_thread",
        "dataDir": r"C:\isolated\data", "workflowProfileDir": r"C:\isolated\data\browser_profiles\dxm_workflow",
        "resourceRoot": r"G:\bundle\resources", "startedAt": timestamp()}
    return {**payload, "fingerprint": fingerprint(payload)}


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def run_script(tmp_path, payload, body):
    path = tmp_path / "payload.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    script = ("$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); . "
        + literal(LIBRARY) + "; $PayloadPath=" + literal(path)
        + "; $Payload=[IO.File]::ReadAllText($PayloadPath,[Text.Encoding]::UTF8)|ConvertFrom-Json; " + body)
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return subprocess.run([SHELL, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15)


def test_powershell_fingerprint_matches_existing_cross_runtime_golden_vector(tmp_path):
    golden = json.loads((Path(__file__).parent / "fixtures" / "runtime_identity_golden_vector.json").read_text(encoding="utf-8"))
    result = run_script(tmp_path, golden["identity"],
        "[PSCustomObject]@{canonical=(ConvertTo-IdentityCanonicalJson $Payload);fingerprint=(Get-PackagedIdentityFingerprint $Payload)}|ConvertTo-Json -Compress")
    assert result.returncode == 0, result.stderr
    actual = json.loads(result.stdout)
    assert actual == {"canonical": golden["canonicalJson"], "fingerprint": golden["fingerprint"]}


def test_canonical_strings_keep_unicode_and_escape_controls_quotes_and_backslashes(tmp_path):
    payload = {"value": "测试'<>&\"\\\b\t\n\f\r\x01", "number": 12, "flag": True, "empty": None}
    result = run_script(tmp_path, payload, "Get-PackagedIdentityFingerprint $Payload")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == fingerprint(payload)


def test_manifest_is_read_from_bundle_and_caller_identity_is_removed(tmp_path):
    build = manifest()
    result = run_script(tmp_path, build, r"""
      $Manifest=Read-PackagedBuildManifest -Path $PayloadPath -ExpectedPackageVersion '0.3.0';
      $Environment=[Diagnostics.ProcessStartInfo]::new().EnvironmentVariables;
      foreach($Key in @('dxm_build_manifest_json','dxm_package_sha256','dxm_backend_instance_id','dxm_workflow_profile_dir')){$Environment[$Key]='stale'};
      $Environment['KEEP_PROBE_SETTING']='preserved';
      Set-PackagedProbeBuildIdentity -Environment $Environment -Manifest $Manifest -InstanceId 'probe-owned' -WorkflowProfileDir 'C:\isolated\profile';
      [PSCustomObject]@{manifest=($Environment['DXM_BUILD_MANIFEST_JSON']|ConvertFrom-Json);packageHash=$Environment['DXM_PACKAGE_SHA256'];instance=$Environment['DXM_BACKEND_INSTANCE_ID'];profile=$Environment['DXM_WORKFLOW_PROFILE_DIR'];other=$Environment['KEEP_PROBE_SETTING']}|ConvertTo-Json -Depth 4 -Compress
    """)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"manifest": build, "packageHash": None,
        "instance": "probe-owned", "profile": r"C:\isolated\profile", "other": "preserved"}


@pytest.mark.parametrize("field,value", [
    ("schemaVersion", "other"), ("gitDirty", "false"), ("gitHead", ""),
    ("builtAt", "2026-10-15T01:02:03Z"), ("packageVersion", "stale"),
    ("fingerprint", "0" * 64), ("unexpected", "extra"),
])
def test_manifest_rejects_wrong_schema_types_version_time_or_fingerprint(tmp_path, field, value):
    build = {**manifest(), field: value}
    if field != "fingerprint":
        build["fingerprint"] = fingerprint(build)
    result = run_script(tmp_path, build,
        "Read-PackagedBuildManifest -Path $PayloadPath -ExpectedPackageVersion '0.3.0'")
    assert result.returncode != 0


IDENTITY_ASSERTION = r"""
  Assert-PackagedProbeRuntimeIdentity -Identity $Payload.identity -Manifest $Payload.manifest -InstanceId 'package-probe-current' -BackendProcessId 4321 -DataDir 'C:\isolated\data' -WorkflowProfileDir 'C:\isolated\data\browser_profiles\dxm_workflow' -ResourceRoot 'G:\bundle\resources' -NotBefore ([DateTimeOffset]::Parse($Payload.notBefore))
"""


def test_probe_identity_accepts_only_bound_process_and_build_facts(tmp_path):
    build = manifest()
    result = run_script(tmp_path, {"manifest": build, "identity": identity(build), "notBefore": timestamp(-10)}, IDENTITY_ASSERTION)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("field,value", [
    ("schemaVersion", "other"), ("instanceId", "inherited"), ("gitHead", "b" * 40),
    ("gitDirty", True), ("gitDirty", "false"), ("buildId", "direct-from-checkout"),
    ("packageVersion", "0.2.3"), ("packageSha256", "a" * 64),
    ("backendPid", 4322), ("backendPid", "4321"), ("browserAgentPid", 4322),
    ("browserExecutionModel", "separate_process"), ("dataDir", r"C:\inherited\data"),
    ("workflowProfileDir", r"C:\inherited\profile"), ("resourceRoot", r"G:\checkout"),
    ("startedAt", "2026-01-01T00:00:00.000Z"), ("startedAt", "2099-01-01T00:00:00.000Z"),
    ("startedAt", "2026-10-15T01:02:03+00:00"), ("fingerprint", "0" * 64), ("unknown", "extra"),
])
def test_every_runtime_identity_field_remains_binding_even_with_a_rehashed_payload(tmp_path, field, value):
    build = manifest()
    runtime = {**identity(build), field: value}
    if field != "fingerprint":
        runtime["fingerprint"] = fingerprint(runtime)
    result = run_script(tmp_path, {"manifest": build, "identity": runtime, "notBefore": timestamp(-10)}, IDENTITY_ASSERTION)
    assert result.returncode != 0, f"篡改字段被接受: {field}"


def test_verifier_validates_both_status_identities_and_retains_all_resource_checks():
    source = (REPO_ROOT / "scripts" / "verify-desktop-package.ps1").read_text(encoding="utf-8-sig")
    assert "build-metadata\\desktop-build-manifest.json" in source
    assert "Read-PackagedBuildManifest -Path $BuildManifestPath -ExpectedPackageVersion $DesktopVersion" in source
    assert "Set-PackagedProbeBuildIdentity -Environment $StartInfo.EnvironmentVariables -Manifest $BuildManifest" in source
    assert "@($Status.runtimeIdentity, $Status.backend.runtimeIdentity)" in source
    assert "-BackendProcessId $Process.Id" in source and "-NotBefore $ProbeStartedAt" in source
    assert "$Status.backend.instanceId -cne $ProbeInstanceId" in source
    for name in ("l2_readonly_probe_runner", "l2_readonly_probe_script", "l2_readonly_probe_allowlist"):
        assert "Assert-PackagedRuntimeDependencyOk -Dependencies $Status.dependencies -Name '" + name + "'" in source
