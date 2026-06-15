import pytest

from src.execution import dxm_live as dxm_live_module
from src.execution.dxm_live import DxmLiveClient


def test_probe_session_closes_browser_when_home_probe_fails(monkeypatch, tmp_path):
    close_calls: list[str] = []

    class FakePage:
        def goto(self, *args, **kwargs):
            raise RuntimeError('network down')

    class FakeContext:
        def add_cookies(self, cookies):
            pass

        def new_page(self):
            return FakePage()

    class FakeBrowser:
        def new_context(self, *args, **kwargs):
            return FakeContext()

        def close(self):
            close_calls.append('closed')

    class FakeChromium:
        def launch(self, **kwargs):
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

    class FakePlaywrightManager:
        def __enter__(self):
            return FakePlaywright()

        def __exit__(self, exc_type, exc, tb):
            return False

    cookie_file = tmp_path / 'cookies.json'
    cookie_file.write_text('[]', encoding='utf-8')
    client = DxmLiveClient()
    client.cookie_file = cookie_file

    monkeypatch.setattr(dxm_live_module, 'sync_playwright', lambda: FakePlaywrightManager())
    monkeypatch.setattr(client, 'load_cookies', lambda: [])

    with pytest.raises(RuntimeError, match='network down'):
        client.probe_session()

    assert close_calls == ['closed']
