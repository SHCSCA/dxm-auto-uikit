param(
  [switch]$SkipBrowserQA,
  [switch]$RequireCleanWorktree,
  [switch]$CheckPortableDesktop,
  [switch]$Help,
  [string]$ExpectedRealDxmWriteReadiness = "BLOCKED",
  [string]$OutDir = "outputs/final-delivery-check"
)

$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$backendDir = Join-Path $root "app\backend"
$frontendDir = Join-Path $root "app\frontend"
$desktopDir = Join-Path $root "app\desktop"
$authoritativeDataDir = Join-Path $root "data"
$absoluteOutDir = if ([System.IO.Path]::IsPathRooted($OutDir)) { $OutDir } else { Join-Path $root $OutDir }
$browserQaOutDir = Join-Path $absoluteOutDir "browser-checks"
$l1ReplayOutDir = Join-Path $absoluteOutDir "l1-selector-replay"
$pytestRuntimeDataDir = Join-Path $absoluteOutDir "pytest-runtime-data"
$qaRuntimeDataDir = Join-Path $absoluteOutDir "qa-runtime-data"
$browserQaJson = Join-Path $browserQaOutDir "qa-browser-check.json"
$postFinalReportQaJson = Join-Path $browserQaOutDir "qa-final-report-check.json"
$summaryPath = Join-Path $absoluteOutDir "final-delivery-check.md"
$jsonPath = Join-Path $absoluteOutDir "final-delivery-check.json"
$packagedDesktopSmokeCapturePath = Join-Path $absoluteOutDir "packaged-desktop-smoke.png"
$packagedDesktopSmokeUserDataDir = Join-Path $absoluteOutDir "packaged-desktop-smoke-user-data"
$portableDesktopSmokeCapturePath = Join-Path $absoluteOutDir "portable-desktop-smoke.png"
$portableDesktopSmokeUserDataDir = Join-Path $absoluteOutDir "portable-desktop-smoke-user-data"
$packagedDesktopCredentialSmokePath = Join-Path $absoluteOutDir "packaged-desktop-credential-smoke.json"
$packagedDesktopVisibleSmokePath = Join-Path $absoluteOutDir "packaged-desktop-visible-smoke.json"
$packagedDesktopVisibleSmokeUserDataDir = Join-Path $absoluteOutDir "packaged-desktop-visible-smoke-user-data"
$l2AllowlistReviewTemplateMarkdownPath = Join-Path $absoluteOutDir "l2-allowlist-review-template.md"
$l2AllowlistReviewTemplateJsonPath = Join-Path $absoluteOutDir "l2-allowlist-review-template.json"
$qaProcesses = @()
$qaBackendPort = $null
$qaFrontendPort = $null
$workspaceApiBase = "http://127.0.0.1:8000"
$commands = @()

if ($Help) {
  Write-Host ""
  Write-Host "Usage:"
  Write-Host "  scripts\final-delivery-check.bat"
  Write-Host "  scripts\final-delivery-check.bat -RequireCleanWorktree"
  Write-Host "  scripts\final-delivery-check.bat -OutDir outputs\final-delivery-check"
  Write-Host ""
  Write-Host "Options:"
  Write-Host "  -RequireCleanWorktree  Require pre/post git status to be clean for source package acceptance."
  Write-Host "  -CheckPortableDesktop  Also verify the portable no-install desktop exe during packaged desktop smoke."
  Write-Host "  -SkipBrowserQA         Developer-only shortcut; do not use for formal delivery acceptance."
  Write-Host "  -ExpectedRealDxmWriteReadiness <BLOCKED|READY|UNKNOWN>  Expected real DXM write readiness for this acceptance run; default BLOCKED."
  Write-Host "  -OutDir <path>         Write reports, logs, screenshots and sidecars to a custom directory."
  Write-Host ""
  exit 0
}

New-Item -ItemType Directory -Path $absoluteOutDir -Force | Out-Null
New-Item -ItemType Directory -Path $browserQaOutDir -Force | Out-Null

function Write-Utf8NoBomFile {
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [AllowNull()][string]$Value
  )

  $encoding = New-Object System.Text.UTF8Encoding -ArgumentList $false
  [System.IO.File]::WriteAllText($Path, [string]$Value, $encoding)
}

function Write-JsonNoBomFile {
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][object]$Value,
    [int]$Depth = 12
  )

  Write-Utf8NoBomFile -Path $Path -Value ($Value | ConvertTo-Json -Depth $Depth)
}

function Invoke-JsonUtf8 {
  param(
    [string]$Uri,
    [int]$TimeoutSec = 5
  )

  $response = Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec $TimeoutSec
  $content = $null
  if ($response.RawContentStream) {
    $stream = $response.RawContentStream
    if ($stream.CanSeek) {
      $stream.Position = 0
    }
    $reader = New-Object System.IO.StreamReader($stream, [System.Text.Encoding]::UTF8, $true)
    try {
      $content = $reader.ReadToEnd()
    } finally {
      $reader.Dispose()
    }
  }
  if ([string]::IsNullOrEmpty($content)) {
    $content = [string]$response.Content
  }
  return $content | ConvertFrom-Json
}

function Get-JsonObjectPropertyCount {
  param(
    [object]$Value
  )

  if ($null -eq $Value -or $null -eq $Value.PSObject) {
    return 0
  }
  return @($Value.PSObject.Properties).Count
}

function Get-WorkspaceSnapshot {
  param(
    [string]$ApiBase
  )

  try {
    return Invoke-JsonUtf8 -Uri "$ApiBase/api/delivery/workspace" -TimeoutSec 5
  } catch {
    return $null
  }
}

function Get-AuthoritativeWorkspaceSnapshot {
  $code = @"
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path('app/backend').resolve()))

from src.repository import Repository
from src.services.delivery_workspace import build_delivery_workspace

print(json.dumps(build_delivery_workspace(Repository()), ensure_ascii=True))
"@

  try {
    $output = & $pythonExe -c $code
    if ($LASTEXITCODE -ne 0 -or !$output) {
      return $null
    }
    return (($output -join "`n") | ConvertFrom-Json)
  } catch {
    return $null
  }
}

function Get-WorkspaceGate {
  param(
    [object]$WorkspaceSnapshot,
    [string]$Level
  )

  if ($WorkspaceSnapshot -and $WorkspaceSnapshot.regression_gates) {
    return $WorkspaceSnapshot.regression_gates | Where-Object { $_.level -eq $Level } | Select-Object -First 1
  }
  return $null
}

function Get-L3EvidenceReadiness {
  param(
    [object]$WorkspaceSnapshot
  )

  $missing = New-Object System.Collections.Generic.List[string]
  $deliveryReadiness = if ($WorkspaceSnapshot) { $WorkspaceSnapshot.delivery_readiness } else { $null }
  if (!$deliveryReadiness) {
    $missing.Add("delivery_readiness unavailable")
  } else {
    if ($deliveryReadiness.has_l3_evidence -ne $true) {
      $missing.Add("L3 manual canary evidence missing")
    }
    $jobs = @($deliveryReadiness.jobs)
    if ($jobs.Count -eq 0) {
      $missing.Add("delivery_readiness jobs missing")
    }
    foreach ($job in $jobs) {
      $jobLabel = if ($job.job_id) { "job $($job.job_id)" } else { "job" }
      if ($job.has_save_result -ne $true) {
        $missing.Add("$jobLabel save_result missing")
      }
      if ($job.has_unpublished_proof -ne $true) {
        $missing.Add("$jobLabel published=false proof missing")
      }
      if ($job.has_network_or_har_save_response -ne $true) {
        $missing.Add("$jobLabel network/HAR save response missing")
      }
      if ($job.has_save_evidence_file -ne $true) {
        $missing.Add("$jobLabel save screenshot/path missing")
      }
      if ($job.has_unpublished_evidence_file -ne $true) {
        $missing.Add("$jobLabel unpublished screenshot/path missing")
      }
    }
  }

  [pscustomobject]@{
    ready = $missing.Count -eq 0
    missing = @($missing)
  }
}

function Convert-RealModeReleasePlanForFinalCheck {
  param(
    [object]$WorkspaceSnapshot
  )

  if (!$WorkspaceSnapshot -or !$WorkspaceSnapshot.real_mode_release_plan) {
    return $null
  }

  $plan = $WorkspaceSnapshot.real_mode_release_plan
  $modes = @($plan.modes | ForEach-Object {
    $checklist = @($_.readiness_checklist)
    $missingChecklist = @($checklist | Where-Object { $_.status -ne "passed" })
    [pscustomobject]@{
      mode = $_.mode
      label = $_.label
      status = $_.status
      allowed = [bool]$_.allowed
      releaseScope = $_.release_scope
      requiredEvidenceCount = @($_.required_evidence).Count
      requiredControlCount = @($_.required_controls).Count
      blockerCount = @($_.blockers).Count
      readinessChecklistCount = $checklist.Count
      missingChecklistCount = $missingChecklist.Count
      blockers = @($_.blockers)
      readinessChecklist = $checklist
    }
  })

  return [pscustomobject]@{
    schema = $plan.schema
    scope = $plan.scope
    publishAllowed = [bool]$plan.publish_allowed
    batchUnattendedPublishAllowed = [bool]$plan.batch_unattended_publish_allowed
    allowedModes = @($modes | Where-Object { $_.allowed } | ForEach-Object { $_.mode })
    blockedModes = @($modes | Where-Object { -not $_.allowed } | ForEach-Object { $_.mode })
    modes = $modes
  }
}

