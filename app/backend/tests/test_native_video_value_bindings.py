"""本机合成 VNode 的 Chromium 负例；通过不代表生产会暴露内部绑定。"""

import base64
from types import SimpleNamespace

import pytest
from playwright.sync_api import sync_playwright

from src.execution.native_video_value_bindings import collect_native_video_value_bindings, validate_value_bindings, TRANSITION_GIFS
from tests.support.native_video_observation_case import make_bindings


PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aVS0AAAAASUVORK5CYII=')
URLS = ['https://fixture.invalid/a.png', 'https://fixture.invalid/b.png']


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
    page = context.new_page()
    transitions = ''.join(f'<li class="{"activeName" if value == 4 else ""}"><img src="{gif}"></li>'
                          for value, gif in enumerate(TRANSITION_GIFS))
    page.set_content(f'''<style>div,li {{display:block;min-height:8px;min-width:8px}} img {{width:3px;height:3px}}</style>
      <div class="ant-modal-wrap" role="dialog"><div class="img-translate-video">
      <ul class="content-imgs">{''.join(f'<li><img src="{url}"></li>' for url in URLS)}</ul>
      <div class="page-content_right-top"><ul class="content-list">{transitions}</ul></div>
      <div class="page-content_right-bottom"><ul class="content-list"><li class="activeName"><div><span>arbitrary label</span></div><i></i></li>
      <li><div><span>library</span></div></li><li>copyright</li></ul></div></div></div>''')
    page.wait_for_function('Array.from(document.images).every(img => img.complete && img.naturalWidth>0)')
    page.evaluate('''urls=>{
      const type={__name:'ImgToVideoModal'};
      window.owner={uid:7,type,vnode:{type},isMounted:true,isUnmounted:false,props:{visible:true}};
      const bind=el=>el.__vnode={el,ctx:owner,type:el.tagName.toLowerCase(),props:{class:el.className}};
      document.querySelectorAll('.img-translate-video,.content-imgs,li,img').forEach(bind);
      const list=document.querySelector('.content-imgs');
      list.__vnode.dirs=[{value:{sortList:urls.map(url=>({url})),isNeedKey:true,updateKey:()=>{throw Error('not callable')}}}];
      [...list.querySelectorAll('img')].forEach((img,index)=>img.__vnode.dirs=[{value:urls[index]},{value:undefined}]);
      document.querySelectorAll('.page-content_right-top img').forEach(img=>img.__vnode.props.src=img.getAttribute('src'));
      const row=document.querySelector('.page-content_right-bottom li'),group=row.firstElementChild,span=group.firstElementChild;
      bind(group);bind(span);
      const comment=document.createComment('');group.insertBefore(comment,span);
      const branch={type:Symbol.for('v-cmt'),children:'',ctx:owner,el:comment};
      group.__vnode.children=[branch,span.__vnode];row.__vnode.children=[group.__vnode,{type:'native-icon'}];
    }''', URLS)
    yield page
    context.close()


def test_full_native_sequence_exact_gif_and_actual_conditional_branch_are_read_without_labels(page):
    result = collect_native_video_value_bindings(page)
    assert result['missing'] == [] and result['collected'] is True
    inputs = validate_value_bindings(result)
    assert inputs == {'images': URLS, 'transition': 4, 'music': {'mode': 'none'}}
    assert result['document_time_origin'] > 0
    assert all(result[key] is False for key in ('executionAllowed', 'capabilityCertified', 'inputFreezeAllowed'))


@pytest.mark.parametrize('change,reason', [
    ("delete document.querySelector('.content-imgs').__vnode", 'COMPONENT_BINDING_UNAVAILABLE'),
    ("owner.type.__name='OtherModal'", 'COMPONENT_BINDING_UNAVAILABLE'),
    ("owner.props.visible=false", 'COMPONENT_BINDING_UNAVAILABLE'),
    ("document.querySelector('.content-imgs').__vnode.ctx={...owner}", 'COMPONENT_BINDING_UNAVAILABLE'),
    ("document.querySelector('.content-imgs').__vnode.dirs[0].value.sortList.reverse()", 'ORDER_OR_COMPLETENESS'),
    ("document.querySelector('.content-imgs img').__vnode.dirs=[]", 'LAZY_BINDING_UNAVAILABLE'),
    ("document.querySelector('.content-imgs li').remove()", 'COLLECTION_INCOMPLETE'),
    ("Object.defineProperty(document.querySelector('.content-imgs img'),'complete',{value:false})", 'LOAD_OR_URL_UNPROVEN'),
    ("document.querySelector('.page-content_right-top img').__vnode.props.src+='?cdn=changed'", 'NATIVE_GIF_UNPROVEN'),
    ("document.querySelector('.page-content_right-top li').classList.add('activeName')", 'ACTIVE_BINDING_DRIFT'),
    ("document.querySelector('.page-content_right-top li').remove()", 'COLLECTION_UNPROVEN'),
    ("document.querySelector('.page-content_right-bottom li').__vnode.children[0].children[0].type={__name:'PlayerMusic'}", 'STABLE_ID_OR_NATIVE_NONE'),
    ("document.querySelector('.page-content_right-bottom li').__vnode.children[0].children[0].el.remove()", 'STABLE_ID_OR_NATIVE_NONE'),
    ("document.querySelector('.page-content_right-bottom li').__vnode.props.class=''", 'ACTIVE_BINDING_UNPROVEN'),
])
def test_unavailable_or_drifted_native_facts_fail_closed_without_position_fallback(page, change, reason):
    page.evaluate(change)
    result = collect_native_video_value_bindings(page)
    assert any(reason in code for code in result['missing'])
    with pytest.raises(ValueError):
        validate_value_bindings(result)
    assert result['inputFreezeAllowed'] is False


