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


def test_update_template_can_disable_template():
    client = TestClient(app)
    created = client.post('/api/templates', json={
        'template_type': 'logistics',
        'template_name': '可停用物流模板',
        'binding_scope': 'Dang Kang / 立牌类谷子',
        'payload': {'logistics': {'logistics_type': '普货'}},
        'is_enabled': True,
    }).json()

    response = client.patch(f"/api/templates/{created['id']}", json={'is_enabled': False})

    assert response.status_code == 200
    data = response.json()
    assert data['template_name'] == '可停用物流模板'
    assert data['is_enabled'] is False


def test_template_center_metadata_exposes_chinese_edit_page_sections():
    client = TestClient(app)
    response = client.get('/api/template-center/metadata')

    assert response.status_code == 200
    data = response.json()
    section_labels = [section["label"] for section in data["sections"]]
    assert "店铺与任务基础" in section_labels
    assert "店小秘引用模板" in section_labels
    assert "仅本次任务使用" in data["actions"]
    assert "设为店铺默认模板" in data["actions"]
    assert "设为类目默认模板" in data["actions"]
    assert "套用预置配置模板" in data["actions"]
    assert "套用默认测试模板" not in data["actions"]
