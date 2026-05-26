$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$backendDir = Join-Path $root "app\backend"
$frontendDir = Join-Path $root "app\frontend"
$dataDir = Join-Path $root "data"
$launcherLog = Join-Path $dataDir "start-mvp.log"
$backendLog = Join-Path $dataDir "backend.log"
$frontendLog = Join-Path $dataDir "frontend.log"
$npmInstallLog = Join-Path $dataDir "npm-install.log"
$backendRunner = Join-Path $dataDir "run-backend.cmd"
$frontendRunner = Join-Path $dataDir "run-frontend.cmd"
$backendPort = 8000
$frontendPort = 5173
$checkOnly = $args -contains "--check" -or $args -contains "/check"
$help = $args -contains "--help" -or $args -contains "/?"

function Write-Step {
  param([string]$Message)
  $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Message"
  Write-Host $line
  [System.IO.File]::AppendAllText($launcherLog, "$line`r`n", [System.Text.Encoding]::UTF8)
}

function Fail {
  param([string]$Message)
  Write-Step "Error: $Message"
  exit 1
}

function Get-PortOwnerText {
  param([int]$Port)
  $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  if (!$connections) {
    return "port $Port is available"
  }
  $owners = @()
  foreach ($connection in $connections) {
    $processName = "unknown"
    try {
      $processName = (Get-Process -Id $connection.OwningProcess -ErrorAction Stop).ProcessName
    } catch {
      $processName = "unknown"
    }
    $owners += "PID $($connection.OwningProcess) ($processName)"
  }
  return "port $Port is in use by " + (($owners | Select-Object -Unique) -join ", ")
}

if ($help) {
  Write-Host ""
  Write-Host "Usage:"
  Write-Host "  scripts\start-mvp.bat          Start backend and frontend, then open the page"
  Write-Host "  scripts\start-mvp.bat --check  Check the local environment only"
  Write-Host ""
  Write-Host "Logs:"
  Write-Host "  data\start-mvp.log"
  Write-Host "  data\backend.log"
  Write-Host "  data\frontend.log"
  Write-Host "  data\npm-install.log"
  Write-Host ""
  Write-Host "Stop:"
  Write-Host "  Close the DXM Backend Service and DXM Frontend Service CMD windows."
  exit 0
}

New-Item -ItemType Directory -Path $dataDir -Force | Out-Null

Write-Step "=============================================="
Write-Step "DXM Auto UI Kit MVP launcher"
Write-Step "Project root: $root"
Write-Step "Backend log: $backendLog"
Write-Step "Frontend log: $frontendLog"
Write-Step "Launcher log: $launcherLog"
Write-Step "=============================================="

if (!(Test-Path -LiteralPath $backendDir)) {
  Fail "backend directory does not exist: $backendDir"
}
Write-Step "Backend directory OK: $backendDir"

if (!(Test-Path -LiteralPath $frontendDir)) {
  Fail "frontend directory does not exist: $frontendDir"
}
Write-Step "Frontend directory OK: $frontendDir"

$venvPython = Join-Path $backendDir ".venv\Scripts\python.exe"
if (Test-Path -LiteralPath $venvPython) {
  $pythonExe = $venvPython
} else {
  $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
  if (!$pythonCmd) {
    Fail "Python 3.11+ was not found. Create app\backend\.venv or add python to PATH."
  }
  $pythonExe = $pythonCmd.Source
}
Write-Step "Python: $pythonExe"

if (!(Get-Command npm -ErrorAction SilentlyContinue)) {
  Fail "npm was not found. Install Node.js first."
}
Write-Step "npm OK"

if (!(Get-Command curl -ErrorAction SilentlyContinue)) {
  Fail "curl was not found. Enable Windows curl or install curl."
}
Write-Step "curl OK"

