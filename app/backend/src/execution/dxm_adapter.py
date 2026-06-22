from typing import Any


class DxmWorkflowAdapter:
    def __init__(self, login_flow: Any) -> None:
        self.login_flow = login_flow

    def check_login_state(self) -> dict[str, Any]:
        visible_state = self._visible_logged_in_state()
        if visible_state is not None:
            return self._result('check_login_state', visible_state)
        live_client = getattr(self.login_flow, 'live_client', None)
        if live_client is not None and hasattr(live_client, 'probe_session'):
            try:
                return self._result('check_login_state', self._state_from_live_probe(live_client.probe_session()))
            except Exception as exc:
                saved_state = self.login_flow.get_state()
                if self._state_looks_logged_in(saved_state):
                    return self._result(
                        'check_login_state',
                        {
                            **saved_state,
                            'stage': saved_state.get('stage') or 'login_success',
                            'live_probe_error': str(exc),
                        },
                    )
                raise
        return self._result('check_login_state', self.login_flow.get_state())

    def open_draft_box(self) -> dict[str, Any]:
        return self._result('open_draft_box', self.login_flow.navigate_post_login('draft_box'))

    def claim_product(
        self,
        note_text: str,
        product_query: str | None = None,
        store_name: str | None = None,
        target_source_urls: list[str] | None = None,
    ) -> dict[str, Any]:
        return self._result(
            'claim_product',
            self.login_flow.perform_draft_box_action(
                'remark',
                note_text,
                product_query=product_query,
                store_name=store_name,
                target_source_urls=target_source_urls,
            ),
        )

    def open_editor(
        self,
        product_query: str | None = None,
        store_name: str | None = None,
        note_text: str | None = None,
    ) -> dict[str, Any]:
        return self._result(
            'open_editor',
            self.login_flow.perform_draft_box_action(
                'edit',
                note_text,
                product_query=product_query,
                store_name=store_name,
            ),
        )

    def enable_semi_managed(
        self,
        product_query: str | None = None,
        store_name: str | None = None,
    ) -> dict[str, Any]:
        return self._result(
            'enable_semi_managed',
            self.login_flow.perform_editor_action(
                'enable_semi_managed',
                product_query=product_query,
                store_name=store_name,
            ),
        )

    def fill_editor_required_defaults(
        self,
        defaults: dict[str, Any] | None = None,
        product_query: str | None = None,
        store_name: str | None = None,
    ) -> dict[str, Any]:
        return self._result(
            'fill_editor_required_defaults',
            self.login_flow.perform_editor_action(
                'fill_editor_required_defaults',
                defaults=defaults,
                product_query=product_query,
                store_name=store_name,
            ),
        )

    def fill_media_assets(
        self,
        defaults: dict[str, Any] | None = None,
        product_query: str | None = None,
        store_name: str | None = None,
    ) -> dict[str, Any]:
        return self._result(
            'fill_media_assets',
            self.login_flow.perform_editor_action(
                'fill_media_assets',
                defaults=defaults,
                product_query=product_query,
                store_name=store_name,
            ),
        )

    def verify_edit_ownership(
        self,
        product_query: str | None = None,
        store_name: str | None = None,
    ) -> dict[str, Any]:
        return self._result(
            'verify_edit_ownership',
            self.login_flow.perform_editor_action(
                'verify_edit_ownership',
                product_query=product_query,
                store_name=store_name,
            ),
        )

    def fill_editor_variants(
        self,
        defaults: dict[str, Any] | None = None,
        product_query: str | None = None,
        store_name: str | None = None,
    ) -> dict[str, Any]:
        return self._result(
            'fill_editor_variants',
            self.login_flow.perform_editor_action(
                'fill_editor_variants',
                defaults=defaults,
                product_query=product_query,
                store_name=store_name,
            ),
        )

    def fill_compliance_defaults(
        self,
        defaults: dict[str, Any] | None = None,
        product_query: str | None = None,
        store_name: str | None = None,
    ) -> dict[str, Any]:
        return self._result(
            'fill_compliance_defaults',
            self.login_flow.perform_editor_action(
                'fill_compliance_defaults',
                defaults=defaults,
                product_query=product_query,
                store_name=store_name,
            ),
        )

    def open_semi_managed_page(
        self,
        defaults: dict[str, Any] | None = None,
        product_query: str | None = None,
        store_name: str | None = None,
    ) -> dict[str, Any]:
        return self._result(
            'open_semi_managed_page',
            self.login_flow.perform_editor_action(
                'open_semi_managed_page',
                defaults=defaults,
                product_query=product_query,
                store_name=store_name,
            ),
        )

    def fill_semi_managed_defaults(
        self,
        defaults: dict[str, Any] | None = None,
        product_query: str | None = None,
        store_name: str | None = None,
    ) -> dict[str, Any]:
        return self._result(
            'fill_semi_managed_defaults',
            self.login_flow.perform_editor_action(
                'fill_semi_managed_defaults',
                defaults=defaults,
                product_query=product_query,
                store_name=store_name,
            ),
        )

    def save_only(
        self,
        defaults: dict[str, Any] | None = None,
        product_query: str | None = None,
        store_name: str | None = None,
    ) -> dict[str, Any]:
        return self._result(
            'save_only',
            self.login_flow.perform_editor_action(
                'save_only',
                defaults=defaults,
                product_query=product_query,
                store_name=store_name,
            ),
        )

    def verify_not_published(
        self,
        product_query: str | None = None,
        store_name: str | None = None,
    ) -> dict[str, Any]:
        return self._result(
            'verify_not_published',
            self.login_flow.perform_editor_action(
                'verify_not_published',
                product_query=product_query,
                store_name=store_name,
            ),
        )

    def update_live_hud(self, hud: dict[str, Any]) -> dict[str, Any]:
        updater = getattr(self.login_flow, 'update_live_hud', None)
        if not callable(updater):
            return {'ok': True, 'updated': False, 'reason': 'live_hud_unavailable'}
        return updater(hud)

    def _result(self, action: str, evidence: dict[str, Any]) -> dict[str, Any]:
        stage = evidence.get('stage')
        return {
            'ok': not str(stage).endswith('_failed'),
            'stage': stage,
            'page_title': evidence.get('page_title'),
            'page_url': evidence.get('page_url'),
            'screenshot_url': evidence.get('screenshot_url'),
            'action': action,
            'product_query': evidence.get('product_query'),
            'store_name': evidence.get('store_name'),
            'save_result': evidence.get('save_result'),
            'fill_result': evidence.get('fill_result'),
            'evidence': evidence,
        }

    def _state_from_live_probe(self, probe: dict[str, Any]) -> dict[str, Any]:
        if probe.get('logged_in'):
            product_page = probe.get('product_page') or {}
            return {
                'stage': 'login_success',
                'page_title': probe.get('title') or product_page.get('title'),
                'page_url': probe.get('final_url') or product_page.get('url'),
                'screenshot_url': probe.get('home_screenshot_url') or probe.get('home_screenshot') or product_page.get('screenshot_url') or product_page.get('screenshot'),
                'live_probe': probe,
            }
        return {
            'stage': 'login_failed',
            'page_title': probe.get('title') or '店小秘登录态失效',
            'page_url': probe.get('final_url'),
            'screenshot_url': probe.get('home_screenshot_url') or probe.get('home_screenshot'),
            'live_probe': probe,
        }

    def _visible_logged_in_state(self) -> dict[str, Any] | None:
        has_visible_session = bool(
            getattr(self.login_flow, '_page', None)
            or getattr(self.login_flow, '_browser', None)
            or getattr(self.login_flow, '_context', None)
        )
        if not has_visible_session:
            return None
        state = self.login_flow.get_state()
        if self._state_looks_logged_in(state):
            return state
        return None

    def _state_looks_logged_in(self, state: dict[str, Any]) -> bool:
        if state.get('stage') == 'login_success':
            return True
        page_url = str(state.get('page_url') or '')
        page_title = str(state.get('page_title') or '')
        return 'dianxiaomi.com/web/' in page_url and '登录' not in page_title
