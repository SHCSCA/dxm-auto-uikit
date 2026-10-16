"""真实 Chromium 运行本地合成 DOM；不证明生产页面暴露 directive 或默认值。"""

import base64
from types import SimpleNamespace

import pytest
from playwright.sync_api import sync_playwright

from src.execution.native_video_dom_observation import (
    NATIVE_VIDEO_DOM_OBSERVATION_SCRIPT, collect_native_video_dom_observation,
)


PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aVS0AAAAASUVORK5CYII=')
URLS = ['https://fixture.invalid/selected-a.png', 'https://fixture.invalid/selected-b.png']
HTML = """<style>.ant-modal-wrap,.img-translate-video,.content-imgs,li {display:block;width:100px;min-height:10px} img {width:2px;height:2px}</style>
<div class="ant-modal-wrap" role="dialog"><div class="img-translate-video">
<div class="content-imgs"><li><img src="https://fixture.invalid/selected-a.png"></li><li><img src="https://fixture.invalid/selected-b.png"></li></div>
<div class="page-content_right-top"><div class="content-list"><li class="activeName"><img src="https://fixture.invalid/template-preview.gif">自然</li></div></div>
<div class="page-content_right-bottom"><div class="content-list"><li class="activeName">无背景音乐</li><li>music1</li></div></div>
</div></div>"""


@pytest.fixture(scope='module')
def browser():
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(headless=True)
        yield instance
        instance.close()


@pytest.fixture
def page(browser):
    context = browser.new_context()
    context.route('**/*', lambda route: route.fulfill(status=200, content_type='image/png', body=PNG))
    instance = context.new_page()
    instance.set_content(HTML)
    instance.wait_for_function('Array.from(document.images).every(img => img.complete && img.naturalWidth > 0)')
    instance.evaluate("""urls => {
      const list=document.querySelector('.content-imgs');
      list.__vnode={dirs:[{value:{sortList:urls.map(url => ({url})),isNeedKey:true}}]};
      [...list.querySelectorAll('img')].forEach((img,index) => {img.__vnode={dirs:[{value:urls[index]},{value:undefined}]};});
      document.querySelector('.page-content_right-top img').__vnode={props:{src:'https://fixture.invalid/native-template.gif'}};
    }""", URLS)
    yield instance
    context.close()


def _assert_closed(result):
    assert result['executionAllowed'] is False
    assert result['capabilityCertified'] is False
    assert result['inputFreezeAllowed'] is False
    assert result['sourceVersionCandidate']['verified'] is False


def test_synthetic_complete_selection_preserves_native_order_but_cannot_freeze(page):
    result = collect_native_video_dom_observation(page)
    _assert_closed(result)
    assert result['collected'] is True
    images = result['actual']['images']
    assert images['sortListCount'] == images['domCount'] == 2
    assert images['selectionConsistent'] is True
    assert images['loaded'] is True
    assert images['selectedUrlsCandidate'] == URLS
    assert result['actual']['transition']['stableValue'] is None
    assert result['actual']['transition']['candidates'][0]['previews'][0]['vnodeSrcCandidate'] == 'https://fixture.invalid/native-template.gif'
    assert result['actual']['music']['stableId'] is None
    assert result['actual']['music']['silence'] is None
    assert 'VIDEO_TRANSITION_STABLE_VALUE_MISSING' in result['missing']
    assert 'VIDEO_MUSIC_STABLE_ID_OR_SILENCE_MISSING' in result['missing']


