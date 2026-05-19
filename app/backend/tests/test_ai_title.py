from pathlib import Path

from fastapi.testclient import TestClient

from src.main import app
from src.services.title_ai import TitleAIService


class DummyTitleAIService:
    def __init__(self):
        self.saved_payload = None
        self.generated_payload = None

    def get_config(self):
        return {
            'provider': 'deepseek',
            'model': 'deepseek-chat',
            'base_url': 'https://api.deepseek.com/chat/completions',
            'has_api_key': True,
            'api_key_masked': 'sk-****badd',
        }

    def save_config(self, api_key: str, model: str = 'deepseek-chat'):
        self.saved_payload = {'api_key': api_key, 'model': model}
        return self.get_config()

    def generate_title(self, source_title: str, title_style: str = 'clear, searchable, non-hype', max_length: int = 110):
        self.generated_payload = {
            'source_title': source_title,
            'title_style': title_style,
            'max_length': max_length,
        }
        return {
            'provider': 'deepseek',
            'model': 'deepseek-chat',
            'source_title': source_title,
            'generated_title': 'Hazbin Hotel Alastor Acrylic Stand Desktop Ornament',
            'max_length': max_length,
        }


def test_get_ai_config_returns_deepseek_defaults(monkeypatch):
    service = DummyTitleAIService()
    monkeypatch.setattr('src.main.title_ai_service', service)

    client = TestClient(app)
    response = client.get('/api/ai/config')

    assert response.status_code == 200
    data = response.json()
    assert data['provider'] == 'deepseek'
    assert data['model'] == 'deepseek-chat'
    assert data['has_api_key'] is True
    assert data['api_key_masked'].startswith('sk-')


def test_post_ai_config_saves_api_key_and_model(monkeypatch):
    service = DummyTitleAIService()
    monkeypatch.setattr('src.main.title_ai_service', service)

    client = TestClient(app)
    response = client.post('/api/ai/config', json={
        'api_key': 'sk-test-123456',
        'model': 'deepseek-chat',
    })

    assert response.status_code == 200
    assert service.saved_payload == {
        'api_key': 'sk-test-123456',
        'model': 'deepseek-chat',
    }
    assert response.json()['model'] == 'deepseek-chat'


def test_generate_title_endpoint_uses_ai_service(monkeypatch):
    service = DummyTitleAIService()
    monkeypatch.setattr('src.main.title_ai_service', service)

    client = TestClient(app)
    response = client.post('/api/ai/title/generate', json={
        'source_title': '地狱客栈阿拉斯托亚克力立牌桌面摆件',
        'title_style': 'clear, searchable, non-hype',
        'max_length': 90,
    })

    assert response.status_code == 200
    data = response.json()
    assert service.generated_payload == {
        'source_title': '地狱客栈阿拉斯托亚克力立牌桌面摆件',
        'title_style': 'clear, searchable, non-hype',
        'max_length': 90,
    }
    assert data['generated_title'] == 'Hazbin Hotel Alastor Acrylic Stand Desktop Ornament'
    assert data['model'] == 'deepseek-chat'


def test_title_ai_service_loads_defaults_without_existing_file(tmp_path):
    service = TitleAIService(config_file=tmp_path / 'title-ai.json')

    data = service.get_config()

    assert data['provider'] == 'deepseek'
    assert data['model'] == 'deepseek-chat'
    assert data['has_api_key'] is False
    assert data['api_key_masked'] is None


def test_title_ai_service_save_config_masks_api_key(tmp_path):
    config_file = tmp_path / 'title-ai.json'
    service = TitleAIService(config_file=config_file)

    data = service.save_config(api_key='sk-1234567890abcdef', model='deepseek-chat')

    assert data['has_api_key'] is True
    assert data['api_key_masked'] == 'sk-12**********cdef'
    assert config_file.exists() is True
    assert '1234567890abcdef' in config_file.read_text(encoding='utf-8')
