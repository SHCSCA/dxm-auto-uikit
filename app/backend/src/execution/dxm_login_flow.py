import json
import os
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, TimeoutError, sync_playwright

from src.core.config import SCREENSHOT_DIR, SESSION_DIR
from src.execution.browser_runtime import chrome_launch_options
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
DXM_REFERENCE_TEMPLATE_SECTIONS = (
    'attribute_info',
    'description',
    'freight',
    'service',
    'eu_responsible',
    'manufacturer',
    'compliance',
    'semi_managed',
)
DRAFT_ACTION_SCREENSHOT_MAP = {
    'remark': SCREENSHOT_DIR / 'dianxiaomi_draft_box_remark.png',
    'edit': SCREENSHOT_DIR / 'dianxiaomi_draft_box_edit.png',
}
EDITOR_ACTION_SCREENSHOT_MAP = {
    'fill_editor_required_defaults': SCREENSHOT_DIR / 'dianxiaomi_fill_editor_required_defaults.png',
    'verify_edit_ownership': SCREENSHOT_DIR / 'dianxiaomi_verify_edit_ownership.png',
    'fill_editor_variants': SCREENSHOT_DIR / 'dianxiaomi_fill_editor_variants.png',
    'fill_media_assets': SCREENSHOT_DIR / 'dianxiaomi_fill_media_assets.png',
    'fill_compliance_defaults': SCREENSHOT_DIR / 'dianxiaomi_fill_compliance_defaults.png',
    'enable_semi_managed': SCREENSHOT_DIR / 'dianxiaomi_enable_semi_managed.png',
    'open_semi_managed_page': SCREENSHOT_DIR / 'dianxiaomi_open_semi_managed_page.png',
    'fill_semi_managed_defaults': SCREENSHOT_DIR / 'dianxiaomi_fill_semi_managed_defaults.png',
    'save_only': SCREENSHOT_DIR / 'dianxiaomi_save_only.png',
    'verify_not_published': SCREENSHOT_DIR / 'dianxiaomi_verify_not_published.png',
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
        'url': 'https://www.dianxiaomi.com/web/smt/smtProductList/draft?status=0',
        'label': '速卖通采集箱',
        'message': '已进入速卖通采集箱，可继续查看备注、编辑和发布动作。',
        'next_action': '继续执行添加备注、编辑产品或发布前检查。',
    },
}
WORKFLOW_READY_TERMS = {
    'product': ['产品列表', '标题 / 产品ID', '标题/产品ID', '操作'],
    'data_acquisition': ['数据采集', '搜索内容', '认领', '采集箱'],
    'draft_box': ['店铺账号', '搜索内容', '标题/产品ID', '移入待发布', '编辑'],
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

    def perform_draft_box_action(
        self,
        action: str,
        note_text: str | None = None,
        product_query: str | None = None,
        store_name: str | None = None,
        target_source_urls: list[str] | None = None,
    ) -> dict[str, Any]:
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
            result = self._perform_draft_box_action(
                action,
                note_text=note_text,
                product_query=product_query,
                store_name=store_name,
                target_source_urls=target_source_urls,
            )
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
                'product_query': result.get('product_query'),
                'store_name': result.get('store_name'),
                'target_row_text': result.get('target_row_text'),
                'target_source_urls': result.get('target_source_urls', []),
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
            'product_query': result.get('product_query'),
            'store_name': result.get('store_name'),
            'note_verified': result.get('note_verified'),
            'target_row_text': result.get('target_row_text'),
            'target_source_urls': result.get('target_source_urls', []),
        }
        self._write_state(state)
        self._close_browser_session()
        return state

    def perform_editor_action(
        self,
        action: str,
        defaults: dict[str, Any] | None = None,
        product_query: str | None = None,
        store_name: str | None = None,
    ) -> dict[str, Any]:
        if action not in EDITOR_ACTION_SCREENSHOT_MAP:
            state = self._error_state(
                stage='editor_action_failed',
                label='无效动作',
                message=f'不支持的编辑页动作：{action}',
                next_action='请改为 verify_edit_ownership、fill_editor_required_defaults、fill_editor_variants、fill_media_assets、fill_compliance_defaults、enable_semi_managed、open_semi_managed_page、fill_semi_managed_defaults、save_only 或 verify_not_published。',
            )
            self._write_state(state)
            return state
        try:
            result = self._perform_editor_action(
                action,
                defaults=defaults,
                product_query=product_query,
                store_name=store_name,
            )
        except Exception as exc:
            state = self._error_state(
                stage=f'{action}_failed',
                label='动作失败',
                message=f'执行编辑页动作失败：{exc}',
                next_action='确认编辑页或半托管页仍可访问，且页面结构未变。',
            )
            self._write_state(state)
            self._close_browser_session()
            return state

        state = {
            'stage': result.get('stage') or action,
            'label': result.get('label') or '编辑页动作已执行',
            'message': result.get('message') or f'已执行编辑页动作：{action}',
            'next_action': result.get('next_action') or '继续执行下一步。',
            'requires_user_action': str(result.get('stage')).endswith('_failed'),
            'page_title': result.get('page_title'),
            'page_url': result.get('page_url'),
            'screenshot_url': result.get('screenshot_url'),
            'updated_at': now_iso(),
            'current_action': action,
            'product_query': product_query,
            'store_name': store_name,
            'semi_managed_visible': result.get('semi_managed_visible'),
            'semi_managed_enabled': result.get('semi_managed_enabled'),
            'save_result': result.get('save_result'),
            'fill_result': result.get('fill_result'),
            'source_editor_url': result.get('source_editor_url') or result.get('editor_page_url'),
            'published': result.get('published', False),
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
        wait_result = self._wait_for_page_ready(
            page,
            WORKFLOW_READY_TERMS.get(target, [config['label']]),
            label=config['label'],
            timeout=60000,
        )
        self._dismiss_blocking_modals(page)
        screenshot_path = WORKFLOW_SCREENSHOT_MAP[target]
        page.screenshot(path=str(screenshot_path), full_page=True)
        return {
            'page_title': page.title(),
            'page_url': page.url,
            'screenshot_url': self._artifact_url(screenshot_path),
            'target': target,
            'wait_result': wait_result,
        }

    def _perform_draft_box_action(
        self,
        action: str,
        note_text: str | None = None,
        product_query: str | None = None,
        store_name: str | None = None,
        target_source_urls: list[str] | None = None,
    ) -> dict[str, Any]:
        page = self._ensure_page_with_cookies()
        draft_url = WORKFLOW_TARGETS['draft_box']['url']
        page.goto(draft_url, wait_until='domcontentloaded', timeout=45000)
        self._wait_for_page_ready(
            page,
            WORKFLOW_READY_TERMS['draft_box'],
            label='速卖通采集箱',
            timeout=60000,
        )
        self._dismiss_blocking_modals(page)
        claim_mark = note_text or self._current_claim_mark(product_query=product_query, store_name=store_name)
        self._search_draft_box(page, product_query=product_query, store_name=store_name)
        try:
            row_info = self._find_draft_box_row(
                page,
                product_query,
                store_name=store_name,
                claim_mark=claim_mark,
                target_source_urls=target_source_urls,
            )
        except RuntimeError:
            if not product_query or not store_name:
                raise
            self._search_draft_box(page, product_query=None, store_name=store_name)
            row_info = self._find_draft_box_row(
                page,
                product_query,
                store_name=store_name,
                claim_mark=claim_mark,
                target_source_urls=target_source_urls,
            )

        if action == 'edit':
            editor_page = self._open_editor_from_draft_box(page, row_info=row_info)
            screenshot_path = DRAFT_ACTION_SCREENSHOT_MAP[action]
            editor_page.screenshot(path=str(screenshot_path), full_page=True)
            editor_meta = self._extract_editor_page_meta(editor_page)
            return {
                'page_title': editor_page.title(),
                'page_url': editor_page.url,
                'screenshot_url': self._artifact_url(screenshot_path),
                'action': action,
                'note_text': note_text,
                'product_query': product_query,
                'store_name': store_name,
                'target_row_text': row_info.get('rowText'),
                'target_source_urls': row_info.get('sourceUrls', []),
                'message': '已从采集箱进入真实编辑界面。',
                'editor_sections': editor_meta['sections'],
                'top_actions': editor_meta['top_actions'],
                'detected_fields': editor_meta['fields'],
            }

        note_text = note_text or 'AI认领'
        if note_text in (row_info.get('rowText') or ''):
            note_result = {'verified': True, 'rowText': row_info.get('rowText'), 'already_present': True}
        else:
            note_result = self._add_note_to_draft_row(
                page,
                row_info,
                note_text,
                product_query=product_query,
                store_name=store_name,
            )
        screenshot_path = DRAFT_ACTION_SCREENSHOT_MAP[action]
        page.screenshot(path=str(screenshot_path), full_page=True)
        return {
            'page_title': page.title(),
            'page_url': page.url,
            'screenshot_url': self._artifact_url(screenshot_path),
            'action': action,
            'note_text': note_text,
            'product_query': product_query,
            'store_name': store_name,
            'note_verified': note_result.get('verified'),
            'target_row_text': note_result.get('rowText') or row_info.get('rowText'),
            'target_source_urls': row_info.get('sourceUrls', []),
        }

    def _perform_editor_action(
        self,
        action: str,
        defaults: dict[str, Any] | None = None,
        product_query: str | None = None,
        store_name: str | None = None,
    ) -> dict[str, Any]:
        page = self._ensure_page_with_cookies()
        state = self.get_state()
        if action in {
            'fill_editor_required_defaults',
            'verify_edit_ownership',
            'fill_editor_variants',
            'fill_media_assets',
            'fill_compliance_defaults',
            'enable_semi_managed',
            'open_semi_managed_page',
        }:
            editor_url = state.get('page_url')
            if not editor_url:
                raise RuntimeError('缺少上次编辑页地址')
            page.goto(editor_url, wait_until='domcontentloaded', timeout=45000)
            page.wait_for_timeout(2000)
            ready = self._wait_for_body_text(page, ['基本信息', '半托管服务', '产品信息'])
            if not ready and product_query:
                page = self._open_editor_page_for_product(page, product_query, store_name)
                self._wait_for_body_text(page, ['基本信息', '半托管服务', '产品信息'])
            self._dismiss_blocking_modals(page)
            if action == 'verify_edit_ownership':
                return self._verify_edit_ownership_on_page(
                    page,
                    product_query,
                    store_name,
                    expected_source_urls=state.get('target_source_urls') or [],
                )
            if action == 'fill_editor_required_defaults':
                return self._fill_editor_required_defaults_on_page(page, defaults)
            if action == 'fill_editor_variants':
                return self._fill_editor_variants_on_page(page, defaults)
            if action == 'fill_media_assets':
                return self._fill_media_assets_on_page(page, defaults)
            if action == 'fill_compliance_defaults':
                return self._fill_compliance_defaults_on_page(page, defaults)
            if action == 'enable_semi_managed':
                return self._enable_semi_managed_on_page(page)
            return self._open_semi_managed_page_from_editor(page, defaults)

        semi_url = state.get('page_url')
        if not semi_url:
            raise RuntimeError('缺少上次半托管页地址')
        source_editor_url = state.get('source_editor_url') or state.get('editor_page_url')
        needs_source_reopen = bool(source_editor_url and 'editFromSmt' in str(semi_url) and '?' not in str(semi_url))
        if needs_source_reopen:
            page.goto(source_editor_url, wait_until='domcontentloaded', timeout=45000)
            page.wait_for_timeout(2000)
            self._wait_for_body_text(page, ['基本信息', '半托管服务', '产品信息'])
            self._dismiss_blocking_modals(page)
            open_result = self._open_semi_managed_page_from_editor(page, defaults)
            if str(open_result.get('stage')).endswith('_failed'):
                failed_stage = (
                    'fill_semi_managed_defaults_failed'
                    if action == 'fill_semi_managed_defaults'
                    else f'{action}_failed'
                )
                return {
                    **open_result,
                    'stage': failed_stage,
                    'label': '半托管页重新打开失败',
                    'source_editor_url': source_editor_url,
                }
        elif 'editFromSmt' not in str(page.url or ''):
            page.goto(semi_url, wait_until='domcontentloaded', timeout=45000)
            page.wait_for_timeout(2000)
        self._wait_for_body_text(page, ['半托管', '重量', '包装尺寸', '物流属性'])
        self._dismiss_blocking_modals(page)
        if action == 'fill_semi_managed_defaults':
            result = self._fill_semi_managed_defaults_on_page(page, defaults)
            if source_editor_url and not result.get('source_editor_url'):
                result['source_editor_url'] = source_editor_url
            return result
        if action == 'verify_not_published':
            result = self._verify_not_published_on_page(page, product_query, store_name, prior_save_result=state.get('save_result'))
        else:
            prefill = self._fill_semi_managed_defaults_on_page(page, defaults)
            if str(prefill.get('stage')).endswith('_failed'):
                return {
                    **prefill,
                    'stage': 'save_only_failed',
                    'label': '保存前半托管字段填写失败',
                    'message': prefill.get('message') or '保存前半托管字段未补齐。',
                }
            result = self._save_only_on_page(page)
        if source_editor_url and isinstance(result, dict) and not result.get('source_editor_url'):
            result['source_editor_url'] = source_editor_url
        return result

    def _enable_semi_managed_on_page(self, page: Page) -> dict[str, Any]:
        page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
        page.wait_for_timeout(800)
        target = page.evaluate(r'''() => {
          const norm = (s) => String(s || '').replace(/\s+/g, '').trim();
          const isVisible = (el) => {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const rectOf = (el) => {
            const r = el.getBoundingClientRect();
            return {x:r.x, y:r.y, w:r.width, h:r.height};
          };
          const labels = Array.from(document.querySelectorAll('label,span,div,td,th')).filter(el => {
            return isVisible(el) && norm(el.innerText || el.textContent).includes('半托管服务');
          });
          const label = labels.find(el => norm(el.innerText || el.textContent) === '半托管服务') || labels[0];
          if (!label) return {visible:false, enabled:false};
          const labelRect = rectOf(label);
          const labelY = labelRect.y + labelRect.h / 2;
          const allInputs = Array.from(document.querySelectorAll('input[type="checkbox"]'));
          const inputs = allInputs.filter(isVisible);
          const input = inputs.find(el => {
            const r = rectOf(el);
            const y = r.y + r.h / 2;
            return Math.abs(y - labelY) < 28 && r.x > labelRect.x;
          });
          const textTarget = Array.from(document.querySelectorAll('label,span,div')).filter(isVisible).find(el => {
            const r = rectOf(el);
            const y = r.y + r.h / 2;
            return Math.abs(y - labelY) < 28 && r.x > labelRect.x && norm(el.innerText || el.textContent) === '参与';
          });
          return {
            visible:true,
            enabled: input ? !!input.checked : false,
            inputIndex: input ? allInputs.indexOf(input) : null,
            rect: input ? rectOf(input) : (textTarget ? rectOf(textTarget) : null),
          };
        }''')
        if target.get('visible') and not target.get('enabled'):
            input_index = target.get('inputIndex')
            if input_index is not None:
                try:
                    page.locator('input[type="checkbox"]').nth(int(input_index)).check(timeout=3000, force=True)
                except TimeoutError:
                    if target.get('rect'):
                        self._click_rect_center(page, target['rect'])
            elif target.get('rect'):
                self._click_rect_center(page, target['rect'])
            page.wait_for_timeout(800)
        result = page.evaluate(r'''() => {
          const norm = (s) => String(s || '').replace(/\s+/g, '').trim();
          const isVisible = (el) => {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const rectOf = (el) => {
            const r = el.getBoundingClientRect();
            return {x:r.x, y:r.y, w:r.width, h:r.height};
          };
          const labels = Array.from(document.querySelectorAll('label,span,div,td,th')).filter(el => {
            return isVisible(el) && norm(el.innerText || el.textContent).includes('半托管服务');
          });
          const label = labels.find(el => norm(el.innerText || el.textContent) === '半托管服务') || labels[0];
          if (!label) return {visible:false, enabled:false};
          const labelRect = rectOf(label);
          const labelY = labelRect.y + labelRect.h / 2;
          const input = Array.from(document.querySelectorAll('input[type="checkbox"]')).filter(isVisible).find(el => {
            const r = rectOf(el);
            const y = r.y + r.h / 2;
            return Math.abs(y - labelY) < 28 && r.x > labelRect.x;
          });
          return {visible:true, enabled: input ? !!input.checked : false};
        }''')
        screenshot_path = EDITOR_ACTION_SCREENSHOT_MAP['enable_semi_managed']
        page.screenshot(path=str(screenshot_path), full_page=True)
        visible = bool(result.get('visible'))
        enabled = bool(result.get('enabled'))
        return {
            'stage': 'semi_managed_enabled' if visible and enabled else 'enable_semi_managed_failed',
            'label': '半托管服务已勾选' if visible and enabled else '半托管服务不可用',
            'message': '已确认半托管服务参与状态。' if visible and enabled else '未找到或未能勾选半托管服务。',
            'page_title': page.title(),
            'page_url': page.url,
            'screenshot_url': self._artifact_url(screenshot_path),
            'semi_managed_visible': visible,
            'semi_managed_enabled': enabled,
            'published': False,
        }

    def _open_semi_managed_page_from_editor(self, page: Page, defaults: dict[str, Any] | None = None) -> dict[str, Any]:
        source_editor_url = page.url
        required_result = self._fill_editor_required_defaults_on_page(page, defaults)
        if required_result['stage'].endswith('_failed'):
            return {
                **required_result,
                'stage': 'open_semi_managed_page_failed',
                'label': '普通编辑页必填项未通过',
                'message': required_result.get('message') or '普通编辑页必填项未通过，不能进入半托管信息。',
            }
        variants_result = self._fill_editor_variants_on_page(page, defaults)
        if variants_result['stage'].endswith('_failed'):
            return {
                **variants_result,
                'stage': 'open_semi_managed_page_failed',
                'label': '普通编辑页变体信息未通过',
                'message': variants_result.get('message') or '普通编辑页变体信息未补齐，不能进入半托管信息。',
                'preflight_results': {
                    'required_defaults': required_result,
                    'variants': variants_result,
                },
            }
        eu_media_verified_before_enable = False
        media_result = {'stage': 'media_assets_filled', 'fill_result': {'eu_outer_package_image': {'ok': True, 'skipped': True, 'reason': 'no_config'}}}
        if self._extract_eu_outer_package_filename(defaults or {}):
            media_result = self._fill_media_assets_on_page(page, defaults)
            if media_result['stage'].endswith('_failed'):
                return {
                    **media_result,
                    'stage': 'open_semi_managed_page_failed',
                    'label': '欧盟外包装图未通过',
                    'message': media_result.get('message') or '欧盟外包装图未回填，不能进入半托管信息。',
                }
            eu_media_verified_before_enable = self._media_result_has_verified_eu_outer_package(media_result)
        compliance_result = self._fill_compliance_defaults_on_page(page, defaults)
        if compliance_result['stage'].endswith('_failed'):
            return {
                **compliance_result,
                'stage': 'open_semi_managed_page_failed',
                'label': '普通编辑页合规信息未通过',
                'message': compliance_result.get('message') or '普通编辑页合规信息未补齐，不能进入半托管信息。',
                'preflight_results': {
                    'required_defaults': required_result,
                    'variants': variants_result,
                    'media': media_result,
                    'compliance': compliance_result,
                },
            }
        main_images_result = self._repair_product_main_images_on_page(page)
        if not main_images_result.get('ok'):
            return {
                'stage': 'open_semi_managed_page_failed',
                'label': '普通编辑页主图未通过',
                'message': main_images_result.get('message') or '主图存在无效图片，不能进入半托管信息。',
                'page_title': page.title(),
                'page_url': page.url,
                'fill_result': main_images_result,
                'preflight_results': {
                    'required_defaults': required_result,
                    'variants': variants_result,
                    'media': media_result,
                    'compliance': compliance_result,
                    'main_images': main_images_result,
                },
                'published': False,
            }
        customs_preflight = (required_result.get('fill_result') or {}).get('customs_supervision') or {}
        customs_after_repairs = customs_preflight
        if customs_preflight and not customs_preflight.get('ok'):
            flattened_defaults = self._flatten_editor_defaults(defaults or {})
            customs_after_repairs = self._fill_customs_supervision_attribute(
                page,
                flattened_defaults.get('customs_product_name_priorities') or ['钥匙扣', 'keychain'],
            )
            if not customs_after_repairs.get('ok'):
                return {
                    'stage': 'open_semi_managed_page_failed',
                    'label': '普通编辑页海关监管属性未通过',
                    'message': customs_after_repairs.get('reason') or '海关监管属性未补齐，不能进入半托管信息。',
                    'page_title': page.title(),
                    'page_url': page.url,
                    'fill_result': customs_after_repairs,
                    'preflight_results': {
                        'required_defaults': required_result,
                        'variants': variants_result,
                        'media': media_result,
                        'compliance': compliance_result,
                        'main_images': main_images_result,
                        'customs_supervision_after_repairs': customs_after_repairs,
                    },
                    'published': False,
                }
        enable_result = self._enable_semi_managed_on_page(page)
        if enable_result['stage'].endswith('_failed'):
            enable_result['stage'] = 'open_semi_managed_page_failed'
            return enable_result
        if self._extract_eu_outer_package_filename(defaults or {}):
            media_result = self._fill_media_assets_on_page(page, defaults)
            deferred_required = any(
                item.get('deferred') and self._is_eu_outer_package_slot(item.get('label'), item.get('slot_key'))
                for item in media_result.get('fill_result', {}).get('image_slots', [])
            )
            if media_result['stage'].endswith('_failed') or (deferred_required and not eu_media_verified_before_enable):
                return {
                    **media_result,
                    'stage': 'open_semi_managed_page_failed',
                    'label': '欧盟外包装图未通过',
                    'message': media_result.get('message') or '欧盟外包装图未回填，不能进入半托管信息。',
                }
        clicked = page.evaluate(r'''() => {
          const norm = (s) => String(s || '').replace(/\s+/g, '').trim();
          const btn = Array.from(document.querySelectorAll('button,a,span,div')).find(el => norm(el.innerText || el.textContent) === '编辑半托管信息');
          if (!btn) return false;
          btn.dispatchEvent(new MouseEvent('click', {bubbles:true}));
          return true;
        }''')
        if not clicked:
            return {
                'stage': 'open_semi_managed_page_failed',
                'label': '半托管编辑入口缺失',
                'message': '未找到“编辑半托管信息”入口。',
                'page_title': page.title(),
                'page_url': page.url,
                'screenshot_url': enable_result.get('screenshot_url'),
                'published': False,
            }
        page.wait_for_timeout(2500)
        screenshot_path = EDITOR_ACTION_SCREENSHOT_MAP['open_semi_managed_page']
        page_state = self._semi_managed_page_state(page)
        for _ in range(10):
            if page_state.get('blocked') or page_state.get('is_semi_page'):
                break
            page.wait_for_timeout(1500)
            page_state = self._semi_managed_page_state(page)
        page.screenshot(path=str(screenshot_path), full_page=True)
        if page_state.get('blocked'):
            return {
                'stage': 'open_semi_managed_page_failed',
                'label': '半托管编辑入口被产品信息错误阻断',
                'message': page_state.get('message') or '产品信息中有错误，请先补齐普通编辑页字段。',
                'page_title': page.title(),
                'page_url': page.url,
                'screenshot_url': self._artifact_url(screenshot_path),
                'published': False,
            }
        if not page_state.get('is_semi_page'):
            return {
                'stage': 'open_semi_managed_page_failed',
                'label': '半托管编辑页未打开',
                'message': '点击“编辑半托管信息”后仍停留在普通编辑页。',
                'page_title': page.title(),
                'page_url': page.url,
                'screenshot_url': self._artifact_url(screenshot_path),
                'published': False,
            }
        return {
            'stage': 'semi_managed_page',
            'label': '已进入半托管编辑页',
            'message': '已打开半托管信息编辑页。',
            'page_title': page.title(),
            'page_url': page.url,
            'screenshot_url': self._artifact_url(screenshot_path),
            'source_editor_url': source_editor_url,
            'published': False,
        }

    def _repair_product_main_images_on_page(self, page: Page) -> dict[str, Any]:
        self._dismiss_blocking_modals(page)
        before = self._product_main_images_state(page)
        if not before.get('found'):
            return {
                'ok': False,
                'message': before.get('message') or '未找到普通编辑页主图模块。',
                'before': before,
                'after': before,
            }
        deleted_invalid = []
        for _ in range(10):
            delete_target = page.evaluate(r'''() => {
              const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
              const rectOf = (el) => {
                const r = el.getBoundingClientRect();
                return {x:r.x, y:r.y, w:r.width, h:r.height};
              };
              const parseDims = (text, img) => {
                const m = String(text || '').match(/(\d+)\s*[xX×]\s*(\d+)/);
                if (m) return {width:Number(m[1]), height:Number(m[2])};
                return {width:Number(img?.naturalWidth || 0), height:Number(img?.naturalHeight || 0)};
              };
              const root = document.querySelector('.productMainImgModule');
              if (!root) return null;
              root.scrollIntoView({block:'center', inline:'nearest'});
              const items = Array.from(root.querySelectorAll('.single-image.img-item, .single-image'));
              for (let index = 0; index < items.length; index += 1) {
                const item = items[index];
                const text = textOf(item);
                const img = item.querySelector('img');
                const dims = parseDims(text, img);
                const src = img?.getAttribute('src') || '';
                const valid = dims.width > 0 && dims.height > 0 && !/addImg|placeholder/i.test(src);
                if (valid) continue;
                const del = item.querySelector('.icon_delete, [class*="icon_delete"], [class*="delete"]');
                if (del) return {first_invalid_delete:true, index, text, src, dims, rect:rectOf(del)};
              }
              return null;
            }''')
            if not delete_target:
                break
            self._click_rect_center(page, delete_target['rect'])
            deleted_invalid.append({key: delete_target.get(key) for key in ('index', 'text', 'src', 'dims')})
            page.wait_for_timeout(800)
            confirm = self._click_safe_modal_button(page, ['确定', '确认', '删除'])
            if confirm.get('ok'):
                page.wait_for_timeout(800)
            self._dismiss_blocking_modals(page)

        if before.get('selected_valid_count', 0) < 1 and before.get('valid_count', 0) < 1:
            return {
                'ok': False,
                'message': '主图模块没有可用的有效图片。',
                'before': before,
                'after': before,
            }
        action = page.evaluate(r'''() => {
          const parseDims = (text, img) => {
            const m = String(text || '').match(/(\d+)\s*[xX×]\s*(\d+)/);
            if (m) return {width:Number(m[1]), height:Number(m[2])};
            return {width:Number(img?.naturalWidth || 0), height:Number(img?.naturalHeight || 0)};
          };
          const describe = (item, index) => {
            const input = item.querySelector('input[type="checkbox"]');
            const img = item.querySelector('img');
            const text = String(item.innerText || item.textContent || '').replace(/\s+/g, ' ').trim();
            const dims = parseDims(text, img);
            const checked = Boolean((input && input.checked) || item.classList.contains('checked'));
            const src = img?.getAttribute('src') || '';
            const valid = dims.width > 0 && dims.height > 0 && !/addImg|placeholder/i.test(src);
            return {item, input, index, text, dims, checked, valid, src};
          };
          const root = document.querySelector('.productMainImgModule');
          if (!root) return {clicked_invalid: [], clicked_valid: [], found: false};
          const items = Array.from(root.querySelectorAll('.single-image.img-item, .single-image'))
            .map(describe)
            .filter(info => info.text.includes(' X ') || info.text.includes('×') || info.src);
          const clickedInvalid = [];
          for (const info of items) {
            if (info.checked && !info.valid && info.input) {
              info.input.click();
              clickedInvalid.push({index: info.index, text: info.text, dims: info.dims, src: info.src});
            }
          }
          const refreshed = items.map(info => describe(info.item, info.index));
          const validCount = refreshed.filter(info => info.valid).length;
          const targetSelectedValidCount = Math.min(2, Math.max(1, validCount));
          let selectedValidCount = refreshed.filter(info => info.checked && info.valid).length;
          const clickedValid = [];
          for (const info of refreshed) {
            if (selectedValidCount >= targetSelectedValidCount) break;
            if (!info.checked && info.valid && info.input) {
              info.input.click();
              clickedValid.push({index: info.index, text: info.text, dims: info.dims, src: info.src});
              selectedValidCount += 1;
            }
          }
          return {found: true, clicked_invalid: clickedInvalid, clicked_valid: clickedValid};
        }''')
        page.wait_for_timeout(800)
        after = self._product_main_images_state(page)
        ok = bool(after.get('found')) and after.get('selected_invalid_count', 0) == 0 and after.get('selected_valid_count', 0) >= 1
        if ok:
            message = '主图已修复：已取消无效 0 X 0 图片，并保留有效主图。'
        else:
            message = '主图仍存在无效已选图片，不能进入半托管信息。'
        return {
            'ok': ok,
            'message': message,
            'before': before,
            'deleted_invalid': deleted_invalid,
            'action': action,
            'after': after,
        }

    def _product_main_images_state(self, page: Page) -> dict[str, Any]:
        return page.evaluate(r'''() => {
          const parseDims = (text, img) => {
            const m = String(text || '').match(/(\d+)\s*[xX×]\s*(\d+)/);
            if (m) return {width:Number(m[1]), height:Number(m[2])};
            return {width:Number(img?.naturalWidth || 0), height:Number(img?.naturalHeight || 0)};
          };
          const root = document.querySelector('.productMainImgModule');
          if (!root) {
            return {found:false, message:'未找到普通编辑页主图模块。', images:[], total:0, valid_count:0, selected_valid_count:0, selected_invalid_count:0};
          }
          const images = Array.from(root.querySelectorAll('.single-image.img-item, .single-image')).map((item, index) => {
            const input = item.querySelector('input[type="checkbox"]');
            const img = item.querySelector('img');
            const text = String(item.innerText || item.textContent || '').replace(/\s+/g, ' ').trim();
            const dims = parseDims(text, img);
            const checked = Boolean((input && input.checked) || item.classList.contains('checked'));
            const src = img?.getAttribute('src') || '';
            const valid = dims.width > 0 && dims.height > 0 && !/addImg|placeholder/i.test(src);
            return {index, text, checked, valid, width:dims.width, height:dims.height, src};
          }).filter(item => item.text.includes(' X ') || item.text.includes('×') || item.src);
          const selectedInvalid = images.filter(item => item.checked && !item.valid);
          const selectedValid = images.filter(item => item.checked && item.valid);
          const validImages = images.filter(item => item.valid);
          return {
            found: true,
            total: images.length,
            valid_count: validImages.length,
            selected_valid_count: selectedValid.length,
            selected_invalid_count: selectedInvalid.length,
            selected_invalid: selectedInvalid,
            selected_valid: selectedValid,
            images,
          };
        }''')

    def _media_result_has_verified_eu_outer_package(self, media_result: dict[str, Any]) -> bool:
        fill_result = media_result.get('fill_result') if isinstance(media_result, dict) else {}
        if not isinstance(fill_result, dict):
            return False
        eu_result = fill_result.get('eu_outer_package_image')
        if isinstance(eu_result, dict) and eu_result.get('ok') and not eu_result.get('deferred'):
            return True
        image_slots = fill_result.get('image_slots')
        if not isinstance(image_slots, list):
            return False
        return any(
            isinstance(item, dict)
            and self._is_eu_outer_package_slot(item.get('label'), item.get('slot_key'))
            and item.get('ok')
            and not item.get('deferred')
            for item in image_slots
        )

    def _verify_edit_ownership_on_page(
        self,
        page: Page,
        product_query: str | None = None,
        store_name: str | None = None,
        expected_source_urls: list[str] | None = None,
    ) -> dict[str, Any]:
        result = page.evaluate(r'''({productQuery, storeName, expectedSourceUrls}) => {
          const body = String(document.body ? document.body.innerText || document.body.textContent || '' : '');
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const fieldValues = Array.from(document.querySelectorAll('input,textarea,select'))
            .filter(visible)
            .map(el => String(el.value || el.getAttribute('value') || '').trim())
            .filter(Boolean)
            .join('\n');
          const combined = `${body}\n${fieldValues}`;
          const compact = combined.replace(/\s+/g, '');
          const query = String(productQuery || '').trim();
          const store = String(storeName || '').trim();
          const expectedUrls = Array.isArray(expectedSourceUrls) ? expectedSourceUrls.map(String).filter(Boolean) : [];
          const extractGoodsId = (url) => {
            const match = String(url || '').match(/[?&]goods_id=([^&#]+)/);
            return match ? match[1] : '';
          };
          const currentUrls = Array.from(document.querySelectorAll('a[href],input,textarea'))
            .map(el => String(el.href || el.value || el.getAttribute('value') || ''))
            .filter(Boolean);
          const expectedGoodsIds = expectedUrls.map(extractGoodsId).filter(Boolean);
          const sourceMatched = expectedUrls.some(url => combined.includes(url))
            || expectedGoodsIds.some(id => currentUrls.some(url => url.includes(id)));
          const queryMatched = query ? combined.includes(query) || compact.includes(query.replace(/\s+/g, '')) : false;
          const storeMatched = store ? combined.includes(store) || compact.includes(store.replace(/\s+/g, '')) : true;
          const hasEditorSignals = compact.includes('基本信息') && compact.includes('产品信息');
          return {
            ok: Boolean((queryMatched || sourceMatched) && storeMatched && hasEditorSignals),
            product_query: query,
            store_name: store,
            query_matched: queryMatched,
            source_matched: sourceMatched,
            expected_source_urls: expectedUrls,
            matched_goods_ids: expectedGoodsIds.filter(id => currentUrls.some(url => url.includes(id))).slice(0, 3),
            store_matched: storeMatched,
            has_editor_signals: hasEditorSignals,
            reason: query || expectedUrls.length ? null : '缺少目标商品标识，禁止继续编辑',
            body_excerpt: body.slice(0, 500),
            matched_field_values: fieldValues.split('\n').filter(value => query && value.includes(query)).slice(0, 3),
          };
        }''', {'productQuery': product_query, 'storeName': store_name, 'expectedSourceUrls': expected_source_urls or []})
        screenshot_path = EDITOR_ACTION_SCREENSHOT_MAP['verify_edit_ownership']
        page.screenshot(path=str(screenshot_path), full_page=True)
        ok = bool(result.get('ok'))
        return {
            'stage': 'edit_ownership_verified' if ok else 'verify_edit_ownership_failed',
            'label': '编辑页归属已校验' if ok else '编辑页归属校验失败',
            'message': '编辑页商品与当前任务匹配。' if ok else result.get('reason') or '编辑页缺少当前任务商品标识。',
            'page_title': page.title(),
            'page_url': page.url,
            'screenshot_url': self._artifact_url(screenshot_path),
            'fill_result': result,
            'product_query': product_query,
            'store_name': store_name,
            'published': False,
        }

    def _fill_editor_required_defaults_on_page(self, page: Page, defaults: dict[str, Any] | None = None) -> dict[str, Any]:
        values: dict[str, Any] = {
            'category_keyword': '立牌',
            'category_match': 'ACG Stand',
            'title': 'Hazbin Hotel Alastor Acrylic Stand Keychain Colorful Bag Pendant Card',
            'custom_attributes': [
                ['Material', 'Acrylic'],
                ['Theme', 'Anime'],
                ['Product Type', 'Acrylic Stand'],
                ['Feature', 'Display Stand'],
                ['Style', 'Cartoon'],
            ],
            'declared_value': '1',
            'stock': '200',
            'weight': '0.03',
            'length': '10',
            'width': '10',
            'height': '2',
            'sku_code': '610274761685-DK-AD-10CM',
            'delivery_days': '7',
            'gross_weight': '0.03',
            'freight_template_priorities': ['40g普货包裹', '80g普货包裹', '100g普货包裹', '普货包裹'],
            'service_template_priorities': ['Service Template for New Sellers'],
            'eu_responsible_priorities': ['Jacqueiline Marti'],
            'manufacturer_priorities': ['jiyang county thunder', 'Jiyang County thunder'],
            'customs_product_name_priorities': ['钥匙扣', 'keychain'],
        }
        values.update(self._flatten_editor_defaults(defaults or {}))

        category = self._select_editor_category(
            page,
            keyword=str(values['category_keyword']),
            match_text=str(values['category_match']),
        )
        page.wait_for_timeout(1000)
        self._dismiss_blocking_modals(page)
        if not category.get('ok'):
            screenshot_path = EDITOR_ACTION_SCREENSHOT_MAP['fill_editor_required_defaults']
            page.screenshot(path=str(screenshot_path), full_page=True)
            return {
                'stage': 'fill_editor_required_defaults_failed',
                'label': '普通编辑页仍有必填项缺失',
                'message': '普通编辑页缺少字段：category',
                'page_title': page.title(),
                'page_url': page.url,
                'screenshot_url': self._artifact_url(screenshot_path),
                'fill_result': {'category': category, 'missing': ['category']},
                'published': False,
            }
        dxm_reference_template_results = self._apply_dxm_reference_templates_on_page(page, values)
        reference_missing = self._missing_required_reference_template_results(dxm_reference_template_results)
        if reference_missing:
            screenshot_path = EDITOR_ACTION_SCREENSHOT_MAP['fill_editor_required_defaults']
            page.screenshot(path=str(screenshot_path), full_page=True)
            return {
                'stage': 'fill_editor_required_defaults_failed',
                'label': '店小秘引用模板失败',
                'message': '店小秘引用模板缺失或未命中：' + ', '.join(reference_missing),
                'page_title': page.title(),
                'page_url': page.url,
                'screenshot_url': self._artifact_url(screenshot_path),
                'fill_result': {
                    'category': category,
                    'dxm_reference_template_results': dxm_reference_template_results,
                    'missing': reference_missing,
                },
                'dxm_reference_template_results': dxm_reference_template_results,
                'published': False,
            }
        field_result = page.evaluate(r'''(values) => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const norm = (s) => String(s || '').replace(/\s+/g, '').trim();
          const hasChinese = (s) => /[\u3400-\u9fff]/.test(String(s || ''));
          const rectOf = (el) => {
            const r = el.getBoundingClientRect();
            return {x:r.x, y:r.y, w:r.width, h:r.height};
          };
          const docY = (el) => {
            const r = el.getBoundingClientRect();
            return r.y + window.scrollY;
          };
          const setValue = (el, value) => {
            if (!el || el.disabled) return false;
            const proto = el.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
            const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
            if (setter) setter.call(el, value);
            else el.value = value;
            el.dispatchEvent(new Event('input', {bubbles:true}));
            el.dispatchEvent(new Event('change', {bubbles:true}));
            el.dispatchEvent(new Event('blur', {bubbles:true}));
            return true;
          };
          const visibleInputs = () => Array.from(document.querySelectorAll('input,textarea')).filter(visible);
          const setByPlaceholder = (placeholder, value, occurrence = 0) => {
            const matches = visibleInputs().filter(el => String(el.placeholder || '') === placeholder && !el.disabled);
            return setValue(matches[occurrence], value);
          };
          const setById = (id, value) => setValue(document.getElementById(id), value);
          const inputsNearLabel = (labelText, yTolerance = 46) => {
            const labels = Array.from(document.querySelectorAll('label,span,div,td,th')).filter(visible).filter(el => norm(el.innerText || el.textContent).includes(norm(labelText)));
            if (!labels.length) return [];
            const inputs = visibleInputs().filter(el => !el.disabled);
            const candidates = [];
            for (const label of labels) {
              const lr = rectOf(label);
              const ly = docY(label) + lr.h / 2;
              const rowInputs = inputs.filter(el => {
                const r = rectOf(el);
                const y = docY(el) + r.h / 2;
                return Math.abs(y - ly) < yTolerance && r.x > lr.x - 10;
              }).sort((a, b) => rectOf(a).x - rectOf(b).x);
              candidates.push(...rowInputs);
            }
            return Array.from(new Set(candidates));
          };
          const textInputs = visibleInputs().filter(el => el.tagName === 'INPUT' && el.type === 'text' && !el.disabled);
          const titleInput = inputsNearLabel('产品标题', 56)[0] || textInputs.find(el => hasChinese(el.value) && rectOf(el).w > 400 && docY(el) < 800) || textInputs.find(el => {
            const r = rectOf(el);
            return r.width > 500 && docY(el) < 800;
          });
          const title = setValue(titleInput, values.title);
          const attrNames = visibleInputs().filter(el => String(el.placeholder || '').includes('属性名'));
          const attrValues = visibleInputs().filter(el => String(el.placeholder || '').includes('属性值'));
          const customAttributes = Array.isArray(values.custom_attributes) ? values.custom_attributes : [];
          const attrs = customAttributes.map((pair, idx) => {
            return {
              name: setValue(attrNames[idx], pair[0]),
              value: setValue(attrValues[idx], pair[1]),
            };
          });
          const textByRect = textInputs.slice().sort((a, b) => docY(a) - docY(b) || rectOf(a).x - rectOf(b).x);
          const skuCandidate = inputsNearLabel('商品编码', 56)[0] || textByRect.find(el => {
            const r = rectOf(el);
            const y = docY(el);
            return y > 2300 && r.width >= 200 && !String(el.placeholder || '').includes('发货') && (hasChinese(el.value) || String(el.value || '').length > 50);
          });
          const deliveryCandidate = inputsNearLabel('发货期限', 56)[0];
          const grossDimensionInputs = inputsNearLabel('包装后尺寸', 56).filter(el => {
            const r = rectOf(el);
            return r.width >= 50 && r.width <= 140;
          });
          const all = {
            title,
            attr_count: attrs.filter(x => x.name && x.value).length,
            declared_value: setByPlaceholder('请输入货值', values.declared_value),
            stock: setByPlaceholder('请输入库存数量', values.stock),
            weight: setByPlaceholder('请输入重量', values.weight),
            length: setByPlaceholder('长', values.length),
            width: setByPlaceholder('宽', values.width),
            height: setByPlaceholder('高', values.height),
            sku_code: setValue(skuCandidate, values.sku_code),
            delivery_days: setValue(deliveryCandidate, values.delivery_days) || setByPlaceholder('请输入发货期限', values.delivery_days),
            gross_weight: setById('form_item_grossWeight', values.gross_weight),
            gross_length: setValue(grossDimensionInputs[0], values.length),
            gross_width: setValue(grossDimensionInputs[1], values.width),
            gross_height: setValue(grossDimensionInputs[2], values.height),
          };
          const remainingChineseAttrs = visibleInputs()
            .filter(el => String(el.placeholder || '').includes('属性'))
            .map(el => el.value || '')
            .filter(hasChinese);
          return {...all, remaining_chinese_attributes: remainingChineseAttrs};
        }''', values)
        field_result.update({
            'title': self._fill_text_inputs_near_label(page, '产品标题', [str(values['title'])]).get('ok') or field_result.get('title'),
            'sku_code': self._fill_text_inputs_near_label(page, '商品编码', [str(values['sku_code'])]).get('ok') or field_result.get('sku_code'),
            'delivery_days': self._fill_text_inputs_near_label(page, '发货期限', [str(values['delivery_days'])]).get('ok') or field_result.get('delivery_days'),
        })
        packaging = self._fill_packaging_info(
            page,
            gross_weight=str(values['gross_weight']),
            dimensions=[str(values['length']), str(values['width']), str(values['height'])],
        )
        if packaging.get('ok'):
            field_result.update({
                'gross_weight': True,
                'gross_length': True,
                'gross_width': True,
                'gross_height': True,
            })

        reference_templates = dxm_reference_template_results.get('attribute_info') or {'ok': True, 'skipped': True}
        category_attributes = self._fill_category_required_attributes(page)
        self._dismiss_blocking_modals(page)
        original_box = self._choose_ant_select_near_label(page, '是否原箱', ['否'])
        logistics = self._check_choice_by_text(page, '普货')
        tax = self._check_choice_by_text(page, '不含关税报价')
        freight = dxm_reference_template_results.get('freight') or self._choose_ant_select_near_label(page, '运费模板', values.get('freight_template_priorities') or [])
        service = dxm_reference_template_results.get('service') or self._choose_ant_select_near_label(page, '服务模板', values.get('service_template_priorities') or [])
        customs = self._fill_customs_supervision_attribute(page, values.get('customs_product_name_priorities') or [])
        eu_responsible = dxm_reference_template_results.get('eu_responsible') or self._choose_ant_select_near_label(page, '欧盟责任人', values.get('eu_responsible_priorities') or [])
        manufacturer = dxm_reference_template_results.get('manufacturer') or self._choose_ant_select_near_label(page, '品牌制造商', values.get('manufacturer_priorities') or [])

        page.wait_for_timeout(1200)
        self._dismiss_blocking_modals(page)
        validation = self._editor_required_defaults_state(page)
        screenshot_path = EDITOR_ACTION_SCREENSHOT_MAP['fill_editor_required_defaults']
        page.screenshot(path=str(screenshot_path), full_page=True)
        missing = list(validation.get('missing') or [])
        field_missing_map = {
            'english_title': 'title',
            'delivery_days': 'delivery_days',
        }
        missing = [
            item for item in missing
            if not (item in field_missing_map and field_result.get(field_missing_map[item]))
        ]
        downstream_owned_missing = {
            'declared_value',
            'stock',
            'weight',
            'customs_supervision',
        }
        missing = [item for item in missing if item not in downstream_owned_missing]
        required_selects = {
            'category': category,
            'category_attributes': category_attributes,
            'tax_quote': tax,
            'freight_template': freight,
            'service_template': service,
        }
        missing.extend(name for name, result in required_selects.items() if not result.get('ok'))
        missing.extend(self._missing_required_reference_template_results(dxm_reference_template_results))
        if field_result.get('remaining_chinese_attributes'):
            missing.append('custom_attributes_english')
        missing = sorted(set(missing))
        optional_unfilled = [
            name for name, result in {
                'eu_responsible': eu_responsible,
                'manufacturer': manufacturer,
            }.items()
            if not result.get('ok')
        ]
        return {
            'stage': 'editor_required_defaults_filled' if not missing else 'fill_editor_required_defaults_failed',
            'label': '普通编辑页必填项已填写' if not missing else '普通编辑页仍有必填项缺失',
            'message': '已填写普通编辑页保守默认值。' if not missing else f'普通编辑页缺少字段：{", ".join(missing)}',
            'page_title': page.title(),
            'page_url': page.url,
            'screenshot_url': self._artifact_url(screenshot_path),
            'fill_result': {
                'category': category,
                'reference_templates': reference_templates,
                'dxm_reference_template_results': dxm_reference_template_results,
                'category_attributes': category_attributes,
                'fields': field_result,
                'original_box': original_box,
                'logistics_attribute': logistics,
                'tax_quote': tax,
                'freight_template': freight,
                'service_template': service,
                'customs_supervision': customs,
                'eu_responsible': eu_responsible,
                'manufacturer': manufacturer,
                'missing': missing,
                'optional_unfilled': optional_unfilled,
            },
            'dxm_reference_template_results': dxm_reference_template_results,
            'published': False,
        }

    def _fill_editor_variants_on_page(self, page: Page, defaults: dict[str, Any] | None = None) -> dict[str, Any]:
        values: dict[str, Any] = {
            'declared_value': '1',
            'stock': '200',
            'weight': '0.03',
            'length': '10',
            'width': '10',
            'height': '2',
            'logistics_attribute': '普货',
        }
        values.update(self._flatten_editor_defaults(defaults or {}))
        result = page.evaluate(r'''(values) => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
          const setNativeValue = (target, value) => {
            if (!target || target.disabled) return false;
            const proto = target.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
            const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
            if (setter) setter.call(target, value);
            else target.value = value;
            target.dispatchEvent(new Event('input', {bubbles:true}));
            target.dispatchEvent(new Event('change', {bubbles:true}));
            target.dispatchEvent(new Event('blur', {bubbles:true}));
            return true;
          };
          const tables = Array.from(document.querySelectorAll('table,.vxe-table,.ant-table,div'))
            .filter(visible)
            .filter(el => {
              const text = textOf(el);
              return text.includes('零售价') && text.includes('货值') && text.includes('库存') && text.includes('物流属性');
            });
          const scope = tables.sort((a, b) => textOf(a).length - textOf(b).length)[0] || document;
          const inputs = Array.from(scope.querySelectorAll('input,textarea')).filter(visible).filter(el => !el.disabled);
          const fillByPlaceholder = (needle, value) => {
            const matched = inputs.filter(el => String(el.placeholder || '').includes(needle));
            return {
              matched: matched.length,
              filled: matched.filter(el => setNativeValue(el, String(value))).length,
            };
          };
          const declaredValue = fillByPlaceholder('货值', values.declared_value);
          const stock = fillByPlaceholder('库存', values.stock);
          const weight = fillByPlaceholder('重量', values.weight);
          const length = fillByPlaceholder('长', values.length);
          const width = fillByPlaceholder('宽', values.width);
          const height = fillByPlaceholder('高', values.height);
          const plainGoodsVisible = textOf(scope).includes(values.logistics_attribute || '普货');
          const logisticsIconCount = scope === document ? 0 : Array.from(scope.querySelectorAll('tbody tr i.icon_edit2, tbody tr .icon_edit2'))
            .filter(visible)
            .map(el => el.closest('i,.icon_edit2') || el)
            .filter((el, idx, arr) => arr.indexOf(el) === idx)
            .length;
          const missing = [];
          if (!declaredValue.filled) missing.push('declared_value');
          if (!stock.filled) missing.push('stock');
          if (!weight.filled) missing.push('weight');
          if (!length.filled || !width.filled || !height.filled) missing.push('dimensions');
          if (!plainGoodsVisible && !logisticsIconCount) missing.push('logistics_attribute');
          return {
            ok: missing.length === 0,
            missing,
            declared_value: declaredValue,
            stock,
            weight,
            length,
            width,
            height,
            logistics_attribute_visible: plainGoodsVisible,
            logistics_icon_count: logisticsIconCount,
            variant_scope_found: scope !== document,
          };
        }''', values)
        missing = list(result.get('missing') or [])
        if result.get('variant_scope_found') and int(result.get('logistics_icon_count') or 0) > 0:
            logistics_result = self._fill_editor_variant_logistics_attribute(page, str(values.get('logistics_attribute') or '普货'))
            result['logistics_attribute_detail'] = logistics_result
            if logistics_result.get('ok'):
                result['missing'] = [item for item in missing if item != 'logistics_attribute']
            else:
                result['missing'] = sorted(set(missing + ['logistics_attribute']))
            result['ok'] = not result['missing']
        elif 'logistics_attribute' in missing and result.get('variant_scope_found'):
            logistics_result = self._fill_semi_logistics_attribute(page, str(values.get('logistics_attribute') or '普货'))
            result['logistics_attribute_detail'] = logistics_result
            if logistics_result.get('ok'):
                result['missing'] = [item for item in missing if item != 'logistics_attribute']
                result['ok'] = not result['missing']
        screenshot_path = EDITOR_ACTION_SCREENSHOT_MAP['fill_editor_variants']
        page.screenshot(path=str(screenshot_path), full_page=True)
        ok = bool(result.get('ok'))
        return {
            'stage': 'editor_variants_filled' if ok else 'fill_editor_variants_failed',
            'label': '普通变种表格已填写' if ok else '普通变种表格填写失败',
            'message': '已按配置填写普通变种表格。' if ok else f"普通变种表格缺少字段：{', '.join(result.get('missing') or [])}",
            'page_title': page.title(),
            'page_url': page.url,
            'screenshot_url': self._artifact_url(screenshot_path),
            'fill_result': result,
            'published': False,
        }

    def _fill_editor_variant_logistics_attribute(self, page: Page, value: str) -> dict[str, Any]:
        normalized = value.replace(' ', '').lower()
        plain_goods = normalized in {'普货', '普通货', '普通', 'none', 'no', '无'}
        icons = page.evaluate(r'''() => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const rectOf = (el) => {
            const r = el.getBoundingClientRect();
            return {x:r.x, y:r.y, w:r.width, h:r.height};
          };
          const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
          const tables = Array.from(document.querySelectorAll('table,.vxe-table,.ant-table,div'))
            .filter(visible)
            .filter(el => {
              const text = textOf(el);
              return text.includes('零售价') && text.includes('货值') && text.includes('库存') && text.includes('物流属性');
            });
          const scope = tables.sort((a, b) => textOf(a).length - textOf(b).length)[0];
          if (!scope) return [];
          return Array.from(scope.querySelectorAll('tbody tr i.icon_edit2, tbody tr .icon_edit2'))
            .filter(visible)
            .map(el => el.closest('i,.icon_edit2') || el)
            .filter((el, idx, arr) => arr.indexOf(el) === idx)
            .map((el, index) => ({index, rect:rectOf(el), row_text:textOf(el.closest('tr') || el).slice(0, 160)}))
            .sort((a, b) => a.rect.y - b.rect.y || a.rect.x - b.rect.x);
        }''')
        if not icons:
            return {'ok': False, 'reason': '未找到普通变体物流属性编辑入口'}

        modal_results = []
        for item in icons:
            opened = page.evaluate(r'''(targetIndex) => {
              const visible = (el) => {
                const r = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
              };
              const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
              const tables = Array.from(document.querySelectorAll('table,.vxe-table,.ant-table,div'))
                .filter(visible)
                .filter(el => {
                  const text = textOf(el);
                  return text.includes('零售价') && text.includes('货值') && text.includes('库存') && text.includes('物流属性');
                });
              const scope = tables.sort((a, b) => textOf(a).length - textOf(b).length)[0];
              if (!scope) return {ok:false, reason:'未找到普通变体表格'};
              const icons = Array.from(scope.querySelectorAll('tbody tr i.icon_edit2, tbody tr .icon_edit2'))
                .filter(visible)
                .map(el => el.closest('i,.icon_edit2') || el)
                .filter((el, idx, arr) => arr.indexOf(el) === idx)
                .sort((a, b) => {
                  const ar = a.getBoundingClientRect();
                  const br = b.getBoundingClientRect();
                  return ar.y - br.y || ar.x - br.x;
                });
              const icon = icons[targetIndex];
              if (!icon) return {ok:false, reason:'普通变体物流属性编辑入口索引失效'};
              icon.scrollIntoView({block:'center', inline:'center'});
              icon.click();
              return {ok:true, row_text:textOf(icon.closest('tr') || icon).slice(0, 160)};
            }''', item.get('index'))
            if not opened.get('ok'):
                modal_results.append({**opened, 'row_text': item.get('row_text')})
                continue
            page.wait_for_timeout(800)
            state = page.evaluate(r'''({value, plainGoods}) => {
              const visible = (el) => {
                const r = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
              };
              const norm = (s) => String(s || '').replace(/\s+/g, '').trim();
              const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
              const rectOf = (el) => {
                const r = el.getBoundingClientRect();
                return {x:r.x, y:r.y, w:r.width, h:r.height};
              };
              const modal = Array.from(document.querySelectorAll('.ant-modal, .ant-modal-wrap, [role="dialog"]'))
                .filter(visible)
                .find(el => textOf(el).includes('物流属性') && textOf(el).includes('确定'));
              if (!modal) return {ok:false, reason:'普通变体物流属性弹窗未打开'};
              const labels = Array.from(modal.querySelectorAll('label')).filter(visible);
              const selected = [];
              for (const label of labels) {
                const input = label.querySelector('input[type="checkbox"],input[type="radio"]');
                const text = norm(label.innerText || label.textContent);
                if (!input) continue;
                if (text.includes(norm(value)) && !input.checked) {
                  label.dispatchEvent(new MouseEvent('click', {bubbles:true}));
                  selected.push(text);
                }
              }
              const hasRequested = labels.some(label => norm(label.innerText || label.textContent).includes(norm(value)));
              const confirm = Array.from(modal.querySelectorAll('button,span,a,div'))
                .filter(visible)
                .find(el => norm(el.innerText || el.textContent) === '确定');
              return {ok:hasRequested, confirm_rect: confirm ? rectOf(confirm) : null, selected, reason: hasRequested ? null : '未找到请求的普通变体物流属性'};
            }''', {'value': value, 'plainGoods': plain_goods})
            if not state.get('ok') or not state.get('confirm_rect'):
                modal_results.append({**state, 'row_text': item.get('row_text')})
                page.keyboard.press('Escape')
                page.wait_for_timeout(300)
                continue
            self._click_rect_center(page, state['confirm_rect'])
            page.wait_for_timeout(700)
            modal_results.append({**state, 'row_text': item.get('row_text')})

        missing = [item for item in modal_results if not item.get('ok')]
        return {
            'ok': not missing,
            'plain_goods': plain_goods,
            'icon_count': len(icons),
            'results': modal_results,
            'reason': missing[0].get('reason') if missing else None,
        }

    def _fill_media_assets_on_page(self, page: Page, defaults: dict[str, Any] | None = None) -> dict[str, Any]:
        values = self._flatten_editor_defaults(defaults or {})
        slots = self._extract_image_slots(values)
        screenshot_path = EDITOR_ACTION_SCREENSHOT_MAP['fill_media_assets']
        if not slots:
            page.screenshot(path=str(screenshot_path), full_page=True)
            return {
                'stage': 'media_assets_filled',
                'label': '图片资产无需处理',
                'message': '未配置图片槽位文件名，本步骤按配置跳过。',
                'page_title': page.title(),
                'page_url': page.url,
                'screenshot_url': self._artifact_url(screenshot_path),
                'fill_result': {'eu_outer_package_image': {'ok': True, 'skipped': True, 'reason': 'no_config'}},
                'published': False,
            }

        self._dismiss_blocking_modals(page)
        slot_results = []
        failures = []
        deferred = []
        marketing_result = {'ok': True, 'skipped': True, 'reason': 'not_configured'}
        if self._should_generate_marketing_images(values):
            marketing_result = self._generate_marketing_images_on_page(
                page,
                allow_generate=not self._marketing_images_marked_already_generated(values),
                scene_fallback_filename=self._extract_marketing_scene_filename(values),
            )
            if not marketing_result.get('ok'):
                failures.append({'label': '营销图片', **marketing_result})
        for slot in slots:
            slot_result = self._fill_image_slot_by_filename(
                page,
                slot_label=slot['label'],
                filename=slot['filename'],
            )
            slot_results.append({**slot, **slot_result})
            if slot_result.get('deferred'):
                deferred.append(slot)
            elif not slot_result.get('ok'):
                failures.append({**slot, **slot_result})

        page.screenshot(path=str(screenshot_path), full_page=True)
        eu_result = next(
            (item for item in slot_results if self._is_eu_outer_package_slot(item.get('label'), item.get('slot_key'))),
            slot_results[0] if slot_results else {},
        )
        if failures:
            first_failure = failures[0]
            stage = 'fill_media_assets_failed'
            label = '图片资产填写失败'
            message = first_failure.get('reason') or f"未能回填图片槽位：{first_failure.get('label')}"
        elif deferred:
            names = ', '.join(str(item.get('label')) for item in deferred)
            stage = 'media_assets_deferred'
            label = '图片资产延后处理'
            message = f'当前页面未出现图片槽位，已延后处理：{names}'
        else:
            stage = 'media_assets_filled'
            label = '图片资产已填写'
            message = '已按配置处理图片银行槽位。'
        return {
            'stage': stage,
            'label': label,
            'message': message,
            'page_title': page.title(),
            'page_url': page.url,
            'screenshot_url': self._artifact_url(screenshot_path),
            'fill_result': {
                'image_slots': slot_results,
                'eu_outer_package_image': eu_result,
                'marketing_images': marketing_result,
            },
            'published': False,
        }

    def _fill_compliance_defaults_on_page(self, page: Page, defaults: dict[str, Any] | None = None) -> dict[str, Any]:
        values: dict[str, Any] = {
            'eu_responsible_priorities': ['Jacqueiline Marti'],
            'manufacturer_priorities': ['jiyang county thunder', 'Jiyang County thunder'],
        }
        values.update(self._flatten_editor_defaults(defaults or {}))

        self._dismiss_blocking_modals(page)
        eu_responsible = self._choose_ant_select_near_label(page, '欧盟责任人', values.get('eu_responsible_priorities') or [])
        manufacturer = self._choose_ant_select_near_label(page, '品牌制造商', values.get('manufacturer_priorities') or [])
        media = {'ok': True, 'skipped': True, 'reason': 'no_config'}
        if self._extract_eu_outer_package_filename(values):
            media = self._fill_media_assets_on_page(page, values).get('fill_result', {}).get('eu_outer_package_image') or {}

        missing = []
        if self._extract_eu_outer_package_filename(values) and not media.get('ok'):
            missing.append('eu_outer_package_image')
        optional_unfilled = [
            name for name, result in {
                'eu_responsible': eu_responsible,
                'manufacturer': manufacturer,
            }.items()
            if not result.get('ok')
        ]
        screenshot_path = EDITOR_ACTION_SCREENSHOT_MAP['fill_compliance_defaults']
        page.screenshot(path=str(screenshot_path), full_page=True)
        return {
            'stage': 'compliance_defaults_filled' if not missing else 'fill_compliance_defaults_failed',
            'label': '合规字段已填写' if not missing else '合规字段填写失败',
            'message': '已按配置处理合规字段。' if not missing else f'合规字段缺少：{", ".join(missing)}',
            'page_title': page.title(),
            'page_url': page.url,
            'screenshot_url': self._artifact_url(screenshot_path),
            'fill_result': {
                'eu_responsible': eu_responsible,
                'manufacturer': manufacturer,
                'eu_outer_package_image': media,
                'missing': missing,
                'optional_unfilled': optional_unfilled,
            },
            'published': False,
        }

    def _extract_eu_outer_package_filename(self, defaults: dict[str, Any] | None) -> str:
        data = defaults or {}
        candidates: list[Any] = [
            data.get('eu_outer_package_filename'),
            data.get('eu_outer_package_image_filename'),
        ]
        image = data.get('eu_outer_package_image')
        if isinstance(image, dict):
            candidates.extend([image.get('filename'), image.get('file_name'), image.get('name')])
        compliance = data.get('compliance')
        if isinstance(compliance, dict):
            candidates.extend([
                compliance.get('eu_outer_package_filename'),
                compliance.get('eu_outer_package_image_filename'),
            ])
            compliance_image = compliance.get('eu_outer_package_image')
            if isinstance(compliance_image, dict):
                candidates.extend([compliance_image.get('filename'), compliance_image.get('file_name'), compliance_image.get('name')])
        image_payload = data.get('image')
        if isinstance(image_payload, dict):
            candidates.extend([
                image_payload.get('eu_outer_package_filename'),
                image_payload.get('eu_outer_package_image_filename'),
            ])
            nested = image_payload.get('eu_outer_package_image')
            if isinstance(nested, dict):
                candidates.extend([nested.get('filename'), nested.get('file_name'), nested.get('name')])
            slots = image_payload.get('slots')
            if isinstance(slots, list):
                for slot in slots:
                    if not isinstance(slot, dict):
                        continue
                    if self._is_eu_outer_package_slot(slot.get('label') or slot.get('slot_label'), slot.get('slot_key') or slot.get('type')):
                        candidates.extend([
                            slot.get('filename'),
                            slot.get('file_name'),
                            slot.get('name'),
                        ])
        for value in candidates:
            text = str(value or '').strip()
            if text:
                return text
        return ''

    def _flatten_editor_defaults(self, defaults: dict[str, Any] | None) -> dict[str, Any]:
        data = dict(defaults or {})
        flattened = dict(data)
        groups = {
            'category': {
                'category_keyword': ('category_keyword', 'keyword', 'search_keyword'),
                'category_match': ('category_match', 'match_text', 'category_name'),
                'custom_attributes': ('custom_attributes',),
                'attribute_template_priorities': ('attribute_template_priorities', 'reference_template_priorities', 'attribute_templates'),
            },
            'logistics': {
                'weight': ('weight',),
                'length': ('length',),
                'width': ('width',),
                'height': ('height',),
                'gross_weight': ('gross_weight', 'package_weight'),
                'gross_length': ('gross_length', 'package_length'),
                'gross_width': ('gross_width', 'package_width'),
                'gross_height': ('gross_height', 'package_height'),
                'delivery_days': ('delivery_days',),
                'freight_template_priorities': ('freight_template_priorities', 'freight_templates', 'freight_template'),
                'service_template_priorities': ('service_template_priorities', 'service_templates', 'service_template'),
                'logistics_attribute': ('logistics_attribute', 'attribute'),
                'is_original_box': ('is_original_box', 'original_box'),
            },
            'pricing': {
                'declared_value': ('declared_value', 'value'),
                'stock': ('stock',),
                'retail_price': ('retail_price', 'price'),
                'product_price': ('product_price', 'price'),
                'supply_price': ('supply_price', 'supply'),
            },
            'sku': {
                'sku_code': ('sku_code', 'goods_code'),
                'jit_stock': ('jit_stock', 'stock'),
                'stock': ('stock',),
            },
            'compliance': {
                'eu_responsible_priorities': ('eu_responsible_priorities', 'eu_responsible_names'),
                'manufacturer_priorities': ('manufacturer_priorities', 'manufacturer_names'),
                'customs_product_name_priorities': ('customs_product_name_priorities', 'customs_product_names', 'customs_name'),
                'eu_outer_package_filename': ('eu_outer_package_filename', 'eu_outer_package_image_filename'),
            },
            'semi_managed': {
                'jit_stock': ('jit_stock', 'stock'),
                'product_price': ('product_price', 'price'),
                'supply_price': ('supply_price', 'supply'),
                'retail_price': ('retail_price',),
                'weight': ('weight',),
                'length': ('length',),
                'width': ('width',),
                'height': ('height',),
                'is_original_box': ('is_original_box', 'original_box'),
                'logistics_attribute': ('logistics_attribute', 'attribute'),
            },
        }
        for group_name, aliases in groups.items():
            group = data.get(group_name)
            if not isinstance(group, dict):
                continue
            for target_key, source_keys in aliases.items():
                for source_key in source_keys:
                    value = group.get(source_key)
                    if value is not None and value != '':
                        flattened[target_key] = value
                        break
        return flattened

    def _extract_image_slots(self, defaults: dict[str, Any] | None) -> list[dict[str, str]]:
        data = defaults or {}
        slots: list[dict[str, str]] = []

        def add_slot(label: Any, filename: Any, slot_key: Any = None, source: Any = None) -> None:
            label_text = str(label or '').strip()
            filename_text = str(filename or '').strip()
            key_text = str(slot_key or '').strip()
            if self._is_marketing_image_slot(label_text, key_text):
                return
            if not label_text and self._is_eu_outer_package_slot(label_text, key_text):
                label_text = '外包装/标签实拍图-欧盟'
            if not label_text or not filename_text:
                return
            if any(item['label'] == label_text and item['filename'] == filename_text for item in slots):
                return
            slots.append({
                'label': label_text,
                'filename': filename_text,
                'slot_key': key_text,
                'source': str(source or 'smt_image_bank').strip(),
            })

        image_payload = data.get('image')
        if isinstance(image_payload, dict):
            raw_slots = image_payload.get('slots')
            if isinstance(raw_slots, list):
                for raw_slot in raw_slots:
                    if not isinstance(raw_slot, dict):
                        continue
                    filename = (
                        raw_slot.get('filename')
                        or raw_slot.get('file_name')
                        or raw_slot.get('name')
                    )
                    add_slot(
                        raw_slot.get('label') or raw_slot.get('slot_label'),
                        filename,
                        raw_slot.get('slot_key') or raw_slot.get('type'),
                        raw_slot.get('source'),
                    )
            image_filename = image_payload.get('eu_outer_package_filename') or image_payload.get('eu_outer_package_image_filename')
            nested = image_payload.get('eu_outer_package_image')
            if isinstance(nested, dict):
                image_filename = image_filename or nested.get('filename') or nested.get('file_name') or nested.get('name')
            add_slot('外包装/标签实拍图-欧盟', image_filename, 'eu_outer_package', image_payload.get('source'))

        direct_image = data.get('eu_outer_package_image')
        direct_filename = data.get('eu_outer_package_filename') or data.get('eu_outer_package_image_filename')
        if isinstance(direct_image, dict):
            direct_filename = direct_filename or direct_image.get('filename') or direct_image.get('file_name') or direct_image.get('name')
        add_slot('外包装/标签实拍图-欧盟', direct_filename, 'eu_outer_package')
        return slots

    def _is_marketing_image_slot(self, label: Any, slot_key: Any = None) -> bool:
        text = f'{label or ""} {slot_key or ""}'.lower().replace('-', '_').replace(' ', '_')
        return (
            'marketing' in text
            or '白底图' in text
            or '场景图' in text
            or '3:4' in text
            or '1:1' in text
        )

    def _extract_marketing_scene_filename(self, defaults: dict[str, Any] | None) -> str:
        data = defaults or {}
        candidates: list[Any] = [
            data.get('marketing_scene_3_4_filename'),
            data.get('marketing_scene_filename'),
            data.get('scene_3_4_filename'),
        ]
        image_payload = data.get('image')
        if isinstance(image_payload, dict):
            candidates.extend([
                image_payload.get('marketing_scene_3_4_filename'),
                image_payload.get('marketing_scene_filename'),
                image_payload.get('scene_3_4_filename'),
            ])
            nested = image_payload.get('marketing_scene_3_4') or image_payload.get('marketing_scene_image')
            if isinstance(nested, dict):
                candidates.extend([nested.get('filename'), nested.get('file_name'), nested.get('name')])
            slots = image_payload.get('slots')
            if isinstance(slots, list):
                for slot in slots:
                    if not isinstance(slot, dict):
                        continue
                    label = slot.get('label') or slot.get('slot_label')
                    slot_key = slot.get('slot_key') or slot.get('type')
                    slot_text = f'{label or ""} {slot_key or ""}'.lower().replace('-', '_').replace(' ', '_')
                    if 'marketing_scene_3_4' in slot_text or '3:4' in slot_text or '场景图' in slot_text:
                        candidates.extend([slot.get('filename'), slot.get('file_name'), slot.get('name')])
        for value in candidates:
            text = str(value or '').strip()
            if text:
                return text
        return self._extract_eu_outer_package_filename(data)

    def _is_eu_outer_package_slot(self, label: Any, slot_key: Any = None) -> bool:
        text = f'{label or ""} {slot_key or ""}'.lower().replace('-', '_').replace(' ', '_')
        return (
            'eu_outer_package' in text
            or '外包装' in text
            or '标签实拍图_欧盟' in text
            or '标签实拍图-欧盟' in text
        )

    def _should_generate_marketing_images(self, defaults: dict[str, Any] | None) -> bool:
        image = (defaults or {}).get('image')
        if not isinstance(image, dict):
            return False
        if self._marketing_images_marked_already_generated(defaults):
            return True
        strategy = str(
            image.get('marketing_images_strategy')
            or image.get('marketing_strategy')
            or ''
        ).strip().lower()
        if strategy in {'generate', 'one_click_generate', 'auto_generate', '一键生成'}:
            return True
        slots = image.get('slots')
        if not isinstance(slots, list):
            return False
        for slot in slots:
            if not isinstance(slot, dict):
                continue
            slot_strategy = str(slot.get('strategy') or '').strip().lower()
            label = str(slot.get('label') or slot.get('slot_label') or slot.get('slot_key') or slot.get('type') or '')
            if slot_strategy in {'generate', 'one_click_generate', 'auto_generate', '一键生成'} and (
                '白底图' in label or '场景图' in label or 'marketing' in label.lower()
            ):
                return True
        return False

    def _marketing_images_marked_already_generated(self, defaults: dict[str, Any] | None) -> bool:
        image = (defaults or {}).get('image')
        if not isinstance(image, dict):
            return False
        values = [
            image.get('marketing_images_already_generated'),
            image.get('already_generated'),
            image.get('marketing_already_generated'),
        ]
        return any(value is True or str(value).strip().lower() in {'true', '1', 'yes', '已生成'} for value in values)

    def _generate_marketing_images_on_page(
        self,
        page: Page,
        allow_generate: bool = True,
        scene_fallback_filename: str = '',
    ) -> dict[str, Any]:
        before = self._marketing_images_state(page)
        if before.get('ok'):
            white_background = self._apply_marketing_white_background(page)
            after = self._marketing_images_state(page)
            if not white_background.get('ok'):
                if after.get('ok'):
                    return {
                        'ok': True,
                        'already_generated': True,
                        'before': before,
                        'white_background': white_background,
                        'after': after,
                        'warning': white_background.get('reason') or '营销图片白底处理未完成，但必需营销图已存在',
                    }
                return {
                    'ok': False,
                    'already_generated': True,
                    'reason': white_background.get('reason') or '营销图片白底处理失败',
                    'before': before,
                    'white_background': white_background,
                    'after': after,
                }
            return {'ok': True, 'already_generated': True, 'before': before, 'white_background': white_background, 'after': after}
        if not allow_generate:
            return {
                'ok': False,
                'already_generated': True,
                'reason': before.get('reason') or '配置标记营销图已生成，但页面未检测到完整营销图',
                'before': before,
            }
        target = page.evaluate(r'''() => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
          const rectOf = (el) => {
            const r = el.getBoundingClientRect();
            return {x:r.x, y:r.y, w:r.width, h:r.height};
          };
          const marketing = Array.from(document.querySelectorAll('.market-img-module,.ant-form-item,div')).filter(visible).find(el => {
            const text = textOf(el);
            return text.includes('(1:1白底图)') && text.includes('(3:4场景图)');
          });
          if (!marketing) return {ok:false, reason:'未找到营销图片模块'};
          const button = Array.from(marketing.querySelectorAll('button,a,span,div')).filter(visible).find(el => {
            return textOf(el) === '一键生成' || String(el.className || '').includes('generate-market-img');
          });
          if (!button) return {ok:false, reason:'未找到营销图片一键生成入口'};
          button.scrollIntoView({block:'center', inline:'nearest'});
          return {ok:true, rect:rectOf(button), text:textOf(button), class_name:String(button.className || '')};
        }''')
        if not target.get('ok'):
            return target
        self._click_rect_center(page, target['rect'])
        page.wait_for_timeout(6000)
        self._dismiss_blocking_modals(page)
        white_background = self._apply_marketing_white_background(page)
        if not white_background.get('ok'):
            return {
                'ok': False,
                'reason': white_background.get('reason') or '营销图片白底处理失败',
                'target': target,
                'before': before,
                'white_background': white_background,
            }
        page.wait_for_timeout(1500)
        after = self._marketing_images_state(page)
        if not after.get('ok'):
            fallback = self._fill_missing_marketing_scene_from_bank(page, after, scene_fallback_filename)
            if fallback.get('ok'):
                final_state = self._marketing_images_state(page)
                if final_state.get('ok'):
                    return {'ok': True, 'target': target, 'before': before, 'white_background': white_background, 'after': final_state, 'scene_fallback': fallback}
                return {'ok': False, 'reason': final_state.get('reason') or '营销图片备用图回填后仍未补齐', 'target': target, 'before': before, 'white_background': white_background, 'after': final_state, 'scene_fallback': fallback}
            return {'ok': False, 'reason': fallback.get('reason') or after.get('reason') or '营销图片一键生成后仍未补齐', 'target': target, 'before': before, 'white_background': white_background, 'after': after, 'scene_fallback': fallback}
        return {'ok': True, 'target': target, 'before': before, 'white_background': white_background, 'after': after}

    def _fill_missing_marketing_scene_from_bank(self, page: Page, state: dict[str, Any], filename: str) -> dict[str, Any]:
        missing = state.get('missing') if isinstance(state, dict) else []
        if '3:4场景图' not in (missing or []):
            return {'ok': True, 'skipped': True, 'reason': '3:4场景图未缺失'}
        filename = str(filename or '').strip()
        if not filename:
            return {'ok': False, 'reason': '营销3:4场景图缺少备用图片文件名'}
        return self._fill_marketing_scene_image_by_filename(page, filename)

    def _fill_marketing_scene_image_by_filename(self, page: Page, filename: str) -> dict[str, Any]:
        clear_result = self._remove_invalid_marketing_image(page, '3:4场景图')
        if not clear_result.get('ok'):
            return clear_result
        open_result = self._open_marketing_image_picker(page, '3:4场景图')
        if not open_result.get('ok'):
            return {**open_result, 'clear_result': clear_result}
        bank_result = self._open_smt_image_bank_from_picker(page, require_menu=False)
        if not bank_result.get('ok'):
            return {**bank_result, 'clear_result': clear_result, 'picker': open_result}
        select_result = self._select_image_bank_asset_by_filename(page, filename)
        if not select_result.get('ok'):
            return {**select_result, 'clear_result': clear_result, 'picker': open_result, 'image_bank': bank_result}
        return {'ok': True, 'filename': filename, 'clear_result': clear_result, 'picker': open_result, 'image_bank': bank_result, 'selection': select_result}

    def _remove_invalid_marketing_image(self, page: Page, label: str) -> dict[str, Any]:
        self._dismiss_blocking_modals(page)
        target = page.evaluate(r'''(label) => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
          const norm = (s) => String(s || '').replace(/\s+/g, '').trim();
          const rectOf = (el) => {
            const r = el.getBoundingClientRect();
            return {x:r.x, y:r.y, w:r.width, h:r.height};
          };
          const wanted = norm(label);
          const item = Array.from(document.querySelectorAll('.market-img-item'))
            .filter(visible)
            .map(el => ({el, text:textOf(el), rect:rectOf(el)}))
            .filter(item => norm(item.text).includes(wanted))
            .sort((a, b) => (a.rect.w * a.rect.h) - (b.rect.w * b.rect.h) || a.text.length - b.text.length)[0]?.el;
          if (!item) return {ok:false, reason:`未找到营销图片槽位：${label}`};
          const text = textOf(item);
          const img = item.querySelector('img');
          const src = String(img?.getAttribute('src') || '');
          const sizeMatch = text.match(/(\d+)\s*[xX×]\s*(\d+)/);
          const width = sizeMatch ? Number(sizeMatch[1]) : null;
          const height = sizeMatch ? Number(sizeMatch[2]) : null;
          const emptyDataPlaceholder = src.startsWith('data:image') && !sizeMatch;
          const hasImage = Boolean(src) && !src.includes('addImg') && !src.includes('addimg') && !emptyDataPlaceholder;
          const invalid = hasImage && (
            (width !== null && height !== null && (width <= 0 || height <= 0))
            || (label.includes('3:4') && width !== null && height !== null && (width < 750 || height < 1000))
          );
          if (!hasImage || !invalid) return {ok:true, skipped:true, reason: hasImage ? '营销图片不是无效图，无需删除' : '营销图片槽位为空'};
          const dangerous = Array.from(item.querySelectorAll('button,a,span,div'))
            .filter(visible)
            .find(el => ['发布','继续发布','确认发布','提交发布','保存并发布','保存并移入待发布'].includes(norm(el.innerText || el.textContent)));
          if (dangerous) return {ok:false, reason:`营销图片槽位附近出现危险动作：${norm(dangerous.innerText || dangerous.textContent)}`};
          const deleteTargets = Array.from(item.querySelectorAll('button,a,[role="button"],span,div,i,em'))
            .filter(visible)
            .map(el => ({el, text:norm(el.innerText || el.textContent), title:norm(el.getAttribute('title') || el.getAttribute('aria-label') || ''), cls:String(el.className || ''), rect:rectOf(el)}))
            .filter(x => {
              const hay = `${x.text} ${x.title} ${x.cls}`.toLowerCase();
              const small = x.rect.w <= 48 && x.rect.h <= 48;
              return small && /(删除|delete|trash|remove|icon_delete)/i.test(hay);
            })
            .sort((a, b) => (a.rect.w * a.rect.h) - (b.rect.w * b.rect.h));
          const picked = deleteTargets[0];
          if (!picked) return {ok:false, reason:`未找到${label}无效图删除入口`, item_text:text.slice(0, 240)};
          picked.el.scrollIntoView({block:'center', inline:'nearest'});
          return {ok:true, rect:rectOf(picked.el), text:picked.text, title:picked.title, class_name:picked.cls, item_text:text.slice(0, 240), dimensions: sizeMatch ? {width, height} : null};
        }''', label)
        if not target.get('ok') or target.get('skipped'):
            return target
        self._click_rect_center(page, target['rect'])
        page.wait_for_timeout(700)
        confirm = self._click_safe_modal_button(page, ['确定', '确认', '删除'])
        if not confirm.get('ok') and '未找到可确认的弹窗' not in str(confirm.get('reason') or ''):
            return {**target, 'ok': False, 'reason': confirm.get('reason'), 'confirm': confirm}
        page.wait_for_timeout(1200)
        return {**target, 'confirm': confirm}

    def _open_marketing_image_picker(self, page: Page, label: str) -> dict[str, Any]:
        self._dismiss_blocking_modals(page)
        target = page.evaluate(r'''(label) => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
          const norm = (s) => String(s || '').replace(/\s+/g, '').trim();
          const rectOf = (el) => {
            const r = el.getBoundingClientRect();
            return {x:r.x, y:r.y, w:r.width, h:r.height};
          };
          const wanted = norm(label);
          const items = Array.from(document.querySelectorAll('.market-img-item'))
            .filter(visible)
            .map(el => ({el, text:textOf(el), rect:rectOf(el)}))
            .filter(item => norm(item.text).includes(wanted))
            .sort((a, b) => (a.rect.w * a.rect.h) - (b.rect.w * b.rect.h) || a.text.length - b.text.length);
          const item = items[0]?.el;
          if (!item) return {ok:false, reason:`未找到营销图片槽位：${label}`};
          const itemRect = rectOf(item);
          const dangerous = Array.from(item.querySelectorAll('button,a,span,div'))
            .filter(visible)
            .find(el => ['发布','继续发布','确认发布','提交发布','保存并发布','保存并移入待发布'].includes(norm(el.innerText || el.textContent)));
          if (dangerous) return {ok:false, reason:`营销图片槽位附近出现危险动作：${norm(dangerous.innerText || dangerous.textContent)}`};
          const itemText = textOf(item);
          const placeholder = Array.from(item.querySelectorAll('img')).filter(visible).map(img => ({el:img, src:String(img.getAttribute('src') || ''), rect:rectOf(img)}))
            .find(x => x.src.includes('addImg') || x.src.includes('addimg') || (x.src.startsWith('data:image') && !/\d+\s*[xX×]\s*\d+/.test(itemText)));
          if (placeholder) {
            const clickTarget = placeholder.el.closest('button,a,[role="button"],.img-out,.img-box,.single-image,.add-img,.upload-img,div,span') || placeholder.el;
            clickTarget.scrollIntoView({block:'center', inline:'nearest'});
            return {ok:true, rect:rectOf(clickTarget), text:'添加图片', class_name:String(clickTarget.className || ''), placeholder:true};
          }
          const imgRect = Array.from(item.querySelectorAll('img')).filter(visible).map(rectOf)[0] || itemRect;
          const controls = Array.from(item.querySelectorAll('button,a,[role="button"],.operate-box,.icon-operate,.add-img,.upload-img,span,div,i,em'))
            .filter(visible)
            .map(el => ({el, text:norm(el.innerText || el.textContent), title:norm(el.getAttribute('title') || el.getAttribute('aria-label') || ''), cls:String(el.className || ''), rect:rectOf(el)}))
            .filter(x => {
              const hay = `${x.text} ${x.title} ${x.cls}`.toLowerCase();
              if (/(删除|delete|trash|remove|close|发布|保存并发布)/i.test(hay)) return false;
              if (x.text === '预览' || x.text === '生成标签') return false;
              if (x.cls.includes('disabled')) return false;
              if (x.text.includes('添加图片') || x.text.includes('选择图片') || x.text.includes('图片银行') || x.text.includes('上传图片')) return true;
              const centerX = x.rect.x + x.rect.w / 2;
              const centerY = x.rect.y + x.rect.h / 2;
              const small = x.rect.w <= 64 && x.rect.h <= 64;
              const inImage = centerX >= imgRect.x - 8 && centerX <= imgRect.x + imgRect.w + 24 && centerY >= imgRect.y - 8 && centerY <= imgRect.y + imgRect.h + 24;
              return small && inImage && (hay.includes('operate') || hay.includes('tool') || hay.includes('icon') || hay.includes('upload') || hay.includes('add') || !x.text);
            })
            .sort((a, b) => {
              const score = (x) => {
                if (x.text.includes('添加图片') || x.text.includes('选择图片')) return 0;
                if (x.text.includes('图片银行') || x.text.includes('上传图片')) return 1;
                if (x.cls.toLowerCase().includes('icon-operate')) return 2;
                if (x.cls.toLowerCase().includes('operate')) return 3;
                return 4;
              };
              return score(a) - score(b) || (a.rect.w * a.rect.h) - (b.rect.w * b.rect.h);
            });
          const picked = controls[0];
          if (!picked) return {ok:false, reason:`${label}槽位没有可点击的图片选择入口`, item_text:textOf(item).slice(0, 240)};
          picked.el.scrollIntoView({block:'center', inline:'nearest'});
          return {ok:true, text:picked.text, title:picked.title, class_name:picked.cls, rect:rectOf(picked.el), item_text:textOf(item).slice(0, 240)};
        }''', label)
        if not target.get('ok'):
            return target
        self._click_rect_center(page, target['rect'])
        page.wait_for_timeout(1200)
        self._dismiss_blocking_modals(page)
        opened = page.evaluate(r'''() => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
          const body = textOf(document.body || document.documentElement);
          const hasBankMenu = Array.from(document.querySelectorAll('li,button,a,span,div')).filter(visible).some(el => textOf(el).includes('图片银行（速卖通）'));
          const hasImageDialog = Array.from(document.querySelectorAll('.ant-modal, .ant-modal-wrap, [role="dialog"]')).filter(visible).some(el => {
            const text = textOf(el);
            return text.includes('图片') || text.includes('上传') || text.includes('图片银行');
          });
          return {ok: hasBankMenu || hasImageDialog, has_bank_menu: hasBankMenu, has_image_dialog: hasImageDialog, body_excerpt: body.slice(-500)};
        }''')
        if not opened.get('ok'):
            return {'ok': False, 'reason': f'点击{label}槽位后未出现图片选择菜单或图片弹窗', 'target': target, 'opened': opened}
        return {'ok': True, 'target': target, 'opened': opened}

    def _open_marketing_white_background_dialog(self, page: Page) -> dict[str, Any]:
        trigger = page.evaluate(r'''() => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
          const norm = (s) => String(s || '').replace(/\s+/g, '').trim();
          const labelOf = (el) => norm([el.innerText || el.textContent, el.getAttribute('title'), el.getAttribute('aria-label')].join(' '));
          const rectOf = (el) => {
            const r = el.getBoundingClientRect();
            return {x:r.x, y:r.y, w:r.width, h:r.height};
          };
          const hasSize = (item) => /\d+\s*[xX×]\s*\d+/.test(item.text);
          const items = Array.from(document.querySelectorAll('.market-img-item, .ant-form-item, li, div'))
            .filter(visible)
            .map(el => ({el, text:textOf(el), rect:rectOf(el)}))
            .filter(item => item.text.includes('1:1白底图') || item.text.includes('营销图片'));
          const item = items
            .filter(item => item.text.length <= 260)
            .sort((a, b) => {
              const itemScore = (item) => {
                if (item.text.includes('1:1白底图') && hasSize(item)) return 0;
                if (item.text.includes('1:1白底图')) return 1;
                return 2;
              };
              return itemScore(a) - itemScore(b) || a.text.length - b.text.length || (a.rect.w * a.rect.h) - (b.rect.w * b.rect.h);
            })[0];
          if (!item) return {ok:false, reason:'未找到营销图片白底图槽位'};
          const itemRect = item.rect;
          const dangerous = Array.from(item.el.querySelectorAll('button,a,span,div'))
            .filter(visible)
            .find(el => ['发布','继续发布','确认发布','提交发布','保存并发布','保存并移入待发布','移入待发布'].includes(norm(el.innerText || el.textContent)));
          if (dangerous) return {ok:false, reason:`营销图片附近出现危险动作：${norm(dangerous.innerText || dangerous.textContent)}`};
          const isRightSideDanger = (x) => {
            const label = `${x.text} ${x.label} ${x.cls}`.toLowerCase();
            const centerX = x.rect.x + x.rect.w / 2;
            const centerY = x.rect.y + x.rect.h / 2;
            const rightSide = centerX >= itemRect.x + itemRect.w * 0.58;
            const lower = centerY >= itemRect.y + itemRect.h * 0.45;
            return rightSide && lower && /(删除|垃圾桶|delete|trash|remove)/i.test(label);
          };
          const isLowerLeftTool = (x) => {
            const label = `${x.text} ${x.label} ${x.cls}`.toLowerCase();
            const centerX = x.rect.x + x.rect.w / 2;
            const centerY = x.rect.y + x.rect.h / 2;
            const leftSide = centerX <= itemRect.x + Math.max(96, itemRect.w * 0.42);
            const lower = centerY >= itemRect.y + itemRect.h * 0.45;
            const small = x.rect.w <= 56 && x.rect.h <= 56;
            return leftSide && lower && small && !isRightSideDanger(x) && !/(删除|垃圾桶|delete|trash|remove|发布|保存)/i.test(label)
              && (x.label.includes('图片工具') || x.label.includes('工具') || x.label.includes('下拉') || x.label.includes('更多') || label.includes('tool') || label.includes('operate') || label.includes('more') || !x.text);
          };
          const controls = Array.from(item.el.querySelectorAll('button,a,[role="button"],span,div'))
            .filter(visible)
            .map(el => ({el, text:norm(el.innerText || el.textContent), label:labelOf(el), cls:String(el.className || ''), role:String(el.getAttribute('role') || ''), haspopup:String(el.getAttribute('aria-haspopup') || ''), rect:rectOf(el)}))
            .filter(x => {
              if (['删除','垃圾桶','预览','生成','一键生成','发布','继续发布','确认发布','提交发布'].some(term => x.label.includes(term))) return false;
              if (isRightSideDanger(x)) return false;
              if (/^\d+[xX×]\d+/.test(x.text)) return false;
              if (x.text.includes('图片白底')) return true;
              if (!(item.text.includes('1:1白底图') && hasSize(item))) return false;
              if (isLowerLeftTool(x)) return true;
              return x.label.includes('图片工具') || x.label.includes('工具') || x.label.includes('下拉') || x.label.includes('更多') || x.haspopup === 'menu';
            })
            .sort((a, b) => {
              const score = (x) => {
                if (x.text.includes('图片白底')) return 0;
                if (isLowerLeftTool(x)) return 1;
                if (x.label.includes('图片工具')) return 2;
                if (x.label.includes('工具') || x.label.includes('下拉') || x.label.includes('更多')) return 3;
                return 3;
              };
              return score(a) - score(b) || (a.rect.w * a.rect.h) - (b.rect.w * b.rect.h);
            });
          const picked = controls[0];
          if (!picked) return {ok:false, reason:'未找到营销图片工具菜单入口', item_text:item.text.slice(0, 260)};
          picked.el.scrollIntoView({block:'center', inline:'nearest'});
          return {ok:true, trigger_rect:rectOf(picked.el), trigger_text:picked.text, trigger_class:picked.cls};
        }''')
        if not trigger.get('ok'):
            return trigger
        self._click_rect_center(page, trigger['trigger_rect'])
        page.wait_for_timeout(900)
        item = page.evaluate(r'''({triggerRect}) => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
          const norm = (s) => String(s || '').replace(/\s+/g, '').trim();
          const rectOf = (el) => {
            const r = el.getBoundingClientRect();
            return {x:r.x, y:r.y, w:r.width, h:r.height};
          };
          const menus = Array.from(document.querySelectorAll('.ant-dropdown:not(.ant-dropdown-hidden), .ant-dropdown-menu, [role="menu"], .ant-modal, .modal'))
            .filter(visible);
          const nearTrigger = (el) => {
            if (!triggerRect) return true;
            const r = rectOf(el);
            const dx = Math.max(0, Math.max(triggerRect.x - (r.x + r.w), r.x - (triggerRect.x + triggerRect.w)));
            const dy = Math.max(0, Math.max(triggerRect.y - (r.y + r.h), r.y - (triggerRect.y + triggerRect.h)));
            return dx <= 260 && dy <= 320;
          };
          const scopedMenus = menus.filter(nearTrigger);
          const closestMenu = scopedMenus[scopedMenus.length - 1];
          if (!closestMenu) return {ok:false, reason:'未找到图片白底菜单容器'};
          const candidates = Array.from(closestMenu.querySelectorAll('li,button,a,span,div'))
            .filter(visible)
            .map(el => ({el, text:norm(el.innerText || el.textContent), rect:rectOf(el)}))
            .filter(x => x.text === '图片白底');
          const picked = candidates[0];
          if (!picked) return {ok:false, reason:'未找到图片白底菜单项'};
          return {ok:true, text:picked.text, item_rect:rectOf(picked.el)};
        }''', {'triggerRect': trigger.get('trigger_rect')})
        if not item.get('ok'):
            return {**item, 'trigger': trigger}
        self._click_rect_center(page, item['item_rect'])
        page.wait_for_timeout(1200)
        return {**item, 'trigger': trigger}

    def _apply_marketing_white_background(self, page: Page) -> dict[str, Any]:
        dialog = self._marketing_white_background_dialog_target(page)
        if dialog.get('skipped'):
            open_result = self._open_marketing_white_background_dialog(page)
            if not open_result.get('ok'):
                return open_result
            dialog = self._marketing_white_background_dialog_target(page)
            dialog = {**dialog, 'open_result': open_result}
            if dialog.get('skipped'):
                return {**dialog, 'ok': False, 'reason': '点击图片白底后未出现一键白底弹窗'}
        if not dialog.get('ok') or dialog.get('skipped'):
            return dialog
        if dialog.get('select_rect'):
            self._click_rect_center(page, dialog['select_rect'])
            page.wait_for_timeout(500)
        self._click_rect_center(page, dialog['button_rect'])
        page.wait_for_timeout(8000)
        close_result = page.evaluate(r'''() => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
          const rectOf = (el) => {
            const r = el.getBoundingClientRect();
            return {x:r.x, y:r.y, w:r.width, h:r.height};
          };
          const modal = Array.from(document.querySelectorAll('.ant-modal, .ant-modal-wrap, [role="dialog"]'))
            .filter(visible)
            .reverse()
            .find(el => textOf(el).includes('图片白底'));
          if (!modal) return {closed:true};
          const close = Array.from(modal.querySelectorAll('button,a,span,div')).filter(visible).find(el => {
            const text = textOf(el).replace(/\s+/g, '');
            return text === '关闭' || text === '×' || String(el.className || '').includes('ant-modal-close');
          });
          return close ? {closed:false, close_rect:rectOf(close)} : {closed:false};
        }''')
        if close_result.get('close_rect'):
            self._click_rect_center(page, close_result['close_rect'])
            page.wait_for_timeout(800)
        return {**dialog, 'clicked': True, 'close_result': close_result}

    def _marketing_white_background_dialog_target(self, page: Page) -> dict[str, Any]:
        return page.evaluate(r'''() => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
          const norm = (s) => String(s || '').replace(/\s+/g, '').trim();
          const rectOf = (el) => {
            const r = el.getBoundingClientRect();
            return {x:r.x, y:r.y, w:r.width, h:r.height};
          };
          const modal = Array.from(document.querySelectorAll('.ant-modal, .ant-modal-wrap, [role="dialog"]'))
            .filter(visible)
            .reverse()
            .find(el => {
              const text = textOf(el);
              return text.includes('图片白底') && text.includes('一键白底');
            });
          if (!modal) return {ok:true, skipped:true, reason:'未出现图片白底弹窗'};
          const modalText = textOf(modal);
          const dangerousTerms = ['发布', '立即发布', '继续发布', '保存并发布', '确认发布', '提交发布', '保存并移入待发布', '移入待发布'];
          const dangerousTerm = dangerousTerms.find(term => norm(modalText).includes(norm(term)));
          if (dangerousTerm) return {ok:false, reason:`图片白底弹窗出现危险动作：${dangerousTerm}`, modal_text:modalText.slice(0, 300)};
          const checkboxes = Array.from(modal.querySelectorAll('input[type="checkbox"]')).filter(visible);
          const unchecked = checkboxes.find(el => !el.checked);
          const selectAll = Array.from(modal.querySelectorAll('label,span,div')).filter(visible).find(el => norm(el.innerText || el.textContent) === '选择全部');
          const selectRect = unchecked ? rectOf(unchecked) : (selectAll ? rectOf(selectAll) : null);
          const button = Array.from(modal.querySelectorAll('button,a,span,div')).filter(visible).find(el => norm(el.innerText || el.textContent) === '一键白底');
          if (!button) return {ok:false, reason:'未找到一键白底按钮', modal_text:modalText.slice(0, 300)};
          return {
            ok:true,
            modal_found:true,
            selected_count_text: (modalText.match(/已选中\d+张/) || [''])[0],
            select_rect: selectRect,
            button_rect: rectOf(button),
          };
        }''')

    def _marketing_images_state(self, page: Page) -> dict[str, Any]:
        return page.evaluate(r'''() => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
          const items = Array.from(document.querySelectorAll('.market-img-item')).filter(visible).map((el) => {
            const text = textOf(el);
            const img = el.querySelector('img');
            const src = String(img?.getAttribute('src') || '');
            const sizeMatch = text.match(/(\d+)\s*[xX×]\s*(\d+)/);
            const naturalWidth = Number(img?.naturalWidth || 0) || null;
            const naturalHeight = Number(img?.naturalHeight || 0) || null;
            const width = sizeMatch ? Number(sizeMatch[1]) : naturalWidth;
            const height = sizeMatch ? Number(sizeMatch[2]) : naturalHeight;
            const rawHasImage = Boolean(src) && !src.includes('addImg') && !src.includes('addimg');
            const hasNonZeroSize = rawHasImage && width !== null && height !== null && width > 0 && height > 0;
            const isWhite = text.includes('1:1白底图');
            const isScene = text.includes('3:4场景图');
            const meetsRequiredSize = (isWhite && width >= 800 && height >= 800)
              || (isScene && width >= 750 && height >= 1000)
              || (!isWhite && !isScene && hasNonZeroSize);
            return {
              text,
              has_image: rawHasImage && hasNonZeroSize && meetsRequiredSize,
              raw_has_image: rawHasImage,
              is_placeholder: !src || src.includes('addImg') || src.includes('addimg') || !hasNonZeroSize || !meetsRequiredSize,
              dimensions: width !== null && height !== null ? {width, height, source: sizeMatch ? 'text' : 'natural'} : null,
              src_excerpt: src.slice(0, 120),
            };
          });
          const white = items.find(item => item.text.includes('1:1白底图'));
          const scene = items.find(item => item.text.includes('3:4场景图'));
          const missing = [];
          if (!white || !white.has_image) missing.push('1:1白底图');
          if (!scene || !scene.has_image) missing.push('3:4场景图');
          return {
            ok: missing.length === 0,
            missing,
            reason: missing.length ? `营销图片缺少：${missing.join(', ')}` : null,
            items,
          };
        }''')

    def _fill_image_slot_by_filename(self, page: Page, slot_label: str, filename: str) -> dict[str, Any]:
        before = self._image_slot_state(page, slot_label, filename)
        requires_configured_filename = self._is_eu_outer_package_slot(slot_label)
        materialize_result = None
        if before.get('missing_slot'):
            materialize_result = self._materialize_image_slot_section(page, slot_label)
            before = self._image_slot_state(page, slot_label, filename)
        if before.get('ok') and (not requires_configured_filename or before.get('filename_matched')):
            return {'ok': True, 'already_filled': True, 'verified': before, 'filename': filename, 'materialized': materialize_result}
        if before.get('missing_slot'):
            return {'ok': True, 'deferred': True, 'reason': before.get('reason'), 'verified': before, 'filename': filename, 'materialized': materialize_result}
        clear_result = None
        if requires_configured_filename and before.get('ok') and not before.get('filename_matched'):
            clear_result = self._remove_image_slot_existing_image(page, slot_label)
            if not clear_result.get('ok'):
                return {'ok': False, 'reason': clear_result.get('reason'), 'verified': before, 'filename': filename, 'clear_result': clear_result, 'materialized': materialize_result}
        result = self._fill_image_slot_asset_by_filename(page, slot_label, filename)
        after = self._image_slot_state(page, slot_label, filename)
        selection = result.get('selection') if isinstance(result.get('selection'), dict) else {}
        picked = selection.get('picked') if isinstance(selection.get('picked'), dict) else {}
        search = selection.get('search') if isinstance(selection.get('search'), dict) else {}
        selected_configured_filename = bool(
            search.get('filled')
            and search.get('search_text') == filename
            and filename in str(picked.get('text') or '')
        )
        verified_configured_filename = (
            bool(after.get('filename_matched') or selected_configured_filename)
            if requires_configured_filename
            else True
        )
        ok = bool(result.get('ok') and after.get('ok') and verified_configured_filename)
        if ok:
            response = {'ok': True, 'filename': filename, 'picker': result.get('picker'), 'image_bank': result.get('image_bank'), 'selection': result.get('selection'), 'verified': after, 'materialized': materialize_result}
            if requires_configured_filename:
                response['selected_configured_filename'] = selected_configured_filename
            return response
        reason = result.get('reason')
        if requires_configured_filename and result.get('ok') and after.get('ok') and not verified_configured_filename:
            reason = f'欧盟外包装图未匹配配置文件名：{filename}'
        return {**result, 'ok': False, 'reason': reason, 'verified': after, 'filename': filename, 'clear_result': clear_result, 'materialized': materialize_result}

    def _remove_image_slot_existing_image(self, page: Page, slot_label: str) -> dict[str, Any]:
        self._dismiss_blocking_modals(page)
        target = page.evaluate(r'''(slotLabel) => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
          const norm = (s) => String(s || '').replace(/[：:\/\s]/g, '').trim();
          const rectOf = (el) => {
            const r = el.getBoundingClientRect();
            return {x:r.x, y:r.y, w:r.width, h:r.height};
          };
          const aliases = ['外包装/标签实拍图-欧盟', '外包装标签实拍图-欧盟', '外包装标签实拍图欧盟', slotLabel];
          const labels = Array.from(document.querySelectorAll('label,span,div,td,th'))
            .filter(visible)
            .map(el => ({el, text:textOf(el), rect:rectOf(el)}))
            .filter(item => aliases.some(alias => item.text.includes(alias) || norm(item.text).includes(norm(alias))))
            .sort((a, b) => (a.rect.w * a.rect.h) - (b.rect.w * b.rect.h) || a.text.length - b.text.length);
          const label = labels[0]?.el;
          if (!label) return {ok:false, reason:`未找到${slotLabel}槽位`};
          const row = label.closest('.qualification-module-item, .ant-form-item, tr, li') || label.parentElement;
          if (!row) return {ok:false, reason:`未找到${slotLabel}所在行`};
          const dangerous = Array.from(row.querySelectorAll('button,a,span,div'))
            .filter(visible)
            .find(el => ['发布','继续发布','确认发布','提交发布','保存并发布','保存并移入待发布','移入待发布'].includes(norm(el.innerText || el.textContent)));
          if (dangerous) return {ok:false, reason:`${slotLabel}槽位附近出现危险动作：${norm(dangerous.innerText || dangerous.textContent)}`};
          const imgs = Array.from(row.querySelectorAll('img')).filter(visible).filter(img => {
            const src = String(img.getAttribute('src') || '');
            return src && !src.includes('addImg') && !src.includes('addimg') && !src.includes('static/img/addImg');
          }).map(img => ({el:img, rect:rectOf(img)}));
          const img = imgs[0];
          if (!img) return {ok:true, already_empty:true};
          const controls = Array.from(row.querySelectorAll('button,a,[role="button"],span,div,i,em'))
            .filter(visible)
            .map(el => ({el, text:norm(el.innerText || el.textContent), title:norm(el.getAttribute('title') || el.getAttribute('aria-label') || ''), cls:String(el.className || ''), rect:rectOf(el)}))
            .filter(x => {
              const label = `${x.text} ${x.title} ${x.cls}`.toLowerCase();
              const centerX = x.rect.x + x.rect.w / 2;
              const centerY = x.rect.y + x.rect.h / 2;
              const inImageRight = centerX >= img.rect.x + img.rect.w * 0.65 && centerX <= img.rect.x + img.rect.w + 24;
              const inImageBottom = centerY >= img.rect.y + img.rect.h * 0.65 && centerY <= img.rect.y + img.rect.h + 24;
              const small = x.rect.w <= 42 && x.rect.h <= 42;
              if (/(删除|垃圾桶|delete|trash|remove)/i.test(label)) return small && inImageRight && inImageBottom;
              return small && inImageRight && inImageBottom && !/(tool|operate|more|翻译|白底|美图|生成|发布|保存)/i.test(label);
            })
            .sort((a, b) => (a.rect.w * a.rect.h) - (b.rect.w * b.rect.h));
          const picked = controls[0];
          if (!picked) return {ok:false, reason:`未找到${slotLabel}旧图删除入口`};
          picked.el.scrollIntoView({block:'center', inline:'nearest'});
          return {ok:true, rect:rectOf(picked.el), text:picked.text, class_name:picked.cls};
        }''', slot_label)
        if not target.get('ok') or target.get('already_empty'):
            return target
        self._click_rect_center(page, target['rect'])
        page.wait_for_timeout(700)
        confirm = self._click_safe_modal_button(page, ['确定', '确认', '删除'])
        if not confirm.get('ok') and '未找到可确认的弹窗' not in str(confirm.get('reason') or ''):
            return {**target, 'ok': False, 'reason': confirm.get('reason'), 'confirm': confirm}
        page.wait_for_timeout(1200)
        return {**target, 'confirm': confirm}

    def _materialize_image_slot_section(self, page: Page, slot_label: str) -> dict[str, Any]:
        result: dict[str, Any] = {'ok': False, 'reason': '资质信息区域未唤醒'}
        for _ in range(5):
            result = page.evaluate(r'''(slotLabel) => {
              const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
              const norm = (s) => String(s || '').replace(/[：:\/\s-]/g, '').trim();
              const wanted = norm(slotLabel);
              const isEuOuter = wanted.includes('外包装标签实拍图欧盟') || String(slotLabel || '').toLowerCase().includes('eu_outer_package');
              const aliases = isEuOuter ? [slotLabel, '外包装/标签实拍图-欧盟', '外包装标签实拍图-欧盟', '外包装标签实拍图欧盟', '资质信息'] : [slotLabel];
              const candidates = Array.from(document.querySelectorAll('label,span,div,td,th,section'))
                .map(el => ({el, text:textOf(el)}))
                .filter(item => aliases.some(alias => item.text.includes(alias) || norm(item.text).includes(norm(alias))));
              const picked = candidates
                .filter(item => item.text.length <= 240)
                .sort((a, b) => a.text.length - b.text.length)[0] || candidates[0];
              if (picked) {
                picked.el.scrollIntoView({block:'center', inline:'nearest'});
                return {ok:true, found:true, text:picked.text.slice(0, 240)};
              }
              window.scrollTo(0, document.body.scrollHeight);
              return {ok:true, found:false, scroll_y:window.scrollY, body_height:document.body.scrollHeight};
            }''', slot_label)
            page.wait_for_timeout(700)
            if result.get('found'):
                break
        return result

    def _eu_outer_package_image_state(self, page: Page, filename: str) -> dict[str, Any]:
        return self._image_slot_state(page, '外包装/标签实拍图-欧盟', filename)

    def _image_slot_state(self, page: Page, slot_label: str, filename: str) -> dict[str, Any]:
        return page.evaluate(r'''({slotLabel, filename}) => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
          const attrText = (el) => [el.getAttribute('src'), el.getAttribute('alt'), el.getAttribute('title'), el.getAttribute('data-name')]
            .map(v => String(v || '')).join(' ');
          const norm = (s) => String(s || '').replace(/[：:\/\s]/g, '').trim();
          const isEuOuter = norm(slotLabel).includes('外包装标签实拍图欧盟') || String(slotLabel || '').toLowerCase().includes('eu_outer_package');
          const aliases = isEuOuter ? [slotLabel, '外包装/标签实拍图-欧盟', '外包装标签实拍图-欧盟', '外包装标签实拍图欧盟'] : [slotLabel];
          const rectOf = (el) => {
            const r = el.getBoundingClientRect();
            return {x:r.x, y:r.y, w:r.width, h:r.height};
          };
          const labelCandidates = Array.from(document.querySelectorAll('label,span,div,td,th'))
            .filter(visible)
            .map(el => ({el, text:textOf(el), rect:rectOf(el)}))
            .filter(item => aliases.some(alias => item.text.includes(alias) || norm(item.text).includes(norm(alias))))
            .sort((a, b) => {
              const smallA = a.text.length <= 160 && a.rect.w <= 520 && a.rect.h <= 140 ? 0 : 1;
              const smallB = b.text.length <= 160 && b.rect.w <= 520 && b.rect.h <= 140 ? 0 : 1;
              return smallA - smallB || (a.rect.w * a.rect.h) - (b.rect.w * b.rect.h) || a.text.length - b.text.length;
            });
          const label = labelCandidates[0]?.el;
          if (!label) return {ok:false, missing_slot:true, reason:`未找到${slotLabel}槽位`};
          const row = label.closest('.qualification-module-item, .ant-form-item, tr, li') || label.parentElement;
          if (!row) return {ok:false, reason:`未找到${slotLabel}所在行`};
          const rowText = textOf(row);
          const imgs = Array.from(row.querySelectorAll('img')).filter(visible);
          const imageTexts = imgs.map(attrText);
          const hasConfiguredName = filename && (rowText.includes(filename) || imageTexts.some(text => text.includes(filename)));
          const filledImgs = imgs.filter(img => {
            const src = String(img.getAttribute('src') || '');
            return src && !src.includes('addImg') && !src.includes('addimg') && !src.includes('static/img/addImg');
          });
          return {
            ok: Boolean(hasConfiguredName || filledImgs.length),
            reason: hasConfiguredName || filledImgs.length ? null : (slotLabel === '外包装/标签实拍图-欧盟' ? '欧盟外包装图槽位仍为空' : `${slotLabel}槽位仍为空`),
            filename_matched: Boolean(hasConfiguredName),
            filled_image_count: filledImgs.length,
            row_text: rowText.slice(0, 300),
            image_texts: imageTexts.slice(0, 5),
          };
        }''', {'slotLabel': slot_label, 'filename': filename})

    def _fill_eu_outer_package_image(self, page: Page, filename: str) -> dict[str, Any]:
        return self._fill_image_slot_asset_by_filename(page, '外包装/标签实拍图-欧盟', filename)

    def _fill_image_slot_asset_by_filename(self, page: Page, slot_label: str, filename: str) -> dict[str, Any]:
        open_result = self._open_image_slot_picker(page, slot_label)
        if not open_result.get('ok'):
            return open_result
        bank_result = self._open_smt_image_bank_from_picker(page, require_menu=self._is_eu_outer_package_slot(slot_label))
        if not bank_result.get('ok'):
            return bank_result
        select_result = self._select_image_bank_asset_by_filename(page, filename)
        if not select_result.get('ok'):
            return select_result
        return {'ok': True, 'filename': filename, 'picker': open_result, 'image_bank': bank_result, 'selection': select_result}

    def _open_eu_outer_package_image_picker(self, page: Page) -> dict[str, Any]:
        return self._open_image_slot_picker(page, '外包装/标签实拍图-欧盟')

    def _open_image_slot_picker(self, page: Page, slot_label: str) -> dict[str, Any]:
        target = page.evaluate(r'''(slotLabel) => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
          const norm = (s) => String(s || '').replace(/\s+/g, '').trim();
          const rectOf = (el) => {
            const r = el.getBoundingClientRect();
            return {x:r.x, y:r.y, w:r.width, h:r.height};
          };
          const labelNorm = (s) => String(s || '').replace(/[：:\/\s]/g, '').trim();
          const isEuOuter = labelNorm(slotLabel).includes('外包装标签实拍图欧盟') || String(slotLabel || '').toLowerCase().includes('eu_outer_package');
          const aliases = isEuOuter ? [slotLabel, '外包装/标签实拍图-欧盟', '外包装标签实拍图-欧盟', '外包装标签实拍图欧盟'] : [slotLabel];
          const labelCandidates = Array.from(document.querySelectorAll('label,span,div,td,th'))
            .filter(visible)
            .map(el => ({el, text:textOf(el), rect:rectOf(el)}))
            .filter(item => aliases.some(alias => item.text.includes(alias) || labelNorm(item.text).includes(labelNorm(alias))))
            .sort((a, b) => {
              const smallA = a.text.length <= 160 && a.rect.w <= 520 && a.rect.h <= 140 ? 0 : 1;
              const smallB = b.text.length <= 160 && b.rect.w <= 520 && b.rect.h <= 140 ? 0 : 1;
              return smallA - smallB || (a.rect.w * a.rect.h) - (b.rect.w * b.rect.h) || a.text.length - b.text.length;
            });
          const label = labelCandidates[0]?.el;
          if (!label) return {ok:false, missing_slot:true, reason:`未找到${slotLabel}槽位`};
          const row = label.closest('.qualification-module-item, .ant-form-item, tr, li') || label.parentElement;
          if (!row) return {ok:false, reason:`未找到${slotLabel}所在行`};
          const dangerous = Array.from(row.querySelectorAll('button,a,span,div'))
            .filter(visible)
            .find(el => ['发布','继续发布','确认发布','提交发布','保存并发布','保存并移入待发布'].includes(norm(el.innerText || el.textContent)));
          if (dangerous) return {ok:false, reason:`${slotLabel}槽位附近出现危险动作：${norm(dangerous.innerText || dangerous.textContent)}`};
          const bankMenuText = '图片银行（速卖通）';
          const preferredTexts = ['添加图片', '选择图片', '上传图片', '图片银行'];
          const rowRect = rectOf(row);
          const addPlaceholder = Array.from(row.querySelectorAll('img')).filter(visible).map(img => ({el:img, src:String(img.getAttribute('src') || ''), rect:rectOf(img)}))
            .find(x => x.src.includes('addImg') || x.src.includes('addimg'));
          if (addPlaceholder) {
            const clickTarget = addPlaceholder.el.closest('button,a,[role="button"],.operate-box,.add-img,.upload-img,div,span') || addPlaceholder.el;
            clickTarget.scrollIntoView({block:'center', inline:'nearest'});
            return {ok:true, text:'添加图片', class_name:String(clickTarget.className || ''), rect:rectOf(clickTarget), placeholder:true};
          }
          const isRightSideDanger = (x) => {
            const text = `${x.text} ${x.cls}`.toLowerCase();
            const nearRight = x.rect.x + x.rect.w / 2 > rowRect.x + rowRect.w * 0.58;
            return nearRight && (x.text.includes('删除') || text.includes('delete') || text.includes('trash') || text.includes('remove'));
          };
          const isLowerLeftTool = (x) => {
            const centerX = x.rect.x + x.rect.w / 2;
            const centerY = x.rect.y + x.rect.h / 2;
            const nearLeft = centerX <= rowRect.x + Math.max(96, rowRect.w * 0.32);
            const lower = centerY >= rowRect.y + rowRect.h * 0.45;
            const small = x.rect.w <= 56 && x.rect.h <= 56;
            const cls = x.cls.toLowerCase();
            const label = `${x.text} ${x.cls}`;
            return nearLeft && lower && small && !isRightSideDanger(x) && !/(删除|delete|trash|remove|close)/i.test(label)
              && (cls.includes('tool') || cls.includes('operate') || cls.includes('icon') || cls.includes('more') || !x.text);
          };
          const isEmptyAddSlot = (x) => {
            const cls = x.cls.toLowerCase();
            const label = `${x.text} ${x.cls}`;
            return !isRightSideDanger(x) && (x.text.includes('添加图片') || x.text.includes('选择图片') || cls.includes('add') || cls.includes('upload') || /addimg|add-img|upload-img/i.test(label));
          };
          const controls = Array.from(row.querySelectorAll('button,a,[role="button"],.operate-box,.icon-operate,.add-img,.upload-img,span,div'))
            .filter(visible)
            .map(el => ({el, text:norm(el.innerText || el.textContent), cls:String(el.className || ''), rect:rectOf(el)}))
            .filter(x => {
              if (x.text === '生成标签' || x.text === '删除' || x.text === '预览') return false;
              if (x.cls.includes('disabled')) return false;
              if (isRightSideDanger(x)) return false;
              if (preferredTexts.some(t => x.text.includes(t))) return true;
              if (isEmptyAddSlot(x) || isLowerLeftTool(x)) return true;
              const cls = x.cls.toLowerCase();
              const classLooksLikeAddMenu = (
                cls.includes('add')
                || cls.includes('upload')
                || cls.includes('operate')
                || cls.includes('icon-operate')
              );
              return classLooksLikeAddMenu && !x.text.match(/^\d+\s*x\s*\d+$/i) && bankMenuText;
            })
            .sort((a, b) => {
              const score = (x) => {
                if (isEmptyAddSlot(x)) return 0;
                if (isLowerLeftTool(x)) return 1;
                if (x.text.includes('添加图片')) return 2;
                if (x.text.includes('图片银行')) return 3;
                if (preferredTexts.some(t => x.text.includes(t))) return 4;
                return 3;
              };
              return score(a) - score(b) || (a.rect.w * a.rect.h) - (b.rect.w * b.rect.h);
            });
          const picked = controls[0];
          if (!picked) return {ok:false, reason: slotLabel === '外包装/标签实拍图-欧盟' ? '欧盟外包装图槽位没有可点击的图片选择入口' : `${slotLabel}槽位没有可点击的图片选择入口`};
          picked.el.scrollIntoView({block:'center', inline:'nearest'});
          return {ok:true, text:picked.text, class_name:picked.cls, rect:rectOf(picked.el)};
        }''', slot_label)
        if not target.get('ok'):
            return target
        self._click_rect_center(page, target['rect'])
        page.wait_for_timeout(1200)
        self._dismiss_blocking_modals(page)
        opened = page.evaluate(r'''() => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
          const body = textOf(document.body || document.documentElement);
          const hasBankMenu = Array.from(document.querySelectorAll('li,button,a,span,div')).filter(visible).some(el => textOf(el).includes('图片银行（速卖通）'));
          const hasImageDialog = Array.from(document.querySelectorAll('.ant-modal, .ant-modal-wrap, [role="dialog"]')).filter(visible).some(el => {
            const text = textOf(el);
            return text.includes('图片') || text.includes('上传') || text.includes('图片银行');
          });
          return {ok: hasBankMenu || hasImageDialog, has_bank_menu: hasBankMenu, has_image_dialog: hasImageDialog, body_excerpt: body.slice(-500)};
        }''')
        if not opened.get('ok'):
            return {'ok': False, 'reason': '点击欧盟外包装图槽位后未出现图片选择菜单或图片弹窗', 'target': target, 'opened': opened}
        return {'ok': True, 'target': target, 'opened': opened}

    def _open_smt_image_bank_from_picker(self, page: Page, require_menu: bool = False) -> dict[str, Any]:
        clicked = page.evaluate(r'''(requireMenu) => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
          const rectOf = (el) => {
            const r = el.getBoundingClientRect();
            return {x:r.x, y:r.y, w:r.width, h:r.height};
          };
          const body = textOf(document.body || document.documentElement);
          const modalAlreadyOpen = Array.from(document.querySelectorAll('.ant-modal, .ant-modal-wrap, [role="dialog"]')).filter(visible).some(el => {
            const text = textOf(el);
            return text.includes('从图片银行选择') || text.includes('图片银行的分组') || text.includes('请输入图片名称');
          });
          const exact = Array.from(document.querySelectorAll('li,button,a,span,div'))
            .filter(visible)
            .find(el => textOf(el) === '图片银行（速卖通）');
          const target = exact || Array.from(document.querySelectorAll('li,button,a,span,div'))
            .filter(visible)
            .find(el => textOf(el).includes('图片银行') && textOf(el).includes('速卖通'));
          if (!target) {
            if (modalAlreadyOpen && !requireMenu) return {ok:true, already_open:true, reason:'图片银行弹窗已打开'};
            return {ok:false, reason:'未看到图片银行（速卖通）菜单', body_excerpt:body.slice(-500)};
          }
          return {ok:true, rect:rectOf(target), text:textOf(target)};
        }''', require_menu)
        if not clicked.get('ok'):
            return clicked
        if clicked.get('rect'):
            self._click_rect_center(page, clicked['rect'])
            page.wait_for_timeout(1800)
        ready = page.evaluate(r'''() => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
          const modal = Array.from(document.querySelectorAll('.ant-modal, .ant-modal-wrap, [role="dialog"]')).filter(visible).find(el => {
            const text = textOf(el);
            return text.includes('图片') || text.includes('图片银行') || text.includes('选择图片');
          });
          if (!modal) return {ok:false, reason:'图片银行弹窗未打开'};
          return {ok:true, text:textOf(modal).slice(0, 500)};
        }''')
        if not ready.get('ok'):
            return ready
        return {'ok': True, 'clicked': clicked, 'ready': ready}

    def _select_image_bank_asset_by_filename(self, page: Page, filename: str) -> dict[str, Any]:
        self._dismiss_blocking_modals(page)
        filled_search = page.evaluate(r'''(filename) => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
          const modal = Array.from(document.querySelectorAll('.ant-modal, .ant-modal-wrap, [role="dialog"]')).filter(visible).reverse().find(el => {
            const text = textOf(el);
            return text.includes('图片') || text.includes('选择图片') || text.includes('图片银行');
          });
          if (!modal) return {ok:false, reason:'未找到图片银行弹窗'};
          const setValue = (el, value) => {
            const proto = el.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
            const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
            if (setter) setter.call(el, value);
            else el.value = value;
            el.dispatchEvent(new Event('input', {bubbles:true}));
            el.dispatchEvent(new Event('change', {bubbles:true}));
            return true;
          };
          const inputs = Array.from(modal.querySelectorAll('input,textarea')).filter(visible).filter(el => !el.disabled);
          const preferred = inputs.find(el => {
            const hint = `${el.placeholder || ''} ${el.name || ''} ${el.id || ''}`;
            return /搜索|图片|名称|文件|关键字|keyword|name/i.test(hint);
          }) || inputs[0];
          if (!preferred) return {ok:false, reason:'图片银行未找到可输入图片名称的搜索框'};
          setValue(preferred, filename);
          const buttons = Array.from(modal.querySelectorAll('button,a,span,div')).filter(visible);
          const search = buttons.find(el => ['搜索','查询'].includes(textOf(el).replace(/\s+/g, '')));
          if (!search) return {ok:false, reason:'图片银行未找到搜索按钮'};
          return {
            ok:true,
            filled:true,
            search_text: filename,
            search_rect: (() => { const r = search.getBoundingClientRect(); return {x:r.x,y:r.y,w:r.width,h:r.height}; })(),
          };
        }''', filename)
        if not filled_search.get('ok'):
            return filled_search
        self._click_rect_center(page, filled_search['search_rect'])
        page.wait_for_timeout(2000)
        pick = page.evaluate(r'''(filename) => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
          const rectOf = (el) => {
            const r = el.getBoundingClientRect();
            return {x:r.x, y:r.y, w:r.width, h:r.height};
          };
          const attrText = (el) => [el.getAttribute('src'), el.getAttribute('alt'), el.getAttribute('title'), el.getAttribute('data-name'), el.getAttribute('data-filename')]
            .map(v => String(v || '')).join(' ');
          const modal = Array.from(document.querySelectorAll('.ant-modal, .ant-modal-wrap, [role="dialog"]')).filter(visible).reverse().find(el => {
            const text = textOf(el);
            return text.includes('图片') || text.includes('选择图片') || text.includes('图片银行');
          });
          if (!modal) return {ok:false, reason:'图片银行弹窗已关闭或未打开'};
          const candidates = Array.from(modal.querySelectorAll('li,tr,.img-item,.image-item,.ant-image,div,span,img'))
            .filter(visible)
            .map(el => ({el, text: `${textOf(el)} ${attrText(el)}`.trim(), rect:rectOf(el)}))
            .filter(x => x.text.includes(filename));
          const picked = candidates.find(x => x.el.tagName === 'IMG') || candidates.sort((a, b) => a.text.length - b.text.length)[0];
          if (!picked) return {ok:false, reason:`图片银行未找到文件：${filename}`, sample:textOf(modal).slice(0, 500)};
          const target = picked.el.closest('.img-item,.image-item,li,tr,div') || picked.el;
          return {ok:true, text:picked.text.slice(0, 300), rect:rectOf(target)};
        }''', filename)
        if not pick.get('ok'):
            return pick
        self._click_rect_center(page, pick['rect'])
        page.wait_for_timeout(700)
        confirm = self._click_safe_modal_button(page, ['确定', '确认', '选用', '选择', '插入', '使用'])
        if not confirm.get('ok'):
            return {**confirm, 'selection': pick}
        page.wait_for_timeout(1500)
        return {'ok': True, 'filename': filename, 'search': filled_search, 'picked': pick, 'confirm': confirm}

    def _click_safe_modal_button(self, page: Page, labels: list[str]) -> dict[str, Any]:
        last_result: dict[str, Any] = {}
        for attempt in range(2):
            result = page.evaluate(r'''(labels) => {
              const visible = (el) => {
                const r = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
              };
              const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
              const norm = (s) => String(s || '').replace(/\s+/g, '').trim();
              const rectOf = (el) => {
                const r = el.getBoundingClientRect();
                return {x:r.x, y:r.y, w:r.width, h:r.height};
              };
              const modals = Array.from(document.querySelectorAll('.ant-modal, .ant-modal-wrap, [role="dialog"]')).filter(visible).reverse();
              const modal = modals[0];
              if (!modal) return {ok:false, reason:'未找到可确认的弹窗'};
              const modalText = textOf(modal);
              const dangerousTerms = ['发布', '立即发布', '继续发布', '保存并发布', '确认发布', '提交发布', '保存并移入待发布', '移入待发布'];
              const dangerousTerm = dangerousTerms.find(term => norm(modalText).includes(norm(term)));
              if (dangerousTerm) return {ok:false, reason:`检测到危险弹窗：${dangerousTerm}`, modal_text:modalText.slice(0, 300)};
              const buttons = Array.from(modal.querySelectorAll('button,a,span,div')).filter(visible);
              const target = buttons.find(el => labels.includes(norm(el.innerText || el.textContent)) && !el.disabled);
              if (!target) return {ok:false, reason:`未找到确认按钮：${labels.join('/')}`, modal_text:modalText.slice(0, 300)};
              return {ok:true, text:norm(target.innerText || target.textContent), rect:rectOf(target)};
            }''', labels)
            if result.get('ok'):
                self._click_rect_center(page, result['rect'])
                return result
            last_result = result
            modal_text = str(result.get('modal_text') or '')
            if attempt == 0 and ('公告' in modal_text or '通知' in modal_text or '小秘公告' in modal_text):
                dismissed = self._dismiss_blocking_modals(page)
                if dismissed:
                    page.wait_for_timeout(500)
                    continue
        return last_result

    def _select_editor_category(self, page: Page, keyword: str, match_text: str) -> dict[str, Any]:
        body_state = self._editor_required_defaults_state(page)
        if body_state.get('category_selected'):
            return {'ok': True, 'already_selected': True, 'text': body_state.get('category_text')}

        self._dismiss_blocking_modals(page)
        page.evaluate('window.scrollTo(0, 0)')
        self._wait_for_body_text(page, ['产品分类', '选择分类', '基本信息'], timeout=15000)
        page.wait_for_timeout(800)
        category_button = self._find_editor_category_button(page)
        if not category_button:
            return {'ok': False, 'reason': '未找到选择分类按钮'}
        self._click_rect_center(page, category_button['rect'])
        page.wait_for_timeout(1000)
        if self._dismiss_blocking_modals(page):
            page.evaluate('window.scrollTo(0, 0)')
            page.wait_for_timeout(800)
            category_button = self._find_editor_category_button(page)
            if not category_button:
                return {'ok': False, 'reason': '公告关闭后未找到选择分类按钮'}
            self._click_rect_center(page, category_button['rect'])
            page.wait_for_timeout(1000)
        try:
            page.locator('.ant-modal input[placeholder*="搜索分类"]').first.fill(keyword, timeout=8000)
            page.keyboard.press('Enter')
            page.locator('.ant-modal button:has-text("搜索")').first.click(timeout=3000)
        except TimeoutError:
            self._close_visible_modal(page)
            return {'ok': False, 'reason': '未找到分类弹窗搜索控件'}
        page.wait_for_timeout(2000)
        row = page.evaluate(r'''(matchText) => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const rectOf = (el) => {
            const r = el.getBoundingClientRect();
            return {x:r.x, y:r.y, w:r.width, h:r.height};
          };
          const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
          const modal = Array.from(document.querySelectorAll('[role="dialog"], .ant-modal, .ant-modal-wrap')).find(el => visible(el) && textOf(el).includes(matchText));
          if (!modal) return {ok:false, reason:`未找到分类结果：${matchText}`};
          const candidates = Array.from(modal.querySelectorAll('tr,li,div,span')).filter(visible).map(el => ({el, text:textOf(el)})).filter(x => x.text.includes(matchText) || x.text.includes('立牌类谷子'));
          const picked = candidates
            .filter(x => x.text.includes('ACG Stand') || x.text.includes('立牌类谷子'))
            .sort((a, b) => a.text.length - b.text.length)[0]
            || candidates.sort((a, b) => a.text.length - b.text.length)[0];
          if (!picked) return {ok:false, reason:`未找到分类结果：${matchText}`};
          const target = picked.el.closest('tr,li') || picked.el;
          return {ok:true, text:picked.text, rect:rectOf(target)};
        }''', match_text)
        if not row.get('ok'):
            self._close_visible_modal(page)
            return row
        self._click_rect_center(page, row['rect'])
        page.wait_for_timeout(800)
        selected = self._click_visible_text(page, '选择', preferred_tags=('BUTTON', 'A'))
        if not selected:
            selected = self._click_visible_text(page, '确定', preferred_tags=('BUTTON', 'A'))
        page.wait_for_timeout(1800)
        if selected:
            self._wait_for_body_text(page, ['ACG Stand', '立牌类谷子'], timeout=6000)
        state = self._editor_required_defaults_state(page)
        ok = bool(state.get('category_selected'))
        if not ok:
            self._close_visible_modal(page)
        return {
            'ok': ok,
            'text': row.get('text'),
            'category_text': state.get('category_text'),
            'selected_action_clicked': bool(selected),
            'reason': None if ok else '分类结果已点击，但未检测到页面分类回显',
        }

    def _find_editor_category_button(self, page: Page) -> dict[str, Any] | None:
        return page.evaluate(r'''() => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const norm = (s) => String(s || '').replace(/\s+/g, '').trim();
          const docY = (el) => {
            const r = el.getBoundingClientRect();
            return r.y + window.scrollY;
          };
          const rectOf = (el) => {
            const r = el.getBoundingClientRect();
            return {x:r.x,y:r.y,w:r.width,h:r.height};
          };
          const labels = Array.from(document.querySelectorAll('label,span,div,td,th')).filter(visible).filter(el => norm(el.innerText || el.textContent).includes('产品分类'));
          const label = labels.sort((a, b) => Math.abs(docY(a) - window.scrollY - 300) - Math.abs(docY(b) - window.scrollY - 300))[0];
          const labelY = label ? docY(label) : null;
          const buttons = Array.from(document.querySelectorAll('button,a,span,div,[role="button"]'))
            .filter(visible)
            .filter(el => norm(el.innerText || el.textContent) === '选择分类')
            .map(el => ({el, rect:rectOf(el), distance: labelY === null ? 0 : Math.abs(docY(el) - labelY)}));
          const picked = (labelY === null ? buttons : buttons.filter(x => x.distance < 90))
            .sort((a, b) => a.distance - b.distance || a.rect.x - b.rect.x)[0] || buttons[0];
          return picked ? {rect:picked.rect} : null;
        }''')

    def _fill_category_required_attributes(self, page: Page) -> dict[str, Any]:
        age = self._check_choice_by_text(page, '14 + y(14+y)')
        if not age.get('ok'):
            age = self._check_choice_by_text(page, '18+(18+)')
        origin = self._choose_ant_select_near_label(page, '产地', ['中国大陆', 'Mainland China', 'China'])
        brand = self._choose_ant_select_near_label(page, '品牌', ['NONE', 'NoEnName', '无品牌'])
        item_type = self._choose_ant_select_near_label(page, '产品类型', ['Model', 'Puppets', 'Other'])
        chemical = self._choose_ant_select_near_label(page, '高关注化学品', ['None', '无', 'No'])
        generic = self._fill_unselected_category_attribute_selects(page)
        result = {
            'age': age,
            'origin': origin,
            'brand': brand,
            'item_type': item_type,
            'high_concerned_chemical': chemical,
            'generic_required_attributes': generic,
        }
        missing = [name for name, value in result.items() if not value.get('ok')]
        return {'ok': not missing, 'missing': missing, **result}

    def _fill_unselected_category_attribute_selects(self, page: Page) -> dict[str, Any]:
        filled: list[dict[str, Any]] = []
        text_filled = self._fill_category_attribute_text_inputs(page)
        skipped: list[str] = []
        attempted: set[str] = set()
        for _ in range(24):
            target = page.evaluate(r'''(attempted) => {
              const visible = (el) => {
                const r = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
              };
              const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
              const rectOf = (el) => {
                const r = el.getBoundingClientRect();
                return {x:r.x, y:r.y, w:r.width, h:r.height};
              };
              const items = Array.from(document.querySelectorAll('.attr-form-item')).filter(visible).map(el => {
                const text = textOf(el);
                const select = Array.from(el.querySelectorAll('.ant-select')).filter(visible).find(sel => textOf(sel).includes('请选择'));
                const label = text.replace(/\s*请选择\s*$/, '').slice(0,120);
                return select && !attempted.includes(label) ? {label, rect:rectOf(select)} : null;
              }).filter(Boolean);
              return items[0] || null;
            }''', list(attempted))
            if not target:
                break
            label = str(target.get('label') or '')
            attempted.add(label)
            priorities = self._category_attribute_priorities(label)
            selected = self._select_category_attribute_value(page, label, priorities)
            if selected.get('ok'):
                filled.append({'label': label, 'value': selected.get('value'), 'strategy': selected.get('strategy')})
            else:
                page.keyboard.press('Escape')
                page.wait_for_timeout(200)
                skipped.append(label)

        remaining = page.evaluate(r'''() => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
          return Array.from(document.querySelectorAll('.attr-form-item')).filter(visible)
            .map(el => textOf(el))
            .filter(text => text.includes('请选择'))
            .map(text => text.replace(/\s*请选择\s*$/, '').slice(0,120));
        }''')
        return {'ok': not remaining, 'filled': filled, 'text_filled': text_filled, 'skipped': skipped, 'remaining': remaining, 'attempted': sorted(attempted)}

    def _select_category_attribute_value(self, page: Page, label: str, priorities: list[str]) -> dict[str, Any]:
        for priority in priorities[:4]:
            prepared = self._focus_category_attribute_input(page, label, priority)
            if not prepared.get('ok'):
                continue
            page.wait_for_timeout(800)
            option = self._visible_category_attribute_option(page, [priority, *priorities])
            if option:
                page.keyboard.press('ArrowDown')
                page.wait_for_timeout(120)
                page.keyboard.press('Enter')
                page.wait_for_timeout(650)
                state = self._category_attribute_row_state(page, label)
                if state.get('ok'):
                    return {'ok': True, 'value': state.get('text') or option.get('text'), 'strategy': 'keyboard_select'}

                self._click_rect_center(page, option['rect'])
                page.wait_for_timeout(650)
                state = self._category_attribute_row_state(page, label)
                if state.get('ok'):
                    return {'ok': True, 'value': state.get('text') or option.get('text'), 'strategy': 'option_click'}

            fallback = self._fill_category_attribute_free_text(page, label, priority)
            if fallback.get('ok'):
                page.wait_for_timeout(350)
                state = self._category_attribute_row_state(page, label)
                if state.get('ok'):
                    return {'ok': True, 'value': fallback.get('value'), 'strategy': 'free_text'}
        return {'ok': False, 'reason': 'no_selectable_option'}

    def _focus_category_attribute_input(self, page: Page, label: str, value: str) -> dict[str, Any]:
        return page.evaluate(r'''({label, value}) => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
          const item = Array.from(document.querySelectorAll('.attr-form-item')).filter(visible).find(el => textOf(el).includes(label));
          if (!item) return {ok:false, reason:'attribute_not_found'};
          const select = Array.from(item.querySelectorAll('.ant-select')).filter(visible)[0];
          const input = select ? Array.from(select.querySelectorAll('input')).filter(visible).find(el => !el.disabled) : null;
          if (!select || !input) return {ok:false, reason:'input_not_found', text:textOf(item).slice(0,160)};
          select.scrollIntoView({block:'center', inline:'nearest'});
          select.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, cancelable:true, view:window}));
          select.dispatchEvent(new MouseEvent('mouseup', {bubbles:true, cancelable:true, view:window}));
          select.dispatchEvent(new MouseEvent('click', {bubbles:true, cancelable:true, view:window}));
          input.click();
          input.focus();
          const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
          if (setter) setter.call(input, String(value));
          else input.value = String(value);
          input.dispatchEvent(new InputEvent('input', {bubbles:true, inputType:'insertText', data:String(value)}));
          input.dispatchEvent(new Event('change', {bubbles:true}));
          return {ok:true, label, value, text:textOf(item).slice(0,160), className:String(select.className || '')};
        }''', {'label': label, 'value': value})

    def _category_attribute_row_state(self, page: Page, label: str) -> dict[str, Any]:
        return page.evaluate(r'''(label) => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
          const item = Array.from(document.querySelectorAll('.attr-form-item')).filter(visible).find(el => textOf(el).includes(label));
          if (!item) return {ok:false, reason:'attribute_not_found'};
          const text = textOf(item);
          return {ok: !text.includes('请选择'), text:text.slice(0,160)};
        }''', label)

    def _visible_category_attribute_option(self, page: Page, priorities: list[str]) -> dict[str, Any] | None:
        return page.evaluate(r'''(priorities) => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
          const norm = (s) => String(s || '').replace(/\s+/g, '').toLowerCase();
          const rectOf = (el) => {
            const r = el.getBoundingClientRect();
            return {x:r.x, y:r.y, w:r.width, h:r.height};
          };
          const options = Array.from(document.querySelectorAll('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option, .ant-select-dropdown:not(.ant-select-dropdown-hidden) [role="option"]'))
            .filter(visible)
            .map(el => ({el, text:textOf(el)}))
            .filter(x => x.text && !x.text.includes('暂无数据') && !x.text.includes('请选择'));
          if (!options.length) return null;
          for (const priority of priorities) {
            const match = options.find(x => norm(x.text).includes(norm(priority)));
            if (match) return {text:match.text, rect:rectOf(match.el)};
          }
          const picked = options.sort((a, b) => a.text.length - b.text.length)[0];
          return {text:picked.text, rect:rectOf(picked.el)};
        }''', priorities)

    def _search_category_attribute_option(self, page: Page, priorities: list[str]) -> dict[str, Any] | None:
        for priority in priorities[:4]:
            page.keyboard.press('Control+A')
            page.keyboard.press('Backspace')
            page.keyboard.type(str(priority))
            page.wait_for_timeout(800)
            option = page.evaluate(r'''(priorities) => {
              const visible = (el) => {
                const r = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
              };
              const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
              const norm = (s) => String(s || '').replace(/\s+/g, '').toLowerCase();
              const rectOf = (el) => {
                const r = el.getBoundingClientRect();
                return {x:r.x, y:r.y, w:r.width, h:r.height};
              };
              const options = Array.from(document.querySelectorAll('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option, .ant-select-dropdown:not(.ant-select-dropdown-hidden) [role="option"]'))
                .filter(visible)
                .map(el => ({el, text:textOf(el)}))
                .filter(x => x.text && !x.text.includes('暂无数据') && !x.text.includes('请选择'));
              if (!options.length) return null;
              for (const priority of priorities) {
                const match = options.find(x => norm(x.text).includes(norm(priority)));
                if (match) return {text:match.text, rect:rectOf(match.el)};
              }
              const picked = options.sort((a, b) => a.text.length - b.text.length)[0];
              return {text:picked.text, rect:rectOf(picked.el)};
            }''', priorities)
            if option:
                return option
        return None

    def _fill_category_attribute_free_text(self, page: Page, label: str, value: str) -> dict[str, Any]:
        page.keyboard.press('Escape')
        page.wait_for_timeout(150)
        return page.evaluate(r'''({label, value}) => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
          const setValue = (el, value) => {
            if (!el || el.disabled) return false;
            const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
            if (setter) setter.call(el, value);
            else el.value = value;
            el.dispatchEvent(new InputEvent('input', {bubbles:true, inputType:'insertText', data:value}));
            el.dispatchEvent(new Event('change', {bubbles:true}));
            el.dispatchEvent(new Event('blur', {bubbles:true}));
            return true;
          };
          const item = Array.from(document.querySelectorAll('.attr-form-item')).filter(visible).find(el => textOf(el).includes(label));
          if (!item) return {ok:false, reason:'attribute_not_found'};
          const select = Array.from(item.querySelectorAll('.ant-select')).filter(visible)[0];
          if (!select || !String(select.className || '').includes('ant-select-auto-complete')) {
            return {ok:false, reason:'not_free_text_attribute'};
          }
          const input = Array.from(select.querySelectorAll('input')).filter(visible).find(el => !el.disabled);
          const ok = setValue(input, value);
          return {ok, label, value, text:textOf(item).slice(0,160)};
        }''', {'label': label, 'value': value})

    def _fill_category_attribute_text_inputs(self, page: Page) -> dict[str, Any]:
        return page.evaluate(r'''() => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
          const setValue = (el, value) => {
            if (!el || el.disabled || String(el.value || '').trim()) return false;
            const proto = el.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
            const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
            if (setter) setter.call(el, value);
            else el.value = value;
            el.dispatchEvent(new Event('input', {bubbles:true}));
            el.dispatchEvent(new Event('change', {bubbles:true}));
            el.dispatchEvent(new Event('blur', {bubbles:true}));
            return true;
          };
          const defaults = [
            {label:'型号(Model Number)', value:'ACG-Keychain'},
            {label:'警告(Warning)', value:'Keep away from fire'},
            {label:'尺寸(Dimensions)', value:'10cm'},
            {label:'动漫电影游戏人物角色(ACG Character)', value:'Hermione Granger'},
          ];
          const filled = [];
          for (const item of defaults) {
            const row = Array.from(document.querySelectorAll('.attr-form-item')).filter(visible).find(el => textOf(el).includes(item.label));
            const input = row ? Array.from(row.querySelectorAll('input,textarea')).filter(visible).find(el => !el.disabled) : null;
            if (setValue(input, item.value)) filled.push(item);
          }
          return {ok:true, filled};
        }''')

    def _category_attribute_priorities(self, label: str) -> list[str]:
        text = label.lower()
        if 'mfg series' in text or '系列' in label:
            return ['Resin', '树脂', 'Model']
        if 'material' in text or '材质' in label:
            return ['Acrylic', '亚克力', 'PVC', 'Plastic']
        if 'theme' in text or '主题' in label:
            return ['Anime', 'Movie', 'TV', 'Cartoon']
        if 'gender' in text or '性别' in label:
            return ['Unisex', '男女', '通用']
        if 'condition' in text or '状态' in label:
            return ['In-Stock', '现货', 'New']
        if 'remote' in text or '遥控' in label or 'electric' in text or '带电' in label or 'original package' in text or '原盒' in label:
            return ['No', '否', 'None']
        if 'source' in text or '动漫来源' in label:
            return ['Japan', 'Anime', 'Other']
        if 'item type' in text or 'puppets' in text or '玩偶' in label or '产品类型' in label:
            return ['Model', 'Figure', 'Puppets', 'Other']
        if 'completion' in text or '完成度' in label:
            return ['Finished Goods', 'Finished', '成品']
        if 'commodity' in text or '商品属性' in label:
            return ['Finished Goods', 'Accessories', 'Other']
        if 'scale' in text or '比例' in label:
            return ['1/12', '1:12', 'Other']
        if 'acg name' in text or '动漫电影游戏名称' in label or 'version' in text or '版本' in label:
            return ['Other', '其他', 'Anime']
        return ['Other', '其他', 'No', 'None']

    def _apply_reference_templates_on_page(self, page: Page, priorities: list[str]) -> dict[str, Any]:
        if not priorities:
            return {'ok': True, 'skipped': True, 'reason': 'no_reference_template_config'}
        clicked = page.evaluate(r'''(priorities) => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
          const norm = (s) => String(s || '').replace(/\s+/g, '').trim();
          const rectOf = (el) => {
            const r = el.getBoundingClientRect();
            return {x:r.x, y:r.y, w:r.width, h:r.height};
          };
          const root = Array.from(document.querySelectorAll('section,form,div'))
            .filter(visible)
            .find(el => textOf(el).includes('属性信息') && textOf(el).includes('引用模板'));
          const scope = root || document;
          const select = Array.from(scope.querySelectorAll('.ant-select')).filter(visible).find(el => {
            const text = textOf(el);
            return text.includes('请选择引用模板') || text.includes('引用模板') || text.includes('---请选择引用模板---');
          });
          if (!select) return {ok:false, reason:'未找到属性信息引用模板选择框'};
          const selectedText = textOf(select);
          const terms = priorities.map(String).filter(Boolean);
          if (terms.some(term => selectedText.includes(term)) && !selectedText.includes('请选择')) {
            return {ok:true, already_selected:true, text:selectedText};
          }
          select.scrollIntoView({block:'center', inline:'nearest'});
          return {ok:true, rect:rectOf(select), text:norm(selectedText)};
        }''', priorities)
        if not clicked.get('ok') or clicked.get('already_selected'):
            return clicked
        self._click_rect_center(page, clicked['rect'])
        page.wait_for_timeout(800)
        result = self._click_ant_option_near_rect(page, priorities, clicked['rect'])
        verify = page.evaluate(r'''(priorities) => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
          const select = Array.from(document.querySelectorAll('.ant-select')).filter(visible).find(el => {
            const text = textOf(el);
            return text.includes('引用模板') || priorities.some(term => text.includes(String(term)));
          });
          const text = textOf(select || document.body);
          return {ok: priorities.some(term => text.includes(String(term))), text:text.slice(0, 160)};
        }''', priorities)
        return {**result, 'verified': verify, 'ok': bool(result.get('ok') and verify.get('ok'))}

    def _apply_dxm_reference_templates_on_page(self, page: Page, values: dict[str, Any]) -> dict[str, dict[str, Any]]:
        configs = self._dxm_reference_template_configs(values)
        results: dict[str, dict[str, Any]] = {}
        label_sections = {
            'freight': '运费模板',
            'service': '服务模板',
            'eu_responsible': '欧盟责任人',
            'manufacturer': '品牌制造商',
        }
        unsupported_labels = {
            'description': '描述信息',
            'compliance': '合规信息',
            'semi_managed': '半托管信息',
        }
        for section in DXM_REFERENCE_TEMPLATE_SECTIONS:
            config = configs.get(section)
            if not config:
                continue
            names = list(config.get('names') or [])
            required = bool(config.get('required', True))
            if not names:
                result = {'ok': not required, 'skipped': True, 'reason': 'no_reference_template_config'}
            elif section == 'attribute_info':
                result = self._apply_reference_templates_on_page(page, names)
            elif section in label_sections:
                result = self._choose_ant_select_near_label(page, label_sections[section], names)
            else:
                result = {
                    'ok': False,
                    'reason': f'{unsupported_labels[section]}引用模板暂未实现真实控件：{", ".join(names)}',
                    'optional': not required,
                }
            results[section] = {**result, 'section': section, 'names': names, 'required': required}
        return results

    def _dxm_reference_template_configs(self, values: dict[str, Any]) -> dict[str, dict[str, Any]]:
        raw = values.get('dxm_reference_templates_resolved') or values.get('dxm_reference_templates')
        if not raw and any(section in values for section in DXM_REFERENCE_TEMPLATE_SECTIONS):
            raw = values
        if isinstance(raw, dict):
            return {
                section: self._normalize_dxm_reference_template_config(raw.get(section))
                for section in DXM_REFERENCE_TEMPLATE_SECTIONS
                if section in raw
            }
        legacy = {
            'attribute_info': values.get('attribute_template_priorities'),
            'freight': values.get('freight_template_priorities'),
            'service': values.get('service_template_priorities'),
            'eu_responsible': values.get('eu_responsible_priorities'),
            'manufacturer': values.get('manufacturer_priorities'),
        }
        return {
            section: {'names': names, 'required': True}
            for section, names in legacy.items()
            if names
        }

    def _normalize_dxm_reference_template_config(self, config: Any) -> dict[str, Any]:
        if isinstance(config, dict):
            names = config.get('names') or config.get('templates') or config.get('template_names') or config.get('priorities') or []
            if isinstance(names, str):
                names = [names]
            return {'names': [str(name) for name in (names or []) if str(name or '').strip()], 'required': bool(config.get('required', True))}
        if isinstance(config, str):
            return {'names': [config], 'required': True}
        if isinstance(config, list):
            return {'names': [str(name) for name in config if str(name or '').strip()], 'required': True}
        return {'names': [], 'required': True}

    def _missing_required_reference_template_results(self, results: dict[str, dict[str, Any]]) -> list[str]:
        return [
            f'dxm_reference_templates.{section}'
            for section, result in results.items()
            if result.get('required', True) and not result.get('ok')
        ]

    def _fill_customs_supervision_attribute(self, page: Page, priorities: list[str]) -> dict[str, Any]:
        configured = page.evaluate(r'''() => {
          const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const rectOf = (el) => {
            const r = el.getBoundingClientRect();
            return {x:r.x, y:r.y, w:r.width, h:r.height};
          };
          const body = textOf(document.body || document.documentElement);
          const compact = body.replace(/\s+/g, '');
          const valueAfter = (label) => {
            const idx = compact.indexOf(label);
            if (idx < 0) return '';
            return compact.slice(idx + label.length).replace(/^[：:]/, '').slice(0, 40);
          };
          const valueAfterAny = (labels) => {
            for (const label of labels) {
              const value = valueAfter(label);
              if (value) return value;
            }
            return '';
          };
          const hasTaxCode = compact.includes('税率代码') && /\d{8,12}/.test(compact);
          const productNameValue = valueAfterAny(['品名(Productname)', '品名(Product name)', 'Productname', 'Productname:', '品名']);
          const kindValue = valueAfterAny(['种类(Kind)', '种类']);
          const hasProductName = Boolean(productNameValue) && !productNameValue.startsWith('请选择');
          const hasKind = Boolean(kindValue) && !kindValue.startsWith('请选择');
          const hasCustomsArea = compact.includes('海关监管属性') || compact.includes('更新海关监管') || compact.includes('添加海关监管') || compact.includes('添加全球海关监管属性');
          const selectError = compact.includes('请完善海关监管属性') || compact.includes('请选择海关监管属性');
          const customsItem = Array.from(document.querySelectorAll('.ant-form-item')).filter(visible).find(el => textOf(el).includes('海关监管属性'));
          const updateButton = customsItem && Array.from(customsItem.querySelectorAll('button,a,span,div'))
            .find(el => visible(el) && String(el.innerText || el.textContent || '').replace(/\s+/g, '').trim() === '更新海关监管');
          const updateTarget = updateButton && (updateButton.closest('button,a') || updateButton);
          return {
            ok: hasTaxCode && hasCustomsArea && (hasProductName || hasKind) && !selectError,
            has_tax_code: hasTaxCode,
            has_product_name: hasProductName,
            has_kind: hasKind,
            has_customs_area: hasCustomsArea,
            select_error: selectError,
            product_name_value: productNameValue,
            kind_value: kindValue,
            update_rect: updateTarget ? rectOf(updateTarget) : null,
            body_excerpt: body.slice(-800),
          };
        }''')
        if configured.get('ok'):
            if configured.get('update_rect'):
                self._click_rect_center(page, configured['update_rect'])
                page.wait_for_timeout(1500)
                self._dismiss_blocking_modals(page)
                return {'ok': True, 'already_configured': True, 'updated_existing': True, 'state': configured}
            return {'ok': True, 'already_configured': True, 'state': configured}

        opened = page.evaluate(r'''() => {
          const norm = (s) => String(s || '').replace(/\s+/g, '').trim();
          const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const rectOf = (el) => {
            const r = el.getBoundingClientRect();
            return {x:r.x, y:r.y, w:r.width, h:r.height};
          };
          const allowedTexts = ['添加海关监管', '添加全球海关监管属性'];
          const labelNode = Array.from(document.querySelectorAll('label, .ant-form-item-label, .label-wrapper'))
            .filter(visible)
            .find(el => textOf(el).includes('海关监管属性'));
          const customsItem = (labelNode && labelNode.closest('.ant-form-item'))
            || Array.from(document.querySelectorAll('.ant-form-item, .form-item, section')).filter(visible)
              .find(el => textOf(el).includes('海关监管属性'))
            || null;
          if (customsItem) customsItem.scrollIntoView({block:'center', inline:'nearest'});
          const scope = customsItem || document;
          const globalLabel = customsItem && Array.from(customsItem.querySelectorAll('label,span,div,input')).filter(visible)
            .find(el => norm(el.innerText || el.textContent) === '添加全球海关监管属性');
          const globalTarget = globalLabel && (globalLabel.closest('label') || globalLabel);
          if (globalTarget && !String(globalTarget.className || '').includes('checked')) globalTarget.click();
          const buttons = Array.from(scope.querySelectorAll('button,a,span,div,[role="button"]'))
            .filter(visible)
            .filter(el => allowedTexts.includes(norm(el.innerText || el.textContent)) && !el.disabled)
            .map(el => el.closest('button,a,[role="button"]') || el)
            .filter((el, idx, arr) => arr.indexOf(el) === idx);
          const visibleButtons = buttons
            .map(el => ({el, rect:rectOf(el)}))
            .filter(x => x.rect.w > 0 && x.rect.h > 0)
            .sort((a, b) => {
              const rank = (el) => ['BUTTON', 'A'].includes(el.tagName) || el.getAttribute('role') === 'button' ? 0 : 1;
              return rank(a.el) - rank(b.el);
            });
          const button = visibleButtons.find(x => x.rect.y + x.rect.h > 0 && x.rect.y < window.innerHeight)
            || visibleButtons[0]
            || null;
          if (!button) return {ok:false, reason:'未找到可见添加海关监管按钮'};
          button.el.scrollIntoView({block:'center', inline:'nearest'});
          return {ok:true, rect:rectOf(button.el), candidates:buttons.length};
        }''')
        if not opened.get('ok'):
            return opened
        self._click_rect_center(page, opened['rect'])

        try:
            page.wait_for_function(
                r'''() => {
                  const body = document.body ? (document.body.innerText || document.body.textContent || '') : '';
                  return body.includes('海关监管')
                    && (body.includes('品名(Product name)') || body.includes('种类(Kind)'))
                    && body.includes('确定');
                }''',
                timeout=10000,
            )
        except TimeoutError:
            fallback = page.evaluate(r'''() => {
              const norm = (s) => String(s || '').replace(/\s+/g, '').trim();
              const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
              const visible = (el) => {
                const r = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
              };
              const rectOf = (el) => {
                const r = el.getBoundingClientRect();
                return {x:r.x, y:r.y, w:r.width, h:r.height};
              };
              const allowedTexts = ['添加海关监管', '添加全球海关监管属性'];
              const labelNode = Array.from(document.querySelectorAll('label, .ant-form-item-label, .label-wrapper'))
                .filter(visible)
                .find(el => textOf(el).includes('海关监管属性'));
              const customsItem = (labelNode && labelNode.closest('.ant-form-item'))
                || Array.from(document.querySelectorAll('.ant-form-item, .form-item, section')).filter(visible)
                  .find(el => textOf(el).includes('海关监管属性'))
                || null;
              if (customsItem) customsItem.scrollIntoView({block:'center', inline:'nearest'});
              const scope = customsItem || document;
              const globalLabel = customsItem && Array.from(customsItem.querySelectorAll('label,span,div,input')).filter(visible)
                .find(el => norm(el.innerText || el.textContent) === '添加全球海关监管属性');
              const globalTarget = globalLabel && (globalLabel.closest('label') || globalLabel);
              if (globalTarget && !String(globalTarget.className || '').includes('checked')) globalTarget.click();
              const button = Array.from(scope.querySelectorAll('button,a,span,div,[role="button"]'))
                .filter(visible)
                .filter(el => allowedTexts.includes(norm(el.innerText || el.textContent)) && !el.disabled)
                .map(el => el.closest('button,a,[role="button"]') || el)
                .filter((el, idx, arr) => arr.indexOf(el) === idx)
                .map(el => ({el, rect:rectOf(el)}))
                .filter(x => x.rect.w > 0 && x.rect.h > 0)
                .sort((a, b) => {
                  const rank = (el) => ['BUTTON', 'A'].includes(el.tagName) || el.getAttribute('role') === 'button' ? 0 : 1;
                  return rank(a.el) - rank(b.el);
                })
                .find(x => x.rect.y + x.rect.h > 0 && x.rect.y < window.innerHeight);
              if (!button) return null;
              return button.rect;
            }''')
            if not fallback:
                return {'ok': False, 'reason': '海关监管弹窗未打开'}
            self._click_rect_center(page, fallback)
            try:
                page.wait_for_function(
                    r'''() => {
                      const body = document.body ? (document.body.innerText || document.body.textContent || '') : '';
                      return body.includes('海关监管')
                        && (body.includes('品名(Product name)') || body.includes('种类(Kind)'))
                        && body.includes('确定');
                    }''',
                    timeout=10000,
                )
            except TimeoutError:
                return {'ok': False, 'reason': '海关监管弹窗未打开'}

        selected_options: list[str] = []
        confirm_texts: list[str] = []
        for _ in range(6):
            modal_state = page.evaluate(r'''() => {
              const norm = (s) => String(s || '').replace(/\s+/g, '').trim();
              const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
              const rectOf = (el) => {
                const r = el.getBoundingClientRect();
                return {x:r.x, y:r.y, w:r.width, h:r.height};
              };
              const modal = Array.from(document.querySelectorAll('.ant-modal, [role="dialog"], .ant-modal-wrap'))
                .find(el => textOf(el).includes('海关监管') && (textOf(el).includes('品名(Product name)') || textOf(el).includes('种类(Kind)')));
              if (!modal) return null;
              const modalText = textOf(modal);
              const selects = Array.from(modal.querySelectorAll('.ant-select'))
                .map(el => {
                  const text = norm(el.innerText || el.textContent);
                  return {el, text, rect:rectOf(el)};
                })
                .filter(x => x.rect.w > 0 && x.rect.h > 0);
              const unresolvedSelect = selects.find(x => !x.text || x.text.includes('请选择') || x.text.includes('请选中')) || null;
              const button = modal && Array.from(modal.querySelectorAll('button'))
                .find(el => norm(el.innerText || el.textContent) === '确定');
              return {
                text: modalText,
                select_rect: unresolvedSelect ? unresolvedSelect.rect : null,
                confirm_rect: button ? rectOf(button) : null,
                is_product_name_step: modalText.includes('品名(Product name)'),
              };
            }''')
            if not modal_state:
                break
            if modal_state.get('select_rect'):
                self._click_rect_center(page, modal_state['select_rect'])
                page.wait_for_timeout(1200)
                if modal_state.get('is_product_name_step'):
                    page.keyboard.press('Enter')
                    page.wait_for_timeout(1200)
                    option = {'ok': True, 'text': 'active-option'}
                else:
                    option = self._click_ant_option_near_rect(
                        page,
                        ['其他', 'Other'],
                        modal_state['select_rect'],
                        required=False,
                    )
                    if not option.get('ok'):
                        return {
                            'ok': False,
                            'reason': '未找到可用海关监管种类选项，已停止避免误选',
                            'state': {'modal_text': str(modal_state.get('text') or '')[:300]},
                        }
                selected_options.append(str(option.get('text') or ''))
            if not modal_state.get('confirm_rect'):
                break
            confirm_texts.append(str(modal_state.get('text') or '')[:300])
            self._click_rect_center(page, modal_state['confirm_rect'])
            page.wait_for_timeout(2500)

        state = page.evaluate(r'''() => {
          const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
          const body = textOf(document.body || document.documentElement);
          const compact = body.replace(/\s+/g, '');
          const valueAfter = (label) => {
            const idx = compact.indexOf(label);
            if (idx < 0) return '';
            return compact.slice(idx + label.length).replace(/^[：:]/, '').slice(0, 40);
          };
          const valueAfterAny = (labels) => {
            for (const label of labels) {
              const value = valueAfter(label);
              if (value) return value;
            }
            return '';
          };
          const modalStillOpen = compact.includes('品名(Productname)') && compact.includes('取消') && compact.includes('确定');
          const hasTaxCode = compact.includes('税率代码') && /\d{8,12}/.test(compact);
          const productNameValue = valueAfterAny(['品名(Productname)', '品名(Product name)', 'Productname', 'Productname:', '品名']);
          const kindValue = valueAfterAny(['种类(Kind)', '种类']);
          const hasProductName = Boolean(productNameValue) && !productNameValue.startsWith('请选择');
          const hasKind = Boolean(kindValue) && !kindValue.startsWith('请选择');
          const hasCustomsArea = compact.includes('海关监管属性') || compact.includes('更新海关监管') || compact.includes('添加海关监管') || compact.includes('添加全球海关监管属性');
          const selectError = compact.includes('请选择海关监管属性') || compact.includes('请完善海关监管属性');
          return {
            ok: !modalStillOpen && hasTaxCode && hasCustomsArea && (hasProductName || hasKind) && !selectError,
            modal_still_open: modalStillOpen,
            has_tax_code: hasTaxCode,
            has_product_name: hasProductName,
            has_kind: hasKind,
            has_customs_area: hasCustomsArea,
            select_error: selectError,
            product_name_value: productNameValue,
            kind_value: kindValue,
            body_excerpt: body.slice(-1000),
          };
        }''')
        return {
            'ok': bool(state.get('ok')),
            'selected': selected_options[-1] if selected_options else None,
            'selected_options': selected_options,
            'confirm_steps': len(confirm_texts),
            'confirm_texts': confirm_texts,
            'state': state,
            'reason': None if state.get('ok') else '海关监管属性未落表',
        }

    def _semi_managed_page_state(self, page: Page) -> dict[str, Any]:
        return page.evaluate(r'''() => {
          const body = String(document.body ? document.body.innerText || document.body.textContent || '' : '');
          const compact = body.replace(/\s+/g, '');
          const blockedTerms = ['产品信息中有错误，请检查', '产品信息中有错误'];
          const blocked = blockedTerms.find(term => compact.includes(term));
          const isEditPage = compact.includes('基本信息') && compact.includes('产品信息') && compact.includes('编辑半托管信息');
          const hasSemiForm = compact.includes('半托管') && (compact.includes('半托管商品信息') || compact.includes('半托管信息') || compact.includes('包装尺寸') || compact.includes('物流属性'));
          return {
            blocked: Boolean(blocked),
            message: blocked || null,
            is_semi_page: hasSemiForm && !isEditPage && !blocked,
            body_excerpt: compact.slice(0, 500),
          };
        }''')

    def _editor_required_defaults_state(self, page: Page) -> dict[str, Any]:
        return page.evaluate(r'''() => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const norm = (s) => String(s || '').replace(/\s+/g, '').trim();
          const hasChinese = (s) => /[\u3400-\u9fff]/.test(String(s || ''));
          const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
          const body = textOf(document.body || document.documentElement);
          const compactBody = norm(body);
          const inputs = Array.from(document.querySelectorAll('input,textarea')).filter(visible);
          const inputByPlaceholder = (placeholder) => inputs.find(el => String(el.placeholder || '') === placeholder && !el.disabled);
          const inputById = (id) => document.getElementById(id);
          const titleInput = inputs.find(el => {
            const r = el.getBoundingClientRect();
            return el.tagName === 'INPUT' && el.type === 'text' && r.width > 500 && r.y < 420;
          });
          const selectTextByInputId = (id) => {
            const input = document.getElementById(id);
            const root = input?.closest('.ant-select');
            return root ? norm(root.innerText || root.textContent) : '';
          };
          const categoryItem = Array.from(document.querySelectorAll('.category-item,.ant-form-item')).filter(visible).map(el => {
            const r = el.getBoundingClientRect();
            return {el, text:textOf(el), compact:norm(el.innerText || el.textContent), rect:r};
          }).filter(item => item.rect.y < 560 && item.compact.includes('产品分类'))
            .sort((a, b) => a.compact.length - b.compact.length)[0];
          const categoryText = categoryItem ? norm(categoryItem.text) : '';
          const values = {
            category_text: categoryText,
            title: titleInput?.value || '',
            declared_value: inputByPlaceholder('请输入货值')?.value || '',
            weight: inputByPlaceholder('请输入重量')?.value || '',
            length: inputByPlaceholder('长')?.value || '',
            width: inputByPlaceholder('宽')?.value || '',
            height: inputByPlaceholder('高')?.value || '',
            delivery_days: inputByPlaceholder('请输入发货期限')?.value || '',
            gross_weight: inputById('form_item_grossWeight')?.value || '',
            freight_template: selectTextByInputId('form_item_freightTemplateId'),
            service_template: selectTextByInputId('form_item_promiseTemplateId'),
          };
          const missing = [];
          if (!values.title || hasChinese(values.title)) missing.push('english_title');
          const categorySelected = categoryText.includes('ACGStand') || categoryText.includes('立牌类谷子');
          if (!categorySelected) missing.push('category');
          if (!values.declared_value) missing.push('declared_value');
          if (!values.weight) missing.push('weight');
          if (!values.length || !values.width || !values.height) missing.push('package_dimensions');
          if (!values.delivery_days) missing.push('delivery_days');
          if (!values.gross_weight) missing.push('gross_weight');
          if (!values.freight_template || values.freight_template.includes('请选择')) missing.push('freight_template');
          if (!values.service_template || values.service_template.includes('请选择') || values.service_template.includes('请选中')) missing.push('service_template');
          const valueAfter = (label) => {
            const idx = compactBody.indexOf(label);
            if (idx < 0) return '';
            return compactBody.slice(idx + label.length).replace(/^[：:]/, '').slice(0, 40);
          };
          const valueAfterAny = (labels) => {
            for (const label of labels) {
              const value = valueAfter(label);
              if (value) return value;
            }
            return '';
          };
          const customsProductNameValue = valueAfterAny(['品名(Productname)', '品名(Product name)', '品名']);
          const customsKindValue = valueAfterAny(['种类(Kind)', '种类']);
          const customsConfigured = compactBody.includes('税率代码')
            && /\d{8,12}/.test(compactBody)
            && (compactBody.includes('海关监管属性') || compactBody.includes('更新海关监管') || compactBody.includes('添加海关监管') || compactBody.includes('添加全球海关监管属性'))
            && (
              (customsProductNameValue && !customsProductNameValue.startsWith('请选择'))
              || (customsKindValue && !customsKindValue.startsWith('请选择'))
            );
          const customsWarning = compactBody.includes('请完善海关监管属性') || compactBody.includes('请选择海关监管属性');
          if (customsWarning || (compactBody.includes('海关监管属性') && !customsConfigured)) missing.push('customs_supervision');
          return {
            missing,
            values,
            customs_configured: customsConfigured,
            category_selected: categorySelected,
            category_text: values.category_text,
          };
        }''')

    def _click_visible_text(self, page: Page, text: str, preferred_tags: tuple[str, ...] = ('BUTTON', 'A', 'SPAN', 'DIV')) -> bool:
        target = page.evaluate(r'''({text, preferredTags}) => {
          const norm = (s) => String(s || '').replace(/\s+/g, '').trim();
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const rectOf = (el) => {
            const r = el.getBoundingClientRect();
            return {x:r.x, y:r.y, w:r.width, h:r.height};
          };
          const matches = Array.from(document.querySelectorAll('button,a,span,div')).filter(el => visible(el) && norm(el.innerText || el.textContent) === norm(text));
          const preferred = matches.find(el => preferredTags.includes(el.tagName)) || matches[0];
          return preferred ? {rect:rectOf(preferred)} : null;
        }''', {'text': text, 'preferredTags': list(preferred_tags)})
        if not target or not target.get('rect'):
            return False
        self._click_rect_center(page, target['rect'])
        return True

    def _choose_ant_select_near_label(self, page: Page, label_text: str, priorities: list[str]) -> dict[str, Any]:
        page.keyboard.press('Escape')
        page.wait_for_timeout(200)
        rect = page.evaluate(r'''(labelText) => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const norm = (s) => String(s || '').replace(/\s+/g, '').trim();
          const rectOf = (el) => {
            const r = el.getBoundingClientRect();
            return {x:r.x, y:r.y, w:r.width, h:r.height};
          };
          const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
          const allLabels = Array.from(document.querySelectorAll('label,span,div,td,th'))
            .filter(visible)
            .map(el => {
              const r = rectOf(el);
              const text = textOf(el);
              return {el, text, normText: norm(text), rect: r};
            })
            .filter(x => x.text && x.text.length <= 90 && x.rect.w <= 360 && x.rect.h <= 90);
          const exactLabels = allLabels.filter(x => x.normText === norm(labelText) || x.normText === `*${norm(labelText)}`);
          const labels = exactLabels.length ? exactLabels : allLabels.filter(x => x.normText.includes(norm(labelText)));
          const selects = Array.from(document.querySelectorAll('.ant-select')).filter(visible);
          for (const label of labels) {
            const lr = label.rect;
            const ly = lr.y + lr.h / 2;
            const formItemSelect = label.el.closest('.ant-form-item')?.querySelector('.ant-select');
            const select = (formItemSelect && visible(formItemSelect) ? formItemSelect : null) || selects.find(el => {
              const r = rectOf(el);
              const y = r.y + r.h / 2;
              return Math.abs(y - ly) < 35 && r.x > lr.x;
            });
            if (select) {
              select.scrollIntoView({block:'center'});
              return {rect: rectOf(select), text: textOf(select), input_id: select.querySelector('input')?.id || ''};
            }
          }
          return null;
        }''', label_text)
        if not rect:
            return {'ok': False, 'reason': f'未找到选择框：{label_text}'}
        existing_text = str(rect.get('text') or '').strip()
        if existing_text and not any(term in existing_text for term in ('请选择', '请选中', '----')):
            return {'ok': True, 'already_selected': True, 'text': existing_text}
        self._click_rect_center(page, rect['rect'])
        page.wait_for_timeout(800)
        result = self._click_ant_option_near_rect(page, priorities, rect['rect'])
        verify = self._verify_ant_select_value(page, rect.get('input_id'), rect['rect'], priorities)
        if verify.get('ok'):
            return {**result, **verify}
        if not priorities:
            return verify
        self._click_rect_center(page, rect['rect'])
        page.wait_for_timeout(300)
        input_id = rect.get('input_id')
        try:
            if input_id:
                page.locator(f'#{input_id}').first.fill(str(priorities[0]), timeout=3000, force=True)
            else:
                page.keyboard.type(str(priorities[0]))
            page.wait_for_timeout(1200)
        except TimeoutError:
            return verify if verify else result
        result = self._click_ant_option_near_rect(page, priorities, rect['rect'])
        verify = self._verify_ant_select_value(page, rect.get('input_id'), rect['rect'], priorities)
        return {**result, **verify} if verify.get('ok') else verify

    def _verify_ant_select_value(
        self,
        page: Page,
        input_id: str | None,
        anchor_rect: dict[str, Any],
        priorities: list[str],
    ) -> dict[str, Any]:
        return page.evaluate(r'''({inputId, anchor, priorities}) => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const norm = (s) => String(s || '').replace(/\s+/g, '').trim();
          const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
          const rectOf = (el) => {
            const r = el.getBoundingClientRect();
            return {x:r.x, y:r.y, w:r.width, h:r.height};
          };
          let root = null;
          if (inputId) {
            const input = document.getElementById(inputId);
            root = input?.closest('.ant-select') || null;
          }
          if (!root || !visible(root)) {
            const selects = Array.from(document.querySelectorAll('.ant-select')).filter(visible);
            root = selects.find(el => {
              const r = rectOf(el);
              return Math.abs((r.x + r.w / 2) - (anchor.x + anchor.w / 2)) < 40
                && Math.abs((r.y + r.h / 2) - (anchor.y + anchor.h / 2)) < 40;
            }) || null;
          }
          if (!root) return {ok:false, reason:'未找到选择后的目标选择框'};
          const text = textOf(root);
          const compact = norm(text);
          const unresolved = !compact || compact.includes('请选择') || compact.includes('请选中') || compact.includes('----');
          const terms = priorities.map(String).filter(Boolean).map(norm);
          const matched = !terms.length || terms.some(term => compact.includes(term));
          return {
            ok: !unresolved && matched,
            text,
            unresolved,
            matched,
            reason: (!unresolved && matched) ? null : `选择框未落值：${text || '空'}`,
          };
        }''', {'inputId': input_id, 'anchor': anchor_rect, 'priorities': priorities})

    def _close_visible_modal(self, page: Page) -> None:
        self._click_visible_text(page, '关闭', preferred_tags=('BUTTON', 'A', 'SPAN'))
        page.wait_for_timeout(500)

    def _fill_text_inputs_near_label(self, page: Page, label_text: str, values: list[str]) -> dict[str, Any]:
        indexes = page.evaluate(r'''({labelText, count}) => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const norm = (s) => String(s || '').replace(/\s+/g, '').trim();
          const rectOf = (el) => {
            const r = el.getBoundingClientRect();
            return {x:r.x, y:r.y, w:r.width, h:r.height};
          };
          const docY = (el) => {
            const r = el.getBoundingClientRect();
            return r.y + window.scrollY;
          };
          const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
          const allLabels = Array.from(document.querySelectorAll('label,span,div,td,th'))
            .filter(visible)
            .map(el => {
              const r = rectOf(el);
              const text = textOf(el);
              return {el, text, normText: norm(text), rect: r};
            })
            .filter(x => x.text && x.text.length <= 90 && x.rect.w <= 360 && x.rect.h <= 90);
          const exactLabels = allLabels.filter(x => x.normText === norm(labelText) || x.normText === `*${norm(labelText)}`);
          const labels = exactLabels.length ? exactLabels : allLabels.filter(x => x.normText.includes(norm(labelText)));
          const allInputs = Array.from(document.querySelectorAll('input,textarea'));
          for (const label of labels) {
            const lr = label.rect;
            const ly = docY(label.el) + lr.h / 2;
            const rowInputs = allInputs
              .filter(el => visible(el) && !el.disabled && (el.tagName === 'TEXTAREA' || ['text', 'number', ''].includes(el.type)))
              .filter(el => {
                const r = rectOf(el);
                const y = docY(el) + r.h / 2;
                return Math.abs(y - ly) < 62 && r.x > lr.x - 10;
              })
              .sort((a, b) => rectOf(a).x - rectOf(b).x);
            if (rowInputs.length >= count) {
              rowInputs[0].scrollIntoView({block:'center'});
              return rowInputs.slice(0, count).map(el => allInputs.indexOf(el));
            }
          }
          return [];
        }''', {'labelText': label_text, 'count': len(values)})
        if len(indexes or []) < len(values):
            return {'ok': False, 'reason': f'未找到输入框：{label_text}'}
        inputs = page.locator('input,textarea')
        filled: list[str] = []
        for index, value in zip(indexes, values):
            try:
                inputs.nth(int(index)).fill(str(value), timeout=3000, force=True)
                filled.append(str(value))
            except TimeoutError:
                return {'ok': False, 'reason': f'填写失败：{label_text}'}
        page.wait_for_timeout(300)
        return {'ok': True, 'filled': filled}

    def _fill_packaging_info(self, page: Page, gross_weight: str, dimensions: list[str]) -> dict[str, Any]:
        gross = page.locator('#form_item_grossWeight').first
        try:
            gross.scroll_into_view_if_needed(timeout=3000)
            gross.fill(gross_weight, timeout=3000, force=True)
        except TimeoutError:
            return {'ok': False, 'reason': '包装后重量填写失败'}
        indexes = page.evaluate(r'''(count) => {
          const gross = document.getElementById('form_item_grossWeight');
          if (!gross) return [];
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const rectOf = (el) => {
            const r = el.getBoundingClientRect();
            return {x:r.x, y:r.y, w:r.width, h:r.height};
          };
          const docY = (el) => {
            const r = el.getBoundingClientRect();
            return r.y + window.scrollY;
          };
          const allInputs = Array.from(document.querySelectorAll('input,textarea'));
          const gy = docY(gross);
          const candidates = allInputs
            .filter(el => visible(el) && !el.disabled && el.tagName === 'INPUT' && ['text', 'number', ''].includes(el.type))
            .filter(el => {
              const r = rectOf(el);
              const y = docY(el);
              return y > gy + 20 && y < gy + 140 && r.w >= 50 && r.w <= 150;
            })
            .sort((a, b) => docY(a) - docY(b) || rectOf(a).x - rectOf(b).x);
          return candidates.slice(0, count).map(el => allInputs.indexOf(el));
        }''', len(dimensions))
        if len(indexes or []) < len(dimensions):
            return {'ok': False, 'reason': '包装后尺寸输入框不足'}
        inputs = page.locator('input,textarea')
        for index, value in zip(indexes, dimensions):
            try:
                inputs.nth(int(index)).fill(str(value), timeout=3000, force=True)
            except TimeoutError:
                return {'ok': False, 'reason': '包装后尺寸填写失败'}
        page.wait_for_timeout(300)
        return {'ok': True, 'gross_weight': gross_weight, 'dimensions': dimensions}

    def _choose_ant_select_by_input_id(
        self,
        page: Page,
        input_id: str,
        priorities: list[str],
        required: bool = True,
    ) -> dict[str, Any]:
        page.keyboard.press('Escape')
        page.wait_for_timeout(200)
        current = page.evaluate(r'''(inputId) => {
          const input = document.getElementById(inputId);
          const root = input?.closest('.ant-select');
          const text = String(root?.innerText || root?.textContent || '').replace(/\s+/g, '').trim();
          if (!root) return {exists:false, text:''};
          const unresolved = !text || text.includes('请选择') || text.includes('请选中') || text.includes('----');
          const r = root.getBoundingClientRect();
          return {exists:true, text, unresolved, rect:{x:r.x,y:r.y,w:r.width,h:r.height}};
        }''', input_id)
        if not current.get('exists'):
            return {'ok': not required, 'reason': f'未找到选择框：{input_id}', 'optional': not required}
        if not current.get('unresolved'):
            return {'ok': True, 'already_selected': True, 'text': current.get('text')}
        try:
            page.locator(f'#{input_id}').first.scroll_into_view_if_needed(timeout=3000)
            page.locator(f'#{input_id}').first.click(timeout=3000, force=True)
        except TimeoutError:
            return {'ok': not required, 'reason': f'无法展开选择框：{input_id}', 'optional': not required}
        result = self._click_ant_option(page, priorities, required=required)
        if result.get('ok') or not priorities:
            return result
        try:
            page.locator(f'#{input_id}').first.click(timeout=3000, force=True)
            page.locator(f'#{input_id}').first.fill(str(priorities[0]), timeout=3000, force=True)
            page.wait_for_timeout(1200)
        except TimeoutError:
            return result
        return self._click_ant_option(page, priorities, required=required)

    def _click_ant_option_near_rect(
        self,
        page: Page,
        priorities: list[str],
        anchor_rect: dict[str, Any],
        required: bool = True,
    ) -> dict[str, Any]:
        page.wait_for_timeout(800)
        option = page.evaluate(r'''({priorities, anchor}) => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < window.innerHeight
              && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const rectOf = (el) => {
            const r = el.getBoundingClientRect();
            return {x:r.x, y:r.y, w:r.width, h:r.height};
          };
          const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
          const overlaps = (a, b) => a.x < b.x + b.w + 80 && a.x + a.w > b.x - 80;
          const distance = (a, b) => Math.abs((a.x + a.w / 2) - (b.x + b.w / 2)) + Math.abs(a.y - (b.y + b.h));
          const options = Array.from(document.querySelectorAll('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option, .ant-select-dropdown:not(.ant-select-dropdown-hidden) [role="option"]'))
            .filter(visible)
            .map(el => ({el, text:textOf(el), rect:rectOf(el)}))
            .filter(x => x.text && x.text !== '请选择' && !x.text.includes('暂无数据'));
          const candidates = options
            .filter(x => overlaps(x.rect, anchor) && x.rect.y >= anchor.y - 8 && x.rect.y <= anchor.y + 420)
            .sort((a, b) => distance(a.rect, anchor) - distance(b.rect, anchor));
          if (!candidates.length) return null;
          const priorityTerms = priorities.map(String).filter(Boolean);
          const matched = priorityTerms.reduce((found, term) => found || candidates.find(x => x.text.includes(term)), null);
          const picked = matched || (priorityTerms.length ? null : candidates[0]);
          if (!picked) return {no_match:true, options:candidates.map(x => x.text).slice(0, 20)};
          return {text:picked.text, rect:picked.rect};
        }''', {'priorities': priorities, 'anchor': anchor_rect})
        if not option or not option.get('rect'):
            reason = '未找到匹配选项' if option and option.get('no_match') else '未找到当前选择框附近的可选项'
            return {'ok': not required, 'reason': reason, 'optional': not required, 'options': (option or {}).get('options')}
        self._click_rect_center(page, option['rect'])
        page.wait_for_timeout(800)
        return {'ok': True, 'text': option.get('text')}

    def _click_ant_option(self, page: Page, priorities: list[str], required: bool = True) -> dict[str, Any]:
        page.wait_for_timeout(800)
        option = page.evaluate(r'''(priorities) => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const rectOf = (el) => {
            const r = el.getBoundingClientRect();
            return {x:r.x, y:r.y, w:r.width, h:r.height};
          };
          const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
          const options = Array.from(document.querySelectorAll('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option, .ant-select-dropdown:not(.ant-select-dropdown-hidden) [role="option"]'))
            .filter(visible)
            .map(el => ({el, text:textOf(el)}))
            .filter(x => x.text && x.text !== '请选择' && !x.text.includes('暂无数据'));
          if (!options.length) return null;
          const priorityTerms = priorities.map(String).filter(Boolean);
          const matched = priorityTerms.reduce((found, term) => found || options.find(x => x.text.includes(term)), null);
          const picked = matched || (priorityTerms.length ? null : options[0]);
          if (!picked) return {no_match:true, options: options.map(x => x.text).slice(0, 20)};
          return {text:picked.text, rect:rectOf(picked.el)};
        }''', priorities)
        if not option or not option.get('rect'):
            page.keyboard.press('Escape')
            reason = '未找到匹配选项' if option and option.get('no_match') else '未找到可选模板'
            return {'ok': not required, 'reason': reason, 'optional': not required, 'options': (option or {}).get('options')}
        self._click_rect_center(page, option['rect'])
        page.wait_for_timeout(800)
        return {'ok': True, 'text': option.get('text')}

    def _check_choice_by_text(self, page: Page, text: str) -> dict[str, Any]:
        result = page.evaluate(r'''(text) => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const norm = (s) => String(s || '').replace(/\s+/g, '').trim();
          const rectOf = (el) => {
            const r = el.getBoundingClientRect();
            return {x:r.x, y:r.y, w:r.width, h:r.height};
          };
          const nodes = Array.from(document.querySelectorAll('label,span,div')).filter(visible).filter(el => norm(el.innerText || el.textContent) === norm(text));
          const node = nodes.find(el => el.closest('label')) || nodes[0];
          if (!node) return {ok:false, reason:`未找到选项：${text}`};
          const label = node.closest('label') || node;
          const input = label.querySelector('input[type="checkbox"],input[type="radio"]');
          if (input && input.checked) return {ok:true, already_checked:true};
          label.scrollIntoView({block:'center'});
          return {ok:true, rect:rectOf(label)};
        }''', text)
        if result.get('ok') and result.get('rect'):
            self._click_rect_center(page, result['rect'])
            page.wait_for_timeout(500)
        return result

    def _fill_semi_managed_defaults_on_page(self, page: Page, defaults: dict[str, Any] | None = None) -> dict[str, Any]:
        values = {
            'is_original_box': '否',
            'logistics_attribute': '普货',
            'weight': '0.03',
            'length': '10',
            'width': '10',
            'height': '2',
            'jit_stock': '100',
        }
        values.update(self._flatten_editor_defaults(defaults or {}))
        values['stock'] = values.get('jit_stock') or values.get('stock') or '100'
        original_box = self._fill_semi_original_box(page, str(values['is_original_box']))
        logistics_attribute = self._fill_semi_logistics_attribute(page, str(values['logistics_attribute']))
        result = page.evaluate(r'''(values) => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
          const rectOf = (el) => {
            const r = el.getBoundingClientRect();
            return {x:r.x, y:r.y, w:r.width, h:r.height, bottom:r.bottom, right:r.right};
          };
          const setNativeValue = (target, value) => {
            if (!target || target.disabled) return false;
            const proto = target.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
            const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
            if (setter) setter.call(target, value);
            else target.value = value;
            target.dispatchEvent(new Event('input', {bubbles:true}));
            target.dispatchEvent(new Event('change', {bubbles:true}));
            target.dispatchEvent(new Event('blur', {bubbles:true}));
            return String(target.value || '').trim() === String(value);
          };
          const KEY_TERMS = ['产品价格', '重量', '尺寸', 'JIT库存', 'SKU编码', '货品编码', '货品条码', '物流属性', '是否原箱'];
          const headers = Array.from(document.querySelectorAll('th,td,label,div,span'))
            .filter(visible)
            .map(el => ({el, tag:el.tagName, text:textOf(el), rect:rectOf(el)}))
            .filter(x => {
              if (!x.text || x.rect.w < 8 || x.rect.h < 8) return false;
              const otherTerms = KEY_TERMS.filter(term => x.text.includes(term)).length;
              if (x.text.length > 90 && otherTerms >= 2) return false;
              return true;
            });
          const inputs = Array.from(document.querySelectorAll('input,textarea'))
            .filter(el => visible(el) && !el.disabled)
            .map(el => ({el, value:el.value || '', placeholder:el.placeholder || '', id:el.id || '', rect:rectOf(el)}));
          const headerScore = (item, term) => {
            const shortText = item.text.replace(/[：:*]/g, '').trim();
            const exact = shortText === term ? 0 : (shortText.startsWith(term) ? 1 : 2);
            const semanticTag = ['TH', 'TD', 'LABEL'].includes(item.tag) ? 0 : 1;
            return exact * 1000 + semanticTag * 100 + Math.min(item.text.length, 160) + (item.rect.w / 100) + (item.rect.y / 1000);
          };
          const headerCandidates = (term) => headers
            .filter(x => x.text.includes(term))
            .sort((a, b) => headerScore(a, term) - headerScore(b, term));
          const inputsBelowHeader = (term) => {
            for (const header of headerCandidates(term)) {
              const matched = inputs
                .filter(x => {
                  const overlapsX = x.rect.x < header.rect.right + 12 && x.rect.right > header.rect.x - 12;
                  const belowHeader = x.rect.y >= header.rect.bottom - 6 && x.rect.y <= header.rect.bottom + 170;
                  return overlapsX && belowHeader;
                })
                .sort((a, b) => a.rect.y - b.rect.y || a.rect.x - b.rect.x);
              if (matched.length) return matched;
            }
            return [];
          };
          const inputByPlaceholder = (term) => inputs
            .filter(x => String(x.placeholder || '').includes(term))
            .sort((a, b) => a.rect.y - b.rect.y || a.rect.x - b.rect.x)[0] || null;
          const tableInputsByHeader = (term) => {
            const cells = Array.from(document.querySelectorAll('th,td'))
              .filter(visible)
              .map(el => ({el, text:textOf(el), rect:rectOf(el)}))
              .filter(x => x.text.includes(term))
              .sort((a, b) => headerScore({...a, tag:a.el.tagName}, term) - headerScore({...b, tag:b.el.tagName}, term));
            for (const header of cells) {
              const table = header.el.closest('table');
              if (!table || typeof header.el.cellIndex !== 'number' || header.el.cellIndex < 0) continue;
              const geometric = inputs
                .filter(x => table.contains(x.el))
                .filter(x => {
                  const overlapsX = x.rect.x < header.rect.right + 12 && x.rect.right > header.rect.x - 12;
                  const belowHeader = x.rect.y >= header.rect.bottom - 6 && x.rect.y <= header.rect.bottom + 180;
                  return overlapsX && belowHeader;
                })
                .sort((a, b) => a.rect.y - b.rect.y || a.rect.x - b.rect.x)
                .map(x => ({...x, strategy:'table_header_geometry'}));
              if (geometric.length) return geometric;
              const rows = Array.from(table.querySelectorAll('tr')).filter(row => !row.contains(header.el));
              for (const row of rows) {
                const cell = Array.from(row.children).filter(el => ['TD', 'TH'].includes(el.tagName))[header.el.cellIndex];
                if (!cell || !visible(cell)) continue;
                const found = Array.from(cell.querySelectorAll('input,textarea'))
                  .filter(el => visible(el) && !el.disabled)
                  .map(el => ({el, value:el.value || '', placeholder:el.placeholder || '', id:el.id || '', rect:rectOf(el), strategy:'table_column'}));
                if (found.length) return found;
              }
            }
            return [];
          };
          const tableByTerms = (terms) => Array.from(document.querySelectorAll('table'))
            .filter(visible)
            .map(el => ({el, text:textOf(el)}))
            .filter(x => terms.every(term => x.text.includes(term)))
            .sort((a, b) => a.text.length - b.text.length)[0]?.el || null;
          const inputsInTable = (table) => inputs
            .filter(x => table && table.contains(x.el))
            .sort((a, b) => a.rect.x - b.rect.x || a.rect.y - b.rect.y);
          const locatedInput = (term, placeholderTerm = term) => {
            const fromTable = tableInputsByHeader(term)[0];
            if (fromTable) return fromTable;
            const below = inputsBelowHeader(term)[0];
            if (below) return {...below, strategy:'column_header'};
            const byPlaceholder = inputByPlaceholder(placeholderTerm);
            if (byPlaceholder) return {...byPlaceholder, strategy:'placeholder'};
            return null;
          };
          const setOrAccept = (field, item, desiredValue, options = {}) => {
            const detail = {
              ok: false,
              located: Boolean(item?.el),
              strategy: item?.strategy || null,
              value_before: item?.el ? String(item.el.value || '') : '',
              value_after: item?.el ? String(item.el.value || '') : '',
            };
            if (!item?.el) return detail;
            const desired = String(desiredValue ?? '');
            if (options.acceptExisting && !desired && String(item.el.value || '').trim()) {
              detail.ok = true;
              detail.accepted_existing = true;
              return detail;
            }
            detail.ok = setNativeValue(item.el, desired);
            detail.value_after = String(item.el.value || '');
            return detail;
          };
          const goodsTable = tableByTerms(['重量', '尺寸']);
          const goodsInputs = inputsInTable(goodsTable);
          const variantTable = tableByTerms(['产品价格', 'JIT库存']);
          const variantInputs = inputsInTable(variantTable);
          const weight = locatedInput('重量', '重量');
          const dimensions = (
            goodsInputs.length >= 4
              ? goodsInputs.slice(-3).map(x => ({...x, strategy:'goods_table_rightmost'}))
              : (tableInputsByHeader('尺寸').length ? tableInputsByHeader('尺寸') : inputsBelowHeader('尺寸').map(x => ({...x, strategy:'column_header'})))
          ).slice(0, 3);
          const jitStock = variantInputs.length
            ? {...variantInputs[variantInputs.length - 1], strategy:'variant_table_rightmost'}
            : locatedInput('JIT库存', '库存');
          const productPrice = locatedInput('产品价格', '价格');
          const goodsCode = variantInputs.length >= 3
            ? {...variantInputs[variantInputs.length - 3], strategy:'variant_optional_left_of_stock'}
            : null;
          const goodsBarcode = variantInputs.length >= 2
            ? {...variantInputs[variantInputs.length - 2], strategy:'variant_optional_left_of_stock'}
            : null;
          const productPriceValue = values.product_price || values.supply_price || values.retail_price || '';
          const details = {
            product_price: setOrAccept('product_price', productPrice, productPriceValue, {acceptExisting:true}),
            weight: setOrAccept('weight', weight, values.weight),
            length: setOrAccept('length', dimensions[0] || null, values.length),
            width: setOrAccept('width', dimensions[1] || null, values.width),
            height: setOrAccept('height', dimensions[2] || null, values.height),
            stock: setOrAccept('stock', jitStock, values.stock),
          };
          const optionalDetails = {
            goods_code: goodsCode?.el ? setOrAccept('goods_code', goodsCode, '') : {ok:true, located:false, skipped:true},
            goods_barcode: goodsBarcode?.el ? setOrAccept('goods_barcode', goodsBarcode, '') : {ok:true, located:false, skipped:true},
          };
          return {
            product_price: details.product_price.ok,
            weight: details.weight.ok,
            length: details.length.ok,
            width: details.width.ok,
            height: details.height.ok,
            stock: details.stock.ok,
            field_details: details,
            optional_details: optionalDetails,
          };
        }''', values)
        result = result or {}
        result['is_original_box'] = bool(original_box.get('ok'))
        result['logistics_attribute'] = bool(logistics_attribute.get('ok'))
        missing = [name for name, ok in (result or {}).items() if not ok]
        screenshot_path = EDITOR_ACTION_SCREENSHOT_MAP['fill_semi_managed_defaults']
        page.screenshot(path=str(screenshot_path), full_page=True)
        return {
            'stage': 'semi_managed_defaults_filled' if not missing else 'fill_semi_managed_defaults_failed',
            'label': '半托管默认值已填写' if not missing else '半托管默认值填写失败',
            'message': '已填写半托管保守默认值。' if not missing else f'缺少半托管字段：{", ".join(missing)}',
            'page_title': page.title(),
            'page_url': page.url,
            'screenshot_url': self._artifact_url(screenshot_path),
            'fill_result': {
                **result,
                'original_box': original_box,
                'logistics_attribute_detail': logistics_attribute,
                'missing': missing,
                'optional_unfilled': ['goods_code', 'goods_barcode'],
            },
            'published': False,
        }

    def _fill_semi_original_box(self, page: Page, value: str) -> dict[str, Any]:
        ids = page.evaluate(r'''() => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          return Array.from(document.querySelectorAll('input[id*="originalBox"]'))
            .filter(visible)
            .map(el => el.id)
            .filter(Boolean);
        }''')
        if not ids:
            return {'ok': False, 'reason': '未找到半托管是否原箱选择框'}
        results = []
        for input_id in ids:
            results.append(self._choose_ant_select_by_input_id(page, input_id, [value], required=True))
        missing = [item for item in results if not item.get('ok')]
        return {'ok': not missing, 'results': results, 'reason': missing[0].get('reason') if missing else None}

    def _fill_semi_logistics_attribute(self, page: Page, value: str) -> dict[str, Any]:
        normalized = value.replace(' ', '').lower()
        plain_goods = normalized in {'普货', '普通货', '普通', 'none', 'no', '无'}
        icons = page.evaluate(r'''() => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const rectOf = (el) => {
            const r = el.getBoundingClientRect();
            return {x:r.x, y:r.y, w:r.width, h:r.height};
          };
          const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
          const logisticsHeader = Array.from(document.querySelectorAll('th,td,div,span'))
            .filter(visible)
            .map(el => ({el, text:textOf(el), rect:rectOf(el)}))
            .filter(x => x.text.includes('物流属性') && x.rect.y > 500)
            .sort((a, b) => a.rect.y - b.rect.y || a.rect.x - b.rect.x)[0];
          if (!logisticsHeader) return [];
          return Array.from(document.querySelectorAll('i.icon_edit2, .icon_edit2'))
            .filter(visible)
            .map(el => ({rect:rectOf(el)}))
            .filter(x => x.rect.y >= logisticsHeader.rect.y + 30 && x.rect.y <= logisticsHeader.rect.y + 120)
            .sort((a, b) => a.rect.y - b.rect.y || a.rect.x - b.rect.x)
            .map(x => x.rect);
        }''')
        if not icons:
            return {'ok': plain_goods, 'skipped': plain_goods, 'reason': None if plain_goods else '未找到半托管物流属性编辑入口'}

        modal_results = []
        for rect in icons:
            self._click_rect_center(page, rect)
            page.wait_for_timeout(800)
            state = page.evaluate(r'''({value, plainGoods}) => {
              const visible = (el) => {
                const r = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
              };
              const norm = (s) => String(s || '').replace(/\s+/g, '').trim();
              const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
              const rectOf = (el) => {
                const r = el.getBoundingClientRect();
                return {x:r.x, y:r.y, w:r.width, h:r.height};
              };
              const modal = Array.from(document.querySelectorAll('.ant-modal, .ant-modal-wrap, [role="dialog"]'))
                .filter(visible)
                .find(el => textOf(el).includes('修改物流属性'));
              if (!modal) return {ok:false, reason:'物流属性弹窗未打开'};
              const labels = Array.from(modal.querySelectorAll('label')).filter(visible);
              const selected = [];
              for (const label of labels) {
                const input = label.querySelector('input[type="checkbox"]');
                const text = norm(label.innerText || label.textContent);
                if (!input) continue;
                if (plainGoods && input.checked) {
                  label.dispatchEvent(new MouseEvent('click', {bubbles:true}));
                } else if (!plainGoods && text.includes(norm(value)) && !input.checked) {
                  label.dispatchEvent(new MouseEvent('click', {bubbles:true}));
                  selected.push(text);
                }
              }
              const hasRequested = plainGoods || labels.some(label => norm(label.innerText || label.textContent).includes(norm(value)));
              const confirm = Array.from(modal.querySelectorAll('button,span,a,div'))
                .filter(visible)
                .find(el => norm(el.innerText || el.textContent) === '确定');
              return {ok:hasRequested, confirm_rect: confirm ? rectOf(confirm) : null, selected, reason: hasRequested ? null : '未找到请求的物流属性'};
            }''', {'value': value, 'plainGoods': plain_goods})
            if not state.get('ok') or not state.get('confirm_rect'):
                modal_results.append(state)
                page.keyboard.press('Escape')
                page.wait_for_timeout(300)
                continue
            self._click_rect_center(page, state['confirm_rect'])
            page.wait_for_timeout(700)
            modal_results.append(state)
        missing = [item for item in modal_results if not item.get('ok')]
        return {'ok': not missing, 'plain_goods': plain_goods, 'results': modal_results, 'reason': missing[0].get('reason') if missing else None}

    def _save_only_on_page(self, page: Page) -> dict[str, Any]:
        click_result = page.evaluate(r'''() => {
          const norm = (s) => String(s || '').replace(/\s+/g, '').trim();
          const labels = ['发布','立即发布','继续发布','保存并发布','确认发布','提交发布','保存并移入待发布','移入待发布'];
          const isUsableAction = (el) => {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none' && !el.disabled && el.getAttribute('aria-disabled') !== 'true';
          };
          const candidates = Array.from(document.querySelectorAll('button,a,[role="button"]')).filter(isUsableAction).map(el => ({el, text:norm(el.innerText || el.textContent)}));
          const save = candidates.find(x => x.text === '保存');
          if (!save) {
            const forbidden = candidates.find(x => labels.includes(x.text));
            if (forbidden) return {ok:false, reason:`命中发布按钮：${forbidden.text}`, published:false};
            const fallback = Array.from(document.querySelectorAll('button,a,[role="button"],span,div')).filter(isUsableAction).map(el => ({text:norm(el.innerText || el.textContent)}));
            const fallbackForbidden = fallback.find(x => labels.includes(x.text));
            return {ok:false, reason: fallbackForbidden ? `命中发布按钮：${fallbackForbidden.text}` : '未找到保存按钮', published:false};
          }
          const r = save.el.getBoundingClientRect();
          return {ok:true, rect:{x:r.x,y:r.y,w:r.width,h:r.height}, message:'已定位保存按钮', published:false};
        }''')
        click_result = click_result or {}
        network_events = self._capture_save_network_events(page, click_result.get('rect'))
        if click_result.get('ok') and click_result.get('rect'):
            self._click_rect_center(page, click_result['rect'])
            click_result = {**click_result, 'clicked': True, 'message': '已点击保存'}
        page.wait_for_timeout(2500)
        verify_result = click_result
        if click_result.get('ok'):
            verify_result = page.evaluate(r'''(clickResult) => {
              const body = String(document.body ? document.body.innerText || document.body.textContent || '' : '');
              const compact = body.replace(/\s+/g, '');
              const successTerms = ['保存成功','编辑成功','产品编辑成功','已保存'];
              const successTerm = successTerms.find(term => compact.includes(term));
              if (!successTerm) {
                return {...clickResult, ok:false, reason:'未检测到保存成功提示', success_text:null, published:false};
              }
              return {...clickResult, ok:true, success_text:successTerm, published:false};
            }''', click_result)
            network_result = self._network_save_result(network_events)
            verify_result = {
                **(verify_result or {}),
                'network_events': network_events[:8],
                'network_save_result': network_result,
            }
            if network_result.get('ok') is True:
                verify_result = {
                    **verify_result,
                    'ok': True,
                    'success_text': verify_result.get('success_text') or network_result.get('message') or '保存接口成功',
                }
        screenshot_path = EDITOR_ACTION_SCREENSHOT_MAP['save_only']
        page.screenshot(path=str(screenshot_path), full_page=True)
        ok = bool(verify_result.get('ok'))
        return {
            'stage': 'save_only' if ok else 'save_only_failed',
            'label': '已保存' if ok else '保存失败',
            'message': verify_result.get('success_text') or verify_result.get('message') or verify_result.get('reason') or '保存失败',
            'page_title': page.title(),
            'page_url': page.url,
            'screenshot_url': self._artifact_url(screenshot_path),
            'save_result': verify_result,
            'published': False,
        }

    def _verify_not_published_on_page(
        self,
        page: Page,
        product_query: str | None = None,
        store_name: str | None = None,
        prior_save_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = page.evaluate(r'''({productQuery, storeName}) => {
          const body = String(document.body ? document.body.innerText || document.body.textContent || '' : '');
          const compact = body.replace(/\s+/g, '');
          const publishRiskTerms = ['发布成功', '已上架', '在线商品', '商品已发布'];
          const saveOnlyTerms = ['待发布', '保存成功', '编辑成功', '产品已保存', '产品编辑成功'];
          const risk = publishRiskTerms.find(term => compact.includes(term));
          const saveOnly = saveOnlyTerms.find(term => compact.includes(term));
          return {
            ok: Boolean(saveOnly && !risk),
            product_query: productQuery || null,
            store_name: storeName || null,
            save_only_term: saveOnly || null,
            publish_risk_term: risk || null,
            body_excerpt: body.slice(0, 500),
            published: Boolean(risk),
          };
        }''', {'productQuery': product_query, 'storeName': store_name})
        prior_save_ok = bool(prior_save_result and prior_save_result.get('ok') is True and prior_save_result.get('published') is not True)
        if result and not result.get('publish_risk_term') and prior_save_ok and not result.get('ok'):
            result['ok'] = True
            result['save_only_term'] = prior_save_result.get('success_text') or prior_save_result.get('message') or '上一保存动作成功'
            result['verified_by_prior_save_result'] = True
        screenshot_path = SCREENSHOT_DIR / 'dianxiaomi_verify_not_published.png'
        page.screenshot(path=str(screenshot_path), full_page=True)
        ok = bool(result.get('ok'))
        return {
            'stage': 'not_published_verified' if ok else 'verify_not_published_failed',
            'label': '未发布状态已校验' if ok else '未发布状态校验失败',
            'message': result.get('save_only_term') or result.get('publish_risk_term') or '未找到待发布或保存成功证明。',
            'page_title': page.title(),
            'page_url': page.url,
            'screenshot_url': self._artifact_url(screenshot_path),
            'fill_result': result,
            'published': bool(result.get('published')),
        }

    def _capture_save_network_events(self, page: Page, save_rect: dict[str, Any] | None) -> list[dict[str, Any]]:
        if not save_rect or not hasattr(page, 'on'):
            return []
        events: list[dict[str, Any]] = []
        requests_by_id: dict[int, dict[str, Any]] = {}

        def request_method(request: Any) -> str | None:
            return str(getattr(request, 'method', '') or '').upper() or None

        def request_url(request: Any) -> str:
            return str(getattr(request, 'url', '') or '')

        def request_resource_type(request: Any) -> str | None:
            return str(getattr(request, 'resource_type', '') or '') or None

        def on_request(request) -> None:
            url = request_url(request)
            method = request_method(request)
            resource_type = request_resource_type(request)
            if not self._is_save_related_url(url, method=method, resource_type=resource_type):
                return
            item: dict[str, Any] = {
                'url': url,
                'method': method,
                'resource_type': resource_type,
            }
            try:
                post_data = request.post_data
                if post_data:
                    item['post_data_excerpt'] = str(post_data)[:500]
            except Exception:
                pass
            requests_by_id[id(request)] = item
            events.append(item)

        def on_response(response) -> None:
            url = str(getattr(response, 'url', '') or '')
            request = getattr(response, 'request', None)
            method = request_method(request) if request is not None else None
            resource_type = request_resource_type(request) if request is not None else None
            if not self._is_save_related_url(url, method=method, resource_type=resource_type):
                return
            item = requests_by_id.get(id(request)) if request is not None else None
            if item is None:
                item = {
                    'url': url,
                    'method': method,
                    'resource_type': resource_type,
                }
                events.append(item)
            item['status'] = getattr(response, 'status', None)
            try:
                item['json'] = response.json()
            except Exception:
                try:
                    item['text_excerpt'] = str(response.text() or '')[:500]
                except Exception:
                    item['text_excerpt'] = ''

        try:
            page.on('response', on_response)
        except Exception:
            return events
        try:
            page.on('request', on_request)
        except Exception:
            pass
        return events

    def _is_save_related_url(
        self,
        url: str,
        *,
        method: str | None = None,
        resource_type: str | None = None,
    ) -> bool:
        text = url.lower()
        if 'dianxiaomi.com' not in text:
            return False
        if any(term in text for term in ('publish', 'release', 'online', 'submitpublish')):
            return False
        if any(text.endswith(ext) for ext in ('.js', '.css', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.woff', '.woff2')):
            return False
        if any(term in text for term in ('save', 'edit', 'update', 'submit')):
            return True
        if (method or '').upper() in {'POST', 'PUT', 'PATCH'} and (resource_type or '').lower() in {'xhr', 'fetch'}:
            return any(term in text for term in ('smt', 'product', 'semi', 'sku', 'item'))
        return False

    def _network_save_result(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        if not events:
            return {'ok': None, 'reason': '未捕获保存相关接口响应'}
        for item in reversed(events):
            payload = item.get('json')
            if isinstance(payload, dict):
                code = payload.get('code')
                msg = payload.get('msg') or payload.get('message')
                ok = code in (0, '0') or payload.get('success') is True
                return {
                    'ok': ok,
                    'url': item.get('url'),
                    'method': item.get('method'),
                    'status': item.get('status'),
                    'code': code,
                    'msg': msg,
                    'message': msg,
                    'raw': payload,
                }
        last = events[-1]
        status = last.get('status')
        return {
            'ok': 200 <= int(status or 0) < 300,
            'url': last.get('url'),
            'method': last.get('method'),
            'status': status,
            'msg': last.get('text_excerpt'),
            'message': last.get('text_excerpt'),
        }

    def _ensure_page(self) -> Page:
        if self._page is not None:
            return self._page
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            **chrome_launch_options(headless=self._is_headless()),
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

    def _dismiss_blocking_modals(self, page: Page) -> int:
        dismissed = 0
        for _ in range(10):
            result = page.evaluate(r'''() => {
              const norm = (s) => String(s || '').replace(/\s+/g, '').trim();
              const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
              const rectOf = (el) => {
                const r = el.getBoundingClientRect();
                return {x:r.x, y:r.y, w:r.width, h:r.height};
              };
              const isVisible = (el) => {
                const r = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
              };
              const guide = Array.from(document.querySelectorAll('.guide-overlay, .guide-body, [class*="guide"], [class*="Guide"]')).find(el => {
                if (!isVisible(el)) return false;
                const text = norm(el.innerText || el.textContent);
                return text.includes('跳过') || text.includes('下一步') || text.includes('我知道') || text.includes('知道了');
              });
              if (guide) {
                const guideText = textOf(guide);
                const guideButtons = Array.from(guide.querySelectorAll('button,a,span,div')).filter(isVisible);
                const labels = ['跳过','我知道了','知道了','关闭','取消'];
                const textMatches = guideButtons.filter(el => labels.includes(norm(el.innerText || el.textContent)));
                const target = textMatches.find(el => ['BUTTON', 'A'].includes(el.tagName))
                  || (textMatches[0] && (textMatches[0].closest('button,a') || textMatches[0]));
                if (target) {
                  return {visible:true, clicked:`guide:${norm(target.innerText || target.textContent)}`, rect:rectOf(target), text:guideText.slice(0,300)};
                }
              }
              const modal = Array.from(document.querySelectorAll('.notice-list-modal, .ant-modal-wrap, [role="dialog"]')).find(isVisible);
              if (!modal) return {visible:false};
              const modalText = textOf(modal);
              const compactModalText = norm(modalText);
              if (compactModalText.includes('从图片银行选择') || compactModalText.includes('图片银行的分组')) {
                return {visible:false, image_bank:true};
              }
              const dangerousTerms = ['发布', '立即发布', '继续发布', '保存并发布', '确认发布', '提交发布', '保存并移入待发布', '移入待发布'];
              const dangerousTerm = dangerousTerms.find(term => compactModalText.includes(norm(term)));
              if (dangerousTerm) {
                return {visible:true, dangerous:true, reason:`检测到危险弹窗：${dangerousTerm}`, text:modalText.slice(0,300)};
              }
              const closeButton = Array.from(modal.querySelectorAll('.ant-modal-close, .ant-modal-close-x, .close, .close-btn, .notice-close, [class*="close"], [aria-label*="Close"], [aria-label*="关闭"]'))
                .find(isVisible);
              if (closeButton) {
                return {visible:true, clicked:'modal-close', rect:rectOf(closeButton)};
              }
              const isNoticeModal = modal.classList.contains('notice-list-modal') || compactModalText.includes('公告') || compactModalText.includes('通知');
              const labels = isNoticeModal
                ? ['跳过','下一步','完成','我知道了','知道了','关闭','确定','下一条']
                : ['跳过','下一步','完成','我知道了','知道了','关闭','取消'];
              const buttons = Array.from(modal.querySelectorAll('button,a,span,div')).filter(isVisible);
              const textMatches = buttons.filter(el => labels.includes(norm(el.innerText || el.textContent)));
              const target = textMatches.find(el => ['BUTTON', 'A'].includes(el.tagName))
                || (textMatches[0] && (textMatches[0].closest('button,a') || textMatches[0]));
              if (!target) return {visible:true, clicked: isNoticeModal ? 'escape' : null};
              return {visible:true, clicked:norm(target.innerText || target.textContent), rect:rectOf(target)};
            }''')
            if not result or not result.get('visible'):
                return dismissed
            if result.get('dangerous'):
                raise RuntimeError(result.get('reason') or '检测到危险弹窗，已停止自动点击')
            if not result.get('clicked'):
                return dismissed
            if result.get('clicked') == 'escape':
                page.keyboard.press('Escape')
                dismissed += 1
                page.wait_for_timeout(800)
                continue
            rect = result.get('rect')
            if rect:
                self._click_rect_center(page, rect)
                dismissed += 1
            page.wait_for_timeout(800)
        return dismissed

    def _wait_for_body_text(self, page: Page, terms: list[str], timeout: int = 20000) -> bool:
        try:
            page.wait_for_function(
                """(terms) => {
                  const text = document.body ? (document.body.innerText || document.body.textContent || '') : '';
                  return terms.some((term) => text.includes(term));
                }""",
                arg=terms,
                timeout=timeout,
            )
            return True
        except TimeoutError:
            return False

    def _wait_for_page_ready(
        self,
        page: Page,
        terms: list[str],
        *,
        label: str,
        timeout: int = 60000,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout / 1000
        last: dict[str, Any] = {}
        while time.monotonic() < deadline:
            self._dismiss_blocking_modals(page)
            last = page.evaluate(r'''(terms) => {
              const visible = (el) => {
                const r = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
              };
              const text = document.body ? (document.body.innerText || document.body.textContent || '') : '';
              const compact = String(text || '').replace(/\s+/g, '').trim();
              const readyTerm = terms.find(term => text.includes(term));
              const loadingNodes = Array.from(document.querySelectorAll(
                '.ant-spin-spinning, .vxe-loading, .vxe-loading--wrapper, .el-loading-mask, .loading, [class*="loading"], [class*="Loading"]'
              )).filter(visible);
              const loadingText = loadingNodes
                .map(el => (el.innerText || el.textContent || '').replace(/\s+/g, '').trim())
                .join('');
              const loading = (
                loadingNodes.length > 0
                || compact.includes('LOADING')
                || compact.includes('加载中')
                || compact.includes('正在加载')
              ) && !readyTerm;
              const rows = Array.from(document.querySelectorAll('tr.vxe-body--row, tr, .ant-table-row')).filter(visible).length;
              const inputs = Array.from(document.querySelectorAll('input, textarea')).filter(visible).length;
              return {
                ready: Boolean(readyTerm) && !loading,
                ready_term: readyTerm || null,
                loading,
                loading_count: loadingNodes.length,
                rows,
                inputs,
                text_excerpt: text.slice(0, 500),
                url: location.href,
                title: document.title,
                loading_text: loadingText.slice(0, 200),
              };
            }''', terms)
            if last.get('ready'):
                return last
            page.wait_for_timeout(1000)
        excerpt = (last.get('text_excerpt') or '').replace('\n', ' ')[:180]
        raise RuntimeError(
            f'{label} {timeout // 1000} 秒内仍未加载完成；'
            f'请检查网络、店小秘接口或页面是否被遮罩阻塞。'
            f'最后状态 loading={last.get("loading")} rows={last.get("rows")} inputs={last.get("inputs")} text={excerpt}'
        )

    def _open_editor_page_for_product(self, page: Page, product_query: str, store_name: str | None = None) -> Page:
        draft_url = WORKFLOW_TARGETS['draft_box']['url']
        page.goto(draft_url, wait_until='domcontentloaded', timeout=45000)
        self._wait_for_page_ready(
            page,
            WORKFLOW_READY_TERMS['draft_box'],
            label='速卖通采集箱',
            timeout=60000,
        )
        self._dismiss_blocking_modals(page)
        claim_mark = self._current_claim_mark(product_query=product_query, store_name=store_name)
        self._search_draft_box(page, product_query=product_query, store_name=store_name)
        try:
            row_info = self._find_draft_box_row(page, product_query, store_name=store_name, claim_mark=claim_mark)
        except RuntimeError:
            if not store_name:
                raise
            self._search_draft_box(page, product_query=None, store_name=store_name)
            row_info = self._find_draft_box_row(page, product_query, store_name=store_name, claim_mark=claim_mark)
        editor_page = self._open_editor_from_draft_box(page, row_info=row_info)
        editor_page.wait_for_timeout(1500)
        return editor_page

    def _current_claim_mark(self, product_query: str | None = None, store_name: str | None = None) -> str | None:
        state = self.get_state()
        claim_mark = state.get('note_text')
        if not claim_mark:
            return None
        if product_query and state.get('product_query') and state.get('product_query') != product_query:
            return None
        if store_name and state.get('store_name') and state.get('store_name') != store_name:
            return None
        return claim_mark

    def _search_draft_box(self, page: Page, product_query: str | None = None, store_name: str | None = None) -> None:
        if not product_query and not store_name:
            return
        if store_name:
            page.evaluate(r'''(store) => {
          const norm = (s) => String(s || '').replace(/\s+/g, '').trim();
          const scoped = Array.from(document.querySelectorAll('.shop-con .d-tag-group-item, .shop-con .d-tag-group-item *'));
          const storeEl = scoped.find(el => norm(el.innerText || el.textContent) === norm(store));
          const storeTarget = storeEl && (storeEl.closest('.d-tag-group-item') || storeEl);
          if (storeTarget) storeTarget.dispatchEvent(new MouseEvent('click', {bubbles:true}));
        }''', store_name)
            page.wait_for_timeout(1200)
            self._dismiss_blocking_modals(page)
        if product_query is not None or store_name:
            page.evaluate(r'''(frag) => {
          const norm = (s) => String(s || '').replace(/\s+/g, '').trim();
          const all = Array.from(document.querySelectorAll('*'));
          const input = Array.from(document.querySelectorAll('input.ant-input,input')).find(el => {
            const r = el.getBoundingClientRect();
            return r.width > 220 && r.height > 20 && !el.disabled;
          });
          if (input) {
            input.value = frag || '';
            input.dispatchEvent(new Event('input', {bubbles:true}));
            input.dispatchEvent(new Event('change', {bubbles:true}));
          }
          const btn = all.find(el => norm(el.innerText || el.textContent) === '搜索');
          if (btn) btn.dispatchEvent(new MouseEvent('click', {bubbles:true}));
        }''', product_query)
        self._wait_for_page_ready(
            page,
            ['标题/产品ID', '暂无数据', '移入待发布', '编辑'],
            label='采集箱搜索结果',
            timeout=30000,
        )
        self._dismiss_blocking_modals(page)

    def _find_draft_box_row(
        self,
        page: Page,
        product_query: str | None = None,
        store_name: str | None = None,
        claim_mark: str | None = None,
        target_source_urls: list[str] | None = None,
    ) -> dict[str, Any]:
        row_info = page.evaluate(r'''({frag, store, claimMark, targetSourceUrls}) => {
          const rows = Array.from(document.querySelectorAll('tr.vxe-body--row, tr'));
          const normText = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
          const sourceUrls = (row) => Array.from(row.querySelectorAll('a[href]'))
            .map(a => String(a.href || a.getAttribute('href') || ''))
            .filter(url => url.includes('goods_id=') || url.includes('detail.1688.com') || url.includes('yangkeduo.com'));
          const claim = claimMark;
          const targetUrls = Array.isArray(targetSourceUrls) ? targetSourceUrls.filter(Boolean).map(String) : [];
          const hasTargetSource = (row) => {
            if (!targetUrls.length) return false;
            const urls = sourceUrls(row);
            return urls.some(url => targetUrls.some(target => url === target || url.includes(target) || target.includes(url)));
          };
          const candidates = rows.map((tr, idx) => ({idx, text:normText(tr)})).filter(x => {
            if (!x.text) return false;
            if (store && !x.text.includes(`「${store}」`) && !x.text.includes(store)) return false;
            if (claim && x.text.includes(claim)) return true;
            if (hasTargetSource(rows[x.idx])) return true;
            return frag ? x.text.includes(frag) : ['移入待发布','编辑','发布','更多'].some(k => x.text.includes(k));
          });
          const claimMatches = claim ? candidates.filter(x => x.text.includes(claim)) : [];
          if (claimMatches.length > 1) {
            return {ok:false, ambiguous:true, matches:claimMatches.map(x => ({rowIndex:x.idx, rowText:x.text.slice(0,300)}))};
          }
          if (claimMatches.length === 1) {
            const row = rows[claimMatches[0].idx];
            const actions = Array.from(row.querySelectorAll('*')).map(el => {
              const txt = normText(el);
              const r = el.getBoundingClientRect();
              if (!txt || r.width < 5 || r.height < 5) return null;
              if (!['移入待发布','编辑','发布','更多'].includes(txt)) return null;
              return {txt, tag: el.tagName, cls: String(el.className || ''), rect: {x:r.x,y:r.y,w:r.width,h:r.height}};
            }).filter(Boolean);
            return {ok:true, rowIndex:claimMatches[0].idx, rowText:claimMatches[0].text.slice(0,700), sourceUrls:sourceUrls(row), actions, matchedBy:'claim_mark'};
          }
          const sourceMatches = targetUrls.length ? candidates.filter(x => hasTargetSource(rows[x.idx])) : [];
          if (sourceMatches.length > 1) {
            return {ok:false, ambiguous:true, matches:sourceMatches.map(x => ({rowIndex:x.idx, rowText:x.text.slice(0,300), sourceUrls:sourceUrls(rows[x.idx])}))};
          }
          if (sourceMatches.length === 1) {
            const row = rows[sourceMatches[0].idx];
            const actions = Array.from(row.querySelectorAll('*')).map(el => {
              const txt = normText(el);
              const r = el.getBoundingClientRect();
              if (!txt || r.width < 5 || r.height < 5) return null;
              if (!['移入待发布','编辑','发布','更多'].includes(txt)) return null;
              return {txt, tag: el.tagName, cls: String(el.className || ''), rect: {x:r.x,y:r.y,w:r.width,h:r.height}};
            }).filter(Boolean);
            return {ok:true, rowIndex:sourceMatches[0].idx, rowText:sourceMatches[0].text.slice(0,700), sourceUrls:sourceUrls(row), actions, matchedBy:'source_url'};
          }
          if (frag && candidates.length > 1) {
            return {ok:false, ambiguous:true, matches:candidates.map(x => ({rowIndex:x.idx, rowText:x.text.slice(0,300)}))};
          }
          const picked = candidates.find(x => !x.text.includes('备注:')) || candidates[0] || null;
          if (!picked) return {ok:false, matches:candidates};
          const row = rows[picked.idx];
          const actions = Array.from(row.querySelectorAll('*')).map(el => {
            const txt = normText(el);
            const r = el.getBoundingClientRect();
            if (!txt || r.width < 5 || r.height < 5) return null;
            if (!['移入待发布','编辑','发布','更多'].includes(txt)) return null;
            return {txt, tag: el.tagName, cls: String(el.className || ''), rect: {x:r.x,y:r.y,w:r.width,h:r.height}};
          }).filter(Boolean);
          return {ok:true, rowIndex:picked.idx, rowText:picked.text.slice(0,700), sourceUrls:sourceUrls(row), actions};
        }''', {'frag': product_query, 'store': store_name, 'claimMark': claim_mark, 'targetSourceUrls': target_source_urls or []})
        if not row_info or not row_info.get('ok'):
            if row_info and row_info.get('ambiguous'):
                raise RuntimeError(f'目标商品行不唯一，请提供更精确的商品标题或唯一标识：{product_query}')
            raise RuntimeError(f'未找到目标商品行：{product_query or "首个可操作商品"}')
        return row_info

    def _add_note_to_draft_row(
        self,
        page: Page,
        row_info: dict[str, Any],
        note_text: str,
        product_query: str | None = None,
        store_name: str | None = None,
    ) -> dict[str, Any]:
        actions = row_info.get('actions', [])
        more = (
            next((a for a in actions if a.get('txt') == '更多' and 'ant-dropdown-trigger' in str(a.get('cls', ''))), None)
            or next((a for a in actions if a.get('txt') == '更多' and a.get('tag') in {'A', 'SPAN'}), None)
            or next((a for a in actions if a.get('txt') == '更多'), None)
        )
        if not more:
            raise RuntimeError('目标商品行未找到更多入口')
        self._click_rect_center(page, more['rect'])
        page.wait_for_timeout(1500)

        add_note = page.evaluate(r'''() => {
          const el = Array.from(document.querySelectorAll('li.ant-dropdown-menu-item')).find(el => {
            return (el.innerText || el.textContent || '').replace(/\s+/g, '').trim() === '添加备注';
          });
          if (!el) return null;
          const r = el.getBoundingClientRect();
          return {rect:{x:r.x,y:r.y,w:r.width,h:r.height}};
        }''')
        if not add_note:
            raise RuntimeError('未找到添加备注入口')
        self._click_rect_center(page, add_note['rect'])
        page.wait_for_timeout(1500)

        write_res = page.evaluate(r'''(note) => {
          const modal = Array.from(document.querySelectorAll('[role="dialog"], .ant-modal-wrap, .ant-modal')).find(el => {
            const t = (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
            return t.includes('备注');
          });
          if (!modal) return {ok:false, reason:'未找到备注弹窗'};
          const field = Array.from(modal.querySelectorAll('textarea,input')).find(el => {
            const r = el.getBoundingClientRect();
            return r.width > 150 && r.height > 20 && !el.disabled;
          });
          if (!field) return {ok:false, reason:'未找到备注输入框'};
          field.value = note;
          field.dispatchEvent(new Event('input', {bubbles:true}));
          field.dispatchEvent(new Event('change', {bubbles:true}));
          const submit = Array.from(modal.querySelectorAll('button,span,a,div')).find(el => {
            return (el.innerText || el.textContent || '').replace(/\s+/g, '').trim() === '提交';
          });
          if (!submit) return {ok:false, reason:'未找到提交按钮'};
          submit.dispatchEvent(new MouseEvent('click', {bubbles:true}));
          return {ok:true};
        }''', note_text)
        if not write_res.get('ok'):
            raise RuntimeError(write_res.get('reason') or '提交备注失败')
        page.wait_for_timeout(2500)

        verify = page.evaluate(r'''({rowIndex, note}) => {
          const rows = Array.from(document.querySelectorAll('tr.vxe-body--row, tr'));
          const rowTexts = rows.map(row => (row.innerText || row.textContent || '').replace(/\s+/g, ' ').trim());
          const fallbackText = rowTexts[rowIndex] || '';
          const text = fallbackText.slice(0,700);
          return {verified:fallbackText.includes(note), rowText:text};
        }''', {'rowIndex': row_info.get('rowIndex'), 'note': note_text})
        if verify and verify.get('verified'):
            return verify
        if store_name or product_query:
            try:
                self._search_draft_box(page, product_query=None, store_name=store_name)
                page.wait_for_timeout(1000)
                fallback_verify = page.evaluate(r'''({note, store}) => {
                  const rows = Array.from(document.querySelectorAll('tr.vxe-body--row, tr'));
                  const texts = rows.map(row => (row.innerText || row.textContent || '').replace(/\s+/g, ' ').trim());
                  const matches = texts.filter(text => {
                    if (!text.includes(note)) return false;
                    if (!store) return true;
                    return text.includes(`「${store}」`) || text.includes(store);
                  });
                  if (matches.length === 1) {
                    return {verified:true, rowText:matches[0].slice(0,700), verifiedBy:'claim_mark_store_search'};
                  }
                  return {
                    verified:false,
                    rowText:(matches[0] || '').slice(0,700),
                    matchCount:matches.length,
                    verifiedBy:'claim_mark_store_search'
                  };
                }''', {'note': note_text, 'store': store_name})
                if fallback_verify and fallback_verify.get('verified'):
                    fallback_verify['initialRowText'] = (verify or {}).get('rowText')
                    return fallback_verify
                if verify is not None:
                    verify['fallbackVerify'] = fallback_verify
            except Exception as exc:
                if verify is not None:
                    verify['fallbackError'] = str(exc)
        return verify or {}

    def _click_rect_center(self, page: Page, rect: dict[str, Any]) -> None:
        page.mouse.click(rect['x'] + rect['w'] / 2, rect['y'] + rect['h'] / 2)

    def _open_editor_from_draft_box(self, page: Page, row_info: dict[str, Any] | None = None) -> Page:
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

        actions = (row_info or {}).get('actions', [])
        edit_action = (
            next((a for a in actions if a.get('txt') == '编辑' and a.get('tag') == 'A'), None)
            or next((a for a in actions if a.get('txt') == '编辑' and a.get('tag') in {'A', 'SPAN'}), None)
            or next((a for a in actions if a.get('txt') == '编辑'), None)
        )
        if edit_action:
            if hasattr(self._context, 'expect_page'):
                try:
                    with self._context.expect_page(timeout=8000) as new_page_info:
                        self._click_rect_center(page, edit_action['rect'])
                    new_page = new_page_info.value
                    new_page.wait_for_load_state('domcontentloaded', timeout=10000)
                    new_page.wait_for_timeout(1500)
                    if '/web/smt/edit' in new_page.url:
                        return new_page
                    page = new_page
                except TimeoutError:
                    page.wait_for_timeout(1500)
            else:
                self._click_rect_center(page, edit_action['rect'])
                page.wait_for_timeout(1500)
        else:
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
