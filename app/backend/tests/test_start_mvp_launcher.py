from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
START_MVP_SCRIPT = REPO_ROOT / "scripts" / "start-mvp.ps1"


def test_start_mvp_does_not_open_frontend_page_when_service_health_has_warnings():
    script = START_MVP_SCRIPT.read_text(encoding="utf-8")

    assert "STARTED_WITH_WARNINGS: page was not opened" in script
    assert "Open the page manually after both health checks pass" in script
    assert "if ($serviceWarnings.Count -gt 0)" in script
    assert "Start-Process \"http://127.0.0.1:$frontendPort\"" in script

    warning_branch = script.index("if ($serviceWarnings.Count -gt 0)")
    success_branch = script.index("} else {", warning_branch)
    open_page = script.index("Start-Process \"http://127.0.0.1:$frontendPort\"")
    warning_branch_text = script[warning_branch:success_branch]
    success_branch_text = script[success_branch:]

    assert warning_branch < open_page
    assert "Start-Process \"http://127.0.0.1:$frontendPort\"" not in warning_branch_text
    assert "Start-Process \"http://127.0.0.1:$frontendPort\"" in success_branch_text


def test_start_mvp_uses_single_launcher_window_with_child_process_logs_and_cleanup():
    script = START_MVP_SCRIPT.read_text(encoding="utf-8")

    assert "cmd.exe" not in script
    assert "DXM Backend Service" not in script
    assert "DXM Frontend Service" not in script
    assert "Stop-ProcessTree" in script
    assert "CreateKillOnCloseJob" in script
    assert "JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE" in script
    assert "[DxmJobObject]::Assign" in script
    assert "backend-start.gate" in script
    assert "frontend-start.gate" in script
    assert 'while (!(Test-Path -LiteralPath `$gatePath))' in script
    assert "Set-Content -LiteralPath $GatePath" in script
    assert "-WindowStyle Hidden" in script
    assert "-NoNewWindow" not in script
    assert "-PassThru" in script
    assert "-RedirectStandardOutput" in script
    assert "wrapper failed" in script
    assert "Close this launcher window" in script or "Ctrl+C" in script


def test_start_mvp_streams_child_logs_back_to_single_launcher_console():
    script = START_MVP_SCRIPT.read_text(encoding="utf-8")

    assert "function Initialize-LogTailCursor" in script
    assert "function Read-NewRuntimeLogLines" in script
    assert "function Write-ServiceLogUpdates" in script
    assert "Streaming backend/frontend logs into this launcher window" in script
    assert "Write-ServiceLogUpdates" in script[script.index("while ($true)"):]
    assert "[backend]" in script
    assert "[frontend]" in script
    assert "$logTailCursors" in script
    assert '$logTailCursors["backend"] = Initialize-LogTailCursor -Path $backendLog' in script
    assert '$logTailCursors["frontend"] = Initialize-LogTailCursor -Path $frontendLog' in script
    assert '$logTailCursors[$Service.Name] = Initialize-LogTailCursor -Path $Service.Log' in script


def test_start_mvp_check_mode_does_not_install_frontend_dependencies():
    script = START_MVP_SCRIPT.read_text(encoding="utf-8")

    missing_vite_branch = script[script.index('if (!(Test-Path -LiteralPath $viteCmd))'):]
    check_only_guard = missing_vite_branch.index('if ($checkOnly)')
    npm_install = missing_vite_branch.index('npm install')

    assert check_only_guard < npm_install
    assert 'frontend node_modules are missing' in missing_vite_branch[:npm_install]


def test_start_mvp_auto_selects_free_frontend_port_when_5173_is_busy():
    script = START_MVP_SCRIPT.read_text(encoding="utf-8")

    assert "function Find-FreePort" in script
    assert "$frontendPort = Find-FreePort -PreferredPort $frontendPort" in script
    assert "Frontend port 5173 is busy; using port $frontendPort instead" in script
    assert 'Fail "frontend $(Get-PortOwnerText -Port $frontendPort)' not in script


def test_start_mvp_processes_runtime_restart_commands_from_ui():
    script = START_MVP_SCRIPT.read_text(encoding="utf-8")

    assert "$runtimeControlCommand = Join-Path $dataDir \"runtime-control-command.json\"" in script
    assert "DXM_RUNTIME_CONTROL_COMMAND_FILE" in script
    assert "function Read-RuntimeControlCommand" in script
    assert "function Restart-ManagedService" in script
    assert "Runtime control: restarting" in script
    assert "restart_backend" in script
    assert "restart_frontend" in script
    assert "Read-RuntimeControlCommand" in script[script.index("while ($true)"):]


def test_start_mvp_clears_stale_runtime_control_command_before_managed_startup():
    script = START_MVP_SCRIPT.read_text(encoding="utf-8")

    assert "Runtime control: cleared stale command file before managed startup" in script

    check_exit = script.index('Write-Step "Check mode completed. Environment is ready; services were not started."')
    stale_clear = script.index("Runtime control: cleared stale command file before managed startup")
    backend_start = script.index('$backendStart = Start-ManagedProcess')
    runtime_loop = script.index("while ($true)")

    assert check_exit < stale_clear < backend_start < runtime_loop
    assert "Remove-Item -LiteralPath $runtimeControlCommand" in script[stale_clear - 160:stale_clear + 160]


def test_start_mvp_monitors_service_health_when_wrapper_process_exits():
    script = START_MVP_SCRIPT.read_text(encoding="utf-8")

    assert "function Test-ManagedServiceHealthy" in script
    assert 'if ($Service.Name -eq "backend") { "/health" } else { "" }' in script
    assert 'Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$($Service.Port)$path"' in script
    assert "if ($Service.Process.HasExited -and !(Test-ManagedServiceHealthy -Service $Service))" in script
    assert "if ($service.Process.HasExited -and !(Test-ManagedServiceHealthy -Service $service))" in script
    assert "if ($service.Process.HasExited) {" not in script[script.index("while ($true)"):]


def test_start_mvp_replaces_previous_managed_backend_without_killing_unknown_processes():
    script = START_MVP_SCRIPT.read_text(encoding="utf-8")

    assert "function Test-IsManagedDxmBackendProcess" in script
    assert "function Stop-ManagedBackendPortOwners" in script
    assert "function Stop-ProcessTree" in script
    assert "Backend port $backendPort is busy; checking whether it is an older DXM backend" in script
    assert "Previous DXM backend stopped; launching current backend code" in script
    assert "Backend port $Port is occupied by unmanaged process(es)" in script
    assert "uvicorn" in script
    assert "src.main:app" in script
    assert "--port $backendPort" in script

    stop_tree = script.index("function Stop-ProcessTree")
    stop_managed = script.index("function Stop-ManagedBackendPortOwners")
    busy_branch = script.index('if ($backendBusy)')
    assert stop_tree < stop_managed < busy_branch
    assert "Fail \"backend $(Get-PortOwnerText -Port $backendPort)" in script[busy_branch:]
