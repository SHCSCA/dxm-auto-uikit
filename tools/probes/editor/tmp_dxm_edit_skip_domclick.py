import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path('/root/.Hermes/workspace/dxm-auto-uikit')
COOKIE_FILE = ROOT / 'data' / 'sessions' / 'dianxiaomi_cookies.json'
OUT_JSON = ROOT / 'data' / 'sessions' / 'dianxiaomi_edit_skip_domclick.json'
OUT_DIR = ROOT / 'data' / 'screenshots'
OUT_DIR.mkdir(parents=True, exist_ok=True)
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
    result = {'steps': []}

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

    # click edit via DOM event
    edit = page.evaluate(r'''(frag) => {
      const rows = Array.from(document.querySelectorAll('tr.vxe-body--row, tr'));
      const row = rows.find(tr => (tr.innerText||tr.textContent||'').includes(frag));
      if (!row) return {ok:false, reason:'row_not_found'};
      const a = Array.from(row.querySelectorAll('a')).find(el => (el.innerText||el.textContent||'').replace(/\s+/g,'').trim()==='编辑');
      if (!a) return {ok:false, reason:'edit_not_found'};
      a.dispatchEvent(new MouseEvent('click', {bubbles:true}));
      return {ok:true};
    }''', TARGET_TEXT)
    page.wait_for_timeout(1800)
    result['steps'].append({'step':'edit_click', 'data':edit, 'url':page.url, 'title':page.title()})
    page.screenshot(path=str(OUT_DIR / 'dxm_edit_skip_dom_01_dialog.png'), full_page=True)

    probe = page.evaluate(r'''() => {
      const dlg = Array.from(document.querySelectorAll('[role="dialog"], .ant-modal-wrap, .ant-modal')).find(el => {
        const t = (el.innerText||el.textContent||'').replace(/\s+/g,' ').trim();
        return t.includes('跳过，去编辑产品') || t.includes('编辑分类');
      });
      if (!dlg) return {ok:false, reason:'dialog_not_found'};
      const btn = Array.from(dlg.querySelectorAll('button')).find(el => (el.innerText||el.textContent||'').replace(/\s+/g,'').trim()==='跳过，去编辑产品');
      return {ok:true, text:(dlg.innerText||dlg.textContent||'').replace(/\s+/g,' ').trim(), has_button:!!btn};
    }''')
    result['steps'].append({'step':'dialog_probe', 'data':probe})

    # direct element click
    skip = page.evaluate(r'''() => {
      const btn = Array.from(document.querySelectorAll('button')).find(el => (el.innerText||el.textContent||'').replace(/\s+/g,'').trim()==='跳过，去编辑产品');
      if (!btn) return {ok:false, reason:'skip_btn_not_found'};
      btn.click();
      return {ok:true, cls:String(btn.className||'')};
    }''')
    page.wait_for_timeout(5000)
    page.screenshot(path=str(OUT_DIR / 'dxm_edit_skip_dom_02_after_skip.png'), full_page=True)
    result['steps'].append({'step':'skip_click', 'data':skip, 'url':page.url, 'title':page.title()})

    final = page.evaluate(r'''() => {
      const body = document.body.innerText || '';
      return {
        flags: {
          has_dxm_info: body.includes('店小秘信息'),
          has_product_info: body.includes('产品信息'),
          has_save: body.includes('保存'),
          has_publish: body.includes('发布'),
          has_half_manage: body.includes('半托管')
        },
        body: body.slice(0,7000)
      };
    }''')
    result['steps'].append({'step':'final', 'data':final, 'url':page.url, 'title':page.title()})

    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    browser.close()
