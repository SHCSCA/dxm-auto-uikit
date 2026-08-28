import pytest

from src.execution.action_result_contract import ACTION_RESULT_CONTRACTS
from src.execution.browser_agent_protocol import build_frozen_product_target_identity
from src.execution.dxm_adapter import DxmWorkflowAdapter


TARGET_STORE = 'Dang Kang'
TARGET_PRODUCT_ID = '130658341390401740'
TARGET_SOURCE_URL = 'https://detail.1688.com/offer/1057791519266.html'


def frozen_target_identity():
    return build_frozen_product_target_identity(
        product_id=TARGET_PRODUCT_ID,
        store_name=TARGET_STORE,
        source_urls=[TARGET_SOURCE_URL],
    )


_frozen_target_identity = frozen_target_identity


class FakeLoginFlow:
    def __init__(self, stage='login_success', ok=True):
        self.calls = []
        self.stage = stage
        self.ok = ok

    def get_state(self):
        self.calls.append(('get_state',))
        return self._state(self.stage)

    def navigate_post_login(self, target):
        self.calls.append(('navigate_post_login', target))
        return self._state('workflow_navigation')

    def perform_draft_box_action(
        self,
        action,
        product_query=None,
        store_name=None,
        target_source_urls=None,
        target_identity=None,
    ):
        self.calls.append(
            (
                'perform_draft_box_action',
                action,
                None,
                product_query,
                store_name,
                target_source_urls,
                target_identity,
            )
        )
        return self._state('editor_page' if action == 'edit' else 'draft_box_action')

    def perform_editor_action(
        self,
        action,
        defaults=None,
        product_query=None,
        store_name=None,
        target_source_urls=None,
        target_identity=None,
    ):
        self.calls.append(
            (
                'perform_editor_action',
                action,
                defaults,
                product_query,
                store_name,
                target_identity,
            )
        )
        return self._state(action)

    def _state(self, stage):
        state = {
            'stage': stage,
            'page_title': '速卖通商品箱',
            'page_url': 'https://www.dianxiaomi.com/web/smt/smtProductList/draft',
            'screenshot_url': '/artifacts/screenshots/draft-box.png',
            'login_check': {
                'logged_in': True,
                'business_page_ready': True,
                'loading': False,
            },
        }
        if self.ok is not None:
            state['ok'] = self.ok
        return state


class FakeLiveClient:
    def __init__(self, logged_in=True):
        self.logged_in = logged_in
        self.probed = False

    def probe_session(self):
        self.probed = True
        if self.logged_in:
            return {
                'logged_in': True,
                'title': '店小秘--首页',
                'final_url': 'https://www.dianxiaomi.com/web/home',
                'home_screenshot': 'C:/tmp/home.png',
            }
        return {
            'logged_in': False,
            'reason': 'cookie_expired',
            'title': '店小秘登录',
            'final_url': 'https://www.dianxiaomi.com/',
        }


class FakeLoginFlowWithLiveProbe(FakeLoginFlow):
    def __init__(self, logged_in=True):
        super().__init__(stage='opening_login_page')
        self.live_client = FakeLiveClient(logged_in=logged_in)


class FakeBrowserAgentLoginFlow(FakeLoginFlowWithLiveProbe):
    def __init__(self, visible_stage='login_failed', logged_in=True):
        super().__init__(logged_in=logged_in)
        self.visible_stage = visible_stage

    def check_visible_login_state(self):
        self.calls.append(('check_visible_login_state',))
        return {
            **self._state(self.visible_stage),
            'ok': self.visible_stage == 'login_success',
        }


class FailingLiveClient:
    def __init__(self):
        self.probed = False

    def probe_session(self):
        self.probed = True
        raise RuntimeError('It looks like you are using Playwright Sync API inside the asyncio loop. Please use the Async API instead.')


class FakeVisibleLoginFlow(FakeLoginFlow):
    def __init__(self, stage='login_success'):
        super().__init__(stage=stage)
        self.live_client = FailingLiveClient()
        self._page = object()
        self._browser = object()


def test_real_dxm_adapter_declares_persistent_browser_agent_requirement():
    adapter = DxmWorkflowAdapter(FakeLoginFlow())

    assert adapter.requires_persistent_browser_agent is True