function Get-RealDxmWriteReadiness {
  param(
    [object]$L2Gate,
    [object]$L3Gate,
    [object]$L3EvidenceReadiness
  )

  if (!$L2Gate -or !$L3Gate) {
    return "UNKNOWN"
  }
  if ($L2Gate.status -eq "passed" -and $L3Gate.status -eq "passed") {
    if ($L3EvidenceReadiness -and $L3EvidenceReadiness.ready -eq $true) {
      return "READY"
    }
    return "BLOCKED"
  }
  return "BLOCKED"
}

function Get-RealDxmWriteBlockedReason {
  param(
    [object]$L2Gate,
    [object]$L3Gate,
    [object]$L3EvidenceReadiness
  )

  if (!$L2Gate -or !$L3Gate) {
    return "L2/L3 gate records unavailable; real DXM writes remain blocked."
  }
  if ($L2Gate.status -ne "passed") {
    return "L2 gate is $($L2Gate.status); real DXM writes require data_acquisition and draft_box real readonly pass in the same run."
  }
  if ($L3Gate.status -ne "passed") {
    return "L3 gate is $($L3Gate.status); real DXM writes require manual single-save canary approval and evidence."
  }
  if (!$L3EvidenceReadiness -or $L3EvidenceReadiness.ready -ne $true) {
    $missing = if ($L3EvidenceReadiness -and $L3EvidenceReadiness.missing) { $L3EvidenceReadiness.missing -join "; " } else { "L3 evidence completeness unknown" }
    return "L3 evidence incomplete: $missing."
  }
  return ""
}

function Get-SourcePackageCheck {
  param(
    [string]$SourcePackageReadiness
  )

  if (!$RequireCleanWorktree) {
    return "NOT_REQUIRED"
  }
  if ($SourcePackageReadiness -eq "CLEAN") {
    return "PASS"
  }
  return "FAIL"
}

function Remove-PostFinalReportQaArtifacts {
  $paths = @(
    $postFinalReportQaJson,
    (Join-Path $browserQaOutDir "qa-final-report-check.md"),
    (Join-Path $browserQaOutDir "qa-report-center-final.png"),
    (Join-Path $browserQaOutDir "qa-final-report-console.jsonl"),
    (Join-Path $browserQaOutDir "qa-final-report-network.json")
  )
  foreach ($path in $paths) {
    if ($path -and (Test-Path -LiteralPath $path)) {
      Remove-Item -LiteralPath $path -Force
    }
  }
}

function Write-ProvisionalDeliveryCheckReport {
  param(
    [object]$WorkspaceSnapshot,
    [string]$WorkspaceApiBase
  )

  $provisionalGitHead = $null
  $provisionalGitStatus = $null
  try {
    $provisionalGitHead = (& git -C $root rev-parse HEAD).Trim()
    $provisionalGitStatus = (& git -C $root status --short) -join "`n"
  } catch {
    $provisionalGitHead = $null
    $provisionalGitStatus = $null
  }

  $provisionalL2Gate = Get-WorkspaceGate -WorkspaceSnapshot $WorkspaceSnapshot -Level "L2"
  $provisionalL3Gate = Get-WorkspaceGate -WorkspaceSnapshot $WorkspaceSnapshot -Level "L3"
  $provisionalL3EvidenceReadiness = Get-L3EvidenceReadiness -WorkspaceSnapshot $WorkspaceSnapshot
  $provisionalReadiness = Get-RealDxmWriteReadiness -L2Gate $provisionalL2Gate -L3Gate $provisionalL3Gate -L3EvidenceReadiness $provisionalL3EvidenceReadiness
  $provisionalBlockedReason = Get-RealDxmWriteBlockedReason -L2Gate $provisionalL2Gate -L3Gate $provisionalL3Gate -L3EvidenceReadiness $provisionalL3EvidenceReadiness
  # Provisional report must be BLOCKED when gates are unavailable; Browser QA needs a fail-closed current-run state.
  if ($provisionalReadiness -eq "UNKNOWN") {
    $provisionalReadiness = "BLOCKED"
  }
  $provisionalControlledSingleSaveReady = $provisionalReadiness -eq "READY"
  $provisionalRealDxmMutationScope = if ($provisionalControlledSingleSaveReady) { "controlled_single_save_only" } else { "none" }
  $provisionalRealModeReleasePlan = Convert-RealModeReleasePlanForFinalCheck -WorkspaceSnapshot $WorkspaceSnapshot
  $sourceReadiness = if ([string]::IsNullOrWhiteSpace($provisionalGitStatus)) { "CLEAN" } else { "DIRTY" }

  $provisionalResult = [pscustomobject]@{
    schema = "dxm_final_delivery_check.v1"
    checkedAt = (Get-Date).ToUniversalTime().ToString("o")
    ok = $false
    okScope = "local_workbench_only"
    realDxmMutationAllowed = $provisionalControlledSingleSaveReady
    realDxmMutationScope = $provisionalRealDxmMutationScope
    controlledSingleSaveReady = $provisionalControlledSingleSaveReady
    batchUnattendedPublishAllowed = $false
    realModeReleasePlan = $provisionalRealModeReleasePlan
    expectedRealDxmWriteReadiness = $ExpectedRealDxmWriteReadiness
    realDxmWriteReadinessMatchesExpected = $provisionalReadiness -eq $ExpectedRealDxmWriteReadiness
    status = "final_delivery_check_in_progress_for_browser_qa"
    localWorkbenchCheck = "IN_PROGRESS"
    realDxmWriteReadiness = $provisionalReadiness
    productionRealWriteReady = $false
    realDxmWriteBlockedReason = $provisionalBlockedReason
    l3EvidenceReadiness = $provisionalL3EvidenceReadiness
    sourcePackageReadiness = $sourceReadiness
    preSourcePackageReadiness = $sourceReadiness
    postSourcePackageReadiness = $sourceReadiness
    requireCleanWorktree = [bool]$RequireCleanWorktree
    sourcePackageCheck = Get-SourcePackageCheck -SourcePackageReadiness $sourceReadiness
    gateEvidenceCheck = if ($provisionalL2Gate -and $provisionalL3Gate) { "PASS" } else { "FAIL" }
    deliverableMode = "DXM semi-managed automation workbench"
    realDxmWrites = if ($provisionalReadiness -eq "READY") { "controlled single_save is ready only after L2/L3 evidence review and explicit manual canary approval; batch/unattended/publish remain separately gated" } elseif ($provisionalReadiness -eq "UNKNOWN") { "unknown because L2/L3 gates could not be read; writes remain blocked" } else { "blocked until fresh real L2 data_acquisition and draft_box pass, followed by L3 manual canary evidence" }
    root = $root
    gitHead = $provisionalGitHead
    preGitStatusShort = $provisionalGitStatus
    postGitStatusShort = $provisionalGitStatus
    commands = $commands
    qaServices = @{
      backendPort = $qaBackendPort
      frontendPort = $qaFrontendPort
      workspaceApiBase = $WorkspaceApiBase
      pytestRuntimeDataDir = $pytestRuntimeDataDir
      qaRuntimeDataDir = $qaRuntimeDataDir
      isolated = $true
    }
    browserQa = $null
    gates = @{
      l2 = $provisionalL2Gate
      l3 = $provisionalL3Gate
    }
    artifacts = @{
      summary = $summaryPath
      json = $jsonPath
    }
  }

  Write-JsonNoBomFile -Path $jsonPath -Value $provisionalResult
}

function Resolve-Python {
  $venvPython = Join-Path $backendDir ".venv\Scripts\python.exe"
  if (Test-Path -LiteralPath $venvPython) {
    return $venvPython
  }
  $python = Get-Command python -ErrorAction SilentlyContinue
  if ($python) {
    return $python.Source
  }
  throw "Python was not found."
}

function Resolve-Npm {
  $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
  if ($npm) {
    return $npm.Source
  }
  $npm = Get-Command npm -ErrorAction SilentlyContinue
  if ($npm) {
    return $npm.Source
  }
  throw "npm was not found."
}

function Resolve-Node {
  $node = Get-Command node.exe -ErrorAction SilentlyContinue
  if ($node) {
    return $node.Source
  }
  $node = Get-Command node -ErrorAction SilentlyContinue
  if ($node) {
    return $node.Source
  }
  throw "node was not found."
}

function Read-QaJsonSummary {
  param([string]$Path)

  if (!(Test-Path -LiteralPath $Path)) {
    return $null
  }

  try {
    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
  } catch {
    # Windows PowerShell 5.1 can reject valid browser-captured JSON when DOM text
    # contains characters its JSON parser handles poorly. Keep the full artifact
    # on disk and re-read only the delivery-check fields through Node.
  }

  $code = @"
const fs = require('fs');
const input = JSON.parse(fs.readFileSync(process.argv[1], 'utf8'));
const slim = {
  checkedAt: input.checkedAt || null,
  url: input.url || null,
  mode: input.mode || null,
  ok: input.ok === true,
  assertions: input.assertions || {},
  screenshotHashes: input.screenshotHashes || {},
  sidecarHashes: input.sidecarHashes || {},
  environment: input.environment || {},
  manifest: input.manifest || {}
};
process.stdout.write(JSON.stringify(slim));
"@

  try {
    $output = & $nodeExe -e $code $Path
    if ($LASTEXITCODE -ne 0 -or !$output) {
      return $null
    }
    return (($output -join "`n") | ConvertFrom-Json)
  } catch {
    return $null
  }
}

