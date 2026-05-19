import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path('/root/.Hermes/workspace/dxm-auto-uikit')
COOKIE_FILE = ROOT / 'data' / 'sessions' / 'dianxiaomi_cookies.json'
OUT_JSON = ROOT / 'data' / 'sessions' / 'dianxiaomi_edit_flow_probe.json'
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
    page.screenshot(path=str(OUT_DIR / 'dxm_edit_flow_01_search.png'), full_page=True)
    result['steps'].append({'step':'landing','url':page.url,'title':page.title(),'body':page.locator('body').inner_text()[:3000]})

    row_info = page.evaluate(r'''(frag) => {
      const rows = Array.from(document.querySelectorAll('tr.vxe-body--row, tr'));
      const matches = rows.map((tr, idx) => ({idx, text:(tr.innerText||tr.textContent||'').replace(/\s+/g,' ').trim()})).filter(x => x.text.includes(frag));
      const picked = matches.find(x => !x.text.includes('备注:')) || matches[0] || null;
      if (!picked) return {ok:false, matches};
      const row = rows[picked.idx];
      const actions = Array.from(row.querySelectorAll('*')).map(el => {
        const txt = (el.innerText||el.textContent||'').replace(/\s+/g,' ').trim();
        const r = el.getBoundingClientRect();
        if (!txt || r.width < 5 || r.height < 5) return null;
        if (!['移入待发布','编辑','发布','更多'].includes(txt)) return null;
        return {txt, tag:el.tagName, cls:String(el.className||''), rect:{x:r.x,y:r.y,w:r.width,h:r.height}, html:el.outerHTML.slice(0,200)};
      }).filter(Boolean);
      return {ok:true, rowIndex:picked.idx, rowText:picked.text.slice(0,600), actions};
    }''', TARGET_TEXT)
    result['steps'].append({'step':'row_info','data':row_info})
    edit = next((a for a in row_info.get('actions', []) if a['txt']=='编辑'), None)
    result['steps'].append({'step':'edit_target','data':edit})
    if not edit:
      OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
      print(json.dumps(result, ensure_ascii=False, indent=2))
      browser.close()
      raise SystemExit

    page.mouse.click(edit['rect']['x'] + edit['rect']['w']/2, edit['rect']['y'] + edit['rect']['h']/2)
    page.wait_for_timeout(2200)
    page.screenshot(path=str(OUT_DIR / 'dxm_edit_flow_02_after_edit_click.png'), full_page=True)

    popup = page.evaluate(r'''() => {
      const dialogs = Array.from(document.querySelectorAll('[role="dialog"], .ant-modal-wrap, .ant-modal')).map(el => ({
        cls:String(el.className||''),
        txt:(el.innerText||el.textContent||'').replace(/\s+/g,' ').trim().slice(0,1000)
      }));
      const category = dialogs.find(d => d.txt.includes('分类') || d.txt.includes('编辑分类') || d.txt.includes('类目'));
      return {dialogs, category};
    }''')
    result['steps'].append({'step':'after_edit_click','data':popup, 'url': page.url, 'title': page.title()})

    # click skip if popup exists
    skip_result = page.evaluate(r'''() => {
      const candidates = Array.from(document.querySelectorAll('button, span, a, div')).filter(el => {
        const t = (el.innerText||el.textContent||'').replace(/\s+/g,'').trim();
        return ['跳过','暂不选择','稍后再说','取消'].includes(t);
      });
      const el = candidates[0];
      if (!el) return {ok:false, reason:'no_skip_button'};
      el.dispatchEvent(new MouseEvent('click', {bubbles:true}));
      return {ok:true, text:(el.innerText||el.textContent||'').replace(/\s+/g,'').trim(), cls:String(el.className||'')};
    }''')
    page.wait_for_timeout(2500)
    page.screenshot(path=str(OUT_DIR / 'dxm_edit_flow_03_after_skip.png'), full_page=True)
    result['steps'].append({'step':'skip_popup','data':skip_result,'url':page.url,'title':page.title()})

    edit_page = page.evaluate(r'''() => {
      const body = document.body.innerText || '';
      const flags = {
        has_dxm_info: body.includes('店小秘信息'),
        has_product_info: body.includes('产品信息'),
        has_save: body.includes('保存'),
        has_publish: body.includes('发布'),
        has_half_manage_text: body.includes('半托管'),
        has_consignment: body.includes('托管'),
        has_logistics_template: body.includes('运费模板'),
        has_category: body.includes('分类'),
      };
      const matches = Array.from(document.querySelectorAll('*')).map(el => {
        const txt = (el.innerText||el.textContent||'').replace(/\s+/g,' ').trim();
        if (!txt) return null;
        const keywords = ['半托管','托管','运费模板','店小秘信息','产品信息','保存','发布','类目','分类'];
        if (!keywords.some(k => txt.includes(k))) return null;
        const r = el.getBoundingClientRect();
        const st = getComputedStyle(el);
        if (st.display==='none' || st.visibility==='hidden' || parseFloat(st.opacity||'1')===0 || r.width < 5 || r.height < 5) return null;
        return {tag:el.tagName, txt:txt.slice(0,150), cls:String(el.className||''), rect:{x:r.x,y:r.y,w:r.width,h:r.height}};
      }).filter(Boolean).slice(0,120);
      return {flags, matches, body: body.slice(0,6000)};
    }''')
    result['steps'].append({'step':'edit_page_state','data':edit_page,'url':page.url,'title':page.title()})

    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    browser.close()
