param(
  [int]$WaitSeconds = 25,
  [switch]$CheckPortable
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
$ExePath = Join-Path $RepoRoot 'outputs\desktop-build\win-unpacked\DXM-Agent-Console.exe'
$PortableExePath = Join-Path $RepoRoot 'outputs\desktop-build\DXM-Agent-Console-Portable-0.1.0.exe'
$LogPath = Join-Path $env:APPDATA 'DXM Agent Console\data\desktop-main.log'
$LegacyLogPath = Join-Path $env:APPDATA 'dxm-agent-desktop\data\desktop-main.log'
$CapturePath = Join-Path $env:TEMP 'dxm-agent-console-packaged-smoke.png'
$PortableCapturePath = Join-Path $env:TEMP 'dxm-agent-console-portable-smoke.png'

Write-Host 'DXM Agent Console packaged smoke'
Write-Host "Exe: $ExePath"

if (!(Test-Path $ExePath)) {
  throw "Packaged exe is missing: $ExePath"
}

$RequiredResources = @(
  'resources\app\backend\.venv\Scripts\python.exe',
  'resources\tools\probes\l2_readonly_probe_runner.py',
  'resources\tools\probes\l2_readonly_probe.py',
  'resources\config\l2_readonly_allowlist.json'
)
foreach ($RelativePath in $RequiredResources) {
  $ResourcePath = Join-Path (Split-Path $ExePath) $RelativePath
  if (!(Test-Path $ResourcePath)) {
    throw "Packaged resource is missing: $RelativePath"
  }
}

foreach ($Path in @($LogPath, $LegacyLogPath)) {
  if (Test-Path $Path) {
    Remove-Item -LiteralPath $Path -Force
  }
}

if (Test-Path $CapturePath) {
  Remove-Item -LiteralPath $CapturePath -Force
}
if (Test-Path $PortableCapturePath) {
  Remove-Item -LiteralPath $PortableCapturePath -Force
}

function Wait-ForFile {
  param(
    [string]$Path,
    [int]$TimeoutSeconds
  )
  $Deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  while ((Get-Date) -lt $Deadline) {
    if (Test-Path -LiteralPath $Path) {
      return $true
    }
    Start-Sleep -Milliseconds 500
  }
  return $false
}

function Get-DesktopSmokeLog {
  $LogCandidates = @($LogPath, $LegacyLogPath)
  $ExistingLog = $LogCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
  if (!$ExistingLog) {
    throw "desktop-main.log was not created. Checked: $($LogCandidates -join ', ')"
  }
  return $ExistingLog
}

function Assert-DesktopSmokeLog {
  param(
    [string]$ExistingLog,
    [string]$ExpectedPythonRoot,
    [string]$Label
  )
  $LogText = Get-Content -LiteralPath $ExistingLog -Raw -Encoding UTF8
  if ($LogText -notmatch 'Starting backend') {
    throw "$Label failed: desktop-main.log does not contain Starting backend. Log: $ExistingLog"
  }
  $BundledPythonRelative = 'resources\app\backend\.venv\Scripts\python.exe'
  if ($ExpectedPythonRoot) {
    $BundledPythonPath = Join-Path $ExpectedPythonRoot $BundledPythonRelative
    if ($LogText -notmatch [regex]::Escape($BundledPythonPath)) {
      throw "$Label backend did not start with bundled Python: $BundledPythonPath. Log: $ExistingLog"
    }
  } elseif ($LogText -notmatch [regex]::Escape($BundledPythonRelative)) {
    throw "$Label backend did not start with bundled Python resource path: $BundledPythonRelative. Log: $ExistingLog"
  }
  if ($LogText -notmatch 'Loaded frontend') {
    throw "$Label failed: desktop-main.log does not contain Loaded frontend. Log: $ExistingLog"
  }
}

function Assert-PackagedRuntimeClean {
  param(
    [string]$ExePath
  )
  $VenvPath = Join-Path (Split-Path $ExePath) 'resources\app\backend\.venv'
  $BytecodeFiles = @(Get-ChildItem -LiteralPath $VenvPath -Recurse -Force -Filter '*.pyc' -ErrorAction SilentlyContinue)
  $BytecodeDirs = @(Get-ChildItem -LiteralPath $VenvPath -Recurse -Force -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue)
  if ($BytecodeFiles.Count -gt 0 -or $BytecodeDirs.Count -gt 0) {
    throw "Packaged runtime generated Python bytecode cache. *.pyc=$($BytecodeFiles.Count), __pycache__=$($BytecodeDirs.Count). Runtime must keep the免安装版 directory clean."
  }
}

function Get-FreeLoopbackPort {
  $Listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Parse('127.0.0.1'), 0)
  try {
    $Listener.Start()
    return [int]$Listener.LocalEndpoint.Port
  } finally {
    $Listener.Stop()
  }
}

