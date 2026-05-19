import json
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

ROOT = Path('/root/.Hermes/workspace/dxm-auto-uikit')
COOKIE_FILE = ROOT / 'data' / 'sessions' / 'dianxiaomi_cookies.json'
OUT_JSON = ROOT / 'data' / 'sessions' / 'dianxiaomi_cross_category_leaf_v2.json'
OUT_DIR = ROOT / 'data' / 'screenshots'
OUT_DIR.mkdir(parents=True, exist_ok=True)
TARGET_URL = 'https://www.dianxiaomi.com/web/smt/edit?id=130658341226453206'
TARGETS = [
    {'l1': '珠宝饰品及配件'},
    {'l1': '家居用品'},
    {'l1': '电脑和办公'},
]


def load_cookies():
    raw = json.loads(COOKIE_FILE.read_text(encoding='utf-8'))
    out = []
    for c in raw:
        item = {
            'name': c['name'], 'value': c['value'], 'domain': c['domain'], 'path': c.get('path', '/'),
            'httpOnly': c.get('httpOnly', False), 'secure': c.get('secure', False),
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
  const items = Array.from(modal.querySelectorAll('.categories-item')).filter(visible).map(el => {
    const r = el.getBoundingClientRect();
    return {text:textOf(el), cls:clean(el.className||''), x:r.x, active:clean(el.className||'').includes('active')};
  }).filter(x => x.text);
  const buckets = {};
  for (const item of items) {
    const key = Math.round(item.x / 20) * 20;
    if (!buckets[key]) buckets[key] = [];
    buckets[key].push(item);
  }
  const columns = Object.keys(buckets).map(k => ({
    approx_x: Number(k),
    items: buckets[k].slice(0, 60),
    active_items: buckets[k].filter(i => i.active).map(i => i.text),
  })).sort((a,b)=>a.approx_x-b.approx_x);
  return {found:true, columns};
}
'''


def close_overlays(page):
    try:
        page.evaluate("document.querySelectorAll('.bullet-layer,.comm-modal,.ant-modal-mask,#theNewestModalLabelFrame').forEach(el=>el.remove())")
        page.wait_for_timeout(200)
    except Exception:
        pass


def open_modal(page):
    try:
        page.locator('text=选择分类').first.click(timeout=4000)
    except Exception:
        page.evaluate(r'''() => {
          const btn = Array.from(document.querySelectorAll('button')).find(el => ((el.innerText||el.textContent||'').replace(/\s+/g,'').trim()) === '选择分类');
          if (btn) btn.dispatchEvent(new MouseEvent('click', {bubbles:true, cancelable:true}));
        }''')
    page.wait_for_timeout(1200)
    return page.locator('[role="dialog"], .ant-modal').filter(has_text='选择类目').first


def extract(page):
    return page.evaluate(JS_EXTRACT)


def section_map(data):
    return {s['title']: set(s['labels']) for s in data['sections']}


def diff_maps(base, other):
    out = []
    for title in sorted(set(base) | set(other)):
        a = base.get(title, set())
        b = other.get(title, set())
        out.append({'title': title, 'common': sorted(a & b), 'removed': sorted(a - b), 'added': sorted(b - a)})
    return out


def click_item_in_column(page, text, col_idx):
    cols = page.evaluate(JS_COLUMNS)
    if not cols.get('found'):
        raise RuntimeError('category modal not found')
    columns = cols['columns']
    if col_idx >= len(columns):
        raise RuntimeError(f'column {col_idx} missing; have {len(columns)} columns')
    column = columns[col_idx]
    # exact text match first
    choices = [i for i in column['items'] if i['text'] == text]
    if not choices:
        choices = [i for i in column['items'] if text in i['text']]
    if not choices:
        raise RuntimeError(f'target {text} not found in column {col_idx}; sample={[i["text"] for i in column["items"][:15]]}')
    page.evaluate(r'''(payload) => {
      const clean = (s) => String(s || '').replace(/\s+/g, ' ').trim();
      const visible = (el) => {
        const st = getComputedStyle(el); const r = el.getBoundingClientRect();
        return st.display !== 'none' && st.visibility !== 'hidden' && parseFloat(st.opacity || '1') !== 0 && r.width > 10 && r.height > 10;
      };
      const items = Array.from(document.querySelectorAll('.categories-item')).filter(visible).map(el => {
        const r = el.getBoundingClientRect();
        return {el, text:clean(el.innerText||el.textContent||''), key:Math.round(r.x/20)*20};
      });
      const target = items.find(i => i.key === payload.key && i.text === payload.text) || items.find(i => i.key === payload.key && i.text.includes(payload.text));
      if (target) target.el.dispatchEvent(new MouseEvent('click', {bubbles:true, cancelable:true}));
    }''', {'key': column['approx_x'], 'text': choices[0]['text']})
    page.wait_for_timeout(1200)
    return page.evaluate(JS_COLUMNS)


def choose_leaf(page, l1):
    modal = open_modal(page)
    close_overlays(page)
    states = []
    states.append({'step': 'opened', 'columns': page.evaluate(JS_COLUMNS)})
    state1 = click_item_in_column(page, l1, 0)
    states.append({'step': f'clicked_l1_{l1}', 'columns': state1})
    # choose first non-active item from column 1 after l1 click
    cols1 = state1['columns']
    if len(cols1) < 2:
        raise RuntimeError(f'after clicking {l1}, no second column')
    col1_items = cols1[1]['items']
    l2 = next((i['text'] for i in col1_items if not i['active']), None)
    if not l2:
        l2 = col1_items[0]['text']
    state2 = click_item_in_column(page, l2, 1)
    states.append({'step': f'clicked_l2_{l2}', 'columns': state2})
    cols2 = state2['columns']
    if len(cols2) < 3:
        raise RuntimeError(f'after clicking {l2}, no third column')
    col2_items = cols2[2]['items']
    l3 = next((i['text'] for i in col2_items if not i['active']), None)
    if not l3:
        l3 = col2_items[0]['text']
    state3 = click_item_in_column(page, l3, 2)
    states.append({'step': f'clicked_l3_{l3}', 'columns': state3})
    try:
        modal.locator('button:has-text("选择")').first.click(timeout=3000)
    except PlaywrightTimeoutError:
        page.locator('button:has-text("选择")').last.click(timeout=3000)
    page.wait_for_timeout(2500)
    close_overlays(page)
    return {'chosen_path': [l1, l2, l3], 'states': states}

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

    for target in TARGETS:
        attempt = {'target': target}
        try:
            pick = choose_leaf(page, target['l1'])
            after = extract(page)
            attempt['pick'] = pick
            attempt['after'] = after
            attempt['changed'] = baseline.get('categoryText') != after.get('categoryText')
            attempt['before_category'] = baseline.get('categoryText')
            attempt['after_category'] = after.get('categoryText')
            attempt['section_diff'] = diff_maps(base_map, section_map(after))
            result['attempts'].append(attempt)
            safe = target['l1'].replace('/', '_')
            page.screenshot(path=str(OUT_DIR / f'dxm_cross_leaf_v2_after_{safe}.png'), full_page=True)
        except Exception as exc:
            attempt['error'] = str(exc)
            result['attempts'].append(attempt)
        page.goto(TARGET_URL, wait_until='domcontentloaded', timeout=45000)
        page.wait_for_timeout(4000)
        close_overlays(page)

    successful = [a for a in result['attempts'] if a.get('changed')]
    global_stable = {}
    if successful:
        titles = set().union(*[set(s['title'] for s in a['section_diff']) for a in successful])
        for title in titles:
            commons = [set(next((d['common'] for d in a['section_diff'] if d['title'] == title), [])) for a in successful]
            if commons:
                global_stable[title] = sorted(set.intersection(*commons) if len(commons) > 1 else commons[0])
    result['global_stable_by_section'] = global_stable
    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'out_json': str(OUT_JSON), 'successful_changed': len(successful)}, ensure_ascii=False))
    browser.close()
