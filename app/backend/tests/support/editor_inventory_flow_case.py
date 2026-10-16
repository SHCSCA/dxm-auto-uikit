"""真实离线页面配合合成字段；只证明观察包装，不证明生产控件或完整填写。"""

import threading
import time
import uuid
from contextlib import contextmanager
from types import SimpleNamespace

from src.batch_edit.frozen_execution_contract import frozen_execution_defaults
from src.execution.browser_agent_protocol import build_frozen_product_target_identity
from src.execution.dxm_adapter import DxmWorkflowAdapter
from src.execution.dxm_login_flow import DxmLoginFlow
from src.execution.managed_browser_context import create_managed_browser_context
from src.execution.native_video_transport import bind_native_video_transport, require_native_video_transport
from tests.support.editor_inventory_case import URL, inventory_case, inventory_html


@contextmanager
def editor_inventory_flow_case(browser, tmp_path, monkeypatch):
    context = create_managed_browser_context(browser)
    page = context.new_page()
    binding = bind_native_video_transport(page)
    target = build_frozen_product_target_identity(product_id='10001', store_name='fixture-store',
        source_urls=['https://detail.1688.com/offer/10001.html'])
    body = inventory_html() + '<input name="storeName" value="fixture-store"><a href="https://detail.1688.com/offer/10001.html">source</a>'

    def prepare_page(route):
        if route.request.url == URL:
            route.fulfill(status=200, content_type='text/html', body=body)
        else:
            route.abort()

    context.route('**/*', prepare_page)
    try:
        page.goto(URL, wait_until='networkidle')
        context.unroute('**/*', prepare_page)
        flow = DxmLoginFlow(None, state_file=tmp_path / 'isolated-inventory-state.json')
        flow._browser, flow._context, flow._page = browser, context, page
        flow._browser_session_thread_id = threading.get_ident()
        session = flow._bind_browser_context_generation(context)
        evidence = {'command_id': uuid.uuid4().hex, 'state': 'PREPARE_ROLLBACK', 'command_action': 'observe_editor_control_inventory',
            'mode': 'batch_draft_save', 'task_id': 1, 'job_id': 2, 'runtime_id': 'inventory-runtime',
            'browser_session_id': session, 'deadline_monotonic': time.monotonic() + 60}
        adapter = DxmWorkflowAdapter(flow)
        adapter.set_execution_evidence_context(evidence)
        payload, category = inventory_case()
        monkeypatch.setattr('src.execution.editor_inventory_flow.SCREENSHOT_DIR', tmp_path)
        monkeypatch.setattr('src.execution.browser_agent_worker.SCREENSHOT_DIR', tmp_path)
        args = {'defaults': frozen_execution_defaults(payload), 'category_schema': category, 'product_query': '10001',
            'store_name': 'fixture-store', 'shop_id': '91', 'target_identity': target}
        yield SimpleNamespace(flow=flow, adapter=adapter, page=page, browser=browser, context=context, binding=binding,
            transport=require_native_video_transport(page), args=args, payload=payload, evidence=evidence)
    finally:
        binding.close()
        context.close()
