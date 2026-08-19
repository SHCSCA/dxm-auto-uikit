import os
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from src.execution.action_result_contract import ACTION_RESULT_CONTRACTS
from src.execution.browser_agent_protocol import canonical_frozen_target_identity


_FAILURE_CODE_PATTERN = re.compile(r'^[A-Z][A-Z0-9_]{2,63}$')
_CONTRACT_SOURCE_KEYS = (
    'contract_observations',
    'login_check',
    'live_probe',
    'wait_result',
    'navigation_result',
    'draft_action_result',
    'claim_result',
    'verification_result',
    'editor_action_result',
    'fill_result',
    'save_result',
    'unpublished_proof',
)
_FROZEN_TARGET_REQUIRED_ACTIONS = frozenset(
    {
        'claim_product',
        'open_editor',
        'verify_edit_ownership',
        'fill_editor_required_defaults',
        'fill_editor_variants',
        'fill_media_assets',
        'fill_compliance_defaults',
        'enable_semi_managed',
        'open_semi_managed_page',
        'fill_semi_managed_defaults',
        'save_only',
        'verify_not_published',
    }
)
_RECOVERABILITY_BY_CODE = {
    'AUTH_REVALIDATION_FAILED': ('manual_takeover', False, True),
    'AUTH_VERIFIER_MISSING': ('manual_takeover', False, True),
    'BROWSER_SESSION_MISMATCH': ('restart_runtime', True, True),
    'BROWSER_SESSION_UNAVAILABLE': ('restart_runtime', True, True),
    'MUTATION_OPERATION_FAILED': ('manual_takeover', False, True),
    'BROWSER_AGENT_COMMAND_REVOKED': ('manual_takeover', False, True),
    'BROWSER_AGENT_LATE_RESULT_IGNORED': ('manual_takeover', False, True),
    'MUTATION_LEDGER_COMMIT_FAILED': ('manual_takeover', False, True),
    'MUTATION_LEDGER_REQUIRED': ('manual_takeover', False, True),
    'MUTATION_LEDGER_UNAVAILABLE': ('manual_takeover', False, True),
    'MUTATION_DISPATCH_NOT_CONFIRMED': ('manual_takeover', False, True),
    'MUTATION_OUTCOME_UNKNOWN': ('manual_takeover', False, True),
    'PAGE_LOADING': ('retry_same_page', True, True),
    'RUNTIME_DISCONNECTED': ('restart_runtime', True, True),
    'STRUCTURED_UNPUBLISHED_STATUS_MISSING': ('manual_takeover', False, True),
}


