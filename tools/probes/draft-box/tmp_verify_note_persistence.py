import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path('/root/.Hermes/workspace/dxm-auto-uikit')
COOKIE_FILE = ROOT / 'data' / 'sessions' / 'dianxiaomi_cookies.json'
OUT_JSON = ROOT / 'data' / 'sessions' / 'dianxiaomi_note_verify.json'
OUT_DIR = ROOT / 'data' / 'screenshots'
OUT_DIR.mkdir(parents=True, exist_ok=True)

TARGET_TEXT = '崩坏3钥匙扣爱莉希雅'


def load_cookies():
    raw = json.loads(COOKIE_FILE.read_text(encoding='utf-8'))
    out = []
    for c in raw:
        item = {
            'name': c['name'], 'value': c['value'], 'domain': c['domain'], 'path': c.get('path', '/'),
            'httpOnly': c.get('httpOnly', False), 'secure': c.get('secure', False)
        }
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

    page.goto('https://www.dianxiaomi.com/web/productCrawl/dataAcquisition', wait_until='domcontentloaded', timeout=45000)
    page.wait_for_timeout(3000)
    try:
        page.locator('.ant-modal-close').first.click(force=True)
        page.wait_for_timeout(800)
    except Exception:
        pass
    try:
        page.get_by_text('跳过', exact=True).click(force=True, timeout=1500)
        page.wait_for_timeout(800)
    except Exception:
        pass

    # switch to claimed tab
    tab_res = page.evaluate(r'''() => {
      const tab = Array.from(document.querySelectorAll('*')).find(el => /^已认领\(\d+\)$/.test((el.innerText||el.textContent||'').replace(/\s+/g,'')));
      if (!tab) return {ok:false};
      const text = (tab.innerText||tab.textContent||'').replace(/\s+/g,'').trim();
      tab.dispatchEvent(new MouseEvent('click', {bubbles:true}));
      return {ok:true, text};
    }''')
    page.wait_for_timeout(1200)
    result['steps'].append({'step': 'switch_claimed', **tab_res})

    # search target row by title
    search_res = page.evaluate('(frag) => {\n'
        'const input = Array.from(document.querySelectorAll("input.ant-input, input")).find(el => { const r = el.getBoundingClientRect(); return r.width > 200 && r.height > 20 && !el.disabled; });\n'
        'if (!input) return {ok:false, reason:"no_input"};\n'
        'input.value = frag; input.dispatchEvent(new Event("input", {bubbles:true})); input.dispatchEvent(new Event("change", {bubbles:true}));\n'
        'const btn = Array.from(document.querySelectorAll("button, span, a, div")).find(el => (el.innerText||el.textContent||"").replace(/\\s+/g,"").trim()==="搜索");\n'
        'if (btn) btn.dispatchEvent(new MouseEvent("click", {bubbles:true}));\n'
        'return {ok:true, value: input.value};\n'
        '}', TARGET_TEXT)
    page.wait_for_timeout(2000)
    page.screenshot(path=str(OUT_DIR / 'dxm_note_verify_01_search.png'), full_page=True)
    result['steps'].append({'step': 'search', **search_res})

    # locate matching row and open more menu
    row_res = page.evaluate('(frag) => {\n'
        'const rows = Array.from(document.querySelectorAll("tr.vxe-body--row, tr"));\n'
        'let row = rows.find(tr => (tr.innerText||tr.textContent||"").includes(frag));\n'
        'if (!row) return {ok:false, reason:"row_not_found"};\n'
        'const rowText = (row.innerText||row.textContent||"").replace(/\\s+/g," ").trim().slice(0,400);\n'
        'const trigger = row.querySelector(".ant-dropdown-trigger");\n'
        'if (!trigger) return {ok:false, reason:"no_trigger", rowText};\n'
        'for (const evt of ["mouseenter","mouseover","mousedown","mouseup","click"]) trigger.dispatchEvent(new MouseEvent(evt,{bubbles:true}));\n'
        'return {ok:true, rowText};\n'
        '}', TARGET_TEXT)
    page.wait_for_timeout(1200)
    result['steps'].append({'step': 'open_more', **row_res})

    # click add note from dropdown
    item = page.evaluate(r'''() => {
      const el = Array.from(document.querySelectorAll('li.ant-dropdown-menu-item')).find(el => (el.innerText||el.textContent||'').replace(/\s+/g,'').trim()==='添加备注');
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return {x:r.x,y:r.y,w:r.width,h:r.height};
    }''')
    result['steps'].append({'step': 'dropdown_item_found', 'item': item})
    if item:
        page.mouse.click(item['x'] + item['w']/2, item['y'] + item['h']/2)
        page.wait_for_timeout(1500)
    page.screenshot(path=str(OUT_DIR / 'dxm_note_verify_02_modal.png'), full_page=True)

    verify = page.evaluate(r'''() => {
      const modal = Array.from(document.querySelectorAll('[role="dialog"], .ant-modal-wrap, .ant-modal')).find(el => {
        const t = (el.innerText||el.textContent||'').replace(/\s+/g,' ').trim();
        return t.includes('备注') && t.includes('颜色');
      });
      if (!modal) return {ok:false, reason:'no_modal'};
      const field = Array.from(modal.querySelectorAll('textarea, input')).find(el => {
        const r = el.getBoundingClientRect();
        return r.width > 150 && r.height > 20 && !el.disabled;
      });
      const value = field ? (field.value || '') : '';
      const redSelected = Array.from(modal.querySelectorAll('*')).some(el => {
        const st = getComputedStyle(el);
        const cls = String(el.className||'');
        const bg = st.backgroundColor || '';
        const border = st.borderColor || '';
        return (bg.includes('255, 0, 0') || border.includes('255, 0, 0')) && (cls.includes('active') || cls.includes('selected') || cls.includes('border-#333') || cls.includes('border-#000') || cls.includes('border-black'));
      });
      const redNodes = Array.from(modal.querySelectorAll('*')).map(el => {
        const st = getComputedStyle(el);
        const cls = String(el.className||'');
        const bg = st.backgroundColor || '';
        const border = st.borderColor || '';
        const r = el.getBoundingClientRect();
        if (r.width < 8 || r.height < 8) return null;
        if (bg.includes('255, 0, 0') || border.includes('255, 0, 0')) {
          return {tag: el.tagName, cls, bg, border, txt: (el.innerText||el.textContent||'').replace(/\s+/g,' ').trim(), rect:{x:r.x,y:r.y,w:r.width,h:r.height}};
        }
        return null;
      }).filter(Boolean).slice(0,20);
      return {
        ok:true,
        modal_text:(modal.innerText||modal.textContent||'').replace(/\s+/g,' ').trim(),
        field_value:value,
        field_placeholder: field ? field.getAttribute('placeholder') : None,
        red_selected:redSelected,
        red_nodes:redNodes
      };
    }'''.replace('None', 'null'))
    result['steps'].append({'step': 'verify_modal', **verify})

    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    browser.close()
