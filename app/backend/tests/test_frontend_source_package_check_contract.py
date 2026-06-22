from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
WORKBENCH_MODULES_TSX = REPO_ROOT / "app" / "frontend" / "src" / "components" / "WorkbenchModules.tsx"
RESULTS_PAGE_TSX = REPO_ROOT / "app" / "frontend" / "src" / "components" / "workbench" / "ResultsPage.tsx"
QA_BROWSER_CHECK = REPO_ROOT / "scripts" / "qa-browser-check.ps1"


def test_report_center_uses_source_package_check_not_readiness_for_acceptance_state():
    source = RESULTS_PAGE_TSX.read_text(encoding="utf-8")

    assert "SourcePackageCheckRow" in source
    assert "source_package_check === 'NOT_REQUIRED'" in source
    assert "源码包验收 NOT_REQUIRED" in source
    assert "默认本地验收不要求源码包 clean" in source
    assert "label={`源码包 ${finalCheck?.source_package_readiness" not in source


def test_browser_qa_asserts_source_package_not_required_copy():
    source = QA_BROWSER_CHECK.read_text(encoding="utf-8")

    assert "sourcePackageNotRequired" in source
    assert "sourcePackageNotRequiredCopy" in source
    assert "finalCheckSummaryForReport" in source
    assert "finalCheckSummaryForReport?.source_package_check === 'NOT_REQUIRED'" in source
