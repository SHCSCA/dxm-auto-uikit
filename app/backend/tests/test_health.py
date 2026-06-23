from fastapi.testclient import TestClient

from src.main import app


def test_health_ok():
    client = TestClient(app)
    response = client.get('/health')
    assert response.status_code == 200
    assert response.json() == {'status': 'ok'}


def test_health_exposes_backend_instance_id_when_launcher_sets_it(monkeypatch):
    import src.main as main

    monkeypatch.setattr(main, "RUNTIME_BACKEND_INSTANCE_ID", "desktop-instance-test")
    client = TestClient(app)

    response = client.get('/health')

    assert response.status_code == 200
    assert response.json()["instanceId"] == "desktop-instance-test"
