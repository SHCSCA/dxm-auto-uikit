from src.execution.dxm_adapter import DxmWorkflowAdapter


class FakeLoginFlow:
    def __init__(self, stage='login_success'):
        self.calls = []
        self.stage = stage

    def get_state(self):
        self.calls.append(('get_state',))
        return self._state(self.stage)

    def navigate_post_login(self, target):
        self.calls.append(('navigate_post_login', target))
        return self._state('workflow_navigation')

    def perform_draft_box_action(self, action, note_text=None, product_query=None, store_name=None, target_source_urls=None):
        self.calls.append(('perform_draft_box_action', action, note_text, product_query, store_name, target_source_urls))
        return self._state('editor_page' if action == 'edit' else 'draft_box_action')

    def perform_editor_action(self, action, defaults=None, product_query=None, store_name=None):
        self.calls.append(('perform_editor_action', action, defaults, product_query, store_name))
        return self._state(action)

    def _state(self, stage):
        return {
            'stage': stage,
            'page_title': '速卖通采集箱',
            'page_url': 'https://www.dianxiaomi.com/web/smt/smtProductList/draft',
            'screenshot_url': '/artifacts/screenshots/draft-box.png',
        }


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


def test_check_login_state_delegates_to_login_flow_get_state():
    flow = FakeLoginFlow()
    result = DxmWorkflowAdapter(flow).check_login_state()

    assert flow.calls == [('get_state',)]
    assert result['ok'] is True
    assert result['action'] == 'check_login_state'
    assert result['stage'] == 'login_success'
    assert result['evidence']['page_title'] == '速卖通采集箱'


def test_check_login_state_prefers_live_probe_when_available():
    flow = FakeLoginFlowWithLiveProbe(logged_in=True)
    result = DxmWorkflowAdapter(flow).check_login_state()

    assert flow.calls == []
    assert flow.live_client.probed is True
    assert result['ok'] is True
    assert result['stage'] == 'login_success'
    assert result['page_url'] == 'https://www.dianxiaomi.com/web/home'


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


def test_check_login_state_falls_back_to_saved_login_state_when_probe_hits_sync_guard():
    flow = FakeLoginFlow(stage='login_success')
    flow.live_client = FailingLiveClient()

    result = DxmWorkflowAdapter(flow).check_login_state()

    assert flow.live_client.probed is True
    assert flow.calls == [('get_state',)]
    assert result['ok'] is True
    assert result['stage'] == 'login_success'
    assert 'Playwright Sync API' in result['evidence']['live_probe_error']


def test_open_draft_box_delegates_to_login_flow_navigation():
    flow = FakeLoginFlow()
    result = DxmWorkflowAdapter(flow).open_draft_box()

    assert flow.calls == [('navigate_post_login', 'draft_box')]
    assert result['action'] == 'open_draft_box'
    assert result['stage'] == 'workflow_navigation'


def test_claim_product_delegates_to_remark_action_with_note_text():
    flow = FakeLoginFlow()
    result = DxmWorkflowAdapter(flow).claim_product('AI认领')

    assert flow.calls == [('perform_draft_box_action', 'remark', 'AI认领', None, None, None)]
    assert result['action'] == 'claim_product'
    assert result['stage'] == 'draft_box_action'


def test_claim_product_passes_optional_target_filters():
    flow = FakeLoginFlow()
    result = DxmWorkflowAdapter(flow).claim_product('AI认领', product_query='崩坏3钥匙扣', store_name='Dang Kang')

    assert flow.calls == [('perform_draft_box_action', 'remark', 'AI认领', '崩坏3钥匙扣', 'Dang Kang', None)]
    assert result['action'] == 'claim_product'


def test_open_editor_delegates_to_edit_action():
    flow = FakeLoginFlow()
    result = DxmWorkflowAdapter(flow).open_editor()

    assert flow.calls == [('perform_draft_box_action', 'edit', None, None, None, None)]
    assert result['action'] == 'open_editor'
    assert result['stage'] == 'editor_page'


def test_open_editor_passes_optional_target_filters():
    flow = FakeLoginFlow()
    result = DxmWorkflowAdapter(flow).open_editor(product_query='崩坏3钥匙扣', store_name='Dang Kang')

    assert flow.calls == [('perform_draft_box_action', 'edit', None, '崩坏3钥匙扣', 'Dang Kang', None)]
    assert result['action'] == 'open_editor'


