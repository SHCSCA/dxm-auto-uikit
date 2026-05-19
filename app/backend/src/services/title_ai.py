import json
from pathlib import Path
from urllib import error, request

from src.core.config import TITLE_AI_CONFIG_FILE


class TitleAIService:
    def __init__(self, config_file: Path | None = None):
        self.config_file = config_file or TITLE_AI_CONFIG_FILE

    def get_config(self) -> dict:
        config = self._load_config()
        api_key = str(config.get('api_key') or '').strip()
        return {
            'provider': 'deepseek',
            'model': config.get('model') or 'deepseek-chat',
            'base_url': 'https://api.deepseek.com/chat/completions',
            'has_api_key': bool(api_key),
            'api_key_masked': self._mask_api_key(api_key) if api_key else None,
        }

    def save_config(self, api_key: str, model: str = 'deepseek-chat') -> dict:
        payload = {
            'provider': 'deepseek',
            'model': model or 'deepseek-chat',
            'api_key': api_key.strip(),
        }
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        self.config_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        return self.get_config()

    def generate_title(self, source_title: str, title_style: str = 'clear, searchable, non-hype', max_length: int = 110) -> dict:
        config = self._load_config()
        api_key = str(config.get('api_key') or '').strip()
        model = str(config.get('model') or 'deepseek-chat').strip()
        if not api_key:
            raise RuntimeError('DeepSeek API Key 未配置，先调用 /api/ai/config 写入。')

        prompt = self._build_prompt(source_title=source_title, title_style=title_style, max_length=max_length)
        generated_title = self._request_title(prompt=prompt, api_key=api_key, model=model)
        final_title = self._normalize_title(generated_title, max_length=max_length)
        return {
            'provider': 'deepseek',
            'model': model,
            'source_title': source_title,
            'generated_title': final_title,
            'max_length': max_length,
        }

    def _load_config(self) -> dict:
        if not self.config_file.exists():
            return {'provider': 'deepseek', 'model': 'deepseek-chat', 'api_key': ''}
        return json.loads(self.config_file.read_text(encoding='utf-8'))

    def _build_prompt(self, source_title: str, title_style: str, max_length: int) -> str:
        return (
            '你是跨境电商标题生成器。\n'
            '任务：把中文商品标题改写成英文标题。\n'
            '硬约束：\n'
            '1. 只能使用原始标题能支持的事实，不得杜撰尺寸、数量、材质、功能。\n'
            '2. 只输出一行英文标题，不要解释，不要序号，不要引号。\n'
            '3. 不要输出促销词、夸张词、包邮词。\n'
            f'4. 标题长度不超过 {max_length} 个字符。\n'
            f'5. 风格要求：{title_style}。\n'
            f'原始中文标题：{source_title}'
        )

    def _request_title(self, prompt: str, api_key: str, model: str) -> str:
        payload = json.dumps({
            'model': model,
            'messages': [
                {'role': 'system', 'content': 'You generate compliant English ecommerce titles.'},
                {'role': 'user', 'content': prompt},
            ],
            'temperature': 0.2,
        }).encode('utf-8')
        req = request.Request(
            url='https://api.deepseek.com/chat/completions',
            data=payload,
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {api_key}',
            },
            method='POST',
        )
        try:
            with request.urlopen(req, timeout=60) as response:
                data = json.loads(response.read().decode('utf-8'))
        except error.HTTPError as exc:
            detail = exc.read().decode('utf-8', errors='ignore')
            raise RuntimeError(f'DeepSeek 调用失败：HTTP {exc.code} {detail}') from exc
        except error.URLError as exc:
            raise RuntimeError(f'DeepSeek 网络调用失败：{exc.reason}') from exc

        choices = data.get('choices') or []
        if not choices:
            raise RuntimeError('DeepSeek 未返回可用标题结果。')
        content = ((choices[0].get('message') or {}).get('content') or '').strip()
        if not content:
            raise RuntimeError('DeepSeek 返回内容为空。')
        return content.splitlines()[0].strip()

    def _normalize_title(self, title: str, max_length: int) -> str:
        cleaned = ' '.join(title.replace('"', '').replace("'", '').split())
        return cleaned[:max_length].strip()

    def _mask_api_key(self, api_key: str) -> str:
        if len(api_key) <= 10:
            return '*' * len(api_key)
        return api_key[:5] + '*' * (len(api_key) - 9) + api_key[-4:]