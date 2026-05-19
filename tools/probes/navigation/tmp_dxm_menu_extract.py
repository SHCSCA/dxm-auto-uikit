import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path('/root/.Hermes/workspace/dxm-auto-uikit')
COOKIE_FILE = ROOT / 'data' / 'sessions' / 'dianxiaomi_cookies.json'
OUT_JSON = ROOT / 'data' / 'sessions' / 'dianxiaomi_menu_extract.json'
OUT_DIR = ROOT / 'data' / 'screenshots'
OUT_DIR.mkdir(parents=True, exist_ok=True)


def load_cookies():
    raw = json.loads(COOKIE_FILE.read_text(encoding='utf-8'))
    cookies = []
    for c in raw:
        item = {
            'name': c['name'], 'value': c['value'], 'domain': c['domain'], 'path': c.get('path', '/'),
            'httpOnly': c.get('httpOnly', False), 'secure': c.get('secure', False)
        }
        same_site = c.get('sameSite')
        if same_site in ('lax', 'strict', 'none', 'Lax', 'Strict', 'None'):
            item['sameSite'] = same_site.capitalize() if same_site.lower() != 'none' else 'None'
        if 'expirationDate' in c:
            item['expires'] = int(c['expirationDate'])
        cookies.append(item)
    return cookies


def visible_overlay_info(page):
    return page.evaluate(r'''() => {
      const selectors = ['[role="dialog"]','.modal','.dialog','.popup','.pop','.mask','.layui-layer','[class*="modal"]','[class*="dialog"]','[class*="popup"]','[class*="mask"]'];
      const out = [];
      const seen = new Set();
      for (const sel of selectors) {
        for (const el of document.querySelectorAll(sel)) {
          if (seen.has(el)) continue; seen.add(el);
          const st = getComputedStyle(el); const r = el.getBoundingClientRect();
          const visible = st.display !== 'none' && st.visibility !== 'hidden' && parseFloat(st.opacity || '1') > 0 && r.width > 20 && r.height > 20;
          if (!visible) continue;
          out.push({sel, cls: el.className || '', txt: (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 120)});
        }
      }
      return out.slice(0, 15);
    }''')


def try_close_overlays(page):
    logs = []
    for _ in range(4):
        info = visible_overlay_info(page)
        logs.append({'before': info})
        if not info:
            break
        closed = False
        # Prefer explicit close button inside ant modal
        for sel in ['.ant-modal-close', '.ant-modal-close-x', '.ant-modal-footer button']:
            try:
                loc = page.locator(sel)
                if loc.count() > 0 and loc.first.is_visible(timeout=800):
                    loc.first.click(timeout=1200, force=True)
                    page.wait_for_timeout(1000)
                    logs[-1]['clicked'] = sel
                    closed = True
                    break
            except Exception as e:
                logs[-1].setdefault('errors', []).append(f'{sel}: {e}')
        if not closed:
            for txt in ['关闭', '×']:
                try:
                    loc = page.get_by_text(txt, exact=True)
                    if loc.count() > 0 and loc.first.is_visible(timeout=800):
                        loc.first.click(timeout=1200, force=True)
                        page.wait_for_timeout(1000)
                        logs[-1]['clicked'] = txt
                        closed = True
                        break
                except Exception as e:
                    logs[-1].setdefault('errors', []).append(f'{txt}: {e}')
        if not closed:
            break
    return logs

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
    context = browser.new_context(ignore_https_errors=True, viewport={'width': 1440, 'height': 1024})
    context.add_cookies(load_cookies())
    page = context.new_page()
    page.goto('https://www.dianxiaomi.com/index.htm', wait_until='domcontentloaded', timeout=45000)
    page.wait_for_timeout(3000)
    result = {'url': page.url, 'title': page.title(), 'overlay_logs': try_close_overlays(page)}
    page.get_by_text('产品', exact=True).hover(timeout=4000)
    page.wait_for_timeout(1200)
    page.screenshot(path=str(OUT_DIR / 'dxm_menu_extract.png'), full_page=True)
    result['menu_nodes'] = page.evaluate(r'''() => {
      const targets = ['数据采集','数据搬家','采集箱','待发布','在线产品','创建产品','常用模板','营销管理','产品诊断','货品管理','半托管产品'];
      const nodes = Array.from(document.querySelectorAll('*'));
      const out = [];
      for (const el of nodes) {
        const txt = (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
        if (!targets.includes(txt)) continue;
        const st = getComputedStyle(el); const r = el.getBoundingClientRect();
        if (st.display === 'none' || st.visibility === 'hidden' || parseFloat(st.opacity || '1') === 0 || r.width < 5 || r.height < 5) continue;
        out.push({
          text: txt,
          tag: el.tagName,
          href: el.getAttribute('href'),
          onclick: el.getAttribute('onclick'),
          cls: el.className || '',
          id: el.id || '',
          rect: {x:r.x,y:r.y,w:r.width,h:r.height},
          parent_tag: el.parentElement?.tagName || '',
          parent_cls: el.parentElement?.className || '',
          parent_href: el.parentElement?.getAttribute?.('href') || null,
          data_route: el.getAttribute('data-route') || null,
          data_path: el.getAttribute('data-path') || null
        });
      }
      return out;
    }''')
    # direct route extraction from html snippets mentioning menu keywords
    result['route_snippets'] = page.evaluate(r'''() => {
      const html = document.body.innerHTML;
      const snippets = [];
      for (const kw of ['采集箱','待发布','在线产品','创建产品']) {
        const idx = html.indexOf(kw);
        if (idx >= 0) snippets.push({kw, snippet: html.slice(Math.max(0, idx - 300), idx + 500)});
      }
      return snippets;
    }''')
    browser.close()

OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(result, ensure_ascii=False, indent=2))
