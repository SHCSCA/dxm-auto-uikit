import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path('/root/.Hermes/workspace/dxm-auto-uikit')
COOKIE_FILE = ROOT / 'data' / 'sessions' / 'dianxiaomi_cookies.json'
OUT_JSON = ROOT / 'data' / 'sessions' / 'dianxiaomi_edit_popup_watch.json'
TARGET_TEXT = '崩坏3钥匙扣爱莉希雅'


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
    result = {'before_pages': 1}

    page.goto('https://www.dianxiaomi.com/web/smt/smtProductList/draft', wait_until='domcontentloaded', timeout=45000)
    page.wait_for_timeout(3500)
    page.evaluate(r'''({target, frag}) => {
      const all = Array.from(document.querySelectorAll('*'));
      const store = all.find(el => (el.innerText||el.textContent||'').replace(/\s+/g,'').trim() === target.replace(/\s+/g,''));
      if (store) store.dispatchEvent(new MouseEvent('click', {bubbles:true}));
      const input = Array.from(document.querySelectorAll('input.ant-input,input')).find(el => {
        const r = el.getBoundingClientRect();
        return r.width > 220 && r.height > 20 && !el.disabled;
      });
      if (input) {
        input.value = frag;
        input.dispatchEvent(new Event('input', {bubbles:true}));
        input.dispatchEvent(new Event('change', {bubbles:true}));
      }
      const btn = all.find(el => (el.innerText||el.textContent||'').replace(/\s+/g,'').trim() === '搜索');
      if (btn) btn.dispatchEvent(new MouseEvent('click', {bubbles:true}));
    }''', {'target': 'Dang Kang', 'frag': TARGET_TEXT})
    page.wait_for_timeout(2200)

    edit = page.evaluate(r'''(frag) => {
      const row = Array.from(document.querySelectorAll('tr.vxe-body--row, tr')).find(tr => (tr.innerText||tr.textContent||'').includes(frag));
      if (!row) return null;
      const a = Array.from(row.querySelectorAll('a')).find(el => (el.innerText||el.textContent||'').replace(/\s+/g,'').trim()==='编辑');
      if (!a) return null;
      const r = a.getBoundingClientRect();
      return {x:r.x,y:r.y,w:r.width,h:r.height};
    }''', TARGET_TEXT)
    result['edit_rect'] = edit
    page.mouse.click(edit['x'] + edit['w']/2, edit['y'] + edit['h']/2)
    page.wait_for_timeout(1500)
    result['after_edit_pages'] = [{'url': pg.url, 'title': pg.title()} for pg in ctx.pages]

    skip = page.evaluate(r'''() => {
      const btn = Array.from(document.querySelectorAll('button')).find(el => (el.innerText||el.textContent||'').replace(/\s+/g,'').trim()==='跳过，去编辑产品');
      if (!btn) return null;
      const r = btn.getBoundingClientRect();
      return {x:r.x,y:r.y,w:r.width,h:r.height};
    }''')
    result['skip_rect'] = skip
    if skip:
        page.mouse.click(skip['x'] + skip['w']/2, skip['y'] + skip['h']/2)
    page.wait_for_timeout(4000)
    result['after_skip_pages'] = [{'url': pg.url, 'title': pg.title()} for pg in ctx.pages]
    result['active_page_url'] = page.url
    result['active_title'] = page.title()
    result['body_tail'] = page.locator('body').inner_text()[-1200:]

    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    browser.close()
