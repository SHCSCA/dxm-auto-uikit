"""本机新文档运行被动脚本；profile 是 spy，不声称加载过生产公开资源。"""

import pytest
from playwright.sync_api import sync_playwright

from src.execution.native_video_lifetime import NativeVideoLifetime
from src.execution.native_video_lifetime_script import NATIVE_VIDEO_LIFETIME_READ, LIFETIME_READER
from tests.support.native_video_lifetime_case import install_profile_spy


URL = 'https://fixture.invalid/editor?id=10001'
HTML = '''<meta charset="utf-8"><style>div,button,input{min-height:12px;min-width:12px}</style>
<script>window.inlineInitial=window.__dxmNativeVideoReadonlyLifetimeV1?.();</script>
<div class="product-add-wrapper"><input id="outside"><div class="video-operate"><button id="entry">图片生成视频</button></div></div>
<div class="ant-modal-wrap" role="dialog" style="display:none"><div class="ant-modal-header"><button id="header">header</button></div>
<div class="img-translate-video"><input id="inside"><button id="option">option</button></div></div>
<script>document.querySelector('#entry').onclick=()=>document.querySelector('[role=dialog]').style.display='block';</script>'''


@pytest.fixture(scope='module')
def browser():
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(headless=True)
        yield instance
        instance.close()


@pytest.fixture
def case(browser, monkeypatch):
    install_profile_spy(monkeypatch)
    context = browser.new_context()
    context.route('**/*', lambda route: route.fulfill(status=200, content_type='text/html', body=HTML))
    page = context.new_page()
    owner = NativeVideoLifetime(page, page_url=URL, session_id='session-1').start()
    page.goto(URL)
    yield page, owner
    owner.close()
    context.close()


def test_init_script_precedes_inline_document_code_and_only_trusted_first_entry_counts(case):
    page, owner = case
    first = page.evaluate('inlineInitial')
    assert first['reveal_count'] == first['entry_click_count'] == first['visible_count'] == 0
    assert first['unexpected_interactions'] == [] and owner.navigation_count == 1
    initial = owner.read()
    page.locator('#outside').fill('legitimate prior fill')
    assert owner.read()['unexpected_interactions'] == []
    page.locator('#entry').click()
    actual = owner.read()
    assert actual['reveal_count'] == actual['entry_click_count'] == actual['visible_count'] == 1
    assert actual['document_time_origin'] == initial['document_time_origin'] == page.evaluate('performance.timeOrigin')
    assert owner.profile.started and owner.profile.expect_navigation


def test_reader_property_is_immutable_and_reads_do_not_mutate_dom_or_send_requests(case):
    page, owner = case
    page.locator('#entry').click()
    requests = []
    page.on('request', lambda request: requests.append(request.url))
    page.evaluate('''()=>{
      window.mutations=[];window.watch=new MutationObserver(items=>mutations.push(...items));
      watch.observe(document.body,{subtree:true,attributes:true,childList:true,characterData:true});
    }''')
    descriptor = page.evaluate(f"Object.getOwnPropertyDescriptor(window,'{LIFETIME_READER}')")
    assert descriptor['writable'] is False and descriptor['configurable'] is False
    assert owner.read() == owner.read()
    assert page.evaluate('mutations.length') == 0 and requests == []


@pytest.mark.parametrize('selector,event', [
    ('#header', 'click'), ('#inside', 'input'), ('#inside', 'change'),
    ('#inside', 'keydown'), ('#inside', 'drop'), ('#inside', 'pointerdown'),
])
def test_any_modal_interaction_including_header_invalidates_default_provenance(case, selector, event):
    page, owner = case
    page.locator('#entry').click()
    page.locator(selector).dispatch_event(event)
    raw = page.evaluate(NATIVE_VIDEO_LIFETIME_READ)
    assert event in raw['unexpected_interactions']
    with pytest.raises(RuntimeError, match='INTERACTION_OR_LIFETIME'):
        owner.read()


def test_synthetic_entry_click_is_not_a_user_action_or_authorized_native_reveal(case):
    page, owner = case
    page.locator('#entry').evaluate('element=>element.click()')
    raw = page.evaluate(NATIVE_VIDEO_LIFETIME_READ)
    assert raw['entry_click_count'] == 1 and raw['reveal_count'] == 1
    assert raw['unexpected_interactions'] == ['synthetic_entry_click']
    with pytest.raises(RuntimeError, match='INTERACTION_OR_LIFETIME'):
        owner.read()


def test_second_entry_click_is_recorded_even_if_modal_stays_visible(case):
    page, owner = case
    page.locator('#entry').click(); page.locator('#entry').click()
    raw = page.evaluate(NATIVE_VIDEO_LIFETIME_READ)
    assert raw['entry_click_count'] == 2 and raw['reveal_count'] == 1


def test_hidden_then_reopened_native_modal_retains_closed_history(case):
    page, owner = case
    page.locator('#entry').click()
    page.locator('[role=dialog]').evaluate("element=>element.style.display='none'")
    page.wait_for_function("window.__dxmNativeVideoReadonlyLifetimeV1().closed_count===1")
    page.locator('#entry').click()
    raw = page.evaluate(NATIVE_VIDEO_LIFETIME_READ)
    assert raw['closed_count'] == 1 and raw['reveal_count'] == raw['entry_click_count'] == 2
    with pytest.raises(RuntimeError, match='INTERACTION_OR_LIFETIME'):
        owner.read()


def test_same_task_hidden_reopen_cannot_disappear_inside_mutation_observer_batch(case):
    page, owner = case
    page.locator('#entry').click()
    owner.read()
    page.locator('[role=dialog]').evaluate("element=>{element.style.display='none';element.style.display='block'}")
    with pytest.raises(RuntimeError, match='INTERACTION_OR_LIFETIME'):
        owner.read()


def test_same_task_detach_reattach_cannot_reuse_modal_default_history(case):
    page, owner = case
    page.locator('#entry').click()
    owner.read()
    page.locator('[role=dialog]').evaluate('element=>{element.remove();document.body.append(element)}')
    with pytest.raises(RuntimeError, match='INTERACTION_OR_LIFETIME'):
        owner.read()


def test_duplicate_modal_history_remains_rejected_after_duplicate_removed(case):
    page, owner = case
    page.locator('#entry').click()
    page.locator('[role=dialog]').evaluate('element=>element.after(element.cloneNode(true))')
    page.wait_for_function("window.__dxmNativeVideoReadonlyLifetimeV1().duplicate_modal_seen")
    page.locator('[role=dialog]').last.evaluate('element=>element.remove()')
    with pytest.raises(RuntimeError, match='INTERACTION_OR_LIFETIME'):
        owner.read()


def test_same_url_reload_has_new_native_origin_and_cannot_reuse_python_owner(case):
    page, owner = case
    previous = owner.read()['document_time_origin']
    page.reload()
    current = page.evaluate(NATIVE_VIDEO_LIFETIME_READ)
    assert current['document_time_origin'] != previous
    assert current['entry_click_count'] == 0 and current['reveal_count'] == 0
    assert owner.navigation_count == 2 and owner.invalid
    with pytest.raises(RuntimeError, match='DOCUMENT_DRIFT'):
        owner.read()
