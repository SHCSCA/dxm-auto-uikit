import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
FINAL_DELIVERY_CHECK = REPO_ROOT / "scripts" / "final-delivery-check.ps1"
QA_BROWSER_CHECK = REPO_ROOT / "scripts" / "qa-browser-check.ps1"
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
    assert '-TimeoutSeconds 360' in backend_pytest_section
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


def test_final_delivery_check_reports_l2_probe_evidence_and_plan():
    script = FINAL_DELIVERY_CHECK.read_text(encoding="utf-8")

    assert "Invoke-JsonUtf8" in script
    assert "Invoke-RestMethod -Uri \"$workspaceApiBase/api/delivery/workspace\"" not in script
    assert "Get-JsonObjectPropertyCount $l2Gate.latest.realTargets" in script
    assert "Get-JsonObjectPropertyCount $l2Gate.latest.mockTargets" in script
    assert "l2ProbeEvidenceSummary" in script
    assert "l2AllowlistReviewCandidates" in script
    assert "l2AllowlistReviewTemplate" in script
    assert "l2AllowlistReviewTemplateHashes" in script
    assert "Get-FileHash -LiteralPath $l2AllowlistReviewTemplateMarkdownPath" in script
    assert "markdown_sha256" in script
    assert "json_sha256" in script
    assert "l2ProbePlan" in script
    assert "okScope" in script
    assert "realDxmMutationAllowed" in script
    assert "$ExpectedRealDxmWriteReadiness = \"READY\"" in script
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

    assert "# 用户交付使用说明 - 2026-06-11" in guide
    assert "## 验收人快速判定清单" in guide
    assert "自动化工作台验收通过" in guide
    assert "`Local workbench check: PASS`" in guide
    assert "`Browser QA: PASS`" in guide
    assert "`Real DXM write readiness: READY`" in guide
    assert "`okScope=local_workbench_and_controlled_single_save_ready`" in guide
    assert "`realDxmMutationAllowed=true`" in guide
    assert "自动化工作台与受控单商品只保存可交付" in guide
    assert "源码包交付通过" in guide
    assert "`Source package check: PASS`" in guide
    assert "`scripts\\final-delivery-check.bat -RequireCleanWorktree`" in guide
    assert "以 `outputs/final-delivery-check/final-delivery-check.json` 的 `gitHead` 字段为准" in guide
    assert "真实单商品只保存仍只能按只读页面检查、人工批准和保存证据链启动" in guide
    assert "不能只看 `ok: true`" in guide


def test_readme_next_steps_focus_on_allowlist_l2_l3_reverification():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    next_steps = readme[readme.index("## 下一步重点"):readme.index("## 目录结构")]

    assert "config/l2_readonly_allowlist.json" in next_steps
    assert "受控单商品只保存证据" in next_steps
    assert "认领或批量保存" in next_steps
    assert "批量、无人值守和发布" in next_steps
    assert "实现真实 `DxmAdapter`" not in next_steps
    assert "最终交付验收记录-20260603.md" in readme


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


def test_final_delivery_check_captures_final_report_center_after_final_json_write():
    script = FINAL_DELIVERY_CHECK.read_text(encoding="utf-8")
    qa_script = QA_BROWSER_CHECK.read_text(encoding="utf-8")
    workbench_modules = WORKBENCH_MODULES.read_text(encoding="utf-8")
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
    assert "hasExpectedPostFinalReportQa" in qa_script[qa_script.index("assertions: {"):qa_script.index("finalReportApiIsFinal")]
    assert "'最终报告中心 QA '" not in qa_script
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
    assert 'testId="final-report-center-qa"' in workbench_modules
    assert "state={postFinalReportQaState}" in workbench_modules
    assert "data-testid={testId}" in workbench_modules
    assert "data-state={state}" in workbench_modules
    assert ".l2-review-candidates" in frontend_css
    assert "overflow-wrap: anywhere" in frontend_css
    assert 'data-testid="final-report-center-screenshot-path"' in workbench_modules
    assert 'data-testid="report-center-section"' in workbench_modules
    assert ".replaceAll(" not in workbench_modules
    assert "data-section={item.id}" in app_shell
    assert "Final report state QA" in script
    assert "Final report center QA" in script
    assert "Remove-PostFinalReportQaArtifacts" in script
    assert "$postFinalReportStateQaCommand.ok" in script
    assert "$postFinalReportCenterQaCommand.ok" in script
    assert "postFinalReportQa" in script
    assert "finalReportCenterScreenshot" in script
    final_json_write = script.index("$result | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $jsonPath -Encoding UTF8")
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
