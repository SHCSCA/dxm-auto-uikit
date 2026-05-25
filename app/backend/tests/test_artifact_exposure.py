from fastapi.testclient import TestClient

from src.main import DATA_DIR, app, normalize_artifact_paths


def test_artifacts_route_does_not_expose_sensitive_data_dirs():
    sensitive_file = DATA_DIR / "sessions" / "artifact-exposure-test.txt"
    sensitive_file.parent.mkdir(parents=True, exist_ok=True)
    sensitive_file.write_text("secret-cookie", encoding="utf-8")

    try:
        response = TestClient(app).get("/artifacts/sessions/artifact-exposure-test.txt")
    finally:
        sensitive_file.unlink(missing_ok=True)

    assert response.status_code == 404


def test_artifacts_route_serves_public_screenshots():
    public_file = DATA_DIR / "screenshots" / "artifact-public-test.txt"
    public_file.parent.mkdir(parents=True, exist_ok=True)
    public_file.write_text("public-proof", encoding="utf-8")

    try:
        response = TestClient(app).get("/artifacts/screenshots/artifact-public-test.txt")
    finally:
        public_file.unlink(missing_ok=True)

    assert response.status_code == 200
    assert response.text == "public-proof"


def test_normalize_artifact_paths_only_urls_public_artifact_roots():
    public_file = DATA_DIR / "screenshots" / "public-proof.png"
    sensitive_file = DATA_DIR / "sessions" / "dianxiaomi_cookies.json"

    normalized = normalize_artifact_paths({
        "public": str(public_file),
        "sensitive": str(sensitive_file),
    })

    assert normalized["public_url"] == "/artifacts/screenshots/public-proof.png"
    assert "sensitive_url" not in normalized
