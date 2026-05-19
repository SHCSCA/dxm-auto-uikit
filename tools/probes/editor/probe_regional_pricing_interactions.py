import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path('/root/.Hermes/workspace/dxm-auto-uikit')
COOKIE_FILE = ROOT / 'data' / 'sessions' / 'dianxiaomi_cookies.json'
OUT_JSON = ROOT / 'data' / 'sessions' / 'dianxiaomi_regional_pricing_interactions.json'
OUT_DIR = ROOT / 'data' / 'screenshots'
OUT_DIR.mkdir(parents=True, exist_ok=True)
TARGET_URL = 'https://www.dianxiaomi.com/web/smt/edit?id=130658341226453206'


def load_cookies():
    raw = json.loads(COOKIE_FILE.read_text(encoding='utf-8'))
    out = []
    for c in raw:
        item = {
            'name': c['name'],
            'value': c['value'],
            'domain': c['domain'],
            'path': c.get('path', '/'),
            'httpOnly': c.get('httpOnly', False),
            'secure': c.get('secure', False),
        }
        ss = c.get('sameSite')
        if ss in ('lax', 'strict', 'none', 'Lax', 'Strict', 'None'):
            item['sameSite'] = ss.capitalize() if ss.lower() != 'none' else 'None'
        if 'expirationDate' in c:
            item['expires'] = int(c['expirationDate'])
        out.append(item)
    return out


JS_SECTION = r'''
() => {
  const clean = (s) => String(s || '').replace(/\s+/g, ' ').trim();
  const visible = (el) => {
    if (!el) return false;
    const st = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return st.display !== 'none' && st.visibility !== 'hidden' && parseFloat(st.opacity || '1') !== 0 && r.width > 3 && r.height > 3;
  };
  const txt = (el) => clean(el.innerText || el.textContent || '');
  const section = Array.from(document.querySelectorAll('.form-card')).find(card => visible(card) && txt(card).includes('区域调价信息'));
  if (!section) return {found:false};
  const controls = Array.from(section.querySelectorAll('input, textarea, select, button, label, .ant-select, .ant-select-selector, .ant-radio-wrapper, .ant-checkbox-wrapper, .vxe-table, .vxe-header--row, .vxe-body--row')).filter(visible).map(el => ({
    tag: el.tagName,
    text: txt(el).slice(0, 200),
    cls: clean(el.className || ''),
    type: el.getAttribute('type') || '',
    placeholder: el.getAttribute('placeholder') || '',
    value: el.value || ''
  })).slice(0, 250);
  return {
    found:true,
    section_text: txt(section).slice(0, 10000),
    controls,
  };
}
'''