def test_open_editor_passes_note_text_for_claim_mark_targeting():
    flow = FakeLoginFlow()
    result = DxmWorkflowAdapter(flow).open_editor(
        product_query='崩坏3钥匙扣',
        store_name='Dang Kang',
        note_text='AI认领-19-31',
    )

    assert flow.calls == [('perform_draft_box_action', 'edit', 'AI认领-19-31', '崩坏3钥匙扣', 'Dang Kang', None)]
    assert result['action'] == 'open_editor'


def test_enable_semi_managed_delegates_to_editor_action():
    flow = FakeLoginFlow()
    result = DxmWorkflowAdapter(flow).enable_semi_managed(product_query='崩坏3钥匙扣', store_name='Dang Kang')

    assert flow.calls == [('perform_editor_action', 'enable_semi_managed', None, '崩坏3钥匙扣', 'Dang Kang')]
    assert result['action'] == 'enable_semi_managed'


def test_fill_editor_required_defaults_passes_defaults_and_target_context():
    flow = FakeLoginFlow()
    result = DxmWorkflowAdapter(flow).fill_editor_required_defaults(
        defaults={'weight': '0.03'},
        product_query='崩坏3钥匙扣',
        store_name='Dang Kang',
    )

    assert flow.calls == [('perform_editor_action', 'fill_editor_required_defaults', {'weight': '0.03'}, '崩坏3钥匙扣', 'Dang Kang')]
    assert result['action'] == 'fill_editor_required_defaults'


def test_fill_media_assets_passes_defaults_and_target_context():
    flow = FakeLoginFlow()
    result = DxmWorkflowAdapter(flow).fill_media_assets(
        defaults={'image': {'eu_outer_package_filename': 'eu.jpg'}},
        product_query='崩坏3钥匙扣',
        store_name='Dang Kang',
    )

    assert flow.calls == [('perform_editor_action', 'fill_media_assets', {'image': {'eu_outer_package_filename': 'eu.jpg'}}, '崩坏3钥匙扣', 'Dang Kang')]
    assert result['action'] == 'fill_media_assets'


def test_fill_compliance_defaults_passes_defaults_and_target_context():
    flow = FakeLoginFlow()
    result = DxmWorkflowAdapter(flow).fill_compliance_defaults(
        defaults={'compliance': {'material': 'ABS'}},
        product_query='崩坏3钥匙扣',
        store_name='Dang Kang',
    )

    assert flow.calls == [('perform_editor_action', 'fill_compliance_defaults', {'compliance': {'material': 'ABS'}}, '崩坏3钥匙扣', 'Dang Kang')]
    assert result['action'] == 'fill_compliance_defaults'


def test_open_semi_managed_page_passes_defaults_and_target_context():
    flow = FakeLoginFlow()
    result = DxmWorkflowAdapter(flow).open_semi_managed_page(
        defaults={'image': {'marketing_images_strategy': 'generate'}},
        product_query='崩坏3钥匙扣',
        store_name='Dang Kang',
    )

    assert flow.calls == [('perform_editor_action', 'open_semi_managed_page', {'image': {'marketing_images_strategy': 'generate'}}, '崩坏3钥匙扣', 'Dang Kang')]
    assert result['action'] == 'open_semi_managed_page'


def test_fill_semi_managed_defaults_passes_defaults_and_target_context():
    flow = FakeLoginFlow()
    result = DxmWorkflowAdapter(flow).fill_semi_managed_defaults(
        defaults={'weight': '0.03'},
        product_query='崩坏3钥匙扣',
        store_name='Dang Kang',
    )

    assert flow.calls == [('perform_editor_action', 'fill_semi_managed_defaults', {'weight': '0.03'}, '崩坏3钥匙扣', 'Dang Kang')]
    assert result['action'] == 'fill_semi_managed_defaults'


def test_save_only_passes_defaults_and_target_context_to_editor_action():
    flow = FakeLoginFlow()
    result = DxmWorkflowAdapter(flow).save_only(
        defaults={'stock': '200'},
        product_query='崩坏3钥匙扣',
        store_name='Dang Kang',
    )

    assert flow.calls == [('perform_editor_action', 'save_only', {'stock': '200'}, '崩坏3钥匙扣', 'Dang Kang')]
    assert result['action'] == 'save_only'


def test_failed_stage_sets_ok_false():
    flow = FakeLoginFlow(stage='login_failed')
    result = DxmWorkflowAdapter(flow).check_login_state()

    assert result['ok'] is False
    assert result['stage'] == 'login_failed'
