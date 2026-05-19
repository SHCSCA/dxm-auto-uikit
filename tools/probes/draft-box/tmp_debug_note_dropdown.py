import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path('/root/.Hermes/workspace/dxm-auto-uikit')
COOKIE_FILE = ROOT / 'data' / 'sessions' / 'dianxiaomi_cookies.json'


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
    page.goto('https://www.dianxiaomi.com/web/productCrawl/dataAcquisition', wait_until='domcontentloaded', timeout=45000)
    page.wait_for_timeout(3000)
    try:
        page.locator('.ant-modal-close').first.click(force=True)
        page.wait_for_timeout(800)
    except Exception:
        pass
    try:
        page.get_by_text('跳过', exact=True).click(force=True, timeout=1500)
        page.wait_for_timeout(800)
    except Exception:
        pass

    # switch claimed tab
    page.evaluate(r'''() => {
      const tab = Array.from(document.querySelectorAll('*')).find(el => /^已认领\(\d+\)$/.test((el.innerText||el.textContent||'').replace(/\s+/g,'')));
      if (tab) tab.dispatchEvent(new MouseEvent('click', {bubbles:true}));
    }''')
    page.wait_for_timeout(1200)

    # capture first row ids and more html
    print('--- first row info ---')
    print(json.dumps(page.evaluate(r'''() => {
      const row = document.querySelector('tr.vxe-body--row');
      if (!row) return {ok:false};
      const moreWrap = row.querySelector('.ant-dropdown-trigger');
      return {
        ok:true,
        rowText:(row.innerText||row.textContent||'').replace(/\s+/g,' ').trim().slice(0,300),
        moreHtml: moreWrap ? moreWrap.outerHTML : null,
        rowHtml: row.outerHTML.slice(0,1500)
      };
    }'''), ensure_ascii=False, indent=2))

    # try multiple open methods
    methods = []
    for method in ['dispatch_trigger', 'dispatch_anchor', 'mouse_click', 'locator_click_force']:
        page.reload(wait_until='domcontentloaded', timeout=45000)
        page.wait_for_timeout(3000)
        try:
            page.locator('.ant-modal-close').first.click(force=True)
            page.wait_for_timeout(500)
        except Exception:
            pass
        try:
            page.get_by_text('跳过', exact=True).click(force=True, timeout=1200)
            page.wait_for_timeout(500)
        except Exception:
            pass
        page.evaluate(r'''() => {
          const tab = Array.from(document.querySelectorAll('*')).find(el => /^已认领\(\d+\)$/.test((el.innerText||el.textContent||'').replace(/\s+/g,'')));
          if (tab) tab.dispatchEvent(new MouseEvent('click', {bubbles:true}));
        }''')
        page.wait_for_timeout(1200)
        if method == 'dispatch_trigger':
            page.evaluate(r'''() => {
              const row = document.querySelector('tr.vxe-body--row');
              const el = row && row.querySelector('.ant-dropdown-trigger');
              if (el) {
                for (const evt of ['mouseenter','mouseover','mousedown','mouseup','click']) {
                  el.dispatchEvent(new MouseEvent(evt, {bubbles:true}));
                }
              }
            }''')
        elif method == 'dispatch_anchor':
            page.evaluate(r'''() => {
              const row = document.querySelector('tr.vxe-body--row');
              const el = row && Array.from(row.querySelectorAll('a')).find(a => (a.innerText||a.textContent||'').replace(/\s+/g,'').trim()==='更多');
              if (el) {
                for (const evt of ['mouseenter','mouseover','mousedown','mouseup','click']) {
                  el.dispatchEvent(new MouseEvent(evt, {bubbles:true}));
                }
              }
            }''')
        elif method == 'mouse_click':
            box = page.evaluate(r'''() => {
              const row = document.querySelector('tr.vxe-body--row');
              const el = row && row.querySelector('.ant-dropdown-trigger');
              if (!el) return null;
              const r = el.getBoundingClientRect();
              return {x:r.x,y:r.y,w:r.width,h:r.height};
            }''')
            if box:
                page.mouse.click(box['x'] + box['w']/2, box['y'] + box['h']/2)
        elif method == 'locator_click_force':
            try:
                page.locator('tr.vxe-body--row .ant-dropdown-trigger').first.click(force=True, timeout=1500)
            except Exception as e:
                methods.append({'method': method, 'error': str(e)})
        page.wait_for_timeout(1500)
        state = page.evaluate(r'''() => {
          const found = [];
          for (const el of document.querySelectorAll('body *')) {
            const txt = (el.innerText||el.textContent||'').replace(/\s+/g,' ').trim();
            const cls = String(el.className||'');
            if (txt.includes('添加备注') || txt.includes('删除') || cls.includes('dropdown')) {
              const st = getComputedStyle(el); const r = el.getBoundingClientRect();
              found.push({tag:el.tagName, cls, txt:txt.slice(0,200), display:st.display, visibility:st.visibility, opacity:st.opacity, rect:{x:r.x,y:r.y,w:r.width,h:r.height}});
            }
          }
          return found.slice(0,80);
        }''')
        methods.append({'method': method, 'state': state})
    print('--- methods ---')
    print(json.dumps(methods, ensure_ascii=False, indent=2))
    browser.close()