function Assert-PackagedRuntimeDependencyOk {
  param(
    [object]$Dependencies,
    [string]$Name,
    [string]$ResourceRoot
  )
  $Dependency = $Dependencies.$Name
  if (!$Dependency) {
    throw "Packaged runtime dependency is missing from /api/runtime/status: $Name"
  }
  if ($Dependency.status -ne 'ok') {
    $CheckedPaths = @($Dependency.checkedPaths) -join ', '
    throw "Packaged runtime dependency $Name is $($Dependency.status). Path: $($Dependency.path). Checked: $CheckedPaths"
  }
  if ([string]$Dependency.path -notlike "$ResourceRoot*") {
    throw "Packaged runtime dependency $Name did not resolve from resources. Path: $($Dependency.path). Resource root: $ResourceRoot"
  }
}

function Assert-PackagedBackendResourceStatus {
  param(
    [string]$ExePath,
    [int]$TimeoutSeconds
  )
  $ExeDir = Split-Path $ExePath
  $ResourceRoot = Join-Path $ExeDir 'resources'
  $PythonPath = Join-Path $ResourceRoot 'app\backend\.venv\Scripts\python.exe'
  $BackendDir = Join-Path $ResourceRoot 'app\backend'
  $RuntimeDataDir = Join-Path $env:TEMP "dxm-agent-console-runtime-check-$([guid]::NewGuid().ToString('N'))"
  New-Item -ItemType Directory -Force -Path $RuntimeDataDir | Out-Null
  $Port = Get-FreeLoopbackPort
  $ApiBase = "http://127.0.0.1:$Port"
  $Process = $null
  $Succeeded = $false

  try {
    $StartInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $StartInfo.FileName = $PythonPath
    $StartInfo.WorkingDirectory = $BackendDir
    $StartInfo.Arguments = "-m uvicorn src.main:app --host 127.0.0.1 --port $Port"
    $StartInfo.UseShellExecute = $false
    $StartInfo.CreateNoWindow = $true
    $StartInfo.EnvironmentVariables['DXM_DATA_DIR'] = $RuntimeDataDir
    $StartInfo.EnvironmentVariables['DXM_RESOURCE_ROOT'] = $ResourceRoot
    $StartInfo.EnvironmentVariables['DXM_DESKTOP'] = '1'
    $StartInfo.EnvironmentVariables['DXM_LAUNCHER_LOG_FILE'] = Join-Path $RuntimeDataDir 'desktop-main.log'
    $StartInfo.EnvironmentVariables['DXM_BACKEND_PORT'] = [string]$Port
    $StartInfo.EnvironmentVariables['DXM_BACKEND_URL'] = $ApiBase
    $StartInfo.EnvironmentVariables['PYTHONIOENCODING'] = 'utf-8'
    $StartInfo.EnvironmentVariables['PYTHONDONTWRITEBYTECODE'] = '1'

    $Process = [System.Diagnostics.Process]::new()
    $Process.StartInfo = $StartInfo
    if (!$Process.Start()) {
      throw 'Could not start packaged backend runtime check process'
    }

    $Deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $Status = $null
    while ((Get-Date) -lt $Deadline) {
      try {
        $Status = Invoke-RestMethod -UseBasicParsing -Uri "$ApiBase/api/runtime/status" -TimeoutSec 2
        break
      } catch {
        Start-Sleep -Milliseconds 500
      }
    }
    if (!$Status) {
      throw "Packaged runtime status check timed out: $ApiBase/api/runtime/status"
    }

    Assert-PackagedRuntimeDependencyOk -Dependencies $Status.dependencies -Name 'l2_readonly_probe_runner' -ResourceRoot $ResourceRoot
    Assert-PackagedRuntimeDependencyOk -Dependencies $Status.dependencies -Name 'l2_readonly_probe_script' -ResourceRoot $ResourceRoot
    Assert-PackagedRuntimeDependencyOk -Dependencies $Status.dependencies -Name 'l2_readonly_probe_allowlist' -ResourceRoot $ResourceRoot
    $Succeeded = $true
  } finally {
    if ($Process -and !$Process.HasExited) {
      try {
        $Process.Kill()
      } catch {}
    }
    if ($Succeeded -and (Test-Path $RuntimeDataDir)) {
      Remove-Item -LiteralPath $RuntimeDataDir -Recurse -Force
    }
  }
}