@pytest.mark.parametrize('change,missing', [
    ("document.querySelector('.ant-modal-wrap').remove()", 'VIDEO_MODAL_NOT_UNIQUE_VISIBLE'),
    ("document.body.append(document.querySelector('.ant-modal-wrap').cloneNode(true))", 'VIDEO_MODAL_NOT_UNIQUE_VISIBLE'),
    ("document.querySelector('.ant-modal-wrap').style.display='none'", 'VIDEO_MODAL_NOT_UNIQUE_VISIBLE'),
    ("delete document.querySelector('.content-imgs').__vnode", 'VIDEO_SORT_LIST_BINDING_UNAVAILABLE'),
    ("document.querySelector('.content-imgs').__vnode.dirs.push(document.querySelector('.content-imgs').__vnode.dirs[0])", 'VIDEO_SORT_LIST_BINDING_NOT_UNIQUE'),
    ("document.querySelector('.content-imgs').__vnode.dirs[0].value.sortList.pop()", 'VIDEO_IMAGE_DOM_SORT_LIST_COUNT_DRIFT'),
    ("document.querySelector('.content-imgs').__vnode.dirs[0].value.sortList.reverse()", 'VIDEO_IMAGE_DOM_SORT_LIST_CORRESPONDENCE_UNPROVEN'),
    ("document.querySelector('.content-imgs').__vnode.dirs[0].value.sortList[1].url='https://fixture.invalid/selected-a.png'", 'VIDEO_IMAGE_SELECTION_DUPLICATE'),
    ("delete document.querySelector('.content-imgs img').__vnode", 'VIDEO_IMAGE_LAZY_URL_UNAVAILABLE'),
    ("document.querySelector('.content-imgs li').style.display='none'", 'VIDEO_SELECTED_IMAGE_NOT_VISIBLE'),
    ("document.querySelector('.page-content_right-top li').classList.remove('activeName')", 'VIDEO_TRANSITION_SELECTION_NOT_UNIQUE_VISIBLE'),
    ("document.querySelector('.page-content_right-bottom li').classList.remove('activeName')", 'VIDEO_MUSIC_SELECTION_NOT_UNIQUE_VISIBLE'),
])
def test_missing_or_ambiguous_raw_facts_are_explicit_without_guessed_values(page, change, missing):
    page.evaluate(change)
    result = collect_native_video_dom_observation(page)
    _assert_closed(result)
    assert missing in result['missing']


def test_lazy_placeholder_cannot_replace_unloaded_native_image(page):
    page.evaluate("""() => {
      const img=document.querySelector('.content-imgs img');
      Object.defineProperty(img,'complete',{value:false});
      Object.defineProperty(img,'naturalWidth',{value:0});
    }""")
    result = collect_native_video_dom_observation(page)
    assert 'VIDEO_IMAGE_NOT_LOADED' in result['missing']
    assert result['actual']['images']['loaded'] is False
    assert result['actual']['images']['selectedUrlsCandidate'] is None
    _assert_closed(result)


def test_loaded_placeholder_url_drift_is_not_a_complete_selected_input(page):
    page.evaluate("Object.defineProperty(document.querySelector('.content-imgs img'),'currentSrc',{value:'https://fixture.invalid/placeholder.png'})")
    result = collect_native_video_dom_observation(page)
    assert 'VIDEO_IMAGE_LOADED_URL_DRIFT' in result['missing']
    assert result['actual']['images']['selectedUrlsCandidate'] is None


def test_more_than_native_limit_cannot_be_silently_truncated_to_complete_inputs(page):
    page.evaluate("""() => {
      const list=document.querySelector('.content-imgs');
      list.__vnode.dirs[0].value.sortList=Array.from({length:9},(_,index) => ({url:'https://fixture.invalid/'+index+'.png'}));
    }""")
    result = collect_native_video_dom_observation(page)
    assert result['actual']['images']['sortListCount'] == 9
    assert result['actual']['images']['sortListUrlsCandidate'] is None
    assert result['actual']['images']['selectedUrlsCandidate'] is None
    assert 'VIDEO_IMAGE_COLLECTION_OVER_LIMIT' in result['missing']
    _assert_closed(result)


def test_multiple_lazy_url_bindings_are_not_resolved_by_first_match(page):
    page.evaluate("document.querySelector('.content-imgs img').__vnode.dirs.push({value:'https://fixture.invalid/another.png'})")
    result = collect_native_video_dom_observation(page)
    assert 'VIDEO_IMAGE_LAZY_URL_NOT_UNIQUE' in result['missing']
    assert result['actual']['images']['selectedUrlsCandidate'] is None
    _assert_closed(result)


