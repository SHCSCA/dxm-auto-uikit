import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path('/root/.Hermes/workspace/dxm-auto-uikit')
COOKIE_FILE = ROOT / 'data' / 'sessions' / 'dianxiaomi_cookies.json'
OUT_JSON = ROOT / 'data' / 'sessions' / 'dianxiaomi_box_note_precise.json'
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
    page.screenshot(path=str(OUT_DIR / 'dxm_box_note_precise_01_search.png'), full_page=True)

    row_info = page.evaluate(r'''(frag) => {
      const rows = Array.from(document.querySelectorAll('tr.vxe-body--row, tr'));
      const matches = rows.map((tr, idx) => ({idx, text:(tr.innerText||tr.textContent||'').replace(/\s+/g,' ').trim()})).filter(x => x.text.includes(frag));
      const picked = matches.find(x => !x.text.includes('备注:')) || matches[0] || null;
      if (!picked) return {ok:false, matches};
      const row = rows[picked.idx];
      const actions = Array.from(row.querySelectorAll('*')).map(el => {
        const txt = (el.innerText||el.textContent||'').replace(/\s+/g,' ').trim();
        const r = el.getBoundingClientRect();
        if (!txt || r.width < 5 || r.height < 5) return null;
        if (!['移入待发布','编辑','发布','更多'].includes(txt)) return null;
        return {txt, tag: el.tagName, cls: String(el.className||''), rect: {x:r.x,y:r.y,w:r.width,h:r.height}, html: el.outerHTML.slice(0,200)};
      }).filter(Boolean);
      return {ok:true, rowIndex:picked.idx, rowText:picked.text.slice(0,600), actions};
    }''', TARGET_TEXT)
    result['steps'].append({'step':'row_info','data':row_info})

    if not row_info.get('ok') or not row_info.get('actions'):
        OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False, indent=2))
        browser.close()
        raise SystemExit

    more = next((a for a in row_info['actions'] if a['txt'] == '更多'), None)
    result['steps'].append({'step':'more_target','data':more})
    if not more:
        OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False, indent=2))
        browser.close()
        raise SystemExit

    page.mouse.click(more['rect']['x'] + more['rect']['w']/2, more['rect']['y'] + more['rect']['h']/2)
    page.wait_for_timeout(1500)
    page.screenshot(path=str(OUT_DIR / 'dxm_box_note_precise_02_more_clicked.png'), full_page=True)

    dropdown = page.evaluate(r'''() => {
      return Array.from(document.querySelectorAll('.ant-dropdown, .ant-dropdown-menu, li.ant-dropdown-menu-item')).map(el => {
        const r = el.getBoundingClientRect();
        const st = getComputedStyle(el);
        return {tag:el.tagName, cls:String(el.className||''), txt:(el.innerText||el.textContent||'').replace(/\s+/g,' ').trim(), rect:{x:r.x,y:r.y,w:r.width,h:r.height}, display:st.display, visibility:st.visibility};
      }).filter(x => x.txt || x.cls.includes('dropdown')).slice(0,30)
    }''')
    result['steps'].append({'step':'dropdown','data':dropdown})

    add_note = page.evaluate(r'''() => {
      const el = Array.from(document.querySelectorAll('li.ant-dropdown-menu-item')).find(el => (el.innerText||el.textContent||'').replace(/\s+/g,'').trim()==='添加备注');
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return {txt:(el.innerText||el.textContent||'').trim(), rect:{x:r.x,y:r.y,w:r.width,h:r.height}};
    }''')
    result['steps'].append({'step':'add_note','data':add_note})
    if not add_note:
        OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False, indent=2))
        browser.close()
        raise SystemExit

    page.mouse.click(add_note['rect']['x'] + add_note['rect']['w']/2, add_note['rect']['y'] + add_note['rect']['h']/2)
    page.wait_for_timeout(1500)
    page.screenshot(path=str(OUT_DIR / 'dxm_box_note_precise_03_note_modal.png'), full_page=True)

    modal_info = page.evaluate(r'''() => {
      const modal = Array.from(document.querySelectorAll('[role="dialog"], .ant-modal-wrap, .ant-modal')).find(el => {
        const t = (el.innerText||el.textContent||'').replace(/\s+/g,' ').trim();
        return t.includes('备注') && t.includes('颜色');
      });
      if (!modal) return {ok:false};
      const field = Array.from(modal.querySelectorAll('textarea,input')).find(el => {
        const r = el.getBoundingClientRect();
        return r.width > 150 && r.height > 20 && !el.disabled;
      });
      return {ok:true, modalText:(modal.innerText||modal.textContent||'').replace(/\s+/g,' ').trim(), fieldValue: field.value || '', placeholder: field.getAttribute('placeholder')};
    }''')
    result['steps'].append({'step':'modal_info','data':modal_info})
    if not modal_info.get('ok'):
        OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False, indent=2))
        browser.close()
        raise SystemExit

    write_res = page.evaluate(r'''() => {
      const modal = Array.from(document.querySelectorAll('[role="dialog"], .ant-modal-wrap, .ant-modal')).find(el => {
        const t = (el.innerText||el.textContent||'').replace(/\s+/g,' ').trim();
        return t.includes('备注') && t.includes('颜色');
      });
      const field = Array.from(modal.querySelectorAll('textarea,input')).find(el => {
        const r = el.getBoundingClientRect();
        return r.width > 150 && r.height > 20 && !el.disabled;
      });
      field.value = 'AI认领';
      field.style.color = 'red';
      field.dispatchEvent(new Event('input', {bubbles:true}));
      field.dispatchEvent(new Event('change', {bubbles:true}));
      const red = Array.from(modal.querySelectorAll('*')).find(el => {
        const st = getComputedStyle(el);
        const r = el.getBoundingClientRect();
        return r.width >= 12 && r.width <= 40 && r.height >= 12 && r.height <= 40 && (st.backgroundColor||'').includes('255, 0, 0');
      });
      let redInfo = null;
      if (red) {
        red.dispatchEvent(new MouseEvent('click', {bubbles:true}));
        const st = getComputedStyle(red);
        redInfo = {bg: st.backgroundColor, border: st.borderColor, cls: String(red.className||'')};
      }
      const submit = Array.from(modal.querySelectorAll('button,span,a,div')).find(el => (el.innerText||el.textContent||'').replace(/\s+/g,'').trim()==='提交');
      let submitInfo = null;
      if (submit) {
        submit.dispatchEvent(new MouseEvent('click', {bubbles:true}));
        submitInfo = {tag: submit.tagName, cls: String(submit.className||'')};
      }
      return {ok:true, redInfo, submitInfo};
    }''')
    page.wait_for_timeout(2500)
    page.screenshot(path=str(OUT_DIR / 'dxm_box_note_precise_04_after_submit.png'), full_page=True)
    result['steps'].append({'step':'write_submit','data':write_res})

    verify = page.evaluate(r'''(rowIndex) => {
      const rows = Array.from(document.querySelectorAll('tr.vxe-body--row, tr'));
      const row = rows[rowIndex];
      if (!row) return {ok:false};
      return {ok:true, rowText:(row.innerText||row.textContent||'').replace(/\s+/g,' ').trim().slice(0,700)};
    }''', row_info['rowIndex'])
    result['steps'].append({'step':'verify','data':verify, 'body':page.locator('body').inner_text()[:4500]})

    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    browser.close()
