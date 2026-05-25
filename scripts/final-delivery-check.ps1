param(
  [switch]$SkipBrowserQA,
  [switch]$RequireCleanWorktree,
  [string]$OutDir = "outputs/final-delivery-check"
)

$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$backendDir = Join-Path $root "app\backend"
$frontendDir = Join-Path $root "app\frontend"
$absoluteOutDir = if ([System.IO.Path]::IsPathRooted($OutDir)) { $OutDir } else { Join-Path $root $OutDir }
$browserQaOutDir = Join-Path $absoluteOutDir "browser-checks"
$browserQaJson = Join-Path $browserQaOutDir "qa-browser-check.json"
$summaryPath = Join-Path $absoluteOutDir "final-delivery-check.md"
$jsonPath = Join-Path $absoluteOutDir "final-delivery-check.json"
$qaProcesses = @()
$qaBackendPort = $null
$qaFrontendPort = $null
$workspaceApiBase = "http://127.0.0.1:8000"

New-Item -ItemType Directory -Path $absoluteOutDir -Force | Out-Null
New-Item -ItemType Directory -Path $browserQaOutDir -Force | Out-Null

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
  if ($Name -eq "Backend pytest" -and (($stdout + "`n" + $stderr) -match '(?m)(=+ FAILURES =+|=+ ERRORS =+|[1-9][0-9]* failed|[1-9][0-9]* error)')) {
    $exitCode = 1
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

trap {
  Stop-QAProcesses
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
$preGitStatus = $null
try {
  $preGitStatus = (& git -C $root status --short) -join "`n"
} catch {
  $preGitStatus = $null
}
$commands = @()
$commands += Invoke-CapturedCommand `
  -Name "Windows startup preflight" `
  -FilePath "cmd.exe" `
  -Arguments @("/c", "scripts\start-mvp.bat", "--check") `
  -WorkingDirectory $root `
  -TimeoutSeconds 180
$commands += Invoke-CapturedCommand `
  -Name "Backend pytest" `
  -FilePath $pythonExe `
  -Arguments @("-m", "pytest", "-q") `
  -WorkingDirectory $backendDir `
  -TimeoutSeconds 180
$commands += Invoke-CapturedCommand `
  -Name "Frontend production build" `
  -FilePath $npmExe `
  -Arguments @("run", "build") `
  -WorkingDirectory $frontendDir `
  -TimeoutSeconds 180
$commands += Invoke-CapturedCommand `
  -Name "L1 selector replay" `
  -FilePath $pythonExe `
  -Arguments @("tools/probes/l1_selector_replay.py", "--output-dir", "data/l1_selector_replay") `
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
  $viteCmd = Join-Path $frontendDir "node_modules\.bin\vite.cmd"
  if (!(Test-Path -LiteralPath $viteCmd)) {
    throw "Vite was not found at $viteCmd. Run scripts\start-mvp.bat --check first."
  }
  $qaProcesses += Start-BackgroundCommand `
    -Name "QA backend service" `
    -FilePath $pythonExe `
    -Arguments @("-m", "uvicorn", "src.main:app", "--host", "127.0.0.1", "--port", [string]$qaBackendPort) `
    -WorkingDirectory $backendDir
  Wait-HttpReady -Name "QA backend service" -Uri "$workspaceApiBase/health" -TimeoutSeconds 45
  $qaProcesses += Start-BackgroundCommand `
    -Name "QA frontend preview" `
    -FilePath $viteCmd `
    -Arguments @("preview", "--host", "127.0.0.1", "--port", [string]$qaFrontendPort, "--strictPort") `
    -WorkingDirectory $frontendDir
  Wait-HttpReady -Name "QA frontend preview" -Uri "http://127.0.0.1:$qaFrontendPort" -TimeoutSeconds 45
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
  try {
    $browserQa = Get-Content -LiteralPath $browserQaJson -Raw | ConvertFrom-Json
  } catch {
    $browserQa = $null
  }
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
try {
  $workspaceSnapshot = Invoke-RestMethod -Uri "$workspaceApiBase/api/delivery/workspace" -TimeoutSec 5
} catch {
  $workspaceSnapshot = $null
}
$l2Gate = $null
$l3Gate = $null
if ($workspaceSnapshot -and $workspaceSnapshot.regression_gates) {
  $l2Gate = $workspaceSnapshot.regression_gates | Where-Object { $_.level -eq "L2" } | Select-Object -First 1
  $l3Gate = $workspaceSnapshot.regression_gates | Where-Object { $_.level -eq "L3" } | Select-Object -First 1
}

$localWorkbenchOk = @($commands | Where-Object { -not $_.ok }).Count -eq 0
if (!$SkipBrowserQA -and (!$browserQa -or $browserQa.ok -ne $true)) {
  $localWorkbenchOk = $false
}
$realDxmWriteReadiness = "BLOCKED"
$preSourcePackageReadiness = if ([string]::IsNullOrWhiteSpace($preGitStatus)) { "CLEAN" } else { "DIRTY" }
$postSourcePackageReadiness = if ([string]::IsNullOrWhiteSpace($postGitStatus)) { "CLEAN" } else { "DIRTY" }
$sourcePackageReadiness = if ($preSourcePackageReadiness -eq "CLEAN" -and $postSourcePackageReadiness -eq "CLEAN") { "CLEAN" } else { "DIRTY" }
$sourcePackageCheck = if (!$RequireCleanWorktree) {
  "NOT_REQUIRED"
} elseif ($sourcePackageReadiness -eq "CLEAN") {
  "PASS"
} else {
  "FAIL"
}
$overallOk = $localWorkbenchOk -and (!$RequireCleanWorktree -or $sourcePackageCheck -eq "PASS")

$result = [pscustomobject]@{
  schema = "dxm_final_delivery_check.v1"
  checkedAt = (Get-Date).ToUniversalTime().ToString("o")
  ok = $overallOk
  status = if ($overallOk) {
    if ($RequireCleanWorktree) { "local_workbench_source_package_check_pass" } else { "local_workbench_check_pass" }
  } else {
    if ($RequireCleanWorktree -and $sourcePackageCheck -eq "FAIL") { "source_package_check_fail" } else { "local_workbench_check_fail" }
  }
  localWorkbenchCheck = if ($localWorkbenchOk) { "PASS" } else { "FAIL" }
  realDxmWriteReadiness = $realDxmWriteReadiness
  sourcePackageReadiness = $sourcePackageReadiness
  preSourcePackageReadiness = $preSourcePackageReadiness
  postSourcePackageReadiness = $postSourcePackageReadiness
  requireCleanWorktree = [bool]$RequireCleanWorktree
  sourcePackageCheck = $sourcePackageCheck
  deliverableMode = "local safety diagnostic workbench"
  realDxmWrites = "blocked until real L2 data_acquisition and draft_box pass, followed by L3 manual canary"
  root = $root
  gitHead = $gitHead
  preGitStatusShort = $preGitStatus
  postGitStatusShort = $postGitStatus
  commands = $commands
  qaServices = @{
    backendPort = $qaBackendPort
    frontendPort = $qaFrontendPort
    workspaceApiBase = $workspaceApiBase
    isolated = -not [bool]$SkipBrowserQA
  }
  browserQa = $browserQa
  gates = @{
    l2 = $l2Gate
    l3 = $l3Gate
  }
  artifacts = @{
    summary = $summaryPath
    json = $jsonPath
    browserQaJson = $browserQaJson
    browserQaMarkdown = (Join-Path $browserQaOutDir "qa-browser-check.md")
    taskCenterScreenshot = (Join-Path $browserQaOutDir "qa-task-center.png")
    executionConsoleScreenshot = (Join-Path $browserQaOutDir "qa-execution-console.png")
    qaConsole = (Join-Path $browserQaOutDir "qa-console.jsonl")
    qaNetwork = (Join-Path $browserQaOutDir "qa-network.json")
  }
}

$result | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $jsonPath -Encoding UTF8

$summaryLines = New-Object System.Collections.Generic.List[string]
$summaryLines.Add("# DXM Local Workbench Delivery Check")
$summaryLines.Add("")
$summaryLines.Add("- Checked at: $($result.checkedAt)")
$summaryLines.Add("- Local workbench check: $($result.localWorkbenchCheck)")
$summaryLines.Add("- Real DXM write readiness: $($result.realDxmWriteReadiness)")
$summaryLines.Add("- Source package readiness: $($result.sourcePackageReadiness)")
$summaryLines.Add("- Require clean worktree: $($result.requireCleanWorktree)")
$summaryLines.Add("- Source package check: $($result.sourcePackageCheck)")
$summaryLines.Add("- Deliverable mode: $($result.deliverableMode)")
$summaryLines.Add("- Real DXM writes: $($result.realDxmWrites)")
$summaryLines.Add("- Git HEAD: $($result.gitHead)")
if (!$SkipBrowserQA) {
  $summaryLines.Add("- Browser QA services: isolated backend $qaBackendPort / frontend $qaFrontendPort")
}
$summaryLines.Add("")
$summaryLines.Add("## Safety Gates")
if ($l2Gate) {
  $summaryLines.Add("- L2: $($l2Gate.status)")
  if ($l2Gate.status -ne "passed") {
    $summaryLines.Add("  - reason: real data_acquisition and draft_box readonly probes are not passed in the same valid gate window")
  }
} else {
  $summaryLines.Add("- L2: UNKNOWN - backend workspace snapshot was unavailable")
}
if ($l3Gate) {
  $summaryLines.Add("- L3: $($l3Gate.status)")
  if ($l3Gate.status -ne "passed") {
    $summaryLines.Add("  - reason: real DXM mutation remains blocked until L2 passes and L3 manual canary evidence is collected")
  }
} else {
  $summaryLines.Add("- L3: UNKNOWN - backend workspace snapshot was unavailable")
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
$summaryLines.Add("## Browser QA")
$summaryLines.Add("- Browser QA: $(if ($browserQa -and $browserQa.ok -eq $true) { "PASS" } elseif ($SkipBrowserQA) { "SKIPPED" } else { "FAIL/MISSING" })")
if ($browserQa -and $browserQa.assertions) {
  foreach ($property in $browserQa.assertions.PSObject.Properties) {
    $summaryLines.Add("- $(if ($property.Value) { "PASS" } else { "FAIL" }) $($property.Name)")
  }
}
$summaryLines.Add("")
$summaryLines.Add("## Artifacts")
$summaryLines.Add("- JSON: $jsonPath")
$summaryLines.Add("- Browser QA JSON: $($result.artifacts.browserQaJson)")
$summaryLines.Add("- Browser QA Markdown: $($result.artifacts.browserQaMarkdown)")
$summaryLines.Add("- Task screenshot: $($result.artifacts.taskCenterScreenshot)")
$summaryLines.Add("- Console screenshot: $($result.artifacts.executionConsoleScreenshot)")
$summaryLines.Add("- Console sidecar: $($result.artifacts.qaConsole)")
$summaryLines.Add("- Network sidecar: $($result.artifacts.qaNetwork)")
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
