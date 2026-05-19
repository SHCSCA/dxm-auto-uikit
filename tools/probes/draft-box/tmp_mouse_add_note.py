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
    # open more via true click on trigger center
    box=page.evaluate(r'''() => { const el=document.querySelector('tr.vxe-body--row .ant-dropdown-trigger'); if(!el) return null; const r=el.getBoundingClientRect(); return {x:r.x,y:r.y,w:r.width,h:r.height}; }''')
    print('trigger', box)
    page.mouse.click(box['x']+box['w']/2, box['y']+box['h']/2)
    page.wait_for_timeout(800)
    item=page.evaluate(r'''() => {
      const el=Array.from(document.querySelectorAll('li.ant-dropdown-menu-item')).find(el => (el.innerText||el.textContent||'').replace(/\s+/g,'').trim()==='添加备注');
      if(!el) return null; const r=el.getBoundingClientRect(); return {x:r.x,y:r.y,w:r.width,h:r.height, html:el.outerHTML};
    }''')
    print('item', json.dumps(item, ensure_ascii=False))
    if item:
        page.mouse.click(item['x']+item['w']/2, item['y']+item['h']/2)
        page.wait_for_timeout(2000)
    print(json.dumps(page.evaluate(r'''() => ({
      body: document.body.innerText.slice(0,4000),
      notes: Array.from(document.querySelectorAll('body *')).map(el => ({txt:(el.innerText||el.textContent||'').replace(/\s+/g,' ').trim(), cls:String(el.className||'')})).filter(x => x.txt.includes('备注') || x.txt.includes('添加备注') || x.txt.includes('保存')).slice(0,80),
      dialogs: Array.from(document.querySelectorAll('[role="dialog"], .ant-modal-wrap, .ant-drawer, .ant-popover')).map(el => ({txt:(el.innerText||el.textContent||'').replace(/\s+/g,' ').trim().slice(0,500), cls:String(el.className||'')})).slice(0,20)
    })'''), ensure_ascii=False, indent=2))
    browser.close()
