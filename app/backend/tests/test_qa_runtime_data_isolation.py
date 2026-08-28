import os
import subprocess
import sys
from pathlib import Path


def _read_text_robust(path: Path) -> str:
    """Read text with UTF-8, falling back to GBK on decode error.
    The repo contains files with mixed encodings (ASCII/UTF-8 English + GBK Chinese).
    """
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="gbk")


REPO_ROOT = Path(__file__).resolve().parents[3]
FINAL_DELIVERY_CHECK = REPO_ROOT / "scripts" / "final-delivery-check.ps1"
FINAL_DELIVERY_STATE_CONTRACT = REPO_ROOT / "scripts" / "test-final-delivery-state-consistency-contract.ps1"
QA_BROWSER_CHECK = REPO_ROOT / "scripts" / "qa-browser-check.ps1"
VERIFY_DESKTOP_PACKAGE = REPO_ROOT / "scripts" / "verify-desktop-package.ps1"
WORKBENCH_MODULES = REPO_ROOT / "app" / "frontend" / "src" / "components" / "WorkbenchModules.tsx"
APP_SHELL = REPO_ROOT / "app" / "frontend" / "src" / "components" / "AppShell.tsx"
MVP_CONTRACT = REPO_ROOT / "docs" / "product" / "MVP-竖切-草稿箱批量只保存.md"


def test_backend_config_can_use_dxm_data_dir_override(tmp_path):
    env = os.environ.copy()
    env["DXM_DATA_DIR"] = str(tmp_path / "isolated-data")

    output = subprocess.check_output(
        [
            sys.executable,
            "-c",
            "from src.core.config import DATA_DIR, DB_PATH; print(DATA_DIR); print(DB_PATH)",
        ],
        cwd=REPO_ROOT / "app" / "backend",
        env=env,
        text=True,
    ).splitlines()

    assert Path(output[0]) == tmp_path / "isolated-data"
    assert Path(output[1]) == tmp_path / "isolated-data" / "sqlite" / "dxm_auto_uikit.db"


def test_final_delivery_state_consistency_contract_executes():
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(FINAL_DELIVERY_STATE_CONTRACT),
            "-SourceScript",
            str(FINAL_DELIVERY_CHECK),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "state consistency contract: 11/11 passed" in result.stdout


def test_final_delivery_check_runs_browser_qa_backend_with_isolated_data_dir():
    script = FINAL_DELIVERY_CHECK.read_text(encoding="utf-8")

    assert "$l1ReplayOutDir" in script
    assert "--output-dir\", $l1ReplayOutDir" in script
    assert "--output-dir\", \"data/l1_selector_replay\"" not in script
    assert "$qaRuntimeDataDir" in script
    assert "$pytestRuntimeDataDir" in script
    assert "DXM_DATA_DIR" in script
    assert "Start-BackgroundCommandWithEnvironment" in script
    backend_pytest_section = script[script.index('-Name "Backend pytest"') - 400:script.index('-Name "Frontend production build"')]
    assert "DXM_DATA_DIR" in backend_pytest_section
    assert '-TimeoutSeconds 600' in backend_pytest_section
    qa_backend_section = script[script.index('-Name "QA backend service"') - 400:script.index('Wait-HttpReady -Name "QA backend service"')]
    assert "DXM_DATA_DIR" in qa_backend_section
    assert "pytestRuntimeDataDir" in script
    assert "qaRuntimeDataDir" in script


def test_final_delivery_check_seeds_qa_runtime_from_authoritative_data_before_backend_start():
    script = FINAL_DELIVERY_CHECK.read_text(encoding="utf-8")

    assert "Seed-QARuntimeData" in script
    assert "$authoritativeDataDir = Join-Path $root \"data\"" in script
    assert "Copy-AuthoritativeDataItem" in script
    assert "sqlite" in script
    assert "l2_readonly_probe" in script
    assert "screenshots" in script
    assert "evidences" in script
    qa_startup_section = script[
        script.index("Remove-Item -LiteralPath $qaRuntimeDataDir"):
        script.index('-Name "QA backend service"')
    ]
    assert "Seed-QARuntimeData" in qa_startup_section
    assert "DXM_DATA_DIR = $qaRuntimeDataDir" not in qa_startup_section
    qa_backend_section = script[
        script.index('-Name "QA backend service"'):
        script.index('Wait-HttpReady -Name "QA backend service"')
    ]
    assert "DXM_DATA_DIR = $qaRuntimeDataDir" in qa_backend_section


