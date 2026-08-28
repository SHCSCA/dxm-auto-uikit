from pathlib import Path

import pytest
from pydantic import ValidationError

from src.main import app
from src.models import TaskCreate
from src.state_machine.contracts import ExecutionMode, StateName, normalize_execution_mode


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_business_claim_routes_are_not_part_of_the_api() -> None:
    route_paths = {route.path for route in app.routes}

    assert "/api/acquisition/claim-requests" not in route_paths
    assert "/api/acquisition/claimed-products" not in route_paths
    assert "/api/dxm/workflow/claim-product" not in route_paths


def test_claim_only_is_not_an_execution_mode() -> None:
    assert "claim_only" not in {mode.value for mode in ExecutionMode}
    with pytest.raises(ValueError):
        normalize_execution_mode("claim_only")
    with pytest.raises(ValidationError):
        TaskCreate.model_validate(
            {
                "name": "removed business flow",
                "mode": "claim_only",
                "publish_scene": "SMT_CLAIM_TO_DRAFT_ONLY",
            }
        )


def test_claim_to_draft_states_are_removed() -> None:
    state_names = {state.value for state in StateName}

    assert "OPEN_DATA_ACQUISITION" not in state_names
    assert "CLAIM_TO_DRAFT_BOX" not in state_names
    assert "VERIFY_DRAFT_BOX_CLAIM" not in state_names


def test_frontend_has_no_business_claim_page_or_route() -> None:
    frontend = REPO_ROOT / "app" / "frontend" / "src"
    app_source = (frontend / "App.tsx").read_text(encoding="utf-8")
    type_source = (frontend / "types.ts").read_text(encoding="utf-8")

    assert not (frontend / "components" / "workbench" / "AcquisitionClaimPage.tsx").exists()
    for removed_token in (
        "AcquisitionClaimPage",
        "acquisition_claim",
        "/api/acquisition/claim-requests",
        "claim_only",
        "data_acquisition",
    ):
        assert removed_token not in app_source
    assert "AcquisitionClaimCreateRequest" not in type_source
    assert "AcquisitionClaimResponse" not in type_source

    current_product_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in frontend.rglob("*")
        if path.suffix in {".ts", ".tsx"}
    )
    for removed_copy in (
        "待认领",
        "认领入箱",
        "ClaimCandidate",
        "claimCandidates",
        "AcquisitionClaim",
        "twoStageAcceptance",
        "claim_only",
        "data_acquisition",
        "acquisition_claim",
    ):
        assert removed_copy not in current_product_source


def test_current_runtime_sources_do_not_expose_claim_to_draft_flow() -> None:
    runtime_files = (
        REPO_ROOT / "app" / "backend" / "src" / "main.py",
        REPO_ROOT / "app" / "backend" / "src" / "models.py",
        REPO_ROOT / "app" / "backend" / "src" / "execution" / "v1_runner.py",
        REPO_ROOT / "app" / "backend" / "src" / "execution" / "dxm_adapter.py",
        REPO_ROOT / "app" / "backend" / "src" / "execution" / "browser_agent_protocol.py",
        REPO_ROOT / "app" / "backend" / "src" / "execution" / "browser_agent_worker.py",
    )
    removed_tokens = (
        "claim_only",
        "CLAIM_TO_DRAFT_BOX",
        "VERIFY_DRAFT_BOX_CLAIM",
        "OPEN_DATA_ACQUISITION",
        "/api/acquisition/",
    )

    for path in runtime_files:
        source = path.read_text(encoding="utf-8")
        for removed_token in removed_tokens:
            assert removed_token not in source, f"{removed_token!r} remains in {path}"
