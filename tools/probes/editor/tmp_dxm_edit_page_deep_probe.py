import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path('/root/.Hermes/workspace/dxm-auto-uikit')
COOKIE_FILE = ROOT / 'data' / 'sessions' / 'dianxiaomi_cookies.json'
OUT_JSON = ROOT / 'data' / 'sessions' / 'dianxiaomi_edit_page_deep_probe.json'
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

    # switch store + search
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
    page.screenshot(path=str(OUT_DIR / 'dxm_edit_deep_01_search.png'), full_page=True)

    # locate target row and edit link from row text block rather than exact row indices
    locate = page.evaluate(r'''(frag) => {
      const rows = Array.from(document.querySelectorAll('tr.vxe-body--row, tr'));
      const row = rows.find(tr => (tr.innerText||tr.textContent||'').includes(frag));
      if (!row) return {ok:false, reason:'row_not_found'};
      const rowText = (row.innerText||row.textContent||'').replace(/\s+/g,' ').trim().slice(0,500);
      const editA = Array.from(row.querySelectorAll('a')).find(el => (el.innerText||el.textContent||'').replace(/\s+/g,'').trim()==='编辑');
      if (!editA) return {ok:false, reason:'edit_not_found', rowText};
      const r = editA.getBoundingClientRect();
      return {ok:true, rowText, edit:{tag:editA.tagName, cls:String(editA.className||''), rect:{x:r.x,y:r.y,w:r.width,h:r.height}, html:editA.outerHTML.slice(0,200)}};
    }''', TARGET_TEXT)
    result['steps'].append({'step':'locate_row','data':locate})
    if not locate.get('ok'):
        OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False, indent=2))
        browser.close(); raise SystemExit

    e = locate['edit']
    page.mouse.click(e['rect']['x'] + e['rect']['w']/2, e['rect']['y'] + e['rect']['h']/2)
    page.wait_for_timeout(2000)
    page.screenshot(path=str(OUT_DIR / 'dxm_edit_deep_02_after_edit_click.png'), full_page=True)

    dialog = page.evaluate(r'''() => {
      const dlg = Array.from(document.querySelectorAll('[role="dialog"], .ant-modal-wrap, .ant-modal')).find(el => {
        const t = (el.innerText||el.textContent||'').replace(/\s+/g,' ').trim();
        return t.includes('编辑分类') || t.includes('跳过，去编辑产品') || (t.includes('选择产品') && t.includes('编辑产品'));
      });
      if (!dlg) return {ok:false};
      const buttons = Array.from(dlg.querySelectorAll('button,span,a,div')).map(el => {
        const txt = (el.innerText||el.textContent||'').replace(/\s+/g,' ').trim();
        const r = el.getBoundingClientRect();
        if (!txt || r.width < 5 || r.height < 5) return null;
        return {txt, tag:el.tagName, cls:String(el.className||''), rect:{x:r.x,y:r.y,w:r.width,h:r.height}};
      }).filter(Boolean);
      const skip = buttons.find(b => b.txt.includes('跳过')) || null;
      return {ok:true, text:(dlg.innerText||dlg.textContent||'').replace(/\s+/g,' ').trim().slice(0,1200), skip};
    }''')
    result['steps'].append({'step':'category_dialog','data':dialog})
    if dialog.get('ok') and dialog.get('skip'):
      s = dialog['skip']
      page.mouse.click(s['rect']['x'] + s['rect']['w']/2, s['rect']['y'] + s['rect']['h']/2)
      page.wait_for_timeout(3500)
      page.screenshot(path=str(OUT_DIR / 'dxm_edit_deep_03_after_skip.png'), full_page=True)
      result['steps'].append({'step':'skip_clicked','data':s, 'url':page.url, 'title':page.title()})

    # inspect current page state after skip
    inspect = page.evaluate(r'''() => {
      const body = document.body.innerText || '';
      const keys = ['店小秘信息','产品信息','保存','发布','半托管','托管','运费模板','分类','类目','物流'];
      const matches = Array.from(document.querySelectorAll('*')).map(el => {
        const txt = (el.innerText||el.textContent||'').replace(/\s+/g,' ').trim();
        if (!txt) return null;
        if (!keys.some(k => txt.includes(k))) return null;
        const r = el.getBoundingClientRect();
        const st = getComputedStyle(el);
        if (st.display==='none' || st.visibility==='hidden' || parseFloat(st.opacity||'1')===0 || r.width < 5 || r.height < 5) return null;
        return {tag:el.tagName, txt:txt.slice(0,150), cls:String(el.className||''), rect:{x:r.x,y:r.y,w:r.width,h:r.height}};
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
          has_category: body.includes('分类') || body.includes('类目')
        },
        body: body.slice(0,7000),
        matches
      };
    }''')
    result['steps'].append({'step':'post_skip_inspect','url':page.url,'title':page.title(),'data':inspect})

    # scroll once more and inspect lower-half content for half-managed sections
    page.mouse.wheel(0, 1200)
    page.wait_for_timeout(1200)
    page.screenshot(path=str(OUT_DIR / 'dxm_edit_deep_04_scrolled.png'), full_page=True)
    lower = page.evaluate(r'''() => {
      const body = document.body.innerText || '';
      const interesting = ['半托管','托管','价格','库存','物流','运费模板','发货','履约','服务模板','仓'];
      const matches = Array.from(document.querySelectorAll('*')).map(el => {
        const txt = (el.innerText||el.textContent||'').replace(/\s+/g,' ').trim();
        if (!txt) return null;
        if (!interesting.some(k => txt.includes(k))) return null;
        const r = el.getBoundingClientRect();
        const st = getComputedStyle(el);
        if (st.display==='none' || st.visibility==='hidden' || parseFloat(st.opacity||'1')===0 || r.width < 5 || r.height < 5) return null;
        return {tag:el.tagName, txt:txt.slice(0,160), cls:String(el.className||''), rect:{x:r.x,y:r.y,w:r.width,h:r.height}};
      }).filter(Boolean).slice(0,120);
      return {body: body.slice(0,7000), matches};
    }''')
    result['steps'].append({'step':'lower_inspect','data':lower})

    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    browser.close()
