import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path('/root/.Hermes/workspace/dxm-auto-uikit')
COOKIE_FILE = ROOT / 'data' / 'sessions' / 'dianxiaomi_cookies.json'
OUT_DIR = ROOT / 'data' / 'screenshots'
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_JSON = ROOT / 'data' / 'sessions' / 'dianxiaomi_draft_probe.json'


def load_cookies():
    raw = json.loads(COOKIE_FILE.read_text(encoding='utf-8'))
    cookies = []
    for c in raw:
        item = {
            'name': c['name'], 'value': c['value'], 'domain': c['domain'], 'path': c.get('path', '/'),
            'httpOnly': c.get('httpOnly', False), 'secure': c.get('secure', False)
        }
        same_site = c.get('sameSite')
        if same_site in ('lax', 'strict', 'none', 'Lax', 'Strict', 'None'):
            item['sameSite'] = same_site.capitalize() if same_site.lower() != 'none' else 'None'
        if 'expirationDate' in c:
            item['expires'] = int(c['expirationDate'])
        cookies.append(item)
    return cookies

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
    context = browser.new_context(ignore_https_errors=True, viewport={'width': 1440, 'height': 1200})
    context.add_cookies(load_cookies())
    page = context.new_page()
    page.goto('https://www.dianxiaomi.com/web/smt/smtProductList/draft', wait_until='domcontentloaded', timeout=45000)
    page.wait_for_timeout(3500)
    body = page.locator('body').inner_text()[:5000]
    page.screenshot(path=str(OUT_DIR / 'dxm_draft_probe.png'), full_page=True)
    data = {
        'url': page.url,
        'title': page.title(),
        'body': body,
        'keywords': {},
        'matches': page.evaluate(r'''() => {
          const targets = ['待发布产品','编辑','发布','更多','店铺','所属店铺','授权店铺','导入','导出','同步产品'];
          const out = [];
          for (const el of document.querySelectorAll('a,button,span,div,td,th')) {
            const txt = (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
            if (!txt) continue;
            if (!targets.some(t => txt === t || txt.includes(t))) continue;
            const st = getComputedStyle(el); const r = el.getBoundingClientRect();
            if (st.display === 'none' || st.visibility === 'hidden' || parseFloat(st.opacity || '1') === 0 || r.width < 5 || r.height < 5) continue;
            out.push({text: txt.slice(0,80), tag: el.tagName, href: el.getAttribute('href'), cls: el.className || '', id: el.id || '', rect: {x:r.x,y:r.y,w:r.width,h:r.height}})
          }
          return out.slice(0,120)
        }''')
    }
    for kw in ['店铺','所属店铺','授权店铺','待发布产品','编辑','发布']:
        data['keywords'][kw] = kw in body
    browser.close()

OUT_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(data, ensure_ascii=False, indent=2))
