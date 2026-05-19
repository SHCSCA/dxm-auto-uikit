import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path('/root/.Hermes/workspace/dxm-auto-uikit')
COOKIE_FILE = ROOT / 'data' / 'sessions' / 'dianxiaomi_cookies.json'


def load_cookies():
    raw = json.loads(COOKIE_FILE.read_text(encoding='utf-8'))
    out = []
    for c in raw:
        item = {'name': c['name'], 'value': c['value'], 'domain': c['domain'], 'path': c.get('path', '/'), 'httpOnly': c.get('httpOnly', False), 'secure': c.get('secure', False)}
        ss = c.get('sameSite')
        if ss in ('lax', 'strict', 'none', 'Lax', 'Strict', 'None'):
            item['sameSite'] = ss.capitalize() if ss.lower() != 'none' else 'None'
        if 'expirationDate' in c:
            item['expires'] = int(c['expirationDate'])
        out.append(item)
    return out

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
    ctx = browser.new_context(ignore_https_errors=True, viewport={'width': 1600, 'height': 1400})
    ctx.add_cookies(load_cookies())
    page = ctx.new_page()
    page.goto('https://www.dianxiaomi.com/web/smt/smtProductList/draft', wait_until='domcontentloaded', timeout=45000)
    page.wait_for_timeout(3500)
    page.evaluate(r'''() => {
      const all = Array.from(document.querySelectorAll('*'));
      const store = all.find(el => (el.innerText||el.textContent||'').replace(/\s+/g,'').trim()==='DangKang');
      if (store) store.dispatchEvent(new MouseEvent('click',{bubbles:true}));
      const input = Array.from(document.querySelectorAll('input.ant-input,input')).find(el => {const r=el.getBoundingClientRect(); return r.width>220 && r.height>20 && !el.disabled});
      if (input){input.value='崩坏3钥匙扣爱莉希雅'; input.dispatchEvent(new Event('input',{bubbles:true})); input.dispatchEvent(new Event('change',{bubbles:true}));}
      const btn = all.find(el => (el.innerText||el.textContent||'').replace(/\s+/g,'').trim()==='搜索');
      if (btn) btn.dispatchEvent(new MouseEvent('click',{bubbles:true}));
    }''')
    page.wait_for_timeout(2200)
    edits = page.locator('a').filter(has_text='编辑')
    print('count', edits.count())
    data=[]
    for i in range(min(edits.count(),10)):
        e=edits.nth(i)
        try:
            vis=e.is_visible(timeout=500)
            box=e.bounding_box()
            txt=e.inner_text(timeout=500)
            data.append({'i':i,'visible':vis,'box':box,'txt':txt})
        except Exception as ex:
            data.append({'i':i,'error':str(ex)})
    print(json.dumps(data, ensure_ascii=False, indent=2))
    browser.close()