def test_adapter_exposes_e2_product_detail_reader_unchanged():
    class ProductDetailFlow(FakeLoginFlow):
        def read_e2_product_details(self, *, shop_id, product_ids):
            self.calls.append(('read_e2_product_details', shop_id, tuple(product_ids)))
            return {'payload': {'products': [{'id': product_ids[0]}]}}

    flow = ProductDetailFlow()
    result = DxmWorkflowAdapter(flow).read_e2_product_details(
        shop_id='6517349',
        product_ids=['130658341390401740'],
    )

    assert result == {'payload': {'products': [{'id': '130658341390401740'}]}}
    assert flow.calls == [
        ('read_e2_product_details', '6517349', ('130658341390401740',)),
    ]


def test_adapter_forwards_e2_representative_products_without_signature_drift():
    class PlanScopeFlow(FakeLoginFlow):
        def read_e2_plan_scope(self, *, shop_id, category_ids, representative_product_ids=None):
            self.calls.append((
                'read_e2_plan_scope',
                shop_id,
                tuple(category_ids),
                representative_product_ids,
            ))
            return {'payload': {'category_schemas': {}}}

    flow = PlanScopeFlow()
    result = DxmWorkflowAdapter(flow).read_e2_plan_scope(
        shop_id='6517349',
        category_ids=['100004476'],
        representative_product_ids={'100004476': '130658341390401740'},
    )

    assert result == {'payload': {'category_schemas': {}}}
    assert flow.calls == [(
        'read_e2_plan_scope',
        '6517349',
        ('100004476',),
        {'100004476': '130658341390401740'},
    )]


def test_check_login_state_delegates_to_login_flow_get_state():
    flow = FakeLoginFlow()
    result = DxmWorkflowAdapter(flow).check_login_state()

    assert flow.calls == [('get_state',)]
    assert result['ok'] is True
    assert result['action'] == 'check_login_state'
    assert result['stage'] == 'login_success'
    assert result['evidence']['page_title'] == '速卖通商品箱'


def test_check_login_state_prefers_live_probe_when_available():
    flow = FakeLoginFlowWithLiveProbe(logged_in=True)
    result = DxmWorkflowAdapter(flow).check_login_state()

    assert flow.calls == []
    assert flow.live_client.probed is True
    assert result['ok'] is False
    assert result['stage'] == 'login_success'
    assert result['page_url'] == 'https://www.dianxiaomi.com/web/home'


def test_browser_agent_check_login_state_uses_execution_browser_not_cookie_probe(monkeypatch):
    monkeypatch.setenv('DXM_WORKFLOW_ACTION_RUNTIME', 'browser_agent')
    flow = FakeBrowserAgentLoginFlow(visible_stage='login_failed', logged_in=True)

    result = DxmWorkflowAdapter(flow).check_login_state()

    assert flow.calls == [('check_visible_login_state',)]
    assert flow.live_client.probed is False
    assert result['ok'] is False
    assert result['stage'] == 'login_failed'


def test_check_login_state_live_probe_failure_blocks_workflow():
    flow = FakeLoginFlowWithLiveProbe(logged_in=False)
    result = DxmWorkflowAdapter(flow).check_login_state()

    assert result['ok'] is False
    assert result['stage'] == 'login_failed'
    assert result['evidence']['live_probe']['reason'] == 'cookie_expired'


def test_check_login_state_reuses_visible_logged_in_browser_before_headless_probe():
    flow = FakeVisibleLoginFlow(stage='login_success')

    result = DxmWorkflowAdapter(flow).check_login_state()

    assert flow.live_client.probed is False
    assert flow.calls == [('get_state',)]
    assert result['ok'] is True
    assert result['stage'] == 'login_success'


def test_check_login_state_fails_closed_when_probe_hits_sync_guard():
    flow = FakeLoginFlow(stage='login_success')
    flow.live_client = FailingLiveClient()

    result = DxmWorkflowAdapter(flow).check_login_state()

    assert flow.live_client.probed is True
    assert flow.calls == [('get_state',)]
    assert result['ok'] is False
    assert result['stage'] == 'login_failed'
    assert result['requires_user_action'] is True
    assert 'Playwright Sync API' in result['evidence']['live_probe_error']