JS_MODAL = r'''
() => {
  const clean = (s) => String(s || '').replace(/\s+/g, ' ').trim();
  const visible = (el) => {
    if (!el) return false;
    const st = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return st.display !== 'none' && st.visibility !== 'hidden' && parseFloat(st.opacity || '1') !== 0 && r.width > 3 && r.height > 3;
  };
  const txt = (el) => clean(el.innerText || el.textContent || '');
  const dialogs = Array.from(document.querySelectorAll('[role="dialog"], .ant-modal, .ant-modal-wrap, .vxe-table--body-wrapper, .ant-drawer, .ant-popover, .ant-dropdown')).filter(visible).map(el => ({
    tag: el.tagName,
    cls: clean(el.className || ''),
    text: txt(el).slice(0, 3000)
  }));
  const controls = Array.from(document.querySelectorAll('input, textarea, button, label, .ant-select, .ant-select-selector, .ant-radio-wrapper, .ant-checkbox-wrapper, table, .vxe-table, .vxe-header--row, .vxe-body--row')).filter(visible).map(el => ({
    tag: el.tagName,
    cls: clean(el.className || ''),
    text: txt(el).slice(0, 200),
    type: el.getAttribute('type') || '',
    placeholder: el.getAttribute('placeholder') || '',
    value: el.value || ''
  })).slice(0, 300);
  return {dialogs, controls};
}
'''

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
    ctx = browser.new_context(ignore_https_errors=True, viewport={'width': 1600, 'height': 2600})
    ctx.add_cookies(load_cookies())
    page = ctx.new_page()
    result = {'steps': []}
    page.goto(TARGET_URL, wait_until='domcontentloaded', timeout=45000)
    page.wait_for_timeout(5000)
    page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.55)")
    page.wait_for_timeout(1200)
    page.screenshot(path=str(OUT_DIR / 'dxm_regional_interactions_01_section.png'), full_page=True)
    section = page.evaluate(JS_SECTION)
    result['steps'].append({'step': 'initial_section', 'data': section})

    # close blocking notice/bullet modal if present
    try:
        page.locator('.ant-modal-close, .comm-modal .anticon-close, .bullet-layer .ant-modal-close, .bullet-layer button:has-text("关闭")').first.click(timeout=2500)
        page.wait_for_timeout(1200)
        result['steps'].append({'step': 'close_overlay', 'status': 'clicked_close'})
    except Exception as exc:
        result['steps'].append({'step': 'close_overlay', 'status': 'not_closed', 'error': str(exc)})

    # hard-remove persistent overlay/iframe when click-close fails
    removed = page.evaluate(r'''() => {
      const selectors = ['.bullet-layer', '.comm-modal', '.ant-modal-wrap', '.ant-modal-mask', '#theNewestModalLabelFrame'];
      const removed = [];
      for (const sel of selectors) {
        for (const el of document.querySelectorAll(sel)) {
          removed.push({sel, cls: String(el.className || ''), id: el.id || ''});
          el.remove();
        }
      }
      return removed;
    }''')
    page.wait_for_timeout(500)
    result['steps'].append({'step': 'remove_overlay_nodes', 'removed': removed})

    if not section.get('found'):
        OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'out_json': str(OUT_JSON), 'found': False}, ensure_ascii=False))
        browser.close()
        raise SystemExit

    excel_btn = page.locator('text=Excel快速编辑').first
    if excel_btn.count() > 0:
        try:
            page.evaluate(r'''() => {
              const el = Array.from(document.querySelectorAll('*')).find(x => ((x.innerText || x.textContent || '').replace(/\s+/g,'').trim()) === 'Excel快速编辑');
              if (el) el.dispatchEvent(new MouseEvent('click', {bubbles:true, cancelable:true}));
            }''')
            page.wait_for_timeout(2000)
            page.screenshot(path=str(OUT_DIR / 'dxm_regional_interactions_02_excel.png'), full_page=True)
            result['steps'].append({'step': 'after_excel_click', 'data': page.evaluate(JS_MODAL)})
            try:
                page.locator('.ant-modal-close, .ant-modal-wrap .anticon-close, button:has-text("关闭")').first.click(timeout=2000)
                page.wait_for_timeout(1000)
            except Exception:
                pass
        except Exception as exc:
            result['steps'].append({'step': 'after_excel_click', 'error': str(exc), 'data': page.evaluate(JS_MODAL)})

    method_locator = page.locator('text=直接报价').first
    if method_locator.count() > 0:
        try:
            method_locator.click(timeout=4000)
            page.wait_for_timeout(1500)
            page.screenshot(path=str(OUT_DIR / 'dxm_regional_interactions_03_method.png'), full_page=True)
            result['steps'].append({'step': 'after_method_click', 'data': page.evaluate(JS_MODAL)})
        except Exception as exc:
            result['steps'].append({'step': 'after_method_click', 'error': str(exc), 'data': page.evaluate(JS_MODAL)})

    batch_locator = page.locator('text=批量填充').first
    if batch_locator.count() > 0:
        try:
            batch_locator.click(timeout=4000)
            page.wait_for_timeout(1500)
            page.screenshot(path=str(OUT_DIR / 'dxm_regional_interactions_04_batch.png'), full_page=True)
            result['steps'].append({'step': 'after_batch_click', 'data': page.evaluate(JS_MODAL)})
        except Exception as exc:
            result['steps'].append({'step': 'after_batch_click', 'error': str(exc), 'data': page.evaluate(JS_MODAL)})

    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'out_json': str(OUT_JSON), 'steps': [x['step'] for x in result['steps']]}, ensure_ascii=False))
    browser.close()
