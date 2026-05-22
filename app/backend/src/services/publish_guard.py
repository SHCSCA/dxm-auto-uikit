from collections.abc import Iterable


class PublishGuardService:
    BLOCKED_ERROR_CODE = 'E999'
    _PUBLISH_PHRASES = (
        '立即发布',
        '继续发布',
        '保存并发布',
        '确认发布',
        '提交发布',
        '保存并移入待发布',
        '移入待发布',
    )
    _EXACT_PUBLISH_TERMS = (
        '发布',
    )
    _PUBLISH_URL_TERMS = (
        'submitpublish',
        'publish',
        'release',
        'online',
    )
    _SAVE_ACTIONS = ('save', '保存')

    def check(
        self,
        intended_action: str = '',
        target_text: str = '',
        current_url: str = '',
        visible_texts: Iterable[str] | None = None,
        modal_texts: Iterable[str] | None = None,
        network_urls: Iterable[str] | None = None,
    ) -> dict:
        reasons: list[str] = []
        self._append_if_publish_signal(reasons, 'intended_action', intended_action)
        self._append_if_publish_signal(reasons, 'target_text', target_text)
        self._append_if_publish_signal(reasons, 'current_url', current_url, url_like=True)
        self._append_collection_matches(reasons, 'visible_texts', visible_texts)
        self._append_collection_matches(reasons, 'modal_texts', modal_texts)
        self._append_collection_matches(reasons, 'network_urls', network_urls, url_like=True)

        return {
            'allowed': not reasons,
            'risk_level': 'critical' if reasons else 'low',
            'error_code': self.BLOCKED_ERROR_CODE if reasons else None,
            'reasons': reasons,
        }

    def evaluate(
        self,
        intended_action: str = '',
        target_text: str = '',
        current_url: str = '',
        visible_texts: Iterable[str] | None = None,
        modal_texts: Iterable[str] | None = None,
        network_urls: Iterable[str] | None = None,
    ) -> dict:
        return self.check(
            intended_action=intended_action,
            target_text=target_text,
            current_url=current_url,
            visible_texts=visible_texts,
            modal_texts=modal_texts,
            network_urls=network_urls,
        )

    def is_allowed(
        self,
        intended_action: str = '',
        target_text: str = '',
        current_url: str = '',
        visible_texts: Iterable[str] | None = None,
        modal_texts: Iterable[str] | None = None,
        network_urls: Iterable[str] | None = None,
    ) -> bool:
        return bool(self.check(
            intended_action=intended_action,
            target_text=target_text,
            current_url=current_url,
            visible_texts=visible_texts,
            modal_texts=modal_texts,
            network_urls=network_urls,
        )['allowed'])

    def _append_collection_matches(
        self,
        reasons: list[str],
        field_name: str,
        values: Iterable[str] | None,
        url_like: bool = False,
    ) -> None:
        for value in values or []:
            self._append_if_publish_signal(reasons, field_name, value, url_like=url_like)

    def _append_if_publish_signal(
        self,
        reasons: list[str],
        field_name: str,
        value: str | None,
        url_like: bool = False,
    ) -> None:
        matched_term = self._matched_publish_term(value, url_like=url_like)
        if matched_term:
            reasons.append(f'{field_name} contains publish signal: {matched_term}')

    def _matched_publish_term(self, value: str | None, url_like: bool = False) -> str | None:
        normalized = self._normalize(value)
        if not normalized:
            return None

        url_terms = self._PUBLISH_URL_TERMS if url_like else ()
        for term in (*self._PUBLISH_PHRASES, *url_terms):
            if term in normalized:
                return term
        for term in self._EXACT_PUBLISH_TERMS:
            if normalized == term:
                return term
        return None

    def _normalize(self, value: str | None) -> str:
        return ''.join(str(value or '').lower().split())
