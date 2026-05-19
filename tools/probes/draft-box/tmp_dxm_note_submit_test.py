import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path('/root/.Hermes/workspace/dxm-auto-uikit')
COOKIE_FILE = ROOT / 'data' / 'sessions' / 'dianxiaomi_cookies.json'
OUT_JSON = ROOT / 'data' / 'sessions' / 'dianxiaomi_note_submit_test.json'
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

    page.evaluate(r'''() => {
      const tab = Array.from(document.querySelectorAll('*')).find(el => /^已认领\(\d+\)$/.test((el.innerText||el.textContent||'').replace(/\s+/g,'')));
      if (tab) tab.dispatchEvent(new MouseEvent('click', {bubbles:true}));
    }''')
    page.wait_for_timeout(1200)
    result['steps'].append({'step':'switch_claimed_done'})

    # retry opening more dropdown until item visible
    add_note_item = None
    for i in range(5):
        page.evaluate(r'''() => {
          const row = document.querySelector('tr.vxe-body--row');
          const trigger = row && row.querySelector('.ant-dropdown-trigger');
          if (trigger) {
            for (const evt of ['mouseenter','mouseover','mousedown','mouseup','click']) trigger.dispatchEvent(new MouseEvent(evt,{bubbles:true}));
          }
        }''')
        page.wait_for_timeout(1000)
        add_note_item = page.evaluate(r'''() => {
          const el = Array.from(document.querySelectorAll('li.ant-dropdown-menu-item')).find(el => (el.innerText||el.textContent||'').replace(/\s+/g,'').trim()==='添加备注');
          if (!el) return null;
          const r = el.getBoundingClientRect();
          return {x:r.x,y:r.y,w:r.width,h:r.height, txt:(el.innerText||el.textContent||'').trim()};
        }''')
        if add_note_item:
            break
    result['steps'].append({'step':'dropdown_item', 'item': add_note_item})
    if not add_note_item:
        OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False, indent=2))
        browser.close()
        raise SystemExit

    page.mouse.click(add_note_item['x'] + add_note_item['w']/2, add_note_item['y'] + add_note_item['h']/2)
    page.wait_for_timeout(1500)
    page.screenshot(path=str(OUT_DIR / 'dxm_note_submit_01_modal_open.png'), full_page=True)

    modal_open = page.evaluate(r'''() => {
      const modal = Array.from(document.querySelectorAll('[role="dialog"], .ant-modal-wrap')).find(el => (el.innerText||el.textContent||'').includes('备注') && (el.innerText||el.textContent||'').includes('颜色'));
      return modal ? {ok:true, text:(modal.innerText||modal.textContent||'').replace(/\s+/g,' ').trim()} : {ok:false};
    }''')
    result['steps'].append({'step':'modal_open', **modal_open})

    # fill content and select red color by DOM
    action = page.evaluate(r'''() => {
      const modal = Array.from(document.querySelectorAll('[role="dialog"], .ant-modal-wrap')).find(el => (el.innerText||el.textContent||'').includes('备注') && (el.innerText||el.textContent||'').includes('颜色'));
      if (!modal) return {ok:false, reason:'no_note_modal'};

      const field = Array.from(modal.querySelectorAll('textarea, input')).find(el => {
        const r = el.getBoundingClientRect();
        return r.width > 100 && r.height > 20 && !el.disabled;
      });
      let fieldInfo = null;
      if (field) {
        field.value = 'AI认领';
        field.style.color = 'red';
        field.dispatchEvent(new Event('input', {bubbles:true}));
        field.dispatchEvent(new Event('change', {bubbles:true}));
        fieldInfo = {tag: field.tagName, placeholder: field.getAttribute('placeholder'), cls: String(field.className||'')};
      }

      const colorEl = Array.from(modal.querySelectorAll('*')).find(el => {
        const st = getComputedStyle(el);
        const r = el.getBoundingClientRect();
        const bg = st.backgroundColor;
        return r.width >= 12 && r.width <= 40 && r.height >= 12 && r.height <= 40 && (bg.includes('255, 0, 0') || bg.includes('220, 20, 60') || bg.includes('231, 76, 60') || bg.includes('red'));
      });
      let colorInfo = null;
      if (colorEl) {
        colorEl.dispatchEvent(new MouseEvent('click', {bubbles:true}));
        colorInfo = {tag: colorEl.tagName, cls: String(colorEl.className||''), bg: getComputedStyle(colorEl).backgroundColor};
      }

      const submit = Array.from(modal.querySelectorAll('button, span, a, div')).find(el => (el.innerText||el.textContent||'').replace(/\s+/g,'').trim()==='提交');
      let submitInfo = null;
      if (submit) {
        submit.dispatchEvent(new MouseEvent('click', {bubbles:true}));
        submitInfo = {tag: submit.tagName, cls: String(submit.className||'')};
      }

      return {ok:true, fieldInfo, colorInfo, submitInfo};
    }''')
    page.wait_for_timeout(2500)
    page.screenshot(path=str(OUT_DIR / 'dxm_note_submit_02_after_submit.png'), full_page=True)
    result['steps'].append({'step':'submit_action', **action})

    result['steps'].append({'step':'after_submit_state', 'dialogs': page.evaluate(r'''() => Array.from(document.querySelectorAll('[role="dialog"], .ant-modal-wrap, .ant-modal')).map(el => ({cls:String(el.className||''), txt:(el.innerText||el.textContent||'').replace(/\s+/g,' ').trim().slice(0,400)})).slice(0,20)'''), 'body': page.locator('body').inner_text()[:4500]})

    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    browser.close()
