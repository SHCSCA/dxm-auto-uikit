from fastapi.testclient import TestClient

from src.main import app


def test_health_ok():
    client = TestClient(app)
    response = client.get('/health')
    assert response.status_code == 200
    payload = response.json()
    assert payload['status'] == 'ok'
    assert payload['instanceId']
    assert payload['runtimeIdentity']['instanceId'] == payload['instanceId']
    assert payload['runtimeIdentity']['browserAgentPid'] == payload['runtimeIdentity']['backendPid']
    assert payload['runtimeIdentity']['browserExecutionModel'] == 'in_process_thread'


def test_health_and_runtime_status_expose_the_exact_same_frozen_identity(monkeypatch):
    import src.main as main

    client = TestClient(app)

    health = client.get('/health')
    runtime = client.get('/api/runtime/status?frontend_url=file://')

    assert health.status_code == 200
    assert runtime.status_code == 200
    health_identity = health.json()["runtimeIdentity"]
    runtime_payload = runtime.json()
    assert health.json()["instanceId"] == health_identity["instanceId"]
    assert runtime_payload["runtimeIdentity"] == health_identity
    assert runtime_payload["backend"]["runtimeIdentity"] == health_identity
    assert runtime_payload["backend"]["instanceId"] == health_identity["instanceId"]


def test_health_reuses_the_bootstrap_frozen_identity_without_regeneration():
    import src.main as main

    assert main.runtime_identity is main.runtime_bootstrap_state.runtime_identity
    assert main.RUNTIME_BACKEND_INSTANCE_ID == main.runtime_bootstrap_state.runtime_identity.instance_id
    assert main.health().runtimeIdentity.model_dump() == main.runtime_bootstrap_state.runtime_identity.as_dict()
    source = (main.REPO_ROOT / "app" / "backend" / "src" / "main.py").read_text(encoding="utf-8")
    assert "RuntimeIdentity.from_environment" not in source
