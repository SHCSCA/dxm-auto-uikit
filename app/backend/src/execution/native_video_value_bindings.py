"""读取已审原生组件的实际绑定；单独结果不提供来源、冻结或执行授权。"""

from copy import deepcopy
import re
from urllib.parse import urlsplit

from src.services.structured_logging import get_logger, log_event, log_exception


SCHEMA = 'dxm.native_video_value_bindings.v1'
PROFILE = 'dxm.public_video.2026-09.v1'
_LOGGER = get_logger('native_video.value_bindings')
# 固定映射来自已审 const 资源；精确原始 URL 是键，不能按标签、位置或 CDN 改写猜测。
TRANSITION_GIFS = (
    'http://wxmark-10001658.picsh.myqcloud.com/wxmark/232073/20201120104404/1fbc3d89ec052790989cf0ecf96dbad4.gif',
    'http://wxmark-10001658.picsh.myqcloud.com/wxmark/232073/20201120102101/6a424a5ddd67288ceaac15747d6052ab.gif',
    'http://wxmark-10001658.picsh.myqcloud.com/wxmark/232073/20201120102445/0c08c7de419743a3a8a0b24a8b9a3e65.gif',
    'http://wxmark-10001658.picsh.myqcloud.com/wxmark/232073/20201120102502/a8e8e8b28946f73a39150fc86a05109d.gif',
    'http://wxmark-10001658.picsh.myqcloud.com/wxmark/232073/20201120102511/6b262d665539eaa237965c7f471374c0.gif',
    'http://wxmark-10001658.picsh.myqcloud.com/wxmark/232073/20201120102524/699de351f11247cfc7938fc6efeb6e84.gif',
    'http://wxmark-10001658.picsh.myqcloud.com/wxmark/232073/20201120102541/82076c60282c258e58be2a26548e1c94.gif',
)
_SCRIPT = r"""() => {
  const result={schema:'dxm.native_video_value_bindings.v1',collected:false,missing:[],document_time_origin:performance.timeOrigin,
    instance:null,images:null,transition:null,music:null,
    executionAllowed:false,capabilityCertified:false,inputFreezeAllowed:false};
  const fail=code=>{if(!result.missing.includes(code))result.missing.push(code);};
  const visible=el=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el);return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden';};
  const validUrl=value=>{try{const u=new URL(value);return typeof value==='string'&&value===value.trim()&&!value.includes(',')&&['https:','http:'].includes(u.protocol)&&!u.username&&!u.password;}catch{return false;}};
  const owned=(el,owner)=>el?.__vnode?.el===el&&el.__vnode.ctx===owner;
  const dirs=el=>Array.isArray(el?.__vnode?.dirs)?el.__vnode.dirs:[];
  const active=el=>el.classList.contains('activeName')&&String(el.__vnode?.props?.class||'').split(/\s+/).includes('activeName');
  const gifs=__TRANSITION_GIFS__;
  try{
    const roots=[...document.querySelectorAll('.ant-modal-wrap[role="dialog"]')].filter(el=>visible(el)&&el.querySelector('.img-translate-video'));
    if(roots.length!==1){fail('VIDEO_MODAL_NOT_UNIQUE_VISIBLE');return result;}
    const contents=[...roots[0].querySelectorAll('.img-translate-video')];
    if(contents.length!==1||!visible(contents[0])){fail('VIDEO_CONTENT_NOT_UNIQUE_VISIBLE');return result;}
    const content=contents[0],lists=[...content.querySelectorAll('.content-imgs')];
    if(lists.length!==1||!visible(lists[0])){fail('VIDEO_IMAGE_LIST_NOT_UNIQUE_VISIBLE');return result;}
    const list=lists[0],owner=list.__vnode?.ctx;
    if(!owner||!Number.isSafeInteger(owner.uid)||owner.uid<0||owner.type?.__name!=='ImgToVideoModal'
      ||owner.vnode?.type!==owner.type||owner.isMounted!==true||owner.isUnmounted!==false||owner.props?.visible!==true
      ||!owned(list,owner)||!owned(content,owner)){fail('VIDEO_NATIVE_COMPONENT_BINDING_UNAVAILABLE');return result;}
    result.instance={uid:owner.uid,type_name:owner.type.__name,mounted:true,visible:true,vnode_dom_bound:true};
    const bindings=dirs(list).filter(b=>b.value&&typeof b.value==='object'&&Array.isArray(b.value.sortList));
    if(bindings.length!==1){fail('VIDEO_SORT_LIST_BINDING_UNAVAILABLE');return result;}
    const binding=bindings[0].value,rows=[...list.children];
    if(Object.keys(binding).sort().join(',')!=='isNeedKey,sortList,updateKey'||binding.isNeedKey!==true||typeof binding.updateKey!=='function')fail('VIDEO_SORT_LIST_NATIVE_SHAPE_INVALID');
    if(rows.length<2||rows.length>8||rows.length!==binding.sortList.length||rows.some(el=>el.tagName!=='LI')){fail('VIDEO_IMAGE_COLLECTION_INCOMPLETE');return result;}
    const selected=binding.sortList.map(item=>item?.url);
    const dom=[],loaded=[];
    for(const row of rows){
      const imgs=[...row.querySelectorAll('img')];
      if(!visible(row)||!owned(row,owner)||imgs.length!==1){fail('VIDEO_IMAGE_NODE_BINDING_INVALID');continue;}
      const img=imgs[0],urls=dirs(img).map(b=>b.value).filter(validUrl);
      if(!owned(img,owner)||urls.length!==1){fail('VIDEO_IMAGE_LAZY_BINDING_UNAVAILABLE');continue;}
      dom.push(urls[0]);loaded.push(img.currentSrc);
      if(!visible(img)||!img.complete||img.naturalWidth<=0||img.naturalHeight<=0||img.currentSrc!==urls[0])fail('VIDEO_IMAGE_LOAD_OR_URL_UNPROVEN');
    }
    if(selected.some(value=>!validUrl(value))||new Set(selected).size!==selected.length
      ||JSON.stringify(selected)!==JSON.stringify(dom)||JSON.stringify(dom)!==JSON.stringify(loaded))fail('VIDEO_IMAGE_ORDER_OR_COMPLETENESS_UNPROVEN');
    result.images={sort_list_urls:selected,dom_urls:dom,loaded_urls:loaded};
    const transitions=[...content.querySelectorAll('.page-content_right-top .content-list > li')];
    if(transitions.length!==7){fail('VIDEO_TRANSITION_COLLECTION_UNPROVEN');return result;}
    const options=[];
    for(const row of transitions){
      const imgs=[...row.querySelectorAll('img')],img=imgs[0],raw=img?.__vnode?.props?.src,value=gifs.indexOf(raw);
      if(!visible(row)||!owned(row,owner)||imgs.length!==1||!owned(img,owner)||value<0)fail('VIDEO_TRANSITION_NATIVE_GIF_UNPROVEN');
      options.push({raw_gif:typeof raw==='string'?raw:null,value,active:active(row)});
      if(row.classList.contains('activeName')!==active(row))fail('VIDEO_TRANSITION_ACTIVE_BINDING_DRIFT');
    }
    const selectedTransitions=options.filter(option=>option.active);
    if(options.length!==7||new Set(options.map(option=>option.value)).size!==7||selectedTransitions.length!==1)fail('VIDEO_TRANSITION_COLLECTION_UNPROVEN');
    result.transition={options,selected_value:selectedTransitions.length===1?selectedTransitions[0].value:null};
    const musicRows=[...content.querySelectorAll('.page-content_right-bottom .content-list > li')];
    const selectedMusic=musicRows.filter(row=>row.classList.contains('activeName'));
    result.music={active_count:selectedMusic.length,none_branch_observed:false,stable_id:null};
    if(selectedMusic.length!==1||!visible(selectedMusic[0])||!owned(selectedMusic[0],owner)||!active(selectedMusic[0]))fail('VIDEO_MUSIC_ACTIVE_BINDING_UNPROVEN');
    else{
      const row=selectedMusic[0],children=row.__vnode.children,group=Array.isArray(children)?children[0]:null;
      const branch=Array.isArray(group?.children)?group.children[0]:null,span=group?.children?.[1];
      // 精确 false 分支是原生 Comment VNode；不读标签、列表 key 或 audio 播放状态。
      const none=children?.length===2&&group?.type==='div'&&group.el===row.firstElementChild&&group.ctx===owner
        &&group.children.length===2&&branch?.type===Symbol.for('v-cmt')&&branch.children===''
        &&branch.ctx===owner&&branch.el?.nodeType===8&&branch.el.parentNode===group.el
        &&branch.el===group.el.firstChild&&branch.el.textContent===''
        &&span?.type==='span'&&span.ctx===owner&&span.el===group.el.lastElementChild;
      result.music.none_branch_observed=none;
      if(!none)fail('VIDEO_MUSIC_STABLE_ID_OR_NATIVE_NONE_UNPROVEN');
    }
    result.collected=true;
  }catch(error){fail('VIDEO_NATIVE_VALUE_READ_FAILED');result.error_type=String(error?.name||'UnknownError');}
  return result;
}"""


