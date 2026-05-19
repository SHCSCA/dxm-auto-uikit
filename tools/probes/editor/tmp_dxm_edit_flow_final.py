import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path('/root/.Hermes/workspace/dxm-auto-uikit')
COOKIE_FILE = ROOT / 'data' / 'sessions' / 'dianxiaomi_cookies.json'
OUT_JSON = ROOT / 'data' / 'sessions' / 'dianxiaomi_edit_flow_final.json'
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

    targets = page.evaluate(r'''(frag) => {
      const rows = Array.from(document.querySelectorAll('tr.vxe-body--row, tr'));
      const picked = rows.map((tr, idx) => ({idx, text:(tr.innerText||tr.textContent||'').replace(/\s+/g,' ').trim()})).find(x => x.text.includes(frag));
      if (!picked) return {ok:false};
      const row = rows[picked.idx];
      const editA = Array.from(row.querySelectorAll('a')).find(el => (el.innerText||el.textContent||'').replace(/\s+/g,'').trim()==='编辑');
      const editDiv = Array.from(row.querySelectorAll('*')).find(el => (el.innerText||el.textContent||'').replace(/\s+/g,'').trim()==='编辑');
      const box = (el) => {
        if (!el) return null;
        const r = el.getBoundingClientRect();
        return {tag: el.tagName, cls: String(el.className||''), txt:(el.innerText||el.textContent||'').replace(/\s+/g,' ').trim(), rect:{x:r.x,y:r.y,w:r.width,h:r.height}};
      };
      return {ok:true, rowText:picked.text.slice(0,500), editA:box(editA), editDiv:box(editDiv)};
    }''', TARGET_TEXT)
    result['steps'].append({'step':'targets','data':targets})
    target = targets.get('editA') or targets.get('editDiv')
    if not target:
        OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False, indent=2))
        browser.close(); raise SystemExit

    page.mouse.click(target['rect']['x'] + target['rect']['w']/2, target['rect']['y'] + target['rect']['h']/2)
    page.wait_for_timeout(2200)
    page.screenshot(path=str(OUT_DIR / 'dxm_edit_final_01_after_edit.png'), full_page=True)
    result['steps'].append({'step':'after_edit','url':page.url,'title':page.title(),'body':page.locator('body').inner_text()[:2500]})

    dialog = page.evaluate(r'''() => {
      const dlg = Array.from(document.querySelectorAll('[role="dialog"], .ant-modal-wrap, .ant-modal')).find(el => {
        const t = (el.innerText||el.textContent||'').replace(/\s+/g,' ').trim();
        return t.includes('编辑分类') || t.includes('跳过，去编辑产品') || t.includes('编辑产品');
      });
      if (!dlg) return {ok:false};
      const buttons = Array.from(dlg.querySelectorAll('button,span,a,div')).map(el => {
        const txt = (el.innerText||el.textContent||'').replace(/\s+/g,' ').trim();
        const r = el.getBoundingClientRect();
        if (!txt || r.width < 5 || r.height < 5) return null;
        return {txt, tag:el.tagName, cls:String(el.className||''), rect:{x:r.x,y:r.y,w:r.width,h:r.height}};
      }).filter(Boolean);
      const skip = buttons.find(b => b.txt.includes('跳过')) || null;
      return {ok:true, text:(dlg.innerText||dlg.textContent||'').replace(/\s+/g,' ').trim().slice(0,1000), buttons, skip};
    }''')
    result['steps'].append({'step':'dialog','data':dialog})
    if dialog.get('ok') and dialog.get('skip'):
        s = dialog['skip']
        page.mouse.click(s['rect']['x'] + s['rect']['w']/2, s['rect']['y'] + s['rect']['h']/2)
        page.wait_for_timeout(3500)
        page.screenshot(path=str(OUT_DIR / 'dxm_edit_final_02_after_skip.png'), full_page=True)
        result['steps'].append({'step':'after_skip','clicked':s,'url':page.url,'title':page.title()})

    final = page.evaluate(r'''() => {
      const body = document.body.innerText || '';
      const matches = Array.from(document.querySelectorAll('*')).map(el => {
        const txt = (el.innerText||el.textContent||'').replace(/\s+/g,' ').trim();
        if (!txt) return null;
        const keys = ['店小秘信息','产品信息','保存','发布','半托管','运费模板','类目','分类'];
        if (!keys.some(k => txt.includes(k))) return null;
        const r = el.getBoundingClientRect();
        const st = getComputedStyle(el);
        if (st.display==='none' || st.visibility==='hidden' || parseFloat(st.opacity||'1')===0 || r.width < 5 || r.height < 5) return null;
        return {tag:el.tagName, txt:txt.slice(0,150), cls:String(el.className||''), rect:{x:r.x,y:r.y,w:r.width,h:r.height}};
      }).filter(Boolean).slice(0,80);
      return {
        flags: {
          has_dxm_info: body.includes('店小秘信息'),
          has_product_info: body.includes('产品信息'),
          has_save: body.includes('保存'),
          has_publish: body.includes('发布'),
          has_half_manage: body.includes('半托管'),
          has_edit_title: document.title.includes('编辑')
        },
        body: body.slice(0,7000),
        matches
      };
    }''')
    result['steps'].append({'step':'final','url':page.url,'title':page.title(),'data':final})

    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    browser.close()
