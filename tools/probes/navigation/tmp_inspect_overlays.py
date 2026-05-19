import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path('/root/.Hermes/workspace/dxm-auto-uikit')
COOKIE_FILE = ROOT / 'data' / 'sessions' / 'dianxiaomi_cookies.json'

def load_cookies():
    raw = json.loads(COOKIE_FILE.read_text(encoding='utf-8'))
    cookies = []
    for c in raw:
        item = {'name': c['name'],'value': c['value'],'domain': c['domain'],'path': c.get('path','/'),'httpOnly': c.get('httpOnly',False),'secure': c.get('secure',False)}
        ss=c.get('sameSite')
        if ss in ('lax','strict','none','Lax','Strict','None'):
            item['sameSite']= ss.capitalize() if ss.lower()!='none' else 'None'
        if 'expirationDate' in c:
            item['expires']=int(c['expirationDate'])
        cookies.append(item)
    return cookies

with sync_playwright() as p:
    browser=p.chromium.launch(headless=True, executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
    context=browser.new_context(ignore_https_errors=True, viewport={'width':1600,'height':1400})
    context.add_cookies(load_cookies())
    page=context.new_page()
    page.goto('https://www.dianxiaomi.com/web/productCrawl/dataAcquisition', wait_until='domcontentloaded', timeout=45000)
    page.wait_for_timeout(3500)
    data=page.evaluate(r'''() => {
      const modalClose = document.querySelector('[role="dialog"] .ant-modal-close, .ant-modal-wrap .ant-modal-close');
      const guide = document.querySelector('.guide-overlay');
      const guideBtns = Array.from(document.querySelectorAll('.guide-overlay button, .guide-overlay a, .guide-overlay .guide-btn *')).map(el => ({tag:el.tagName, text:(el.innerText||el.textContent||'').replace(/\s+/g,' ').trim(), cls:el.className||'', html:el.outerHTML.slice(0,200)}));
      return {
        modalClose: modalClose ? {html: modalClose.outerHTML, txt:(modalClose.innerText||modalClose.textContent||'').trim()} : null,
        modalText: document.querySelector('[role="dialog"]')?.innerText || null,
        guide: guide ? {text:(guide.innerText||guide.textContent||'').replace(/\s+/g,' ').trim(), html:guide.outerHTML.slice(0,2000)} : null,
        guideBtns,
      }
    }''')
    print(json.dumps(data, ensure_ascii=False, indent=2))
    browser.close()