def native_video_value_bindings_script():
    """只嵌入仓内固定已审映射，调用方不能提供候选值或覆盖来源。"""
    import json
    return _SCRIPT.replace('__TRANSITION_GIFS__', json.dumps(TRANSITION_GIFS))


def validate_value_bindings(value):
    """纯结构校验须由持久 Worker 来源和完整生命周期另行绑定。"""
    def require(condition, code):
        if not condition:
            raise ValueError(code)

    require(isinstance(value, dict) and set(value) == {'schema', 'collected', 'missing', 'instance', 'images', 'document_time_origin',
        'transition', 'music', 'executionAllowed', 'capabilityCertified', 'inputFreezeAllowed'}, 'VIDEO_VALUE_BINDINGS_SHAPE_INVALID')
    require(value['schema'] == SCHEMA and value['collected'] is True and value['missing'] == []
        and all(value[key] is False for key in ('executionAllowed', 'capabilityCertified', 'inputFreezeAllowed')), 'VIDEO_VALUE_BINDINGS_INCOMPLETE')
    import math
    require(type(value['document_time_origin']) in {int, float} and math.isfinite(value['document_time_origin'])
        and value['document_time_origin'] > 0, 'VIDEO_VALUE_DOCUMENT_IDENTITY_INVALID')
    instance = value['instance']
    require(isinstance(instance, dict) and set(instance) == {'uid', 'type_name', 'mounted', 'visible', 'vnode_dom_bound'}
        and type(instance['uid']) is int and 0 <= instance['uid'] < 2 ** 53 and instance['type_name'] == 'ImgToVideoModal'
        and all(instance[key] is True for key in ('mounted', 'visible', 'vnode_dom_bound')), 'VIDEO_VALUE_COMPONENT_INVALID')
    images = value['images']
    require(isinstance(images, dict) and set(images) == {'sort_list_urls', 'dom_urls', 'loaded_urls'}, 'VIDEO_VALUE_IMAGES_INVALID')
    urls = images['sort_list_urls']
    require(isinstance(urls, list) and 2 <= len(urls) <= 8 and all(isinstance(url, str) for url in urls)
        and len(set(urls)) == len(urls) and images['dom_urls'] == urls == images['loaded_urls'], 'VIDEO_VALUE_IMAGE_ORDER_DRIFT')
    for url in urls:
        parsed = urlsplit(url)
        require(url == url.strip() and ',' not in url and not any(ord(character) <= 32 for character in url)
            and parsed.scheme in {'http', 'https'} and bool(parsed.netloc)
            and parsed.username is None and parsed.password is None, 'VIDEO_VALUE_IMAGE_URL_INVALID')
    transition = value['transition']
    require(isinstance(transition, dict) and set(transition) == {'options', 'selected_value'}
        and type(transition['selected_value']) is int and transition['selected_value'] in range(7)
        and isinstance(transition['options'], list) and len(transition['options']) == 7, 'VIDEO_VALUE_TRANSITION_INVALID')
    active, seen = [], set()
    for option in transition['options']:
        require(isinstance(option, dict) and set(option) == {'raw_gif', 'value', 'active'}
            and type(option['value']) is int and option['value'] in range(7) and type(option['active']) is bool
            and option['raw_gif'] == TRANSITION_GIFS[option['value']], 'VIDEO_VALUE_TRANSITION_GIF_DRIFT')
        seen.add(option['value'])
        if option['active']:
            active.append(option['value'])
    require(seen == set(range(7)) and active == [transition['selected_value']], 'VIDEO_VALUE_TRANSITION_ACTIVE_DRIFT')
    music = value['music']
    require(isinstance(music, dict) and set(music) == {'active_count', 'none_branch_observed', 'stable_id'}
        and type(music['active_count']) is int and music['active_count'] == 1
        and music['none_branch_observed'] is True and music['stable_id'] is None, 'VIDEO_VALUE_MUSIC_STABLE_BINDING_REQUIRED')
    return {'images': deepcopy(urls), 'transition': transition['selected_value'], 'music': {'mode': 'none'}}


