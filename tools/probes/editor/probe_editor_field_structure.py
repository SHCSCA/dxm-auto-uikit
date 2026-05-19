import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path('/root/.Hermes/workspace/dxm-auto-uikit')
COOKIE_FILE = ROOT / 'data' / 'sessions' / 'dianxiaomi_cookies.json'
OUT_JSON = ROOT / 'data' / 'sessions' / 'dianxiaomi_editor_field_structure.json'
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
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const visible = (el) => {
    if (!el) return false;
    const st = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return st.display !== 'none' && st.visibility !== 'hidden' && parseFloat(st.opacity || '1') !== 0 && r.width > 3 && r.height > 3;
  };
  const textOf = (el) => clean(el.innerText || el.textContent || '');
  const inferControlTypes = (root) => {
    const types = new Set();
    if (!root) return [];
    if (root.querySelector('.ant-select, .ant-select-selector, .d-selector')) types.add('下拉框');
    if (root.querySelector('input[type="text"], input:not([type]), input.ant-input')) types.add('文本输入框');
    if (root.querySelector('input[type="number"]')) types.add('数字输入框');
    if (root.querySelector('textarea')) types.add('多行文本框');
    if (root.querySelector('.ant-radio-wrapper, input[type="radio"]')) types.add('单选框');
    if (root.querySelector('.ant-checkbox-wrapper, input[type="checkbox"]')) types.add('多选框');
    if (root.querySelector('[contenteditable="true"], .w-e-text-container, .ql-editor, .tox-edit-area, iframe')) types.add('富文本编辑器');
    if (root.querySelector('button, .ant-btn')) types.add('按钮');
    if (root.querySelector('a')) types.add('链接');
    if (root.querySelector('img, .upload-list-inline, .ant-upload, .draggable-item, .img-box, .cropper')) types.add('图片/上传区');
    if (root.querySelector('video')) types.add('视频区');
    if (root.querySelector('table, .vxe-table, .sku-table')) types.add('表格/SKU矩阵');
    if (types.size === 0) {
      const txt = textOf(root);
      if (txt.includes('请选择')) types.add('可能下拉框');
      if (txt.includes('上传') || txt.includes('选择图片') || txt.includes('添加视频')) types.add('可能上传区');
      if (txt.includes('同步') || txt.includes('添加') || txt.includes('生成') || txt.includes('查询')) types.add('可能按钮区');
    }
    return Array.from(types);
  };

  const sections = Array.from(document.querySelectorAll('.form-card')).filter(visible).map((card, idx) => {
    const header = card.querySelector('.form-card-header, .form-card-title, h4');
    const sectionTitle = textOf(header).split('(')[0].trim() || `未命名分区_${idx+1}`;
    const items = [];
    const rows = Array.from(card.querySelectorAll('.ant-form-item, .attr-gray-container, .edui-default, .wangEditor-container')).filter(visible);
    for (const row of rows) {
      let labelEl = row.querySelector('.ant-form-item-label label, .ant-form-item-label, label');
      let label = clean(labelEl ? labelEl.innerText || labelEl.textContent || '' : '');
      if (!label) {
        const rowText = textOf(row);
        const candidates = [
          '店铺名称','产品标题','产品分类','店小秘分类','来源URL','产品属性','自定义属性','产品分组','产品图片','营销图片','产品视频','计件单位','销售方式','零售价格','批发','货值','库存数量','扣减方式','重量(kg)','包装尺寸(cm)','是否原箱','物流属性','商品编码','发货期限','产品有效期','调价方式','调价区域','尺码表','PC端描述','无线端描述','运费模板','服务模板','海关监管属性','半托管服务','报价是否含关税','不含关税报价','含关税报价','欧盟责任人','土耳其责任人','品牌制造商','商机品关联','资质信息'
        ];
        label = candidates.find((x) => rowText.includes(x)) || '';
      }
      if (!label) continue;
      const control = row.querySelector('.ant-form-item-control, .ant-form-item-control-input-content, .ant-form-item-control-input') || row;
      const controlText = textOf(control).slice(0, 300);
      const types = inferControlTypes(control);
      const item = {
        label,
        required: !!row.querySelector('.ant-form-item-required'),
        control_types: types,
        control_text: controlText,
        raw_text: textOf(row).slice(0, 500),
        classes: clean(row.className || ''),
      };
      if (!items.find((x) => x.label === item.label && x.raw_text === item.raw_text)) {
        items.push(item);
      }
    }
    const sectionText = textOf(card);
    return {
      section_title: sectionTitle,
      section_text: sectionText.slice(0, 1200),
      item_count: items.length,
      items,
    };
  });

  const topButtons = Array.from(document.querySelectorAll('button, .ant-btn')).filter(visible).map((el) => textOf(el)).filter(Boolean);
  return {
    url: location.href,
    title: document.title,
    sections,
    top_buttons: Array.from(new Set(topButtons)),
    body_head: textOf(document.body).slice(0, 12000),
  };
}
'''

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
    ctx = browser.new_context(ignore_https_errors=True, viewport={'width': 1600, 'height': 2200})
    ctx.add_cookies(load_cookies())
    page = ctx.new_page()
    page.goto(TARGET_URL, wait_until='domcontentloaded', timeout=45000)
    page.wait_for_timeout(5000)
    page.screenshot(path=str(OUT_DIR / 'dxm_editor_field_structure.png'), full_page=True)
    data = page.evaluate(JS)
    OUT_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'out_json': str(OUT_JSON), 'sections': len(data.get('sections', [])), 'top_buttons': data.get('top_buttons', [])}, ensure_ascii=False))
    browser.close()
