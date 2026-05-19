from fastapi.testclient import TestClient

from src.main import app


def test_create_template():
    client = TestClient(app)
    response = client.post('/api/templates', json={
        'template_type': 'title',
        'template_name': '标题模板A',
        'binding_scope': 'platform/category',
        'payload': {'rule': '[核心词]+[卖点词]'},
        'is_enabled': True,
    })
    assert response.status_code == 200
    data = response.json()
    assert data['template_name'] == '标题模板A'
    assert data['payload']['rule'] == '[核心词]+[卖点词]'
