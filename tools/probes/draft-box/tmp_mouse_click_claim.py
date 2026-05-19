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
    box=page.locator('a').filter(has_text='认领').first.bounding_box()
    print('box', box)
    x=box['x']+box['width']/2
    y=box['y']+box['height']/2
    page.mouse.move(x,y)
    page.wait_for_timeout(200)
    page.mouse.click(x,y)
    page.wait_for_timeout(3000)
    print(json.dumps(page.evaluate(r'''() => ({
      dialogs: Array.from(document.querySelectorAll('[role="dialog"], .ant-modal-wrap, .ant-select-dropdown, .ant-dropdown')).map(el => ((el.innerText||el.textContent||'').replace(/\s+/g,' ').trim())).slice(0,10),
      guide: document.querySelector('.guide-overlay') ? {display:getComputedStyle(document.querySelector('.guide-overlay')).display, html:document.querySelector('.guide-overlay').outerHTML.slice(0,400)} : null,
      body: document.body.innerText.slice(0,2500)
    })'''), ensure_ascii=False, indent=2))
    browser.close()
