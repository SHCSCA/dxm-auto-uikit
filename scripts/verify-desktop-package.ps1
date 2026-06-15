param(
  [int]$WaitSeconds = 25,
  [switch]$CheckPortable,
  [int]$PortableMinTempFreeMB = 1024,
  [string]$CapturePath = "",
  [string]$PortableCapturePath = "",
  [string]$CredentialSmokePath = "",
  [string]$SmokeUserDataDir = "",
  [string]$PortableSmokeUserDataDir = ""
)

$ErrorActionPreference = 'Stop'
trap {
  [Console]::Error.WriteLine([string]$_)
  exit 1
}
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')

function Resolve-SmokeArtifactPath {
  param(
    [string]$Path
  )

  $FullPath = [System.IO.Path]::GetFullPath($Path)
  $Parent = Split-Path -Parent $FullPath
  if ($Parent -and !(Test-Path -LiteralPath $Parent)) {
    New-Item -ItemType Directory -Force -Path $Parent | Out-Null
  }
  return $FullPath
}

$ExePath = Join-Path $RepoRoot 'outputs\desktop-build\win-unpacked\DXM-Agent-Console.exe'
$PortableExePath = Join-Path $RepoRoot 'outputs\desktop-build\DXM-Agent-Console-Portable-0.1.0.exe'
if ([string]::IsNullOrWhiteSpace($PortableCapturePath)) {
  $PortableCapturePath = Join-Path $env:TEMP 'dxm-agent-console-portable-smoke.png'
}
if ([string]::IsNullOrWhiteSpace($CapturePath)) {
  $CapturePath = Join-Path $env:TEMP 'dxm-agent-console-packaged-smoke.png'
}
if ([string]::IsNullOrWhiteSpace($CredentialSmokePath)) {
  $CredentialSmokePath = Join-Path $env:TEMP 'dxm-agent-console-credential-smoke.json'
}
if ([string]::IsNullOrWhiteSpace($SmokeUserDataDir)) {
  $SmokeUserDataDir = Join-Path $env:TEMP 'dxm-agent-console-packaged-smoke-user-data'
}
if ([string]::IsNullOrWhiteSpace($PortableSmokeUserDataDir)) {
  $PortableSmokeUserDataDir = Join-Path $env:TEMP 'dxm-agent-console-portable-smoke-user-data'
}
if ($CheckPortable -and $WaitSeconds -lt 180) {
  Write-Host "Portable smoke requires a longer first-launch wait; raising WaitSeconds from $WaitSeconds to 180."
  $WaitSeconds = 180
}
$CapturePath = Resolve-SmokeArtifactPath -Path $CapturePath
$PortableCapturePath = Resolve-SmokeArtifactPath -Path $PortableCapturePath
$CredentialSmokePath = Resolve-SmokeArtifactPath -Path $CredentialSmokePath
$SmokeUserDataDir = [System.IO.Path]::GetFullPath($SmokeUserDataDir)
$PortableSmokeUserDataDir = [System.IO.Path]::GetFullPath($PortableSmokeUserDataDir)

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

if (Test-Path $SmokeUserDataDir) {
  Remove-Item -LiteralPath $SmokeUserDataDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $SmokeUserDataDir | Out-Null
if (Test-Path $PortableSmokeUserDataDir) {
  Remove-Item -LiteralPath $PortableSmokeUserDataDir -Recurse -Force
}

if (Test-Path $CapturePath) {
  Remove-Item -LiteralPath $CapturePath -Force
}
if (Test-Path $PortableCapturePath) {
  Remove-Item -LiteralPath $PortableCapturePath -Force
}
if (Test-Path $CredentialSmokePath) {
  Remove-Item -LiteralPath $CredentialSmokePath -Force
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

function Get-PathFreeBytes {
  param(
    [string]$Path
  )
  $FullPath = [System.IO.Path]::GetFullPath($Path)
  $Root = [System.IO.Path]::GetPathRoot($FullPath)
  $Drive = Get-PSDrive -Name ($Root.Substring(0, 1))
  return [int64]$Drive.Free
}

function Assert-PortableTempSpace {
  param(
    [int]$RequiredMB
  )
  $FreeBytes = Get-PathFreeBytes -Path $env:TEMP
  $FreeMB = [math]::Floor($FreeBytes / 1MB)
  if ($FreeMB -lt $RequiredMB) {
    throw "Portable smoke requires at least ${RequiredMB}MB free on TEMP drive. Current TEMP=$env:TEMP, free=${FreeMB}MB. Clean old %TEMP%\\ns*.tmp portable extraction folders or use the verified directory免安装版."
  }
  Write-Host "Portable TEMP space OK: $FreeMB MB free at $env:TEMP"
}

function Get-DesktopSmokeLog {
  param(
    [string]$UserDataDir = $SmokeUserDataDir
  )
  $LogCandidates = @(
    (Join-Path $UserDataDir 'data\desktop-main.log'),
    (Join-Path $UserDataDir 'legacy-data\desktop-main.log')
  )
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

function Assert-CredentialSmoke {
  param(
    [string]$Path
  )
  if (!(Test-Path -LiteralPath $Path)) {
    throw "Credential smoke result was not created: $Path"
  }
  $Result = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($Result.ok -ne $true) {
    throw "Credential smoke failed: $($Result.error)"
  }
  if ($Result.available -ne $true -or $Result.saved -ne $true -or $Result.loaded -ne $true -or $Result.cleared -ne $true -or $Result.restored -ne $true) {
    throw "Credential smoke did not prove save/load/clear/restore: $($Result | ConvertTo-Json -Compress)"
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
    if ([int]$Status.backend.port -ne $Port) {
      throw "Packaged runtime backend port mismatch. Expected $Port, got $($Status.backend.port)"
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

$Process = Start-Process -FilePath $ExePath -WorkingDirectory (Split-Path $ExePath) -ArgumentList @("--qa-capture=$CapturePath", "--qa-credential-smoke=$CredentialSmokePath", "--qa-user-data-dir=$SmokeUserDataDir") -PassThru
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
Assert-CredentialSmoke -Path $CredentialSmokePath

$ExistingLog = Get-DesktopSmokeLog -UserDataDir $SmokeUserDataDir
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
Write-Host "Credential smoke passed. Result: $CredentialSmokePath"

if ($CheckPortable -and (Test-Path $PortableExePath)) {
  Write-Host "Portable exe: $PortableExePath"
  Assert-PortableTempSpace -RequiredMB $PortableMinTempFreeMB
  $PortableProcess = Start-Process -FilePath $PortableExePath -ArgumentList @("--qa-capture=$PortableCapturePath", "--qa-user-data-dir=$PortableSmokeUserDataDir") -WindowStyle Hidden -PassThru
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
  $PortableLog = Get-DesktopSmokeLog -UserDataDir $PortableSmokeUserDataDir
  Assert-DesktopSmokeLog -ExistingLog $PortableLog -ExpectedPythonRoot $null -Label 'Portable smoke'
  Write-Host "Portable smoke passed. QA capture: $PortableCapturePath"
  Write-Host "Portable smoke log: $PortableLog"
} elseif ($CheckPortable) {
  throw "Portable exe not found: $PortableExePath"
} else {
  Write-Host "Portable smoke skipped. Current delivery target is the verified directory免安装版: outputs\desktop-build\win-unpacked\DXM-Agent-Console.exe"
}