def test_framework_property_read_failure_is_caught_logged_and_never_grants_authority(page, caplog):
    page.evaluate("Object.defineProperty(document.querySelector('.content-imgs'),'__vnode',{get(){throw Error('unavailable property')}})")
    result = collect_native_video_dom_observation(page)
    assert result['collected'] is False
    assert result['errorType'] == 'Error'
    assert 'VIDEO_DOM_OBSERVATION_FAILED' in result['missing']
    assert any(record.levelname == 'ERROR' and record.message == 'native_video_dom_diagnostic_incomplete' for record in caplog.records)
    _assert_closed(result)


def test_source_filename_is_only_a_candidate_not_byte_identity(page):
    page.evaluate("""() => {
      Object.defineProperty(performance,'getEntriesByType',{value:() => [{name:'https://fixture.invalid/ImgToVideoModal-Cn4d-6zD.js?token=private'}, {name:'https://fixture.invalid/const-BvIXJGkR.js'}]});
      window.callerMap={transition:0,music:{mode:'none'}};
    }""")
    result = collect_native_video_dom_observation(page)
    _assert_closed(result)
    assert len(result['sourceVersionCandidate']['observedAssets']) == 2
    assert all('token=' not in value for value in result['sourceVersionCandidate']['observedAssets'])
    assert 'SOURCE_VERSION_NOT_VERIFIED' in result['missing']
    assert result['actual']['transition']['stableValue'] is None
    assert result['actual']['music']['silence'] is None


def test_collector_does_not_mutate_dom_call_handlers_or_start_requests(page):
    requests = []
    page.on('request', lambda request: requests.append(request.url))
    page.evaluate("""() => {
      window.observedMutations=[];
      window.observer=new MutationObserver(records => observedMutations.push(...records.map(record => record.type)));
      observer.observe(document.body,{subtree:true,attributes:true,childList:true,characterData:true});
      const reject=() => {throw Error('diagnostic attempted an effect')};
      window.fetch=reject; window.XMLHttpRequest=reject; window.WebSocket=reject;
      Element.prototype.click=reject; Element.prototype.setAttribute=reject;
      document.querySelectorAll('li').forEach(el => {el.onclick=reject});
      document.querySelector('.content-imgs').__vnode.dirs[0].value.updateKey=reject;
    }""")
    result = collect_native_video_dom_observation(page)
    assert result['collected'] is True
    assert page.evaluate('observedMutations') == []
    assert requests == []
    _assert_closed(result)


def test_boundary_logs_page_failure_and_returns_closed_diagnostic(caplog):
    def fail(_script):
        raise RuntimeError('page unavailable')

    result = collect_native_video_dom_observation(SimpleNamespace(evaluate=fail))
    assert result['collected'] is False
    assert result['inputFreezeAllowed'] is False
    assert result['missing'] == ['VIDEO_DOM_DIAGNOSTIC_FAILED']
    assert 'native_video_dom_diagnostic_failed' in caplog.text


def test_boundary_rejects_a_page_result_that_claims_freeze_authority(caplog):
    result = collect_native_video_dom_observation(SimpleNamespace(evaluate=lambda _: {
        'schema':'dxm.native_video_dom_diagnostic.v1','executionAllowed':False,
        'capabilityCertified':False,'inputFreezeAllowed':True,
    }))
    assert result['collected'] is False and result['inputFreezeAllowed'] is False
    assert 'native_video_dom_diagnostic_failed' in caplog.text


@pytest.mark.parametrize('changes', [
    {'collected': 'true'}, {'collected': 1}, {'missing': None}, {'missing': []},
    {'missing': ['private token=value']}, {'missing': ['']}, {'missing': ['SAME', 'SAME']},
    {'actual': []},
])
def test_wrapper_requires_boolean_collection_and_nonempty_canonical_missing_codes(changes, caplog):
    raw = {'schema':'dxm.native_video_dom_diagnostic.v1', 'collected':True, 'actual':{},
           'executionAllowed':False, 'capabilityCertified':False, 'inputFreezeAllowed':False,
           'missing':['SOURCE_VERSION_NOT_VERIFIED'], **changes}
    result = collect_native_video_dom_observation(SimpleNamespace(evaluate=lambda _: raw))
    assert result['collected'] is False
    assert result['missing'] == ['VIDEO_DOM_DIAGNOSTIC_FAILED']
    assert 'native_video_dom_diagnostic_failed' in caplog.text
