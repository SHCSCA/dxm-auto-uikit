"""新文档中的被动视频交互计数；只保存观察元数据，不修改页面或原生状态。"""

LIFETIME_READER = '__dxmNativeVideoReadonlyLifetimeV1'
NATIVE_VIDEO_LIFETIME_SCRIPT = r"""(() => {
  if (window.top !== window || Object.prototype.hasOwnProperty.call(window,'__dxmNativeVideoReadonlyLifetimeV1')) return;
  let revealCount=0,entryClicks=0,previousVisible=0,closedCount=0,duplicate=false,trackedRoot=null;
  const unexpected=[];
  const visible=el=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el);return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden';};
  const roots=()=>[...document.querySelectorAll('.ant-modal-wrap[role="dialog"]')].filter(el=>visible(el)&&el.querySelector('.img-translate-video'));
  const scan=()=>{
    const current=roots(),count=current.length;
    if(count>1)duplicate=true;
    if(previousVisible===0&&count>0)revealCount++;
    if(previousVisible>0&&count===0)closedCount++;
    previousVisible=count;
    if(count===1)trackedRoot=current[0];
    return count;
  };
  const unexpectedEvent=kind=>{if(unexpected.length<16)unexpected.push(kind);};
  for(const kind of ['click','input','change','keydown','drop','pointerdown']){
    document.addEventListener(kind,event=>{
      const target=event.target instanceof Element?event.target:event.target?.parentElement;
      const entry=target?.closest('.product-add-wrapper .video-operate button');
      if(kind==='click'&&entry&&String(entry.textContent||'').replace(/\s+/g,' ').trim()==='图片生成视频'){
        entryClicks++;
        if(!event.isTrusted)unexpectedEvent('synthetic_entry_click');
      }else if(target?.closest('.ant-modal-wrap[role="dialog"]')?.querySelector('.img-translate-video')){
        unexpectedEvent(kind);
      }
    },{capture:true,passive:true});
  }
  const observe=()=>{
    scan();
    new MutationObserver(records=>{
      const watched=trackedRoot;
      if(watched)for(const record of records){
        if(record.type==='childList'&&[...record.removedNodes].some(node=>node===watched||node instanceof Element&&node.contains(watched))){
          unexpectedEvent('modal_detached_or_replaced');continue;
        }
        const target=record.target;
        if(record.type!=='attributes'||!(target instanceof Element)||!(target===watched||target.contains(watched)))continue;
        const old=String(record.oldValue||''),current=String(target.getAttribute(record.attributeName)||'');
        const styleHidden=value=>/(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*hidden|content-visibility\s*:\s*hidden)\s*(?:;|$)/i.test(value);
        const hidden=record.attributeName==='hidden'
          ||record.attributeName==='aria-hidden'&&(old==='true'||current==='true')
          ||record.attributeName==='style'&&(styleHidden(old)||styleHidden(current))
          ||record.attributeName==='class'&&old!==current;
        if(hidden)unexpectedEvent('modal_visibility_history_changed');
      }
      scan();
    }).observe(document.documentElement,{subtree:true,childList:true,attributes:true,attributeOldValue:true,attributeFilter:['class','style','aria-hidden','hidden']});
  };
  if(document.documentElement)observe();else document.addEventListener('DOMContentLoaded',observe,{once:true});
  const read=()=>{const count=scan();return {schema:'dxm.native_video_document_lifetime.v1',document_time_origin:performance.timeOrigin,
    url:location.href,reveal_count:revealCount,entry_click_count:entryClicks,visible_count:count,
    closed_count:closedCount,duplicate_modal_seen:duplicate,unexpected_interactions:[...unexpected]};};
  Object.defineProperty(window,'__dxmNativeVideoReadonlyLifetimeV1',{value:read,writable:false,configurable:false});
})();"""

NATIVE_VIDEO_LIFETIME_READ = "() => typeof window.__dxmNativeVideoReadonlyLifetimeV1 === 'function' ? window.__dxmNativeVideoReadonlyLifetimeV1() : null"