def test_final_delivery_check_does_not_fallback_to_qa_workspace_snapshot():
    script = FINAL_DELIVERY_CHECK.read_text(encoding="utf-8")

    assert "Get-AuthoritativeWorkspaceSnapshot" in script
    assert "Get-WorkspaceSnapshot -ApiBase $workspaceApiBase" not in script


def test_final_delivery_check_reports_l2_probe_evidence_and_plan():
    script = FINAL_DELIVERY_CHECK.read_text(encoding="utf-8")

    assert "Test-CapturedPowerShellError" in script
    assert "FullyQualifiedErrorId" in script
    assert "WriteErrorException" in script
    assert "Command output contained a PowerShell error record" in script
    assert "Test-PackagedDesktopSmokeError" in script
    assert "Portable smoke requires at least" in script
    assert "Packaged desktop smoke output contained a smoke failure" in script
    assert "Invoke-JsonUtf8" in script
    assert "Invoke-RestMethod -Uri \"$workspaceApiBase/api/delivery/workspace\"" not in script
    assert "Get-JsonObjectPropertyCount $l2Gate.latest.realTargets" in script
    assert "Get-JsonObjectPropertyCount $l2Gate.latest.mockTargets" in script
    assert "l2ProbeEvidenceSummary" in script
    assert "l2AllowlistReviewCandidates" in script
    assert "l2AllowlistReviewTemplate" in script
    assert "l2AllowlistReviewTemplateHashes" in script
    assert "function Get-FileSha256" in script
    assert "Get-FileSha256 -Path $l2AllowlistReviewTemplateMarkdownPath" in script
    assert "markdown_sha256" in script
    assert "json_sha256" in script
    assert "l2ProbePlan" in script
    assert "okScope" in script
    assert "realDxmMutationAllowed" in script
    assert "$ExpectedRealDxmWriteReadiness = \"BLOCKED\"" in script
    assert "default BLOCKED" in script
    assert "$ExpectedRealDxmSingleSaveEndToEnd = \"pending_live_dxm_validation\"" in script
    assert "Get-SingleSaveAcceptanceReadiness" in script
    assert "singleSaveAcceptance" in script
    assert "singleSaveAcceptanceReadiness" in script
    assert "realDxmSingleSaveEndToEnd" in script
    assert "expectedRealDxmSingleSaveEndToEnd" in script
    assert "singleSaveAcceptanceMatchesExpected" in script
    assert "productionDeliveryReady" in script
    assert "Test-FinalDeliveryOverallOk" in script
    assert "-SingleSaveAcceptanceMatchesExpected $singleSaveAcceptanceMatchesExpected" in script
    assert "Real DXM single-save end-to-end" in script
    assert "realDxmWriteReadinessMatchesExpected" in script
    assert "productionRealWriteReady" in script
    assert "realDxmWriteBlockedReason" in script
    assert "l3EvidenceReadiness" in script
    assert "Get-L3EvidenceReadiness" in script
    assert "Convert-RealModeReleasePlanForFinalCheck" in script
    assert "realModeReleasePlan" in script
    assert "blockedModes" in script
    assert "missing_checklist" in script
    assert "## Real Mode Release Plan" in script
    assert "do not infer single_save, controlled_edit_batch, batch_save, unattended, or publish readiness" in script
    assert "twoStageAcceptance" not in script
    assert "save screenshot/path missing" in script
    assert "network/HAR save response missing" in script
    assert "READY note: real DXM READY currently means controlled single_save readiness only" in script
    assert "Expected real DXM write readiness" in script
    assert "local_workbench_only" in script
    assert "Real DXM mutation allowed" in script
    assert "## L2 Readonly Probe Evidence" in script
    assert "## L2 Allowlist Review Candidates" in script
    assert "## L2 Allowlist Review Template" in script
    assert "## L2 Recheck Plan" in script
    assert "write_request_count" in script
    assert "non_read_request_count" in script
    assert "blocked_request_count" in script
    assert "forbidden_keyword_request_count" in script
    assert "websocket_count" in script
    assert "json_path" in script
    assert "markdown_path" in script
    assert "screenshot_sha256" in script
    assert "dom_sha256" in script
    assert "review_only" in script
    assert "allowlist_applied" in script
    assert "manual review only; not an L2 pass" in script
    assert "reviewer" in script
    assert "decision" in script
    assert "rationale" in script
    assert "Markdown sha256" in script
    assert "JSON sha256" in script
    assert "l2-allowlist-review-template.md" in script
    assert "l2-allowlist-review-template.json" in script
    assert "Gate record readability" in script
    assert "DXM Semi-Managed Automation Workbench Delivery Check" in script
    assert "PASS only means L2/L3 records were readable; it is not an L2/L3 gate pass" in script
    assert "L2/L3 gate records available" not in script
    assert "Gate evidence check:" not in script


