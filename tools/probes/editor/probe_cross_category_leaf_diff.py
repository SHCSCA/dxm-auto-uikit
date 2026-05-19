import json
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

ROOT = Path('/root/.Hermes/workspace/dxm-auto-uikit')
COOKIE_FILE = ROOT / 'data' / 'sessions' / 'dianxiaomi_cookies.json'
OUT_JSON = ROOT / 'data' / 'sessions' / 'dianxiaomi_cross_category_leaf_diff.json'
OUT_DIR = ROOT / 'data' / 'screenshots'
OUT_DIR.mkdir(parents=True, exist_ok=True)
TARGET_URL = 'https://www.dianxiaomi.com/web/smt/edit?id=130658341226453206'
TARGET_PATHS = [
    ['珠宝饰品及配件'],
    ['家居用品'],
    ['电脑和办公'],
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
  const modal = Array.from(document.querySelectorAll('[role="dialog"], .ant-modal')).find(visible);
  if (!modal) return {found:false};
  const selectedPath = Array.from(modal.querySelectorAll('.selected-category, .path, .categories-path, .selected-path, .d-breadcrumb, .category-path')).map(textOf).filter(Boolean);
  const items = Array.from(modal.querySelectorAll('.categories-item')).filter(visible).map(el => ({
    text: textOf(el),
    cls: clean(el.className || ''),
  })).filter(x => x.text && x.text.length <= 80);
  const active = items.filter(x => x.cls.includes('active'));
  return {found:true, selectedPath, active, items: items.slice(0, 300), modalText: textOf(modal).slice(0, 8000)};
}
'''


def close_overlays(page):
    try:
        page.evaluate("document.querySelectorAll('.bullet-layer,.comm-modal,.ant-modal-mask,#theNewestModalLabelFrame').forEach(el=>el.remove())")
        page.wait_for_timeout(300)
    except Exception:
        pass


def extract(page):
    return page.evaluate(JS_EXTRACT)


def section_map(data):
    return {s['title']: set(s['labels']) for s in data['sections']}


def diff_maps(base, other):
    out = []
    stable = {}
    for title in sorted(set(base) | set(other)):
        a = base.get(title, set())
        b = other.get(title, set())
        common = sorted(a & b)
        removed = sorted(a - b)
        added = sorted(b - a)
        out.append({'title': title, 'common': common, 'removed': removed, 'added': added})
        stable[title] = common
    return out, stable


def open_modal(page):
    page.locator('text=选择分类').first.click(timeout=5000)
    page.wait_for_timeout(1200)
    close_overlays(page)
    return page.locator('[role="dialog"], .ant-modal').filter(has_text='选择类目').first


def choose_first_leaf(page, path_parts):
    modal = open_modal(page)
    chosen = []
    snapshots = []
    for idx, part in enumerate(path_parts):
        target = modal.locator('.categories-item').filter(has_text=part).first
        if target.count() == 0:
            target = modal.locator(f'text={part}').first
        target.click(timeout=5000)
        page.wait_for_timeout(1200)
        state = page.evaluate(JS_DIALOG)
        snapshots.append({'after_click': part, 'state': state})
        chosen.append(part)

    state = page.evaluate(JS_DIALOG)
    active = [x['text'] for x in state.get('active', [])]
    chosen_leaf = None
    # choose deepest active item not already in path
    for text in reversed(active):
        if text not in chosen and text not in {'选择类目', '搜索'}:
            chosen_leaf = text
            break
    if not chosen_leaf:
        # fallback: choose last active if any
        if active:
            chosen_leaf = active[-1]
    if not chosen_leaf:
        # fallback: choose a non-active visible item after path click
        for item in state.get('items', []):
            if item['text'] not in chosen and 'active' not in item['cls']:
                chosen_leaf = item['text']
                break
    if chosen_leaf:
        target = modal.locator('.categories-item').filter(has_text=chosen_leaf).first
        if target.count() == 0:
            target = modal.locator(f'text={chosen_leaf}').first
        target.click(timeout=5000)
        page.wait_for_timeout(1000)
        chosen.append(chosen_leaf)
        snapshots.append({'after_click': chosen_leaf, 'state': page.evaluate(JS_DIALOG)})

    try:
        modal.locator('button:has-text("选择")').first.click(timeout=3000)
    except PlaywrightTimeoutError:
        page.locator('button:has-text("选择")').last.click(timeout=3000)
    page.wait_for_timeout(2500)
    close_overlays(page)
    return {'chosen_path': chosen, 'snapshots': snapshots}

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
    ctx = browser.new_context(ignore_https_errors=True, viewport={'width': 1600, 'height': 2400})
    ctx.add_cookies(load_cookies())
    page = ctx.new_page()
    page.goto(TARGET_URL, wait_until='domcontentloaded', timeout=45000)
    page.wait_for_timeout(5000)
    close_overlays(page)
    baseline = extract(page)
    base_map = section_map(baseline)
    result = {'baseline': baseline, 'attempts': []}

    for path in TARGET_PATHS:
        attempt = {'target_path': path}
        try:
            pick = choose_first_leaf(page, path)
            current = extract(page)
            attempt['pick'] = pick
            attempt['after'] = current
            attempt['changed'] = baseline.get('categoryText') != current.get('categoryText')
            attempt['before_category'] = baseline.get('categoryText')
            attempt['after_category'] = current.get('categoryText')
            diffs, stable = diff_maps(base_map, section_map(current))
            attempt['section_diff'] = diffs
            attempt['stable_fields_by_section'] = stable
            result['attempts'].append(attempt)
            safe = '_'.join(path)
            page.screenshot(path=str(OUT_DIR / f'dxm_cross_leaf_after_{safe}.png'), full_page=True)
        except Exception as exc:
            attempt['error'] = str(exc)
            result['attempts'].append(attempt)
        page.goto(TARGET_URL, wait_until='domcontentloaded', timeout=45000)
        page.wait_for_timeout(4000)
        close_overlays(page)

    # intersect stable skeleton across successful changed attempts
    successful = [a for a in result['attempts'] if a.get('changed')]
    global_stable = {}
    if successful:
        section_titles = set().union(*[set(a['stable_fields_by_section'].keys()) for a in successful])
        for title in section_titles:
            sets = [set(a['stable_fields_by_section'].get(title, [])) for a in successful]
            if sets:
                common = set.intersection(*sets) if len(sets) > 1 else sets[0]
                global_stable[title] = sorted(common)
    result['global_stable_by_section'] = global_stable
    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'out_json': str(OUT_JSON), 'successful_changed': len(successful)}, ensure_ascii=False))
    browser.close()