def collect_native_video_value_bindings(page):
    """固定只读脚本不点击、不调用原生处理器、不发请求；异常按统一日志降为缺证。"""
    try:
        result = page.evaluate(native_video_value_bindings_script())
        if (not isinstance(result, dict) or result.get('schema') != SCHEMA or type(result.get('collected')) is not bool
                or any(result.get(key) is not False for key in ('executionAllowed', 'capabilityCertified', 'inputFreezeAllowed'))
                or not isinstance(result.get('missing'), list)
                or any(not isinstance(code, str) or re.fullmatch('[A-Z][A-Z0-9_]{0,119}', code) is None for code in result['missing'])
                or len(set(result['missing'])) != len(result['missing'])
                or result['collected'] is False and not result['missing']):
            raise ValueError('VIDEO_VALUE_READ_ENVELOPE_INVALID')
        if result.get('missing') or result.get('collected') is not True:
            log_event(_LOGGER, 'native_video_values_incomplete', level='ERROR' if result.get('error_type') else 'WARNING',
                      missing_codes=result.get('missing', []))
        else:
            validate_value_bindings(result)
        return result
    except Exception as exc:
        log_exception(_LOGGER, 'native_video_values_failed', exc)
        return {'schema': SCHEMA, 'collected': False, 'missing': ['VIDEO_NATIVE_VALUE_READ_FAILED'],
                'instance': None, 'images': None, 'transition': None, 'music': None, 'document_time_origin': None,
                'executionAllowed': False, 'capabilityCertified': False, 'inputFreezeAllowed': False}