def test_desktop_portable_smoke_has_long_enough_timeout_budget():
    final_check = FINAL_DELIVERY_CHECK.read_text(encoding="utf-8")
    verify_script = VERIFY_DESKTOP_PACKAGE.read_text(encoding="utf-8")

    packaged_smoke_section = final_check[
        final_check.index('-Name "Packaged desktop smoke"'):
        final_check.index('-Name "L1 selector replay"')
    ]
    assert "-TimeoutSeconds 360" in packaged_smoke_section
    assert "$CheckPortable -and $WaitSeconds -lt 180" in verify_script
    assert "raising WaitSeconds from $WaitSeconds to 180" in verify_script


def test_mvp_contract_defines_batch_save_evidence_and_readiness_boundary():
    contract = _read_text_robust(MVP_CONTRACT)

    assert "真实可见浏览器" in contract
    assert "draft ≥" in contract
    assert "batch_draft_save" in contract
    assert "页面成功态" in contract
    assert "独立未发布证明" in contract
    assert "UNKNOWN" in contract
    assert "PublishGuard" in contract
    assert "MVP_READY ≠ PROD_READY" in contract
    assert "claim_only 非前置" in contract


def test_mvp_contract_has_current_manual_acceptance_checklist():
    contract = _read_text_robust(MVP_CONTRACT)

    assert "## 11." in contract
    assert "人工验收" in contract
    assert "零发布复核" in contract
    assert "MVP_READY" in contract


def test_readme_next_steps_focus_on_allowlist_l2_l3_reverification():
    readme = _read_text_robust(REPO_ROOT / "README.md")
    assert "MVP_READY" in readme or "BLOCKED" in readme
    assert "PROD_READY" in readme
    assert "MVP" not in readme or readme.count("# MVP") <= 0 or "MVP_READY" in readme


def test_readme_explains_final_check_ok_scope_for_machine_consumers():
    readme = _read_text_robust(REPO_ROOT / "README.md")
    assert "BLOCKED" in readme
    assert "0.3.0" in readme
    assert "PROGRESS.md" in readme or "BLOCKED.md" in readme


def test_final_delivery_check_writes_current_provisional_report_before_browser_qa():
    script = FINAL_DELIVERY_CHECK.read_text(encoding="utf-8")

    assert "Write-ProvisionalDeliveryCheckReport" in script
    assert "final_delivery_check_in_progress_for_browser_qa" in script
    assert "Browser QA reads /api/delivery/final-check" in script
    assert "Provisional report must be BLOCKED when gates are unavailable" in script
    qa_startup_section = script[
        script.index('Wait-HttpReady -Name "QA frontend preview"'):
        script.index('-Name "Browser workbench QA"')
    ]
    assert "Write-ProvisionalDeliveryCheckReport" in qa_startup_section


def test_browser_qa_disables_extensions_and_bounds_cdp_commands():
    script = QA_BROWSER_CHECK.read_text(encoding="utf-8")

    assert '"--disable-extensions"' in script
    assert "CDP command timed out: ' + method" in script
    assert "pending.delete(msgId)" in script


