from __future__ import annotations

from collections.abc import Callable


class SemanticButton:
    def __init__(self, *, visible=True, enabled=True, inside_dialog=False, trial_error=None,
                 dispatch_error=None, on_click: Callable[[], object] | None = None):
        self.visible = visible
        self.enabled = enabled
        self.inside_dialog = inside_dialog
        self.trial_error = trial_error
        self.dispatch_error = dispatch_error
        self.on_click = on_click
        self.trials = 0
        self.dispatches = 0

    def is_visible(self):
        return self.visible

    def is_enabled(self):
        return self.enabled

    def evaluate(self, script):
        assert "closest" in script and "dialog" in script
        return self.inside_dialog

    def click(self, *, trial=False, **kwargs):
        if trial:
            self.trials += 1
            if self.trial_error:
                raise self.trial_error
            return None
        self.dispatches += 1
        if self.dispatch_error:
            raise self.dispatch_error
        if self.on_click:
            return self.on_click()
        return None


class SemanticLocator:
    def __init__(self, buttons):
        self.buttons = buttons

    def count(self):
        return len(self.buttons)

    def nth(self, index):
        return self.buttons[index]


class SemanticSavePage:
    url = "https://www.dianxiaomi.com/web/smt/edit?id=123"

    def __init__(self, buttons=None):
        self.buttons = [SemanticButton()] if buttons is None else buttons
        self.queries = []

    def get_by_role(self, role, *, name, exact):
        assert (role, name, exact) == ("button", "保存", True)
        self.queries.append((role, name, exact))
        return SemanticLocator(self.buttons)

    def wait_for_timeout(self, timeout):
        return None
