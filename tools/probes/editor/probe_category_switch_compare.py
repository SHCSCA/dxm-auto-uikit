import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path('/root/.Hermes/workspace/dxm-auto-uikit')
COOKIE_FILE = ROOT / 'data' / 'sessions' / 'dianxiaomi_cookies.json'
OUT_JSON = ROOT / 'data' / 'sessions' / 'dianxiaomi_category_switch_probe.json'
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


JS_EXTRACT = r'''
() => {
  const clean = (s) => String(s || '').replace(/\s+/g, ' ').trim();
  const visible = (el) => {
    if (!el) return false;
    const st = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return st.display !== 'none' && st.visibility !== 'hidden' && parseFloat(st.opacity || '1') !== 0 && r.width > 3 && r.height > 3;
  };
  const textOf = (el) => clean(el.innerText || el.textContent || '');
  const sections = Array.from(document.querySelectorAll('.form-card')).filter(visible).map(card => {
    const title = textOf(card.querySelector('.form-card-title, .form-card-header, h4')).split('(')[0].trim();
    const labels = Array.from(card.querySelectorAll('.ant-form-item-label label, .ant-form-item-label, label')).filter(visible).map(x => textOf(x)).filter(Boolean);
    return {title, labels};
  });
  const all_labels = sections.flatMap(s => s.labels);
  return {sections, all_labels};
}
'''

JS_DIALOG = r'''
() => {
  const clean = (s) => String(s || '').replace(/\s+/g, ' ').trim();
  const visible = (el) => {
    if (!el) return false;
    const st = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return st.display !== 'none' && st.visibility !== 'hidden' && parseFloat(st.opacity || '1') !== 0 && r.width > 3 && r.height > 3;
  };
  const textOf = (el) => clean(el.innerText || el.textContent || '');
  const dialog = Array.from(document.querySelectorAll('[role="dialog"], .ant-modal, .ant-modal-wrap, .category-modal, .select-category-modal')).find(visible);
  if (!dialog) return {found:false};
  const controls = Array.from(dialog.querySelectorAll('button, input, textarea, a, span, div, li, label')).filter(visible).map(el => ({
    tag: el.tagName,
    cls: clean(el.className || ''),
    text: textOf(el).slice(0, 120),
    placeholder: el.getAttribute('placeholder') || '',
    type: el.getAttribute('type') || '',
  }));
  const candidates = controls.filter(x => x.text && x.text.length >= 2 && x.text.length <= 60 && !['选择分类','确定','取消','关闭','搜索','重置','保存'].includes(x.text)).slice(0, 200);
  return {
    found:true,
    dialog_text: textOf(dialog).slice(0, 5000),
    controls: controls.slice(0, 300),
    candidates,
  };
}
'''

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
    ctx = browser.new_context(ignore_https_errors=True, viewport={'width': 1600, 'height': 2200})
    ctx.add_cookies(load_cookies())
    page = ctx.new_page()
    result = {}
    page.goto(TARGET_URL, wait_until='domcontentloaded', timeout=45000)
    page.wait_for_timeout(5000)
    try:
        page.evaluate("document.querySelectorAll('.bullet-layer,.comm-modal,.ant-modal-wrap,.ant-modal-mask,#theNewestModalLabelFrame').forEach(el=>el.remove())")
        page.wait_for_timeout(500)
    except Exception:
        pass
    page.screenshot(path=str(OUT_DIR / 'dxm_category_switch_01_before.png'), full_page=True)
    result['baseline'] = page.evaluate(JS_EXTRACT)

    page.locator('text=选择分类').first.click(timeout=5000)
    page.wait_for_timeout(1500)
    page.screenshot(path=str(OUT_DIR / 'dxm_category_switch_02_dialog.png'), full_page=True)
    result['dialog'] = page.evaluate(JS_DIALOG)

    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'out_json': str(OUT_JSON), 'dialog_found': result['dialog'].get('found'), 'section_count': len(result['baseline'].get('sections', []))}, ensure_ascii=False))
    browser.close()
