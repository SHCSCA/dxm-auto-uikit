"""原生视频弹窗的零写诊断候选；不生成可信输入、冻结或执行授权。"""

import re

from src.services.structured_logging import get_logger, log_event, log_exception


_LOGGER = get_logger('native_video_dom_observation')
SCHEMA = 'dxm.native_video_dom_diagnostic.v1'
NATIVE_VIDEO_DOM_OBSERVATION_SCRIPT = r"""() => {
  const result = {
    schema:'dxm.native_video_dom_diagnostic.v1', collected:false,
    executionAllowed:false, capabilityCertified:false, inputFreezeAllowed:false,
    sourceVersionCandidate:{
      modalFile:'ImgToVideoModal-Cn4d-6zD.js',
      modalSha256:'25D36FFACB573B45F3D94EB031335BABDF5DF7FA1D870F657C2DC1956ACB5FED',
      constFile:'const-BvIXJGkR.js', observedAssets:[], verified:false
    },
    surfaceMatchCount:0, actual:{},
    missing:['SOURCE_VERSION_NOT_VERIFIED','CURRENT_MODAL_IDENTITY_NOT_BOUND']
  };
  const missing = code => { if (!result.missing.includes(code)) result.missing.push(code); };
  const visible = el => {
    const rect = el.getBoundingClientRect(), style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
  };
  const text = el => String(el.textContent || '').replace(/\s+/g,' ').trim();
  const url = value => {
    if (typeof value !== 'string' || !value || value !== value.trim() || value.includes(',')) return null;
    try {
      const parsed = new URL(value);
      return ['http:','https:'].includes(parsed.protocol) && !parsed.username && !parsed.password ? parsed.href : null;
    } catch { return null; }
  };
  const directives = el => Array.isArray(el.__vnode?.dirs) ? el.__vnode.dirs : [];
  const lazyUrls = el => directives(el).map(binding => binding.value).filter(value => typeof value === 'string' && url(value));
  try {
    // 资源名称只提供版本候选，未读取响应字节就不能证明页面加载的是已审版本。
    const resources = [...document.querySelectorAll('script[src]')].map(el => el.src);
    for (const item of performance.getEntriesByType('resource')) resources.push(item.name);
    for (const resource of resources) {
      try {
        const parsed = new URL(resource, location.href);
        if ([result.sourceVersionCandidate.modalFile,result.sourceVersionCandidate.constFile].some(name => parsed.pathname.endsWith('/'+name))) {
          const candidate = parsed.origin + parsed.pathname;
          if (!result.sourceVersionCandidate.observedAssets.includes(candidate)) result.sourceVersionCandidate.observedAssets.push(candidate);
        }
      } catch { missing('SOURCE_ASSET_URL_INVALID'); }
    }
    if (!result.sourceVersionCandidate.observedAssets.some(value => value.endsWith('/'+result.sourceVersionCandidate.modalFile))) missing('MODAL_ASSET_NOT_OBSERVED');
    if (!result.sourceVersionCandidate.observedAssets.some(value => value.endsWith('/'+result.sourceVersionCandidate.constFile))) missing('CONST_ASSET_NOT_OBSERVED');
    const roots = [...document.querySelectorAll('.ant-modal-wrap[role="dialog"]')]
      .filter(el => visible(el) && el.querySelector('.img-translate-video'));
    result.surfaceMatchCount = roots.length;
    if (roots.length !== 1) { missing('VIDEO_MODAL_NOT_UNIQUE_VISIBLE'); return result; }
    const root = roots[0];
    const contents = [...root.querySelectorAll('.img-translate-video')];
    if (contents.length !== 1 || !visible(contents[0])) { missing('VIDEO_CONTENT_NOT_UNIQUE_VISIBLE'); return result; }
    const lists = [...contents[0].querySelectorAll('.content-imgs')];
    const images = {domCount:0, sortListCount:null, sortListUrlsCandidate:null, dom:[], selectedUrlsCandidate:null, selectionConsistent:false, loaded:false};
    result.actual.images = images;
    if (lists.length !== 1 || !visible(lists[0])) {
      missing('VIDEO_IMAGE_LIST_NOT_UNIQUE_VISIBLE');
    } else {
      const list = lists[0], children = [...list.children];
      const rows = children.filter(el => el.tagName === 'LI');
      images.domCount = rows.length;
      if (rows.length !== children.length) missing('VIDEO_IMAGE_LIST_STRUCTURE_INVALID');
      const bindings = directives(list).filter(binding => binding.value && typeof binding.value === 'object' && Array.isArray(binding.value.sortList));
      if (bindings.length !== 1) missing(bindings.length === 0 ? 'VIDEO_SORT_LIST_BINDING_UNAVAILABLE' : 'VIDEO_SORT_LIST_BINDING_NOT_UNIQUE');
      else {
        const selected = bindings[0].value.sortList;
        images.sortListCount = selected.length;
        // 原生组件最多八项；超限只报告缺证，不能截断后宣称集合完整。
        if (selected.length > 8 || rows.length > 8) missing('VIDEO_IMAGE_COLLECTION_OVER_LIMIT');
        else {
          images.sortListUrlsCandidate = selected.map(item => item && typeof item === 'object' ? item.url : null);
          if (selected.length < 2) missing('VIDEO_IMAGE_COUNT_BELOW_NATIVE_MINIMUM');
          if (selected.length !== rows.length) missing('VIDEO_IMAGE_DOM_SORT_LIST_COUNT_DRIFT');
          if (images.sortListUrlsCandidate.some(value => !url(value))) missing('VIDEO_SORT_LIST_URL_INVALID');
          if (new Set(images.sortListUrlsCandidate.map(url)).size !== selected.length) missing('VIDEO_IMAGE_SELECTION_DUPLICATE');
        }
      }
      if (rows.length <= 8) {
        images.dom = rows.map(row => {
          const matches = [...row.querySelectorAll('img')];
          if (!visible(row)) missing('VIDEO_SELECTED_IMAGE_NOT_VISIBLE');
          if (matches.length !== 1) { missing('VIDEO_IMAGE_NODE_NOT_UNIQUE'); return {imageCount:matches.length}; }
          const img = matches[0], candidates = lazyUrls(img);
          const nativeUrl = candidates.length === 1 ? candidates[0] : null;
          const loaded = img.complete === true && img.naturalWidth > 0 && img.naturalHeight > 0;
          if (candidates.length !== 1) missing(candidates.length === 0 ? 'VIDEO_IMAGE_LAZY_URL_UNAVAILABLE' : 'VIDEO_IMAGE_LAZY_URL_NOT_UNIQUE');
          if (!visible(img)) missing('VIDEO_IMAGE_NOT_VISIBLE');
          if (!loaded) missing('VIDEO_IMAGE_NOT_LOADED');
          if (!url(img.currentSrc) || !nativeUrl || url(img.currentSrc) !== url(nativeUrl)) missing('VIDEO_IMAGE_LOADED_URL_DRIFT');
          return {imageCount:matches.length, visible:visible(img), nativeUrlCandidate:nativeUrl, lazyUrlCandidates:candidates,
            src:img.getAttribute('src'), currentSrc:img.currentSrc || null, loaded,
            naturalWidth:img.naturalWidth, naturalHeight:img.naturalHeight};
        });
      }
      const domUrls = images.dom.map(item => item.nativeUrlCandidate);
      images.selectionConsistent = Array.isArray(images.sortListUrlsCandidate) && images.sortListUrlsCandidate.length === rows.length
        && rows.length === children.length && rows.every(visible) && rows.length > 0
        && images.sortListUrlsCandidate.every((value,index) => url(value) && value === domUrls[index])
        && new Set(domUrls.map(url)).size === domUrls.length;
      if (!images.selectionConsistent) missing('VIDEO_IMAGE_DOM_SORT_LIST_CORRESPONDENCE_UNPROVEN');
      images.loaded = images.dom.length === rows.length && rows.length > 0 && images.dom.every(item => item.visible && item.loaded && url(item.currentSrc) === url(item.nativeUrlCandidate));
      if (images.selectionConsistent && images.loaded) images.selectedUrlsCandidate = [...domUrls];
    }
    // 只返回选中项原始候选；不按中文标签、位置或调用方映射推断稳定值。
    for (const [key,selector] of [
      ['transition','.page-content_right-top .content-list > li'],
      ['music','.page-content_right-bottom .content-list > li']
    ]) {
      const selected = [...contents[0].querySelectorAll(selector)].filter(el => el.classList.contains('activeName'));
      const candidates = selected.map(el => ({text:text(el), visible:visible(el), previews:[...el.querySelectorAll('img')].map(img => ({
        src:img.getAttribute('src'), vnodeSrcCandidate:typeof img.__vnode?.props?.src === 'string' ? img.__vnode.props.src : null,
        lazyUrlCandidates:lazyUrls(img)
      }))}));
      result.actual[key] = {selectedCount:selected.length, candidates, stableValue:null};
      if (selected.length !== 1 || !selected.every(visible)) missing(key === 'transition' ? 'VIDEO_TRANSITION_SELECTION_NOT_UNIQUE_VISIBLE' : 'VIDEO_MUSIC_SELECTION_NOT_UNIQUE_VISIBLE');
    }
    result.actual.music.stableId = null;
    result.actual.music.silence = null;
    missing('VIDEO_TRANSITION_STABLE_VALUE_MISSING');
    missing('VIDEO_MUSIC_STABLE_ID_OR_SILENCE_MISSING');
    result.collected = true;
  } catch (error) {
    missing('VIDEO_DOM_OBSERVATION_FAILED');
    result.errorType = typeof error?.name === 'string' ? error.name : 'UnknownError';
  }
  return result;
}"""


