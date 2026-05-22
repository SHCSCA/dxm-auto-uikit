from fastapi.testclient import TestClient

from src.main import app


def test_selector_profile_list_endpoint():
    client = TestClient(app)

    response = client.get('/api/selector-profiles')

    assert response.status_code == 200
    assert [item['page_key'] for item in response.json()] == [
        'smt_draft_list',
        'smt_edit',
        'smt_semi_edit',
    ]


def test_selector_profile_validate_endpoint_reports_forbidden_button():
    client = TestClient(app)

    response = client.post(
        '/api/selector-profiles/smt_edit/validate',
        json={
            'url': 'https://www.dianxiaomi.com/web/smt/edit?id=1',
            'body_text': '商品信息 半托管服务 编辑半托管信息',
            'visible_buttons': ['保存', '发布'],
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data['ok'] is False
    assert data['forbidden_hits'] == ['发布']
