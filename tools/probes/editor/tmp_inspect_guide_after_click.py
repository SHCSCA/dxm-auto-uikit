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
    context=p.chromium.launch
    ctx=browser.new_context(ignore_https_errors=True, viewport={'width':1600,'height':1400})
    ctx.add_cookies(load_cookies())
    page=ctx.new_page()
    page.goto('https://www.dianxiaomi.com/web/productCrawl/dataAcquisition', wait_until='domcontentloaded', timeout=45000)
    page.wait_for_timeout(3500)
    page.locator('.ant-modal-close').first.click(force=True)
    page.wait_for_timeout(800)
    try:
        page.get_by_text('未认领(51)', exact=False).first.click(force=True)
    except Exception:
        pass
    page.wait_for_timeout(1200)
    print(json.dumps(page.evaluate(r'''() => ({
      dialog: document.querySelector('[role="dialog"]')?.innerText || null,
      guideText: document.querySelector('.guide-overlay')?.innerText || null,
      guideHtml: document.querySelector('.guide-overlay')?.outerHTML.slice(0,3000) || null,
      guideBtns: Array.from(document.querySelectorAll('.guide-overlay *')).map(el => ({tag:el.tagName,text:(el.innerText||el.textContent||'').replace(/\s+/g,' ').trim(),cls:el.className||'',html:el.outerHTML.slice(0,200)})).filter(x=>x.text || x.cls).slice(0,80)
    })'''), ensure_ascii=False, indent=2))
    browser.close()
