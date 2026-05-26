import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
FINAL_DELIVERY_CHECK = REPO_ROOT / "scripts" / "final-delivery-check.ps1"


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
    assert "l2ProbePlan" in script
    assert "## L2 Readonly Probe Evidence" in script
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
