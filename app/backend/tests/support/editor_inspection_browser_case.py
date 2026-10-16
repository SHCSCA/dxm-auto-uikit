"""实际 Chromium 与唯一传输配合合成回复；不访问 DXM，不证明现场资源或控件。"""

import base64
import hashlib
import json
import threading
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from playwright.sync_api import Page

from src.execution import editor_inspection_flow, editor_inspection_scope, native_video_script_capture
from src.execution.dxm_login_flow import DxmLoginFlow, DXM_E2_PLAN_READ_ALLOWLIST
from src.execution.editor_readonly_inspection import make_editor_readonly_guard
from src.execution.managed_browser_context import create_managed_browser_context
from src.execution.manual_login_context import ManualLoginContext
from src.execution.native_video_transport import require_native_video_transport
from src.execution.native_video_value_bindings import TRANSITION_GIFS
from src.services.dxm_plan_reader import DxmPlanReader


URL = 'https://www.dianxiaomi.com/web/smt/edit?id=8101'
URLS = ['https://fixture.invalid/a.png', 'https://fixture.invalid/b.png']
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aVS0AAAAASUVORK5CYII=')


def html(*, early_native=False, reveal_script='', bindings=True):
    scripts = ''.join(f'<script src="{native_video_script_capture.PUBLIC_ASSET_BASE}{name}"></script>'
        for name in native_video_script_capture.REVIEWED_VIDEO_SCRIPTS)
    transitions = ''.join(f'<li class="{"activeName" if value == 4 else ""}"><img src="{gif}"></li>'
        for value, gif in enumerate(TRANSITION_GIFS))
    images = ''.join(f'<li><img src="{url}"></li>' for url in URLS)
    template = '''<meta charset="utf-8"><link rel="icon" href="data:,">
<style>div,li,input,button{min-height:8px;min-width:8px}img{width:3px;height:3px}</style>
__SCRIPTS__<script>window.firstLifetime=window.__dxmNativeVideoReadonlyLifetimeV1?.();</script>
<div class="product-add-wrapper"><input name="subject" value="Synthetic title">
<input name="sourceUrl" value="https://fixture.invalid/product">
<div class="header"><div class="btn-box"><button class="translation-btn">一键翻译</button></div></div>
<div class="video-operate"><button>图片生成视频</button></div></div>
<div class="ant-modal-wrap" role="dialog" style="display:none"><div class="ant-modal-header"><button id="modal-header">header</button></div>
<div class="img-translate-video"><ul class="content-imgs">__IMAGES__</ul>
<div class="page-content_right-top"><ul class="content-list">__TRANSITIONS__</ul></div>
<div class="page-content_right-bottom"><ul class="content-list"><li class="activeName"><div><span>arbitrary</span></div><i></i></li>
<li><div><span>library</span></div></li></ul></div></div></div>
<div class="ant-popover" style="display:none"><div class="translate-panel">translation</div></div>
<script>(()=>{
const urls=__URLS__,type={__name:'ImgToVideoModal'},owner={uid:7,type,vnode:{type},isMounted:true,isUnmounted:false,props:{visible:false}};
if(__BINDINGS__){
const bind=el=>el.__vnode={el,ctx:owner,type:el.tagName.toLowerCase(),props:{class:el.className}};
document.querySelectorAll('.img-translate-video,.content-imgs,li,img').forEach(bind);
const list=document.querySelector('.content-imgs');list.__vnode.dirs=[{value:{sortList:urls.map(url=>({url})),isNeedKey:true,updateKey:()=>{throw Error('forbidden')}}}];
[...list.querySelectorAll('img')].forEach((img,index)=>img.__vnode.dirs=[{value:urls[index]}]);
document.querySelectorAll('.page-content_right-top img').forEach(img=>img.__vnode.props.src=img.getAttribute('src'));
const row=document.querySelector('.page-content_right-bottom li'),group=row.firstElementChild,span=group.firstElementChild;
bind(group);bind(span);const comment=document.createComment('');group.insertBefore(comment,span);
group.__vnode.children=[{type:Symbol.for('v-cmt'),children:'',ctx:owner,el:comment},span.__vnode];row.__vnode.children=[group.__vnode,{type:'native-icon'}];}
const read=(path,body,type)=>fetch(path,{method:'POST',headers:{'Content-Type':type},body}).then(r=>r.json()).catch(()=>null);
window.nativeReads=()=>Promise.all([read('/api/picToVideo/backMusicList.json','{}','application/json'),
read('/api/picToVideo/getCountInfo.json','{}','application/json'),read('/api/midou/valueService/balanceView.json','types=17','application/x-www-form-urlencoded')]);
document.querySelector('.video-operate button').onclick=()=>{owner.props.visible=true;document.querySelector('[role=dialog]').style.display='block';window.nativeReads();__REVEAL__};
document.querySelector('.translation-btn').onclick=()=>document.querySelector('.ant-popover').style.display='block';
if(__EARLY__)window.nativeReads();window.formChanges=[];new MutationObserver(r=>formChanges.push(...r)).observe(document.querySelector('.product-add-wrapper'),{subtree:true,attributes:true,childList:true,characterData:true});
})();</script>'''
    for key, value in {'SCRIPTS': scripts, 'IMAGES': images, 'TRANSITIONS': transitions, 'URLS': json.dumps(URLS),
            'BINDINGS': str(bindings).lower(), 'REVEAL': reveal_script, 'EARLY': str(early_native).lower()}.items():
        template = template.replace('__' + key + '__', value)
    return template