& $pythonExe -c "import fastapi, uvicorn" | Out-Null
if ($LASTEXITCODE -ne 0) {
  Fail "backend Python dependencies are missing. Run: `"$pythonExe`" -m pip install -e app\backend"
}
Write-Step "Backend Python dependencies OK"

$viteCmd = Join-Path $frontendDir "node_modules\.bin\vite.cmd"
if (!(Test-Path -LiteralPath $viteCmd)) {
  Write-Step "Frontend node_modules missing; running npm install"
  Push-Location $frontendDir
  try {
    npm install *> $npmInstallLog
    if ($LASTEXITCODE -ne 0) {
      Fail "npm install failed. Check $npmInstallLog"
    }
  } finally {
    Pop-Location
  }
}
Write-Step "Frontend dependencies OK"

$backendBusy = Get-NetTCPConnection -LocalPort $backendPort -State Listen -ErrorAction SilentlyContinue
$frontendBusy = Get-NetTCPConnection -LocalPort $frontendPort -State Listen -ErrorAction SilentlyContinue

if ($checkOnly) {
  if ($backendBusy) {
    Write-Step "Check warning: backend $(Get-PortOwnerText -Port $backendPort). Launch may fail unless this is the intended DXM backend."
  } else {
    Write-Step "Backend port $backendPort is available"
  }
  if ($frontendBusy) {
    Write-Step "Check warning: frontend $(Get-PortOwnerText -Port $frontendPort). Launch may fail unless this is the intended DXM frontend."
  } else {
    Write-Step "Frontend port $frontendPort is available"
  }
  Write-Step "Check mode completed. Environment is ready; services were not started."
  Write-Step "Done"
  exit 0
}

if ($backendBusy) {
  Fail "backend $(Get-PortOwnerText -Port $backendPort). Close the old DXM Backend Service window or stop that process before launching."
}

if ($frontendBusy) {
  Fail "frontend $(Get-PortOwnerText -Port $frontendPort). Close the old DXM Frontend Service window or stop that process before launching."
}

Write-Step "Writing service runner scripts"
Set-Content -LiteralPath $backendLog -Encoding UTF8 -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Backend log started"
Set-Content -LiteralPath $frontendLog -Encoding UTF8 -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Frontend log started"

@"
@echo off
title DXM Backend Service
cd /d "$backendDir"
set DXM_LOGIN_HEADED=1
echo Backend service is running. Close this window to stop it.
echo Log file: $backendLog
echo [%date% %time%] Starting backend on http://127.0.0.1:$backendPort >> "$backendLog"
"$pythonExe" -m uvicorn src.main:app --host 127.0.0.1 --port $backendPort >> "$backendLog" 2>&1
echo [%date% %time%] Backend exited with code %errorlevel% >> "$backendLog"
echo Backend stopped. You can close this window.
"@ | Set-Content -LiteralPath $backendRunner -Encoding ASCII

@"
@echo off
title DXM Frontend Service
cd /d "$frontendDir"
echo Frontend service is running. Close this window to stop it.
echo Log file: $frontendLog
echo [%date% %time%] Starting frontend on http://127.0.0.1:$frontendPort >> "$frontendLog"
call "$viteCmd" --host 127.0.0.1 --port $frontendPort >> "$frontendLog" 2>&1
echo [%date% %time%] Frontend exited with code %errorlevel% >> "$frontendLog"
echo Frontend stopped. You can close this window.
"@ | Set-Content -LiteralPath $frontendRunner -Encoding ASCII

Write-Step "Opening backend service window"
Start-Process -FilePath "cmd.exe" -ArgumentList "/k `"$backendRunner`""

Write-Step "Opening frontend service window"
Start-Process -FilePath "cmd.exe" -ArgumentList "/k `"$frontendRunner`""

Write-Step "Waiting for services"
Start-Sleep -Seconds 8

$serviceWarnings = @()
try {
  Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$backendPort/health" -TimeoutSec 2 | Out-Null
  Write-Step "Backend OK: http://127.0.0.1:$backendPort/health"
} catch {
  $serviceWarnings += "backend did not respond yet. Check $backendLog"
  Write-Step "Warning: $($serviceWarnings[-1])"
}

try {
  Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$frontendPort" -TimeoutSec 2 | Out-Null
  Write-Step "Frontend OK: http://127.0.0.1:$frontendPort"
} catch {
  $serviceWarnings += "frontend did not respond yet. Check $frontendLog"
  Write-Step "Warning: $($serviceWarnings[-1])"
}

Write-Step "Stop services by closing the DXM Backend Service and DXM Frontend Service windows."
if ($serviceWarnings.Count -gt 0) {
  Write-Step "STARTED_WITH_WARNINGS: page was not opened automatically. $($serviceWarnings -join '; ')"
  Write-Step "Open the page manually after both health checks pass: http://127.0.0.1:$frontendPort"
} else {
  Write-Step "Opening frontend page: http://127.0.0.1:$frontendPort"
  Start-Process "http://127.0.0.1:$frontendPort"
  Write-Step "STARTED_OK"
}
