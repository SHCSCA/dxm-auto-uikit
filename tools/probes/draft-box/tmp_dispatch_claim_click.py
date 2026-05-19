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
    page.locator('.ant-modal-close').first.click(force=True)
    page.wait_for_timeout(1000)
    try:
        page.get_by_text('跳过', exact=True).click(force=True, timeout=1500)
        page.wait_for_timeout(1000)
    except Exception:
        pass
    res=page.evaluate(r'''() => {
      const a = Array.from(document.querySelectorAll('a')).find(el => (el.innerText||el.textContent||'').trim()==='认领');
      if (!a) return {found:false};
      a.dispatchEvent(new MouseEvent('mouseover', {bubbles:true}));
      a.dispatchEvent(new MouseEvent('mousedown', {bubbles:true}));
      a.dispatchEvent(new MouseEvent('mouseup', {bubbles:true}));
      a.dispatchEvent(new MouseEvent('click', {bubbles:true}));
      return {found:true, html:a.outerHTML};
    }''')
    page.wait_for_timeout(2500)
    print('dispatch', res)
    print(json.dumps(page.evaluate(r'''() => ({
      dialogs: Array.from(document.querySelectorAll('[role="dialog"], .ant-modal-wrap, .ant-select-dropdown, .ant-dropdown')).map(el => ({cls: el.className||'', txt:(el.innerText||el.textContent||'').replace(/\s+/g,' ').trim().slice(0,300)})).slice(0,20),
      body: document.body.innerText.slice(0,3000)
    })'''), ensure_ascii=False, indent=2))
    browser.close()
