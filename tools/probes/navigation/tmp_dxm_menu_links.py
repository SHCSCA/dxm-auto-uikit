import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path('/root/.Hermes/workspace/dxm-auto-uikit')
COOKIE_FILE = ROOT / 'data' / 'sessions' / 'dianxiaomi_cookies.json'
OUT_JSON = ROOT / 'data' / 'sessions' / 'dianxiaomi_menu_links.json'
OUT_DIR = ROOT / 'data' / 'screenshots'
OUT_DIR.mkdir(parents=True, exist_ok=True)


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

js_links = r'''
() => {
  const texts = ['数据采集','数据搬家','采集箱','待发布','在线产品','创建产品','常用模板','营销管理','产品诊断'];
  const nodes = Array.from(document.querySelectorAll('a,button,span,div,li'));
  const out = [];
  for (const el of nodes) {
    const txt = (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
    if (!texts.some(t => txt === t || txt.includes(t))) continue;
    const st = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    if (st.display === 'none' || st.visibility === 'hidden' || parseFloat(st.opacity || '1') === 0 || r.width < 10 || r.height < 10) continue;
    out.push({
      tag: el.tagName,
      text: txt,
      href: el.getAttribute('href'),
      onclick: el.getAttribute('onclick'),
      cls: el.className || '',
      id: el.id || '',
      rect: {x:r.x,y:r.y,w:r.width,h:r.height},
      dataset: {...el.dataset},
      parent_text: (el.parentElement?.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 120),
      parent_tag: el.parentElement?.tagName || '',
      parent_cls: el.parentElement?.className || ''
    });
  }
  return out.slice(0, 80);
}
'''

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
    context = browser.new_context(ignore_https_errors=True, viewport={'width': 1440, 'height': 1024})
    context.add_cookies(load_cookies())
    page = context.new_page()
    page.goto('https://www.dianxiaomi.com/index.htm', wait_until='domcontentloaded', timeout=45000)
    page.wait_for_timeout(2500)
    # close stacked modal/overlay dialogs robustly before hovering menu
    for _ in range(8):
        dialog = page.locator('[role="dialog"]:visible')
        try:
            dialog_count = dialog.count()
        except Exception:
            dialog_count = 0
        if dialog_count == 0:
            break
        closed = False
        for sel in [
            '[role="dialog"] .ant-modal-close',
            '[role="dialog"] .ant-modal-close-x',
            '[role="dialog"] .ant-modal-footer button',
            'button:has-text("关闭")',
            'span:has-text("关闭")'
        ]:
            try:
                loc = page.locator(sel)
                if loc.count() > 0 and loc.first.is_visible(timeout=800):
                    loc.first.click(timeout=1500, force=True)
                    page.wait_for_timeout(1200)
                    closed = True
                    break
            except Exception:
                pass
        if not closed:
            try:
                page.keyboard.press('Escape')
                page.wait_for_timeout(800)
                closed = True
            except Exception:
                pass
        if not closed:
            break
    page.get_by_text('产品', exact=True).hover(timeout=5000)
    page.wait_for_timeout(1500)
    page.screenshot(path=str(OUT_DIR / 'dxm_menu_open_links.png'), full_page=True)
    result = {
        'url': page.url,
        'title': page.title(),
        'matches': page.evaluate(js_links)
    }
    # attempt click visible 采集箱-related node using text locators
    attempts = []
    for text in ['采集箱', '待发布', '创建产品']:
        try:
            loc = page.get_by_text(text, exact=True)
            attempts.append({'text': text, 'count': loc.count()})
            for i in range(min(loc.count(), 6)):
                el = loc.nth(i)
                if el.is_visible(timeout=800):
                    box = el.bounding_box()
                    attempts.append({'text': text, 'i': i, 'box': box})
                    el.click(timeout=2500)
                    page.wait_for_timeout(2500)
                    attempts.append({'text': text, 'clicked_i': i, 'url_after': page.url, 'title_after': page.title(), 'body': page.locator('body').inner_text()[:1000]})
                    page.screenshot(path=str(OUT_DIR / f'dxm_after_click_{text}.png'), full_page=True)
                    raise SystemExit
        except SystemExit:
            break
        except Exception as e:
            attempts.append({'text': text, 'error': str(e)})
    result['click_attempts'] = attempts
    browser.close()

OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(result, ensure_ascii=False, indent=2))
