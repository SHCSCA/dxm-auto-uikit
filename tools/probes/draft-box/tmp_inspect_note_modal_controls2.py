import json
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path('/root/.Hermes/workspace/dxm-auto-uikit')
COOKIE_FILE=ROOT/'data'/'sessions'/'dianxiaomi_cookies.json'
def load_cookies():
    raw=json.loads(COOKIE_FILE.read_text(encoding='utf-8'))
    out=[]
    for c in raw:
        item={'name':c['name'],'value':c['value'],'domain':c['domain'],'path':c.get('path','/'),'httpOnly':c.get('httpOnly',False),'secure':c.get('secure',False)}
        ss=c.get('sameSite')
        if ss in ('lax','strict','none','Lax','Strict','None'): item['sameSite']=ss.capitalize() if ss.lower()!='none' else 'None'
        if 'expirationDate' in c: item['expires']=int(c['expirationDate'])
        out.append(item)
    return out
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True, executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
    ctx=browser.new_context(ignore_https_errors=True, viewport={'width':1600,'height':1400})
    ctx.add_cookies(load_cookies())
    page=ctx.new_page()
    page.goto('https://www.dianxiaomi.com/web/productCrawl/dataAcquisition', wait_until='domcontentloaded', timeout=45000)
    page.wait_for_timeout(3000)
    try: page.locator('.ant-modal-close').first.click(force=True); page.wait_for_timeout(800)
    except Exception: pass
    try: page.get_by_text('跳过', exact=True).click(force=True, timeout=1500); page.wait_for_timeout(800)
    except Exception: pass
    page.evaluate(r'''() => {
      const tab=Array.from(document.querySelectorAll('*')).find(el=>/^已认领\(\d+\)$/.test((el.innerText||el.textContent||'').replace(/\s+/g,'')));
      if (tab) tab.dispatchEvent(new MouseEvent('click',{bubbles:true}));
    }''')
    page.wait_for_timeout(1200)
    # exact sequence known to work
    page.evaluate(r'''() => {
      const row=document.querySelector('tr.vxe-body--row');
      const trigger=row && row.querySelector('.ant-dropdown-trigger');
      if (trigger) {
        for (const evt of ['mouseenter','mouseover','mousedown','mouseup','click']) trigger.dispatchEvent(new MouseEvent(evt,{bubbles:true}));
      }
    }''')
    page.wait_for_timeout(1200)
    item=page.evaluate(r'''() => { const el=Array.from(document.querySelectorAll('li.ant-dropdown-menu-item')).find(el => (el.innerText||el.textContent||'').replace(/\s+/g,'').trim()==='添加备注'); if(!el) return null; const r=el.getBoundingClientRect(); return {x:r.x,y:r.y,w:r.width,h:r.height, txt:(el.innerText||el.textContent||'').trim()}; }''')
    print('item', item)
    if item:
        page.mouse.click(item['x']+item['w']/2, item['y']+item['h']/2)
        page.wait_for_timeout(1500)
    print(json.dumps(page.evaluate(r'''() => {
      const mods = Array.from(document.querySelectorAll('[role="dialog"], .ant-modal-wrap, .ant-modal')).map(el => ({cls:String(el.className||''), txt:(el.innerText||el.textContent||'').replace(/\s+/g,' ').trim().slice(0,1000)}));
      const modal = mods.find(m => m.txt.includes('备注')) || null;
      const controls = Array.from(document.querySelectorAll('input, textarea, button, span, div')).map(el => {
        const st=getComputedStyle(el), r=el.getBoundingClientRect();
        if(st.display==='none'||st.visibility==='hidden'||parseFloat(st.opacity||'1')===0||r.width<5||r.height<5) return null;
        const txt=(el.innerText||el.textContent||el.getAttribute('value')||'').replace(/\s+/g,' ').trim();
        if(!(txt.includes('备注') || txt.includes('提交') || txt.includes('关闭') || txt.includes('颜色') || txt.includes('内容') || txt.includes('说明'))) return null;
        return {tag:el.tagName, txt:txt.slice(0,120), cls:String(el.className||''), placeholder:el.getAttribute('placeholder'), style:el.getAttribute('style')||'', rect:{x:r.x,y:r.y,w:r.width,h:r.height}, html:el.outerHTML.slice(0,300)};
      }).filter(Boolean);
      return {mods:mods.slice(0,20), modal, controls:controls.slice(0,120)};
    }'''), ensure_ascii=False, indent=2))
    browser.close()
