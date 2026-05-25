from fastapi.testclient import TestClient

from src.main import app


def test_cors_allows_loopback_frontend_origins():
    client = TestClient(app)

    response = client.options(
        "/health",
        headers={
            "Origin": "http://127.0.0.1:15173",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:15173"


def test_cors_does_not_allow_external_origins():
    client = TestClient(app)

    response = client.options(
        "/health",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
