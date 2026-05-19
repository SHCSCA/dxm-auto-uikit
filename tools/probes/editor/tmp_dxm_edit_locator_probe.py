import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path('/root/.Hermes/workspace/dxm-auto-uikit')
COOKIE_FILE = ROOT / 'data' / 'sessions' / 'dianxiaomi_cookies.json'
OUT_JSON = ROOT / 'data' / 'sessions' / 'dianxiaomi_edit_locator_probe.json'
OUT_DIR = ROOT / 'data' / 'screenshots'
OUT_DIR.mkdir(parents=True, exist_ok=True)


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
    result = {}

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
    page.screenshot(path=str(OUT_DIR / 'dxm_edit_locator_01_search.png'), full_page=True)

    edits = page.locator('a').filter(has_text='编辑')
    result['edit_count'] = edits.count()
    first = edits.first
    result['edit_box'] = first.bounding_box()
    first.click(timeout=3000)
    page.wait_for_timeout(1500)
    page.screenshot(path=str(OUT_DIR / 'dxm_edit_locator_02_after_edit.png'), full_page=True)

    skip_btn = page.get_by_text('跳过，去编辑产品', exact=True)
    result['skip_count'] = skip_btn.count()
    if skip_btn.count() > 0:
        result['skip_box'] = skip_btn.first.bounding_box()
        skip_btn.first.click(timeout=3000)
    page.wait_for_timeout(5000)
    page.screenshot(path=str(OUT_DIR / 'dxm_edit_locator_03_after_skip.png'), full_page=True)

    result['pages'] = [{'url': pg.url, 'title': pg.title()} for pg in ctx.pages]
    result['active_url'] = page.url
    result['active_title'] = page.title()
    result['body_head'] = page.locator('body').inner_text()[:5000]

    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    browser.close()
