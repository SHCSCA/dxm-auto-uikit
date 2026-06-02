$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$backendDir = Join-Path $root "app\backend"
$frontendDir = Join-Path $root "app\frontend"
$dataDir = Join-Path $root "data"
$launcherLog = Join-Path $dataDir "start-mvp.log"
$backendLog = Join-Path $dataDir "backend.log"
$frontendLog = Join-Path $dataDir "frontend.log"
$npmInstallLog = Join-Path $dataDir "npm-install.log"
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

function Find-FreePort {
  param(
    [int]$PreferredPort,
    [int]$MaxAttempts = 50
  )

  for ($offset = 0; $offset -lt $MaxAttempts; $offset += 1) {
    $candidate = $PreferredPort + $offset
    $busy = Get-NetTCPConnection -LocalPort $candidate -State Listen -ErrorAction SilentlyContinue
    if (!$busy) {
      return $candidate
    }
  }

  Fail "no available frontend port found near $PreferredPort. Log: $launcherLog"
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
  Write-Host "  Close this launcher window or press Ctrl+C."
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
  if ($checkOnly) {
    Fail "frontend node_modules are missing. Run npm install in app\frontend or launch without --check to install dependencies."
  }
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
$preferredFrontendPort = $frontendPort
$frontendBusy = Get-NetTCPConnection -LocalPort $frontendPort -State Listen -ErrorAction SilentlyContinue
$frontendPort = Find-FreePort -PreferredPort $frontendPort

if ($checkOnly) {
  if ($backendBusy) {
    Write-Step "Check warning: backend $(Get-PortOwnerText -Port $backendPort). Launch may fail unless this is the intended DXM backend."
  } else {
    Write-Step "Backend port $backendPort is available"
  }
  if ($frontendBusy) {
    Write-Step "Check warning: frontend $(Get-PortOwnerText -Port $preferredFrontendPort). Launch will use port $frontendPort instead."
  } else {
    Write-Step "Frontend port $frontendPort is available"
  }
  Write-Step "Check mode completed. Environment is ready; services were not started."
  Write-Step "Done"
  exit 0
}

if ($backendBusy) {
  Fail "backend $(Get-PortOwnerText -Port $backendPort). Stop that process before launching. Log: $launcherLog"
}

if ($frontendBusy) {
  Write-Step "Frontend port 5173 is busy; using port $frontendPort instead. $(Get-PortOwnerText -Port $preferredFrontendPort)"
}

function ConvertTo-SingleQuotedPowerShellLiteral {
  param([string]$Value)
  return "'" + $Value.Replace("'", "''") + "'"
}

function New-EncodedPowerShellCommand {
  param([string]$Command)
  return [Convert]::ToBase64String([System.Text.Encoding]::Unicode.GetBytes($Command))
}

function New-ManagedProcessCommand {
  param(
    [string]$WorkingDirectory,
    [string]$FilePath,
    [string]$Arguments,
    [string]$StartMessage,
    [string]$ExitName,
    [hashtable]$Environment,
    [string]$GatePath
  )
  $environmentLines = @()
  foreach ($key in $Environment.Keys) {
    $environmentLines += "`$startInfo.EnvironmentVariables[$(ConvertTo-SingleQuotedPowerShellLiteral -Value $key)] = $(ConvertTo-SingleQuotedPowerShellLiteral -Value $Environment[$key])"
  }
  $environmentBlock = $environmentLines -join "`r`n"
  return @"
`$ErrorActionPreference = 'Stop'
try {
  Write-Output "[`$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $StartMessage"
  `$gatePath = $(ConvertTo-SingleQuotedPowerShellLiteral -Value $GatePath)
  while (!(Test-Path -LiteralPath `$gatePath)) {
    Start-Sleep -Milliseconds 50
  }
  Remove-Item -LiteralPath `$gatePath -Force -ErrorAction SilentlyContinue
  `$startInfo = New-Object System.Diagnostics.ProcessStartInfo
  `$startInfo.FileName = $(ConvertTo-SingleQuotedPowerShellLiteral -Value $FilePath)
  `$startInfo.Arguments = $(ConvertTo-SingleQuotedPowerShellLiteral -Value $Arguments)
  `$startInfo.WorkingDirectory = $(ConvertTo-SingleQuotedPowerShellLiteral -Value $WorkingDirectory)
  `$startInfo.UseShellExecute = `$false
  `$startInfo.RedirectStandardOutput = `$true
  `$startInfo.RedirectStandardError = `$true
  `$startInfo.CreateNoWindow = `$true
$environmentBlock
  `$process = New-Object System.Diagnostics.Process
  `$process.StartInfo = `$startInfo
  `$process.add_OutputDataReceived({
    param(`$sender, `$eventArgs)
    if (`$eventArgs.Data -ne `$null) {
      [Console]::Out.WriteLine(`$eventArgs.Data)
    }
  })
  `$process.add_ErrorDataReceived({
    param(`$sender, `$eventArgs)
    if (`$eventArgs.Data -ne `$null) {
      [Console]::Out.WriteLine(`$eventArgs.Data)
    }
  })
  [void]`$process.Start()
  `$process.BeginOutputReadLine()
  `$process.BeginErrorReadLine()
  `$process.WaitForExit()
  `$process.WaitForExit()
  Write-Output "[`$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $ExitName exited with code `$(`$process.ExitCode)"
  exit `$process.ExitCode
} catch {
  Write-Output "[`$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $ExitName wrapper failed: `$(`$_.Exception.Message)"
  exit 1
}
"@
}

