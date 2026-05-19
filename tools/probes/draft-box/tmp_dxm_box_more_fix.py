import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path('/root/.Hermes/workspace/dxm-auto-uikit')
COOKIE_FILE = ROOT / 'data' / 'sessions' / 'dianxiaomi_cookies.json'
OUT_JSON = ROOT / 'data' / 'sessions' / 'dianxiaomi_box_more_fix.json'
OUT_DIR = ROOT / 'data' / 'screenshots'
OUT_DIR.mkdir(parents=True, exist_ok=True)
TARGET_TEXT = '崩坏3钥匙扣爱莉希雅'


def load_cookies():
    raw = json.loads(COOKIE_FILE.read_text(encoding='utf-8'))
    out = []
    for c in raw:
        item = {'name': c['name'], 'value': c['value'], 'domain': c['domain'], 'path': c.get('path', '/'), 'httpOnly': c.get('httpOnly', False), 'secure': c.get('secure', False)}
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
    result = {}
    page.goto('https://www.dianxiaomi.com/web/smt/smtProductList/draft', wait_until='domcontentloaded', timeout=45000)
    page.wait_for_timeout(3500)
    page.evaluate(r'''({target, frag}) => { const stores=[...document.querySelectorAll("*")]; const s=stores.find(el=>(el.innerText||el.textContent||"").replace(/\s+/g,"").trim()===target.replace(/\s+/g,"")); if(s) s.dispatchEvent(new MouseEvent("click",{bubbles:true})); const input=[...document.querySelectorAll("input.ant-input,input")].find(el=>{const r=el.getBoundingClientRect(); return r.width>220 && r.height>20 && !el.disabled}); if(input){input.value=frag; input.dispatchEvent(new Event("input",{bubbles:true})); input.dispatchEvent(new Event("change",{bubbles:true}));} const btn=[...document.querySelectorAll("button,span,a,div")].find(el=>(el.innerText||el.textContent||"").replace(/\s+/g,"").trim()==="搜索"); if(btn) btn.dispatchEvent(new MouseEvent("click",{bubbles:true})); }''', {'target':'Dang Kang','frag':TARGET_TEXT})
    page.wait_for_timeout(2200)

    # row match and exact action links
    info = page.evaluate('(frag) => { const rows=[...document.querySelectorAll("tr.vxe-body--row, tr")]; const idx=rows.findIndex(tr=>(tr.innerText||tr.textContent||"").includes(frag) && !(tr.innerText||tr.textContent||"").includes("备注:")); if(idx<0) return {ok:false}; const row=rows[idx]; const links=[...row.querySelectorAll("a.link.ant-dropdown-trigger, button.link.ant-dropdown-trigger, .link.ant-dropdown-trigger")].map((el,i)=>{const r=el.getBoundingClientRect(); return {i, txt:(el.innerText||el.textContent||"").replace(/\\s+/g," ").trim(), cls:String(el.className||""), rect:{x:r.x,y:r.y,w:r.width,h:r.height}, html:el.outerHTML.slice(0,200)}}); return {ok:true, idx, rowText:(row.innerText||row.textContent||"").replace(/\\s+/g," ").trim().slice(0,500), links}; }', TARGET_TEXT)
    result['row_info'] = info
    if info.get('ok') and info['links']:
        # choose explicit 更多 link
        more = next((x for x in info['links'] if x['txt']=='更多'), None)
        if more:
            page.mouse.click(more['rect']['x'] + more['rect']['w']/2, more['rect']['y'] + more['rect']['h']/2)
            page.wait_for_timeout(1500)
            page.screenshot(path=str(OUT_DIR / 'dxm_box_more_fix_01_menu.png'), full_page=True)
            result['clicked_more'] = more
            result['dropdowns'] = page.evaluate(r'''() => Array.from(document.querySelectorAll('.ant-dropdown, .ant-dropdown-menu, li.ant-dropdown-menu-item')).map(el => { const st=getComputedStyle(el), r=el.getBoundingClientRect(); return {tag:el.tagName, cls:String(el.className||''), txt:(el.innerText||el.textContent||'').replace(/\s+/g,' ').trim(), rect:{x:r.x,y:r.y,w:r.width,h:r.height}, display:st.display}; }).filter(x => x.txt || x.cls.includes('dropdown')).slice(0,30)''')
            item = page.evaluate(r'''() => { const el=[...document.querySelectorAll('li.ant-dropdown-menu-item')].find(el => (el.innerText||el.textContent||'').replace(/\s+/g,'').trim()==='添加备注'); if(!el) return null; const r=el.getBoundingClientRect(); return {x:r.x,y:r.y,w:r.width,h:r.height, txt:(el.innerText||el.textContent||'').trim()}; }''')
            result['add_note_item'] = item
            if item:
                page.mouse.click(item['x'] + item['w']/2, item['y'] + item['h']/2)
                page.wait_for_timeout(1500)
                page.screenshot(path=str(OUT_DIR / 'dxm_box_more_fix_02_modal.png'), full_page=True)
                result['modal'] = page.evaluate(r'''() => { const el=[...document.querySelectorAll('[role="dialog"], .ant-modal-wrap, .ant-modal')].find(el => (el.innerText||el.textContent||'').includes('备注') && (el.innerText||el.textContent||'').includes('颜色')); if(!el) return {ok:false}; return {ok:true, txt:(el.innerText||el.textContent||'').replace(/\s+/g,' ').trim()}; }''')
    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    browser.close()