def test_open_draft_box_delegates_to_login_flow_navigation():
    flow = FakeLoginFlow()
    result = DxmWorkflowAdapter(flow).open_draft_box()

    assert flow.calls == [('navigate_post_login', 'draft_box')]
    assert result['action'] == 'open_draft_box'
    assert result['stage'] == 'workflow_navigation'


def test_capture_draft_box_scope_delegates_readonly_capture_without_contract_rewrite():
    class ScopeFlow:
        def __init__(self):
            self.calls = []

        def capture_draft_box_scope(self, max_items):
            self.calls.append(('capture_draft_box_scope', max_items))
            return {
                'schema': 'dxm_draft_box_scope_capture.v1',
                'ok': True,
                'items': [{'position': 1, 'title': '商品 A'}],
                'zero_write_proof': {'ok': True},
            }

    flow = ScopeFlow()

    result = DxmWorkflowAdapter(flow).capture_draft_box_scope(max_items=25)

    assert flow.calls == [('capture_draft_box_scope', 25)]
    assert result['schema'] == 'dxm_draft_box_scope_capture.v1'
    assert result['items'] == [{'position': 1, 'title': '商品 A'}]


def test_adapter_does_not_infer_success_from_stage_without_explicit_ok():
    flow = FakeLoginFlow(stage='workflow_navigation', ok=None)

    result = DxmWorkflowAdapter(flow).check_login_state()

    assert result['ok'] is False
    assert result['stage'] == 'workflow_navigation'


def test_open_editor_delegates_to_edit_action():
    flow = FakeLoginFlow()
    identity = frozen_target_identity()
    result = DxmWorkflowAdapter(flow).open_editor(store_name=TARGET_STORE, target_identity=identity)

    assert flow.calls == [('perform_draft_box_action', 'edit', None, None, TARGET_STORE, None, identity)]
    assert result['action'] == 'open_editor'
    assert result['stage'] == 'editor_page'


def test_open_editor_passes_optional_target_filters():
    flow = FakeLoginFlow()
    identity = frozen_target_identity()
    result = DxmWorkflowAdapter(flow).open_editor(
        product_query='崩坏3钥匙扣', store_name=TARGET_STORE, target_identity=identity
    )

    assert flow.calls == [('perform_draft_box_action', 'edit', None, '崩坏3钥匙扣', TARGET_STORE, None, identity)]
    assert result['action'] == 'open_editor'


def test_enable_semi_managed_delegates_to_editor_action():
    flow = FakeLoginFlow()
    identity = frozen_target_identity()
    result = DxmWorkflowAdapter(flow).enable_semi_managed(
        product_query='崩坏3钥匙扣', store_name=TARGET_STORE, target_identity=identity
    )

    assert flow.calls == [('perform_editor_action', 'enable_semi_managed', None, '崩坏3钥匙扣', TARGET_STORE, identity)]
    assert result['action'] == 'enable_semi_managed'


def test_fill_editor_required_defaults_passes_defaults_and_target_context():
    flow = FakeLoginFlow()
    identity = frozen_target_identity()
    result = DxmWorkflowAdapter(flow).fill_editor_required_defaults(
        defaults={'weight': '0.03'},
        product_query='崩坏3钥匙扣',
        store_name=TARGET_STORE,
        target_identity=identity,
    )

    assert flow.calls == [('perform_editor_action', 'fill_editor_required_defaults', {'weight': '0.03'}, '崩坏3钥匙扣', TARGET_STORE, identity)]
    assert result['action'] == 'fill_editor_required_defaults'


def test_fill_media_assets_passes_defaults_and_target_context():
    flow = FakeLoginFlow()
    identity = frozen_target_identity()
    result = DxmWorkflowAdapter(flow).fill_media_assets(
        defaults={'image': {'eu_outer_package_filename': 'eu.jpg'}},
        product_query='崩坏3钥匙扣',
        store_name=TARGET_STORE,
        target_identity=identity,
    )

    assert flow.calls == [('perform_editor_action', 'fill_media_assets', {'image': {'eu_outer_package_filename': 'eu.jpg'}}, '崩坏3钥匙扣', TARGET_STORE, identity)]
    assert result['action'] == 'fill_media_assets'


