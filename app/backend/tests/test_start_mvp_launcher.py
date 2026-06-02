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
    assert "-NoNewWindow" in script
    assert "-PassThru" in script
    assert "-RedirectStandardOutput" in script
    assert "wrapper failed" in script
    assert "Close this launcher window" in script or "Ctrl+C" in script


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
