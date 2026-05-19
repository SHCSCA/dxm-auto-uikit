import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path('/root/.Hermes/workspace/dxm-auto-uikit')
COOKIE_FILE = ROOT / 'data' / 'sessions' / 'dianxiaomi_cookies.json'
OUT_JSON = ROOT / 'data' / 'sessions' / 'dianxiaomi_note_probe.json'
OUT_DIR = ROOT / 'data' / 'screenshots'
OUT_DIR.mkdir(parents=True, exist_ok=True)


def load_cookies():
    raw = json.loads(COOKIE_FILE.read_text(encoding='utf-8'))
    cookies = []
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
        cookies.append(item)
    return cookies


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
    ctx = browser.new_context(ignore_https_errors=True, viewport={'width': 1600, 'height': 1400})
    ctx.add_cookies(load_cookies())
    page = ctx.new_page()
    result = {}

    page.goto('https://www.dianxiaomi.com/web/productCrawl/dataAcquisition', wait_until='domcontentloaded', timeout=45000)
    page.wait_for_timeout(3500)
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

    # Switch to 已认领 tab using DOM click dispatch because overlays / virtual table can interfere
    result['tab_switch'] = page.evaluate(r'''() => {
      const tab = Array.from(document.querySelectorAll('*')).find(el => (el.innerText || el.textContent || '').replace(/\s+/g, '').trim() === '已认领(764)');
      if (!tab) return {ok:false, reason:'claimed_tab_not_found'};
      tab.dispatchEvent(new MouseEvent('click', {bubbles:true}));
      return {ok:true, text:(tab.innerText||tab.textContent||'').trim(), cls: tab.className || ''};
    }''')
    page.wait_for_timeout(1200)
    page.screenshot(path=str(OUT_DIR / 'dxm_note_probe_claimed_tab.png'), full_page=True)

    # open first 更多 dropdown in claimed list
    result['open_more'] = page.evaluate(r'''() => {
      const more = Array.from(document.querySelectorAll('a,div,span,button')).find(el => (el.innerText || el.textContent || '').replace(/\s+/g, '').trim() === '更多');
      if (!more) return {ok:false, reason:'more_not_found'};
      more.dispatchEvent(new MouseEvent('click', {bubbles:true}));
      return {ok:true, tag: more.tagName, cls: more.className || ''};
    }''')
    page.wait_for_timeout(1000)
    page.screenshot(path=str(OUT_DIR / 'dxm_note_probe_more_menu.png'), full_page=True)

    # click 添加备注
    result['click_add_note'] = page.evaluate(r'''() => {
      const note = Array.from(document.querySelectorAll('li,div,a,span')).find(el => (el.innerText || el.textContent || '').replace(/\s+/g, '').trim() === '添加备注');
      if (!note) return {ok:false, reason:'add_note_not_found'};
      note.dispatchEvent(new MouseEvent('click', {bubbles:true}));
      return {ok:true, tag: note.tagName, cls: note.className || ''};
    }''')
    page.wait_for_timeout(1500)
    page.screenshot(path=str(OUT_DIR / 'dxm_note_probe_add_note_dialog.png'), full_page=True)

    result['note_modal'] = page.evaluate(r'''() => {
      const dialog = Array.from(document.querySelectorAll('[role="dialog"], .ant-modal-wrap, .ant-drawer, .tox-tinymce')).find(el => {
        const txt = (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
        return txt.includes('备注') || txt.includes('添加备注') || txt.includes('保存') || txt.includes('确定');
      });
      const all = Array.from(document.querySelectorAll('input, textarea, button, a, span, div, [contenteditable="true"], .tox-tinymce, .tox-toolbar, .tox-edit-area, .ql-editor')).map(el => {
        const st = getComputedStyle(el);
        const r = el.getBoundingClientRect();
        if (st.display === 'none' || st.visibility === 'hidden' || parseFloat(st.opacity || '1') === 0 || r.width < 5 || r.height < 5) return null;
        return {
          tag: el.tagName,
          text: (el.innerText || el.textContent || el.getAttribute('value') || '').replace(/\s+/g, ' ').trim().slice(0,120),
          placeholder: el.getAttribute('placeholder'),
          cls: el.className || '',
          id: el.id || '',
          style: el.getAttribute('style') || '',
          rect: {x:r.x, y:r.y, w:r.width, h:r.height}
        };
      }).filter(Boolean);
      return {
        dialog_text: dialog ? (dialog.innerText || dialog.textContent || '').replace(/\s+/g, ' ').trim().slice(0,2000) : null,
        dialog_html: dialog ? dialog.outerHTML.slice(0,5000) : null,
        controls: all.slice(0,250)
      };
    }''')

    browser.close()

OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(result, ensure_ascii=False, indent=2))
