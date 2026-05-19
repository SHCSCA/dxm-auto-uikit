import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path('/root/.Hermes/workspace/dxm-auto-uikit')
COOKIE_FILE = ROOT / 'data' / 'sessions' / 'dianxiaomi_cookies.json'
OUT_JSON = ROOT / 'data' / 'sessions' / 'dianxiaomi_regional_pricing_probe.json'
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


JS = r'''
() => {
  const clean = (s) => String(s || '').replace(/\s+/g, ' ').trim();
  const visible = (el) => {
    if (!el) return false;
    const st = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return st.display !== 'none' && st.visibility !== 'hidden' && parseFloat(st.opacity || '1') !== 0 && r.width > 3 && r.height > 3;
  };
  const txt = (el) => clean(el.innerText || el.textContent || '');
  const inferTypes = (root) => {
    const types = new Set();
    if (!root) return [];
    if (root.querySelector('.ant-select, .ant-select-selector, .d-selector')) types.add('下拉框');
    if (root.querySelector('input[type="text"], input:not([type]), input.ant-input')) types.add('文本输入框');
    if (root.querySelector('input[type="number"]')) types.add('数字输入框');
    if (root.querySelector('textarea')) types.add('多行文本框');
    if (root.querySelector('.ant-radio-wrapper, input[type="radio"]')) types.add('单选框');
    if (root.querySelector('.ant-checkbox-wrapper, input[type="checkbox"]')) types.add('多选框');
    if (root.querySelector('button, .ant-btn')) types.add('按钮');
    if (root.querySelector('table, .vxe-table')) types.add('表格');
    if (types.size === 0) {
      const body = txt(root);
      if (body.includes('请选择')) types.add('可能下拉框');
      if (body.includes('批量') || body.includes('Excel快速编辑')) types.add('可能按钮区');
    }
    return Array.from(types);
  };

  const section = Array.from(document.querySelectorAll('.form-card')).find(card => visible(card) && txt(card).includes('区域调价信息'));
  if (!section) {
    return {found: false, reason: 'regional_pricing_section_not_found'};
  }

  const rows = Array.from(section.querySelectorAll('.ant-form-item, .price-area-item, .price-area-item-box, .editable-row, .vxe-body--row, tr')).filter(visible);
  const rowSamples = rows.slice(0, 20).map((row, idx) => ({
    index: idx,
    text: txt(row).slice(0, 300),
    classes: clean(row.className || ''),
    control_types: inferTypes(row),
  }));

  const countryNodes = Array.from(section.querySelectorAll('*')).filter(el => visible(el)).map(el => ({
    text: txt(el),
    cls: clean(el.className || ''),
    tag: el.tagName,
  })).filter(x => x.text && x.text.length < 40 && ['俄罗斯','美国','英国','法国','德国','西班牙','巴西','韩国','日本','澳大利亚','加拿大','土耳其','墨西哥'].includes(x.text));

  const actionButtons = Array.from(section.querySelectorAll('button, .ant-btn, a, span, div')).filter(visible).map(el => ({
    text: txt(el),
    cls: clean(el.className || ''),
    tag: el.tagName,
  })).filter(x => x.text && ['批量填充','Excel快速编辑','收起','展开'].some(k => x.text.includes(k))).slice(0, 30);

  const keywords = ['调价方式','调价区域','批量填充','Excel快速编辑'];
  const fieldBlocks = Array.from(section.querySelectorAll('*')).filter(visible).map(el => ({
    text: txt(el),
    cls: clean(el.className || ''),
    tag: el.tagName,
    control_types: inferTypes(el),
  })).filter(x => x.text && keywords.some(k => x.text.includes(k))).slice(0, 80);

  const labels = Array.from(section.querySelectorAll('label, .ant-form-item-label, .ant-form-item-label label')).filter(visible).map(el => txt(el)).filter(Boolean);
  const inputs = Array.from(section.querySelectorAll('input, textarea, .ant-select, .ant-select-selector, .ant-radio-wrapper, .ant-checkbox-wrapper')).filter(visible).map(el => ({
    tag: el.tagName,
    type: el.getAttribute('type') || '',
    cls: clean(el.className || ''),
    text: txt(el).slice(0, 100),
    placeholder: el.getAttribute('placeholder') || '',
    value: el.value || '',
  })).slice(0, 120);

  return {
    found: true,
    section_text: txt(section).slice(0, 8000),
    labels,
    row_count: rows.length,
    row_samples: rowSamples,
    country_node_count: countryNodes.length,
    country_nodes: countryNodes.slice(0, 80),
    action_buttons: actionButtons,
    field_blocks: fieldBlocks,
    inputs,
  };
}
'''

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
    ctx = browser.new_context(ignore_https_errors=True, viewport={'width': 1600, 'height': 2600})
    ctx.add_cookies(load_cookies())
    page = ctx.new_page()
    page.goto(TARGET_URL, wait_until='domcontentloaded', timeout=45000)
    page.wait_for_timeout(5000)
    page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.55)")
    page.wait_for_timeout(1200)
    page.screenshot(path=str(OUT_DIR / 'dxm_regional_pricing_probe.png'), full_page=True)
    data = page.evaluate(JS)
    OUT_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'out_json': str(OUT_JSON), 'found': data.get('found'), 'row_count': data.get('row_count'), 'labels': data.get('labels', [])[:20]}, ensure_ascii=False))
    browser.close()
