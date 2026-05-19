import json
import re
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

ROOT = Path('/root/.Hermes/workspace/dxm-auto-uikit')
COOKIE_FILE = ROOT / 'data' / 'sessions' / 'dianxiaomi_cookies.json'
OUT_DIR = ROOT / 'data' / 'screenshots'
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_JSON = ROOT / 'data' / 'sessions' / 'dianxiaomi_menu_probe.json'


def load_cookies():
    raw = json.loads(COOKIE_FILE.read_text(encoding='utf-8'))
    cookies = []
    for c in raw:
        item = {
            'name': c['name'],
            'value': c['value'],
            'domain': c['domain'],
            'path': c.get('path', '/'),
            'httpOnly': c.get('httpOnly', False),
            'secure': c.get('secure', False),
        }
        same_site = c.get('sameSite')
        if same_site in ('lax', 'strict', 'none', 'Lax', 'Strict', 'None'):
            item['sameSite'] = same_site.capitalize() if same_site.lower() != 'none' else 'None'
        if 'expirationDate' in c:
            item['expires'] = int(c['expirationDate'])
        cookies.append(item)
    return cookies


def body_sample(page, n=1200):
    try:
        return page.locator('body').inner_text(timeout=5000)[:n]
    except Exception as e:
        return f'<body_text_error: {e}>'


def visible_overlay_info(page):
    js = r'''
() => {
  const selectors = [
    '[role="dialog"]', '.modal', '.dialog', '.popup', '.pop', '.mask', '.layui-layer',
    '[class*="modal"]', '[class*="dialog"]', '[class*="popup"]', '[class*="mask"]',
    '[class*="notice"]', '[class*="alert"]'
  ];
  const out = [];
  const seen = new Set();
  for (const sel of selectors) {
    for (const el of document.querySelectorAll(sel)) {
      if (seen.has(el)) continue;
      seen.add(el);
      const st = getComputedStyle(el);
      const r = el.getBoundingClientRect();
      const visible = st.display !== 'none' && st.visibility !== 'hidden' && parseFloat(st.opacity || '1') > 0 && r.width > 20 && r.height > 20;
      if (!visible) continue;
      const text = (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 200);
      out.push({selector: sel, className: el.className || '', id: el.id || '', zIndex: st.zIndex || '', rect: {x:r.x,y:r.y,w:r.width,h:r.height}, text});
    }
  }
  return out.slice(0, 20);
}
'''
    return page.evaluate(js)


def try_close_overlays(page):
    attempts = []
    close_patterns = ['关闭', '×', '✕', '我知道了', '知道了', '取消', 'close', 'Close', '稍后', '跳过']
    selectors = ['button', '[role="button"]', 'a', 'span', 'i']
    for _ in range(3):
        info = visible_overlay_info(page)
        attempts.append({'before': info})
        if not info:
            break
        clicked = []
        for text in close_patterns:
            try:
                locator = page.get_by_text(text, exact=True)
                count = locator.count()
                for i in range(min(count, 5)):
                    el = locator.nth(i)
                    if el.is_visible(timeout=1000):
                        el.click(timeout=1500)
                        page.wait_for_timeout(800)
                        clicked.append(text)
                        break
            except Exception:
                pass
        if not clicked:
            # fallback: try top-right small clickable candidates inside overlay-like containers
            js = r'''
() => {
  const sels = ['[role="dialog"]','[class*="modal"]','[class*="dialog"]','[class*="popup"]','[class*="mask"]','.layui-layer'];
  for (const sel of sels) {
    for (const box of document.querySelectorAll(sel)) {
      const r = box.getBoundingClientRect();
      if (r.width < 40 || r.height < 40) continue;
      const candidates = Array.from(box.querySelectorAll('button,a,span,i')).filter(el => {
        const rr = el.getBoundingClientRect();
        const txt = (el.innerText || el.textContent || '').trim();
        return rr.width > 8 && rr.height > 8 && rr.left > r.left + r.width * 0.6 && rr.top < r.top + r.height * 0.35 && txt.length <= 8;
      });
      if (candidates[0]) { candidates[0].click(); return {clicked: true, text: (candidates[0].innerText || candidates[0].textContent || '').trim()}; }
    }
  }
  return {clicked: false};
}
'''
            res = page.evaluate(js)
            clicked.append(str(res))
            page.wait_for_timeout(800)
        attempts[-1]['clicked'] = clicked
    return attempts