def test_audio_playback_and_native_label_are_not_selected_music_authority(page):
    page.evaluate('''()=>{
      const audio=document.createElement('audio');audio.setAttribute('src','https://fixture.invalid/unrelated-preview.mp3');
      document.querySelector('.img-translate-video').append(audio);
      document.querySelector('.page-content_right-bottom span').textContent='music99';
    }''')
    result = collect_native_video_value_bindings(page)
    assert validate_value_bindings(result)['music'] == {'mode': 'none'}


def test_transition_dom_position_is_not_used_as_native_value(page):
    page.evaluate('''()=>{
      const list=document.querySelector('.page-content_right-top .content-list');
      [...list.children].reverse().forEach(row=>list.append(row));
    }''')
    result = collect_native_video_value_bindings(page)
    assert validate_value_bindings(result)['transition'] == 4


def test_framework_property_failure_is_caught_and_logged_as_error(page, caplog):
    page.evaluate("Object.defineProperty(document.querySelector('.content-imgs'),'__vnode',{get(){throw Error('unavailable')}})")
    result = collect_native_video_value_bindings(page)
    assert result['collected'] is False and result['missing'] == ['VIDEO_NATIVE_VALUE_READ_FAILED']
    assert any(record.levelname == 'ERROR' and record.message == 'native_video_values_incomplete' for record in caplog.records)


def test_read_does_not_mutate_dom_call_callbacks_or_initiate_requests(page):
    requests = []
    page.on('request', lambda request: requests.append(request.url))
    page.evaluate('''()=>{
      window.mutations=[];window.watch=new MutationObserver(items=>mutations.push(...items));
      watch.observe(document.body,{subtree:true,attributes:true,childList:true,characterData:true});
      const reject=()=>{throw Error('unexpected effect')};window.fetch=reject;window.XMLHttpRequest=reject;
      Element.prototype.click=reject;document.querySelectorAll('li').forEach(el=>el.onclick=reject);
    }''')
    assert collect_native_video_value_bindings(page)['missing'] == []
    assert page.evaluate('mutations.length') == 0 and requests == []


@pytest.mark.parametrize('change', [
    lambda value: value['images']['dom_urls'].reverse(),
    lambda value: value['images']['sort_list_urls'].append(value['images']['sort_list_urls'][0]),
    lambda value: value['transition']['options'][0].update(raw_gif=TRANSITION_GIFS[1]),
    lambda value: value['transition'].update(selected_value=True),
    lambda value: value['music'].update(stable_id='caller-id'),
    lambda value: value['music'].update(none_branch_observed=False),
    lambda value: value['music'].update(none_branch_observed=1),
    lambda value: value.update(inputFreezeAllowed=True),
    lambda value: value['instance'].update(uid=2 ** 53),
    lambda value: value['images'].update(sort_list_urls=['https://fixture.invalid/a\nb.png', 'https://fixture.invalid/b.png'],
        dom_urls=['https://fixture.invalid/a\nb.png', 'https://fixture.invalid/b.png'],
        loaded_urls=['https://fixture.invalid/a\nb.png', 'https://fixture.invalid/b.png']),
])
def test_pure_shape_validator_does_not_accept_partial_or_caller_remapped_values(change):
    value = make_bindings()
    change(value)
    with pytest.raises(ValueError):
        validate_value_bindings(value)


def test_read_error_is_logged_and_does_not_escape_or_claim_authority(caplog):
    def fail(_script):
        raise RuntimeError('page closed')

    result = collect_native_video_value_bindings(SimpleNamespace(evaluate=fail))
    assert result['collected'] is False and result['missing'] == ['VIDEO_NATIVE_VALUE_READ_FAILED']
    assert result['inputFreezeAllowed'] is False and 'native_video_values_failed' in caplog.text


def test_incomplete_envelope_cannot_smuggle_an_authorization_flag(caplog):
    result = collect_native_video_value_bindings(SimpleNamespace(evaluate=lambda _: {
        'schema': 'dxm.native_video_value_bindings.v1', 'collected': False, 'missing': ['UNAVAILABLE'],
        'executionAllowed': False, 'capabilityCertified': False, 'inputFreezeAllowed': True}))
    assert result['inputFreezeAllowed'] is False and result['missing'] == ['VIDEO_NATIVE_VALUE_READ_FAILED']
