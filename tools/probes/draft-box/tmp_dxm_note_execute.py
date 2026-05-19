import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path('/root/.Hermes/workspace/dxm-auto-uikit')
COOKIE_FILE = ROOT / 'data' / 'sessions' / 'dianxiaomi_cookies.json'
OUT_JSON = ROOT / 'data' / 'sessions' / 'dianxiaomi_note_execute.json'
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
    result['switch_claimed'] = page.evaluate(r'''() => {
      const tab = Array.from(document.querySelectorAll('*')).find(el => /^已认领\(\d+\)$/.test((el.innerText||el.textContent||'').replace(/\s+/g,'')));
      if (!tab) return {ok:false};
      const text = (tab.innerText||tab.textContent||'').replace(/\s+/g,'').trim();
      tab.dispatchEvent(new MouseEvent('click', {bubbles:true}));
      return {ok:true, text};
    }''')
    page.wait_for_timeout(1200)

    # open first more dropdown and click add-note item directly from portal list
    result['open_more'] = page.evaluate(r'''() => {
      const row = document.querySelector('tr.vxe-body--row');
      if (!row) return {ok:false, reason:'no_row'};
      const rowText = (row.innerText||row.textContent||'').replace(/\s+/g,' ').trim().slice(0,300);
      const trigger = row.querySelector('.ant-dropdown-trigger');
      if (!trigger) return {ok:false, reason:'no_trigger', rowText};
      for (const evt of ['mouseenter','mouseover','mousedown','mouseup','click']) {
        trigger.dispatchEvent(new MouseEvent(evt, {bubbles:true}));
      }
      return {ok:true, rowText};
    }''')
    page.wait_for_timeout(1200)
    page.screenshot(path=str(OUT_DIR / 'dxm_note_execute_01_more_open.png'), full_page=True)

    result['dropdown_probe'] = page.evaluate(r'''() => {
      const candidates = Array.from(document.querySelectorAll('body *')).map(el => {
        const txt = (el.innerText||el.textContent||'').replace(/\s+/g,' ').trim();
        if (!(txt === '添加备注' || txt === '删除' || txt === '添加备注 删除')) return null;
        const st = getComputedStyle(el); const r = el.getBoundingClientRect();
        return {tag:el.tagName, cls:String(el.className||''), txt, display:st.display, visibility:st.visibility, opacity:st.opacity, rect:{x:r.x,y:r.y,w:r.width,h:r.height}, html:el.outerHTML.slice(0,500)};
      }).filter(Boolean);
      return candidates;
    }''')

    result['click_add_note'] = page.evaluate(r'''() => {
      const exact = Array.from(document.querySelectorAll('body *')).find(el => (el.innerText||el.textContent||'').replace(/\s+/g,'').trim() === '添加备注');
      if (!exact) return {ok:false, reason:'no_add_note_node'};
      for (const evt of ['mouseenter','mouseover','mousedown','mouseup','click']) {
        exact.dispatchEvent(new MouseEvent(evt, {bubbles:true}));
      }
      return {ok:true, tag: exact.tagName, cls:String(exact.className||''), html: exact.outerHTML.slice(0,500)};
    }''')
    page.wait_for_timeout(1500)
    page.screenshot(path=str(OUT_DIR / 'dxm_note_execute_02_note_modal.png'), full_page=True)

    result['modal_probe'] = page.evaluate(r'''() => {
      const mods = Array.from(document.querySelectorAll('[role="dialog"], .ant-modal-wrap, .ant-modal, .ant-drawer, .tox-tinymce, .ql-container')).map(el => ({
        cls:String(el.className||''),
        txt:(el.innerText||el.textContent||'').replace(/\s+/g,' ').trim().slice(0,800),
        html: el.outerHTML.slice(0,1200)
      }));
      const noteModal = mods.find(x => x.txt.includes('备注') || x.txt.includes('添加备注'));
      return {mods: mods.slice(0,20), noteModal};
    }''')

    # write note if modal/input exists
    result['write_note'] = page.evaluate(r'''() => {
      const rich = document.querySelector('[contenteditable="true"], .ql-editor');
      if (rich) {
        rich.innerHTML = '<span style="color:#ff0000;">AI认领</span>';
        rich.dispatchEvent(new Event('input', {bubbles:true}));
        rich.dispatchEvent(new Event('change', {bubbles:true}));
        return {ok:true, mode:'rich-red'};
      }
      const field = Array.from(document.querySelectorAll('textarea, input')).find(el => {
        const r = el.getBoundingClientRect();
        return r.width > 100 && r.height > 20 && !el.disabled;
      });
      if (!field) return {ok:false, reason:'no_input_field'};
      field.value = 'AI认领';
      field.style.color = 'red';
      field.dispatchEvent(new Event('input', {bubbles:true}));
      field.dispatchEvent(new Event('change', {bubbles:true}));
      return {ok:true, mode:'plain-red-style', placeholder: field.getAttribute('placeholder'), cls: field.className || ''};
    }''')
    page.wait_for_timeout(500)
    page.screenshot(path=str(OUT_DIR / 'dxm_note_execute_03_note_filled.png'), full_page=True)

    result['save_note'] = page.evaluate(r'''() => {
      const btn = Array.from(document.querySelectorAll('button, span, a, div')).find(el => {
        const t = (el.innerText||el.textContent||'').replace(/\s+/g,'').trim();
        return t === '保存' || t === '确定';
      });
      if (!btn) return {ok:false, reason:'no_save_btn'};
      btn.dispatchEvent(new MouseEvent('click', {bubbles:true}));
      return {ok:true, text:(btn.innerText||btn.textContent||'').replace(/\s+/g,'').trim(), cls:String(btn.className||'')};
    }''')
    page.wait_for_timeout(3000)
    page.screenshot(path=str(OUT_DIR / 'dxm_note_execute_04_after_save.png'), full_page=True)

    result['after_save'] = page.evaluate(r'''() => ({
      dialogs: Array.from(document.querySelectorAll('[role="dialog"], .ant-modal-wrap, .ant-modal')).map(el => ({cls:String(el.className||''), txt:(el.innerText||el.textContent||'').replace(/\s+/g,' ').trim().slice(0,400)})).slice(0,20),
      body: document.body.innerText.slice(0,5000)
    })''')

    browser.close()

OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(result, ensure_ascii=False, indent=2))