def _mapping_copy(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _strict_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _exact_save_receipt(value: Mapping[str, Any]) -> bool:
    try:
        parsed = urlsplit(str(value.get('url') or ''))
    except ValueError:
        return False
    host = str(parsed.hostname or '').casefold()
    status = _strict_int(value.get('status'))
    message = str(value.get('message') or value.get('msg') or '').strip()
    return bool(
        value.get('ok') is True
        and value.get('receipt_complete') is True
        and _strict_int(value.get('receipt_count')) == 1
        and (host == 'dianxiaomi.com' or host.endswith('.dianxiaomi.com'))
        and str(parsed.path or '').casefold() in {
            '/api/popchoiceproduct/add.json',
            '/api/smtproduct/add.json',
        }
        and str(value.get('method') or '').upper() == 'POST'
        and status is not None
        and 200 <= status < 300
        and value.get('code') in (0, '0')
        and any(term in message for term in ('保存成功', '编辑保存成功', '编辑成功'))
    )


class DxmWorkflowAdapter:
    requires_persistent_browser_agent = True

    def __init__(self, login_flow: Any) -> None:
        self.login_flow = login_flow

    @staticmethod
    def _require_frozen_target_identity(
        action: str,
        target_identity: Mapping[str, Any] | None,
        store_name: str | None,
    ) -> dict[str, Any]:
        if not isinstance(target_identity, Mapping):
            raise ValueError(f'{action} requires a frozen exact target_identity')
        if not isinstance(store_name, str) or store_name != ' '.join(store_name.split()) or not store_name:
            raise ValueError(f'{action} requires a canonical exact store_name')
        normalized = canonical_frozen_target_identity(dict(target_identity), store_name=store_name)
        if normalized is None:
            raise ValueError(f'{action} target_identity validation returned empty')
        return normalized

    def set_workflow_event_listener(self, listener: Any | None) -> None:
        setter = getattr(self.login_flow, 'set_workflow_event_listener', None)
        if callable(setter):
            setter(listener)

    def set_mutation_authorizer(self, authorizer: Any | None, command_context: dict[str, Any] | None = None) -> None:
        setter = getattr(self.login_flow, 'set_mutation_authorizer', None)
        if callable(setter):
            setter(authorizer, command_context)

    def clear_mutation_authorizer(self) -> None:
        clearer = getattr(self.login_flow, 'clear_mutation_authorizer', None)
        if callable(clearer):
            clearer()

    def set_execution_evidence_context(self, context: dict[str, Any] | None) -> None:
        setter = getattr(self.login_flow, 'set_execution_evidence_context', None)
        if callable(setter):
            setter(context)

    def clear_execution_evidence_context(self) -> None:
        clearer = getattr(self.login_flow, 'clear_execution_evidence_context', None)
        if callable(clearer):
            clearer()

    def browser_session_id(self) -> str | None:
        getter = getattr(self.login_flow, 'browser_session_id', None)
        if not callable(getter):
            return None
        value = getter()
        text = str(value or '').strip()
        return text or None

    def refresh_account_context_hash(self) -> str:
        refresher = getattr(self.login_flow, 'refresh_account_context_hash', None)
        if not callable(refresher):
            raise RuntimeError('AUTH_ACCOUNT_CONTEXT_UNAVAILABLE')
        value = refresher()
        text = str(value or '').strip().upper()
        if len(text) != 64 or any(character not in '0123456789ABCDEF' for character in text):
            raise RuntimeError('AUTH_ACCOUNT_CONTEXT_UNAVAILABLE')
        return text

    def current_account_context_hash(self) -> str | None:
        getter = getattr(self.login_flow, 'current_account_context_hash', None)
        if not callable(getter):
            return None
        value = getter()
        text = str(value or '').strip().upper()
        if len(text) != 64 or any(character not in '0123456789ABCDEF' for character in text):
            return None
        return text

    def current_mutation_identity(self) -> dict[str, Any] | None:
        getter = getattr(self.login_flow, 'current_mutation_identity', None)
        if not callable(getter):
            return None
        value = getter()
        return dict(value) if isinstance(value, Mapping) else None

    def recent_workflow_events(self, limit: int = 20) -> list[dict[str, Any]]:
        recent = getattr(self.login_flow, 'recent_workflow_events', None)
        if not callable(recent):
            return []
        try:
            events = recent(limit)
        except TypeError:
            events = recent()
        return events if isinstance(events, list) else []

    def check_login_state(self) -> dict[str, Any]:
        if self._requires_visible_execution_browser_login_check():
            visible_checker = getattr(self.login_flow, 'check_visible_login_state', None)
            if callable(visible_checker):
                return self._result(
                    'check_login_state',
                    visible_checker(),
                    before_values={'probe': 'visible_execution_browser'},
                )
        visible_state = self._visible_logged_in_state()
        if visible_state is not None:
            return self._result(
                'check_login_state',
                visible_state,
                before_values={'probe': 'visible_execution_browser'},
            )
        live_client = getattr(self.login_flow, 'live_client', None)
        if live_client is not None and hasattr(live_client, 'probe_session'):
            try:
                return self._result(
                    'check_login_state',
                    self._state_from_live_probe(live_client.probe_session()),
                    before_values={'probe': 'live_session'},
                )
            except Exception as exc:
                saved_state = self.login_flow.get_state()
                return self._result(
                    'check_login_state',
                    {
                        **saved_state,
                        'ok': False,
                        'stage': 'login_failed',
                        'label': '登录态检测失败',
                        'message': '无法从当前真实会话重新证明登录账号，已按失败关闭。',
                        'next_action': '请重新打开真实登录页并完成登录，再次检测后读取草稿。',
                        'requires_user_action': True,
                        'live_probe_error': str(exc),
                    },
                    before_values={'probe': 'live_session_probe_failed_closed'},
                )
        return self._result(
            'check_login_state',
            self.login_flow.get_state(),
            before_values={'probe': 'saved_session'},
        )

    def open_draft_box(self) -> dict[str, Any]:
        return self._result(
            'open_draft_box',
            self.login_flow.navigate_post_login('draft_box'),
            before_values={'requested_page_identity': 'draft_box'},
        )

    def capture_draft_box_scope(self, max_items: int) -> dict[str, Any]:
        """Return the flow's raw, read-only scope attestation unchanged."""

        return self.login_flow.capture_draft_box_scope(max_items=max_items)

    def read_draft_shops(self) -> dict[str, Any]:
        """Return the allowlisted shopMap read envelope unchanged."""

        return self.login_flow.read_draft_shops()

    def read_category_children(self, pcid: str = '') -> list[dict[str, Any]]:
        return self.login_flow.read_category_children(pcid=pcid)

    def search_categories(self, keyword: str) -> list[dict[str, Any]]:
        return self.login_flow.search_categories(keyword=keyword)

    def get_category_by_id(self, category_id: str) -> dict[str, Any] | None:
        return self.login_flow.get_category_by_id(category_id=category_id)

    def read_draft_page(
        self,
        *,
        shop_id: str,
        page_no: int,
        page_size: int,
    ) -> dict[str, Any]:
        """Return one allowlisted draft-only page read envelope unchanged."""

        return self.login_flow.read_draft_page(
            shop_id=shop_id,
            page_no=page_no,
            page_size=page_size,
        )

    def read_e2_plan_scope(
        self,
        *,
        shop_id: str,
        category_ids: list[str],
    ) -> dict[str, Any]:
        """Return current-session E2 template/schema reads unchanged."""

        return self.login_flow.read_e2_plan_scope(
            shop_id=shop_id,
            category_ids=category_ids,
        )

    def read_e2_product_details(
        self,
        *,
        shop_id: str,
        product_ids: list[str],
    ) -> dict[str, Any]:
        """Return current-session edit-page reads unchanged."""

        return self.login_flow.read_e2_product_details(
            shop_id=shop_id,
            product_ids=product_ids,
        )

    def open_data_acquisition(self) -> dict[str, Any]:
        return self._result(
            'open_data_acquisition',
            self.login_flow.navigate_post_login('data_acquisition'),
            before_values={'requested_page_identity': 'data_acquisition'},
        )

    def claim_from_data_acquisition(
        self,
        claim_mark: str,
        product_query: str | None = None,
        category_name: str | None = None,
        store_name: str | None = None,
        target_source_urls: list[str] | None = None,
    ) -> dict[str, Any]:
        return self._result(
            'claim_from_data_acquisition',
            self.login_flow.claim_from_data_acquisition(
                claim_mark=claim_mark,
                product_query=product_query,
                category_name=category_name,
                store_name=store_name,
                target_source_urls=target_source_urls,
            ),
            before_values={
                'claim_mark': claim_mark,
                'product_query': product_query,
                'category_name': category_name,
                'store_name': store_name,
                'target_source_urls': list(target_source_urls or []),
            },
        )

    def verify_draft_box_claim(
        self,
        claim_mark: str,
        product_query: str | None = None,
        category_name: str | None = None,
        store_name: str | None = None,
        target_source_urls: list[str] | None = None,
    ) -> dict[str, Any]:
        return self._result(
            'verify_draft_box_claim',
            self.login_flow.verify_draft_box_claim(
                claim_mark=claim_mark,
                product_query=product_query,
                category_name=category_name,
                store_name=store_name,
                target_source_urls=target_source_urls,
            ),
            before_values={
                'claim_mark': claim_mark,
                'product_query': product_query,
                'category_name': category_name,
                'store_name': store_name,
                'target_source_urls': list(target_source_urls or []),
            },
        )

    def claim_product(
        self,
        note_text: str,
        product_query: str | None = None,
        store_name: str | None = None,
        target_source_urls: list[str] | None = None,
        target_identity: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        target_identity = self._require_frozen_target_identity(
            'claim_product', target_identity, store_name
        )
        return self._result(
            'claim_product',
            self.login_flow.perform_draft_box_action(
                'remark',
                note_text,
                product_query=product_query,
                store_name=store_name,
                target_source_urls=target_source_urls,
                target_identity=target_identity,
            ),
            before_values={
                'note_text': note_text,
                'product_query': product_query,
                'store_name': store_name,
                'target_source_urls': list(target_source_urls or []),
                'target_identity': dict(target_identity),
            },
        )

    def open_editor(
        self,
        product_query: str | None = None,
        store_name: str | None = None,
        note_text: str | None = None,
        target_source_urls: list[str] | None = None,
        target_identity: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        target_identity = self._require_frozen_target_identity(
            'open_editor', target_identity, store_name
        )
        return self._result(
            'open_editor',
            self.login_flow.perform_draft_box_action(
                'edit',
                note_text,
                product_query=product_query,
                store_name=store_name,
                target_source_urls=target_source_urls,
                target_identity=target_identity,
            ),
            before_values={
                'note_text': note_text,
                'product_query': product_query,
                'store_name': store_name,
                'target_source_urls': list(target_source_urls or []),
                'target_identity': _mapping_copy(target_identity),
            },
        )

    def enable_semi_managed(
        self,
        product_query: str | None = None,
        store_name: str | None = None,
        target_identity: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        target_identity = self._require_frozen_target_identity(
            'enable_semi_managed', target_identity, store_name
        )
        return self._result(
            'enable_semi_managed',
            self.login_flow.perform_editor_action(
                'enable_semi_managed',
                product_query=product_query,
                store_name=store_name,
                target_identity=target_identity,
            ),
            before_values={
                'product_query': product_query,
                'store_name': store_name,
                'target_identity': _mapping_copy(target_identity),
            },
        )

    def fill_editor_required_defaults(
        self,
        defaults: dict[str, Any] | None = None,
        product_query: str | None = None,
        store_name: str | None = None,
        target_identity: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        target_identity = self._require_frozen_target_identity(
            'fill_editor_required_defaults', target_identity, store_name
        )
        return self._result(
            'fill_editor_required_defaults',
            self.login_flow.perform_editor_action(
                'fill_editor_required_defaults',
                defaults=defaults,
                product_query=product_query,
                store_name=store_name,
                target_identity=target_identity,
            ),
            before_values={
                'defaults': dict(defaults or {}),
                'product_query': product_query,
                'store_name': store_name,
                'target_identity': _mapping_copy(target_identity),
            },
        )

    def fill_media_assets(
        self,
        defaults: dict[str, Any] | None = None,
        product_query: str | None = None,
        store_name: str | None = None,
        target_identity: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        target_identity = self._require_frozen_target_identity(
            'fill_media_assets', target_identity, store_name
        )
        return self._result(
            'fill_media_assets',
            self.login_flow.perform_editor_action(
                'fill_media_assets',
                defaults=defaults,
                product_query=product_query,
                store_name=store_name,
                target_identity=target_identity,
            ),
            before_values={
                'defaults': dict(defaults or {}),
                'product_query': product_query,
                'store_name': store_name,
                'target_identity': _mapping_copy(target_identity),
            },
        )

    def verify_edit_ownership(
        self,
        product_query: str | None = None,
        store_name: str | None = None,
        target_source_urls: list[str] | None = None,
        target_identity: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        target_identity = self._require_frozen_target_identity(
            'verify_edit_ownership', target_identity, store_name
        )
        return self._result(
            'verify_edit_ownership',
            self.login_flow.perform_editor_action(
                'verify_edit_ownership',
                product_query=product_query,
                store_name=store_name,
                target_source_urls=target_source_urls,
                target_identity=target_identity,
            ),
            before_values={
                'product_query': product_query,
                'store_name': store_name,
                'target_source_urls': list(target_source_urls or []),
                'target_identity': _mapping_copy(target_identity),
            },
        )

    def fill_editor_variants(
        self,
        defaults: dict[str, Any] | None = None,
        product_query: str | None = None,
        store_name: str | None = None,
        target_identity: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        target_identity = self._require_frozen_target_identity(
            'fill_editor_variants', target_identity, store_name
        )
        return self._result(
            'fill_editor_variants',
            self.login_flow.perform_editor_action(
                'fill_editor_variants',
                defaults=defaults,
                product_query=product_query,
                store_name=store_name,
                target_identity=target_identity,
            ),
            before_values={
                'defaults': dict(defaults or {}),
                'product_query': product_query,
                'store_name': store_name,
                'target_identity': _mapping_copy(target_identity),
            },
        )

    def fill_compliance_defaults(
        self,
        defaults: dict[str, Any] | None = None,
        product_query: str | None = None,
        store_name: str | None = None,
        target_identity: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        target_identity = self._require_frozen_target_identity(
            'fill_compliance_defaults', target_identity, store_name
        )
        return self._result(
            'fill_compliance_defaults',
            self.login_flow.perform_editor_action(
                'fill_compliance_defaults',
                defaults=defaults,
                product_query=product_query,
                store_name=store_name,
                target_identity=target_identity,
            ),
            before_values={
                'defaults': dict(defaults or {}),
                'product_query': product_query,
                'store_name': store_name,
                'target_identity': _mapping_copy(target_identity),
            },
        )

    def open_semi_managed_page(
        self,
        defaults: dict[str, Any] | None = None,
        product_query: str | None = None,
        store_name: str | None = None,
        target_identity: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        target_identity = self._require_frozen_target_identity(
            'open_semi_managed_page', target_identity, store_name
        )
        return self._result(
            'open_semi_managed_page',
            self.login_flow.perform_editor_action(
                'open_semi_managed_page',
                defaults=defaults,
                product_query=product_query,
                store_name=store_name,
                target_identity=target_identity,
            ),
            before_values={
                'defaults': dict(defaults or {}),
                'product_query': product_query,
                'store_name': store_name,
                'target_identity': _mapping_copy(target_identity),
            },
        )

    def fill_semi_managed_defaults(
        self,
        defaults: dict[str, Any] | None = None,
        product_query: str | None = None,
        store_name: str | None = None,
        target_identity: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        target_identity = self._require_frozen_target_identity(
            'fill_semi_managed_defaults', target_identity, store_name
        )
        return self._result(
            'fill_semi_managed_defaults',
            self.login_flow.perform_editor_action(
                'fill_semi_managed_defaults',
                defaults=defaults,
                product_query=product_query,
                store_name=store_name,
                target_identity=target_identity,
            ),
            before_values={
                'defaults': dict(defaults or {}),
                'product_query': product_query,
                'store_name': store_name,
                'target_identity': _mapping_copy(target_identity),
            },
        )

    def save_only(
        self,
        defaults: dict[str, Any] | None = None,
        product_query: str | None = None,
        store_name: str | None = None,
        target_identity: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        target_identity = self._require_frozen_target_identity(
            'save_only', target_identity, store_name
        )
        return self._result(
            'save_only',
            self.login_flow.perform_editor_action(
                'save_only',
                defaults=defaults,
                product_query=product_query,
                store_name=store_name,
                target_identity=target_identity,
            ),
            before_values={
                'defaults': dict(defaults or {}),
                'product_query': product_query,
                'store_name': store_name,
                'target_identity': dict(target_identity),
            },
        )

    def verify_not_published(
        self,
        product_query: str | None = None,
        store_name: str | None = None,
        target_identity: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        target_identity = self._require_frozen_target_identity(
            'verify_not_published', target_identity, store_name
        )
        return self._result(
            'verify_not_published',
            self.login_flow.perform_editor_action(
                'verify_not_published',
                product_query=product_query,
                store_name=store_name,
                target_identity=target_identity,
            ),
            before_values={
                'product_query': product_query,
                'store_name': store_name,
                'target_identity': dict(target_identity),
            },
        )

    def update_live_hud(self, hud: dict[str, Any]) -> dict[str, Any]:
        updater = getattr(self.login_flow, 'update_live_hud', None)
        if not callable(updater):
            return {'ok': True, 'updated': False, 'reason': 'live_hud_unavailable'}
        return updater(hud)

    def close_browser_session(self) -> None:
        closer = getattr(self.login_flow, '_close_browser_session', None)
        if callable(closer):
            closer()

    def _result(
        self,
        action: str,
        evidence: Any,
        *,
        before_values: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        evidence_map = dict(evidence) if isinstance(evidence, Mapping) else {}
        evidence_map = self._normalize_published_evidence(action, evidence_map)
        stage = evidence_map.get('stage')
        contract_facts = self._build_contract_facts(
            action,
            evidence_map,
            before_values=dict(before_values or {}),
        )
        contract_ok = bool(
            evidence_map.get('ok') is True
            and contract_facts.get('failure_code') is None
        )
        result = {
            **evidence_map,
            'ok': contract_ok,
            'stage': stage,
            'page_title': evidence_map.get('page_title'),
            'page_url': evidence_map.get('page_url'),
            'screenshot_url': evidence_map.get('screenshot_url'),
            'evidence_ref': evidence_map.get('evidence_ref'),
            'action': action,
            'product_query': evidence_map.get('product_query'),
            'store_name': evidence_map.get('store_name'),
            'save_result': evidence_map.get('save_result'),
            'fill_result': evidence_map.get('fill_result'),
            'evidence': evidence_map,
            'contract_facts': contract_facts,
        }
        events = self.recent_workflow_events(240)
        if events:
            result['workflow_events'] = events
        return result

    @classmethod
    def _normalize_published_evidence(
        cls,
        action: str,
        evidence: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Keep ``published`` tri-state and prevent absence-of-proof from becoming false."""

        result = dict(evidence)
        published: bool | None = None
        if action == 'save_only':
            save = _mapping_copy(result.get('save_result'))
            audit = _mapping_copy(save.get('network_audit'))
            receipt = _mapping_copy(save.get('network_save_result'))
            signal = _mapping_copy(save.get('publish_signal'))
            authorization = _mapping_copy(save.get('mutation_authorization'))
            pre_dispatch = _mapping_copy(save.get('pre_dispatch_readback'))
            pre_dispatch_target = _mapping_copy(pre_dispatch.get('exact_save_target'))
            page = _mapping_copy(save.get('page_save_result'))
            transition = _mapping_copy(page.get('status_transition'))
            decision = _mapping_copy(save.get('save_decision'))
            complete_no_publish_save = bool(
                result.get('ok') is True
                and save.get('ok') is True
                and save.get('exact_save_target') is True
                and save.get('clicked') is True
                and save.get('save_click_dispatched') is True
                and save.get('publish_action_clicked') is False
                and save.get('text') == '保存'
                and _strict_int(save.get('exact_save_count')) == 1
                and save.get('click_method') in {'native_exact_save', 'dom_exact_save'}
                and authorization.get('ok') is True
                and authorization.get('executed') is True
                and authorization.get('mutation_action') == 'save_only_click'
                and authorization.get('mutation_status') == 'DISPATCHED'
                and str(authorization.get('mutation_id') or '').strip()
                and pre_dispatch.get('ok') is True
                and pre_dispatch.get('required_readback_complete') is True
                and pre_dispatch.get('write_attempted') is False
                and pre_dispatch.get('phase') == 'before_ledger_begin_dispatch'
                and pre_dispatch_target.get('ok') is True
                and pre_dispatch_target.get('text') == '保存'
                and pre_dispatch_target.get('exact_save_count') == 1
                and isinstance(pre_dispatch.get('identity'), Mapping)
                and pre_dispatch.get('identity')
                and isinstance(pre_dispatch.get('current_field_integrity'), Mapping)
                and pre_dispatch['current_field_integrity'].get('ok') is True
                and _exact_save_receipt(receipt)
                and audit.get('scope') == 'same_origin_write_window'
                and audit.get('complete') is True
                and audit.get('window_closed') is True
                and _strict_int(audit.get('registered_listener_count')) == 2
                and _strict_int(audit.get('removed_listener_count')) == 2
                and _strict_int(audit.get('mutation_request_count')) == 1
                and _strict_int(audit.get('save_request_count')) == 1
                and _strict_int(audit.get('other_mutation_request_count')) == 0
                and _strict_int(audit.get('read_only_schema_request_count')) is not None
                and _strict_int(audit.get('read_only_schema_request_count')) >= 0
                and _strict_int(audit.get('publish_request_count')) == 0
                and signal.get('detected') is False
                and signal.get('kind') == 'network_route_classification'
                and _strict_int(signal.get('request_count')) == 0
                and page.get('ok') is True
                and str(page.get('success_text') or '').strip()
                and transition.get('kind') == 'new_or_changed_structured_save_status'
                and isinstance(transition.get('entry'), Mapping)
                and transition.get('entry')
                and decision == {
                    'ok': True,
                    'rule': 'page_success_and_network_success',
                    'page_ok': True,
                    'network_ok': True,
                    'network_receipt_ok': True,
                    'network_audit_ok': True,
                }
                and save.get('published') is False
            )
            published = False if complete_no_publish_save else None
            save['published'] = published
            result['save_result'] = save
        elif action == 'verify_not_published':
            proof = _mapping_copy(result.get('unpublished_proof'))
            identity = _mapping_copy(proof.get('identity_readback'))
            status = ''.join(str(proof.get('status_text') or proof.get('publish_status') or '').split())
            try:
                proof_page = urlsplit(str(proof.get('page_url') or ''))
            except ValueError:
                proof_page = urlsplit('')
            proof_host = str(proof_page.hostname or '').casefold()
            independent_false = bool(
                result.get('ok') is True
                and proof.get('ok') is True
                and proof.get('verified_on_current_page') is True
                and proof.get('proof_kind') == 'structured_unpublished_status'
                and proof.get('status_scope_unique') is True
                and _strict_int(proof.get('bound_candidate_count')) == 1
                and _strict_int(proof.get('structured_candidate_count')) == 1
                and proof.get('identity_binding_kind') == 'frozen_target_structured_page_readback'
                and re.fullmatch(r'[0-9A-Fa-f]{64}', str(proof.get('target_identity_sha256') or '')) is not None
                and (proof_host == 'dianxiaomi.com' or proof_host.endswith('.dianxiaomi.com'))
                and str(proof_page.path or '').rstrip('/').casefold() == '/web/smt/editfromsmt'
                and identity.get('product_identity_match') is True
                and identity.get('store_identity_match') is True
                and identity.get('source_identity_match') is True
                and proof.get('target_bound') is True
                and proof.get('product_matched') is True
                and proof.get('store_matched') is True
                and proof.get('source_identity_match') is True
                and status in {'待发布', '草稿', '未发布', '待完善'}
                and proof.get('publish_risk_term') in (None, '')
                and proof.get('published') is False
            )
            published = (
                True
                if proof.get('published') is True
                else False if independent_false else None
            )
            proof['published'] = published
            result['unpublished_proof'] = proof

        def rewrite(value: Any) -> Any:
            if isinstance(value, Mapping):
                return {
                    key: published if key == 'published' else rewrite(item)
                    for key, item in value.items()
                }
            if isinstance(value, list):
                return [rewrite(item) for item in value]
            return value

        if action == 'verify_not_published':
            result = {
                key: (
                    published
                    if key == 'published'
                    else rewrite(value)
                    if key in {'unpublished_proof', 'fill_result', 'editor_action_result'}
                    else value
                )
                for key, value in result.items()
            }
        else:
            result = rewrite(result)
        result['published'] = published
        return result

    def _build_contract_facts(
        self,
        action: str,
        evidence: Mapping[str, Any],
        *,
        before_values: dict[str, Any],
    ) -> dict[str, Any]:
        required_names = self._required_postcondition_names(action)
        sources = self._contract_sources(evidence)
        explicit = sources.get('contract_observations') or {}
        explicit_postconditions = (
            explicit.get('postconditions')
            if isinstance(explicit.get('postconditions'), Mapping)
            else {}
        )
        postconditions = {
            name: explicit_postconditions.get(name) is True
            for name in required_names
        }
        for name in required_names:
            if postconditions[name]:
                continue
            postconditions[name] = any(
                self._nested_exact_true(source, name)
                for source in sources.values()
                if isinstance(source, Mapping)
            )

        self._derive_action_postconditions(action, evidence, sources, postconditions)
        if action == 'fill_semi_managed_defaults' and self._contains_deferred_validation(sources):
            postconditions = {name: False for name in required_names}

        after_values = self._after_values(action, sources)
        observations = {
            key: dict(value)
            for key, value in sources.items()
            if isinstance(value, Mapping) and value
        }
        self._augment_action_observations(action, sources, observations)
        if after_values:
            observations[f'{action}_readback'] = dict(after_values)
        for key in ('evidence_ref', 'save_evidence_ref', 'unpublished_evidence_ref'):
            value = evidence.get(key)
            if isinstance(value, Mapping) and value:
                observations[key] = dict(value)

        facts_complete = bool(
            evidence.get('ok') is True
            and self._facts_inputs_complete(action, before_values)
            and self._has_concrete_value(after_values)
            and self._has_concrete_value(observations)
            and postconditions
            and all(postconditions.values())
        )
        failure_code = None if facts_complete else self._failure_code(action, evidence, sources)
        return {
            'before_values': before_values,
            'after_values': after_values,
            'postconditions': postconditions,
            'evidence_observations': observations,
            'failure_code': failure_code,
            'recoverability': self._recoverability(failure_code),
        }

    @staticmethod
    def _required_postcondition_names(action: str) -> tuple[str, ...]:
        contracts = ACTION_RESULT_CONTRACTS.get(action)
        if not contracts:
            return ()
        return tuple(sorted(set().union(*(item.required_postconditions for item in contracts.values()))))

    @staticmethod
    def _contract_sources(evidence: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
        sources: dict[str, dict[str, Any]] = {}
        for key in _CONTRACT_SOURCE_KEYS:
            value = evidence.get(key)
            if isinstance(value, Mapping):
                sources[key] = dict(value)
        return sources

    @classmethod
    def _nested_exact_true(cls, value: Any, key: str) -> bool:
        if not isinstance(value, Mapping):
            return False
        if value.get(key) is True:
            return True
        return any(
            cls._nested_exact_true(nested, key)
            for nested_key, nested in value.items()
            if nested_key not in {'stage', 'label', 'message', 'next_action', 'reason'}
            and isinstance(nested, Mapping)
        )

    @classmethod
    def _contains_deferred_validation(cls, sources: Mapping[str, Any]) -> bool:
        def contains(value: Any) -> bool:
            if not isinstance(value, Mapping):
                return False
            if value.get('deferred_validation') is True or value.get('deferred') is True:
                return True
            return any(contains(item) for item in value.values() if isinstance(item, Mapping))

        return any(contains(source) for source in sources.values())

    @classmethod
    def _has_concrete_value(cls, value: Any) -> bool:
        if isinstance(value, Mapping):
            return any(cls._has_concrete_value(item) for item in value.values())
        if isinstance(value, (list, tuple)):
            return any(cls._has_concrete_value(item) for item in value)
        return value is not None and value != ''

    @classmethod
    def _facts_inputs_complete(cls, action: str, before_values: Mapping[str, Any]) -> bool:
        if not cls._has_concrete_value(before_values):
            return False
        if action in {'claim_from_data_acquisition', 'verify_draft_box_claim'}:
            source_urls = before_values.get('target_source_urls')
            return bool(
                str(before_values.get('claim_mark') or '').strip()
                and str(before_values.get('store_name') or '').strip()
                and isinstance(source_urls, list)
                and source_urls
                and all(isinstance(value, str) and value.strip() for value in source_urls)
            )
        if action not in _FROZEN_TARGET_REQUIRED_ACTIONS:
            return True
        target = before_values.get('target_identity')
        if isinstance(target, Mapping) and target.get('schema_version') == 'dxm_draft_box_target.v1':
            store_name = before_values.get('store_name')
            if not isinstance(store_name, str) or not store_name.strip():
                return False
            try:
                canonical = canonical_frozen_target_identity(dict(target), store_name=store_name)
            except (TypeError, ValueError):
                return False
            return bool(canonical and canonical.get('source_urls'))
        return False

    @staticmethod
    def _after_values(action: str, sources: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
        explicit = sources.get('contract_observations') or {}
        explicit_after = explicit.get('after_values')
        if isinstance(explicit_after, Mapping) and explicit_after:
            return dict(explicit_after)
        if action == 'check_login_state':
            probe = sources.get('login_check') or sources.get('live_probe') or {}
            return {'session_probe': dict(probe)} if probe else {}
        if action in {'open_data_acquisition', 'open_draft_box'}:
            wait = sources.get('wait_result') or {}
            if not wait and isinstance((sources.get('navigation_result') or {}).get('wait_result'), Mapping):
                wait = dict((sources.get('navigation_result') or {})['wait_result'])
            readiness = wait.get('readiness') if isinstance(wait.get('readiness'), Mapping) else {}
            return {
                'observed_page_identity': readiness.get('expected_identity') or wait.get('expected_identity'),
                'business_marker': readiness.get('business_marker') or wait.get('ready_term'),
                'loading': readiness.get('loading') if 'loading' in readiness else wait.get('loading'),
                'blocking_modal': readiness.get('blocking_modal'),
                'readiness': dict(readiness),
            }
        if action == 'save_only':
            save = sources.get('save_result') or {}
            return {
                'mutation_authorization': _mapping_copy(save.get('mutation_authorization')),
                'pre_dispatch_readback': _mapping_copy(save.get('pre_dispatch_readback')),
                'exact_save_target': bool(
                    save.get('exact_save_target') is True
                    or (
                        str(save.get('text') or '') == '保存'
                        and save.get('exact_save_count') == 1
                    )
                ),
                'save_click_dispatched': (
                    True
                    if save.get('save_click_dispatched') is True or save.get('clicked') is True
                    else False if save.get('save_click_dispatched') is False or save.get('clicked') is False
                    else None
                ),
                'network_save_result': _mapping_copy(save.get('network_save_result')),
                'network_audit': _mapping_copy(save.get('network_audit')),
                'publish_signal': _mapping_copy(save.get('publish_signal')),
                'page_save_result': _mapping_copy(save.get('page_save_result')),
                'published': save.get('published'),
            }
        if action == 'verify_not_published':
            proof = sources.get('unpublished_proof') or {}
            return {
                'fresh_probe': dict(proof),
                'target_identity': {
                    'product_matched': proof.get('product_matched'),
                    'store_matched': proof.get('store_matched'),
                    'source_identity_match': proof.get('source_identity_match'),
                    'target_bound': proof.get('target_bound'),
                    'target_identity_sha256': proof.get('target_identity_sha256'),
                },
                'publish_status': proof.get('status_text') or proof.get('publish_status'),
                'identity_readback': _mapping_copy(proof.get('identity_readback')),
                'published': proof.get('published'),
            }
        if action == 'verify_draft_box_claim':
            verification = sources.get('verification_result') or {}
            return {
                'claimed_product': _mapping_copy(verification.get('claimed_product')),
                'draft_box_match': _mapping_copy(verification.get('draft_box_match')),
                'claim_target': _mapping_copy(verification.get('claim_target')),
                'search_result': _mapping_copy(verification.get('search_result')),
            }
        if action == 'claim_from_data_acquisition':
            claim = sources.get('claim_result') or {}
            dialog = claim.get('claim_dialog') if isinstance(claim.get('claim_dialog'), Mapping) else {}
            click_receipt = claim.get('claim_click_receipt') if isinstance(claim.get('claim_click_receipt'), Mapping) else {}
            confirm_receipt = dialog.get('submit_click_receipt') if isinstance(dialog.get('submit_click_receipt'), Mapping) else {}
            return {
                'claim_target': _mapping_copy(claim.get('claim_target')),
                'claim_dialog': dict(dialog),
                'claim_click_dispatched': click_receipt.get('dispatched'),
                'claim_confirm_dispatched': confirm_receipt.get('dispatched'),
                'published': claim.get('published'),
            }
        if action == 'claim_product':
            raw = sources.get('draft_action_result') or {}
            return {
                'target_selection': {
                    'target_unique': raw.get('target_unique'),
                    'ownership_binding_match': raw.get('ownership_binding_match'),
                },
                'note_write_attempted': raw.get('note_write_attempted'),
                'note_readback': {
                    'verified': raw.get('note_verified'),
                    'note_text': raw.get('note_text'),
                    'target_row_text': raw.get('target_row_text'),
                },
            }
        if action == 'open_editor':
            raw = sources.get('draft_action_result') or {}
            return {
                'editor_readiness': _mapping_copy(raw.get('readiness')),
                'target_identity_readback': {
                    'product_identity_match': raw.get('product_identity_match'),
                    'store_identity_match': raw.get('store_identity_match', raw.get('store_match')),
                    'store_match': raw.get('store_match', raw.get('store_identity_match')),
                    'source_identity_match': raw.get('source_identity_match'),
                    'target_identity_sha256': raw.get('target_identity_sha256'),
                    'evidence': _mapping_copy(raw.get('target_identity_evidence')),
                },
            }
        if action == 'verify_edit_ownership':
            return {'ownership_readback': dict(sources.get('fill_result') or {})}
        if action == 'fill_editor_required_defaults':
            return {'base_info_readback': dict(sources.get('fill_result') or {})}
        if action == 'fill_editor_variants':
            return {'variant_readback': dict(sources.get('fill_result') or {})}
        if action == 'fill_media_assets':
            return {'media_readback': dict(sources.get('fill_result') or {})}
        if action == 'fill_compliance_defaults':
            return {'compliance_readback': dict(sources.get('fill_result') or {})}
        if action == 'enable_semi_managed':
            raw = sources.get('editor_action_result') or {}
            return {
                'semi_managed_toggle_readback': {
                    'visible': raw.get('semi_managed_visible'),
                    'enabled': raw.get('semi_managed_enabled'),
                    'preserved_existing': raw.get('preserved_existing_visible_editor_values'),
                }
            }
        if action == 'open_semi_managed_page':
            return {
                'semi_managed_navigation_readback': dict(sources.get('editor_action_result') or {})
            }
        if action == 'fill_semi_managed_defaults':
            return {
                'goods_and_variant_readback': dict(sources.get('fill_result') or {})
            }
        preferred = {
            'check_login_state': ('login_check', 'live_probe'),
            'open_data_acquisition': ('wait_result', 'navigation_result'),
            'open_draft_box': ('wait_result', 'navigation_result'),
            'claim_from_data_acquisition': ('claim_result',),
            'verify_draft_box_claim': ('verification_result',),
            'claim_product': ('draft_action_result',),
            'open_editor': ('draft_action_result',),
            'verify_edit_ownership': ('fill_result', 'editor_action_result'),
            'fill_editor_required_defaults': ('fill_result', 'editor_action_result'),
            'fill_editor_variants': ('fill_result', 'editor_action_result'),
            'fill_media_assets': ('fill_result', 'editor_action_result'),
            'fill_compliance_defaults': ('fill_result', 'editor_action_result'),
            'enable_semi_managed': ('editor_action_result',),
            'open_semi_managed_page': ('editor_action_result',),
            'fill_semi_managed_defaults': ('fill_result', 'editor_action_result'),
            'save_only': ('save_result',),
            'verify_not_published': ('unpublished_proof',),
        }.get(action, ())
        return {
            key: dict(sources[key])
            for key in preferred
            if key in sources and sources[key]
        }

    @staticmethod
    def _augment_action_observations(
        action: str,
        sources: Mapping[str, dict[str, Any]],
        observations: dict[str, Any],
    ) -> None:
        if action == 'save_only':
            save = sources.get('save_result') or {}
            observations.update({
                'mutation_authorization': _mapping_copy(save.get('mutation_authorization')),
                'pre_dispatch_readback': _mapping_copy(save.get('pre_dispatch_readback')),
                'exact_save_target': {
                    'text': save.get('text'),
                    'exact_save_count': save.get('exact_save_count'),
                    'click_method': save.get('click_method'),
                },
                'save_click_dispatched': (
                    True
                    if save.get('save_click_dispatched') is True or save.get('clicked') is True
                    else False if save.get('save_click_dispatched') is False or save.get('clicked') is False
                    else None
                ),
                'network_save_result': _mapping_copy(save.get('network_save_result')),
                'network_audit': _mapping_copy(save.get('network_audit')),
                'publish_signal': _mapping_copy(save.get('publish_signal')),
                'page_save_result': _mapping_copy(save.get('page_save_result')),
            })
        elif action == 'claim_from_data_acquisition':
            claim = sources.get('claim_result') or {}
            dialog = claim.get('claim_dialog') if isinstance(claim.get('claim_dialog'), Mapping) else {}
            claim_click_receipt = _mapping_copy(claim.get('claim_click_receipt'))
            confirm_click_receipt = _mapping_copy(dialog.get('submit_click_receipt'))
            observations.update({
                'claim_click_receipt': claim_click_receipt,
                'claim_confirm_click_receipt': confirm_click_receipt,
                'claim_click_dispatched': claim_click_receipt.get('dispatched'),
                'claim_confirm_dispatched': confirm_click_receipt.get('dispatched'),
            })
        elif action == 'verify_not_published':
            proof = sources.get('unpublished_proof') or {}
            observations.update({
                'fresh_probe': dict(proof),
                'target_identity': {
                    'product_matched': proof.get('product_matched'),
                    'store_matched': proof.get('store_matched'),
                    'source_identity_match': proof.get('source_identity_match'),
                    'target_bound': proof.get('target_bound'),
                    'target_identity_sha256': proof.get('target_identity_sha256'),
                },
                'identity_readback': _mapping_copy(proof.get('identity_readback')),
            })
        elif action == 'verify_draft_box_claim':
            verification = sources.get('verification_result') or {}
            observations.update({
                'claimed_product': _mapping_copy(verification.get('claimed_product')),
                'draft_box_match': _mapping_copy(verification.get('draft_box_match')),
                'claim_target': _mapping_copy(verification.get('claim_target')),
                'search_result': _mapping_copy(verification.get('search_result')),
            })

    def _derive_action_postconditions(
        self,
        action: str,
        evidence: Mapping[str, Any],
        sources: Mapping[str, dict[str, Any]],
        postconditions: dict[str, bool],
    ) -> None:
        if action == 'check_login_state':
            self._derive_login_postconditions(sources, postconditions)
        elif action in {'open_data_acquisition', 'open_draft_box'}:
            expected = 'data_acquisition' if action == 'open_data_acquisition' else 'draft_box'
            self._derive_navigation_postconditions(sources, postconditions, expected)
        elif action == 'claim_from_data_acquisition':
            self._derive_acquisition_claim_postconditions(evidence, sources, postconditions)
        elif action == 'verify_draft_box_claim':
            self._derive_draft_verification_postconditions(evidence, sources, postconditions)
        elif action == 'claim_product':
            self._derive_claim_product_postconditions(evidence, sources, postconditions)
        elif action == 'open_editor':
            self._derive_open_editor_postconditions(evidence, sources, postconditions)
        elif action == 'verify_edit_ownership':
            self._derive_edit_ownership_postconditions(sources, postconditions)
        elif action == 'fill_editor_required_defaults':
            self._derive_base_defaults_postconditions(sources, postconditions)
        elif action == 'fill_editor_variants':
            self._derive_variant_postconditions(sources, postconditions)
        elif action == 'fill_media_assets':
            self._derive_media_postconditions(sources, postconditions)
        elif action == 'fill_compliance_defaults':
            self._derive_compliance_postconditions(sources, postconditions)
        elif action == 'enable_semi_managed':
            editor = sources.get('editor_action_result') or {}
            postconditions['semi_managed_visible'] |= editor.get('semi_managed_visible') is True
            postconditions['semi_managed_enabled'] |= editor.get('semi_managed_enabled') is True
            postconditions['toggle_readback_exact'] |= bool(
                editor.get('semi_managed_visible') is True
                and editor.get('semi_managed_enabled') is True
                and editor.get('preserved_existing_visible_editor_values') is not True
            )
            postconditions['publish_not_attempted'] |= (
                editor.get('publish_action_attempted') is False
            )
        elif action == 'open_semi_managed_page':
            self._derive_open_semi_postconditions(sources, postconditions)
        elif action == 'fill_semi_managed_defaults':
            self._derive_semi_defaults_postconditions(sources, postconditions)
        elif action == 'save_only':
            self._derive_save_postconditions(evidence, sources, postconditions)
        elif action == 'verify_not_published':
            self._derive_unpublished_postconditions(evidence, sources, postconditions)

    @staticmethod
    def _derive_login_postconditions(
        sources: Mapping[str, dict[str, Any]],
        postconditions: dict[str, bool],
    ) -> None:
        candidates = [sources.get('login_check') or {}, sources.get('live_probe') or {}]
        for candidate in candidates:
            product_page = candidate.get('product_page') if isinstance(candidate.get('product_page'), Mapping) else {}
            postconditions['session_authenticated'] |= any(
                candidate.get(key) is True
                for key in ('session_authenticated', 'authenticated', 'logged_in', 'visible_logged_in')
            )
            postconditions['business_page_ready'] |= bool(
                candidate.get('business_page_ready') is True
                or candidate.get('ready') is True
                or product_page.get('ready') is True
                or product_page.get('business_page_ready') is True
            )
            postconditions['loading_absent'] |= bool(
                candidate.get('loading') is False
                or product_page.get('loading') is False
            )

    @staticmethod
    def _derive_navigation_postconditions(
        sources: Mapping[str, dict[str, Any]],
        postconditions: dict[str, bool],
        expected_identity: str,
    ) -> None:
        wait = sources.get('wait_result') or {}
        if not wait and isinstance((sources.get('navigation_result') or {}).get('wait_result'), Mapping):
            wait = dict((sources.get('navigation_result') or {})['wait_result'])
        readiness = wait.get('readiness') if isinstance(wait.get('readiness'), Mapping) else {}
        exact_identity = bool(
            wait.get('ready') is True
            and wait.get('expected_identity') == expected_identity
            and readiness.get('ok') is True
            and readiness.get('expected_identity') == expected_identity
        )
        postconditions['expected_page'] = exact_identity
        postconditions['business_marker_present'] = bool(
            exact_identity
            and str(readiness.get('business_marker') or '').strip()
        )
        postconditions['loading_absent'] = bool(
            exact_identity
            and wait.get('loading') is False
            and readiness.get('loading') is False
        )
        postconditions['blocking_modal_absent'] = bool(
            exact_identity
            and 'blocking_modal' in readiness
            and readiness.get('blocking_modal') in (None, False, '')
        )

    @staticmethod
    def _derive_acquisition_claim_postconditions(
        evidence: Mapping[str, Any],
        sources: Mapping[str, dict[str, Any]],
        postconditions: dict[str, bool],
    ) -> None:
        raw = sources.get('claim_result') or evidence
        target = raw.get('claim_target') if isinstance(raw.get('claim_target'), Mapping) else {}
        dialog = raw.get('claim_dialog') if isinstance(raw.get('claim_dialog'), Mapping) else {}
        store_selection = dialog.get('store_selection') if isinstance(dialog.get('store_selection'), Mapping) else {}
        safety = raw.get('claim_click_safety') if isinstance(raw.get('claim_click_safety'), Mapping) else {}
        claim_click_receipt = raw.get('claim_click_receipt') if isinstance(raw.get('claim_click_receipt'), Mapping) else {}
        claim_authorization = (
            claim_click_receipt.get('authorization')
            if isinstance(claim_click_receipt.get('authorization'), Mapping)
            else {}
        )
        confirm_click_receipt = (
            dialog.get('submit_click_receipt')
            if isinstance(dialog.get('submit_click_receipt'), Mapping)
            else {}
        )
        confirm_authorization = (
            confirm_click_receipt.get('authorization')
            if isinstance(confirm_click_receipt.get('authorization'), Mapping)
            else {}
        )
        postconditions['target_unique'] = bool(
            target.get('ok') is True
            and isinstance(target.get('actionRect'), Mapping)
            and str(target.get('matchedBy') or '').strip()
        )
        postconditions['source_identity_match'] = bool(
            target.get('matchedBy') == 'source_url'
            and target.get('sourceUrls')
        )
        requested_store = ' '.join(str(store_selection.get('requested_store_name') or '').split()).casefold()
        observed_store = ' '.join(str(store_selection.get('observed_store_name') or '').split()).casefold()
        selected_names = [
            ' '.join(str(value or '').split()).casefold()
            for value in store_selection.get('selected_store_names') or []
            if str(value or '').strip()
        ]
        postconditions['store_selected_exact'] = bool(
            store_selection.get('selected') is True
            and requested_store
            and observed_store == requested_store
            and selected_names == [requested_store]
        )
        requested_category = str(raw.get('category_name') or '').strip()
        clicked_options = [str(value).strip() for value in dialog.get('clicked_options') or []]
        postconditions['category_selected_exact'] = bool(
            requested_category and requested_category in clicked_options
        )
        postconditions['claim_dispatched'] = bool(
            dialog.get('submitted') is True
            and safety.get('ok') is True
            and claim_click_receipt.get('dispatched') is True
            and claim_authorization.get('ok') is True
            and claim_authorization.get('executed') is True
            and claim_authorization.get('mutation_action') == 'claim_open_dialog_click'
            and confirm_click_receipt.get('dispatched') is True
            and confirm_authorization.get('ok') is True
            and confirm_authorization.get('executed') is True
            and confirm_authorization.get('mutation_action') == 'claim_confirm_click'
        )
        postconditions['publish_not_attempted'] = safety.get('publish_action_attempted') is False

    @staticmethod
    def _derive_draft_verification_postconditions(
        evidence: Mapping[str, Any],
        sources: Mapping[str, dict[str, Any]],
        postconditions: dict[str, bool],
    ) -> None:
        raw = sources.get('verification_result') or evidence
        match = raw.get('draft_box_match') if isinstance(raw.get('draft_box_match'), Mapping) else {}
        postconditions['draft_box_verified'] |= bool(match and raw.get('evidence_ref'))
        postconditions['target_unique'] |= bool(match.get('matched_by') and match.get('matched_value'))
        postconditions['product_identity_match'] |= bool(match.get('matched_by') and match.get('matched_value'))
        postconditions['store_match'] |= bool(
            match.get('store_name') and isinstance(match.get('store_evidence'), Mapping)
        )
        postconditions['source_identity_match'] |= bool(
            match.get('matched_by') == 'source_url' and match.get('source_urls')
        )
        claim_mark = str(raw.get('claim_mark') or '').strip()
        row_text = str(match.get('row_text') or raw.get('target_row_text') or '')
        postconditions['claim_mark_match'] |= bool(claim_mark and claim_mark in row_text)

    @staticmethod
    def _derive_claim_product_postconditions(
        evidence: Mapping[str, Any],
        sources: Mapping[str, dict[str, Any]],
        postconditions: dict[str, bool],
    ) -> None:
        raw = sources.get('draft_action_result') or evidence
        note_text = str(raw.get('note_text') or '').strip()
        row_text = str(raw.get('target_row_text') or '')
        postconditions['target_unique'] |= raw.get('target_unique') is True
        postconditions['note_write_attempted'] |= raw.get('note_write_attempted') is True
        postconditions['note_readback_exact'] |= bool(
            raw.get('note_verified') is True and note_text and note_text in row_text
        )
        postconditions['ownership_binding_match'] |= raw.get('ownership_binding_match') is True

    @staticmethod
    def _derive_open_editor_postconditions(
        evidence: Mapping[str, Any],
        sources: Mapping[str, dict[str, Any]],
        postconditions: dict[str, bool],
    ) -> None:
        raw = sources.get('draft_action_result') or evidence
        readiness = raw.get('readiness') if isinstance(raw.get('readiness'), Mapping) else {}
        postconditions['expected_editor_page'] |= bool(
            readiness.get('ok') is True and readiness.get('expected_identity') == 'editor'
        )
        postconditions['editor_ready'] |= readiness.get('editor_ready') is True
        postconditions['product_identity_match'] |= raw.get('product_identity_match') is True
        postconditions['store_match'] |= bool(
            raw.get('store_identity_match') is True or raw.get('store_match') is True
        )
        postconditions['source_identity_match'] |= raw.get('source_identity_match') is True

    @staticmethod
    def _derive_edit_ownership_postconditions(
        sources: Mapping[str, dict[str, Any]],
        postconditions: dict[str, bool],
    ) -> None:
        fill = sources.get('fill_result') or {}
        postconditions['editor_identity_match'] |= fill.get('has_editor_signals') is True
        postconditions['product_identity_match'] |= fill.get('product_identity_match') is True
        postconditions['store_match'] |= fill.get('store_identity_match') is True
        postconditions['source_identity_match'] |= fill.get('source_identity_match') is True

    @classmethod
    def _exact_readback_detail(cls, value: Any) -> bool:
        if not isinstance(value, Mapping):
            return False
        expected = value.get('expected_value')
        observed = value.get('value_after')
        return bool(
            value.get('ok') is True
            and value.get('located') is True
            and cls._has_concrete_value(expected)
            and cls._has_concrete_value(observed)
            and str(expected) == str(observed)
        )

    @classmethod
    def _exact_readback_group(cls, value: Any) -> bool:
        if not isinstance(value, Mapping):
            return False
        rows = value.get('values')
        return bool(
            isinstance(rows, list)
            and rows
            and value.get('matched') == len(rows)
            and value.get('filled') == len(rows)
            and all(cls._exact_readback_detail(row) for row in rows)
        )

    @classmethod
    def _derive_base_defaults_postconditions(
        cls,
        sources: Mapping[str, dict[str, Any]],
        postconditions: dict[str, bool],
    ) -> None:
        for name in postconditions:
            postconditions[name] = False
        fill = sources.get('fill_result') or {}
        details = fill.get('field_details') if isinstance(fill.get('field_details'), Mapping) else {}
        title_exact = cls._exact_readback_detail(details.get('title'))
        category_exact = cls._exact_readback_detail(fill.get('category'))
        required_field_names = (
            'title',
            'declared_value',
            'stock',
            'weight',
            'length',
            'width',
            'height',
            'delivery_days',
            'gross_weight',
            'sku_code',
        )
        fields_exact = all(cls._exact_readback_detail(details.get(name)) for name in required_field_names)
        template_results = (
            fill.get('dxm_reference_template_results')
            if isinstance(fill.get('dxm_reference_template_results'), Mapping)
            else {}
        )
        configured_templates = [
            result
            for result in template_results.values()
            if isinstance(result, Mapping) and result.get('names')
        ]
        templates_exact = bool(
            configured_templates
            and all(cls._exact_readback_detail(result) for result in configured_templates)
        )
        required_select_names = (
            'category',
            'original_box',
            'logistics_attribute',
            'tax_quote',
            'freight_template',
            'service_template',
            'customs_supervision',
        )
        selects_exact = all(
            cls._exact_readback_detail(fill.get(name)) for name in required_select_names
        )
        postconditions['title_readback_nonempty'] = bool(
            title_exact and str(details['title'].get('value_after') or '').strip()
        )
        postconditions['title_readback_exact'] = title_exact
        postconditions['category_selected_exact'] = category_exact
        postconditions['required_templates_resolved'] = templates_exact
        postconditions['required_fields_complete'] = bool(
            fields_exact
            and selects_exact
            and templates_exact
            and fill.get('missing') == []
        )

    @classmethod
    def _derive_variant_postconditions(
        cls,
        sources: Mapping[str, dict[str, Any]],
        postconditions: dict[str, bool],
    ) -> None:
        for name in postconditions:
            postconditions[name] = False
        fill = sources.get('fill_result') or {}
        sku_exact = cls._exact_readback_group(fill.get('sku'))
        price_exact = cls._exact_readback_group(fill.get('retail_price'))
        stock_exact = cls._exact_readback_group(fill.get('stock'))
        required_groups = (
            'sku',
            'retail_price',
            'declared_value',
            'stock',
            'weight',
            'length',
            'width',
            'height',
        )
        groups_exact = all(cls._exact_readback_group(fill.get(name)) for name in required_groups)
        original_box = fill.get('variant_original_box')
        original_box_exact = cls._exact_readback_group(original_box)
        logistics = fill.get('logistics_attribute_verify') or fill.get('logistics_attribute_detail')
        logistics_exact = cls._exact_readback_detail(logistics)
        variant_rows_present = bool(
            sku_exact
            and price_exact
            and stock_exact
            and isinstance(fill.get('sku'), Mapping)
            and int(fill['sku'].get('matched') or 0) > 0
        )
        postconditions['variant_rows_present'] = variant_rows_present
        postconditions['sku_readback_exact'] = sku_exact
        postconditions['price_readback_exact'] = price_exact
        postconditions['stock_readback_exact'] = stock_exact
        postconditions['all_required_cells_complete'] = bool(
            variant_rows_present
            and groups_exact
            and original_box_exact
            and logistics_exact
            and fill.get('missing') == []
        )

    @classmethod
    def _derive_media_postconditions(
        cls,
        sources: Mapping[str, dict[str, Any]],
        postconditions: dict[str, bool],
    ) -> None:
        for name in postconditions:
            postconditions[name] = False
        fill = sources.get('fill_result') or {}
        slots = fill.get('image_slots')
        exact_slots = []
        if isinstance(slots, list):
            for slot in slots:
                verified = slot.get('verified') if isinstance(slot, Mapping) else None
                exact_slots.append(bool(
                    isinstance(slot, Mapping)
                    and str(slot.get('filename') or '').strip()
                    and cls._exact_readback_detail(verified)
                    and int(verified.get('filled_image_count') or 0) > 0
                    and slot.get('deferred') is not True
                ))
        all_slots_exact = bool(exact_slots and all(exact_slots))
        marketing = fill.get('marketing_images') if isinstance(fill.get('marketing_images'), Mapping) else {}
        marketing_complete = bool(
            marketing.get('skipped') is True and marketing.get('reason') == 'not_configured'
            or (
                marketing.get('ok') is True
                and isinstance(marketing.get('items'), list)
                and marketing.get('items')
                and all(
                    isinstance(item, Mapping)
                    and item.get('has_image') is True
                    and isinstance(item.get('dimensions'), Mapping)
                    for item in marketing['items']
                )
            )
        )
        postconditions['main_images_present'] = all_slots_exact
        postconditions['required_assets_match'] = all_slots_exact
        postconditions['invalid_images_absent'] = all_slots_exact
        postconditions['marketing_assets_complete'] = marketing_complete

    @classmethod
    def _derive_compliance_postconditions(
        cls,
        sources: Mapping[str, dict[str, Any]],
        postconditions: dict[str, bool],
    ) -> None:
        for name in postconditions:
            postconditions[name] = False
        fill = sources.get('fill_result') or {}
        eu_exact = cls._exact_readback_detail(fill.get('eu_responsible'))
        manufacturer_exact = cls._exact_readback_detail(fill.get('manufacturer'))
        customs_exact = cls._exact_readback_detail(fill.get('customs_supervision'))
        template_results = (
            fill.get('dxm_reference_template_results')
            if isinstance(fill.get('dxm_reference_template_results'), Mapping)
            else {}
        )
        configured = [
            result for result in template_results.values()
            if isinstance(result, Mapping) and result.get('names')
        ]
        templates_exact = bool(
            configured and all(cls._exact_readback_detail(result) for result in configured)
        )
        postconditions['eu_responsible_readback_exact'] = eu_exact
        postconditions['manufacturer_readback_exact'] = manufacturer_exact
        postconditions['customs_readback_exact'] = customs_exact
        postconditions['required_templates_applied'] = templates_exact
        postconditions['required_compliance_complete'] = bool(
            eu_exact
            and manufacturer_exact
            and customs_exact
            and templates_exact
            and fill.get('missing') == []
        )

    @staticmethod
    def _derive_open_semi_postconditions(
        sources: Mapping[str, dict[str, Any]],
        postconditions: dict[str, bool],
    ) -> None:
        raw = sources.get('editor_action_result') or {}
        readiness = raw.get('readiness') if isinstance(raw.get('readiness'), Mapping) else {}
        exact = bool(readiness.get('ok') is True and readiness.get('expected_identity') == 'semi_managed')
        postconditions['expected_semi_managed_page'] |= exact
        postconditions['business_marker_present'] |= bool(exact and readiness.get('business_marker'))
        postconditions['loading_absent'] |= bool(exact and readiness.get('loading') is False)
        postconditions['source_editor_identity_preserved'] |= (
            raw.get('source_editor_identity_preserved') is True
        )

    @staticmethod
    def _derive_semi_defaults_postconditions(
        sources: Mapping[str, dict[str, Any]],
        postconditions: dict[str, bool],
    ) -> None:
        fill = sources.get('fill_result') or {}
        details = fill.get('field_details') if isinstance(fill.get('field_details'), Mapping) else {}

        # These facts are deliberately rebuilt from per-field structured
        # readback.  Boolean summaries (including a producer saying every
        # postcondition is true) are not proof that the page now contains the
        # requested value.
        for name in postconditions:
            postconditions[name] = False

        def concrete(value: Any) -> bool:
            if isinstance(value, Mapping):
                return bool(value) and any(concrete(item) for item in value.values())
            if isinstance(value, (list, tuple)):
                return bool(value) and all(concrete(item) for item in value)
            if isinstance(value, str):
                return bool(value.strip())
            return value is not None

        def detail_exact(field: Mapping[str, Any]) -> bool:
            value_after = field.get('value_after')
            expected_value = field.get('expected_value')
            return bool(
                field.get('ok') is True
                and field.get('located') is True
                and 'value_after' in field
                and 'expected_value' in field
                and concrete(value_after)
                and concrete(expected_value)
                and str(value_after) == str(expected_value)
            )

        def exact(*names: str) -> bool:
            return any(
                detail_exact(field)
                for name in names
                if isinstance((field := details.get(name)), Mapping)
            )

        postconditions['weight_readback_exact'] = exact('weight')
        postconditions['dimensions_readback_exact'] = all(
            exact(name) for name in ('length', 'width', 'height')
        )
        logistics = fill.get('logistics_attribute_detail') if isinstance(fill.get('logistics_attribute_detail'), Mapping) else {}
        postconditions['logistics_attribute_readback_exact'] = bool(
            exact('logistics_attribute') or detail_exact(logistics)
        )
        postconditions['freight_template_readback_exact'] = exact('freight_template')
        postconditions['service_template_readback_exact'] = exact('service_template')
        postconditions['required_goods_fields_complete'] = bool(
            postconditions.get('weight_readback_exact')
            and postconditions.get('dimensions_readback_exact')
            and postconditions.get('logistics_attribute_readback_exact')
            and postconditions.get('freight_template_readback_exact')
            and postconditions.get('service_template_readback_exact')
        )
        variant_rows = fill.get('variant_rows')
        postconditions['variant_rows_present'] = bool(
            isinstance(variant_rows, list)
            and any(isinstance(row, Mapping) and row for row in variant_rows)
        )
        postconditions['product_price_readback_exact'] = exact('product_price')
        postconditions['supply_price_readback_exact'] = exact('supply_price')
        postconditions['jit_stock_readback_exact'] = exact('jit_stock', 'stock')
        postconditions['goods_code_readback_exact'] = exact('goods_code', 'sku_code')
        postconditions['required_variant_fields_complete'] = bool(
            postconditions.get('variant_rows_present')
            and postconditions.get('product_price_readback_exact')
            and postconditions.get('supply_price_readback_exact')
            and postconditions.get('jit_stock_readback_exact')
            and postconditions.get('goods_code_readback_exact')
        )

    @staticmethod
    def _derive_save_postconditions(
        evidence: Mapping[str, Any],
        sources: Mapping[str, dict[str, Any]],
        postconditions: dict[str, bool],
    ) -> None:
        save = sources.get('save_result') or {}
        authorization = save.get('mutation_authorization') if isinstance(save.get('mutation_authorization'), Mapping) else {}
        pre_dispatch = save.get('pre_dispatch_readback') if isinstance(save.get('pre_dispatch_readback'), Mapping) else {}
        pre_dispatch_target = pre_dispatch.get('exact_save_target') if isinstance(pre_dispatch.get('exact_save_target'), Mapping) else {}
        network = save.get('network_save_result') if isinstance(save.get('network_save_result'), Mapping) else {}
        network_audit = save.get('network_audit') if isinstance(save.get('network_audit'), Mapping) else {}
        publish_signal = save.get('publish_signal') if isinstance(save.get('publish_signal'), Mapping) else {}
        page = save.get('page_save_result') if isinstance(save.get('page_save_result'), Mapping) else {}
        decision = save.get('save_decision') if isinstance(save.get('save_decision'), Mapping) else {}
        network_message = str(network.get('message') or network.get('msg') or '').strip()
        page_success_text = str(page.get('success_text') or '').strip()
        page_transition = page.get('status_transition') if isinstance(page.get('status_transition'), Mapping) else {}
        network_status = _strict_int(network.get('status'))
        network_status_ok = bool(network_status is not None and 200 <= network_status < 300)
        postconditions['mutation_authorized'] = bool(
            authorization.get('ok') is True
            and authorization.get('executed') is True
            and authorization.get('mutation_action') == 'save_only_click'
            and str(authorization.get('mutation_id') or '').strip()
            and authorization.get('mutation_status') == 'DISPATCHED'
            and pre_dispatch.get('ok') is True
            and pre_dispatch.get('required_readback_complete') is True
            and pre_dispatch.get('write_attempted') is False
            and pre_dispatch.get('phase') == 'before_ledger_begin_dispatch'
            and pre_dispatch_target.get('ok') is True
            and pre_dispatch_target.get('text') == '保存'
            and pre_dispatch_target.get('exact_save_count') == 1
            and isinstance(pre_dispatch.get('identity'), Mapping)
            and pre_dispatch.get('identity')
            and isinstance(pre_dispatch.get('current_field_integrity'), Mapping)
            and pre_dispatch['current_field_integrity'].get('ok') is True
        )
        postconditions['exact_save_target'] = bool(
            save.get('exact_save_target') is True
            and str(save.get('text') or '') == '保存'
            and save.get('exact_save_count') == 1
            and save.get('click_method') in {'native_exact_save', 'dom_exact_save'}
        )
        postconditions['save_click_dispatched'] = save.get('save_click_dispatched') is True
        postconditions['network_save_success'] = bool(
            _exact_save_receipt(network)
            and decision.get('network_ok') is True
            and network_status_ok
            and network_message
            and network_audit.get('scope') == 'same_origin_write_window'
            and network_audit.get('complete') is True
            and network_audit.get('window_closed') is True
            and _strict_int(network_audit.get('registered_listener_count')) == 2
            and _strict_int(network_audit.get('removed_listener_count')) == 2
            and _strict_int(network_audit.get('mutation_request_count')) == 1
            and _strict_int(network_audit.get('save_request_count')) == 1
            and _strict_int(network_audit.get('other_mutation_request_count')) == 0
            and _strict_int(network_audit.get('read_only_schema_request_count')) is not None
            and _strict_int(network_audit.get('read_only_schema_request_count')) >= 0
            and _strict_int(network_audit.get('publish_request_count')) == 0
            and publish_signal.get('detected') is False
            and publish_signal.get('kind') == 'network_route_classification'
            and _strict_int(publish_signal.get('request_count')) == 0
        )
        postconditions['page_save_success'] = bool(
            page.get('ok') is True
            and decision.get('page_ok') is True
            and page_success_text
            and page_transition.get('kind') == 'new_or_changed_structured_save_status'
            and isinstance(page_transition.get('entry'), Mapping)
            and page_transition.get('entry')
        )
        postconditions['published_false'] = bool(
            save.get('published') is False
            and evidence.get('published') is False
            and decision.get('ok') is True
        )
        postconditions['publish_action_not_clicked'] = bool(
            save.get('publish_action_clicked') is False
            and publish_signal.get('detected') is False
            and _strict_int(network_audit.get('publish_request_count')) == 0
            and network_audit.get('complete') is True
        )

    @staticmethod
    def _derive_unpublished_postconditions(
        evidence: Mapping[str, Any],
        sources: Mapping[str, dict[str, Any]],
        postconditions: dict[str, bool],
    ) -> None:
        proof = sources.get('unpublished_proof') or {}
        identity_readback = proof.get('identity_readback') if isinstance(proof.get('identity_readback'), Mapping) else {}
        status = ''.join(str(proof.get('status_text') or proof.get('publish_status') or '').split())
        structured_current_page = bool(
            proof.get('verified_on_current_page') is True
            and proof.get('proof_kind') == 'structured_unpublished_status'
            and proof.get('status_scope_unique') is True
            and proof.get('bound_candidate_count') == 1
            and str(proof.get('target_identity_sha256') or '').strip()
            and proof.get('identity_binding_kind') == 'frozen_target_structured_page_readback'
            and identity_readback.get('product_identity_match') is True
            and identity_readback.get('store_identity_match') is True
            and identity_readback.get('source_identity_match') is True
        )
        valid_status = status in {'待发布', '草稿', '未发布', '待完善'}
        target_identity_match = bool(
            structured_current_page
            and proof.get('target_bound') is True
            and proof.get('product_matched') is True
            and proof.get('store_matched') is True
            and proof.get('source_identity_match') is True
        )
        unpublished = bool(
            structured_current_page
            and target_identity_match
            and proof.get('ok') is True
            and valid_status
            and proof.get('publish_risk_term') in (None, '')
            and proof.get('published') is False
        )
        postconditions['independent_probe'] = structured_current_page
        postconditions['product_identity_match'] = target_identity_match
        postconditions['unpublished_verified'] = unpublished
        postconditions['publish_status_absent_or_false'] = bool(
            structured_current_page
            and valid_status
            and proof.get('published') is False
            and proof.get('publish_risk_term') in (None, '')
        )
        save_ref = evidence.get('save_evidence_ref')
        unpublished_ref = evidence.get('unpublished_evidence_ref') or evidence.get('evidence_ref')
        postconditions['save_evidence_not_reused'] = bool(
            structured_current_page
            and isinstance(save_ref, Mapping)
            and isinstance(unpublished_ref, Mapping)
            and save_ref.get('path')
            and unpublished_ref.get('path')
            and save_ref.get('sha256')
            and unpublished_ref.get('sha256')
            and save_ref.get('path') != unpublished_ref.get('path')
        )

    @staticmethod
    def _failure_code(
        action: str,
        evidence: Mapping[str, Any],
        sources: Mapping[str, dict[str, Any]],
    ) -> str:
        candidates = [evidence.get('failure_code'), evidence.get('reason_code')]
        for source in sources.values():
            candidates.extend((source.get('failure_code'), source.get('reason_code')))
        for candidate in candidates:
            code = str(candidate or '').strip().upper()
            if _FAILURE_CODE_PATTERN.fullmatch(code):
                return code
        return f"ACTION_{re.sub(r'[^A-Z0-9]+', '_', action.upper()).strip('_')}_FAILED"

    @staticmethod
    def _recoverability(failure_code: str | None) -> dict[str, Any]:
        if failure_code is None:
            return {
                'kind': 'none',
                'retryable': False,
                'requires_page_reverify': False,
                'reason': None,
            }
        kind, retryable, reverify = _RECOVERABILITY_BY_CODE.get(
            failure_code,
            ('manual_takeover', False, True),
        )
        return {
            'kind': kind,
            'retryable': retryable,
            'requires_page_reverify': reverify,
            'reason': failure_code,
        }

    def _state_from_live_probe(self, probe: dict[str, Any]) -> dict[str, Any]:
        if probe.get('logged_in'):
            product_page = probe.get('product_page') or {}
            return {
                'ok': True,
                'stage': 'login_success',
                'page_title': probe.get('title') or product_page.get('title'),
                'page_url': probe.get('final_url') or product_page.get('url'),
                'screenshot_url': probe.get('home_screenshot_url') or probe.get('home_screenshot') or product_page.get('screenshot_url') or product_page.get('screenshot'),
                'live_probe': probe,
            }
        return {
            'ok': False,
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

    def _requires_visible_execution_browser_login_check(self) -> bool:
        return any(
            str(os.getenv(name) or '').strip().lower() in {'1', 'true', 'yes', 'on', 'browser_agent'}
            for name in (
                'DXM_DESKTOP',
                'DXM_WORKFLOW_PERSISTENT_PROFILE',
                'DXM_WORKFLOW_ACTION_RUNTIME',
            )
        )
