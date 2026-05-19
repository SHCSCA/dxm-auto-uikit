import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path('/root/.Hermes/workspace/dxm-auto-uikit')
COOKIE_FILE = ROOT / 'data' / 'sessions' / 'dianxiaomi_cookies.json'
OUT_JSON = ROOT / 'data' / 'sessions' / 'dianxiaomi_box_correct_note_test.json'
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


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
        ctx = browser.new_context(ignore_https_errors=True, viewport={'width': 1600, 'height': 1400})
        ctx.add_cookies(load_cookies())
        page = ctx.new_page()
        result = {'steps': []}

        page.goto('https://www.dianxiaomi.com/web/smt/smtProductList/draft', wait_until='domcontentloaded', timeout=45000)
        page.wait_for_timeout(3500)
        result['steps'].append({'step':'landing','url':page.url,'title':page.title(),'body':page.locator('body').inner_text()[:2500]})
        page.screenshot(path=str(OUT_DIR / 'dxm_box_correct_01_landing.png'), full_page=True)

        # switch store to Dang Kang
        switch_res = page.evaluate(r'''() => {
            const node = Array.from(document.querySelectorAll('*')).find(el => (el.innerText||el.textContent||'').replace(/\s+/g,'').trim()==='DangKang');
            if (!node) return {ok:false, reason:'store_not_found'};
            node.dispatchEvent(new MouseEvent('click', {bubbles:true}));
            return {ok:true, cls:String(node.className||''), text:(node.innerText||node.textContent||'').trim()};
        }''')
        page.wait_for_timeout(1200)
        result['steps'].append({'step':'switch_store','res':switch_res})

        # search target product
        search_res = page.evaluate('(frag) => {\n'
            'const input = Array.from(document.querySelectorAll("input.ant-input, input")).find(el => { const r = el.getBoundingClientRect(); return r.width > 220 && r.height > 20 && !el.disabled; });\n'
            'if (!input) return {ok:false, reason:"no_search_input"};\n'
            'input.value = frag; input.dispatchEvent(new Event("input", {bubbles:true})); input.dispatchEvent(new Event("change", {bubbles:true}));\n'
            'const btn = Array.from(document.querySelectorAll("button, span, a, div")).find(el => (el.innerText||el.textContent||"").replace(/\\s+/g,"").trim()==="搜索");\n'
            'if (btn) btn.dispatchEvent(new MouseEvent("click", {bubbles:true}));\n'
            'return {ok:true, value: input.value};\n'
            '}', TARGET_TEXT)
        page.wait_for_timeout(2000)
        page.screenshot(path=str(OUT_DIR / 'dxm_box_correct_02_search.png'), full_page=True)
        result['steps'].append({'step':'search','res':search_res,'body':page.locator('body').inner_text()[:4000]})

        # find target row WITHOUT existing note first if possible
        row_pick = page.evaluate('(frag) => {\n'
            'const rows = Array.from(document.querySelectorAll("tr.vxe-body--row, tr"));\n'
            'const matches = rows.map((tr, i) => ({i, text:(tr.innerText||tr.textContent||"").replace(/\\s+/g," ").trim()})).filter(x => x.text.includes(frag));\n'
            'let picked = matches.find(x => !x.text.includes("备注:")) || matches[0] || null;\n'
            'if (!picked) return {ok:false, reason:"row_not_found", matches};\n'
            'const row = rows[picked.i];\n'
            'const blocks = Array.from(row.querySelectorAll("div.vxe-cell > div, td > div, a, span, button")).map(el => ({txt:(el.innerText||el.textContent||"").replace(/\\s+/g," ").trim(), cls:String(el.className||"")})).filter(x => x.txt);\n'
            'return {ok:true, rowIndex:picked.i, rowText:picked.text.slice(0,500), blocks};\n'
            '}', TARGET_TEXT)
        result['steps'].append({'step':'row_pick','res':row_pick})
        if not row_pick.get('ok'):
            OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps(result, ensure_ascii=False, indent=2))
            browser.close()
            return

        row_index = row_pick['res']['rowIndex'] if 'res' in row_pick else row_pick['rowIndex']
        if isinstance(row_pick, dict) and 'rowIndex' in row_pick:
            row_index = row_pick['rowIndex']

        # open the row's 更多 menu specifically, avoiding 发布
        open_more = page.evaluate('(rowIndex) => {\n'
            'const rows = Array.from(document.querySelectorAll("tr.vxe-body--row, tr"));\n'
            'const row = rows[rowIndex];\n'
            'if (!row) return {ok:false, reason:"row_missing"};\n'
            'const candidates = Array.from(row.querySelectorAll("div.ant-dropdown-trigger, button.ant-dropdown-trigger, a, span, div")).filter(el => (el.innerText||el.textContent||"").replace(/\\s+/g,"").trim()==="更多");\n'
            'const triggerWrap = Array.from(row.querySelectorAll("div.ant-dropdown-trigger")).find(el => (el.innerText||el.textContent||"").replace(/\\s+/g,"").trim()==="更多");\n'
            'const target = triggerWrap || candidates[0];\n'
            'if (!target) return {ok:false, reason:"no_more_target", rowText:(row.innerText||row.textContent||"").replace(/\\s+/g," ").trim().slice(0,400)};\n'
            'for (const evt of ["mouseenter","mouseover","mousedown","mouseup","click"]) target.dispatchEvent(new MouseEvent(evt,{bubbles:true}));\n'
            'const r = target.getBoundingClientRect();\n'
            'return {ok:true, targetText:(target.innerText||target.textContent||"").trim(), cls:String(target.className||""), rect:{x:r.x,y:r.y,w:r.width,h:r.height}};\n'
            '}', row_index)
        page.wait_for_timeout(1200)
        page.screenshot(path=str(OUT_DIR / 'dxm_box_correct_03_more_menu.png'), full_page=True)
        result['steps'].append({'step':'open_more','res':open_more})

        dropdown_probe = page.evaluate(r'''() => {
            return Array.from(document.querySelectorAll('.ant-dropdown, .ant-dropdown-menu, li.ant-dropdown-menu-item')).map(el => {
                const st = getComputedStyle(el); const r = el.getBoundingClientRect();
                return {tag:el.tagName, cls:String(el.className||''), txt:(el.innerText||el.textContent||'').replace(/\s+/g,' ').trim(), rect:{x:r.x,y:r.y,w:r.width,h:r.height}, display:st.display, visibility:st.visibility};
            }).filter(x => x.txt || x.cls.includes('dropdown')).slice(0,40)
        }''')
        result['steps'].append({'step':'dropdown_probe','items':dropdown_probe})

        add_note_item = page.evaluate(r'''() => {
            const el = Array.from(document.querySelectorAll('li.ant-dropdown-menu-item')).find(el => (el.innerText||el.textContent||'').replace(/\s+/g,'').trim()==='添加备注');
            if (!el) return null;
            const r = el.getBoundingClientRect();
            return {x:r.x,y:r.y,w:r.width,h:r.height, txt:(el.innerText||el.textContent||'').trim()};
        }''')
        result['steps'].append({'step':'add_note_item','item':add_note_item})
        if not add_note_item:
            OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps(result, ensure_ascii=False, indent=2))
            browser.close()
            return

        page.mouse.click(add_note_item['x'] + add_note_item['w']/2, add_note_item['y'] + add_note_item['h']/2)
        page.wait_for_timeout(1500)
        page.screenshot(path=str(OUT_DIR / 'dxm_box_correct_04_note_modal.png'), full_page=True)

        modal_probe = page.evaluate(r'''() => {
            const modal = Array.from(document.querySelectorAll('[role="dialog"], .ant-modal-wrap, .ant-modal')).find(el => {
                const t = (el.innerText||el.textContent||'').replace(/\s+/g,' ').trim();
                return t.includes('备注') && t.includes('颜色');
            });
            if (!modal) return {ok:false, reason:'no_note_modal'};
            const field = Array.from(modal.querySelectorAll('textarea, input')).find(el => {
                const r = el.getBoundingClientRect();
                return r.width > 150 && r.height > 20 && !el.disabled;
            });
            return {ok:true, modalText:(modal.innerText||modal.textContent||'').replace(/\s+/g,' ').trim(), fieldValue: field ? (field.value||'') : '', fieldPlaceholder: field ? field.getAttribute('placeholder') : null};
        }''')
        result['steps'].append({'step':'modal_probe','res':modal_probe})

        if modal_probe.get('ok'):
            write_submit = page.evaluate(r'''() => {
                const modal = Array.from(document.querySelectorAll('[role="dialog"], .ant-modal-wrap, .ant-modal')).find(el => {
                    const t = (el.innerText||el.textContent||'').replace(/\s+/g,' ').trim();
                    return t.includes('备注') && t.includes('颜色');
                });
                if (!modal) return {ok:false, reason:'no_modal'};
                const field = Array.from(modal.querySelectorAll('textarea, input')).find(el => {
                    const r = el.getBoundingClientRect();
                    return r.width > 150 && r.height > 20 && !el.disabled;
                });
                if (!field) return {ok:false, reason:'no_field'};
                field.value = 'AI认领';
                field.style.color = 'red';
                field.dispatchEvent(new Event('input', {bubbles:true}));
                field.dispatchEvent(new Event('change', {bubbles:true}));
                const colorEl = Array.from(modal.querySelectorAll('*')).find(el => {
                    const st = getComputedStyle(el); const bg = st.backgroundColor || ''; const r = el.getBoundingClientRect();
                    return r.width >= 12 && r.width <= 40 && r.height >= 12 && r.height <= 40 && bg.includes('255, 0, 0');
                });
                let colorInfo = null;
                if (colorEl) {
                    colorEl.dispatchEvent(new MouseEvent('click', {bubbles:true}));
                    const st = getComputedStyle(colorEl);
                    colorInfo = {bg: st.backgroundColor, border: st.borderColor, cls: String(colorEl.className||'')};
                }
                const submit = Array.from(modal.querySelectorAll('button, span, a, div')).find(el => (el.innerText||el.textContent||'').replace(/\s+/g,'').trim()==='提交');
                let submitInfo = null;
                if (submit) {
                    submit.dispatchEvent(new MouseEvent('click', {bubbles:true}));
                    submitInfo = {tag: submit.tagName, cls: String(submit.className||'')};
                }
                return {ok:true, colorInfo, submitInfo};
            }''')
            page.wait_for_timeout(2500)
            page.screenshot(path=str(OUT_DIR / 'dxm_box_correct_05_after_submit.png'), full_page=True)
            result['steps'].append({'step':'write_submit','res':write_submit})

        verify_row = page.evaluate('(rowIndex) => {\n'
            'const rows = Array.from(document.querySelectorAll("tr.vxe-body--row, tr"));\n'
            'const row = rows[rowIndex];\n'
            'if (!row) return {ok:false, reason:"row_missing_after"};\n'
            'return {ok:true, rowText:(row.innerText||row.textContent||"").replace(/\\s+/g," ").trim().slice(0,700)};\n'
            '}', row_index)
        result['steps'].append({'step':'verify_row','res':verify_row, 'body':page.locator('body').inner_text()[:5000]})

        browser.close()
        OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    run()