def test_fill_compliance_defaults_passes_defaults_and_target_context():
    flow = FakeLoginFlow()
    identity = frozen_target_identity()
    result = DxmWorkflowAdapter(flow).fill_compliance_defaults(
        defaults={'compliance': {'material': 'ABS'}},
        product_query='崩坏3钥匙扣',
        store_name=TARGET_STORE,
        target_identity=identity,
    )

    assert flow.calls == [('perform_editor_action', 'fill_compliance_defaults', {'compliance': {'material': 'ABS'}}, '崩坏3钥匙扣', TARGET_STORE, identity)]
    assert result['action'] == 'fill_compliance_defaults'


def test_open_semi_managed_page_passes_defaults_and_target_context():
    flow = FakeLoginFlow()
    identity = frozen_target_identity()
    result = DxmWorkflowAdapter(flow).open_semi_managed_page(
        defaults={'image': {'marketing_images_strategy': 'generate'}},
        product_query='崩坏3钥匙扣',
        store_name=TARGET_STORE,
        target_identity=identity,
    )

    assert flow.calls == [('perform_editor_action', 'open_semi_managed_page', {'image': {'marketing_images_strategy': 'generate'}}, '崩坏3钥匙扣', TARGET_STORE, identity)]
    assert result['action'] == 'open_semi_managed_page'


def test_fill_semi_managed_defaults_passes_defaults_and_target_context():
    flow = FakeLoginFlow()
    identity = frozen_target_identity()
    result = DxmWorkflowAdapter(flow).fill_semi_managed_defaults(
        defaults={'weight': '0.03'},
        product_query='崩坏3钥匙扣',
        store_name=TARGET_STORE,
        target_identity=identity,
    )

    assert flow.calls == [('perform_editor_action', 'fill_semi_managed_defaults', {'weight': '0.03'}, '崩坏3钥匙扣', TARGET_STORE, identity)]
    assert result['action'] == 'fill_semi_managed_defaults'


def test_save_only_passes_defaults_and_target_context_to_editor_action():
    flow = FakeLoginFlow()
    identity = frozen_target_identity()
    result = DxmWorkflowAdapter(flow).save_only(
        defaults={'stock': '200'},
        product_query='崩坏3钥匙扣',
        store_name=TARGET_STORE,
        target_identity=identity,
    )

    assert flow.calls == [('perform_editor_action', 'save_only', {'stock': '200'}, '崩坏3钥匙扣', TARGET_STORE, identity)]
    assert result['action'] == 'save_only'


def test_failed_stage_sets_ok_false():
    flow = FakeLoginFlow(stage='login_failed', ok=False)
    result = DxmWorkflowAdapter(flow).check_login_state()

    assert result['ok'] is False
    assert result['stage'] == 'login_failed'


@pytest.mark.parametrize('action', tuple(ACTION_RESULT_CONTRACTS))
def test_every_business_action_exposes_exact_contract_fact_keys_and_registry_postconditions(action):
    adapter = DxmWorkflowAdapter(FakeLoginFlow())

    result = adapter._result(action, {'ok': True})

    assert set(result['contract_facts']) == {
        'before_values',
        'after_values',
        'postconditions',
        'evidence_observations',
        'failure_code',
        'recoverability',
    }
    expected_names = set().union(
        *(
            contract.required_postconditions
            for contract in ACTION_RESULT_CONTRACTS[action].values()
        )
    )
    assert set(result['contract_facts']['postconditions']) == expected_names


def test_semi_managed_deferred_validation_never_satisfies_readback_postconditions():
    required = set().union(
        *(
            contract.required_postconditions
            for contract in ACTION_RESULT_CONTRACTS['fill_semi_managed_defaults'].values()
        )
    )
    result = DxmWorkflowAdapter(FakeLoginFlow())._result(
        'fill_semi_managed_defaults',
        {
            'ok': True,
            'fill_result': {'deferred_validation': True, 'visible': True},
            'contract_observations': {
                'postconditions': {name: True for name in required},
                'after_values': {'visible': True},
            },
        },
        before_values={'defaults': {'weight': '0.03'}},
    )

    assert not any(result['contract_facts']['postconditions'].values())
    assert result['contract_facts']['recoverability']['kind'] != 'none'


