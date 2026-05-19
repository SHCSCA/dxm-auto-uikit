import json
import os
from pathlib import Path
from typing import Any

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, TimeoutError, sync_playwright

from src.core.config import SCREENSHOT_DIR, SESSION_DIR
from src.execution.dxm_live import DxmLiveClient
from src.utils import now_iso

RUNTIME_STATE_FILE = SESSION_DIR / 'dianxiaomi_runtime_state.json'
LOGIN_SCREENSHOT_FILE = SCREENSHOT_DIR / 'dianxiaomi_login_start.png'
LOGIN_RESULT_SCREENSHOT_FILE = SCREENSHOT_DIR / 'dianxiaomi_login_result.png'
WORKFLOW_SCREENSHOT_MAP = {
    'product': SCREENSHOT_DIR / 'dianxiaomi_product_page.png',
    'data_acquisition': SCREENSHOT_DIR / 'dianxiaomi_data_acquisition.png',
    'draft_box': SCREENSHOT_DIR / 'dianxiaomi_draft_box.png',
}
DRAFT_ACTION_SCREENSHOT_MAP = {
    'remark': SCREENSHOT_DIR / 'dianxiaomi_draft_box_remark.png',
    'edit': SCREENSHOT_DIR / 'dianxiaomi_draft_box_edit.png',
}
WORKFLOW_TARGETS = {
    'product': {
        'url': 'https://www.dianxiaomi.com/product/productList.htm',
        'label': '产品列表',
        'message': '已进入产品列表页，可以继续往数据采集或产品管理操作。',
        'next_action': '继续切到数据采集或采集箱视图。',
    },
    'data_acquisition': {
        'url': 'https://www.dianxiaomi.com/web/productCrawl/dataAcquisition',
        'label': '数据采集',
        'message': '已进入数据采集页，可以继续认领产品。',
        'next_action': '继续切换到速卖通采集箱或执行认领。',
    },
    'draft_box': {
        'url': 'https://www.dianxiaomi.com/web/smt/smtProductList/draft',
        'label': '速卖通采集箱',
        'message': '已进入速卖通采集箱，可继续查看备注、编辑和发布动作。',
        'next_action': '继续执行添加备注、编辑产品或发布前检查。',
    },
}