Assert-PackagedRuntimeClean -ExePath $ExePath
Assert-PackagedBackendResourceStatus -ExePath $ExePath -TimeoutSeconds $WaitSeconds
Write-Host 'Packaged backend resource status passed.'

$Process = Start-Process -FilePath $ExePath -WorkingDirectory (Split-Path $ExePath) -ArgumentList "--qa-capture=$CapturePath" -PassThru
if (!$Process.WaitForExit($WaitSeconds * 1000)) {
  try {
    Stop-Process -Id $Process.Id -Force
  } catch {}
  throw "Packaged smoke timed out after $WaitSeconds seconds"
}
if ($Process.ExitCode -ne 0) {
  throw "Packaged smoke failed: exit code $($Process.ExitCode)"
}
if (!(Test-Path $CapturePath)) {
  throw "Packaged smoke failed: QA capture was not created: $CapturePath"
}

$ExistingLog = Get-DesktopSmokeLog
Assert-DesktopSmokeLog -ExistingLog $ExistingLog -ExpectedPythonRoot (Split-Path $ExePath) -Label 'Packaged smoke'
Assert-PackagedRuntimeClean -ExePath $ExePath

try {
  if (!$Process.HasExited) {
    Stop-Process -Id $Process.Id -Force
  }
} catch {}

Get-Process | Where-Object { $_.Path -like '*desktop-build*DXM-Agent-Console.exe' } | ForEach-Object {
  try {
    taskkill /PID $_.Id /T /F | Out-Null
  } catch {}
}

Write-Host "Packaged smoke passed. Log: $ExistingLog"
Write-Host "QA capture: $CapturePath"

if ($CheckPortable -and (Test-Path $PortableExePath)) {
  Write-Host "Portable exe: $PortableExePath"
  $PortableProcess = Start-Process -FilePath $PortableExePath -ArgumentList "--qa-capture=$PortableCapturePath" -WindowStyle Hidden -PassThru
  if (!(Wait-ForFile -Path $PortableCapturePath -TimeoutSeconds $WaitSeconds)) {
    try {
      Stop-Process -Id $PortableProcess.Id -Force
    } catch {}
    throw "Portable QA capture was not created: $PortableCapturePath"
  }
  $PortableExited = $PortableProcess.WaitForExit(5000)
  if ($PortableExited -and $PortableProcess.ExitCode -ne 0) {
    throw "Portable smoke failed: exit code $($PortableProcess.ExitCode)"
  }
  if (!$PortableExited) {
    try {
      Stop-Process -Id $PortableProcess.Id -Force
    } catch {}
  }
  $PortableLog = Get-DesktopSmokeLog
  Assert-DesktopSmokeLog -ExistingLog $PortableLog -ExpectedPythonRoot $null -Label 'Portable smoke'
  Write-Host "Portable smoke passed. QA capture: $PortableCapturePath"
} elseif ($CheckPortable) {
  Write-Host "Portable exe not found, skipped: $PortableExePath"
} else {
  Write-Host "Portable smoke skipped. Current delivery target is the verified directory免安装版: outputs\desktop-build\win-unpacked\DXM-Agent-Console.exe"
}