def test_semi_managed_boolean_claims_without_per_field_readback_never_pass():
    required = set().union(
        *(
            contract.required_postconditions
            for contract in ACTION_RESULT_CONTRACTS['fill_semi_managed_defaults'].values()
        )
    )
    facts = DxmWorkflowAdapter(FakeLoginFlow())._result(
        'fill_semi_managed_defaults',
        {
            'ok': True,
            'fill_result': {name: True for name in required},
        },
        before_values={'defaults': {'weight': '0.03'}},
    )['contract_facts']

    assert not any(facts['postconditions'].values())
    assert facts['recoverability']['kind'] != 'none'


def test_semi_managed_structured_per_field_readback_still_requires_frozen_target():
    def exact(expected):
        return {
            'ok': True,
            'located': True,
            'expected_value': expected,
            'value_after': expected,
        }

    facts = DxmWorkflowAdapter(FakeLoginFlow())._result(
        'fill_semi_managed_defaults',
        {
            'ok': True,
            'fill_result': {
                'field_details': {
                    'weight': exact('0.03'),
                    'length': exact('10'),
                    'width': exact('10'),
                    'height': exact('2'),
                    'logistics_attribute': exact('普货'),
                    'freight_template': exact('40g普货包裹'),
                    'service_template': exact('Service Template for New Sellers'),
                    'product_price': exact('12.99'),
                    'supply_price': exact('8.50'),
                    'stock': exact('100'),
                    'goods_code': exact('SKU-001'),
                },
                'variant_rows': [{'sku': 'SKU-001'}],
            },
        },
        before_values={'defaults': {'weight': '0.03'}},
    )['contract_facts']

    assert all(facts['postconditions'].values())
    assert facts['recoverability']['kind'] != 'none'


@pytest.mark.parametrize(
    ('network_success', 'page_success', 'expected_complete'),
    ((True, True, True), (True, False, False), (False, True, False)),
)
def test_legacy_save_success_booleans_never_replace_structured_receipts(network_success, page_success, expected_complete):
    raw = {
        'ok': True,
        'save_result': {
            'mutation_authorization': {
                'ok': True,
                'executed': True,
                'mutation_action': 'save_only_click',
            },
            'exact_save_target': True,
            'text': '保存',
            'exact_save_count': 1,
            'click_method': 'native_exact_save',
            'save_click_dispatched': True,
            'network_save_success': network_success,
            'page_save_success': page_success,
            'published': False,
            'publish_action_clicked': False,
        },
    }

    facts = DxmWorkflowAdapter(FakeLoginFlow())._result(
        'save_only',
        raw,
        before_values={
            'defaults': {'stock': '200'},
            'target_identity': {'product_query': 'item', 'store_name': 'shop'},
        },
    )['contract_facts']

    assert facts['postconditions']['network_save_success'] is False
    assert facts['postconditions']['page_save_success'] is False
    assert facts['recoverability']['kind'] != 'none'


def test_save_rejects_authorization_for_a_different_mutation_action():
    facts = DxmWorkflowAdapter(FakeLoginFlow())._result(
        'save_only',
        {
            'ok': True,
            'save_result': {
                'mutation_authorization': {
                    'ok': True,
                    'executed': True,
                    'mutation_action': 'claim_confirm_click',
                },
                'exact_save_target': True,
                'save_click_dispatched': True,
                'network_save_success': True,
                'page_save_success': True,
                'published': False,
                'publish_action_clicked': False,
            },
        },
        before_values={
            'defaults': {'stock': '200'},
            'target_identity': {'product_query': 'item', 'store_name': 'shop'},
        },
    )['contract_facts']

    assert facts['postconditions']['mutation_authorized'] is False
    assert facts['recoverability']['kind'] != 'none'


