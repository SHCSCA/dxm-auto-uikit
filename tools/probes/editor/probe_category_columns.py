import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path('/root/.Hermes/workspace/dxm-auto-uikit')
COOKIE_FILE = ROOT / 'data' / 'sessions' / 'dianxiaomi_cookies.json'
OUT_JSON = ROOT / 'data' / 'sessions' / 'dianxiaomi_category_columns_probe.json'
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

JS_COLUMNS = r'''
() => {
  const clean = (s) => String(s || '').replace(/\s+/g, ' ').trim();
  const visible = (el) => {
    if (!el) return false;
    const st = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return st.display !== 'none' && st.visibility !== 'hidden' && parseFloat(st.opacity || '1') !== 0 && r.width > 10 && r.height > 10;
  };
  const textOf = (el) => clean(el.innerText || el.textContent || '');
  const modal = Array.from(document.querySelectorAll('[role="dialog"], .ant-modal')).find(visible);
  if (!modal) return {found:false};

  const searchInputs = Array.from(modal.querySelectorAll('input')).filter(visible).map(el => ({
    placeholder: el.getAttribute('placeholder') || '',
    value: el.value || '',
    cls: clean(el.className || ''),
  }));

  const allItems = Array.from(modal.querySelectorAll('.categories-item')).filter(visible).map(el => {
    const r = el.getBoundingClientRect();
    return {
      text: textOf(el),
      cls: clean(el.className || ''),
      x: r.x,
      y: r.y,
      w: r.width,
      h: r.height,
      active: clean(el.className || '').includes('active'),
    };
  }).filter(x => x.text);

  const xs = Array.from(new Set(allItems.map(i => Math.round(i.x / 20) * 20))).sort((a,b)=>a-b);
  const columns = xs.map((x, idx) => {
    const items = allItems.filter(i => Math.abs((Math.round(i.x / 20) * 20) - x) <= 20);
    return {
      column_index: idx,
      approx_x: x,
      item_count: items.length,
      active_items: items.filter(i => i.active).map(i => i.text),
      sample_items: items.slice(0, 40).map(i => ({text:i.text, active:i.active, cls:i.cls})),
    };
  }).filter(col => col.item_count > 0);

  const footerButtons = Array.from(modal.querySelectorAll('button')).filter(visible).map(el => ({
    text: textOf(el),
    cls: clean(el.className || ''),
  })).filter(x => x.text);

  return {
    found:true,
    modal_text: textOf(modal).slice(0, 8000),
    search_inputs: searchInputs,
    total_items: allItems.length,
    columns,
    footer_buttons: footerButtons,
  };
}
'''

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
    ctx = browser.new_context(ignore_https_errors=True, viewport={'width': 1600, 'height': 2400})
    ctx.add_cookies(load_cookies())
    page = ctx.new_page()
    result = {'steps': []}
    page.goto(TARGET_URL, wait_until='domcontentloaded', timeout=45000)
    page.wait_for_timeout(5000)
    try:
        page.evaluate("document.querySelectorAll('.bullet-layer,.comm-modal,.ant-modal-mask,#theNewestModalLabelFrame').forEach(el=>el.remove())")
        page.wait_for_timeout(300)
    except Exception:
        pass

    try:
        page.locator('text=选择分类').first.click(timeout=5000)
    except Exception:
        page.evaluate(r'''() => {
          const btn = Array.from(document.querySelectorAll('button')).find(el => ((el.innerText || el.textContent || '').replace(/\s+/g,'').trim()) === '选择分类');
          if (btn) btn.dispatchEvent(new MouseEvent('click', {bubbles:true, cancelable:true}));
        }''')
    page.wait_for_timeout(1200)
    page.screenshot(path=str(OUT_DIR / 'dxm_category_columns_01_open.png'), full_page=True)
    result['steps'].append({'step': 'initial', 'data': page.evaluate(JS_COLUMNS)})

    for target in ['珠宝饰品及配件', '家居用品', '电脑和办公']:
        try:
            page.locator('.categories-item').filter(has_text=target).first.click(timeout=5000)
            page.wait_for_timeout(1200)
            page.screenshot(path=str(OUT_DIR / f'dxm_category_columns_after_{target}.png'), full_page=True)
            result['steps'].append({'step': f'after_click_{target}', 'data': page.evaluate(JS_COLUMNS)})
        except Exception as exc:
            result['steps'].append({'step': f'after_click_{target}', 'error': str(exc), 'data': page.evaluate(JS_COLUMNS)})

    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'out_json': str(OUT_JSON), 'steps': [s['step'] for s in result['steps']]}, ensure_ascii=False))
    browser.close()
