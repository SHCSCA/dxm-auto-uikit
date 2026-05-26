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
