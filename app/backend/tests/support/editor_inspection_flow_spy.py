"""仅隔离公开检查编排；不冒充真实传输、生命周期或资源来源。"""

from types import SimpleNamespace

from src.execution import editor_inspection_dialog as dialog_module
from src.execution import editor_inspection_flow as inspection_module
from src.execution import native_video_script_capture as capture_module


def install_inspection_spies(monkeypatch, flow, page, guard, events, tmp_path, observe):
    class Owner:
        def __init__(self, actual, observed, url, *, video):
            assert actual is flow and observed in (None, page)
            self.page, self.url, self.video = page, url, video
            self.binding = SimpleNamespace(transport=SimpleNamespace(invalid=False))
            self.profile = None

        def start(self):
            if self.video:
                self.profile = capture_module.PassiveNativeVideoScriptCapture(page, expected_page_url=self.url).start()
            return self

        def require_document(self):
            assert page.url == self.url and not page.closed

        def rpc(self, method, *args, **kwargs):
            return method(*args, **kwargs)

        def seal_profile(self):
            if self.profile:
                self.profile.close()
                return self.profile.snapshot()
            return None

        def close(self):
            if self.profile and not self.profile.closed:
                self.profile.close()

    class Scope:
        def __init__(self, owner, observed_guard):
            assert observed_guard is guard
            self.owner = owner

        def __enter__(self):
            events.append('synthetic_scope_start')
            return self

        def __exit__(self, *_args):
            events.append('synthetic_scope_closed')
            return False

        def open_video_window(self):
            events.append('synthetic_video_window')
            return {'reveal_count': 0, 'entry_click_count': 0, 'visible_count': 0}

        def summary(self):
            return guard.summary()

    monkeypatch.setattr(inspection_module, 'EditorInspectionOwner', Owner)
    monkeypatch.setattr(inspection_module, 'EditorInspectionScope', Scope)
    monkeypatch.setattr(inspection_module, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(inspection_module, 'SCREENSHOT_DIR', tmp_path / 'screenshots')
    monkeypatch.setattr(dialog_module, 'wait_editor_form_stable', lambda *_: {'ok': True, 'snapshot': [{'field': 'synthetic', 'value': 'private-form-value'}]})
    monkeypatch.setattr(dialog_module, 'observe_inspection_video', lambda owner, **kwargs: observe(owner.page, **kwargs))
    monkeypatch.setattr(inspection_module, 'finalize_inspection_video', lambda *_: events.append('synthetic_final_read'))