def collect_native_video_dom_observation(page):
    """仅在调用方提供的页面收集诊断，不打开浮层、不接生产动作或冻结链。"""
    try:
        result = page.evaluate(NATIVE_VIDEO_DOM_OBSERVATION_SCRIPT)
        if (not isinstance(result, dict) or result.get('schema') != SCHEMA
                or type(result.get('collected')) is not bool or not isinstance(result.get('actual'), dict)
                or not isinstance(result.get('missing'), list) or not result['missing']
                or any(not isinstance(code, str) or re.fullmatch(r'[A-Z][A-Z0-9_]{0,119}', code) is None for code in result['missing'])
                or len(set(result['missing'])) != len(result['missing'])
                or any(result.get(key) is not False for key in ('executionAllowed', 'capabilityCertified', 'inputFreezeAllowed'))):
            raise ValueError('VIDEO_DOM_DIAGNOSTIC_ENVELOPE_INVALID')
        if result.get('missing'):
            log_event(_LOGGER, 'native_video_dom_diagnostic_incomplete', level='ERROR' if result.get('errorType') else 'WARNING',
                      collected=result.get('collected') is True, missing_codes=result['missing'])
        return result
    except Exception as exc:
        log_exception(_LOGGER, 'native_video_dom_diagnostic_failed', exc)
        return {'schema': SCHEMA, 'collected': False, 'actual': {},
                'executionAllowed': False, 'capabilityCertified': False, 'inputFreezeAllowed': False,
                'missing': ['VIDEO_DOM_DIAGNOSTIC_FAILED']}