@contextmanager
def inspection_browser_case(browser, tmp_path, monkeypatch, **html_options):
    context = create_managed_browser_context(browser)
    primary = context.new_page()
    def prepare_home(route):
        route.fulfill(status=200, content_type='text/html', body='<link rel="icon" href="data:,"><body>Synthetic home</body>')
    context.route('https://www.dianxiaomi.com/web/home', prepare_home)
    primary.goto('https://www.dianxiaomi.com/web/home')
    context.unroute('https://www.dianxiaomi.com/web/home', prepare_home)
    flow = DxmLoginFlow(None, state_file=tmp_path / 'synthetic-state.json')
    flow._browser, flow._context, flow._page = browser, context, primary
    flow._browser_session_thread_id = threading.get_ident()
    session = flow._bind_browser_context_generation(context)
    pinned = ManualLoginContext(browser, threading.get_ident())
    pinned.context, pinned.session_id = context, session
    flow._managed_manual_login = pinned
    production_owner = object(); flow._native_video_lifetime = production_owner
    replies, delivered, screenshots = {}, [], []
    original_screenshot = Page.screenshot

    def screenshot(page, **kwargs):
        result = original_screenshot(page, **kwargs)
        screenshots.append(page.evaluate('({firstLifetime,formChanges:formChanges.length})'))
        return result

    monkeypatch.setattr(Page, 'screenshot', screenshot)
    specs = {}
    for index, name in enumerate(native_video_script_capture.REVIEWED_VIDEO_SCRIPTS):
        body = f'window.syntheticSource{index}=true;'.encode()
        replies[native_video_script_capture.PUBLIC_ASSET_BASE + name] = ('application/javascript', body)
        specs[name] = (len(body), hashlib.sha256(body).hexdigest().upper())
    monkeypatch.setattr(native_video_script_capture, 'REVIEWED_VIDEO_SCRIPTS', specs)
    replies[URL] = ('text/html', html(**html_options).encode())

    class OfflineReply:
        def __init__(self, route, reject, require_live):
            self.route, self.request, self.reject, self.require_live = route, route.request, reject, require_live

        def abort(self):
            self.route.abort()

        def continue_(self):
            self.require_live()
            delivered.append((self.request.method, self.request.url, self.request.post_data))
            content_type, body = replies.get(self.request.url, ('image/png', PNG) if self.request.resource_type == 'image'
                else ('application/json', b'{}'))
            # 仅替换本机回复边界；原始浏览器请求仍经过实际 scope 的完整判定。
            self.route.fulfill(status=200, headers={'Content-Type': content_type, 'Content-Length': str(len(body))}, body=body)
            self.require_live()

    monkeypatch.setattr(editor_inspection_scope, 'NativeVideoSafeRoute', OfflineReply)
    monkeypatch.setattr(editor_inspection_flow, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(editor_inspection_flow, 'SCREENSHOT_DIR', tmp_path / 'screenshots')
    envelope, reader_calls = {'synthetic': 'reader'}, []

    def read(**kwargs):
        assert kwargs == {'shop_id': '91', 'product_ids': ['8101']}
        reader_calls.append(len(context.pages))
        return deepcopy(envelope)

    monkeypatch.setattr(flow, 'read_e2_product_details', read)
    monkeypatch.setattr(DxmPlanReader, '_validated_envelope', staticmethod(lambda _: (session, 'synthetic-account', {'products': [{}]})))
    monkeypatch.setattr(DxmPlanReader, '_session_ref', staticmethod(lambda *_: 'synthetic-session-ref'))
    monkeypatch.setattr(DxmPlanReader, '_validated_product_detail', staticmethod(lambda _, **__: ('8101',
        {'subject': 'Synthetic title', 'sourceUrl': 'https://fixture.invalid/product', 'categoryId': '17'})))
    root = Path(__file__).resolve().parents[4]
    guard = make_editor_readonly_guard(root / 'tools/probes/l2_readonly_probe.py', root / 'config/l2_readonly_allowlist.json', DXM_E2_PLAN_READ_ALLOWLIST)
    transport = require_native_video_transport(primary)
    try:
        yield SimpleNamespace(flow=flow, context=context, primary=primary, guard=guard, transport=transport,
            delivered=delivered, reader_calls=reader_calls, production_owner=production_owner, replies=replies,
            prepare_home=prepare_home, screenshots=screenshots)
    finally:
        context.close()


def inspect(case, dialog='video'):
    return case.flow.inspect_editor_readonly(shop_id='91', product_id='8101', session_ref='synthetic-session-ref',
        guard=case.guard, observe_dialog=dialog)