def test_save_requires_structured_exact_target_explicit_dispatch_and_no_publish_fact():
    facts = DxmWorkflowAdapter(FakeLoginFlow())._result(
        'save_only',
        {
            'ok': True,
            'save_result': {
                'mutation_authorization': {
                    'ok': True,
                    'executed': True,
                    'mutation_action': 'save_only_click',
                },
                'exact_save_target': True,
                'text': '保存并移入待发布',
                'exact_save_count': 1,
                'click_method': 'native_exact_save',
                'clicked': True,
                'network_save_success': True,
                'page_save_success': True,
                'published': False,
            },
        },
        before_values={
            'target_identity': {'product_query': 'item', 'store_name': 'shop'},
        },
    )['contract_facts']

    assert facts['postconditions']['exact_save_target'] is False
    assert facts['postconditions']['save_click_dispatched'] is False
    assert facts['postconditions']['publish_action_not_clicked'] is False
    assert facts['recoverability']['kind'] != 'none'


def test_unpublished_proof_reusing_save_evidence_is_rejected():
    reused = {'path': 'proof.png', 'sha256': 'a' * 64}
    raw = {
        'ok': True,
        'save_evidence_ref': reused,
        'unpublished_evidence_ref': dict(reused),
        'unpublished_proof': {
            'independent_probe': True,
            'target_bound': True,
            'product_identity_match': True,
            'unpublished_verified': True,
            'publish_status': False,
        },
    }

    facts = DxmWorkflowAdapter(FakeLoginFlow())._result(
        'verify_not_published',
        raw,
        before_values={'product_query': 'item'},
    )['contract_facts']

    assert facts['postconditions']['save_evidence_not_reused'] is False
    assert facts['recoverability']['kind'] != 'none'


def test_unpublished_boolean_claims_without_current_page_structured_probe_fail_closed():
    facts = DxmWorkflowAdapter(FakeLoginFlow())._result(
        'verify_not_published',
        {
            'ok': True,
            'save_evidence_ref': {'path': 'save.png', 'sha256': 'a' * 64},
            'unpublished_evidence_ref': {'path': 'verify.png', 'sha256': 'b' * 64},
            'unpublished_proof': {
                'independent_probe': True,
                'product_identity_match': True,
                'unpublished_verified': True,
                'publish_status': False,
                'target_bound': True,
                'product_matched': True,
                'store_matched': True,
            },
        },
        before_values={
            'target_identity': {'product_query': 'item', 'store_name': 'shop'},
        },
    )['contract_facts']

    assert not any(facts['postconditions'].values())
    assert facts['recoverability']['kind'] != 'none'


def test_navigation_requires_business_marker_from_structured_readiness_probe():
    facts = DxmWorkflowAdapter(FakeLoginFlow())._result(
        'open_draft_box',
        {
            'ok': True,
            'wait_result': {
                'ready': True,
                'ready_term': 'unstructured-fallback-is-not-proof',
                'expected_identity': 'draft_box',
                'loading': False,
                'readiness': {
                    'ok': True,
                    'expected_identity': 'draft_box',
                    'loading': False,
                    'blocking_modal': None,
                },
            },
        },
        before_values={'requested_page_identity': 'draft_box'},
    )['contract_facts']

    assert facts['postconditions']['expected_page'] is True
    assert facts['postconditions']['business_marker_present'] is False
    assert facts['recoverability']['kind'] != 'none'


def test_save_facts_expose_authorization_target_click_and_both_success_proofs():
    save_result = {
        'mutation_authorization': {
            'ok': True,
            'executed': True,
            'mutation_action': 'save_only_click',
        },
        'text': '保存',
        'exact_save_count': 1,
        'clicked': True,
        'click_method': 'native_exact_save',
        'network_save_result': {'ok': True, 'code': 0},
        'page_save_result': {'ok': True, 'status_transition': {'kind': 'new_status'}},
        'save_decision': {'network_ok': True, 'page_ok': True},
        'published': False,
        'publish_action_clicked': False,
    }

    facts = DxmWorkflowAdapter(FakeLoginFlow())._result(
        'save_only',
        {'ok': True, 'save_result': save_result, 'published': False},
        before_values={
            'defaults': {'stock': '200'},
            'target_identity': {'product_query': 'item', 'store_name': 'shop'},
        },
    )['contract_facts']

    assert set(facts['after_values']) >= {
        'mutation_authorization',
        'exact_save_target',
        'save_click_dispatched',
        'network_save_result',
        'page_save_result',
        'published',
    }
    assert set(facts['evidence_observations']) >= {
        'save_result',
        'mutation_authorization',
        'exact_save_target',
        'network_save_result',
        'page_save_result',
    }


