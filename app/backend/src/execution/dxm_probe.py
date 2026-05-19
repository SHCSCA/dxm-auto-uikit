import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[4]
COOKIE_FILE = ROOT / 'data' / 'sessions' / 'dianxiaomi_cookies.json'
OUT_FILE = ROOT / 'data' / 'sessions' / 'dianxiaomi_probe.json'
SCREENSHOT = ROOT / 'data' / 'screenshots' / 'dianxiaomi_probe.png'

with COOKIE_FILE.open('r', encoding='utf-8') as f:
    raw_cookies = json.load(f)

cookies = []
for c in raw_cookies:
    cookie = {
        'name': c['name'],
        'value': c['value'],
        'domain': c['domain'],
        'path': c.get('path', '/'),
        'httpOnly': c.get('httpOnly', False),
        'secure': c.get('secure', False),
    }
    same_site = c.get('sameSite')
    if same_site in ('lax', 'strict', 'none', 'Lax', 'Strict', 'None'):
        cookie['sameSite'] = same_site.capitalize() if same_site.lower() != 'none' else 'None'
    if 'expirationDate' in c:
        cookie['expires'] = int(c['expirationDate'])
    cookies.append(cookie)

urls = [
    'https://www.dianxiaomi.com/',
    'https://www.dianxiaomi.com/index.htm',
    'https://www.dianxiaomi.com/user/index.htm',
    'https://www.dianxiaomi.com/order/orderList.htm',
    'https://www.dianxiaomi.com/product/productList.htm',
]

results = []
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
    context = browser.new_context(ignore_https_errors=True, viewport={'width': 1440, 'height': 1024})
    context.add_cookies(cookies)
    page = context.new_page()
    for url in urls:
        try:
            page.goto(url, wait_until='domcontentloaded', timeout=45000)
            page.wait_for_timeout(2500)
            results.append({
                'url': url,
                'final_url': page.url,
                'title': page.title(),
                'has_login_text': '欢迎登录' in page.content() or '请输入用户名' in page.content(),
                'has_order_text': '订单' in page.content(),
                'has_product_text': '产品' in page.content() or '刊登' in page.content(),
                'text_sample': page.locator('body').inner_text()[:500]
            })
        except Exception as e:
            results.append({'url': url, 'error': str(e)})
    page.screenshot(path=str(SCREENSHOT), full_page=True)
    browser.close()

OUT_FILE.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'probe_file': str(OUT_FILE), 'screenshot': str(SCREENSHOT), 'results': results}, ensure_ascii=False))
