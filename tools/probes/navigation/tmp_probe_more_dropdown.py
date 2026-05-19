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
    page.wait_for_timeout(3500)
    try: page.locator('.ant-modal-close').first.click(force=True); page.wait_for_timeout(800)
    except Exception: pass
    try: page.get_by_text('跳过', exact=True).click(force=True, timeout=1500); page.wait_for_timeout(800)
    except Exception: pass
    # switch claimed tab
    page.evaluate(r'''() => {
      const tab = Array.from(document.querySelectorAll('*')).find(el => /^已认领\(\d+\)$/.test((el.innerText||el.textContent||'').replace(/\s+/g,'')));
      if (tab) tab.dispatchEvent(new MouseEvent('click', {bubbles:true}));
    }''')
    page.wait_for_timeout(1000)
    # click first more
    page.evaluate(r'''() => {
      const more = Array.from(document.querySelectorAll('a,div,span,button')).find(el => (el.innerText||el.textContent||'').replace(/\s+/g,'').trim()==='更多');
      if (more) more.dispatchEvent(new MouseEvent('click', {bubbles:true}));
    }''')
    page.wait_for_timeout(1200)
    print(json.dumps(page.evaluate(r'''() => ({
      dropdowns: Array.from(document.querySelectorAll('.ant-dropdown, .ant-dropdown-menu, .ant-dropdown-menu-item, .ant-dropdown-placement-bottomLeft, .ant-popover')).map(el => {
        const st=getComputedStyle(el), r=el.getBoundingClientRect();
        return {tag:el.tagName, cls:el.className||'', txt:(el.innerText||el.textContent||'').replace(/\s+/g,' ').trim(), display:st.display, visibility:st.visibility, opacity:st.opacity, rect:{x:r.x,y:r.y,w:r.width,h:r.height}};
      }).slice(0,80),
      bodyTail: document.body.innerText.slice(-1000),
      matchingTexts: Array.from(document.querySelectorAll('*')).map(el => (el.innerText||el.textContent||'').replace(/\s+/g,' ').trim()).filter(t => t.includes('添加备注') || t.includes('删除')).slice(0,50)
    })'''), ensure_ascii=False, indent=2))
    browser.close()
