import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
FINAL_DELIVERY_CHECK = REPO_ROOT / "scripts" / "final-delivery-check.ps1"
FINAL_DELIVERY_STATE_CONTRACT = REPO_ROOT / "scripts" / "test-final-delivery-state-consistency-contract.ps1"
QA_BROWSER_CHECK = REPO_ROOT / "scripts" / "qa-browser-check.ps1"
VERIFY_DESKTOP_PACKAGE = REPO_ROOT / "scripts" / "verify-desktop-package.ps1"
WORKBENCH_MODULES = REPO_ROOT / "app" / "frontend" / "src" / "components" / "WorkbenchModules.tsx"
APP_SHELL = REPO_ROOT / "app" / "frontend" / "src" / "components" / "AppShell.tsx"
USER_DELIVERY_GUIDE = REPO_ROOT / "docs" / "product" / "用户交付使用说明-20260526.md"


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
    assert "$ExpectedRealDxmTwoStageEndToEnd = \"pending_live_dxm_validation\"" in script
    assert "Get-TwoStageAcceptanceReadiness" in script
    assert "twoStageAcceptance" in script
    assert "twoStageAcceptanceReadiness" in script
    assert "realDxmTwoStageEndToEnd" in script
    assert "expectedRealDxmTwoStageEndToEnd" in script
    assert "twoStageAcceptanceMatchesExpected" in script
    assert "productionDeliveryReady" in script
    assert "$overallOk = $localWorkbenchOk -and $gateEvidenceOk -and $realDxmWriteReadinessMatchesExpected -and $twoStageAcceptanceMatchesExpected" in script
    assert "Real DXM two-stage end-to-end" in script
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
    assert "do not infer claim_only, batch_save, unattended, or publish readiness" in script
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


def test_user_delivery_guide_explains_l2_allowlist_review_packet():
    guide = USER_DELIVERY_GUIDE.read_text(encoding="utf-8")
    l2_gate = (REPO_ROOT / "docs" / "product" / "L2只读Probe门禁.md").read_text(encoding="utf-8")

    assert "L2 Allowlist Review Candidates" in guide
    assert "review_only=True" in guide
    assert "allowlist_applied=False" in guide
    assert "不自动放行只读页面检查或真实保存" in guide
    assert "不能为了让报告全绿" in guide
    assert "l2-allowlist-review-template.md" in guide
    assert "l2-allowlist-review-template.json" in guide
    assert "sha256" in guide
    assert "哈希" in guide
    assert "approved_scope" in guide
    assert "residual_risk" in guide
    assert "Allowlist 人工评审记录" in l2_gate
    assert "l2_recheck_required=true" in l2_gate


def test_user_delivery_guide_has_current_acceptance_checklist():
    guide = USER_DELIVERY_GUIDE.read_text(encoding="utf-8")

    assert "# 用户交付使用说明 - 2026-06-24" in guide
    assert "## 验收人快速判定清单" in guide
    assert "自动化工作台验收通过" in guide
    assert "`Local workbench check: PASS`" in guide
    assert "`Browser QA: PASS`" in guide
    assert "`Real DXM write readiness: BLOCKED`" in guide
    assert "`Real DXM write readiness: READY`" in guide
    assert "`Real DXM two-stage end-to-end: pending_live_dxm_validation`" in guide
    assert "`Real DXM two-stage end-to-end: passed`" in guide
    assert "`Production delivery ready: True`" in guide
    assert "`twoStageAcceptance.passed=true`" in guide
    assert "`okScope=local_workbench_only`" in guide
    assert "`okScope=local_workbench_and_controlled_single_save_ready`" in guide
    assert "`realDxmMutationAllowed`" in guide
    assert "当前真实写入 readiness 以最新门禁为准" in guide
    assert "最终自检应为 `Real DXM write readiness: BLOCKED`" in guide
    assert "工作台可交付，真实写入未放行" in guide
    assert "工作台可交付，且受控单商品只保存当前可按门禁启动" in guide
    assert "源码包交付通过" in guide
    assert "`Source package check: PASS`" in guide
    assert "`scripts\\final-delivery-check.bat -RequireCleanWorktree`" in guide
    assert "-ExpectedRealDxmTwoStageEndToEnd pending_live_dxm_validation" in guide
    assert "-ExpectedRealDxmTwoStageEndToEnd passed" in guide
    assert "报告 JSON 中 `gitHead` 对应" in guide
    assert "真实单商品只保存仍只能按只读页面检查、人工批准和保存证据链启动" in guide
    assert "不能只看 `ok: true`" in guide


def test_readme_next_steps_focus_on_allowlist_l2_l3_reverification():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    next_steps = readme[readme.index("## 下一步重点"):readme.index("## 目录结构")]

    assert "config/l2_readonly_allowlist.json" in next_steps
    assert "待认领入箱 -> 商品箱编辑保存" in next_steps
    assert "待认领入箱是当前两段式主流程的第一段" in next_steps
    assert "批量、无人值守和发布" in next_steps
    assert "实现真实 `DxmAdapter`" not in next_steps
    assert "最终交付验收记录" in readme


def test_readme_explains_final_check_ok_scope_for_machine_consumers():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    assert "`ok: true`" in readme
    assert "`okScope`" in readme
    assert "`realDxmMutationAllowed`" in readme
    assert "不能只读取 `ok`" in readme


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


def test_browser_qa_bootstraps_two_stage_flow_without_fake_single_save_products():
    script = QA_BROWSER_CHECK.read_text(encoding="utf-8")
    ensure_section = script[script.index("async function ensureRealMutationTask"):script.index("async function verifyUnreleasedRealModeCreateBlocked")]

    assert "/api/acquisition/claim-requests" in ensure_section
    assert "/api/acquisition/claimed-products" in ensure_section
    assert "Local acceptance claim request" in ensure_section
    assert "Local acceptance draft save task" in ensure_section
    assert "LOCAL_ACCEPTANCE" in ensure_section
    assert "QA two-stage acquisition claim request" not in ensure_section
    assert "QA local gated single_save one product fixture" not in script
    assert "QA guarded single-save product" not in script
    assert "QA unreleased claim_only task" not in script
    assert "product_ids: [claimedProduct.id]" in ensure_section
    assert "source: 'qa'" not in ensure_section
    assert "product_ids: [qaProduct.id]" not in ensure_section


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