def test_browser_qa_reuses_real_single_save_without_fabricating_product_box_facts():
    script = QA_BROWSER_CHECK.read_text(encoding="utf-8")
    ensure_section = script[script.index("async function ensureRealMutationTask"):script.index("async function verifyUnreleasedRealModeCreateBlocked")]

    assert "task?.mode === 'single_save'" in ensure_section
    assert "return await ensureDryRunDemoTask()" in ensure_section
    assert "/api/acquisition/" not in ensure_section
    assert "/api/products" not in ensure_section
    assert "postJson('/api/tasks'" not in ensure_section
    assert "product_box_snapshot" not in ensure_section
    assert "QA local gated single_save one product fixture" not in script
    assert "QA guarded single-save product" not in script
    assert "source: 'qa'" not in ensure_section
    assert "claim_only" not in script
    assert "data_acquisition" not in script
    assert "待认领" not in script


def test_final_delivery_check_captures_final_report_center_after_final_json_write():
    script = FINAL_DELIVERY_CHECK.read_text(encoding="utf-8")
    qa_script = QA_BROWSER_CHECK.read_text(encoding="utf-8")
    workbench_modules = WORKBENCH_MODULES.read_text(encoding="utf-8")
    results_page = (REPO_ROOT / "app" / "frontend" / "src" / "components" / "workbench" / "ResultsPage.tsx").read_text(encoding="utf-8")
    app_shell = APP_SHELL.read_text(encoding="utf-8")
    frontend_css = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")

    assert "ReportOnlyFinal" in qa_script
    assert "AllowMissingPostFinalQa" in qa_script
    assert "function Resolve-Node" in script
    assert "$nodeExe = Resolve-Node" in script
    assert "function Read-QaJsonSummary" in script
    assert "const slim = {" in script
    assert "$browserQa = Read-QaJsonSummary -Path $browserQaJson" in script
    assert "$postFinalReportQa = Read-QaJsonSummary -Path $postFinalReportQaJson" in script
    assert "finalReportCenterShowsFinalPassState" in qa_script
    assert "finalReportCenterQaVisible" in qa_script
    assert "finalReportCenterQaDomState" in qa_script
    assert "finalReportCenterQaTextVisible" in qa_script
    final_report_assertions = qa_script[qa_script.index("assertions: {"):qa_script.index("finalReportApiIsFinal")]
    assert "finalReportCenterQaStateMatchesApi" in final_report_assertions
    assert "hasExpectedPostFinalReportQa" in qa_script
    assert "'最终报告中心 QA '" not in qa_script
    assert "\\u6700\\u7ec8\\u62a5\\u544a\\u4e0e\\u8bc1\\u636e QA" in qa_script
    assert "\\\\u7ef4\\\\u62a4\\\\u9a8c\\\\u6536\\\\u4fe1\\\\u606f" in qa_script
    assert "finalReportCenterScreenshotDomPath" in qa_script
    assert "expectedLockedEvidence" in qa_script
    assert "finalReportExpectedLockedEvidenceRows" in qa_script
    assert "finalReportLockedEvidenceRowsNotWarn" in qa_script
    assert "finalReportLockedEvidenceRowsNeutral" in qa_script
    assert "reportBusinessReportLocked" in qa_script
    assert "reportPostL3ChecklistLocked" in qa_script
    assert "reportLockedEvidenceRowsNeutral" in qa_script
    assert "reportRealWriteReleasePrerequisites" in qa_script
    assert "finalReportBusinessReportLocked" in qa_script
    assert "finalReportPostL3ChecklistLocked" in qa_script
    assert "finalReportNoL3PostEvidenceBlockerChips" in qa_script
    assert "guardDangerTexts" in qa_script
    assert "noL3PostEvidenceDangerChips" in qa_script
    assert "formatQaState" in qa_script
    assert "\\u5f85\\u5237\\u65b0/\\u672a\\u8fd0\\u884c" in qa_script
    assert "finalCheckSummary?.browser_qa_ok === true ? 'PASS' : 'FAIL'" not in qa_script
    assert "finalCheckSummary?.post_final_report_qa_ok === true ? 'PASS' : 'FAIL'" not in qa_script
    assert "保存结果 0 条（预期阻断）" not in qa_script
    assert 'clickSelector(\'[data-section="reports"]\')' in qa_script
    assert 'reportCenterSectionVisible' in qa_script
    assert "waitForBodyIncludes" in qa_script
    assert "post_final_report_qa_ok" in qa_script
    assert "final_report_center_screenshot_path" in qa_script
    assert "qa-report-center-final" in qa_script
    assert 'testId="final-report-center-qa"' in results_page
    assert "state={postFinalReportQaState}" in results_page
    assert "data-testid={testId}" in results_page
    assert "data-state={state}" in results_page
    assert ".l2-review-candidates" in frontend_css
    assert "overflow-wrap: anywhere" in frontend_css
    assert 'data-testid="final-report-center-screenshot-path"' in results_page
    assert 'data-testid="report-center-section"' in results_page
    assert ".replaceAll(" not in workbench_modules
    assert "data-section={item.id}" in app_shell
    assert "Final report state QA" in script
    assert "Final report center QA" in script
    assert "Remove-PostFinalReportQaArtifacts" in script
    assert "$postFinalReportStateQaCommand.ok" in script
    assert "$postFinalReportCenterQaCommand.ok" in script
    assert "postFinalReportQa" in script
    assert "finalReportCenterScreenshot" in script
    assert "function Write-Utf8NoBomFile" in script
    assert "New-Object System.Text.UTF8Encoding -ArgumentList $false" in script
    assert "function Write-JsonNoBomFile" in script
    assert "Set-Content -LiteralPath $jsonPath -Encoding UTF8" not in script
    assert "$result | ConvertTo-Json -Depth 12 | Set-Content" not in script
    final_json_write = script.index("Write-JsonNoBomFile -Path $jsonPath -Value $result")
    post_final_state_qa = script.index('-Name "Final report state QA"')
    post_final_qa = script.index('-Name "Final report center QA"')
    stop_qa = script.rindex("Stop-QAProcesses")
    assert final_json_write < post_final_state_qa < post_final_qa < stop_qa
    first_cleanup = script.index("Remove-PostFinalReportQaArtifacts", final_json_write)
    second_cleanup = script.index("Remove-PostFinalReportQaArtifacts", first_cleanup + 1)
    assert final_json_write < first_cleanup < post_final_state_qa
    assert post_final_state_qa < second_cleanup < post_final_qa
    second_cleanup_section = script[second_cleanup:post_final_qa]
    assert "$postFinalReportQa = $null" in second_cleanup_section
    state_section = script[post_final_state_qa:post_final_qa]
    center_section = script[post_final_qa:stop_qa]
    assert "$postFinalReportStateQaCommand.ok" in state_section
    assert "$postFinalReportCenterQaCommand.ok" in center_section


