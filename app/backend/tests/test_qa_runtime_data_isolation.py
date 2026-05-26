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
    qa_backend_section = script[script.index('-Name "QA backend service"') - 400:script.index('Wait-HttpReady -Name "QA backend service"')]
    assert "DXM_DATA_DIR" in qa_backend_section
    assert "pytestRuntimeDataDir" in script
    assert "qaRuntimeDataDir" in script


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
    assert "$ExpectedRealDxmWriteReadiness = \"BLOCKED\"" in script
    assert "realDxmWriteReadinessMatchesExpected" in script
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
    assert "L2/L3 gate records available" in script
    assert "Only means L2/L3 records were readable; not that L2/L3 passed" in script
    assert "Gate evidence check:" not in script


def test_user_delivery_guide_explains_l2_allowlist_review_packet():
    guide = USER_DELIVERY_GUIDE.read_text(encoding="utf-8")
    l2_gate = (REPO_ROOT / "docs" / "product" / "L2只读Probe门禁.md").read_text(encoding="utf-8")

    assert "L2 Allowlist Review Candidates" in guide
    assert "review_only=True" in guide
    assert "allowlist_applied=False" in guide
    assert "不自动放行 L2/L3" in guide
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

    assert "# 用户交付使用说明 - 2026-05-26" in guide
    assert "## 验收人快速判定清单" in guide
    assert "本地工作台验收通过" in guide
    assert "`Local workbench check: PASS`" in guide
    assert "`Browser QA: PASS`" in guide
    assert "`Real DXM write readiness: BLOCKED`" in guide
    assert "`okScope=local_workbench_only`" in guide
    assert "`realDxmMutationAllowed=false`" in guide
    assert "只代表本地安全诊断工作台可交付" in guide
    assert "源码包交付通过" in guide
    assert "`Source package check: PASS`" in guide
    assert "`scripts\\final-delivery-check.bat -RequireCleanWorktree`" in guide
    assert "不允许启动真实写入" in guide
    assert "不能只看 `ok: true`" in guide


def test_readme_next_steps_focus_on_allowlist_l2_l3_reverification():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    next_steps = readme[readme.index("## 下一步重点"):readme.index("## 目录结构")]

    assert "评审 `allowlist_review_candidates`" in next_steps
    assert "最小、可审计的 L2 只读 allowlist" in next_steps
    assert "同一个 `run-id` 复跑真实 L2 双目标" in next_steps
    assert "L3 `single_save` 金丝雀" in next_steps
    assert "实现真实 `DxmAdapter`" not in next_steps


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


def test_final_delivery_check_captures_final_report_center_after_final_json_write():
    script = FINAL_DELIVERY_CHECK.read_text(encoding="utf-8")
    qa_script = QA_BROWSER_CHECK.read_text(encoding="utf-8")
    workbench_modules = WORKBENCH_MODULES.read_text(encoding="utf-8")
    app_shell = APP_SHELL.read_text(encoding="utf-8")
    frontend_css = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")

    assert "ReportOnlyFinal" in qa_script
    assert "AllowMissingPostFinalQa" in qa_script
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