Add-Type -TypeDefinition @"
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;

public static class DxmJobObject {
    private const int JobObjectExtendedLimitInformation = 9;
    private const uint JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000;

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr CreateJobObject(IntPtr lpJobAttributes, string lpName);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool SetInformationJobObject(IntPtr hJob, int infoType, IntPtr lpJobObjectInfo, uint cbJobObjectInfoLength);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool AssignProcessToJobObject(IntPtr hJob, IntPtr hProcess);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool CloseHandle(IntPtr hObject);

    [StructLayout(LayoutKind.Sequential)]
    private struct JOBOBJECT_BASIC_LIMIT_INFORMATION {
        public long PerProcessUserTimeLimit;
        public long PerJobUserTimeLimit;
        public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize;
        public UIntPtr MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public IntPtr Affinity;
        public uint PriorityClass;
        public uint SchedulingClass;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct IO_COUNTERS {
        public ulong ReadOperationCount;
        public ulong WriteOperationCount;
        public ulong OtherOperationCount;
        public ulong ReadTransferCount;
        public ulong WriteTransferCount;
        public ulong OtherTransferCount;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION {
        public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
        public IO_COUNTERS IoInfo;
        public UIntPtr ProcessMemoryLimit;
        public UIntPtr JobMemoryLimit;
        public UIntPtr PeakProcessMemoryUsed;
        public UIntPtr PeakJobMemoryUsed;
    }

    public static IntPtr CreateKillOnCloseJob(string name) {
        IntPtr job = CreateJobObject(IntPtr.Zero, name);
        if (job == IntPtr.Zero) {
            throw new Win32Exception(Marshal.GetLastWin32Error());
        }

        JOBOBJECT_EXTENDED_LIMIT_INFORMATION info = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        int length = Marshal.SizeOf(typeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION));
        IntPtr pointer = Marshal.AllocHGlobal(length);
        try {
            Marshal.StructureToPtr(info, pointer, false);
            if (!SetInformationJobObject(job, JobObjectExtendedLimitInformation, pointer, (uint)length)) {
                throw new Win32Exception(Marshal.GetLastWin32Error());
            }
            return job;
        } catch {
            CloseHandle(job);
            throw;
        } finally {
            Marshal.FreeHGlobal(pointer);
        }
    }

    public static void Assign(IntPtr job, IntPtr process) {
        if (!AssignProcessToJobObject(job, process)) {
            throw new Win32Exception(Marshal.GetLastWin32Error());
        }
    }

