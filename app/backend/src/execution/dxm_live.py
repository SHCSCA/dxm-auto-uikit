import json
import threading
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

from src.core.config import SCREENSHOT_DIR, SESSION_DIR
from src.execution.browser_runtime import chrome_launch_options

COOKIE_FILE = SESSION_DIR / 'dianxiaomi_cookies.json'
PROBE_FILE = SESSION_DIR / 'dianxiaomi_probe.json'


class DxmLiveClient:
    def __init__(self) -> None:
        self.cookie_file = COOKIE_FILE

    def has_cookie_session(self) -> bool:
        return self.cookie_file.exists()

    def load_cookies(self) -> list[dict[str, Any]]:
        raw = json.loads(self.cookie_file.read_text(encoding='utf-8'))
        cookies: list[dict[str, Any]] = []
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

    def probe_session(self) -> dict[str, Any]:
        if not self.has_cookie_session():
            return {'logged_in': False, 'reason': 'cookie_file_missing'}

        # Playwright Sync API must never run on a thread that may carry a
        # running asyncio loop (e.g. the shared visible-session owner thread):
        # the sync bridge installs a running loop on that thread, which then
        # breaks every later Sync API call on the same thread.  Probe on a
        # fresh one-shot thread instead.
        result_box: dict[str, Any] = {}
        error_box: list[BaseException] = []

        def _run_probe() -> None:
            try:
                result_box.update(self._probe_session_impl())
            except BaseException as exc:  # noqa: BLE001 - forwarded to caller
                error_box.append(exc)

        worker = threading.Thread(target=_run_probe, name='dxm-session-probe', daemon=True)
        worker.start()
        worker.join(timeout=150)
        if worker.is_alive():
            return {'logged_in': False, 'reason': 'probe_timeout'}
        if error_box:
            raise error_box[0]
        return result_box

    def _probe_session_impl(self) -> dict[str, Any]:
        screenshot = SCREENSHOT_DIR / 'dianxiaomi_live_home.png'
        product_screenshot = SCREENSHOT_DIR / 'dianxiaomi_live_products.png'
        result: dict[str, Any] = {}
        with sync_playwright() as p:
            browser = p.chromium.launch(**chrome_launch_options(headless=True))
            try:
                context = browser.new_context(ignore_https_errors=True, viewport={'width': 1440, 'height': 1024})
                context.add_cookies(self.load_cookies())
                page = context.new_page()
                page.goto('https://www.dianxiaomi.com/index.htm', wait_until='domcontentloaded', timeout=45000)
                page.wait_for_timeout(2500)
                body_text = page.locator('body').inner_text()[:1000]
                result = {
                    'logged_in': '欢迎登录' not in body_text and '首页' in body_text,
                    'final_url': page.url,
                    'title': page.title(),
                    'body_text': body_text,
                }
                page.screenshot(path=str(screenshot), full_page=True)
                result['home_screenshot'] = str(screenshot)
                try:
                    page.goto('https://www.dianxiaomi.com/product/productList.htm', wait_until='domcontentloaded', timeout=45000)
                    page.wait_for_timeout(2000)
                    product_text = page.locator('body').inner_text()[:1000]
                    page.screenshot(path=str(product_screenshot), full_page=True)
                    result['product_page'] = {
                        'url': page.url,
                        'title': page.title(),
                        'text': product_text,
                        'screenshot': str(product_screenshot),
                    }
                except Exception as e:
                    result['product_page'] = {'error': str(e)}
            finally:
                browser.close()
        PROBE_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        return result