def test_save_and_verify_before_values_share_exact_target_identity():
    adapter = DxmWorkflowAdapter(FakeLoginFlow())
    identity = frozen_target_identity()

    save = adapter.save_only(
        product_query='item-123',
        store_name=TARGET_STORE,
        target_identity=identity,
    )
    verify = adapter.verify_not_published(
        product_query='item-123',
        store_name=TARGET_STORE,
        target_identity=identity,
    )

    expected = identity
    assert save['contract_facts']['before_values']['target_identity'] == expected
    assert verify['contract_facts']['before_values']['target_identity'] == expected


def _strict_save_result(
    *,
    target_identity: dict,
    network_success: bool = True,
    page_success: bool = True,
) -> dict:
    return {
        'ok': network_success and page_success,
        'mutation_authorization': {
            'ok': True,
            'executed': True,
            'mutation_action': 'save_only_click',
            'mutation_id': 'mutation-1',
            'mutation_status': 'DISPATCHED',
        },
        'pre_dispatch_readback': {
            'ok': True,
            'required_readback_complete': True,
            'write_attempted': False,
            'phase': 'before_ledger_begin_dispatch',
            'exact_save_target': {'ok': True, 'text': '保存', 'exact_save_count': 1},
            'identity': target_identity,
            'current_field_integrity': {'ok': True},
        },
        'exact_save_target': True,
        'text': '保存',
        'exact_save_count': 1,
        'click_method': 'native_exact_save',
        'save_click_dispatched': True,
        'clicked': True,
        'network_save_result': {
            'ok': network_success,
            'receipt_complete': True,
            'receipt_count': 1,
            'url': 'https://www.dianxiaomi.com/api/smtProduct/add.json',
            'method': 'POST',
            'status': 200,
            'code': 0,
            'message': '保存成功',
        },
        'network_audit': {
            'scope': 'same_origin_write_window',
            'complete': True,
            'window_closed': True,
            'registered_listener_count': 2,
            'removed_listener_count': 2,
            'mutation_request_count': 1,
            'save_request_count': 1,
            'other_mutation_request_count': 0,
            'read_only_schema_request_count': 0,
            'publish_request_count': 0,
        },
        'publish_signal': {
            'detected': False,
            'kind': 'network_route_classification',
            'request_count': 0,
        },
        'page_save_result': {
            'ok': page_success,
            'success_text': '保存成功',
            'status_transition': {
                'kind': 'new_or_changed_structured_save_status',
                'entry': {'text': '保存成功'},
            },
        },
        'save_decision': {
            'ok': network_success and page_success,
            'rule': 'page_success_and_network_success',
            'network_ok': network_success,
            'page_ok': page_success,
            'network_receipt_ok': network_success,
            'network_audit_ok': network_success,
        },
        'published': False,
        'publish_action_clicked': False,
    }

@pytest.mark.parametrize(
    ('network_success', 'page_success', 'expected_complete'),
    ((True, True, True), (True, False, False), (False, True, False)),
)
def test_save_requires_network_and_page_success(network_success, page_success, expected_complete):
    target_identity = _frozen_target_identity()
    raw = {
        'ok': True,
        'published': False,
        'save_result': _strict_save_result(
            target_identity=target_identity,
            network_success=network_success,
            page_success=page_success,
        ),
    }

    facts = DxmWorkflowAdapter(FakeLoginFlow())._result(
        'save_only',
        raw,
        before_values={
            'defaults': {'stock': '200'},
            'store_name': 'Dang Kang',
            'target_identity': target_identity,
        },
    )['contract_facts']

    assert facts['postconditions']['network_save_success'] is network_success
    assert facts['postconditions']['page_save_success'] is page_success
    assert (facts['recoverability']['kind'] == 'none') is expected_complete
