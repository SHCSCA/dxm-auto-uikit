from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from src.services.http_errors import register_exception_handlers


def test_unexpected_error_is_logged_without_retry_or_rewriting_unknown_state(caplog):
    app = FastAPI()
    register_exception_handlers(app)
    calls = []
    state = {"execution_state": "unknown"}

    @app.post("/dispatch")
    def dispatch():
        calls.append("attempted")
        raise RuntimeError("token=never-return-this")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/dispatch", headers={"x-request-id": "contract-7"})
    assert response.status_code == 500
    assert response.json()["detail"]["request_id"] == "contract-7"
    assert "never-return-this" not in response.text
    assert calls == ["attempted"]
    assert state == {"execution_state": "unknown"}
    assert any(record.message == "http_unhandled_exception" for record in caplog.records)


def test_known_contract_rejection_keeps_original_status_detail_and_headers():
    app = FastAPI()
    register_exception_handlers(app)

    @app.post("/approve")
    def approve():
        raise HTTPException(409, {"reason_code": "APPROVAL_EXPIRED"}, headers={"Retry-After": "0"})

    with TestClient(app) as client:
        response = client.post("/approve")
    assert response.status_code == 409
    assert response.json() == {"detail": {"reason_code": "APPROVAL_EXPIRED"}}
    assert response.headers["retry-after"] == "0"


def test_validation_rejection_does_not_echo_password_input():
    class Credentials(BaseModel):
        password: str = Field(max_length=2)

    app = FastAPI()
    register_exception_handlers(app)

    @app.post("/credentials")
    def credentials(payload: Credentials):
        return {"ok": True}

    with TestClient(app) as client:
        response = client.post("/credentials", json={"password": "secret-password-input"})
    assert response.status_code == 422
    assert "secret-password-input" not in response.text
    assert response.json()["detail"][0]["loc"] == ["body", "password"]