function Test-CapturedPowerShellError {
  param([string]$Output)

  if ([string]::IsNullOrWhiteSpace($Output)) {
    return $false
  }
  return $Output -match '(?m)^\s*\+\s+CategoryInfo\s*:' `
    -or $Output -match '(?m)^\s*\+\s+FullyQualifiedErrorId\s*:' `
    -or $Output -match 'WriteErrorException'
}

function Test-PackagedDesktopSmokeError {
  param([string]$Output)

  if ([string]::IsNullOrWhiteSpace($Output)) {
    return $false
  }
  return $Output -match 'Portable smoke requires at least' `
    -or $Output -match 'Portable QA capture was not created' `
    -or $Output -match 'Portable smoke failed' `
    -or $Output -match 'Portable exe not found' `
    -or $Output -match 'Packaged smoke failed' `
    -or $Output -match 'Credential smoke failed'
}

function Invoke-CapturedCommand {
  param(
    [string]$Name,
    [string]$FilePath,
    [string[]]$Arguments,
    [string]$WorkingDirectory,
    [int]$TimeoutSeconds = 600
  )

  $startedAt = (Get-Date).ToUniversalTime()
  Write-Host "[$($startedAt.ToString("s"))Z] $Name"
  $slug = ($Name.ToLowerInvariant() -replace '[^a-z0-9]+', '-').Trim('-')
  $stdoutPath = Join-Path $absoluteOutDir "$slug.stdout.log"
  $stderrPath = Join-Path $absoluteOutDir "$slug.stderr.log"
  Remove-Item -LiteralPath $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue
  $argumentString = Join-CommandArguments $Arguments
  $process = Start-Process `
    -FilePath $FilePath `
    -ArgumentList $argumentString `
    -WorkingDirectory $WorkingDirectory `
    -RedirectStandardOutput $stdoutPath `
    -RedirectStandardError $stderrPath `
    -NoNewWindow `
    -PassThru
  $exited = $process.WaitForExit($TimeoutSeconds * 1000)
  if (!$exited) {
    Stop-ProcessTree -ProcessId $process.Id
    $process.WaitForExit()
  }
  $process.Refresh()
  $finishedAt = (Get-Date).ToUniversalTime()
  $stdout = if (Test-Path -LiteralPath $stdoutPath) { [string](Get-Content -LiteralPath $stdoutPath -Raw) } else { "" }
  $stderr = if (Test-Path -LiteralPath $stderrPath) { [string](Get-Content -LiteralPath $stderrPath -Raw) } else { "" }
  if ($null -eq $stdout) { $stdout = "" }
  if ($null -eq $stderr) { $stderr = "" }
  $exitCode = if ($exited -and $process.HasExited) { [int]$process.ExitCode } else { 124 }
  $combinedOutput = $stdout + "`n" + $stderr
  if ($Name -eq "Backend pytest" -and (($stdout + "`n" + $stderr) -match '(?m)(=+ FAILURES =+|=+ ERRORS =+|[1-9][0-9]* failed|[1-9][0-9]* error)')) {
    $exitCode = 1
  }
  if ($exitCode -eq 0 -and (Test-CapturedPowerShellError -Output $combinedOutput)) {
    $exitCode = 1
    $stderr = ($stderr.TrimEnd() + "`nCommand output contained a PowerShell error record; treating command as failed.").TrimStart()
  }
  if ($Name -eq "Packaged desktop smoke" -and $exitCode -eq 0 -and (Test-PackagedDesktopSmokeError -Output $combinedOutput)) {
    $exitCode = 1
    $stderr = ($stderr.TrimEnd() + "`nPackaged desktop smoke output contained a smoke failure; treating command as failed.").TrimStart()
  }

  if ($stdout.Trim()) {
    Write-Host $stdout.Trim()
  }
  if ($stderr.Trim()) {
    Write-Host $stderr.Trim()
  }

  [pscustomobject]@{
    name = $Name
    command = ($FilePath + " " + $argumentString)
    cwd = $WorkingDirectory
    exitCode = $exitCode
    ok = $exitCode -eq 0
    timedOut = -not $exited
    timeoutSeconds = $TimeoutSeconds
    startedAt = $startedAt.ToString("o")
    finishedAt = $finishedAt.ToString("o")
    stdoutLog = $stdoutPath
    stderrLog = $stderrPath
    stdoutTail = ($stdout -split "`r?`n" | Where-Object { $_ } | Select-Object -Last 40)
    stderrTail = ($stderr -split "`r?`n" | Where-Object { $_ } | Select-Object -Last 40)
  }
}

