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


def test_template_center_metadata_exposes_chinese_edit_page_sections():
    client = TestClient(app)
    response = client.get('/api/template-center/metadata')

    assert response.status_code == 200
    data = response.json()
    section_labels = [section["label"] for section in data["sections"]]
    assert "店铺与任务基础" in section_labels
    assert "店小秘引用模板" in section_labels
    assert "仅本次任务使用" in data["actions"]
    assert "保存为店铺模板" in data["actions"]
