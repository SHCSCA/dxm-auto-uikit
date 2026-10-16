"""独立观察层的隔离页面；不提供真实业务成功、视频或完整前序证明。"""

import hashlib
import base64
import os
from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace
from threading import current_thread

from src.batch_edit.scope_contract import canonical_sha256
from src.execution.dxm_login_flow import DxmLoginFlow
from src.execution.content_observation_flow import observe_content_finalize


NOW = '2026-08-31T00:01:00Z'


class Page:
    def __init__(self, payload):
        self.url = f'https://www.dianxiaomi.com/web/smt/edit?id={payload["product_id"]}'
        self.values = {field['field_key']: deepcopy(field['resolved_value']) for field in payload['fields']}
        self.values['title'] = 'Independently observed English result'
        self.values['videoUrl'] = 'https://media.invalid/observed.mp4'
        self.listeners, self.handlers, self.operations = {}, [], []
        self.drift, self.modal, self.missing = False, False, False
        self.capture_threads = []

    def locator(self, selector):
        return SimpleNamespace(count=lambda: int(self.modal) if selector.startswith('[role=') else 1,
            evaluate=lambda script: deepcopy(self.values))

    def evaluate(self, script, argument):
        self.operations.append(argument['operation'])
        assert argument['operation'] == 'readback'
        return {'ok': not self.missing, 'observations': [{'field_key': field['field_key'], 'found': True,
            'value': deepcopy(self.values[field['field_key']]), 'match_count': 1, 'aggregate_kind': 'single'}
            for field in argument['fields']]}

    def route(self, pattern, handler):
        self.handlers.append(handler)

    def unroute(self, pattern, handler):
        self.handlers.remove(handler)

    def on(self, event, callback):
        self.listeners[event] = callback

    def remove_listener(self, event, callback):
        self.listeners.pop(event, None)

    def screenshot(self, *, path, full_page):
        from pathlib import Path
        Path(path).write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='))
        instant = datetime.fromisoformat(NOW.replace('Z', '+00:00')).timestamp()
        os.utime(path, (instant, instant))
        self.capture_threads.append(current_thread().name)
        if self.drift:
            self.values['title'] = 'Drifted during capture'


class Flow:
    def __init__(self, payload, *, session):
        self._page = Page(payload)
        self.session = session
        self._execution_evidence_context = {}

    def browser_session_id(self):
        return self.session

    def refresh_account_context_hash(self):
        return 'A' * 64

    def set_execution_evidence_context(self, context):
        self._execution_evidence_context = dict(context)

    def clear_execution_evidence_context(self):
        self._execution_evidence_context = {}

    def set_mutation_authorizer(self, *args):
        pass

    def clear_mutation_authorizer(self):
        pass

    def recent_workflow_events(self, *args):
        return []

    def _normalize_frozen_target_identity(self, identity, *, store_name):
        return identity, canonical_sha256(identity)

    def _require_frozen_product_page_identity(self, *args, **kwargs):
        if self.session != self._execution_evidence_context['browser_session_id']:
            raise RuntimeError('CONTENT_OBSERVATION_SESSION_DRIFT')

    def _capture_current_editor_category_schema(self, page, payload, *, phase, reject_redirects=False):
        assert reject_redirects is True
        for handler in page.handlers:
            request = SimpleNamespace(url='https://www.dianxiaomi.com/api/smtCategory/attributeList.json',
                method='POST', post_data='categoryId=' + payload['category_id'])
            handler(SimpleNamespace(request=request, continue_=lambda: None, abort=lambda: None))
        return {'ok': True, 'expected_category_id': payload['category_id'], 'observed_category_id': payload['category_id'],
            'expected_category_schema_hash': payload['category_schema_hash'], 'observed_category_schema_hash': payload['category_schema_hash']}

    _capture_frozen_execution_values = staticmethod(DxmLoginFlow._capture_frozen_execution_values)
    _evidence_observed_at = staticmethod(lambda: NOW)

    def _evidence_descriptor(self, path):
        raw = path.read_bytes()
        return {'path': str(path), 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest().upper()}

    def observe_content_finalize(self, **kwargs):
        return observe_content_finalize(self, **kwargs)
