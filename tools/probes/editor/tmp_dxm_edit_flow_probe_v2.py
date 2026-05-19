import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path('/root/.Hermes/workspace/dxm-auto-uikit')
COOKIE_FILE = ROOT / 'data' / 'sessions' / 'dianxiaomi_cookies.json'
OUT_JSON = ROOT / 'data' / 'sessions' / 'dianxiaomi_edit_flow_probe_v2.json'
OUT_DIR = ROOT / 'data' / 'screenshots'
OUT_DIR.mkdir(parents=True, exist_ok=True)
TARGET_TEXT = '崩坏3钥匙扣爱莉希雅'


def load_cookies():
    raw = json.loads(COOKIE_FILE.read_text(encoding='utf-8'))
    out = []
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
        out.append(item)
    return out

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
    ctx = browser.new_context(ignore_https_errors=True, viewport={'width': 1600, 'height': 1400})
    ctx.add_cookies(load_cookies())
    page = ctx.new_page()
    result = {'steps': []}

    page.goto('https://www.dianxiaomi.com/web/smt/smtProductList/draft', wait_until='domcontentloaded', timeout=45000)
    page.wait_for_timeout(3500)
    page.evaluate(r'''({target, frag}) => {
      const all = Array.from(document.querySelectorAll('*'));
      const store = all.find(el => (el.innerText||el.textContent||'').replace(/\s+/g,'').trim() === target.replace(/\s+/g,''));
      if (store) store.dispatchEvent(new MouseEvent('click', {bubbles:true}));
      const input = Array.from(document.querySelectorAll('input.ant-input,input')).find(el => {
        const r = el.getBoundingClientRect();
        return r.width > 220 && r.height > 20 && !el.disabled;
      });
      if (input) {
        input.value = frag;
        input.dispatchEvent(new Event('input', {bubbles:true}));
        input.dispatchEvent(new Event('change', {bubbles:true}));
      }
      const btn = all.find(el => (el.innerText||el.textContent||'').replace(/\s+/g,'').trim() === '搜索');
      if (btn) btn.dispatchEvent(new MouseEvent('click', {bubbles:true}));
    }''', {'target': 'Dang Kang', 'frag': TARGET_TEXT})
    page.wait_for_timeout(2200)
    page.screenshot(path=str(OUT_DIR / 'dxm_edit_flow_v2_01_search.png'), full_page=True)

    info = page.evaluate(r'''(frag) => {
      const rows = Array.from(document.querySelectorAll('tr.vxe-body--row, tr'));
      const picked = rows.map((tr, idx) => ({idx, text:(tr.innerText||tr.textContent||'').replace(/\s+/g,' ').trim()})).find(x => x.text.includes(frag));
      if (!picked) return {ok:false};
      const row = rows[picked.idx];
      const editA = Array.from(row.querySelectorAll('a')).find(el => (el.innerText||el.textContent||'').replace(/\s+/g,'').trim()==='编辑');
      const editDiv = Array.from(row.querySelectorAll('*')).find(el => (el.innerText||el.textContent||'').replace(/\s+/g,'').trim()==='编辑');
      const box = (el) => {
        if (!el) return null;
        const r = el.getBoundingClientRect();
        return {tag:el.tagName, cls:String(el.className||''), html:el.outerHTML.slice(0,200), rect:{x:r.x,y:r.y,w:r.width,h:r.height}};
      };
      return {ok:true, rowText:picked.text.slice(0,500), editA:box(editA), editDiv:box(editDiv)};
    }''', TARGET_TEXT)
    result['steps'].append({'step':'targets','data':info})
    target = info.get('editA') or info.get('editDiv')
    if not target:
        OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False, indent=2))
        browser.close(); raise SystemExit

    # click exact anchor/element center
    page.mouse.click(target['rect']['x'] + target['rect']['w']/2, target['rect']['y'] + target['rect']['h']/2)
    page.wait_for_timeout(2500)
    page.screenshot(path=str(OUT_DIR / 'dxm_edit_flow_v2_02_after_click.png'), full_page=True)
    result['steps'].append({'step':'after_click','url':page.url,'title':page.title(),'body':page.locator('body').inner_text()[:3000]})

    # if category dialog exists, skip it
    skip = page.evaluate(r'''() => {
      const dialog = Array.from(document.querySelectorAll('[role="dialog"], .ant-modal-wrap, .ant-modal')).find(el => {
        const t = (el.innerText||el.textContent||'').replace(/\s+/g,' ').trim();
        return t.includes('分类') || t.includes('类目') || t.includes('编辑分类');
      });
      if (!dialog) return {found:false};
      const btn = Array.from(dialog.querySelectorAll('button,span,a,div')).find(el => ['跳过','取消','暂不选择'].includes((el.innerText||el.textContent||'').replace(/\s+/g,'')));
      if (!btn) return {found:true, clicked:false, text:(dialog.innerText||dialog.textContent||'').replace(/\s+/g,' ').trim().slice(0,800)};
      btn.dispatchEvent(new MouseEvent('click', {bubbles:true}));
      return {found:true, clicked:true, btn:(btn.innerText||btn.textContent||'').replace(/\s+/g,''), text:(dialog.innerText||dialog.textContent||'').replace(/\s+/g,' ').trim().slice(0,800)};
    }''')
    page.wait_for_timeout(2500)
    page.screenshot(path=str(OUT_DIR / 'dxm_edit_flow_v2_03_after_skip.png'), full_page=True)
    result['steps'].append({'step':'skip_dialog','data':skip,'url':page.url,'title':page.title()})

    state = page.evaluate(r'''() => {
      const body = document.body.innerText || '';
      return {
        flags: {
          has_dxm_info: body.includes('店小秘信息'),
          has_product_info: body.includes('产品信息'),
          has_save: body.includes('保存'),
          has_publish: body.includes('发布'),
          has_half_manage: body.includes('半托管'),
          has_edit_page_title: document.title.includes('编辑')
        },
        body: body.slice(0,6000)
      };
    }''')
    result['steps'].append({'step':'final_state','url':page.url,'title':page.title(),'data':state})

    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    browser.close()