function Invoke-CapturedCommandWithEnvironment {
  param(
    [string]$Name,
    [string]$FilePath,
    [string[]]$Arguments,
    [string]$WorkingDirectory,
    [int]$TimeoutSeconds = 600,
    [hashtable]$Environment
  )

  $previousValues = @{}
  foreach ($key in $Environment.Keys) {
    $previousValues[$key] = [System.Environment]::GetEnvironmentVariable($key, "Process")
    [System.Environment]::SetEnvironmentVariable($key, [string]$Environment[$key], "Process")
  }
  try {
    return Invoke-CapturedCommand `
      -Name $Name `
      -FilePath $FilePath `
      -Arguments $Arguments `
      -WorkingDirectory $WorkingDirectory `
      -TimeoutSeconds $TimeoutSeconds
  } finally {
    foreach ($key in $Environment.Keys) {
      [System.Environment]::SetEnvironmentVariable($key, $previousValues[$key], "Process")
    }
  }
}

function Stop-ProcessTree {
  param([int]$ProcessId)

  try {
    Get-CimInstance Win32_Process -Filter "ParentProcessId=$ProcessId" | ForEach-Object {
      Stop-ProcessTree -ProcessId ([int]$_.ProcessId)
    }
  } catch {
    # Best-effort cleanup for timed-out commands.
  }
  Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

function Get-FreeTcpPort {
  param([int]$PreferredPort)

  $port = $PreferredPort
  while ($port -lt ($PreferredPort + 100)) {
    if (!(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)) {
      return $port
    }
    $port += 1
  }
  throw "No free TCP port found near $PreferredPort."
}

function Copy-AuthoritativeDataItem {
  param(
    [string]$Name,
    [string]$TargetDataDir
  )

  $sourcePath = Join-Path $authoritativeDataDir $Name
  if (!(Test-Path -LiteralPath $sourcePath)) {
    return
  }

  $sourceFullPath = (Resolve-Path -LiteralPath $sourcePath).Path
  $targetRootFullPath = (Resolve-Path -LiteralPath $TargetDataDir).Path
  if ($sourceFullPath -eq $targetRootFullPath) {
    throw "Refusing to seed QA runtime from itself: $sourceFullPath"
  }

  Copy-Item -LiteralPath $sourcePath -Destination $TargetDataDir -Recurse -Force
}

function Seed-QARuntimeData {
  param(
    [string]$TargetDataDir
  )

  New-Item -ItemType Directory -Path $TargetDataDir -Force | Out-Null
  foreach ($name in @("sqlite", "l2_readonly_probe", "screenshots", "evidences")) {
    Copy-AuthoritativeDataItem -Name $name -TargetDataDir $TargetDataDir
  }
}

function Start-BackgroundCommand {
  param(
    [string]$Name,
    [string]$FilePath,
    [string[]]$Arguments,
    [string]$WorkingDirectory
  )

  $slug = ($Name.ToLowerInvariant() -replace '[^a-z0-9]+', '-').Trim('-')
  $stdoutPath = Join-Path $absoluteOutDir "$slug.stdout.log"
  $stderrPath = Join-Path $absoluteOutDir "$slug.stderr.log"
  Remove-Item -LiteralPath $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue
  Write-Host "[$(((Get-Date).ToUniversalTime()).ToString("s"))Z] Starting $Name"
  $process = Start-Process `
    -FilePath $FilePath `
    -ArgumentList (Join-CommandArguments $Arguments) `
    -WorkingDirectory $WorkingDirectory `
    -RedirectStandardOutput $stdoutPath `
    -RedirectStandardError $stderrPath `
    -WindowStyle Hidden `
    -PassThru
  [pscustomobject]@{
    name = $Name
    process = $process
    stdoutLog = $stdoutPath
    stderrLog = $stderrPath
  }
}

function Start-BackgroundCommandWithEnvironment {
  param(
    [string]$Name,
    [string]$FilePath,
    [string[]]$Arguments,
    [string]$WorkingDirectory,
    [hashtable]$Environment
  )

  $previousValues = @{}
  foreach ($key in $Environment.Keys) {
    $previousValues[$key] = [System.Environment]::GetEnvironmentVariable($key, "Process")
    [System.Environment]::SetEnvironmentVariable($key, [string]$Environment[$key], "Process")
  }
  try {
    return Start-BackgroundCommand `
      -Name $Name `
      -FilePath $FilePath `
      -Arguments $Arguments `
      -WorkingDirectory $WorkingDirectory
  } finally {
    foreach ($key in $Environment.Keys) {
      [System.Environment]::SetEnvironmentVariable($key, $previousValues[$key], "Process")
    }
  }
}

function Wait-HttpReady {
  param(
    [string]$Name,
    [string]$Uri,
    [int]$TimeoutSeconds = 30
  )

  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  $lastError = $null
  while ((Get-Date) -lt $deadline) {
    try {
      Invoke-WebRequest -UseBasicParsing -Uri $Uri -TimeoutSec 2 | Out-Null
      Write-Host "[$(((Get-Date).ToUniversalTime()).ToString("s"))Z] $Name ready: $Uri"
      return
    } catch {
      $lastError = $_.Exception.Message
      Start-Sleep -Milliseconds 500
    }
  }
  throw "$Name did not become ready at $Uri. Last error: $lastError"
}

function Stop-QAProcesses {
  foreach ($entry in $qaProcesses) {
    if ($entry -and $entry.process -and !$entry.process.HasExited) {
      Stop-ProcessTree -ProcessId ([int]$entry.process.Id)
    }
  }
}

function Write-FatalDeliveryCheckReport {
  param([string]$Message)

  $fatalGitHead = $null
  $fatalGitStatus = $null
  try {
    $fatalGitHead = (& git -C $root rev-parse HEAD).Trim()
    $fatalGitStatus = (& git -C $root status --short) -join "`n"
  } catch {
    $fatalGitHead = $null
    $fatalGitStatus = $null
  }

  $fatalResult = [pscustomobject]@{
    schema = "dxm_final_delivery_check.v1"
    checkedAt = (Get-Date).ToUniversalTime().ToString("o")
    ok = $false
    okScope = "local_workbench_only"
    realDxmMutationAllowed = $false
    realDxmMutationScope = "none"
    controlledSingleSaveReady = $false
    batchUnattendedPublishAllowed = $false
    expectedRealDxmWriteReadiness = $ExpectedRealDxmWriteReadiness
    realDxmWriteReadinessMatchesExpected = $false
    status = "final_delivery_check_fatal_error"
    localWorkbenchCheck = "FAIL"
    realDxmWriteReadiness = "UNKNOWN"
    sourcePackageReadiness = if ([string]::IsNullOrWhiteSpace($fatalGitStatus)) { "CLEAN" } else { "DIRTY" }
    requireCleanWorktree = [bool]$RequireCleanWorktree
    sourcePackageCheck = if ($RequireCleanWorktree -and [string]::IsNullOrWhiteSpace($fatalGitStatus)) { "PASS" } elseif ($RequireCleanWorktree) { "FAIL" } else { "NOT_REQUIRED" }
    deliverableMode = "DXM semi-managed automation workbench"
    realDxmWrites = "unknown because final delivery check stopped before L2/L3 gates could be read"
    root = $root
    gitHead = $fatalGitHead
    preGitStatusShort = $fatalGitStatus
    postGitStatusShort = $fatalGitStatus
    fatalError = $Message
    commands = $commands
    artifacts = @{
      summary = $summaryPath
      json = $jsonPath
    }
  }

  Write-JsonNoBomFile -Path $jsonPath -Value $fatalResult

  $fatalLines = @(
    "# DXM Local Workbench Delivery Check",
    "",
    "- Checked at: $($fatalResult.checkedAt)",
    "- Local workbench check: FAIL",
    "- Real DXM write readiness: UNKNOWN",
    "- Source package readiness: $($fatalResult.sourcePackageReadiness)",
    "- Source package check: $($fatalResult.sourcePackageCheck)",
    "- Git HEAD: $($fatalResult.gitHead)",
    "- Fatal error: $Message",
    "",
    "## Recovery",
    "- Run `scripts\start-mvp.bat --check` to locate missing Python/npm/curl/backend/frontend dependencies.",
    "- If this happened during Browser QA startup, inspect `outputs\final-delivery-check\qa-backend-service.stderr.log` and `outputs\final-delivery-check\qa-frontend-preview.stderr.log`.",
    "- Do not treat UNKNOWN real DXM readiness as approval to write; true write operations remain blocked until L2/L3 evidence passes."
  )
  Set-Content -LiteralPath $summaryPath -Encoding UTF8 -Value ($fatalLines -join "`n")
}

trap {
  Stop-QAProcesses
  try {
    Write-FatalDeliveryCheckReport -Message ([string]$_.Exception.Message)
  } catch {
    Write-Warning "Could not write fatal delivery check report: $($_.Exception.Message)"
  }
  throw
}

function Join-CommandArguments {
  param([string[]]$Arguments)
  (($Arguments | ForEach-Object {
    if ($_ -match '[\s"]') {
      '"' + ($_.Replace('\', '\\').Replace('"', '\"')) + '"'
    } else {
      $_
    }
  }) -join " ")
}

$pythonExe = Resolve-Python
$npmExe = Resolve-Npm
$nodeExe = Resolve-Node
$preGitStatus = $null
try {
  $preGitStatus = (& git -C $root status --short) -join "`n"
} catch {
  $preGitStatus = $null
}
$commands += Invoke-CapturedCommand `
  -Name "Windows startup preflight" `
  -FilePath "cmd.exe" `
  -Arguments @("/c", "scripts\start-mvp.bat", "--check") `
  -WorkingDirectory $root `
  -TimeoutSeconds 180
Remove-Item -LiteralPath $pytestRuntimeDataDir -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $pytestRuntimeDataDir -Force | Out-Null
$commands += Invoke-CapturedCommandWithEnvironment `
  -Name "Backend pytest" `
  -FilePath $pythonExe `
  -Arguments @("-m", "pytest", "-q") `
  -WorkingDirectory $backendDir `
  -TimeoutSeconds 360 `
  -Environment @{ DXM_DATA_DIR = $pytestRuntimeDataDir }
$commands += Invoke-CapturedCommand `
  -Name "Frontend production build" `
  -FilePath $npmExe `
  -Arguments @("run", "build") `
  -WorkingDirectory $frontendDir `
  -TimeoutSeconds 180
$desktopBuildScript = if ($CheckPortableDesktop) { "build:portable" } else { "build" }
$commands += Invoke-CapturedCommand `
  -Name "Desktop production build" `
  -FilePath $npmExe `
  -Arguments @("run", $desktopBuildScript) `
  -WorkingDirectory $desktopDir `
  -TimeoutSeconds 600
$packagedDesktopSmokeArgs = @(
  "-NoProfile",
  "-ExecutionPolicy",
  "Bypass",
  "-File",
  "scripts\verify-desktop-package.ps1",
  "-WaitSeconds",
  "20",
  "-CapturePath",
  $packagedDesktopSmokeCapturePath,
  "-SmokeUserDataDir",
  $packagedDesktopSmokeUserDataDir,
  "-PortableCapturePath",
  $portableDesktopSmokeCapturePath,
  "-PortableSmokeUserDataDir",
  $portableDesktopSmokeUserDataDir,
  "-CredentialSmokePath",
  $packagedDesktopCredentialSmokePath,
  "-VisibleSmokePath",
  $packagedDesktopVisibleSmokePath,
  "-VisibleSmokeUserDataDir",
  $packagedDesktopVisibleSmokeUserDataDir
)
if ($CheckPortableDesktop) {
  $packagedDesktopSmokeArgs += "-CheckPortable"
}
$packagedDesktopSmokeCommand = Invoke-CapturedCommand `
  -Name "Packaged desktop smoke" `
  -FilePath "powershell.exe" `
  -Arguments $packagedDesktopSmokeArgs `
  -WorkingDirectory $root `
  -TimeoutSeconds 360
if ($CheckPortableDesktop -and $packagedDesktopSmokeCommand.ok) {
  $portableDesktopSmokeLogPath = Join-Path $portableDesktopSmokeUserDataDir "data\desktop-main.log"
  if (!(Test-Path -LiteralPath $portableDesktopSmokeCapturePath) -or !(Test-Path -LiteralPath $portableDesktopSmokeLogPath)) {
    $packagedDesktopSmokeCommand.exitCode = 1
    $packagedDesktopSmokeCommand.ok = $false
    $packagedDesktopSmokeCommand.stderrTail = @(
      "Portable desktop smoke evidence missing.",
      "Expected capture: $portableDesktopSmokeCapturePath",
      "Expected log: $portableDesktopSmokeLogPath"
    )
  }
}
$commands += $packagedDesktopSmokeCommand
$commands += Invoke-CapturedCommand `
  -Name "L1 selector replay" `
  -FilePath $pythonExe `
  -Arguments @("tools/probes/l1_selector_replay.py", "--output-dir", $l1ReplayOutDir) `
  -WorkingDirectory $root `
  -TimeoutSeconds 180
$commands += Invoke-CapturedCommand `
  -Name "Git whitespace check" `
  -FilePath "git" `
  -Arguments @("diff", "--check") `
  -WorkingDirectory $root `
  -TimeoutSeconds 120
$commands += Invoke-CapturedCommand `
  -Name "Git staged whitespace check" `
  -FilePath "git" `
  -Arguments @("diff", "--cached", "--check") `
  -WorkingDirectory $root `
  -TimeoutSeconds 120

if (!$SkipBrowserQA) {
  $qaBackendPort = Get-FreeTcpPort -PreferredPort 18000
  $qaFrontendPort = Get-FreeTcpPort -PreferredPort 15173
  $workspaceApiBase = "http://127.0.0.1:$qaBackendPort"
  Remove-Item -LiteralPath $qaRuntimeDataDir -Recurse -Force -ErrorAction SilentlyContinue
  New-Item -ItemType Directory -Path $qaRuntimeDataDir -Force | Out-Null
  Seed-QARuntimeData -TargetDataDir $qaRuntimeDataDir
  $viteCmd = Join-Path $frontendDir "node_modules\.bin\vite.cmd"
  if (!(Test-Path -LiteralPath $viteCmd)) {
    throw "Vite was not found at $viteCmd. Run scripts\start-mvp.bat --check first."
  }
  $qaProcesses += Start-BackgroundCommandWithEnvironment `
    -Name "QA backend service" `
    -FilePath $pythonExe `
    -Arguments @("-m", "uvicorn", "src.main:app", "--host", "127.0.0.1", "--port", [string]$qaBackendPort) `
    -WorkingDirectory $backendDir `
    -Environment @{ DXM_DATA_DIR = $qaRuntimeDataDir; DXM_FINAL_DELIVERY_CHECK_JSON = $jsonPath }
  Wait-HttpReady -Name "QA backend service" -Uri "$workspaceApiBase/health" -TimeoutSeconds 45
  $qaProcesses += Start-BackgroundCommand `
    -Name "QA frontend preview" `
    -FilePath $viteCmd `
    -Arguments @("preview", "--host", "127.0.0.1", "--port", [string]$qaFrontendPort, "--strictPort") `
    -WorkingDirectory $frontendDir
  Wait-HttpReady -Name "QA frontend preview" -Uri "http://127.0.0.1:$qaFrontendPort" -TimeoutSeconds 45
  # Browser QA reads /api/delivery/final-check before the full report is written.
  # Seed it with this run's authoritative git/gate context so QA never depends on a stale prior report.
  $provisionalWorkspaceSnapshot = Get-AuthoritativeWorkspaceSnapshot
  if (!$provisionalWorkspaceSnapshot) {
    $provisionalWorkspaceSnapshot = Get-WorkspaceSnapshot -ApiBase $workspaceApiBase
  }
  Write-ProvisionalDeliveryCheckReport -WorkspaceSnapshot $provisionalWorkspaceSnapshot -WorkspaceApiBase $workspaceApiBase
  $browserQaUrl = "http://127.0.0.1:$qaFrontendPort/?apiBase=$([uri]::EscapeDataString($workspaceApiBase))"
  $commands += Invoke-CapturedCommand `
    -Name "Browser workbench QA" `
    -FilePath "powershell.exe" `
    -Arguments @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "scripts\qa-browser-check.ps1", "-Url", $browserQaUrl, "-OutDir", $browserQaOutDir) `
    -WorkingDirectory $root `
    -TimeoutSeconds 180
}

$browserQa = $null
if (!$SkipBrowserQA -and (Test-Path -LiteralPath $browserQaJson)) {
  $browserQa = Read-QaJsonSummary -Path $browserQaJson
}

$gitHead = $null
$postGitStatus = $null
try {
  $gitHead = (& git -C $root rev-parse HEAD).Trim()
  $postGitStatus = (& git -C $root status --short) -join "`n"
} catch {
  $gitHead = $null
  $postGitStatus = $null
}

$workspaceSnapshot = $null
$workspaceSnapshot = Get-AuthoritativeWorkspaceSnapshot
if (!$workspaceSnapshot) {
  $workspaceSnapshot = Get-WorkspaceSnapshot -ApiBase $workspaceApiBase
}
$l2Gate = $null
$l3Gate = $null
$l2Gate = Get-WorkspaceGate -WorkspaceSnapshot $workspaceSnapshot -Level "L2"
$l3Gate = Get-WorkspaceGate -WorkspaceSnapshot $workspaceSnapshot -Level "L3"
$l2ProbePlan = if ($workspaceSnapshot -and $workspaceSnapshot.l2_probe_plan) { $workspaceSnapshot.l2_probe_plan } else { $null }
$l2ProbeEvidenceSummary = @()
$l2AllowlistReviewCandidates = @()
if ($l2Gate -and $l2Gate.latest) {
  $targetBuckets = @()
  if ((Get-JsonObjectPropertyCount $l2Gate.latest.realTargets) -gt 0) {
    $targetBuckets += [pscustomobject]@{ kind = "real"; targets = $l2Gate.latest.realTargets }
  }
  if ($targetBuckets.Count -eq 0 -and (Get-JsonObjectPropertyCount $l2Gate.latest.mockTargets) -gt 0) {
    $targetBuckets += [pscustomobject]@{ kind = "mock"; targets = $l2Gate.latest.mockTargets }
  }
  foreach ($bucket in $targetBuckets) {
    foreach ($targetProperty in $bucket.targets.PSObject.Properties) {
      $targetResult = $targetProperty.Value
      $network = $targetResult.network
      $diagnostics = $targetResult.diagnostics
      $navigation = if ($diagnostics) { $diagnostics.navigation } else { $null }
      $topBlockedGroups = @()
      if ($diagnostics -and $diagnostics.blocked_request_groups) {
        $topBlockedGroups = @($diagnostics.blocked_request_groups | Select-Object -First 3 | ForEach-Object {
          [pscustomobject]@{
            count = $_.count
            method = $_.method
            host = $_.host
            path = $_.path
            resource_type = $_.resource_type
            reasons = $_.reasons
          }
        })
      }
      if ($diagnostics -and $diagnostics.allowlist_review_candidates) {
        $l2AllowlistReviewCandidates += @($diagnostics.allowlist_review_candidates | ForEach-Object {
          [pscustomobject]@{
            target = $targetProperty.Name
            evidenceKind = $bucket.kind
            count = $_.count
            method = $_.method
            host = $_.host
            path = $_.path
            resource_type = $_.resource_type
            reasons = $_.reasons
            review_only = $_.review_only
            allowlist_applied = $_.allowlist_applied
          }
        })
      }
      $l2ProbeEvidenceSummary += [pscustomobject]@{
        target = $targetProperty.Name
        evidenceKind = $bucket.kind
        ok = $targetResult.ok
        run_id = $targetResult.run_id
        final_url = $targetResult.final_url
        final_path = if ($navigation) { $navigation.final_path } else { $null }
        final_path_class = if ($navigation) { $navigation.final_path_class } else { $null }
        json_path = $targetResult.json_path
        markdown_path = $targetResult.markdown_path
        screenshot_path = $targetResult.screenshot_path
        screenshot_sha256 = $targetResult.screenshot_sha256
        dom_path = $targetResult.dom_path
        dom_sha256 = $targetResult.dom_sha256
        network = @{
          write_request_count = if ($network) { $network.write_request_count } else { $null }
          non_read_request_count = if ($network) { $network.non_read_request_count } else { $null }
          blocked_request_count = if ($network) { $network.blocked_request_count } else { $null }
          forbidden_keyword_request_count = if ($network) { $network.forbidden_keyword_request_count } else { $null }
          websocket_count = if ($network) { $network.websocket_count } else { $null }
        }
        top_blocked_request_groups = $topBlockedGroups
      }
    }
  }
}

$gateEvidenceOk = [bool]($workspaceSnapshot -and $l2Gate -and $l3Gate)
$localWorkbenchOk = @($commands | Where-Object { -not $_.ok }).Count -eq 0
if (!$SkipBrowserQA -and (!$browserQa -or $browserQa.ok -ne $true)) {
  $localWorkbenchOk = $false
}
$l3EvidenceReadiness = Get-L3EvidenceReadiness -WorkspaceSnapshot $workspaceSnapshot
$realDxmWriteReadiness = Get-RealDxmWriteReadiness -L2Gate $l2Gate -L3Gate $l3Gate -L3EvidenceReadiness $l3EvidenceReadiness
$realDxmWriteBlockedReason = Get-RealDxmWriteBlockedReason -L2Gate $l2Gate -L3Gate $l3Gate -L3EvidenceReadiness $l3EvidenceReadiness
$preSourcePackageReadiness = if ([string]::IsNullOrWhiteSpace($preGitStatus)) { "CLEAN" } else { "DIRTY" }
$postSourcePackageReadiness = if ([string]::IsNullOrWhiteSpace($postGitStatus)) { "CLEAN" } else { "DIRTY" }
$sourcePackageReadiness = if ($preSourcePackageReadiness -eq "CLEAN" -and $postSourcePackageReadiness -eq "CLEAN") { "CLEAN" } else { "DIRTY" }
$sourcePackageCheck = Get-SourcePackageCheck -SourcePackageReadiness $sourcePackageReadiness
$controlledSingleSaveReady = $realDxmWriteReadiness -eq "READY"
$realDxmMutationAllowed = $controlledSingleSaveReady
$realDxmMutationScope = if ($controlledSingleSaveReady) { "controlled_single_save_only" } else { "none" }
$batchUnattendedPublishAllowed = $false
$realModeReleasePlan = Convert-RealModeReleasePlanForFinalCheck -WorkspaceSnapshot $workspaceSnapshot
$okScope = if ($controlledSingleSaveReady) { "local_workbench_and_controlled_single_save_ready" } else { "local_workbench_only" }
$realDxmWriteReadinessMatchesExpected = $realDxmWriteReadiness -eq $ExpectedRealDxmWriteReadiness
$overallOk = $localWorkbenchOk -and $gateEvidenceOk -and $realDxmWriteReadinessMatchesExpected -and (!$RequireCleanWorktree -or $sourcePackageCheck -eq "PASS")

$l2AllowlistReviewTemplate = [pscustomobject]@{
  schema = "dxm_l2_allowlist_review_template.v1"
  generatedAt = (Get-Date).ToUniversalTime().ToString("o")
  gitHead = $gitHead
  sourceFinalCheckJson = $jsonPath
  sourceFinalCheckMarkdown = $summaryPath
  reviewState = "pending"
  instructions = @(
    "Manual review only; filling this template does not pass L2.",
    "Keep allowlist_applied=false until a code change implements an explicit, minimal, audited allowlist.",
    "Reject write methods, WebSocket, EventSource, forbidden-keyword URLs, and any request without a clear read-only startup purpose.",
    "After any approved allowlist code change, rerun real L2 data_acquisition and draft_box with the same run-id before L3."
  )
  requiredFields = @("reviewer", "reviewed_at", "decision", "rationale", "approved_scope", "residual_risk")
  candidates = @($l2AllowlistReviewCandidates | ForEach-Object {
    [pscustomobject]@{
      target = $_.target
      evidenceKind = $_.evidenceKind
      method = $_.method
      host = $_.host
      path = $_.path
      resource_type = $_.resource_type
      count = $_.count
      reasons = $_.reasons
      review_only = $_.review_only
      allowlist_applied = $_.allowlist_applied
      reviewer = ""
      reviewed_at = ""
      decision = "pending"
      rationale = ""
      approved_scope = ""
      residual_risk = ""
      l2_recheck_required = $true
    }
  })
}
Write-JsonNoBomFile -Path $l2AllowlistReviewTemplateJsonPath -Value $l2AllowlistReviewTemplate

$l2ReviewTemplateLines = New-Object System.Collections.Generic.List[string]
$l2ReviewTemplateLines.Add("# L2 Allowlist Review Template")
$l2ReviewTemplateLines.Add("")
$l2ReviewTemplateLines.Add("- Generated at: $($l2AllowlistReviewTemplate.generatedAt)")
$l2ReviewTemplateLines.Add("- Git HEAD: $gitHead")
$l2ReviewTemplateLines.Add("- Review state: pending")
$l2ReviewTemplateLines.Add("- Source final check JSON: $jsonPath")
$l2ReviewTemplateLines.Add("- Source final check Markdown: $summaryPath")
$l2ReviewTemplateLines.Add("")
$l2ReviewTemplateLines.Add("## Rules")
foreach ($instruction in $l2AllowlistReviewTemplate.instructions) {
  $l2ReviewTemplateLines.Add("- $instruction")
}
$l2ReviewTemplateLines.Add("")
$l2ReviewTemplateLines.Add("## Candidates")
if ($l2AllowlistReviewCandidates.Count -gt 0) {
  foreach ($candidate in $l2AllowlistReviewCandidates) {
    $l2ReviewTemplateLines.Add("- [ ] $($candidate.target) [$($candidate.evidenceKind)] $($candidate.method) $($candidate.host)$($candidate.path) x$($candidate.count) / $($candidate.resource_type)")
    $l2ReviewTemplateLines.Add("  - reasons: $($candidate.reasons -join ', ')")
    $l2ReviewTemplateLines.Add("  - review_only=$($candidate.review_only); allowlist_applied=$($candidate.allowlist_applied)")
    $l2ReviewTemplateLines.Add("  - reviewer:")
    $l2ReviewTemplateLines.Add("  - reviewed_at:")
    $l2ReviewTemplateLines.Add("  - decision: pending | approve | reject")
    $l2ReviewTemplateLines.Add("  - rationale:")
    $l2ReviewTemplateLines.Add("  - approved_scope:")
    $l2ReviewTemplateLines.Add("  - residual_risk:")
    $l2ReviewTemplateLines.Add("  - l2_recheck_required: true")
  }
} else {
  $l2ReviewTemplateLines.Add("- No candidates were available in the workspace snapshot; keep real DXM writes blocked.")
}
$l2ReviewTemplateLines.Add("")
$l2ReviewTemplateLines.Add("## Completion Criteria")
$l2ReviewTemplateLines.Add("- Every candidate has reviewer, reviewed_at, decision and rationale.")
$l2ReviewTemplateLines.Add("- Approved candidates define an explicit minimal scope and residual risk.")
$l2ReviewTemplateLines.Add("- Rejected candidates remain blocked.")
$l2ReviewTemplateLines.Add("- Real L2 must be rerun after any code/config change; this template is not an L2 pass.")
Set-Content -LiteralPath $l2AllowlistReviewTemplateMarkdownPath -Encoding UTF8 -Value ($l2ReviewTemplateLines -join "`n")

$l2AllowlistReviewTemplateHashes = [pscustomobject]@{
  markdown_sha256 = (Get-FileHash -LiteralPath $l2AllowlistReviewTemplateMarkdownPath -Algorithm SHA256).Hash.ToLowerInvariant()
  json_sha256 = (Get-FileHash -LiteralPath $l2AllowlistReviewTemplateJsonPath -Algorithm SHA256).Hash.ToLowerInvariant()
}

$result = [pscustomobject]@{
  schema = "dxm_final_delivery_check.v1"
  checkedAt = (Get-Date).ToUniversalTime().ToString("o")
  ok = $overallOk
  okScope = $okScope
  realDxmMutationAllowed = $realDxmMutationAllowed
  realDxmMutationScope = $realDxmMutationScope
  controlledSingleSaveReady = $controlledSingleSaveReady
  batchUnattendedPublishAllowed = $batchUnattendedPublishAllowed
  realModeReleasePlan = $realModeReleasePlan
  expectedRealDxmWriteReadiness = $ExpectedRealDxmWriteReadiness
  realDxmWriteReadinessMatchesExpected = $realDxmWriteReadinessMatchesExpected
  status = if ($overallOk) {
    if ($RequireCleanWorktree) { "local_workbench_source_package_check_pass" } else { "local_workbench_check_pass" }
  } else {
    if ($RequireCleanWorktree -and $sourcePackageCheck -eq "FAIL") { "source_package_check_fail" } else { "local_workbench_check_fail" }
  }
  localWorkbenchCheck = if ($localWorkbenchOk) { "PASS" } else { "FAIL" }
  realDxmWriteReadiness = $realDxmWriteReadiness
  productionRealWriteReady = $false
  realDxmWriteBlockedReason = $realDxmWriteBlockedReason
  l3EvidenceReadiness = $l3EvidenceReadiness
  sourcePackageReadiness = $sourcePackageReadiness
  preSourcePackageReadiness = $preSourcePackageReadiness
  postSourcePackageReadiness = $postSourcePackageReadiness
  requireCleanWorktree = [bool]$RequireCleanWorktree
  sourcePackageCheck = $sourcePackageCheck
  checkPortableDesktop = [bool]$CheckPortableDesktop
  gateEvidenceCheck = if ($gateEvidenceOk) { "PASS" } else { "FAIL" }
  deliverableMode = "DXM semi-managed automation workbench"
  realDxmWrites = if ($realDxmWriteReadiness -eq "READY") { "controlled single_save is ready only after L2/L3 evidence review and explicit manual canary approval; batch/unattended/publish remain separately gated" } elseif ($realDxmWriteReadiness -eq "UNKNOWN") { "unknown because L2/L3 gates could not be read; writes remain blocked" } else { "blocked until fresh real L2 data_acquisition and draft_box pass, followed by L3 manual canary evidence" }
  root = $root
  gitHead = $gitHead
  preGitStatusShort = $preGitStatus
  postGitStatusShort = $postGitStatus
  commands = $commands
  qaServices = @{
    backendPort = $qaBackendPort
    frontendPort = $qaFrontendPort
    workspaceApiBase = $workspaceApiBase
    pytestRuntimeDataDir = $pytestRuntimeDataDir
    qaRuntimeDataDir = $qaRuntimeDataDir
    isolated = -not [bool]$SkipBrowserQA
  }
  browserQa = $browserQa
  postFinalReportQa = $null
  l2ProbePlan = $l2ProbePlan
  l2ProbeEvidenceSummary = $l2ProbeEvidenceSummary
  l2AllowlistReviewCandidates = $l2AllowlistReviewCandidates
  l2AllowlistReviewTemplate = $l2AllowlistReviewTemplate
  l2AllowlistReviewTemplateHashes = $l2AllowlistReviewTemplateHashes
  gates = @{
    l2 = $l2Gate
    l3 = $l3Gate
  }
  artifacts = @{
    summary = $summaryPath
    json = $jsonPath
    packagedDesktopSmokeCapture = $packagedDesktopSmokeCapturePath
    packagedDesktopSmokeUserDataDir = $packagedDesktopSmokeUserDataDir
    portableDesktopSmokeCapture = $portableDesktopSmokeCapturePath
    portableDesktopSmokeUserDataDir = $portableDesktopSmokeUserDataDir
    packagedDesktopCredentialSmoke = $packagedDesktopCredentialSmokePath
    packagedDesktopVisibleSmoke = $packagedDesktopVisibleSmokePath
    packagedDesktopVisibleSmokeUserDataDir = $packagedDesktopVisibleSmokeUserDataDir
    l2AllowlistReviewTemplateMarkdown = $l2AllowlistReviewTemplateMarkdownPath
    l2AllowlistReviewTemplateJson = $l2AllowlistReviewTemplateJsonPath
    l1SelectorReplayDir = $l1ReplayOutDir
    browserQaJson = $browserQaJson
    browserQaMarkdown = (Join-Path $browserQaOutDir "qa-browser-check.md")
    postFinalReportQaJson = $postFinalReportQaJson
    postFinalReportQaMarkdown = (Join-Path $browserQaOutDir "qa-final-report-check.md")
    taskCenterScreenshot = (Join-Path $browserQaOutDir "qa-task-center.png")
    executionConsoleScreenshot = (Join-Path $browserQaOutDir "qa-execution-console.png")
    reportCenterScreenshot = (Join-Path $browserQaOutDir "qa-report-center.png")
    finalReportCenterScreenshot = (Join-Path $browserQaOutDir "qa-report-center-final.png")
    mobileTaskScreenshot = (Join-Path $browserQaOutDir "qa-mobile-task-center.png")
    qaConsole = (Join-Path $browserQaOutDir "qa-console.jsonl")
    qaNetwork = (Join-Path $browserQaOutDir "qa-network.json")
    qaBlockedActions = (Join-Path $browserQaOutDir "qa-blocked-actions.json")
  }
}

Write-JsonNoBomFile -Path $jsonPath -Value $result

$postFinalReportQa = $null
if (!$SkipBrowserQA) {
  # The main Browser QA screenshot captures the provisional report used during the run.
  # After writing the final JSON, first verify the final report state, then write that
  # result back and verify the report center visibly exposes the final-page QA evidence.
  Remove-PostFinalReportQaArtifacts
  $postFinalReportStateQaCommand = Invoke-CapturedCommand `
    -Name "Final report state QA" `
    -FilePath "powershell.exe" `
    -Arguments @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "scripts\qa-browser-check.ps1", "-Url", $browserQaUrl, "-OutDir", $browserQaOutDir, "-ReportOnlyFinal", "-AllowMissingPostFinalQa") `
    -WorkingDirectory $root `
    -TimeoutSeconds 180
  $commands += $postFinalReportStateQaCommand
  if (Test-Path -LiteralPath $postFinalReportQaJson) {
    $postFinalReportQa = Read-QaJsonSummary -Path $postFinalReportQaJson
  }
  if (!$postFinalReportStateQaCommand.ok -or !$postFinalReportQa -or $postFinalReportQa.ok -ne $true) {
    $localWorkbenchOk = $false
  }
  $overallOk = $localWorkbenchOk -and $gateEvidenceOk -and $realDxmWriteReadinessMatchesExpected -and (!$RequireCleanWorktree -or $sourcePackageCheck -eq "PASS")
  $result.ok = $overallOk
  $result.status = if ($overallOk) {
    if ($RequireCleanWorktree) { "local_workbench_source_package_check_pass" } else { "local_workbench_check_pass" }
  } else {
    if ($RequireCleanWorktree -and $sourcePackageCheck -eq "FAIL") { "source_package_check_fail" } else { "local_workbench_check_fail" }
  }
  $result.localWorkbenchCheck = if ($localWorkbenchOk) { "PASS" } else { "FAIL" }
  $result.commands = $commands
  $result.postFinalReportQa = $postFinalReportQa
  Write-JsonNoBomFile -Path $jsonPath -Value $result

  Remove-PostFinalReportQaArtifacts
  $postFinalReportQa = $null
  $postFinalReportCenterQaCommand = Invoke-CapturedCommand `
    -Name "Final report center QA" `
    -FilePath "powershell.exe" `
    -Arguments @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "scripts\qa-browser-check.ps1", "-Url", $browserQaUrl, "-OutDir", $browserQaOutDir, "-ReportOnlyFinal") `
    -WorkingDirectory $root `
    -TimeoutSeconds 180
  $commands += $postFinalReportCenterQaCommand
  if (Test-Path -LiteralPath $postFinalReportQaJson) {
    $postFinalReportQa = Read-QaJsonSummary -Path $postFinalReportQaJson
  }
  if (!$postFinalReportCenterQaCommand.ok -or !$postFinalReportQa -or $postFinalReportQa.ok -ne $true) {
    $localWorkbenchOk = $false
  }
  $overallOk = $localWorkbenchOk -and $gateEvidenceOk -and $realDxmWriteReadinessMatchesExpected -and (!$RequireCleanWorktree -or $sourcePackageCheck -eq "PASS")
  $result.ok = $overallOk
  $result.status = if ($overallOk) {
    if ($RequireCleanWorktree) { "local_workbench_source_package_check_pass" } else { "local_workbench_check_pass" }
  } else {
    if ($RequireCleanWorktree -and $sourcePackageCheck -eq "FAIL") { "source_package_check_fail" } else { "local_workbench_check_fail" }
  }
  $result.localWorkbenchCheck = if ($localWorkbenchOk) { "PASS" } else { "FAIL" }
  $result.commands = $commands
  $result.postFinalReportQa = $postFinalReportQa
  Write-JsonNoBomFile -Path $jsonPath -Value $result
}

$summaryLines = New-Object System.Collections.Generic.List[string]
$summaryLines.Add("# DXM Semi-Managed Automation Workbench Delivery Check")
$summaryLines.Add("")
$summaryLines.Add("- Checked at: $($result.checkedAt)")
$summaryLines.Add("- OK scope: $($result.okScope)")
$summaryLines.Add("- Real DXM mutation allowed: $($result.realDxmMutationAllowed)")
$summaryLines.Add("- Real DXM mutation scope: $($result.realDxmMutationScope)")
$summaryLines.Add("- Controlled single_save ready: $($result.controlledSingleSaveReady)")
$summaryLines.Add("- Batch/unattended/publish allowed: $($result.batchUnattendedPublishAllowed)")
$summaryLines.Add("- Production batch/unattended/publish ready: $($result.productionRealWriteReady)")
$summaryLines.Add("- Real DXM write blocked reason: $($result.realDxmWriteBlockedReason)")
$summaryLines.Add("- Expected real DXM write readiness: $($result.expectedRealDxmWriteReadiness)")
$summaryLines.Add("- Real DXM write readiness matches expected: $($result.realDxmWriteReadinessMatchesExpected)")
$summaryLines.Add("- Local workbench check: $($result.localWorkbenchCheck)")
$summaryLines.Add("- Real DXM write readiness: $($result.realDxmWriteReadiness)")
$summaryLines.Add("- Source package readiness: $($result.sourcePackageReadiness)")
$summaryLines.Add("- Require clean worktree: $($result.requireCleanWorktree)")
$summaryLines.Add("- Source package check: $($result.sourcePackageCheck)")
$summaryLines.Add("- Gate record readability: $($result.gateEvidenceCheck)")
$summaryLines.Add("- Gate record note: PASS only means L2/L3 records were readable; it is not an L2/L3 gate pass.")
$summaryLines.Add("- Deliverable mode: $($result.deliverableMode)")
$summaryLines.Add("- Real DXM writes: $($result.realDxmWrites)")
$summaryLines.Add("- Git HEAD: $($result.gitHead)")
$summaryLines.Add("- Acceptance note: PASS means the automation workbench checks pass, required source package checks pass, and real DXM readiness is derived from L2/L3 gates; UNKNOWN is a failure and does not approve writes.")
$summaryLines.Add("- READY note: real DXM READY currently means controlled single_save readiness only; batch, unattended operation, and publish remain separately gated. READY requires L2/L3 passed plus L3 save_result, published=false proof, save/unpublished screenshots or paths, and network/HAR save response evidence.")
if (!$SkipBrowserQA) {
  $summaryLines.Add("- Browser QA services: isolated backend $qaBackendPort / frontend $qaFrontendPort")
}
$summaryLines.Add("")
$summaryLines.Add("## Real Mode Release Plan")
if ($result.realModeReleasePlan) {
  $summaryLines.Add("- Scope: $($result.realModeReleasePlan.scope)")
  $summaryLines.Add("- Publish allowed: $($result.realModeReleasePlan.publishAllowed)")
  $summaryLines.Add("- Batch/unattended/publish allowed: $($result.realModeReleasePlan.batchUnattendedPublishAllowed)")
  $summaryLines.Add("- Allowed modes: $($result.realModeReleasePlan.allowedModes -join ', ')")
  $summaryLines.Add("- Blocked modes: $($result.realModeReleasePlan.blockedModes -join ', ')")
  foreach ($mode in $result.realModeReleasePlan.modes) {
    $summaryLines.Add("- $($mode.mode): status=$($mode.status), allowed=$($mode.allowed), release_scope=$($mode.releaseScope), missing_checklist=$($mode.missingChecklistCount)/$($mode.readinessChecklistCount)")
    if ($mode.blockers.Count -gt 0) {
      $summaryLines.Add("  - blockers: $($mode.blockers -join '; ')")
    }
  }
} else {
  $summaryLines.Add("- Real mode release plan was unavailable from the workspace snapshot; do not infer claim_only, batch_save, unattended, or publish readiness.")
}
$summaryLines.Add("")
$summaryLines.Add("## Safety Gates")
if ($l2Gate) {
  $summaryLines.Add("- L2: $($l2Gate.status)")
  if ($l2Gate.status -ne "passed") {
    $summaryLines.Add("  - reason: $($l2Gate.detail)")
  }
} else {
  $summaryLines.Add("- L2: UNKNOWN - backend workspace snapshot was unavailable")
}
if ($l3Gate) {
  $summaryLines.Add("- L3: $($l3Gate.status)")
  if ($l3Gate.status -ne "passed") {
    $summaryLines.Add("  - reason: controlled real DXM save remains blocked until L2 passes and L3 manual canary evidence is collected")
  }
} else {
  $summaryLines.Add("- L3: UNKNOWN - backend workspace snapshot was unavailable")
}
$summaryLines.Add("")
$summaryLines.Add("## L2 Readonly Probe Evidence")
if ($l2ProbeEvidenceSummary.Count -gt 0) {
  foreach ($item in $l2ProbeEvidenceSummary) {
    $summaryLines.Add("- $($item.target) [$($item.evidenceKind)] ok=$($item.ok) run_id=$($item.run_id)")
    $summaryLines.Add("  - final_url: $($item.final_url)")
    if ($item.final_path) {
      $summaryLines.Add("  - final_path: $($item.final_path) ($($item.final_path_class))")
    }
    $summaryLines.Add("  - network: write_request_count=$($item.network.write_request_count), non_read_request_count=$($item.network.non_read_request_count), blocked_request_count=$($item.network.blocked_request_count), forbidden_keyword_request_count=$($item.network.forbidden_keyword_request_count), websocket_count=$($item.network.websocket_count)")
    $summaryLines.Add("  - json_path: $($item.json_path)")
    $summaryLines.Add("  - markdown_path: $($item.markdown_path)")
    $summaryLines.Add("  - screenshot_path: $($item.screenshot_path)")
    $summaryLines.Add("  - screenshot_sha256: $($item.screenshot_sha256)")
    $summaryLines.Add("  - dom_path: $($item.dom_path)")
    $summaryLines.Add("  - dom_sha256: $($item.dom_sha256)")
    if ($item.top_blocked_request_groups.Count -gt 0) {
      foreach ($group in $item.top_blocked_request_groups) {
        $summaryLines.Add("  - blocked_group: $($group.method) $($group.host)$($group.path) x$($group.count) / $($group.resource_type) / $($group.reasons -join ', ')")
      }
    }
  }
} else {
  $summaryLines.Add("- No L2 readonly probe evidence was available in the workspace snapshot.")
}
$summaryLines.Add("")
$summaryLines.Add("## L2 Allowlist Review Candidates")
if ($l2AllowlistReviewCandidates.Count -gt 0) {
  $summaryLines.Add("- These entries are manual review only; not an L2 pass and not automatically allowlisted.")
  foreach ($candidate in $l2AllowlistReviewCandidates) {
    $summaryLines.Add("- $($candidate.target) [$($candidate.evidenceKind)] $($candidate.method) $($candidate.host)$($candidate.path) x$($candidate.count) / $($candidate.resource_type)")
    $summaryLines.Add("  - reasons: $($candidate.reasons -join ', ')")
    $summaryLines.Add("  - review_only=$($candidate.review_only); allowlist_applied=$($candidate.allowlist_applied)")
  }
} else {
  $summaryLines.Add("- No L2 allowlist review candidates were available in the workspace snapshot.")
}
$summaryLines.Add("")
$summaryLines.Add("## L2 Allowlist Review Template")
$summaryLines.Add("- Markdown: $l2AllowlistReviewTemplateMarkdownPath")
$summaryLines.Add("- Markdown sha256: $($l2AllowlistReviewTemplateHashes.markdown_sha256)")
$summaryLines.Add("- JSON: $l2AllowlistReviewTemplateJsonPath")
$summaryLines.Add("- JSON sha256: $($l2AllowlistReviewTemplateHashes.json_sha256)")
$summaryLines.Add("- State: pending manual review; this template is not an L2 pass.")
$summaryLines.Add("- Required fields: reviewer, reviewed_at, decision, rationale, approved_scope, residual_risk.")
$summaryLines.Add("")
$summaryLines.Add("## L2 Recheck Plan")
if ($l2ProbePlan) {
  $summaryLines.Add("- Purpose: $($l2ProbePlan.purpose)")
  $summaryLines.Add("- Requires approval: $($l2ProbePlan.requiresApproval)")
  $summaryLines.Add("- Cookie file: $($l2ProbePlan.cookieFile)")
  $summaryLines.Add("- Output dir: $($l2ProbePlan.outputDir)")
  foreach ($command in $l2ProbePlan.commands) {
    $summaryLines.Add("- Command: $command")
  }
  foreach ($criterion in $l2ProbePlan.acceptanceCriteria) {
    $summaryLines.Add("- Acceptance: $criterion")
  }
  foreach ($note in $l2ProbePlan.safetyNotes) {
    $summaryLines.Add("- Safety: $note")
  }
} else {
  $summaryLines.Add("- L2 recheck plan was unavailable from the workspace API.")
}
$summaryLines.Add("")
$summaryLines.Add("## Commands")
foreach ($command in $commands) {
  $timeoutText = if ($command.timedOut) { " timed_out=true" } else { "" }
  $summaryLines.Add("- $(if ($command.ok) { "PASS" } else { "FAIL" }) $($command.name) exit=$($command.exitCode)$timeoutText")
  $summaryLines.Add("  - stdout: $($command.stdoutLog)")
  $summaryLines.Add("  - stderr: $($command.stderrLog)")
}
$summaryLines.Add("")
$packagedDesktopSmokeCommand = $commands | Where-Object { $_.name -eq "Packaged desktop smoke" } | Select-Object -Last 1
$summaryLines.Add("## Packaged Desktop Smoke")
$summaryLines.Add("- Packaged desktop smoke: $(if ($packagedDesktopSmokeCommand -and $packagedDesktopSmokeCommand.ok) { "PASS" } else { "FAIL/MISSING" })")
$summaryLines.Add("- Portable desktop smoke: $(if ($CheckPortableDesktop) { "ENABLED" } else { "SKIPPED" })")
$summaryLines.Add("- Packaged desktop capture: $($result.artifacts.packagedDesktopSmokeCapture)")
$summaryLines.Add("- Packaged desktop user data: $($result.artifacts.packagedDesktopSmokeUserDataDir)")
$summaryLines.Add("- Packaged visible window smoke: $($result.artifacts.packagedDesktopVisibleSmoke)")
$summaryLines.Add("- Packaged visible window user data: $($result.artifacts.packagedDesktopVisibleSmokeUserDataDir)")
$summaryLines.Add("- Portable desktop capture: $($result.artifacts.portableDesktopSmokeCapture)")
$summaryLines.Add("- Portable desktop user data: $($result.artifacts.portableDesktopSmokeUserDataDir)")
$summaryLines.Add("- Packaged credential smoke: $($result.artifacts.packagedDesktopCredentialSmoke)")
$summaryLines.Add("")
$summaryLines.Add("## Browser QA")
$summaryLines.Add("- Browser QA: $(if ($browserQa -and $browserQa.ok -eq $true) { "PASS" } elseif ($SkipBrowserQA) { "SKIPPED" } else { "FAIL/MISSING" })")
if ($browserQa -and $browserQa.assertions) {
  foreach ($property in $browserQa.assertions.PSObject.Properties) {
    $summaryLines.Add("- $(if ($property.Value) { "PASS" } else { "FAIL" }) $($property.Name)")
  }
}
$summaryLines.Add("")
$summaryLines.Add("## Final Report Center QA")
$summaryLines.Add("- Final report center QA: $(if ($postFinalReportQa -and $postFinalReportQa.ok -eq $true) { "PASS" } elseif ($SkipBrowserQA) { "SKIPPED" } else { "FAIL/MISSING" })")
if ($postFinalReportQa -and $postFinalReportQa.assertions) {
  foreach ($property in $postFinalReportQa.assertions.PSObject.Properties) {
    $summaryLines.Add("- $(if ($property.Value) { "PASS" } else { "FAIL" }) $($property.Name)")
  }
}
$summaryLines.Add("")
$summaryLines.Add("## Artifacts")
$summaryLines.Add("- JSON: $jsonPath")
$summaryLines.Add("- Packaged desktop smoke capture: $($result.artifacts.packagedDesktopSmokeCapture)")
$summaryLines.Add("- Packaged desktop user data: $($result.artifacts.packagedDesktopSmokeUserDataDir)")
$summaryLines.Add("- Packaged visible window smoke: $($result.artifacts.packagedDesktopVisibleSmoke)")
$summaryLines.Add("- Packaged visible window user data: $($result.artifacts.packagedDesktopVisibleSmokeUserDataDir)")
$summaryLines.Add("- Portable desktop smoke capture: $($result.artifacts.portableDesktopSmokeCapture)")
$summaryLines.Add("- Portable desktop user data: $($result.artifacts.portableDesktopSmokeUserDataDir)")
$summaryLines.Add("- Packaged credential smoke: $($result.artifacts.packagedDesktopCredentialSmoke)")
$summaryLines.Add("- Browser QA JSON: $($result.artifacts.browserQaJson)")
$summaryLines.Add("- Browser QA Markdown: $($result.artifacts.browserQaMarkdown)")
$summaryLines.Add("- Final report QA JSON: $($result.artifacts.postFinalReportQaJson)")
$summaryLines.Add("- Final report QA Markdown: $($result.artifacts.postFinalReportQaMarkdown)")
$summaryLines.Add("- Task screenshot: $($result.artifacts.taskCenterScreenshot)")
$summaryLines.Add("- Console screenshot: $($result.artifacts.executionConsoleScreenshot)")
$summaryLines.Add("- Report screenshot: $($result.artifacts.reportCenterScreenshot)")
$summaryLines.Add("- Final report screenshot: $($result.artifacts.finalReportCenterScreenshot)")
$summaryLines.Add("- Mobile task screenshot: $($result.artifacts.mobileTaskScreenshot)")
$summaryLines.Add("- Console sidecar: $($result.artifacts.qaConsole)")
$summaryLines.Add("- Network sidecar: $($result.artifacts.qaNetwork)")
$summaryLines.Add("- Blocked actions sidecar: $($result.artifacts.qaBlockedActions)")
$summaryLines.Add("")
$summaryLines.Add("## Worktree")
if ([string]::IsNullOrWhiteSpace($preGitStatus)) {
  $summaryLines.Add("- Pre-run git status: clean")
} else {
  $summaryLines.Add("- Pre-run git status: dirty/uncommitted changes present")
}
if ([string]::IsNullOrWhiteSpace($postGitStatus)) {
  $summaryLines.Add("- Post-run git status: clean")
} else {
  $summaryLines.Add("- Post-run git status: dirty/uncommitted changes present")
}
$summaryLines.Add("")

Set-Content -LiteralPath $summaryPath -Encoding UTF8 -Value ($summaryLines -join "`n")

Get-Content -LiteralPath $summaryPath

Stop-QAProcesses

if (!$overallOk) {
  exit 1
}
