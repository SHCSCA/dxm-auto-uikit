import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path('/root/.Hermes/workspace/dxm-auto-uikit')
COOKIE_FILE = ROOT / 'data' / 'sessions' / 'dianxiaomi_cookies.json'
OUT_JSON = ROOT / 'data' / 'sessions' / 'dianxiaomi_box_note_test.json'
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

    page.goto('https://www.dianxiaomi.com/web/smt/smtProductList/draft', wait_until='domcontentloaded', timeout=45000)
    page.wait_for_timeout(3500)
    page.screenshot(path=str(OUT_DIR / 'dxm_box_note_01_landing.png'), full_page=True)
    result['steps'].append({'step':'landing','url':page.url,'title':page.title(),'body':page.locator('body').inner_text()[:2500]})

    # ensure Dang Kang selected in box page
    store_switch = page.evaluate('(target) => {\n'
        'const node = Array.from(document.querySelectorAll("*")).find(el => (el.innerText||el.textContent||"").replace(/\\s+/g,"").trim()===target.replace(/\\s+/g,""));\n'
        'if (!node) return {ok:false, reason:"store_not_found"};\n'
        'node.dispatchEvent(new MouseEvent("click", {bubbles:true}));\n'
        'return {ok:true, text:(node.innerText||node.textContent||"").trim(), cls:String(node.className||"")};\n'
        '}', 'Dang Kang')
    page.wait_for_timeout(1200)
    result['steps'].append({'step':'switch_store','res':store_switch})

    # search target title in collection box
    search_res = page.evaluate('(frag) => {\n'
        'const input = Array.from(document.querySelectorAll("input.ant-input, input")).find(el => { const r = el.getBoundingClientRect(); return r.width > 220 && r.height > 20 && !el.disabled; });\n'
        'if (!input) return {ok:false, reason:"no_search_input"};\n'
        'input.value = frag; input.dispatchEvent(new Event("input", {bubbles:true})); input.dispatchEvent(new Event("change", {bubbles:true}));\n'
        'const btn = Array.from(document.querySelectorAll("button, span, a, div")).find(el => (el.innerText||el.textContent||"").replace(/\\s+/g,"").trim()==="搜索");\n'
        'if (btn) btn.dispatchEvent(new MouseEvent("click", {bubbles:true}));\n'
        'return {ok:true, value: input.value};\n'
        '}', TARGET_TEXT)
    page.wait_for_timeout(2000)
    page.screenshot(path=str(OUT_DIR / 'dxm_box_note_02_search.png'), full_page=True)
    result['steps'].append({'step':'search','res':search_res,'body':page.locator('body').inner_text()[:3500]})

    # find row and open more in collection box
    row_res = page.evaluate('(frag) => {\n'
        'const rows = Array.from(document.querySelectorAll("tr.vxe-body--row, tr"));\n'
        'let row = rows.find(tr => (tr.innerText||tr.textContent||"").includes(frag));\n'
        'if (!row) return {ok:false, reason:"row_not_found"};\n'
        'const rowText = (row.innerText||row.textContent||"").replace(/\\s+/g," ").trim().slice(0,500);\n'
        'const trigger = row.querySelector(".ant-dropdown-trigger");\n'
        'if (!trigger) return {ok:false, reason:"no_more_trigger", rowText};\n'
        'for (const evt of ["mouseenter","mouseover","mousedown","mouseup","click"]) trigger.dispatchEvent(new MouseEvent(evt,{bubbles:true}));\n'
        'return {ok:true, rowText};\n'
        '}', TARGET_TEXT)
    page.wait_for_timeout(1200)
    page.screenshot(path=str(OUT_DIR / 'dxm_box_note_03_more.png'), full_page=True)
    result['steps'].append({'step':'open_more','res':row_res})

    # inspect dropdown
    dropdown = page.evaluate(r'''() => {
      return Array.from(document.querySelectorAll('li.ant-dropdown-menu-item, .ant-dropdown, .ant-dropdown-menu')).map(el => {
        const st = getComputedStyle(el); const r = el.getBoundingClientRect();
        return {tag:el.tagName, cls:String(el.className||''), txt:(el.innerText||el.textContent||'').replace(/\s+/g,' ').trim(), display:st.display, visibility:st.visibility, rect:{x:r.x,y:r.y,w:r.width,h:r.height}};
      }).filter(x => x.txt || x.cls.includes('dropdown')).slice(0,50)
    }''')
    result['steps'].append({'step':'dropdown_probe','items':dropdown})

    # click add note if exists
    item = page.evaluate(r'''() => {
      const el = Array.from(document.querySelectorAll('li.ant-dropdown-menu-item')).find(el => (el.innerText||el.textContent||'').replace(/\s+/g,'').trim()==='添加备注');
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return {x:r.x,y:r.y,w:r.width,h:r.height, txt:(el.innerText||el.textContent||'').trim()};
    }''')
    result['steps'].append({'step':'add_note_item','item':item})
    if item:
        page.mouse.click(item['x'] + item['w']/2, item['y'] + item['h']/2)
        page.wait_for_timeout(1500)
    page.screenshot(path=str(OUT_DIR / 'dxm_box_note_04_modal.png'), full_page=True)

    modal = page.evaluate(r'''() => {
      const modal = Array.from(document.querySelectorAll('[role="dialog"], .ant-modal-wrap, .ant-modal')).find(el => {
        const t = (el.innerText||el.textContent||'').replace(/\s+/g,' ').trim();
        return t.includes('备注') && t.includes('颜色');
      });
      if (!modal) return {ok:false, reason:'no_note_modal'};
      const field = Array.from(modal.querySelectorAll('textarea, input')).find(el => {
        const r = el.getBoundingClientRect();
        return r.width > 150 and r.height > 20
      });
      return {
        ok:true,
        modal_text:(modal.innerText||modal.textContent||'').replace(/\s+/g,' ').trim(),
        field_value: field ? (field.value || '') : '',
        field_placeholder: field ? field.getAttribute('placeholder') : null,
      };
    }'''.replace(' and ', ' && '))
    result['steps'].append({'step':'modal_probe','res':modal})

    if modal.get('ok'):
        write_res = page.evaluate(r'''() => {
          const modal = Array.from(document.querySelectorAll('[role="dialog"], .ant-modal-wrap, .ant-modal')).find(el => {
            const t = (el.innerText||el.textContent||'').replace(/\s+/g,' ').trim();
            return t.includes('备注') && t.includes('颜色');
          });
          if (!modal) return {ok:false, reason:'no_modal'};
          const field = Array.from(modal.querySelectorAll('textarea, input')).find(el => {
            const r = el.getBoundingClientRect();
            return r.width > 150 && r.height > 20 && !el.disabled;
          });
          if (!field) return {ok:false, reason:'no_field'};
          field.value = 'AI认领';
          field.style.color = 'red';
          field.dispatchEvent(new Event('input', {bubbles:true}));
          field.dispatchEvent(new Event('change', {bubbles:true}));
          const colorEl = Array.from(modal.querySelectorAll('*')).find(el => {
            const st = getComputedStyle(el);
            const bg = st.backgroundColor || '';
            const r = el.getBoundingClientRect();
            return r.width >= 12 && r.width <= 40 && r.height >= 12 && r.height <= 40 && bg.includes('255, 0, 0');
          });
          let colorInfo = null;
          if (colorEl) {
            colorEl.dispatchEvent(new MouseEvent('click', {bubbles:true}));
            colorInfo = {bg:getComputedStyle(colorEl).backgroundColor, border:getComputedStyle(colorEl).borderColor, cls:String(colorEl.className||'')};
          }
          const submit = Array.from(modal.querySelectorAll('button, span, a, div')).find(el => (el.innerText||el.textContent||'').replace(/\s+/g,'').trim()==='提交');
          let submitInfo = null;
          if (submit) {
            submit.dispatchEvent(new MouseEvent('click', {bubbles:true}));
            submitInfo = {tag:submit.tagName, cls:String(submit.className||'')};
          }
          return {ok:true, colorInfo, submitInfo};
        }''')
        page.wait_for_timeout(2500)
        page.screenshot(path=str(OUT_DIR / 'dxm_box_note_05_after_submit.png'), full_page=True)
        result['steps'].append({'step':'write_submit','res':write_res})

    # verify row after submit on box page
    verify = page.evaluate('(frag) => {\n'
        'const rows = Array.from(document.querySelectorAll("tr.vxe-body--row, tr"));\n'
        'const row = rows.find(tr => (tr.innerText||tr.textContent||"").includes(frag));\n'
        'if (!row) return {ok:false, reason:"row_not_found_after_submit"};\n'
        'return {ok:true, rowText:(row.innerText||row.textContent||"").replace(/\\s+/g," ").trim().slice(0,600)};\n'
        '}', TARGET_TEXT)
    result['steps'].append({'step':'verify_row','res':verify,'body':page.locator('body').inner_text()[:4500]})

    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    browser.close()