class DxmLoginFlow:
    def __init__(self, live_client: DxmLiveClient, state_file: Path | None = None) -> None:
        self.live_client = live_client
        self.state_file = state_file or RUNTIME_STATE_FILE
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    def get_state(self) -> dict[str, Any]:
        if self.state_file.exists():
            return json.loads(self.state_file.read_text(encoding='utf-8'))
        return self._default_state()

    def start_login(self, username: str, password: str) -> dict[str, Any]:
        try:
            browser_state = self._open_login_page_and_fill(username, password)
        except Exception as exc:
            state = self._error_state(
                stage='login_failed',
                label='打开失败',
                message=f'打开店小秘官网并填写账号密码失败：{exc}',
                next_action='检查本机 Chrome、网络或页面结构后重试。',
            )
            self._write_state(state)
            self._close_browser_session()
            return state
        state = {
            'stage': 'waiting_captcha',
            'label': '等待验证码',
            'message': '账号密码已填写，等待用户输入验证码。',
            'next_action': '用户完成验证码后，点击继续登录。',
            'requires_user_action': True,
            'page_title': browser_state.get('page_title') or '店小秘官网登录页',
            'page_url': browser_state.get('page_url') or 'https://www.dianxiaomi.com/',
            'screenshot_url': browser_state.get('screenshot_url'),
            'updated_at': now_iso(),
            'username': username,
            'password_mask': self._mask_secret(password),
        }
        self._write_state(state)
        return state

    def continue_login(self) -> dict[str, Any]:
        try:
            submit_state = self._submit_login_after_captcha()
            live_status = self.live_client.probe_session()
        except Exception as exc:
            state = self._error_state(
                stage='login_failed',
                label='继续失败',
                message=f'继续登录失败：{exc}',
                next_action='确认验证码是否完成，必要时重新打开官网登录页。',
            )
            self._write_state(state)
            self._close_browser_session()
            return state
        if live_status.get('logged_in'):
            state = {
                'stage': 'login_success',
                'label': '已登录',
                'message': '登录成功，已进入真实店小秘后台。',
                'next_action': '继续进入数据采集、采集箱和编辑流程。',
                'requires_user_action': False,
                'page_title': live_status.get('title') or live_status.get('product_page', {}).get('title') or '店小秘首页',
                'page_url': live_status.get('final_url') or live_status.get('product_page', {}).get('url') or 'https://www.dianxiaomi.com/index.htm',
                'screenshot_url': submit_state.get('screenshot_url') or live_status.get('home_screenshot_url') or live_status.get('product_page', {}).get('screenshot_url'),
                'updated_at': now_iso(),
            }
        else:
            state = {
                'stage': 'login_failed',
                'label': '登录失败',
                'message': '继续登录后仍未检测到有效登录态，请检查验证码、账号密码或页面结构变化。',
                'next_action': '重新打开官网登录页并再次尝试，必要时人工接管浏览器。',
                'requires_user_action': True,
                'page_title': live_status.get('title') or '店小秘官网登录页',
                'page_url': live_status.get('final_url') or submit_state.get('page_url') or 'https://www.dianxiaomi.com/',
                'screenshot_url': submit_state.get('screenshot_url') or live_status.get('home_screenshot_url') or live_status.get('product_page', {}).get('screenshot_url'),
                'updated_at': now_iso(),
            }
        self._write_state(state)
        self._close_browser_session()
        return state

    def navigate_post_login(self, target: str) -> dict[str, Any]:
        if target not in WORKFLOW_TARGETS:
            state = self._error_state(
                stage='workflow_navigation_failed',
                label='无效目标',
                message=f'不支持的业务导航目标：{target}',
                next_action='请改为 product、data_acquisition 或 draft_box。',
            )
            self._write_state(state)
            return state
        try:
            result = self._navigate_in_session(target)
        except Exception as exc:
            state = self._error_state(
                stage='workflow_navigation_failed',
                label='导航失败',
                message=f'进入业务页失败：{exc}',
                next_action='确认登录态有效，必要时重新登录后再试。',
            )
            self._write_state(state)
            self._close_browser_session()
            return state

        config = WORKFLOW_TARGETS[target]
        state = {
            'stage': 'workflow_navigation',
            'label': config['label'],
            'message': config['message'],
            'next_action': config['next_action'],
            'requires_user_action': False,
            'page_title': result.get('page_title') or config['label'],
            'page_url': result.get('page_url') or config['url'],
            'screenshot_url': result.get('screenshot_url'),
            'updated_at': now_iso(),
            'current_nav': target,
        }
        self._write_state(state)
        self._close_browser_session()
        return state

    def perform_draft_box_action(self, action: str, note_text: str | None = None) -> dict[str, Any]:
        if action not in DRAFT_ACTION_SCREENSHOT_MAP:
            state = self._error_state(
                stage='draft_box_action_failed',
                label='无效动作',
                message=f'不支持的采集箱动作：{action}',
                next_action='请改为 remark 或 edit。',
            )
            self._write_state(state)
            return state
        try:
            result = self._perform_draft_box_action(action, note_text=note_text)
        except Exception as exc:
            state = self._error_state(
                stage='draft_box_action_failed',
                label='动作失败',
                message=f'执行采集箱动作失败：{exc}',
                next_action='确认已进入采集箱且页面结构未变，再重试动作。',
            )
            self._write_state(state)
            self._close_browser_session()
            return state

        if action == 'edit':
            state = {
                'stage': 'editor_page',
                'label': '已进入编辑界面',
                'message': result.get('message') or '已进入真实编辑界面，可继续读取字段与模板映射。',
                'next_action': '继续处理分类引导、属性信息与编辑页字段。',
                'requires_user_action': False,
                'page_title': result.get('page_title') or '店小秘--编辑速卖通产品',
                'page_url': result.get('page_url'),
                'screenshot_url': result.get('screenshot_url'),
                'updated_at': now_iso(),
                'current_nav': 'edit_page',
                'current_action': action,
                'note_text': note_text,
                'editor_sections': result.get('editor_sections', []),
                'top_actions': result.get('top_actions', []),
                'detected_fields': result.get('detected_fields', []),
            }
            self._write_state(state)
            self._close_browser_session()
            return state

        state = {
            'stage': 'draft_box_action',
            'label': '采集箱动作已触发',
            'message': self._draft_box_action_message(action, note_text),
            'next_action': '继续验证页面回显或进入下一步。',
            'requires_user_action': False,
            'page_title': result.get('page_title') or '速卖通采集箱',
            'page_url': result.get('page_url') or WORKFLOW_TARGETS['draft_box']['url'],
            'screenshot_url': result.get('screenshot_url'),
            'updated_at': now_iso(),
            'current_nav': 'draft_box',
            'current_action': action,
            'note_text': note_text,
        }
        self._write_state(state)
        self._close_browser_session()
        return state

    def _write_state(self, state: dict[str, Any]) -> None:
        self.state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')

    def _default_state(self) -> dict[str, Any]:
        return {
            'stage': 'opening_login_page',
            'label': '待登录',
            'message': '还没有真实店小秘会话，应该从官网登录开始。',
            'next_action': '打开官网登录页，填账号密码，进入验证码等待态。',
            'requires_user_action': True,
            'page_title': '店小秘官网登录页',
            'page_url': 'https://www.dianxiaomi.com/',
            'screenshot_url': None,
            'updated_at': now_iso(),
        }

    def _error_state(self, stage: str, label: str, message: str, next_action: str) -> dict[str, Any]:
        return {
            'stage': stage,
            'label': label,
            'message': message,
            'next_action': next_action,
            'requires_user_action': True,
            'page_title': '店小秘官网登录页',
            'page_url': 'https://www.dianxiaomi.com/',
            'screenshot_url': None,
            'updated_at': now_iso(),
        }

    def _open_login_page_and_fill(self, username: str, password: str) -> dict[str, Any]:
        page = self._ensure_page()
        page.goto('https://www.dianxiaomi.com/', wait_until='domcontentloaded', timeout=45000)
        page.wait_for_timeout(1500)
        self._fill_first_available(page, [
            'input[placeholder="请输入用户名"]',
            'input[name="account"]',
            'input[name="username"]',
            'input[type="text"]',
        ], username)
        self._fill_first_available(page, [
            'input[placeholder="请输入密码"]',
            'input[name="password"]',
            'input[type="password"]',
        ], password)
        page.screenshot(path=str(LOGIN_SCREENSHOT_FILE), full_page=True)
        return {
            'page_title': page.title(),
            'page_url': page.url,
            'screenshot_url': self._artifact_url(LOGIN_SCREENSHOT_FILE),
        }

    def _submit_login_after_captcha(self) -> dict[str, Any]:
        page = self._ensure_page()
        self._click_first_available(page, [
            'label:has-text("记住密码")',
            'input[type="checkbox"]',
            'text=记住密码',
        ])
        self._click_first_available(page, [
            'button:has-text("登录")',
            'input[type="submit"]',
            'text=登录',
        ])
        page.wait_for_timeout(4000)
        page.screenshot(path=str(LOGIN_RESULT_SCREENSHOT_FILE), full_page=True)
        if self._context is not None:
            cookies = self._context.cookies()
            self.live_client.cookie_file.write_text(json.dumps(cookies, ensure_ascii=False, indent=2), encoding='utf-8')
        return {
            'page_title': page.title(),
            'page_url': page.url,
            'screenshot_url': self._artifact_url(LOGIN_RESULT_SCREENSHOT_FILE),
        }

    def _navigate_in_session(self, target: str) -> dict[str, Any]:
        config = WORKFLOW_TARGETS[target]
        page = self._ensure_page_with_cookies()
        page.goto(config['url'], wait_until='domcontentloaded', timeout=45000)
        page.wait_for_timeout(2500)
        screenshot_path = WORKFLOW_SCREENSHOT_MAP[target]
        page.screenshot(path=str(screenshot_path), full_page=True)
        return {
            'page_title': page.title(),
            'page_url': page.url,
            'screenshot_url': self._artifact_url(screenshot_path),
            'target': target,
        }

    def _perform_draft_box_action(self, action: str, note_text: str | None = None) -> dict[str, Any]:
        page = self._ensure_page_with_cookies()
        draft_url = WORKFLOW_TARGETS['draft_box']['url']
        page.goto(draft_url, wait_until='domcontentloaded', timeout=45000)
        page.wait_for_timeout(2500)

        if action == 'edit':
            editor_page = self._open_editor_from_draft_box(page)
            screenshot_path = DRAFT_ACTION_SCREENSHOT_MAP[action]
            editor_page.screenshot(path=str(screenshot_path), full_page=True)
            editor_meta = self._extract_editor_page_meta(editor_page)
            return {
                'page_title': editor_page.title(),
                'page_url': editor_page.url,
                'screenshot_url': self._artifact_url(screenshot_path),
                'action': action,
                'note_text': note_text,
                'message': '已从采集箱进入真实编辑界面。',
                'editor_sections': editor_meta['sections'],
                'top_actions': editor_meta['top_actions'],
                'detected_fields': editor_meta['fields'],
            }

        screenshot_path = DRAFT_ACTION_SCREENSHOT_MAP[action]
        page.screenshot(path=str(screenshot_path), full_page=True)
        return {
            'page_title': page.title(),
            'page_url': page.url,
            'screenshot_url': self._artifact_url(screenshot_path),
            'action': action,
            'note_text': note_text,
        }

    def _ensure_page(self) -> Page:
        if self._page is not None:
            return self._page
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=self._is_headless(),
            executable_path='/usr/bin/google-chrome',
            args=['--no-sandbox'],
        )
        self._context = self._browser.new_context(ignore_https_errors=True, viewport={'width': 1440, 'height': 1024})
        self._page = self._context.new_page()
        return self._page

    def _ensure_page_with_cookies(self) -> Page:
        page = self._ensure_page()
        if self._context is not None and self.live_client.has_cookie_session():
            cookies = self.live_client.load_cookies()
            if cookies:
                self._context.add_cookies(cookies)
        return page

    def _close_browser_session(self) -> None:
        if self._context is not None:
            self._context.close()
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None

    def _fill_first_available(self, page: Page, selectors: list[str], value: str) -> None:
        for selector in selectors:
            locator = page.locator(selector).first
            try:
                if locator.count() == 0:
                    continue
                locator.click(timeout=2000)
                locator.fill(value, timeout=2000)
                return
            except TimeoutError:
                continue
        raise RuntimeError(f'未找到可填写输入框: {selectors}')

    def _open_editor_from_draft_box(self, page: Page) -> Page:
        if self._context is None:
            raise RuntimeError('浏览器上下文不存在，无法从采集箱进入编辑页')

        edit_selectors = [
            'button:has-text("编辑")',
            'a:has-text("编辑")',
            'text=编辑',
        ]
        skip_selectors = [
            'button:has-text("跳过，去编辑产品")',
            'text=跳过，去编辑产品',
        ]

        for selector in edit_selectors:
            locator = page.locator(selector).first
            try:
                if locator.count() == 0:
                    continue
                locator.click(timeout=3000)
                page.wait_for_timeout(1500)
                break
            except TimeoutError:
                continue
        else:
            raise RuntimeError('未找到采集箱编辑入口')

        if '/web/smt/edit' in page.url:
            return page

        for selector in skip_selectors:
            locator = page.locator(selector).first
            try:
                if locator.count() == 0:
                    continue
                with self._context.expect_page(timeout=5000) as new_page_info:
                    locator.click(timeout=3000)
                new_page = new_page_info.value
                new_page.wait_for_load_state('domcontentloaded', timeout=10000)
                new_page.wait_for_timeout(1500)
                return new_page
            except TimeoutError:
                try:
                    locator.click(timeout=3000)
                    page.wait_for_timeout(1500)
                    if '/web/smt/edit' in page.url:
                        return page
                except TimeoutError:
                    continue

        if '/web/smt/edit' in page.url:
            return page
        raise RuntimeError('已触发编辑动作，但未能进入真实编辑界面')

    def _click_first_available(self, page: Page, selectors: list[str]) -> None:
        for selector in selectors:
            locator = page.locator(selector).first
            try:
                if locator.count() == 0:
                    continue
                locator.click(timeout=2000)
                return
            except TimeoutError:
                continue

    def _extract_editor_page_meta(self, page: Page) -> dict[str, list[str]]:
        body_text = page.locator('body').inner_text(timeout=5000)
        sections = [
            name for name in [
                '基本信息', '店小秘信息', '属性信息', '产品信息', '区域调价信息',
                '描述信息', '包装信息', '模版信息', '其他信息',
            ]
            if name in body_text
        ]
        top_actions = [
            name for name in [
                '一键翻译', '产品检测', '引用产品', '图片检测',
                '保存并移入待发布', '保存', '发布',
            ]
            if name in body_text
        ]
        fields = [
            name for name in [
                '产品标题', '产品分类', '选择分类', '自动识别分类', '产品图片', '营销图片',
                '产品视频', '零售价格', '库存数量', '重量(kg)', '包装尺寸(cm)',
                '物流属性', '商品编码', '发货期限', '运费模板', '服务模板',
                '半托管服务', '报价是否含关税', '不含关税报价', '含关税报价',
                '欧盟责任人', '土耳其责任人', '品牌制造商',
            ]
            if name in body_text
        ]
        return {
            'sections': sections,
            'top_actions': top_actions,
            'fields': fields,
        }

    def _artifact_url(self, path: Path) -> str:
        return '/artifacts/' + path.relative_to(SESSION_DIR.parent).as_posix()

    def _draft_box_action_message(self, action: str, note_text: str | None = None) -> str:
        if action == 'remark':
            return f'已进入采集箱备注动作，目标备注：{note_text or "AI认领"}。'
        if action == 'edit':
            return '已进入采集箱编辑动作，下一步应处理分类引导并打开真实编辑页。'
        return f'已触发采集箱动作：{action}'

    def _is_headless(self) -> bool:
        if os.getenv('DXM_LOGIN_HEADED') == '1':
            return False
        return not bool(os.getenv('DISPLAY'))

    def _mask_secret(self, raw: str) -> str:
        if len(raw) <= 2:
            return '*' * len(raw)
        return raw[0] + '*' * (len(raw) - 2) + raw[-1]
