import json
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

ROOT = Path('/root/.Hermes/workspace/dxm-auto-uikit')
COOKIE_FILE = ROOT / 'data' / 'sessions' / 'dianxiaomi_cookies.json'
OUT_JSON = ROOT / 'data' / 'sessions' / 'dianxiaomi_category_diff_result.json'
OUT_DIR = ROOT / 'data' / 'screenshots'
OUT_DIR.mkdir(parents=True, exist_ok=True)
TARGET_URL = 'https://www.dianxiaomi.com/web/smt/edit?id=130658341226453206'
TARGETS = ['手办模型工具/耗材', '游戏周边玩具', '动物/恐龙手办']


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


def extract(page):
    return page.evaluate(JS_EXTRACT)


def compute_diff(before, after):
    before_map = {s['title']: set(s['labels']) for s in before['sections']}
    after_map = {s['title']: set(s['labels']) for s in after['sections']}
    all_titles = sorted(set(before_map) | set(after_map))
    section_diff = []
    common_all = None
    for title in all_titles:
        a = before_map.get(title, set())
        b = after_map.get(title, set())
        common = sorted(a & b)
        removed = sorted(a - b)
        added = sorted(b - a)
        section_diff.append({'title': title, 'common': common, 'removed': removed, 'added': added})
        if common_all is None:
            common_all = set(common)
        else:
            common_all &= set(common)
    return section_diff, sorted(common_all or [])

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
    ctx = browser.new_context(ignore_https_errors=True, viewport={'width': 1600, 'height': 2400})
    ctx.add_cookies(load_cookies())
    page = ctx.new_page()
    result = {'attempts': []}
    page.goto(TARGET_URL, wait_until='domcontentloaded', timeout=45000)
    page.wait_for_timeout(5000)
    close_overlays(page)
    before = extract(page)
    result['baseline'] = before
    page.screenshot(path=str(OUT_DIR / 'dxm_category_diff_01_before.png'), full_page=True)

    changed = False
    for target in TARGETS:
        attempt = {'target': target}
        try:
            page.locator('text=选择分类').first.click(timeout=5000)
            page.wait_for_timeout(1200)
            close_overlays(page)
            modal = page.locator('[role="dialog"], .ant-modal').filter(has_text='选择类目').first
            if modal.count() == 0:
                modal = page.locator('.ant-modal').first
            target_item = modal.locator('.categories-item').filter(has_text=target).first
            if target_item.count() == 0:
                target_item = modal.locator(f'text={target}').first
            target_item.click(timeout=5000)
            page.wait_for_timeout(800)
            try:
                modal.locator('button:has-text("选择")').first.click(timeout=3000)
            except PlaywrightTimeoutError:
                try:
                    page.locator('button:has-text("选择")').last.click(timeout=3000)
                except Exception:
                    pass
            page.wait_for_timeout(2500)
            page.screenshot(path=str(OUT_DIR / f'dxm_category_diff_after_{target}.png'), full_page=True)
            after = extract(page)
            attempt['after'] = after
            attempt['category_changed'] = before.get('categoryText') != after.get('categoryText')
            attempt['before_category'] = before.get('categoryText')
            attempt['after_category'] = after.get('categoryText')
            section_diff, common_all = compute_diff(before, after)
            attempt['section_diff'] = section_diff
            attempt['common_fields_all_sections'] = common_all
            result['attempts'].append(attempt)
            if attempt['category_changed']:
                result['success'] = attempt
                changed = True
                break
        except Exception as exc:
            attempt['error'] = str(exc)
            result['attempts'].append(attempt)
            try:
                page.keyboard.press('Escape')
                page.wait_for_timeout(500)
            except Exception:
                pass
            close_overlays(page)
            page.goto(TARGET_URL, wait_until='domcontentloaded', timeout=45000)
            page.wait_for_timeout(4000)
            close_overlays(page)
            before = extract(page)
    result['changed'] = changed
    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'out_json': str(OUT_JSON), 'changed': changed, 'attempt_targets': [a['target'] for a in result['attempts']]}, ensure_ascii=False))
    browser.close()