def test_final_delivery_check_includes_packaged_desktop_smoke_in_delivery_gate():
    script = FINAL_DELIVERY_CHECK.read_text(encoding="utf-8")
    smoke_script = (REPO_ROOT / "scripts" / "verify-desktop-package.ps1").read_text(encoding="utf-8")

    assert "[switch]$CheckPortableDesktop" in script
    assert "-CheckPortableDesktop" in script
    assert "[string]$CapturePath" in smoke_script
    assert "[string]$PortableCapturePath" in smoke_script
    assert "[string]$CredentialSmokePath" in smoke_script
    assert "[string]$VisibleSmokePath" in smoke_script
    assert "[string]$VisibleSmokeUserDataDir" in smoke_script
    assert "[string]$PortableSmokeUserDataDir" in smoke_script
    assert "[Console]::Error.WriteLine([string]$_)" in smoke_script
    assert "Resolve-SmokeArtifactPath" in smoke_script
    assert "$CapturePath = Resolve-SmokeArtifactPath -Path $CapturePath" in smoke_script
    assert "$PortableCapturePath = Resolve-SmokeArtifactPath -Path $PortableCapturePath" in smoke_script
    assert "$CredentialSmokePath = Resolve-SmokeArtifactPath -Path $CredentialSmokePath" in smoke_script
    assert "$VisibleSmokePath = Resolve-SmokeArtifactPath -Path $VisibleSmokePath" in smoke_script
    assert 'Get-DesktopSmokeLog -UserDataDir $PortableSmokeUserDataDir' in smoke_script
    assert '"--qa-visible-smoke=$VisibleSmokePath"' in smoke_script
    assert 'Assert-VisibleSmoke -Path $VisibleSmokePath' in smoke_script
    assert '"--qa-user-data-dir=$PortableSmokeUserDataDir"' in smoke_script
    assert "$packagedDesktopSmokeArgs" in script
    assert '$packagedDesktopSmokeArgs += "-CheckPortable"' in script
    assert "$packagedDesktopSmokeCapturePath" in script
    assert "$packagedDesktopSmokeUserDataDir" in script
    assert "$portableDesktopSmokeCapturePath" in script
    assert "$portableDesktopSmokeUserDataDir" in script
    assert "$packagedDesktopCredentialSmokePath" in script
    assert "Portable desktop smoke evidence missing" in script
    assert "Expected capture: $portableDesktopSmokeCapturePath" in script
    assert 'Join-Path $portableDesktopSmokeUserDataDir "data\\desktop-main.log"' in script
    assert "verify-desktop-package.ps1" in script
    assert '-Name "Desktop production build"' in script
    assert '$desktopBuildScript = if ($CheckPortableDesktop) { "build:portable" } else { "build" }' in script
    assert '@("run", $desktopBuildScript)' in script
    assert '-Name "Packaged desktop smoke"' in script
    packaged_args_start = script.index("$packagedDesktopSmokeArgs = @(")
    packaged_args_end = script.index('if ($CheckPortableDesktop)', packaged_args_start)
    packaged_smoke_args = script[
        packaged_args_start:packaged_args_end
    ]
    assert '"-CapturePath"' in packaged_smoke_args
    assert "$packagedDesktopSmokeCapturePath" in packaged_smoke_args
    assert '"-SmokeUserDataDir"' in packaged_smoke_args
    assert "$packagedDesktopSmokeUserDataDir" in packaged_smoke_args
    assert '"-PortableCapturePath"' in packaged_smoke_args
    assert "$portableDesktopSmokeCapturePath" in packaged_smoke_args
    assert '"-PortableSmokeUserDataDir"' in packaged_smoke_args
    assert "$portableDesktopSmokeUserDataDir" in packaged_smoke_args
    assert '"-CredentialSmokePath"' in packaged_smoke_args
    assert "$packagedDesktopCredentialSmokePath" in packaged_smoke_args
    assert '"-VisibleSmokePath"' in packaged_smoke_args
    assert "$packagedDesktopVisibleSmokePath" in packaged_smoke_args
    assert '"-VisibleSmokeUserDataDir"' in packaged_smoke_args
    assert "$packagedDesktopVisibleSmokeUserDataDir" in packaged_smoke_args
    assert "checkPortableDesktop" in script
    assert "packagedDesktopSmokeCapture" in script
    assert "packagedDesktopSmokeUserDataDir" in script
    assert "portableDesktopSmokeCapture" in script
    assert "portableDesktopSmokeUserDataDir" in script
    assert "packagedDesktopCredentialSmoke" in script
    assert "## Packaged Desktop Smoke" in script
    assert "Portable desktop smoke:" in script
    assert "Packaged desktop smoke:" in script
    assert "Packaged desktop capture:" in script
    assert "Packaged desktop user data:" in script
    assert "Portable desktop capture:" in script
    assert "Portable desktop user data:" in script
    assert "Packaged credential smoke:" in script
    assert "Packaged visible window smoke:" in script

    build = script.index('-Name "Frontend production build"')
    desktop_build = script.index('-Name "Desktop production build"')
    smoke = script.index('-Name "Packaged desktop smoke"')
    result = script.index("$result = [pscustomobject]@{")
    assert build < desktop_build < smoke < result