    public static void Close(IntPtr job) {
        if (job != IntPtr.Zero) {
            CloseHandle(job);
        }
    }
}
"@

function Start-ManagedProcess {
  param(
    [string]$Name,
    [string]$Command,
    [string]$LogPath,
    [string]$GatePath
  )
  Remove-Item -LiteralPath $GatePath -Force -ErrorAction SilentlyContinue
  $encodedCommand = New-EncodedPowerShellCommand -Command $Command
  Write-Step "Starting $Name; log: $LogPath"
  $process = Start-Process -FilePath "powershell.exe" -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", $encodedCommand -NoNewWindow -PassThru -RedirectStandardOutput $LogPath
  $jobHandle = [DxmJobObject]::CreateKillOnCloseJob("dxm-auto-uikit-$Name-$($PID)-$($process.Id)")
  try {
    [DxmJobObject]::Assign($jobHandle, $process.Handle)
    Set-Content -LiteralPath $GatePath -Encoding ASCII -Value "go"
  } catch {
    Stop-ProcessTree -RootProcessId $process.Id
    [DxmJobObject]::Close($jobHandle)
    throw
  }
  return [pscustomobject]@{
    Process = $process
    JobHandle = $jobHandle
  }
}

function Stop-ProcessTree {
  param([int]$RootProcessId)
  $children = Get-CimInstance Win32_Process -Filter "ParentProcessId = $RootProcessId" -ErrorAction SilentlyContinue
  foreach ($child in $children) {
    Stop-ProcessTree -RootProcessId $child.ProcessId
  }
  Stop-Process -Id $RootProcessId -Force -ErrorAction SilentlyContinue
}

function Stop-ManagedServices {
  foreach ($service in $managedServices) {
    if ($service.Process -and !$service.Process.HasExited) {
      Write-Step "Stopping $($service.Name) process tree"
      Stop-ProcessTree -RootProcessId $service.Process.Id
    }
    if ($service.JobHandle) {
      [DxmJobObject]::Close($service.JobHandle)
      $service.JobHandle = [IntPtr]::Zero
    }
  }
}

$backendGate = Join-Path $dataDir "backend-start.gate"
$frontendGate = Join-Path $dataDir "frontend-start.gate"
$backendCommand = New-ManagedProcessCommand -WorkingDirectory $backendDir -FilePath $pythonExe -Arguments "-m uvicorn src.main:app --host 127.0.0.1 --port $backendPort" -StartMessage "Starting backend on http://127.0.0.1:$backendPort" -ExitName "Backend" -Environment @{ DXM_LOGIN_HEADED = "1"; DXM_BACKEND_PORT = "$backendPort"; DXM_BACKEND_URL = "http://127.0.0.1:$backendPort"; DXM_FRONTEND_PORT = "$frontendPort"; DXM_FRONTEND_URL = "http://127.0.0.1:$frontendPort" } -GatePath $backendGate
$frontendCommand = New-ManagedProcessCommand -WorkingDirectory $frontendDir -FilePath $viteCmd -Arguments "--host 127.0.0.1 --port $frontendPort" -StartMessage "Starting frontend on http://127.0.0.1:$frontendPort" -ExitName "Frontend" -Environment @{} -GatePath $frontendGate

$managedServices = @()

try {
  $backendStart = Start-ManagedProcess -Name "backend" -Command $backendCommand -LogPath $backendLog -GatePath $backendGate
  $managedServices += [pscustomobject]@{
    Name = "backend"
    Port = $backendPort
    Log = $backendLog
    Process = $backendStart.Process
    JobHandle = $backendStart.JobHandle
  }
  $frontendStart = Start-ManagedProcess -Name "frontend" -Command $frontendCommand -LogPath $frontendLog -GatePath $frontendGate
  $managedServices += [pscustomobject]@{
    Name = "frontend"
    Port = $frontendPort
    Log = $frontendLog
    Process = $frontendStart.Process
    JobHandle = $frontendStart.JobHandle
  }

  Write-Step "Waiting for services"
  Start-Sleep -Seconds 8

  foreach ($service in $managedServices) {
    if ($service.Process.HasExited) {
      Fail "$($service.Name) failed to start on port $($service.Port). Check $($service.Log)"
    }
  }

  $serviceWarnings = @()
  try {
    Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$backendPort/health" -TimeoutSec 2 | Out-Null
    Write-Step "Backend OK: http://127.0.0.1:$backendPort/health"
  } catch {
    $serviceWarnings += "backend failed health check on port $backendPort. Check $backendLog"
    Write-Step "Warning: $($serviceWarnings[-1])"
  }

  try {
    Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$frontendPort" -TimeoutSec 2 | Out-Null
    Write-Step "Frontend OK: http://127.0.0.1:$frontendPort"
  } catch {
    $serviceWarnings += "frontend failed health check on port $frontendPort. Check $frontendLog"
    Write-Step "Warning: $($serviceWarnings[-1])"
  }

  Write-Step "Close this launcher window or press Ctrl+C to stop services."
  if ($serviceWarnings.Count -gt 0) {
    Write-Step "STARTED_WITH_WARNINGS: page was not opened automatically. $($serviceWarnings -join '; ')"
    Write-Step "Open the page manually after both health checks pass: http://127.0.0.1:$frontendPort"
  } else {
    Write-Step "Opening frontend page: http://127.0.0.1:$frontendPort"
    Start-Process "http://127.0.0.1:$frontendPort"
    Write-Step "STARTED_OK"
  }

  while ($true) {
    foreach ($service in $managedServices) {
      if ($service.Process.HasExited) {
        Fail "$($service.Name) stopped on port $($service.Port). Check $($service.Log)"
      }
    }
    Start-Sleep -Seconds 1
  }
} finally {
  Stop-ManagedServices
}
