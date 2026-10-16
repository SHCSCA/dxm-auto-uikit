"""仅在最终读回窗口内允许精确类目 Schema 读取，拒绝其它请求和 UI 副作用。"""

import hashlib
from urllib.parse import parse_qs, urlsplit

from src.services.structured_logging import get_logger, log_exception


class ContentObservationGuard:
    def __init__(self, page, category_id):
        self.page, self.category_id = page, str(category_id)
        self.requests, self.unexpected = [], []
        self.listeners = []
        self.handler = self._route
        self.route_installed = False

    def _route(self, route):
        try:
            request = route.request
            parts = urlsplit(request.url)
            values = parse_qs(request.post_data or '', keep_blank_values=True)
            expected = {'categoryId'} if parts.path == '/api/smtCategory/attributeList.json' else {'categoryId', 'arrtNameId', 'arrtValueId'}
            allowed = (request.method == 'POST' and parts.scheme == 'https' and parts.netloc == 'www.dianxiaomi.com'
                and not parts.query and not parts.fragment
                and parts.path in {'/api/smtCategory/attributeList.json', '/api/smtCategory/childAttributeList.json'}
                and set(values) == expected and values.get('categoryId') == [self.category_id]
                and all(len(items) == 1 and items[0].isdecimal() and int(items[0]) > 0 for items in values.values()))
            self.requests.append({'method': request.method, 'path': parts.path,
                'request_sha256': hashlib.sha256((request.post_data or '').encode()).hexdigest().upper(), 'allowed': allowed})
            if not allowed:
                self.unexpected.append('UNEXPECTED_REQUEST')
                route.abort()
            else:
                route.continue_()
        except Exception as exc:
            self.unexpected.append('REQUEST_GUARD_FAILED')
            log_exception(get_logger('content_observation'), 'content_observation_guard_failed', exc)
            route.abort()

    def __enter__(self):
        try:
            self.route_installed = True
            self.page.route('**/*', self.handler)
            for event in ('popup', 'download', 'dialog', 'framenavigated', 'websocket'):
                callback = lambda *args, event=event: self.unexpected.append(event)
                self.listeners.append((event, callback))
                self.page.on(event, callback)
            return self
        except Exception as exc:
            log_exception(get_logger('content_observation'), 'content_observation_guard_registration_failed', exc)
            self._cleanup()
            raise

    def facts(self):
        if self.unexpected:
            raise RuntimeError('CONTENT_OBSERVATION_UNEXPECTED_EFFECT')
        return {'request_facts': list(self.requests), 'unexpected_effects': []}

    def __exit__(self, *args):
        self._cleanup()
        self.facts()

    def _cleanup(self):
        failures = []
        operations = [('listener', event, callback) for event, callback in self.listeners]
        self.listeners.clear()
        if self.route_installed:
            operations.insert(0, ('route', '**/*', self.handler))
            self.route_installed = False
        for kind, event, callback in operations:
            try:
                if kind == 'route':
                    self.page.unroute(event, callback)
                else:
                    self.page.remove_listener(event, callback)
            except Exception as exc:
                failures.append(exc)
                log_exception(get_logger('content_observation'), 'content_observation_guard_cleanup_failed', exc, resource=kind, observed_event=event)
        if failures:
            raise RuntimeError('CONTENT_OBSERVATION_GUARD_CLEANUP_FAILED') from failures[0]
