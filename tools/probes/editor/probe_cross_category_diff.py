import json
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

ROOT = Path('/root/.Hermes/workspace/dxm-auto-uikit')
COOKIE_FILE = ROOT / 'data' / 'sessions' / 'dianxiaomi_cookies.json'
OUT_JSON = ROOT / 'data' / 'sessions' / 'dianxiaomi_cross_category_diff.json'
OUT_DIR = ROOT / 'data' / 'screenshots'
OUT_DIR.mkdir(parents=True, exist_ok=True)
TARGET_URL = 'https://www.dianxiaomi.com/web/smt/edit?id=130658341226453206'
TARGETS = [
    '珠宝饰品及配件',
    '家居用品',
    '电脑和办公',
]


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
    return {title, labels: Array.from(new Set(labels))};
  });
  const categoryText = textOf(document.querySelector('.category-item .ant-select-selector, .category-item .ant-select, .category-list'));
  return {sections, categoryText};
}
'''


def close_overlays(page):
    try:
        page.evaluate("document.querySelectorAll('.bullet-layer,.comm-modal,.ant-modal-mask,#theNewestModalLabelFrame').forEach(el=>el.remove())")
        page.wait_for_timeout(300)
    except Exception:
        pass


def open_category_modal(page):
    page.locator('text=选择分类').first.click(timeout=5000)
    page.wait_for_timeout(1200)
    close_overlays(page)
    modal = page.locator('[role="dialog"], .ant-modal').filter(has_text='选择类目').first
    if modal.count() == 0:
        modal = page.locator('.ant-modal').first
    return modal


def choose_top_category(modal, text):
    item = modal.locator('.categories-item').filter(has_text=text).first
    if item.count() == 0:
        item = modal.locator(f'text={text}').first
    item.click(timeout=5000)


def confirm_modal(modal, page):
    try:
        modal.locator('button:has-text("选择")').first.click(timeout=3000)
    except PlaywrightTimeoutError:
        page.locator('button:has-text("选择")').last.click(timeout=3000)


def extract(page):
    return page.evaluate(JS_EXTRACT)


def section_map(data):
    return {s['title']: set(s['labels']) for s in data['sections']}


def diff_maps(base, other):
    out = []
    common_union = None
    for title in sorted(set(base) | set(other)):
        a = base.get(title, set())
        b = other.get(title, set())
        common = sorted(a & b)
        removed = sorted(a - b)
        added = sorted(b - a)
        out.append({'title': title, 'common': common, 'removed': removed, 'added': added})
        if common_union is None:
            common_union = set(common)
        else:
            common_union &= set(common)
    return out, sorted(common_union or [])

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
    ctx = browser.new_context(ignore_https_errors=True, viewport={'width': 1600, 'height': 2400})
    ctx.add_cookies(load_cookies())
    page = ctx.new_page()
    page.goto(TARGET_URL, wait_until='domcontentloaded', timeout=45000)
    page.wait_for_timeout(5000)
    close_overlays(page)
    baseline = extract(page)
    result = {
        'baseline': baseline,
        'attempts': [],
    }
    page.screenshot(path=str(OUT_DIR / 'dxm_cross_category_01_before.png'), full_page=True)

    base_map = section_map(baseline)
    global_section_common = None

    for target in TARGETS:
        attempt = {'target': target}
        try:
            modal = open_category_modal(page)
            choose_top_category(modal, target)
            page.wait_for_timeout(800)
            confirm_modal(modal, page)
            page.wait_for_timeout(2500)
            close_overlays(page)
            current = extract(page)
            attempt['after'] = current
            attempt['changed'] = baseline.get('categoryText') != current.get('categoryText')
            attempt['before_category'] = baseline.get('categoryText')
            attempt['after_category'] = current.get('categoryText')
            diffs, common = diff_maps(base_map, section_map(current))
            attempt['section_diff'] = diffs
            attempt['common_fields_all_sections'] = common
            result['attempts'].append(attempt)
            if global_section_common is None:
                global_section_common = set(common)
            else:
                global_section_common &= set(common)
            safe = target.replace('/', '_').replace(' ', '_')
            page.screenshot(path=str(OUT_DIR / f'dxm_cross_category_after_{safe}.png'), full_page=True)
            page.goto(TARGET_URL, wait_until='domcontentloaded', timeout=45000)
            page.wait_for_timeout(4000)
            close_overlays(page)
        except Exception as exc:
            attempt['error'] = str(exc)
            result['attempts'].append(attempt)
            page.goto(TARGET_URL, wait_until='domcontentloaded', timeout=45000)
            page.wait_for_timeout(4000)
            close_overlays(page)

    result['global_common_fields_all_sections'] = sorted(global_section_common or [])
    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'out_json': str(OUT_JSON), 'targets': TARGETS, 'attempts': len(result['attempts'])}, ensure_ascii=False))
    browser.close()