def try_hover_or_click(page, text):
    logs = []
    loc = page.get_by_text(text, exact=True)
    count = loc.count()
    logs.append({'text': text, 'count': count})
    for i in range(min(count, 5)):
        el = loc.nth(i)
        try:
            if not el.is_visible(timeout=1500):
                continue
            box = el.bounding_box()
            logs.append({'candidate': i, 'box': box})
            try:
                el.hover(timeout=2000)
                page.wait_for_timeout(1200)
                logs.append({'candidate': i, 'action': 'hover_ok'})
                return logs
            except Exception as e:
                logs.append({'candidate': i, 'hover_error': str(e)})
            try:
                el.click(timeout=2000)
                page.wait_for_timeout(1500)
                logs.append({'candidate': i, 'action': 'click_ok'})
                return logs
            except Exception as e:
                logs.append({'candidate': i, 'click_error': str(e)})
        except Exception as e:
            logs.append({'candidate': i, 'visible_error': str(e)})
    return logs

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
    context = browser.new_context(ignore_https_errors=True, viewport={'width': 1440, 'height': 1024})
    context.add_cookies(load_cookies())
    page = context.new_page()
    result = {}
    page.goto('https://www.dianxiaomi.com/index.htm', wait_until='domcontentloaded', timeout=45000)
    page.wait_for_timeout(3000)
    result['home_url'] = page.url
    result['home_title'] = page.title()
    result['home_sample'] = body_sample(page)
    result['overlays_before'] = visible_overlay_info(page)
    page.screenshot(path=str(OUT_DIR / 'dxm_home_before_overlay.png'), full_page=True)
    result['overlay_close_attempts'] = try_close_overlays(page)
    result['overlays_after'] = visible_overlay_info(page)
    page.screenshot(path=str(OUT_DIR / 'dxm_home_after_overlay.png'), full_page=True)
    result['product_nav_attempts'] = try_hover_or_click(page, '产品')
    result['after_product_sample'] = body_sample(page, 2000)
    page.screenshot(path=str(OUT_DIR / 'dxm_after_product_nav.png'), full_page=True)
    result['data_collect_attempts'] = try_hover_or_click(page, '数据采集')
    result['after_data_collect_url'] = page.url
    result['after_data_collect_sample'] = body_sample(page, 2500)
    page.screenshot(path=str(OUT_DIR / 'dxm_after_data_collect.png'), full_page=True)

    result['menu_nodes'] = page.evaluate(r'''() => {
      const targets = ['数据采集','数据搬家','采集箱','待发布','在线产品','创建产品','常用模板','营销管理','产品诊断','货品管理','半托管产品'];
      const nodes = Array.from(document.querySelectorAll('*'));
      const out = [];
      for (const el of nodes) {
        const txt = (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
        if (!targets.includes(txt)) continue;
        const st = getComputedStyle(el);
        const r = el.getBoundingClientRect();
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
          parent_href: el.parentElement?.getAttribute?.('href') || null
        });
      }
      return out;
    }''')
    result['route_snippets'] = page.evaluate(r'''() => {
      const html = document.body.innerHTML;
      const snippets = [];
      for (const kw of ['采集箱','待发布','在线产品','创建产品']) {
        const idx = html.indexOf(kw);
        if (idx >= 0) snippets.push({kw, snippet: html.slice(Math.max(0, idx - 300), idx + 500)});
      }
      return snippets;
    }''')

    # gather interesting visible texts for nearby menu items
    interesting = ['数据采集', '数据搬家', '采集箱', '待发布', '在线产品', '创建产品', '常用模板', '营销管理', '产品诊断', '认领']
    found = {}
    for text in interesting:
        try:
            loc = page.get_by_text(text, exact=True)
            found[text] = {'count': loc.count()}
            coords = []
            for i in range(min(loc.count(), 5)):
                el = loc.nth(i)
                if el.is_visible(timeout=800):
                    coords.append(el.bounding_box())
            found[text]['visible_boxes'] = coords
        except Exception as e:
            found[text] = {'error': str(e)}
    result['interesting_texts'] = found

    browser.close()

OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(result, ensure_ascii=False, indent=2))
