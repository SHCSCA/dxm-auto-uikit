import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path('/root/.Hermes/workspace/dxm-auto-uikit')
COOKIE_FILE = ROOT / 'data' / 'sessions' / 'dianxiaomi_cookies.json'
OUT_JSON = ROOT / 'data' / 'sessions' / 'dianxiaomi_edit_enter_page.json'
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

    # search target in Dang Kang draft box
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
    page.screenshot(path=str(OUT_DIR / 'dxm_edit_enter_01_search.png'), full_page=True)

    # precise click on edit anchor
    target = page.evaluate(r'''(frag) => {
      const rows = Array.from(document.querySelectorAll('tr.vxe-body--row, tr'));
      const row = rows.find(tr => (tr.innerText||tr.textContent||'').includes(frag));
      if (!row) return {ok:false, reason:'row_not_found'};
      const edit = Array.from(row.querySelectorAll('a')).find(el => (el.innerText||el.textContent||'').replace(/\s+/g,'').trim()==='编辑');
      if (!edit) return {ok:false, reason:'edit_not_found', rowText:(row.innerText||row.textContent||'').replace(/\s+/g,' ').trim().slice(0,500)};
      const r = edit.getBoundingClientRect();
      return {ok:true, rect:{x:r.x,y:r.y,w:r.width,h:r.height}, rowText:(row.innerText||row.textContent||'').replace(/\s+/g,' ').trim().slice(0,500)};
    }''', TARGET_TEXT)
    result['steps'].append({'step': 'target_row', 'data': target})
    if not target.get('ok'):
        OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False, indent=2))
        browser.close()
        raise SystemExit

    page.mouse.click(target['rect']['x'] + target['rect']['w']/2, target['rect']['y'] + target['rect']['h']/2)
    page.wait_for_timeout(1800)
    page.screenshot(path=str(OUT_DIR / 'dxm_edit_enter_02_after_edit_click.png'), full_page=True)

    # find exact skip button
    skip = page.evaluate(r'''() => {
      const dlg = Array.from(document.querySelectorAll('[role="dialog"], .ant-modal-wrap, .ant-modal')).find(el => {
        const t = (el.innerText||el.textContent||'').replace(/\s+/g,' ').trim();
        return t.includes('编辑分类') || t.includes('跳过，去编辑产品');
      });
      if (!dlg) return {ok:false, reason:'dialog_not_found'};
      const candidates = Array.from(dlg.querySelectorAll('button,span,a,div')).map(el => {
        const txt = (el.innerText||el.textContent||'').replace(/\s+/g,' ').trim();
        const r = el.getBoundingClientRect();
        if (!txt || r.width < 5 || r.height < 5) return null;
        return {txt, tag:el.tagName, cls:String(el.className||''), rect:{x:r.x,y:r.y,w:r.width,h:r.height}};
      }).filter(Boolean);
      const exact = candidates.find(x => x.txt == '跳过，去编辑产品') || candidates.find(x => x.txt.endswith('去编辑产品')) || candidates.find(x => x.txt.includes('跳过'));
      return {ok:!!exact, dialog:(dlg.innerText||dlg.textContent||'').replace(/\s+/g,' ').trim().slice(0,1000), skip: exact, candidates};
    }''')
    result['steps'].append({'step': 'skip_probe', 'data': skip})
    if not skip.get('ok'):
        OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False, indent=2))
        browser.close()
        raise SystemExit

    s = skip['skip']
    page.mouse.click(s['rect']['x'] + s['rect']['w']/2, s['rect']['y'] + s['rect']['h']/2)
    page.wait_for_timeout(4500)
    page.screenshot(path=str(OUT_DIR / 'dxm_edit_enter_03_after_skip.png'), full_page=True)

    final = page.evaluate(r'''() => {
      const body = document.body.innerText || '';
      const keys = ['店小秘信息','产品信息','保存','发布','半托管','托管','物流','运费模板','变种','类目','分类'];
      const matches = Array.from(document.querySelectorAll('*')).map(el => {
        const txt = (el.innerText||el.textContent||'').replace(/\s+/g,' ').trim();
        if (!txt) return null;
        if (!keys.some(k => txt.includes(k))) return null;
        const r = el.getBoundingClientRect();
        const st = getComputedStyle(el);
        if (st.display==='none' || st.visibility==='hidden' || parseFloat(st.opacity||'1')===0 || r.width < 5 || r.height < 5) return null;
        return {tag:el.tagName, txt:txt.slice(0,180), cls:String(el.className||''), rect:{x:r.x,y:r.y,w:r.width,h:r.height}};
      }).filter(Boolean).slice(0,120);
      return {
        flags: {
          has_dxm_info: body.includes('店小秘信息'),
          has_product_info: body.includes('产品信息'),
          has_save: body.includes('保存'),
          has_publish: body.includes('发布'),
          has_half_manage: body.includes('半托管'),
          has_consignment: body.includes('托管'),
          has_shipping_template: body.includes('运费模板'),
          has_variant: body.includes('变种'),
          has_category: body.includes('分类') || body.includes('类目')
        },
        body: body.slice(0,8000),
        matches
      };
    }''')
    result['steps'].append({'step': 'final_page', 'url': page.url, 'title': page.title(), 'data': final})

    # one scroll further down for half-managed fields
    page.mouse.wheel(0, 1400)
    page.wait_for_timeout(1200)
    page.screenshot(path=str(OUT_DIR / 'dxm_edit_enter_04_scrolled.png'), full_page=True)
    lower = page.evaluate(r'''() => {
      const body = document.body.innerText || '';
      const keys = ['半托管','托管','物流','运费模板','发货','服务模板','库存','价格'];
      const matches = Array.from(document.querySelectorAll('*')).map(el => {
        const txt = (el.innerText||el.textContent||'').replace(/\s+/g,' ').trim();
        if (!txt) return null;
        if (!keys.some(k => txt.includes(k))) return null;
        const r = el.getBoundingClientRect();
        const st = getComputedStyle(el);
        if (st.display==='none' || st.visibility==='hidden' || parseFloat(st.opacity||'1')===0 || r.width < 5 || r.height < 5) return null;
        return {tag:el.tagName, txt:txt.slice(0,180), cls:String(el.className||''), rect:{x:r.x,y:r.y,w:r.width,h:r.height}};
      }).filter(Boolean).slice(0,120);
      return {body: body.slice(0,8000), matches};
    }''')
    result['steps'].append({'step': 'lower_section', 'data': lower})

    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    browser.close()
