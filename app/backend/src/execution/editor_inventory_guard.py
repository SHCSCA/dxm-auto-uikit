"""仅在已准备且已绑定的页面上建立零请求观察窗口，不追加传输路由。"""

from copy import deepcopy

from src.execution.native_video_transport import require_native_video_transport
from src.services.structured_logging import get_logger, log_exception


_LOGGER = get_logger('editor.inventory_guard')


class EditorInventoryGuard:
    def __init__(self, page, require_owner):
        self.page, self.require_owner = page, require_owner
        self.transport = self.token = None
        self.listeners, self.unexpected = [], []
        self.active = False

    def _reject(self, reason):
        self.unexpected.append(reason)
        if self.transport is not None:
            self.transport.invalid = True

    def require_live(self):
        self.require_owner()
        if (not self.active or self.transport is None or self.transport.invalid
                or self.transport.active is not self.token or self.token[0] is not self.page
                or self.page not in self.transport.bindings or self.page.context is not self.transport.context):
            raise RuntimeError('EDITOR_INVENTORY_TRANSPORT_SCOPE_DRIFT')
        self.transport._policy()

    def _route(self, route):
        self._reject('UNEXPECTED_REQUEST')
        try:
            route.abort()
        except Exception as exc:
            self._reject('REQUEST_ABORT_FAILED')
            log_exception(_LOGGER, 'editor_inventory_request_abort_failed', exc)

    def _dialog(self, dialog):
        self._reject('dialog')
        try:
            dialog.dismiss()
        except Exception as exc:
            self._reject('DIALOG_DISMISS_FAILED')
            log_exception(_LOGGER, 'editor_inventory_dialog_dismiss_failed', exc)

    def __enter__(self):
        try:
            self.require_owner()
            self.transport = require_native_video_transport(self.page)
            self.token = self.transport.activate(self.page, self._reject, self._route)
            self.active = True
            for event in ('popup', 'download', 'dialog', 'websocket', 'pageerror', 'framenavigated'):
                callback = self._dialog if event == 'dialog' else lambda *args, event=event: self._reject(event)
                self.listeners.append((event, callback))
                self.page.on(event, callback)
                self.require_live()
            return self
        except Exception as exc:
            self._reject('GUARD_REGISTRATION_FAILED')
            log_exception(_LOGGER, 'editor_inventory_guard_registration_failed', exc)
            self._cleanup()
            raise

    def facts(self):
        if self.unexpected:
            raise RuntimeError('EDITOR_INVENTORY_UNEXPECTED_EFFECT')
        self.require_owner()
        if self.transport is None:
            raise RuntimeError('EDITOR_INVENTORY_TRANSPORT_UNPROVEN')
        self.transport._policy()
        return deepcopy({'request_facts': [], 'unexpected_effects': []})

    def __exit__(self, exc_type, exc, traceback):
        if exc_type is not None:
            self._reject('OBSERVATION_FAILED')
        self._cleanup()
        if exc_type is None:
            self.facts()
        return False

    def _cleanup(self):
        failures, operations = [], self.listeners
        self.listeners = []
        # 导航监听最后撤回；清理期间传输窗口仍保持阻断。
        for event, callback in operations:
            try:
                self.page.remove_listener(event, callback)
            except Exception as exc:
                failures.append(exc)
                self._reject('LISTENER_CLEANUP_FAILED')
                log_exception(_LOGGER, 'editor_inventory_guard_cleanup_failed', exc, observed_event=event)
        if self.active:
            try:
                self.require_owner()
                if self.transport.active is not self.token:
                    raise RuntimeError('EDITOR_INVENTORY_TRANSPORT_SCOPE_DRIFT')
                if self.unexpected:
                    self.transport.invalid = True
            except Exception as exc:
                failures.append(exc)
                self._reject('FINAL_OWNER_UNPROVEN')
                log_exception(_LOGGER, 'editor_inventory_final_owner_failed', exc)
            try:
                self.transport.deactivate(self.page)
            except Exception as exc:
                failures.append(exc)
                self._reject('TRANSPORT_CLEANUP_FAILED')
                log_exception(_LOGGER, 'editor_inventory_transport_cleanup_failed', exc)
            finally:
                self.active = False
        if failures:
            raise RuntimeError('EDITOR_INVENTORY_GUARD_CLEANUP_FAILED') from failures[0]
