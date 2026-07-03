import asyncio
import json
import os
import re
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urljoin, urlparse

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, TimeoutError, sync_playwright

from src.core.config import DATA_DIR, SCREENSHOT_DIR, SESSION_DIR
from src.execution.browser_runtime import chrome_launch_options
from src.execution.dxm_live import DxmLiveClient
from src.services.agent_console import HUD_INIT_SCRIPT
from src.utils import now_iso

RUNTIME_STATE_FILE = SESSION_DIR / 'dianxiaomi_runtime_state.json'
LOGIN_SCREENSHOT_FILE = SCREENSHOT_DIR / 'dianxiaomi_login_start.png'
LOGIN_RESULT_SCREENSHOT_FILE = SCREENSHOT_DIR / 'dianxiaomi_login_result.png'
WORKFLOW_BROWSER_PROFILE_DIR = DATA_DIR / 'browser_profiles' / 'dxm_workflow'
VISIBLE_CDP_CONNECT_TIMEOUT_MS = 8000
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
ACQUISITION_ACTION_SCREENSHOT_MAP = {
    'claim': SCREENSHOT_DIR / 'dianxiaomi_data_acquisition_claim.png',
    'verify': SCREENSHOT_DIR / 'dianxiaomi_draft_box_claim_verified.png',
}
DATA_ACQUISITION_CLAIM_FORBIDDEN_TERMS = (
    '保存',
    '发布',
    '立即发布',
    '继续发布',
    '保存并发布',
    '保存并移入待发布',
    '移入待发布',
    '批量发布',
)
DATA_ACQUISITION_CLAIM_ACTION_TERMS = ('认领', '领取')
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
        'message': '已进入产品列表页，可以继续往已有待认领列表或产品管理操作。',
        'next_action': '继续切到已有待认领列表或商品箱视图。',
    },
    'data_acquisition': {
        'url': 'https://www.dianxiaomi.com/web/productCrawl/dataAcquisition',
        'label': '已有待认领列表',
        'message': '已进入店小秘已有待认领列表，可以继续认领到商品箱。',
        'next_action': '继续切换到商品箱或执行认领。',
    },
    'draft_box': {
        'url': 'https://www.dianxiaomi.com/web/smt/smtProductList/draft?status=0',
        'label': '商品箱',
        'message': '已进入商品箱，可继续查看备注、编辑和发布动作。',
        'next_action': '继续执行添加备注、编辑产品或发布前检查。',
    },
}
WORKFLOW_READY_TERMS = {
    'product': ['产品列表', '标题 / 产品ID', '标题/产品ID', '操作'],
    'data_acquisition': ['数据采集', '搜索内容', '认领', '采集箱'],
    'draft_box': ['店铺账号', '搜索内容', '标题/产品ID', '移入待发布', '编辑'],
}
WORKFLOW_HUMAN_STEP_COPY = {
    'data_acquisition_claim:open_start': '打开已有待认领列表',
    'data_acquisition_claim:page_ready_done': '确认待认领列表可操作',
    'data_acquisition_claim:initial_settle_done': '等待待认领列表稳定',
    'data_acquisition_claim:dismiss_before_search_skipped': '准备匹配已有待认领商品',
    'data_acquisition_claim:search_start': '筛选已有待认领商品',
    'data_acquisition_search:source_input_filled': '来源链接仅作匹配',
    'data_acquisition_search:start_collect_clicked': '已阻止创建新来源商品',
    'data_acquisition_search:collect_result_ready': '等待列表刷新',
    'data_acquisition_search:source_input_submitted': '等待列表刷新',
    'data_acquisition_search:result_ready_wait_skipped': '等待列表刷新',
    'data_acquisition_claim:target_find_start': '定位待认领商品',
    'data_acquisition_claim:source_lookup_start': '匹配来源链接',
    'data_acquisition_claim:source_lookup_dom_scan_done': '匹配来源链接',
    'data_acquisition_claim:target_find_done': '确认待认领商品',
    'data_acquisition_claim:click_claim_start': '点击认领按钮',
    'data_acquisition_claim:click_claim_done': '已点击认领按钮',
    'data_acquisition_claim:dialog_start': '确认认领弹窗',
    'data_acquisition_claim:dialog_done': '完成认领确认',
    'data_acquisition_claim:screenshot_start': '保存认领证据',
    'data_acquisition_claim:done': '认领到商品箱完成',
}

DATA_ACQUISITION_NOTICE_AUTO_DISMISS_SCRIPT = r'''
(() => {
  if (window.__dxmAgentDataAcquisitionNoticeAutoDismissInstalled) return;
  window.__dxmAgentDataAcquisitionNoticeAutoDismissInstalled = true;
  const norm = (s) => String(s || '').replace(/\s+/g, '').trim();
  const isVisible = (el) => {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
  };
  const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
  const isNoticeLike = (el, compact) => {
    const cls = String(el.className || '');
    return cls.includes('notice')
      || cls.includes('Notice')
      || cls.includes('activity')
      || cls.includes('Activity')
      || compact.includes('线下活动')
      || compact.includes('小秘公告')
      || compact.includes('活动亮点')
      || compact.includes('公告');
  };
  const hasDangerousMutationText = (compact) => [
    '立即发布',
    '继续发布',
    '保存并发布',
    '确认发布',
    '提交发布',
    '保存并移入待发布',
    '移入待发布',
  ].some(term => compact.includes(norm(term)));
  const closeNotice = () => {
    const selectors = [
      '.notice-list-modal',
      '.ant-modal-wrap',
      '.ant-modal',
      '[role="dialog"]',
      '[class*="notice"]',
      '[class*="Notice"]',
      '[class*="activity"]',
      '[class*="Activity"]'
    ].join(',');
    const modals = Array.from(document.querySelectorAll(selectors))
      .filter(isVisible)
      .map(el => ({el, text: textOf(el), compact: norm(textOf(el))}))
      .filter(item => item.text && isNoticeLike(item.el, item.compact) && !hasDangerousMutationText(item.compact));
    for (const item of modals) {
      const modal = item.el;
      const controls = Array.from(modal.querySelectorAll('.ant-modal-close, .ant-modal-close-x, .close, .close-btn, .notice-close, [class*="close"], [aria-label*="Close"], [aria-label*="关闭"], button, a, span, div'))
        .filter(isVisible)
        .map(el => ({
          el,
          text: norm(el.innerText || el.textContent || el.getAttribute('aria-label') || el.getAttribute('title') || ''),
          cls: String(el.className || ''),
          tag: String(el.tagName || '').toLowerCase(),
        }))
        .filter(item => {
          if (['开始采集', '一键发布', '采集并一键发布', '认领', '批量认领', '保存', '发布'].includes(item.text)) return false;
          return item.text === '关闭'
            || item.text === '知道了'
            || item.text === '我知道了'
            || item.cls.includes('ant-modal-close')
            || item.cls.includes('close')
            || item.cls.includes('Close');
        });
      const target = controls.find(item => item.text === '关闭')
        || controls.find(item => item.cls.includes('ant-modal-close') || item.cls.includes('close') || item.cls.includes('Close'))
        || controls[0];
      if (target) {
        try { target.el.click(); } catch (_) {}
      }
      setTimeout(() => {
        if (document.body.contains(modal) && isVisible(modal)) {
          try { modal.remove(); } catch (_) { modal.style.display = 'none'; }
        }
        document.querySelectorAll('.ant-modal-mask, .modal-backdrop, [class*="modal-mask"]').forEach(mask => {
          if (isVisible(mask)) {
            try { mask.remove(); } catch (_) { mask.style.display = 'none'; }
          }
        });
      }, 200);
    }
  };
  closeNotice();
  const timer = window.setInterval(closeNotice, 500);
  const observer = new MutationObserver(closeNotice);
  const start = () => {
    if (document.documentElement) {
      observer.observe(document.documentElement, {childList: true, subtree: true});
    }
  };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start, {once: true});
  } else {
    start();
  }
  window.setTimeout(() => {
    window.clearInterval(timer);
    observer.disconnect();
  }, 30000);
})();
'''


class DxmLoginFlow:
    def __init__(self, live_client: DxmLiveClient, state_file: Path | None = None) -> None:
        self.live_client = live_client
        self.state_file = state_file or RUNTIME_STATE_FILE
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._browser_session_thread_id: int | None = None
        self._latest_live_hud: dict[str, Any] | None = None
        self._live_hud_reapply_pending = False
        self._live_hud_bound_page_ids: set[int] = set()
        self._live_hud_bound_context_ids: set[int] = set()
        self._data_acquisition_notice_bound_context_ids: set[int] = set()
        self._last_dismiss_blocking_modals_trace: list[dict[str, Any]] = []
        self._recent_workflow_events: list[dict[str, Any]] = []
        self._workflow_event_listener: Callable[[dict[str, Any]], None] | None = None
        self._remote_debugging_port: int | None = None
        self._external_browser_process: subprocess.Popen | None = None

    def set_workflow_event_listener(self, listener: Callable[[dict[str, Any]], None] | None) -> None:
        self._workflow_event_listener = listener if callable(listener) else None

    def recent_workflow_events(self, limit: int = 20) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        return list(self._recent_workflow_events[-limit:])

    def get_state(self) -> dict[str, Any]:
        if self.state_file.exists():
            return json.loads(self.state_file.read_text(encoding='utf-8'))
        return self._default_state()

    def update_live_hud(self, hud: dict[str, Any]) -> dict[str, Any]:
        self._latest_live_hud = dict(hud)
        page = self._page
        if page is None:
            return {'ok': True, 'updated': False, 'reason': 'live_browser_page_missing'}
        try:
            return self._apply_live_hud(page, hud)
        except Exception as exc:
            return {
                'ok': False,
                'updated': False,
                'reason': 'live_browser_hud_apply_failed',
                'error': str(exc),
            }

    def _apply_live_hud(self, page: Page, hud: dict[str, Any]) -> dict[str, Any]:
        self._attach_live_hud_runtime_hooks(page)
        try:
            page.add_init_script(HUD_INIT_SCRIPT)
        except Exception:
            pass
        try:
            self._evaluate_zero_arg_page_function_with_runtime_timeout(
                page,
                f"() => {{\n{HUD_INIT_SCRIPT}\nreturn true;\n}}",
                timeout=750,
            )
        except Exception:
            pass
        self._evaluate_page_function_with_runtime_timeout(
            page,
            """
            (hud) => {
              window.__dxmAgentHudState = hud;
              try {
                window.sessionStorage.setItem('__dxmAgentHudPersistedState', JSON.stringify(hud));
              } catch (error) {}
              try {
                window.localStorage.setItem('__dxmAgentHudPersistedState', JSON.stringify(hud));
              } catch (error) {}
              if (window.__dxmRenderAgentHud) window.__dxmRenderAgentHud();
            }
            """,
            hud,
            timeout=750,
        )
        self._live_hud_reapply_pending = False
        return {
            'ok': True,
            'updated': True,
            'reason': 'live_browser_hud_updated',
            'hud': hud,
            'page_title': self._safe_live_hud_page_title(page),
            'current_url': page.url,
            'updated_at': now_iso(),
        }

    def _safe_live_hud_page_title(self, page: Page) -> str:
        try:
            title = self._evaluate_zero_arg_page_function_with_runtime_timeout(
                page,
                "() => document.title || ''",
                timeout=500,
            )
            return str(title or '')
        except Exception:
            return ''

    def _mark_live_hud_reapply_pending(self, *_args) -> None:
        self._live_hud_reapply_pending = True

    def _trace_workflow_event(self, event: str, **payload: Any) -> None:
        record = {
            'ts': now_iso(),
            'event': event,
            **payload,
        }
        if not record.get('human_step'):
            record['human_step'] = WORKFLOW_HUMAN_STEP_COPY.get(event) or event
        self._recent_workflow_events.append(record)
        del self._recent_workflow_events[:-400]
        listener = self._workflow_event_listener
        if listener:
            try:
                listener(dict(record))
            except Exception:
                pass
        trace_file = os.getenv('DXM_WORKFLOW_TRACE_FILE')
        if not trace_file:
            return
        try:
            path = Path(trace_file)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('a', encoding='utf-8') as fh:
                fh.write(json.dumps(record, ensure_ascii=False, default=str) + '\n')
        except Exception:
            pass

    def _attach_live_hud_runtime_hooks(self, page: Page | None) -> None:
        if page is None:
            return
        page_id = id(page)
        if page_id not in self._live_hud_bound_page_ids:
            self._live_hud_bound_page_ids.add(page_id)
            try:
                page.add_init_script(HUD_INIT_SCRIPT)
            except Exception:
                pass
            for event_name in ('framenavigated', 'domcontentloaded'):
                try:
                    page.on(event_name, self._mark_live_hud_reapply_pending)
                except Exception:
                    pass

        context = getattr(page, 'context', None)
        if context is None:
            return
        context_id = id(context)
        if context_id in self._live_hud_bound_context_ids:
            return
        self._live_hud_bound_context_ids.add(context_id)
        try:
            context.add_init_script(HUD_INIT_SCRIPT)
        except Exception:
            pass
        try:
            context.on('page', self._mark_live_hud_reapply_pending)
        except Exception:
            pass

    def _attach_and_reapply_live_hud_page(self, page: Page) -> None:
        self._attach_live_hud_runtime_hooks(page)
        self._reapply_live_hud_if_available(page)

    def _reapply_live_hud_if_available(self, page: Page) -> None:
        if not self._latest_live_hud:
            return
        try:
            self._apply_live_hud(page, self._latest_live_hud)
            self._live_hud_reapply_pending = False
        except Exception:
            pass

    def _goto_with_live_hud(self, page: Page, url: str, *, wait_until: str = 'domcontentloaded', timeout: int = 45000) -> None:
        self._trace_workflow_event('goto:start', url=url, current_url=getattr(page, 'url', None), wait_until=wait_until, timeout=timeout)
        self._attach_live_hud_runtime_hooks(page)
        self._trace_workflow_event('goto:attached_hud', url=url, current_url=getattr(page, 'url', None))
        page.goto(url, wait_until=wait_until, timeout=timeout)
        self._trace_workflow_event('goto:finished', url=url, current_url=page.url)
        self._reapply_live_hud_if_available(page)
        self._trace_workflow_event('goto:reapplied_hud', url=url, current_url=page.url)

    def _goto_sterile(self, page: Page, url: str, *, wait_until: str = 'domcontentloaded', timeout: int = 45000) -> None:
        self._trace_workflow_event('goto:sterile_start', url=url, current_url=getattr(page, 'url', None), wait_until=wait_until, timeout=timeout)
        page.goto(url, wait_until=wait_until, timeout=timeout)
        self._trace_workflow_event('goto:sterile_finished', url=url, current_url=page.url)

    def _goto_data_acquisition_sterile(self, page: Page, url: str, *, wait_until: str = 'domcontentloaded', timeout: int = 45000) -> None:
        self._trace_workflow_event(
            'data_acquisition_open:sterile_goto_start',
            url=url,
            current_url=getattr(page, 'url', None),
            wait_until=wait_until,
            timeout=timeout,
            human_step='打开已有待认领列表',
        )
        page.goto(url, wait_until=wait_until, timeout=timeout)
        self._trace_workflow_event(
            'data_acquisition_open:sterile_goto_finished',
            url=url,
            current_url=getattr(page, 'url', None),
            human_step='已有待认领列表已打开',
        )
        self._trace_workflow_event(
            'data_acquisition_open:sterile_settle',
            seconds=3.0,
            human_step='等待页面自行加载',
        )
        time.sleep(3.0)

    def _is_current_page_url(self, page: Page, url: str) -> bool:
        try:
            current = urlparse(str(getattr(page, 'url', '') or ''))
            target = urlparse(url)
        except Exception:
            return False
        return (
            bool(current.netloc)
            and current.netloc.casefold() == target.netloc.casefold()
            and current.path.rstrip('/') == target.path.rstrip('/')
        )

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
            self._keep_visible_browser_for_recovery(state)
            self._write_state(state)
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
            'browser_visible': browser_state.get('browser_visible') is True,
            'updated_at': now_iso(),
            'username': username,
            'password_mask': self._mask_secret(password),
        }
        self._write_state(state)
        return state

    def continue_login(self) -> dict[str, Any]:
        try:
            submit_state = self._submit_login_after_captcha()
        except Exception as exc:
            state = self._error_state(
                stage='login_failed',
                label='继续失败',
                message=f'继续登录失败：{exc}',
                next_action='真实浏览器窗口会保留；请确认验证码是否完成，必要时在窗口内修正后再次检测，或重新打开官网登录页。',
            )
            state['browser_visible'] = not self._is_headless()
            self._write_state(state)
            return state
        try:
            live_status = self.live_client.probe_session()
        except Exception as exc:
            if self._submit_state_looks_logged_in(submit_state):
                state = self._login_success_state_from_submit(submit_state)
                self._write_state(state)
                return state
            state = self._error_state(
                stage='login_failed',
                label='继续失败',
                message=f'继续登录失败：{exc}',
                next_action='真实浏览器窗口会保留；请确认验证码是否完成，必要时在窗口内修正后再次检测，或重新打开官网登录页。',
            )
            state['browser_visible'] = not self._is_headless()
            self._write_state(state)
            return state
        if live_status.get('logged_in'):
            state = {
                'stage': 'login_success',
                'label': '已登录',
                'message': '登录成功，已进入真实店小秘后台。',
                'next_action': '真实浏览器窗口会保留；可继续进入已有待认领列表、商品箱和编辑流程。',
                'requires_user_action': False,
                'page_title': live_status.get('title') or live_status.get('product_page', {}).get('title') or '店小秘首页',
                'page_url': live_status.get('final_url') or live_status.get('product_page', {}).get('url') or 'https://www.dianxiaomi.com/index.htm',
                'screenshot_url': submit_state.get('screenshot_url') or live_status.get('home_screenshot_url') or live_status.get('product_page', {}).get('screenshot_url'),
                'browser_visible': not self._is_headless(),
                'updated_at': now_iso(),
            }
        elif self._submit_state_looks_logged_in(submit_state):
            state = self._login_success_state_from_submit(submit_state)
        else:
            state = {
                'stage': 'login_failed',
                'label': '登录失败',
                'message': '继续登录后仍未检测到有效登录态，请检查验证码、账号密码或页面结构变化。',
                'next_action': '真实浏览器窗口会保留；请在窗口内修正验证码或账号密码后，再点击检测登录态。',
                'requires_user_action': True,
                'page_title': live_status.get('title') or '店小秘官网登录页',
                'page_url': live_status.get('final_url') or submit_state.get('page_url') or 'https://www.dianxiaomi.com/',
                'screenshot_url': submit_state.get('screenshot_url') or live_status.get('home_screenshot_url') or live_status.get('product_page', {}).get('screenshot_url'),
                'browser_visible': not self._is_headless(),
                'updated_at': now_iso(),
            }
        self._write_state(state)
        return state

    def check_visible_login_state(self) -> dict[str, Any]:
        home_url = 'https://www.dianxiaomi.com/web/home'
        try:
            page = self._ensure_page_with_cookies()
            self._trace_workflow_event(
                'visible_login_check:start',
                url=home_url,
                current_url=getattr(page, 'url', None),
                human_step='检查执行浏览器登录态',
            )
            self._goto_sterile(page, home_url, wait_until='domcontentloaded', timeout=45000)
            self._force_foreground_dxm_window()
            page.wait_for_timeout(3000)
            login_check = self._inspect_visible_login_state(page)
            visible_logged_in = login_check.get('logged_in') is True
            self._trace_workflow_event(
                'visible_login_check:done',
                url=getattr(page, 'url', None),
                visible_logged_in=visible_logged_in,
                body_excerpt=login_check.get('body_excerpt'),
                human_step='执行浏览器登录态检查完成',
            )
            screenshot_url = None
            page_title = '店小秘登录态检查'
            unreadable_home = login_check.get('reason') == 'home_body_empty'
            if visible_logged_in:
                self._persist_visible_browser_cookies()
                state = {
                    'stage': 'login_success',
                    'label': '已登录',
                    'message': '执行浏览器已登录店小秘，可以继续真实操作。',
                    'next_action': '继续进入待认领商品或商品箱编辑保存。',
                    'requires_user_action': False,
                    'page_title': page_title or '店小秘首页',
                    'page_url': getattr(page, 'url', None) or home_url,
                    'screenshot_url': screenshot_url,
                    'browser_visible': not self._is_headless(),
                    'visible_logged_in': True,
                    'login_check': login_check,
                    'updated_at': now_iso(),
                }
            elif unreadable_home:
                state = {
                    'stage': 'login_page_unreadable',
                    'label': '店小秘页面未加载完成',
                    'message': '执行浏览器已打开店小秘首页，但页面内容为空，无法确认登录状态。',
                    'next_action': '请在真实浏览器刷新页面；如果仍为空，重启真实浏览器执行器后重新检测。',
                    'requires_user_action': True,
                    'page_title': page_title or '店小秘首页',
                    'page_url': getattr(page, 'url', None) or home_url,
                    'screenshot_url': screenshot_url,
                    'browser_visible': not self._is_headless(),
                    'visible_logged_in': False,
                    'login_check': login_check,
                    'updated_at': now_iso(),
                }
            else:
                state = {
                    'stage': 'login_failed',
                    'label': '执行浏览器未登录',
                    'message': '执行浏览器还没有登录店小秘；请在打开的真实浏览器完成登录后再检测。',
                    'next_action': '点击打开真实登录页，或在当前浏览器内完成登录后重新检测。',
                    'requires_user_action': True,
                    'page_title': page_title or '店小秘官网登录页',
                    'page_url': getattr(page, 'url', None) or home_url,
                    'screenshot_url': screenshot_url,
                    'browser_visible': not self._is_headless(),
                    'visible_logged_in': False,
                    'login_check': login_check,
                    'updated_at': now_iso(),
                }
            self._write_state(state)
            return state
        except Exception as exc:
            state = self._error_state(
                stage='login_failed',
                label='执行浏览器检查失败',
                message=f'检查执行浏览器登录态失败：{exc}',
                next_action='真实浏览器窗口会保留；请检查页面后重新检测。',
            )
            state['browser_visible'] = not self._is_headless()
            self._keep_visible_browser_for_recovery(state)
            self._write_state(state)
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
                next_action='确认登录态有效，必要时在真实浏览器内修正页面后再试。',
            )
            self._keep_visible_browser_for_recovery(state)
            self._write_state(state)
            return state

        config = WORKFLOW_TARGETS[target]
        state = {
            'stage': 'workflow_navigation',
            'label': config['label'],
            'message': config['message'],
            'next_action': f"真实浏览器窗口会保留；{config['next_action']}",
            'requires_user_action': False,
            'page_title': result.get('page_title') or config['label'],
            'page_url': result.get('page_url') or config['url'],
            'screenshot_url': result.get('screenshot_url'),
            'browser_visible': not self._is_headless(),
            'updated_at': now_iso(),
            'current_nav': target,
            'dismissed_blocking_modals': result.get('dismissed_blocking_modals'),
            'dismissed_blocking_modals_trace': result.get('dismissed_blocking_modals_trace') or [],
        }
        self._write_state(state)
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
                message=f'不支持的商品箱动作：{action}',
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
                message=f'执行商品箱动作失败：{exc}',
                next_action='确认已进入商品箱且页面结构未变，再重试动作。',
            )
            self._keep_visible_browser_for_recovery(state)
            self._write_state(state)
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
            return state

        state = {
            'stage': 'draft_box_action',
            'label': '商品箱动作已触发',
            'message': self._draft_box_action_message(action, note_text),
            'next_action': '继续验证页面回显或进入下一步。',
            'requires_user_action': False,
            'page_title': result.get('page_title') or '速卖通商品箱',
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
        return state

    def claim_from_data_acquisition(
        self,
        claim_mark: str,
        product_query: str | None = None,
        category_name: str | None = None,
        store_name: str | None = None,
        target_source_urls: list[str] | None = None,
    ) -> dict[str, Any]:
        try:
            result = self._perform_data_acquisition_claim(
                claim_mark=claim_mark,
                product_query=product_query,
                category_name=category_name,
                store_name=store_name,
                target_source_urls=target_source_urls,
            )
        except Exception as exc:
            state = self._error_state(
                stage='data_acquisition_claim_failed',
                label='认领失败',
                message=f'认领已有待认领商品到商品箱失败：{exc}',
                next_action='请确认目标商品已存在于店小秘待认领列表，真实浏览器筛选唯一后再重新认领。',
            )
            self._keep_visible_browser_for_recovery(state)
            self._write_state(state)
            return state

        state = {
            'ok': True,
            'stage': 'data_acquisition_claim',
            'label': '已提交认领',
            'message': result.get('message') or '已在真实店小秘已有待认领列表提交认领。',
            'next_action': '继续打开商品箱确认该商品已经出现。',
            'requires_user_action': False,
            'page_title': result.get('page_title'),
            'page_url': result.get('page_url'),
            'screenshot_url': result.get('screenshot_url'),
            'screenshot_error': result.get('screenshot_error'),
            'updated_at': now_iso(),
            'current_nav': 'data_acquisition',
            'claim_mark': claim_mark,
            'product_query': product_query,
            'category_name': category_name,
            'store_name': store_name,
            'search_result': result.get('search_result'),
            'target_source_urls': result.get('target_source_urls', []),
            'claimed_product': result.get('claimed_product'),
            'claim_target': result.get('claim_target'),
        }
        self._write_state(state)
        return state

    def verify_draft_box_claim(
        self,
        claim_mark: str,
        product_query: str | None = None,
        category_name: str | None = None,
        store_name: str | None = None,
        target_source_urls: list[str] | None = None,
    ) -> dict[str, Any]:
        previous_state = self.get_state()
        try:
            result = self._verify_draft_box_claim(
                claim_mark=claim_mark,
                product_query=product_query,
                category_name=category_name,
                store_name=store_name,
                target_source_urls=target_source_urls,
            )
        except Exception as exc:
            state = self._error_state(
                stage='draft_box_claim_verify_failed',
                label='商品箱确认失败',
                message=f'确认商品箱商品失败：{exc}',
                next_action='请打开商品箱检查认领商品是否出现，必要时回到已有待认领列表重新认领。',
            )
            self._keep_visible_browser_for_recovery(state)
            self._write_state(state)
            return state

        previous_claim_target = previous_state.get('claim_target') if isinstance(previous_state.get('claim_target'), dict) else None
        state = {
            'stage': 'draft_box_claim_verified',
            'label': '商品箱已确认',
            'message': '已确认真实商品进入商品箱。',
            'next_action': '可以进入编辑保存，选择模板后只保存。',
            'requires_user_action': False,
            'page_title': result.get('page_title'),
            'page_url': result.get('page_url'),
            'screenshot_url': result.get('screenshot_url'),
            'updated_at': now_iso(),
            'current_nav': 'draft_box',
            'claim_mark': claim_mark,
            'product_query': product_query,
            'category_name': category_name,
            'store_name': store_name,
            'target_source_urls': result.get('target_source_urls', []),
            'claimed_product': result.get('claimed_product'),
            'claim_target': result.get('claim_target') or previous_claim_target,
        }
        self._write_state(state)
        return state

    def perform_editor_action(
        self,
        action: str,
        defaults: dict[str, Any] | None = None,
        product_query: str | None = None,
        store_name: str | None = None,
        target_source_urls: list[str] | None = None,
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
                target_source_urls=target_source_urls,
            )
        except Exception as exc:
            state = self._error_state(
                stage=f'{action}_failed',
                label='动作失败',
                message=f'执行编辑页动作失败：{exc}',
                next_action='确认编辑页或半托管页仍可访问，且页面结构未变。',
            )
            self._keep_visible_browser_for_recovery(state)
            self._write_state(state)
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

    def _keep_visible_browser_for_recovery(self, state: dict[str, Any]) -> dict[str, Any]:
        state['browser_visible'] = not self._is_headless()
        next_action = str(state.get('next_action') or '').strip()
        if '真实浏览器窗口会保留' not in next_action:
            state['next_action'] = f'真实浏览器窗口会保留；{next_action}'
        page = self._page
        if page is not None:
            try:
                state['page_url'] = page.url
            except Exception:
                pass
        return state

    def _open_login_page_and_fill(self, username: str, password: str) -> dict[str, Any]:
        page = self._ensure_page()
        self._goto_with_live_hud(page, 'https://www.dianxiaomi.com/', wait_until='domcontentloaded', timeout=45000)
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
            'browser_visible': not self._is_headless(),
        }

    def _submit_login_after_captcha(self) -> dict[str, Any]:
        page = self._ensure_page()
        if not self._page_looks_logged_in(page):
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
        self._persist_visible_browser_cookies()
        return {
            'page_title': page.title(),
            'page_url': page.url,
            'screenshot_url': self._artifact_url(LOGIN_RESULT_SCREENSHOT_FILE),
            'visible_logged_in': self._page_looks_logged_in(page),
        }

    def _persist_visible_browser_cookies(self) -> None:
        if self._context is None:
            return
        cookies = self._context.cookies()
        self.live_client.cookie_file.write_text(json.dumps(cookies, ensure_ascii=False, indent=2), encoding='utf-8')

    def _page_looks_logged_in(self, page: Page) -> bool:
        return self._inspect_visible_login_state(page).get('logged_in') is True

    def _inspect_visible_login_state(self, page: Page) -> dict[str, Any]:
        url = str(getattr(page, 'url', '') or '').lower()
        body_text = ''
        if '/web/home' in url or 'index.htm' in url:
            try:
                body_text = page.locator('body').inner_text(timeout=2000)
            except Exception:
                body_text = ''
            normalized = ''.join(str(body_text or '').split())
            if not normalized:
                return {'logged_in': False, 'url': url, 'body_excerpt': '', 'reason': 'home_body_empty'}
            if '欢迎登录' in normalized:
                return {'logged_in': False, 'url': url, 'body_excerpt': str(body_text or '')[:240], 'reason': 'login_text_visible'}
            logged_in = any(term in normalized for term in ('首页', '产品', '订单', '仓库', '物流', '数据'))
            return {
                'logged_in': logged_in,
                'url': url,
                'body_excerpt': str(body_text or '')[:240],
                'reason': None if logged_in else 'home_markers_missing',
            }
        return {'logged_in': False, 'url': url, 'body_excerpt': str(body_text or '')[:240], 'reason': 'not_home_url'}

    def _submit_state_looks_logged_in(self, submit_state: dict[str, Any]) -> bool:
        if submit_state.get('visible_logged_in') is True:
            return True
        url = str(submit_state.get('page_url') or '').lower()
        title = str(submit_state.get('page_title') or '')
        return ('/web/home' in url or 'index.htm' in url) and '登录' not in title

    def _login_success_state_from_submit(self, submit_state: dict[str, Any]) -> dict[str, Any]:
        return {
            'stage': 'login_success',
            'label': '已登录',
            'message': '登录成功，已进入真实店小秘后台。',
            'next_action': '真实浏览器窗口会保留；可继续进入已有待认领列表、商品箱和编辑流程。',
            'requires_user_action': False,
            'page_title': submit_state.get('page_title') or '店小秘首页',
            'page_url': submit_state.get('page_url') or 'https://www.dianxiaomi.com/web/home',
            'screenshot_url': submit_state.get('screenshot_url'),
            'browser_visible': not self._is_headless(),
            'updated_at': now_iso(),
        }

    def _navigate_in_session(self, target: str) -> dict[str, Any]:
        config = WORKFLOW_TARGETS[target]
        self._trace_workflow_event('navigate:start', target=target, url=config['url'])
        page = self._ensure_page_with_cookies()
        self._trace_workflow_event('navigate:page_ready', target=target, current_url=page.url)
        visible_draft_box = target == 'draft_box' and os.name == 'nt' and not self._is_headless()
        if target == 'data_acquisition':
            self._goto_data_acquisition_sterile(page, config['url'], wait_until='domcontentloaded', timeout=45000)
        elif visible_draft_box:
            self._trace_workflow_event(
                'navigate:visible_draft_box_goto_start',
                target=target,
                url=config['url'],
                current_url=getattr(page, 'url', None),
                human_step='打开商品箱页面',
            )
            page.goto(config['url'], wait_until='domcontentloaded', timeout=45000)
            self._trace_workflow_event(
                'navigate:visible_draft_box_goto_done',
                target=target,
                current_url=getattr(page, 'url', None),
                human_step='商品箱页面已打开',
            )
        else:
            self._goto_with_live_hud(page, config['url'], wait_until='domcontentloaded', timeout=45000)
        self._trace_workflow_event('navigate:goto_done', target=target, current_url=page.url)
        if target == 'data_acquisition':
            wait_result = {
                'ready': True,
                'ready_term': 'data_acquisition_opened_after_3s_settle',
                'loading': None,
                'rows': None,
                'inputs': None,
                'url': getattr(page, 'url', ''),
                'title': '店小秘--数据采集',
                'text_excerpt': '已打开已有待认领列表，未执行认领或保存动作。',
            }
            self._trace_workflow_event(
                'navigate:wait_ready_skipped',
                target=target,
                current_url=getattr(page, 'url', None),
                reason='open_only_uses_sterile_3s_settle_without_dom_probe',
            )
            dismissed_blocking_modals = 0
            self._trace_workflow_event('navigate:dismiss_skipped', target=target, reason='open_data_acquisition_only')
        elif visible_draft_box:
            wait_result = self._settle_visible_draft_box(page)
            if not wait_result.get('ready'):
                excerpt = str(wait_result.get('text_excerpt') or '').replace('\n', ' ')[:180]
                raise RuntimeError(
                    f'{config["label"]} 静置后仍未加载完成；'
                    f'最后状态 loading={wait_result.get("loading")} text={excerpt}'
                )
            self._trace_workflow_event(
                'navigate:wait_ready_done',
                target=target,
                current_url=getattr(page, 'url', None),
                wait_result=wait_result,
                reason='visible_draft_box_sterile_settle',
            )
            dismissed_blocking_modals = 0
            self._trace_workflow_event('navigate:dismiss_skipped', target=target, reason='visible_draft_box_sterile_settle')
        else:
            wait_result = self._wait_for_page_ready(
                page,
                WORKFLOW_READY_TERMS.get(target, [config['label']]),
                label=config['label'],
                timeout=60000,
                dismiss_strategy='full',
            )
            self._trace_workflow_event('navigate:wait_ready_done', target=target, current_url=page.url, wait_result=wait_result)
            dismissed_blocking_modals = self._dismiss_blocking_modals(page)
        self._trace_workflow_event('navigate:dismiss_done', target=target, current_url=page.url, dismissed=dismissed_blocking_modals)
        screenshot_path = WORKFLOW_SCREENSHOT_MAP[target]
        screenshot_url = None
        if target == 'data_acquisition' or visible_draft_box:
            reason = 'data_acquisition_viewport_screenshot_can_block' if target == 'data_acquisition' else 'visible_draft_box_open_only_screenshot_skipped'
            self._trace_workflow_event('navigate:screenshot_skipped', target=target, reason=reason)
        else:
            self._trace_workflow_event('navigate:screenshot_start', target=target, path=str(screenshot_path))
            page.screenshot(path=str(screenshot_path), full_page=True, timeout=15000)
            self._trace_workflow_event('navigate:screenshot_done', target=target, path=str(screenshot_path), current_url=page.url)
            screenshot_url = self._artifact_url(screenshot_path)
        page_title = wait_result.get('title') if (target == 'data_acquisition' or visible_draft_box) else page.title()
        page_title = page_title or config['label']
        self._trace_workflow_event('navigate:return', target=target, current_url=page.url, page_title=page_title)
        return {
            'page_title': page_title,
            'page_url': page.url,
            'screenshot_url': screenshot_url,
            'target': target,
            'wait_result': wait_result,
            'dismissed_blocking_modals': dismissed_blocking_modals,
            'dismissed_blocking_modals_trace': list(self._last_dismiss_blocking_modals_trace),
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
        visible_draft_box = os.name == 'nt' and not self._is_headless()
        if visible_draft_box:
            self._trace_workflow_event(
                'draft_box_action:sterile_goto_start',
                url=draft_url,
                current_url=getattr(page, 'url', None),
                human_step='打开商品箱页面',
            )
            page.goto(draft_url, wait_until='domcontentloaded', timeout=45000)
            self._trace_workflow_event(
                'draft_box_action:sterile_goto_done',
                current_url=getattr(page, 'url', None),
                human_step='商品箱页面已打开',
            )
            wait_result = self._settle_visible_draft_box(page)
            if not wait_result.get('ready'):
                excerpt = str(wait_result.get('text_excerpt') or '').replace('\n', ' ')[:180]
                raise RuntimeError(
                    f'速卖通商品箱静置后仍未加载完成；'
                    f'最后状态 loading={wait_result.get("loading")} text={excerpt}'
                )
            self._trace_workflow_event(
                'draft_box_action:dismiss_skipped_visible',
                reason='visible_draft_box_uses_non_blocking_ready_wait',
                human_step='可见商品箱跳过弹窗脚本处理',
            )
        else:
            self._goto_with_live_hud(page, draft_url, wait_until='domcontentloaded', timeout=45000)
            self._wait_for_page_ready(
                page,
                WORKFLOW_READY_TERMS['draft_box'],
                label='速卖通商品箱',
                timeout=60000,
                dismiss_strategy='full',
            )
            self._dismiss_blocking_modals(page)
        claim_mark = note_text or self._current_claim_mark(product_query=product_query, store_name=store_name)
        row_info: dict[str, Any] | None = None
        try:
            row_info = self._find_draft_box_row(
                page,
                product_query,
                store_name=store_name,
                claim_mark=claim_mark,
                target_source_urls=target_source_urls,
            )
        except RuntimeError as initial_exc:
            self._trace_workflow_event(
                'draft_box_action:visible_find_missed',
                action=action,
                reason=str(initial_exc)[:240],
                human_step='当前商品箱列表未直接找到商品',
            )
        if row_info is None:
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
            screenshot_result = self._capture_optional_workflow_screenshot(
                editor_page,
                screenshot_path,
                trace_prefix='draft_box_edit',
            )
            editor_meta = self._extract_editor_page_meta(editor_page)
            return {
                'page_title': editor_page.title(),
                'page_url': editor_page.url,
                'screenshot_url': screenshot_result.get('screenshot_url'),
                'screenshot_error': screenshot_result.get('error'),
                'action': action,
                'note_text': note_text,
                'product_query': product_query,
                'store_name': store_name,
                'target_row_text': row_info.get('rowText'),
                'target_source_urls': row_info.get('sourceUrls', []),
                'message': '已从商品箱进入真实编辑界面。',
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
        screenshot_result = self._capture_optional_workflow_screenshot(
            page,
            screenshot_path,
            trace_prefix=f'draft_box_{action}',
        )
        return {
            'page_title': page.title(),
            'page_url': page.url,
            'screenshot_url': screenshot_result.get('screenshot_url'),
            'screenshot_error': screenshot_result.get('error'),
            'action': action,
            'note_text': note_text,
            'product_query': product_query,
            'store_name': store_name,
            'note_verified': note_result.get('verified'),
            'target_row_text': note_result.get('rowText') or row_info.get('rowText'),
            'target_source_urls': row_info.get('sourceUrls', []),
        }

    def _perform_data_acquisition_claim(
        self,
        claim_mark: str,
        product_query: str | None = None,
        category_name: str | None = None,
        store_name: str | None = None,
        target_source_urls: list[str] | None = None,
    ) -> dict[str, Any]:
        self._trace_workflow_event('data_acquisition_claim:open_start')
        data_acquisition_url = WORKFLOW_TARGETS['data_acquisition']['url']
        page = self._open_data_acquisition_page_for_claim(data_acquisition_url)
        try:
            wait_result = self._wait_for_data_acquisition_ready_for_claim(page)
        except Exception as exc:
            if not self._is_playwright_target_closed_error(exc):
                raise
            self._trace_workflow_event(
                'data_acquisition_claim:recover_closed_page',
                error=str(exc),
                current_url=getattr(page, 'url', None),
            )
            self._page = None
            page = self._open_data_acquisition_page_for_claim(data_acquisition_url, force_goto=True)
            wait_result = self._wait_for_data_acquisition_ready_for_claim(page)
        self._trace_workflow_event('data_acquisition_claim:page_ready_done')
        page.wait_for_timeout(300)
        self._trace_workflow_event('data_acquisition_claim:initial_settle_done', stopped_loading_with_escape=False)
        self._trace_workflow_event('data_acquisition_claim:dismiss_before_search_skipped', reason='activity_notice_can_block')
        self._trace_workflow_event('data_acquisition_claim:search_start')
        search_result = self._search_data_acquisition(
            page,
            product_query=product_query,
            category_name=category_name,
            store_name=store_name,
            target_source_urls=target_source_urls,
            source_input_rect=wait_result.get('first_input_rect') if isinstance(wait_result, dict) else None,
            start_collect_rect=wait_result.get('start_collect_rect') if isinstance(wait_result, dict) else None,
        )
        self._trace_workflow_event(
            'data_acquisition_claim:search_done',
            query_source=search_result.get('query_source') if isinstance(search_result, dict) else None,
            filled=search_result.get('filled') if isinstance(search_result, dict) else None,
            clicked_search=search_result.get('clicked_search') if isinstance(search_result, dict) else None,
            reason=search_result.get('reason') if isinstance(search_result, dict) else None,
        )
        if isinstance(search_result, dict) and search_result.get('reason'):
            raise RuntimeError(str(search_result['reason']))
        self._trace_workflow_event('data_acquisition_claim:target_find_start')
        target = self._find_data_acquisition_claim_target(
            page,
            product_query=product_query,
            category_name=category_name,
            store_name=store_name,
            target_source_urls=target_source_urls,
        )
        self._trace_workflow_event(
            'data_acquisition_claim:target_find_done',
            ok=target.get('ok'),
            matched_by=target.get('matchedBy'),
            reason=target.get('reason'),
        )
        if not target.get('ok'):
            raise RuntimeError(target.get('reason') or '未找到可认领的待认领商品')

        dismissed_modals = self._dismiss_data_acquisition_blocking_modals(page)
        self._trace_workflow_event(
            'data_acquisition_claim:dismiss_before_click_done',
            dismissed=dismissed_modals,
            human_step='清理认领前弹窗',
        )
        page.wait_for_timeout(300)
        self._trace_workflow_event('data_acquisition_claim:target_refind_after_dismiss_start')
        target = self._find_data_acquisition_claim_target(
            page,
            product_query=product_query,
            category_name=category_name,
            store_name=store_name,
            target_source_urls=target_source_urls,
        )
        self._trace_workflow_event(
            'data_acquisition_claim:target_refind_after_dismiss_done',
            ok=target.get('ok'),
            matched_by=target.get('matchedBy'),
            reason=target.get('reason'),
            action_rect=target.get('actionRect'),
            action_text=target.get('actionText'),
            row_text=str(target.get('rowText') or '')[:240],
            debug=target.get('debug'),
            human_step='重新确认认领按钮',
        )
        if not target.get('ok'):
            raise RuntimeError(target.get('reason') or '清理弹窗后未找到可认领的待认领商品')
        safety_result = self._assert_data_acquisition_claim_click_safe(page, target)
        self._trace_workflow_event(
            'data_acquisition_claim:click_claim_start',
            safety_ok=safety_result.get('ok') if isinstance(safety_result, dict) else None,
        )
        self._click_data_acquisition_claim_rect_center(page, target['actionRect'], purpose='认领按钮')
        self._trace_workflow_event('data_acquisition_claim:click_claim_done')
        time.sleep(1.5)
        self._trace_workflow_event('data_acquisition_claim:dialog_start')
        dialog_result = self._complete_data_acquisition_claim_dialog(
            page,
            category_name=category_name,
            store_name=store_name,
        )
        if not dialog_result.get('ok'):
            raise RuntimeError(dialog_result.get('reason') or '认领确认失败')
        self._trace_workflow_event('data_acquisition_claim:dialog_done')
        time.sleep(2.5)
        self._dismiss_data_acquisition_blocking_modals(page)
        self._trace_workflow_event('data_acquisition_claim:screenshot_start')
        screenshot_path = ACQUISITION_ACTION_SCREENSHOT_MAP['claim']
        screenshot_result = self._capture_optional_workflow_screenshot(
            page,
            screenshot_path,
            trace_prefix='data_acquisition_claim',
        )
        claimed_product = {
            'title': target.get('title') or product_query or category_name or '店小秘待认领商品',
            'category_name': target.get('categoryName') or category_name,
            'source_url': (target.get('sourceUrls') or [None])[0],
            'row_text': target.get('rowText'),
        }
        self._trace_workflow_event('data_acquisition_claim:done')
        page_url = str(getattr(page, 'url', '') or WORKFLOW_TARGETS['data_acquisition']['url'])
        if os.name == 'nt' and not self._is_headless() and self._is_data_acquisition_page_url(page):
            page_title = '店小秘--数据采集'
        else:
            page_title = page.title()
        return {
            'page_title': page_title,
            'page_url': page_url,
            'screenshot_url': screenshot_result.get('screenshot_url'),
            'screenshot_error': screenshot_result.get('error'),
            'message': '已在已有待认领列表提交认领到商品箱。',
            'claim_mark': claim_mark,
            'product_query': product_query,
            'category_name': category_name,
            'store_name': store_name,
            'search_result': search_result,
            'target_source_urls': target.get('sourceUrls', []) or target_source_urls or [],
            'claimed_product': claimed_product,
            'claim_target': target,
            'claim_dialog': dialog_result,
            'claim_click_safety': safety_result,
            'published': False,
        }

    def _open_data_acquisition_page_for_claim(self, data_acquisition_url: str, *, force_goto: bool = False) -> Page:
        page = self._ensure_data_acquisition_page_with_cookies()
        if not force_goto and self._is_current_page_url(page, data_acquisition_url):
            self._trace_workflow_event(
                'data_acquisition_claim:reuse_current_page',
                current_url=getattr(page, 'url', None),
                target_url=data_acquisition_url,
            )
            self._attach_and_reapply_live_hud_page(page)
            return page
        self._goto_data_acquisition_sterile(page, data_acquisition_url, wait_until='domcontentloaded', timeout=45000)
        return page

    def _ensure_data_acquisition_page_with_cookies(self) -> Page:
        if os.name == 'nt' and not self._is_headless() and self._page is not None:
            try:
                is_reusable_visible_data_acquisition_page = (
                    not self._is_playwright_object_closed(self._page)
                    and self._is_data_acquisition_page_url(self._page)
                )
            except Exception:
                is_reusable_visible_data_acquisition_page = False
            if is_reusable_visible_data_acquisition_page:
                self._trace_workflow_event(
                    'ensure_page:reuse_visible_data_acquisition_page',
                    current_url=getattr(self._page, 'url', None),
                    reason='preserve_loaded_visible_data_acquisition_page',
                    human_step='复用已打开的已有待认领列表',
                )
                return self._page
        return self._ensure_page_with_cookies()

    def _install_data_acquisition_notice_auto_dismiss(self, page: Page | None) -> bool:
        if page is None or self._is_headless():
            return False
        try:
            context = page.context
        except Exception:
            return False
        context_id = id(context)
        if context_id in self._data_acquisition_notice_bound_context_ids:
            return True
        try:
            context.add_init_script(DATA_ACQUISITION_NOTICE_AUTO_DISMISS_SCRIPT)
            self._data_acquisition_notice_bound_context_ids.add(context_id)
            self._trace_workflow_event(
                'data_acquisition_notice_auto_dismiss:installed',
                human_step='准备关闭店小秘通知弹窗',
            )
            return True
        except Exception as exc:
            self._trace_workflow_event(
                'data_acquisition_notice_auto_dismiss:install_failed',
                error=str(exc)[:240],
                human_step='准备关闭店小秘通知弹窗',
            )
            return False

    def _wait_for_data_acquisition_ready_for_claim(self, page: Page) -> dict[str, Any]:
        if os.name == 'nt' and not self._is_headless() and self._is_data_acquisition_page_url(page):
            return self._wait_for_visible_data_acquisition_claim_settle(page)
        return self._wait_for_page_ready(
            page,
            WORKFLOW_READY_TERMS['data_acquisition'],
            label='已有待认领列表',
            timeout=60000,
            dismiss_strategy='data_acquisition_no_dismiss',
        )

    def _wait_for_visible_data_acquisition_claim_settle(self, page: Page) -> dict[str, Any]:
        terms = WORKFLOW_READY_TERMS['data_acquisition']
        timeout = 60000
        deadline = time.monotonic() + timeout / 1000
        last: dict[str, Any] = {}
        last_trace_at = 0.0
        self._trace_workflow_event(
            'wait_ready:start',
            label='已有待认领列表',
            terms=terms,
            timeout=timeout,
            current_url=getattr(page, 'url', None),
            dismiss_strategy='visible_sterile_settle',
            human_step='等待已有待认领列表自行加载',
        )
        self._trace_workflow_event(
            'wait_ready:settle',
            label='已有待认领列表',
            seconds=3.0,
            reason='visible_data_acquisition_claim_uses_sterile_settle_without_dom_probe',
            human_step='等待页面稳定',
        )
        time.sleep(3.0)
        while time.monotonic() < deadline:
            result = self._inspect_data_acquisition_ready_state_with_locators(page, terms)
            result['strategy'] = 'visible_locator_condition_wait'
            if not result.get('ready') and int(result.get('claim_count') or 0) > 0:
                result['ready'] = True
                result['ready_term'] = 'existing_claim_action_ready'
                result['ignored_loading'] = bool(result.get('loading'))
            last = result
            if result.get('ready'):
                self._trace_workflow_event('wait_ready:ready', label='已有待认领列表', result=result)
                return result
            now = time.monotonic()
            if now - last_trace_at >= 5:
                last_trace_at = now
                self._trace_workflow_event('wait_ready:poll', label='已有待认领列表', result=result)
            time.sleep(1.0)
        reason_parts: list[str] = []
        if last.get('loading'):
            reason_parts.append('页面仍在加载')
        if not last.get('claim_count'):
            reason_parts.append('未看到已有待认领商品的认领按钮')
        if last.get('has_collect_form') and not last.get('claim_count'):
            reason_parts.append('当前停留在店小秘新建来源商品输入区，系统不会填写链接或创建新来源商品')
        reason = '，'.join(reason_parts) or '页面未达到可操作状态'
        diagnostic = self._data_acquisition_claim_timeout_diagnostic(last)
        self._trace_workflow_event(
            'wait_ready:timeout',
            label='已有待认领列表',
            result=last,
            reason=reason,
            diagnostic=diagnostic,
            human_step='已有待认领列表还不能操作',
        )
        diagnostic_text = f'{diagnostic}。' if diagnostic else ''
        raise RuntimeError(
            f'已有待认领列表 {timeout // 1000} 秒内仍不可认领：{reason}。'
            f'{diagnostic_text}'
            '系统不会填写链接、不会点击开始采集、不会创建新来源商品；'
            '请确认待认领列表里已经显示目标商品后重试。'
        )

    def _data_acquisition_claim_timeout_diagnostic(self, state: dict[str, Any]) -> str:
        details: list[str] = []
        current_url = str(state.get('url') or '').strip()
        if current_url:
            details.append(f'当前地址 {current_url[:180]}')
        loading_items = state.get('loading_items')
        if isinstance(loading_items, list) and loading_items:
            markers: list[str] = []
            for item in loading_items[:3]:
                if not isinstance(item, dict):
                    continue
                selector = str(item.get('selector') or '').strip()
                text = str(item.get('text') or '').replace('\n', ' ').strip()
                marker = selector or 'loading'
                if text:
                    marker = f'{marker}={text[:60]}'
                markers.append(marker)
            if markers:
                details.append('加载标记 ' + ' / '.join(markers))
        elif str(state.get('loading_text') or '').strip():
            details.append('加载提示 ' + str(state.get('loading_text') or '').strip()[:120])
        probe_error = str(state.get('probe_error') or '').strip()
        if probe_error:
            details.append('页面检查异常 ' + probe_error[:160])
        if int(state.get('claim_count') or 0) <= 0:
            details.append('未检测到认领按钮')
        return '；'.join(details)

    def _is_playwright_target_closed_error(self, exc: Exception) -> bool:
        text = str(exc).casefold()
        return (
            'target page, context or browser has been closed' in text
            or 'browser has been closed' in text
            or 'target closed' in text
        )

    def _assert_data_acquisition_claim_click_safe(self, page: Page, target: dict[str, Any]) -> dict[str, Any]:
        target_row_text = str(target.get('rowText') or '')
        target_action_text = str(target.get('actionText') or '')
        action_rect = target.get('actionRect') if isinstance(target.get('actionRect'), dict) else {}
        target_context = f'{target_row_text} {target_action_text}'
        if self._contains_data_acquisition_claim_forbidden_term(target_context):
            raise RuntimeError('待认领商品安全检查未通过：目标商品行包含保存、发布或待发布动作，系统已停止；不会保存或发布。')
        if not any(term in target_action_text for term in DATA_ACQUISITION_CLAIM_ACTION_TERMS):
            raise RuntimeError('待认领商品安全检查未通过：当前点击目标不是认领按钮，系统已停止；不会保存或发布。')
        if not self._rect_has_clickable_area(action_rect):
            raise RuntimeError('待认领商品安全检查未通过：没有拿到可点击的认领按钮位置，系统已停止；不会保存或发布。')
        if target.get('matchedBy') == 'source_url_search_first_result':
            raise RuntimeError('待认领商品安全检查未通过：不再允许使用固定坐标认领，必须识别到真实商品行和认领按钮。')

        live_context = page.evaluate(r'''({actionRect}) => {
          const visible = (el) => {
            if (!el) return false;
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const textOf = (el) => (el ? (el.innerText || el.textContent || '') : '').replace(/\s+/g, ' ').trim();
          const norm = (s) => String(s || '').replace(/\s+/g, '').trim();
          const forbidden = ['保存','发布','立即发布','继续发布','保存并发布','保存并移入待发布','移入待发布','批量发布'];
          const claimTerms = ['认领', '领取'];
          const url = String(window.location.href || '');
          const isDxmPage = /dianxiaomi\.com/i.test(url);
          const isDataAcquisitionUrl = /dataAcquisition|productCrawl/i.test(url);
          if (isDxmPage && !isDataAcquisitionUrl) {
            return {
              ok: false,
              reason: '当前页面不是店小秘已有待认领列表页',
              page_url: url,
            };
          }
          const rect = actionRect || {};
          const x = Number(rect.x || 0) + Number(rect.w || 0) / 2;
          const y = Number(rect.y || 0) + Number(rect.h || 0) / 2;
          const hit = document.elementFromPoint(x, y);
          if (!visible(hit)) {
            return {ok:false, reason:'当前认领按钮位置不可见', page_url:url};
          }
          const action = hit.closest('button,a,[role="button"]') || hit;
          const row = hit.closest('tr.vxe-body--row, tr.ant-table-row, tr.el-table__row, tr, .ant-table-row, .el-table__row, .vxe-body--row, [class*="table-row"], [class*="list-item"]');
          const actionText = textOf(action);
          const rowText = textOf(row || action);
          const actionContext = norm(`${actionText} ${action.getAttribute?.('title') || ''} ${action.getAttribute?.('aria-label') || ''} ${action.className || ''}`);
          const rowContext = norm(rowText);
          if (forbidden.some(term => actionContext.includes(norm(term)) || rowContext.includes(norm(term)))) {
            return {
              ok: false,
              reason: '点击区域包含保存、发布或待发布动作',
              action_text: actionText.slice(0, 120),
              row_text: rowText.slice(0, 260),
              page_url: url,
            };
          }
          if (!claimTerms.some(term => actionContext.includes(norm(term)))) {
            return {
              ok: false,
              reason: '当前点击目标不是认领按钮',
              action_text: actionText.slice(0, 120),
              row_text: rowText.slice(0, 260),
              page_url: url,
            };
          }
          return {
            ok: true,
            action_text: actionText.slice(0, 120),
            row_text: rowText.slice(0, 260),
            page_url: url,
          };
        }''', {'actionRect': action_rect})
        if not isinstance(live_context, dict) or not live_context.get('ok'):
            reason = (live_context or {}).get('reason') if isinstance(live_context, dict) else None
            self._trace_workflow_event(
                'data_acquisition_claim:click_safety_failed',
                reason=reason,
                action_rect=action_rect,
                action_text=(live_context or {}).get('action_text') if isinstance(live_context, dict) else None,
                row_text=(live_context or {}).get('row_text') if isinstance(live_context, dict) else None,
                page_url=(live_context or {}).get('page_url') if isinstance(live_context, dict) else None,
                human_step='认领按钮安全检查失败',
            )
            raise RuntimeError(f'待认领商品安全检查未通过：{reason or "当前页面不适合执行认领"}，系统已停止；不会保存或发布。')
        return live_context

    def _contains_data_acquisition_claim_forbidden_term(self, text: str) -> bool:
        normalized = ''.join(str(text or '').split())
        return any(''.join(term.split()) in normalized for term in DATA_ACQUISITION_CLAIM_FORBIDDEN_TERMS)

    def _rect_has_clickable_area(self, rect: dict[str, Any]) -> bool:
        try:
            return float(rect.get('w') or 0) > 0 and float(rect.get('h') or 0) > 0
        except (TypeError, ValueError):
            return False

    def _search_data_acquisition(
        self,
        page: Page,
        product_query: str | None = None,
        category_name: str | None = None,
        store_name: str | None = None,
        target_source_urls: list[str] | None = None,
        source_input_rect: dict[str, Any] | None = None,
        start_collect_rect: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        source_query = next((str(value).strip() for value in (target_source_urls or []) if str(value or '').strip()), '')
        if source_query and str(product_query or '').strip():
            try:
                product_query_matches_source = self._source_urls_match([str(product_query).strip()], target_source_urls or [])
            except Exception:
                product_query_matches_source = str(product_query).strip() in {str(value).strip() for value in (target_source_urls or [])}
            if product_query_matches_source:
                product_query = None
        if source_query:
            self._trace_workflow_event(
                'data_acquisition_search:source_url_match_only',
                target_source_url_count=len([value for value in (target_source_urls or []) if str(value or '').strip()]),
                human_step='来源链接仅用于匹配已有待认领商品',
            )
        if str(product_query or '').strip():
            query = str(product_query or '').strip()
            query_source = 'product_query'
        elif str(category_name or '').strip():
            query = str(category_name or '').strip()
            query_source = 'category_name'
        else:
            query = ''
            query_source = 'none'
        if not query and not store_name:
            return {
                'query': '',
                'query_source': query_source,
                'target_source_urls': list(target_source_urls or []),
                'source_match_only': bool(source_query),
                'filled': False,
                'clicked_search': False,
            }
        result = page.evaluate(r'''({query, store, querySource}) => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const norm = (s) => String(s || '').replace(/\s+/g, '').trim();
          const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
          if (store) {
            const storeTarget = Array.from(document.querySelectorAll('button,a,span,div,li'))
              .filter(visible)
              .find(el => norm(textOf(el)) === norm(store) || norm(textOf(el)).includes(norm(store)));
            if (storeTarget) storeTarget.dispatchEvent(new MouseEvent('click', {bubbles:true}));
          }
          let filled = false;
          if (query) {
            const inputs = Array.from(document.querySelectorAll('input, textarea')).filter(el => {
              if (!visible(el) || el.disabled || el.readOnly) return false;
              const r = el.getBoundingClientRect();
              return r.width > 140 && r.height > 18;
            });
            const isUrlInput = (el) => {
              const label = norm([el.placeholder, el.getAttribute('aria-label'), el.getAttribute('name'), el.id, el.className].join(' '));
              return label.includes('来源链接') || label.includes('商品链接') || label.includes('链接') || label.includes('网址') || label.includes('来源') || label.includes('url') || label.includes('source');
            };
            const urlInput = inputs.find(isUrlInput);
            const nonUrlInputs = inputs.filter(el => !isUrlInput(el));
            const genericInput = nonUrlInputs.find(el => {
              const label = norm([el.placeholder, el.getAttribute('aria-label'), el.getAttribute('name')].join(' '));
              return label.includes('搜索') || label.includes('标题') || label.includes('产品') || label.includes('关键词') || label.includes('内容');
            }) || nonUrlInputs[0];
            const input = genericInput;
            if (input) {
              input.value = query;
              input.dispatchEvent(new Event('input', {bubbles:true}));
              input.dispatchEvent(new Event('change', {bubbles:true}));
              filled = true;
            }
          }
          const search = Array.from(document.querySelectorAll('button,a,span,div'))
            .filter(visible)
            .find(el => ['搜索','查询','筛选'].includes(norm(textOf(el))));
          if (search) search.dispatchEvent(new MouseEvent('click', {bubbles:true}));
          return {filled, clicked_search: Boolean(search)};
        }''', {'query': query, 'store': store_name, 'querySource': query_source})
        result = {
            **(result or {}),
            'query': query,
            'query_source': query_source,
            'target_source_urls': list(target_source_urls or []),
            'source_match_only': bool(source_query),
        }
        if result.get('filled') or result.get('clicked_search') or store_name:
            page.wait_for_timeout(8000)
            page.keyboard.press('Escape')
            page.wait_for_timeout(500)
            self._trace_workflow_event(
                'data_acquisition_search:result_ready_wait_skipped',
                reason='data_acquisition_dom_probe_can_block_after_search',
                stopped_loading_with_escape=True,
            )
        return result

    def _search_data_acquisition_source_url_input(
        self,
        page: Page,
        query: str,
        target_source_urls: list[str],
        product_query: str | None = None,
        source_input_rect: dict[str, Any] | None = None,
        start_collect_rect: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._trace_workflow_event(
            'data_acquisition_search:source_url_match_only',
            target_source_url_count=len([value for value in (target_source_urls or []) if str(value or '').strip()]),
            human_step='来源链接仅用于匹配已有待认领商品',
        )
        return {
            'query': query,
            'query_source': 'target_source_url',
            'target_source_urls': list(target_source_urls or []),
            'filled': False,
            'clicked_search': False,
            'source_match_only': True,
            'reason': '来源链接只用于匹配已有待认领商品，不写入店小秘输入框，不创建新来源商品。',
        }

    def _data_acquisition_source_input_value_snapshot(self, page: Page, expected_query: str) -> dict[str, Any]:
        selectors = (
            'textarea[placeholder*="产品的网址"]',
            'textarea[placeholder*="网址"]',
            'textarea[placeholder*="商品链接"]',
            'textarea[placeholder*="来源链接"]',
            'textarea[placeholder*="链接"]',
            'textarea[placeholder*="URL"]',
            'textarea[placeholder*="url"]',
            'textarea.ant-input',
            'textarea',
            'input[placeholder*="产品的网址"]',
            'input[placeholder*="网址"]',
            'input[placeholder*="商品链接"]',
            'input[placeholder*="来源链接"]',
            'input[placeholder*="链接"]',
            'input[placeholder*="URL"]',
            'input[placeholder*="url"]',
            '[contenteditable="true"]',
            '[role="textbox"]',
            'input',
        )
        expected_tokens = self._data_acquisition_source_url_tokens([expected_query])
        first_text_field: dict[str, Any] | None = None
        for selector in selectors:
            try:
                candidates = page.locator(selector)
                count = min(self._locator_count(candidates), 5)
                for index in range(count):
                    candidate = candidates.nth(index)
                    info = candidate.evaluate(
                        """(el) => {
                          const tag = String(el.tagName || '').toLowerCase();
                          const type = String(el.getAttribute('type') || '').toLowerCase();
                          const editable = el.isContentEditable || el.getAttribute('contenteditable') === 'true';
                          const textLikeInput = tag === 'input' && !['checkbox','radio','hidden','button','submit','reset','file'].includes(type);
                          const usable = tag === 'textarea' || textLikeInput || editable || el.getAttribute('role') === 'textbox';
                          return {
                            usable,
                            tag,
                            type,
                            value: String(el.value || el.textContent || '').trim(),
                          };
                        }""",
                        timeout=700,
                    )
                    if not isinstance(info, dict) or not info.get('usable'):
                        continue
                    text = str(info.get('value') or '').strip()
                    contains_expected = expected_query in text or any(token and token in text for token in expected_tokens)
                    snapshot = {
                        'found': True,
                        'selector': selector,
                        'index': index,
                        'tag': info.get('tag'),
                        'type': info.get('type'),
                        'value_excerpt': text[:260],
                        'contains_expected': contains_expected,
                    }
                    if contains_expected:
                        return snapshot
                    if first_text_field is None:
                        first_text_field = snapshot
            except Exception as exc:  # noqa: BLE001 - DXM widgets can detach while we inspect.
                last_error = str(exc)[:160]
                continue
        if first_text_field is not None:
            return first_text_field
        return {
            'found': False,
            'contains_expected': False,
            'reason': locals().get('last_error', '未找到可读取值的来源链接输入框'),
        }

    def _fill_data_acquisition_source_url_input_rect(
        self,
        page: Page,
        query: str,
        source_input_rect: dict[str, Any] | None,
    ) -> dict[str, Any]:
        self._trace_workflow_event(
            'data_acquisition_search:source_input_blocked',
            reason='source_url_match_only_scope',
        )
        return {'ok': False, 'reason': '来源链接只用于匹配已有待认领商品，不写入店小秘输入框，不创建新来源商品。'}

    def _fill_data_acquisition_source_url_primary_input(self, page: Page, query: str) -> dict[str, Any]:
        self._trace_workflow_event(
            'data_acquisition_search:source_input_blocked',
            reason='source_url_match_only_scope',
        )
        return {'ok': False, 'reason': '来源链接只用于匹配已有待认领商品，不写入店小秘输入框，不创建新来源商品。'}

    def _deprecated_fill_data_acquisition_source_url_primary_input(self, page: Page, query: str) -> dict[str, Any]:
        selectors = [
            'textarea[placeholder*="产品的网址"]',
            'textarea[placeholder*="网址"]',
            'textarea[placeholder*="商品链接"]',
            'textarea[placeholder*="来源链接"]',
            'textarea[placeholder*="链接"]',
            'textarea[placeholder*="URL"]',
            'textarea[placeholder*="url"]',
            'textarea.ant-input',
            'input[placeholder*="产品的网址"]',
            'input[placeholder*="网址"]',
            'input[placeholder*="商品链接"]',
            'input[placeholder*="来源链接"]',
            'input[placeholder*="链接"]',
            'input[placeholder*="URL"]',
            'input[placeholder*="url"]',
        ]
        errors: list[str] = []
        for selector in selectors:
            try:
                candidates = page.locator(selector)
                if self._locator_count(candidates) < 1:
                    continue
                field = candidates.first
                field.fill(query, timeout=1200)
                return {'ok': True, 'selector': selector, 'method': 'primary_locator_fill'}
            except Exception as exc:  # noqa: BLE001 - Playwright raises locator-specific timeout errors.
                errors.append(f'{selector}: {str(exc)[:120]}')
        return {
            'ok': False,
            'reason': '; '.join(errors[-3:]) or '未找到店小秘采集页网址输入框',
        }

    def _fill_data_acquisition_source_url_input(self, page: Page, query: str) -> dict[str, Any]:
        self._trace_workflow_event(
            'data_acquisition_search:source_input_blocked',
            reason='source_url_match_only_scope',
        )
        return {'ok': False, 'reason': '来源链接只用于匹配已有待认领商品，不写入店小秘输入框，不创建新来源商品。'}

    def _deprecated_fill_data_acquisition_source_url_input(self, page: Page, query: str) -> dict[str, Any]:
        query_json = json.dumps(query, ensure_ascii=False)
        expression = r'''(() => {
              const query = __DXM_SOURCE_QUERY__;
              const visible = (el) => {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
              };
              const norm = (s) => String(s || '').replace(/\s+/g, '').trim().toLowerCase();
              const textOf = (el) => (el ? (el.innerText || el.textContent || '') : '').replace(/\s+/g, ' ').trim();
              const setValue = (el, value) => {
                const tag = String(el.tagName || '').toLowerCase();
                if (el.isContentEditable) {
                  el.focus();
                  el.textContent = value;
                } else {
                  const proto = tag === 'textarea' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
                  const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
                  el.focus();
                  if (setter) setter.call(el, value);
                  else el.value = value;
                }
                el.dispatchEvent(new Event('input', {bubbles:true}));
                el.dispatchEvent(new Event('change', {bubbles:true}));
              };
              const fields = Array.from(document.querySelectorAll('textarea,input,[contenteditable="true"]'))
                .filter(el => {
                  if (!visible(el) || el.disabled || el.readOnly) return false;
                  const r = el.getBoundingClientRect();
                  return r.width >= 120 && r.height >= 18;
                })
                .map((el, index) => {
                  const r = el.getBoundingClientRect();
                  const tag = String(el.tagName || '').toLowerCase();
                  const meta = norm([
                    el.placeholder,
                    el.getAttribute('aria-label'),
                    el.getAttribute('name'),
                    el.id,
                    el.className,
                    textOf(el.closest('label')),
                    textOf(el.parentElement),
                  ].join(' '));
                  let score = 0;
                  if (meta.includes('网址') || meta.includes('链接') || meta.includes('url') || meta.includes('source')) score += 100;
                  if (meta.includes('产品') || meta.includes('商品')) score += 35;
                  if (tag === 'textarea') score += 35;
                  if (r.width >= 300) score += 15;
                  if (r.height >= 60) score += 25;
                  if (String(el.type || '').toLowerCase() === 'hidden') score -= 200;
                  return {el, index, score, tag, meta, rect:{x:r.x, y:r.y, w:r.width, h:r.height}};
                })
                .filter(item => item.score > 0)
                .sort((a, b) => b.score - a.score || a.rect.y - b.rect.y);
              const target = fields[0];
              if (!target) {
                return {ok:false, reason:'页面中没有找到可见的网址或链接输入区'};
              }
              target.el.scrollIntoView({block:'center', inline:'nearest'});
              setValue(target.el, query);
              return {
                ok: true,
                selector: `${target.tag}:nth(${target.index})`,
                tag: target.tag,
                score: target.score,
                rect: target.rect,
                meta: target.meta.slice(0, 160),
              };
            })()'''.replace('__DXM_SOURCE_QUERY__', query_json)
        try:
            cdp = page.context.new_cdp_session(page)
            response = cdp.send(
                'Runtime.evaluate',
                {
                    'expression': expression,
                    'returnByValue': True,
                    'timeout': 2000,
                },
            )
            if isinstance(response, dict) and response.get('exceptionDetails'):
                text = str(response.get('exceptionDetails'))[:240]
                return {'ok': False, 'reason': f'页面输入区脚本执行失败：{text}'}
            value = ((response or {}).get('result') or {}).get('value')
            if isinstance(value, dict):
                return value
            return {'ok': False, 'reason': '页面输入区没有返回可用结果'}
        except Exception as exc:  # noqa: BLE001 - Playwright may fail while DXM is navigating.
            return {'ok': False, 'reason': str(exc)[:240]}

    def _click_data_acquisition_start_collect(
        self,
        page: Page,
        *,
        start_collect_rect: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._trace_workflow_event(
            'data_acquisition_search:start_collect_blocked',
            reason='existing_data_claim_scope',
        )
        return {'ok': False, 'reason': '当前系统只处理店小秘已有待认领商品，不创建新来源商品。'}

    def _wait_data_acquisition_collect_result(
        self,
        page: Page,
        *,
        timeout: int = 90000,
        product_query: str | None = None,
        target_source_urls: list[str] | None = None,
    ) -> dict[str, Any]:
        visible_data_acquisition = self._is_data_acquisition_page_url(page) and not self._is_headless()
        target_required = visible_data_acquisition and bool(
            str(product_query or '').strip() or any(str(value or '').strip() for value in (target_source_urls or []))
        )
        if visible_data_acquisition:
            settle_seconds = min(max(timeout / 1000, 3), 3)
            self._trace_workflow_event(
                'data_acquisition_search:collect_result_initial_settle',
                seconds=settle_seconds,
                reason='wait_before_checking_visible_dxm_result_list',
            )
            time.sleep(settle_seconds)
        deadline = time.monotonic() + timeout / 1000
        last_state: dict[str, Any] = {}
        while time.monotonic() < deadline:
            loading_state = self._data_acquisition_visible_loading_state(page)
            loading = bool(loading_state.get('loading'))
            claim_count = self._count_exact_data_acquisition_claim_actions(page)
            target_state = (
                self._data_acquisition_collect_target_state(
                    page,
                    product_query=product_query,
                    target_source_urls=target_source_urls,
                )
                if target_required and claim_count > 0
                else {'ready': not target_required}
            )
            target_ready = bool(target_state.get('ready'))
            last_state = {
                'loading': loading,
                'loading_count': loading_state.get('loading_count', 0),
                'loading_text': loading_state.get('loading_text', ''),
                'claim_count': claim_count,
                'target_ready': target_ready,
                'target_state': target_state,
                'strategy': 'visible_locator_collect_result',
            }
            if claim_count > 0 and target_ready:
                self._trace_workflow_event(
                    'data_acquisition_search:collect_result_ready',
                    loading=loading,
                    claim_count=claim_count,
                    target_ready=target_ready,
                    target_matched_by=target_state.get('matched_by'),
                    ignored_loading=bool(loading),
                )
                return {'ok': True, **last_state}
            if claim_count > 0 and target_required:
                self._trace_workflow_event(
                    'data_acquisition_search:collect_result_target_pending',
                    loading=loading,
                    claim_count=claim_count,
                    target_state=target_state,
                )
            if visible_data_acquisition:
                time.sleep(1.0)
            else:
                page.wait_for_timeout(1000)
        if target_required:
            raise RuntimeError(
                '店小秘已有待认领列表没有出现目标商品，系统不会从旧列表或不确定列表认领；'
                f'最后状态 claim_count={last_state.get("claim_count")} target={last_state.get("target_state")}'
            )
        raise RuntimeError('店小秘已有待认领列表一直在加载，系统没有看到可认领商品；请确认目标商品已存在于店小秘待认领列表后再重试。')

    def _data_acquisition_collect_target_state(
        self,
        page: Page,
        *,
        product_query: str | None = None,
        target_source_urls: list[str] | None = None,
    ) -> dict[str, Any]:
        try:
            target = self._find_data_acquisition_claim_target(
                page,
                product_query=product_query,
                target_source_urls=target_source_urls,
            )
        except Exception as exc:  # noqa: BLE001 - DXM may still be refreshing the result table.
            return {'ready': False, 'reason': str(exc)[:240]}
        if not isinstance(target, dict):
            return {'ready': False, 'reason': '目标商品检查没有返回结果'}
        return {
            'ready': bool(target.get('ok')),
            'matched_by': target.get('matchedBy'),
            'reason': target.get('reason'),
            'debug': target.get('debug'),
            'row_text': str(target.get('rowText') or '')[:240],
        }

    def _inspect_data_acquisition_collect_result_state(self, page: Page) -> dict[str, Any]:
        script = r'''() => {
          const visible = (el) => {
            if (!el) return false;
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const textOf = (el) => String(el && (el.innerText || el.textContent) || '').replace(/\s+/g, ' ').trim();
          const norm = (s) => String(s || '').replace(/\s+/g, '').trim();
          const loadingNodes = Array.from(document.querySelectorAll(
            '.ant-spin-spinning, .vxe-loading, .vxe-loading--wrapper, .el-loading-mask, .ant-spin, .loading, [class*="loading"], [class*="Loading"]'
          )).filter(visible).slice(0, 10);
          const actions = Array.from(document.querySelectorAll('button,a,[role="button"],span'))
            .filter(visible)
            .map(el => norm(textOf(el)))
            .filter(text => ['认领','领取','认领到采集箱','领取到采集箱'].includes(text));
          return {
            loading: loadingNodes.length > 0,
            loading_count: loadingNodes.length,
            loading_text: loadingNodes.map(textOf).filter(Boolean).join(' ').slice(0, 200),
            claim_count: actions.length,
            url: location.href,
            title: document.title,
          };
        }'''
        try:
            result = self._evaluate_zero_arg_page_function_with_runtime_timeout(page, script, timeout=2000)
        except Exception as exc:
            self._trace_workflow_event('data_acquisition_search:collect_result_probe_failed', error=str(exc)[:240])
            return {'loading': True, 'loading_count': 1, 'loading_text': '页面检查无响应', 'claim_count': 0, 'probe_error': str(exc)[:240]}
        if isinstance(result, dict):
            return result
        return {'loading': True, 'loading_count': 1, 'loading_text': '页面检查未返回结果', 'claim_count': 0, 'probe_error': 'non_object'}

    def _count_exact_data_acquisition_claim_actions(self, page: Page) -> int:
        count = 0
        for selector in ('button', 'a', '[role="button"]', 'span'):
            try:
                candidates = page.locator(selector).filter(has_text='认领')
            except Exception:
                continue
            for index in range(min(self._locator_count(candidates), 20)):
                text = self._locator_text(candidates.nth(index), timeout=500)
                compact = ''.join(str(text or '').split())
                if compact in {'认领', '领取', '认领到采集箱', '领取到采集箱'}:
                    count += 1
        return count

    def _locator_visible_any(self, page: Page, selectors: tuple[str, ...]) -> bool:
        for selector in selectors:
            try:
                locator = page.locator(selector).first
                if locator.is_visible(timeout=350):
                    return True
            except Exception:
                continue
        return False

    def _data_acquisition_visible_loading_state(self, page: Page) -> dict[str, Any]:
        selectors = (
            '.vxe-loading',
            '.vxe-loading--wrapper',
            '.el-loading-mask',
            '.ant-spin-spinning',
            '.ant-spin',
            '.loading',
            '[class*="loading"]',
            '[class*="Loading"]',
        )
        visible_items: list[dict[str, Any]] = []
        for selector in selectors:
            try:
                nodes = page.locator(selector)
            except Exception:
                continue
            for index in range(min(self._locator_count(nodes), 8)):
                node = nodes.nth(index)
                rect = self._locator_bounding_box(node, timeout=250)
                if not rect:
                    continue
                text = self._locator_text(node, timeout=250)
                visible_items.append({
                    'selector': selector,
                    'text': text[:80],
                    'rect': rect,
                })
                break
        return {
            'loading': bool(visible_items),
            'loading_count': len(visible_items),
            'loading_text': ' '.join(item.get('text') or item.get('selector') or '' for item in visible_items)[:200],
            'loading_items': visible_items[:5],
        }

    def _find_data_acquisition_claim_target(
        self,
        page: Page,
        product_query: str | None = None,
        category_name: str | None = None,
        store_name: str | None = None,
        target_source_urls: list[str] | None = None,
    ) -> dict[str, Any]:
        if str(product_query or '').strip():
            product_target = self._find_data_acquisition_claim_target_by_product_query_script(
                page,
                str(product_query or '').strip(),
                target_source_urls=target_source_urls or [],
            )
            if isinstance(product_target, dict) and product_target.get('ok'):
                return product_target
        if any(str(value or '').strip() for value in (target_source_urls or [])):
            return self._find_data_acquisition_claim_target_by_source_url(
                page,
                target_source_urls or [],
                product_query=product_query,
            )
        return page.evaluate(r'''({productQuery, categoryName, storeName, targetSourceUrls}) => {
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
          const norm = (s) => String(s || '').replace(/\s+/g, '').trim();
          const forbidden = ['发布','立即发布','继续发布','保存并发布','保存并移入待发布','移入待发布','批量发布'];
          const sourceUrls = (row) => Array.from(row.querySelectorAll('a[href]'))
            .map(a => String(a.href || a.getAttribute('href') || ''))
            .filter(url => url.includes('detail.1688.com') || url.includes('yangkeduo.com') || url.includes('http'));
          const targetUrls = Array.isArray(targetSourceUrls) ? targetSourceUrls.filter(Boolean).map(String) : [];
          const hasTargetSource = (row) => {
            if (!targetUrls.length) return false;
            const urls = sourceUrls(row);
            return urls.some(url => targetUrls.some(target => url === target || url.includes(target) || target.includes(url)));
          };
          const rows = Array.from(document.querySelectorAll(
            'tr.vxe-body--row, tr.ant-table-row, tr.el-table__row, tr, .ant-table-row, .el-table__row, .vxe-body--row, [class*="table-row"], [class*="list-item"]'
          )).filter(visible);
          const query = String(productQuery || '').trim();
          const category = String(categoryName || '').trim();
          const store = String(storeName || '').trim();
          const candidates = [];
          rows.forEach((row, index) => {
            const rowText = textOf(row);
            if (!rowText || forbidden.some(term => norm(rowText).includes(norm(term)))) return;
            if (store && rowText.includes(store) === false && norm(rowText).includes(norm(store)) === false) {
              // 数据采集页通常不直接展示店铺，店铺可能在认领弹窗里选择，因此不强制过滤。
            }
            const actions = Array.from(row.querySelectorAll('button,a,[role="button"],span,div'))
              .filter(visible)
              .map(el => ({
                el,
                text: norm(textOf(el)),
                title: norm([el.getAttribute('title'), el.getAttribute('aria-label')].join(' ')),
                cls: String(el.className || ''),
                disabled: Boolean(el.disabled || el.getAttribute('aria-disabled') === 'true' || String(el.className || '').includes('disabled')),
                rect: rectOf(el),
              }))
              .filter(item => {
                const hay = `${item.text} ${item.title} ${item.cls}`;
                if (item.disabled) return false;
                if (forbidden.some(term => norm(hay).includes(norm(term)))) return false;
                if (item.text.includes('已认领') || item.text.includes('已领取')) return false;
                return item.text === '认领'
                  || item.text === '领取'
                  || item.text.includes('认领到采集箱')
                  || item.text.includes('领取到采集箱')
                  || item.title.includes('认领')
                  || item.title.includes('领取');
              })
              .sort((a, b) => (a.rect.w * a.rect.h) - (b.rect.w * b.rect.h));
            if (!actions.length) return;
            const compact = norm(rowText);
            const queryMatched = query ? (rowText.includes(query) || compact.includes(norm(query))) : false;
            const categoryMatched = category ? (rowText.includes(category) || compact.includes(norm(category))) : false;
            const sourceMatched = hasTargetSource(row);
            if (targetUrls.length) {
              if (!sourceMatched) return;
            } else {
              if (query && !queryMatched) return;
              if (!query && category && !categoryMatched) return;
            }
            const lines = rowText.split(/\s{2,}|\n/).map(s => s.trim()).filter(Boolean);
            candidates.push({
              ok: true,
              rowIndex: index,
              rowText: rowText.slice(0, 900),
              title: lines.find(line => !/(认领|领取|采集箱|操作|来源|店铺)/.test(line)) || query || category || rowText.slice(0, 80),
              categoryName: categoryMatched ? category : null,
              sourceUrls: sourceUrls(row),
              actionText: actions[0].text || actions[0].title,
              actionRect: actions[0].rect,
              matchedBy: sourceMatched ? 'source_url' : (queryMatched ? 'product_query' : (categoryMatched ? 'category_name' : 'first_claimable')),
            });
          });
          if (!candidates.length) {
            return {
              ok: false,
              reason: query
                ? `未找到包含“${query}”且可认领的待认领商品`
                : '未找到可认领的待认领商品；请先筛选到唯一商品',
            };
          }
          if (!query && candidates.length > 1) {
            return {
              ok: false,
              reason: '当前待认领结果不唯一，请先输入商品关键词或选择具体商品后再认领',
              matches: candidates.slice(0, 5).map(item => ({rowIndex:item.rowIndex, rowText:item.rowText.slice(0, 260)})),
            };
          }
          if (query && candidates.length > 1) {
            const exact = candidates.filter(item => norm(item.rowText).includes(norm(query)));
            if (exact.length === 1) return exact[0];
            return {
              ok: false,
              reason: `商品关键词“${query}”匹配到多个可认领结果，请先缩小筛选范围`,
              matches: candidates.slice(0, 5).map(item => ({rowIndex:item.rowIndex, rowText:item.rowText.slice(0, 260)})),
            };
          }
          return candidates[0];
        }''', {'productQuery': product_query, 'categoryName': category_name, 'storeName': store_name, 'targetSourceUrls': target_source_urls or []})

    def _find_data_acquisition_claim_target_by_product_query_script(
        self,
        page: Page,
        product_query: str,
        *,
        target_source_urls: list[str],
    ) -> dict[str, Any] | None:
        script = r'''({productQuery, targetSourceUrls}) => {
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
          const norm = (s) => String(s || '').replace(/\s+/g, '').trim().toLowerCase();
          const forbidden = ['发布','立即发布','继续发布','保存并发布','保存并移入待发布','移入待发布','批量发布','一键发布'];
          const sourceUrls = (row) => Array.from(row.querySelectorAll('a[href]'))
            .map(a => String(a.href || a.getAttribute('href') || ''))
            .filter(url => url.includes('detail.1688.com') || url.includes('yangkeduo.com') || url.includes('aliexpress') || url.includes('http'));
          const targetUrls = Array.isArray(targetSourceUrls) ? targetSourceUrls.filter(Boolean).map(String) : [];
          const sourceMatched = (urls) => urls.some(url => targetUrls.some(target => url === target || url.includes(target) || target.includes(url)));
          const query = String(productQuery || '').trim();
          const queryNorm = norm(query);
          const tokens = query
            .toLowerCase()
            .replace(/[^a-z0-9\u4e00-\u9fa5]+/g, ' ')
            .split(/\s+/)
            .filter(token => token.length >= 4)
            .slice(0, 8);
          const rows = Array.from(document.querySelectorAll(
            'tr.vxe-body--row, tr.ant-table-row, tr.el-table__row, tr, .ant-table-row, .el-table__row, .vxe-body--row'
          )).filter(visible);
          const candidates = [];
          for (const [index, row] of rows.entries()) {
            const rowText = textOf(row);
            const compact = norm(rowText);
            if (!rowText || forbidden.some(term => compact.includes(norm(term)))) continue;
            const urls = sourceUrls(row);
            const hasSourceMismatch = targetUrls.length && urls.length && !sourceMatched(urls);
            if (hasSourceMismatch) continue;
            const exact = queryNorm && compact.includes(queryNorm);
            const tokenHits = tokens.filter(token => compact.includes(norm(token))).length;
            if (!exact && tokenHits < Math.min(3, tokens.length || 3)) continue;
            const actions = Array.from(row.querySelectorAll('button,a,[role="button"],span,div'))
              .filter(visible)
              .map(el => ({
                el,
                text: norm(textOf(el)),
                title: norm([el.getAttribute('title'), el.getAttribute('aria-label')].join(' ')),
                cls: String(el.className || ''),
                disabled: Boolean(el.disabled || el.getAttribute('aria-disabled') === 'true' || String(el.className || '').includes('disabled')),
                rect: rectOf(el),
              }))
              .filter(item => {
                const hay = `${item.text} ${item.title} ${item.cls}`;
                if (item.disabled) return false;
                if (forbidden.some(term => norm(hay).includes(norm(term)))) return false;
                if (item.text.includes('已认领') || item.text.includes('已领取')) return false;
                return item.text === '认领'
                  || item.text === '领取'
                  || item.text.includes('认领到采集箱')
                  || item.text.includes('领取到采集箱')
                  || item.title.includes('认领')
                  || item.title.includes('领取');
              })
              .sort((a, b) => (a.rect.w * a.rect.h) - (b.rect.w * b.rect.h));
            if (!actions.length) continue;
            const lines = rowText.split(/\s{2,}|\n/).map(s => s.trim()).filter(Boolean);
            candidates.push({
              ok: true,
              matchedBy: exact ? 'product_query_exact_script' : 'product_query_tokens_script',
              rowIndex: index,
              title: lines.find(line => !/(认领|领取|采集箱|操作|来源|店铺)/.test(line)) || query || rowText.slice(0, 80),
              rowText: rowText.slice(0, 900),
              actionText: actions[0].text || actions[0].title || '认领',
              actionRect: actions[0].rect,
              sourceUrls: urls.length ? urls : targetUrls,
              debug: {strategy:'product_query_script', tokenHits, tokenCount:tokens.length, sourceChecked:Boolean(targetUrls.length), sourceMatched:sourceMatched(urls)},
            });
          }
          if (!candidates.length) return null;
          candidates.sort((a, b) => {
            const aExact = a.matchedBy === 'product_query_exact_script' ? 1 : 0;
            const bExact = b.matchedBy === 'product_query_exact_script' ? 1 : 0;
            return bExact - aExact || a.rowIndex - b.rowIndex;
          });
          return candidates[0];
        }'''
        try:
            payload = {'productQuery': product_query, 'targetSourceUrls': target_source_urls or []}
            try:
                cdp = page.context.new_cdp_session(page)
                response = cdp.send(
                    'Runtime.evaluate',
                    {
                        'expression': f'({script})({json.dumps(payload, ensure_ascii=False)})',
                        'returnByValue': True,
                        'timeout': 2000,
                    },
                )
                if isinstance(response, dict) and response.get('exceptionDetails'):
                    raise RuntimeError(str(response.get('exceptionDetails'))[:240])
                result = ((response or {}).get('result') or {}).get('value')
            except Exception:
                result = page.evaluate(script, payload)
        except Exception as exc:
            self._trace_workflow_event(
                'data_acquisition_claim:product_query_script_failed',
                error=str(exc)[:240],
            )
            return self._find_data_acquisition_claim_target_by_product_query_locator(
                page,
                product_query,
                target_source_urls=target_source_urls,
            )
        if isinstance(result, dict):
            return result
        return None

    def _data_acquisition_source_url_tokens(self, source_urls: list[str]) -> list[str]:
        path_tokens: list[str] = []
        query_tokens: list[str] = []
        for raw in source_urls:
            text = str(raw or '').strip()
            if not text:
                continue
            parsed = urlparse(text)
            for pattern in (r'[?&#]goods_id=(\d+)', r'offer/(\d+)\.html', r'item/(\d+)\.html'):
                for match in re.findall(pattern, text):
                    if match and match not in path_tokens:
                        path_tokens.append(match)
            parts = [(parsed.path, path_tokens), (parsed.query, query_tokens)]
            if not parsed.path and not parsed.query:
                parts.append((text, path_tokens))
            for part, bucket in parts:
                normalized = ''.join(ch if ch.isalnum() else ' ' for ch in part)
                for token in normalized.split():
                    if len(token) >= 8 and token not in bucket:
                        bucket.append(token)
        path_tokens.sort(key=lambda token: (0 if token.isdigit() else 1, -len(token)))
        query_tokens.sort(key=lambda token: (0 if token.isdigit() else 1, -len(token)))
        tokens: list[str] = []
        for token in [*path_tokens, *query_tokens]:
            if token not in tokens:
                tokens.append(token)
        return tokens[:12]

    def _find_data_acquisition_claim_target_by_source_url(
        self,
        page: Page,
        target_source_urls: list[str],
        product_query: str | None = None,
    ) -> dict[str, Any]:
        tokens = self._data_acquisition_source_url_tokens(target_source_urls)
        if not tokens:
            return {'ok': False, 'reason': '来源链接缺少可用于匹配的商品标识'}
        self._trace_workflow_event('data_acquisition_claim:source_lookup_start', token_count=len(tokens))
        result: dict[str, Any] | None = None
        scanned_links = 0
        matched_without_action: dict[str, Any] | None = None
        for token in tokens:
            safe_token = ''.join(ch for ch in token if ch.isalnum())
            if not safe_token:
                continue
            try:
                anchors = page.locator(f'a[href*="{safe_token}"]')
            except Exception:
                continue
            count = min(self._locator_count(anchors), 5)
            scanned_links += count
            for index in range(count):
                anchor = anchors.nth(index)
                row = self._source_match_container(anchor)
                row_text = self._locator_text(row, timeout=1000)
                if self._contains_data_acquisition_claim_forbidden_term(row_text):
                    continue
                action = self._claim_action_in_container(row)
                source_url = self._locator_attribute(anchor, 'href', timeout=1000)
                if action is None:
                    matched_without_action = {
                        'reason': '来源商品行内未找到认领按钮',
                        'rowText': row_text[:400],
                        'sourceUrls': [source_url] if source_url else [],
                        'debug': {'matchedToken': safe_token, 'scannedLinks': scanned_links},
                    }
                    continue
                action_rect = self._locator_box(action, timeout=1000)
                if not self._rect_has_clickable_area(action_rect):
                    matched_without_action = {
                        'reason': '来源商品行内未拿到可点击认领按钮位置',
                        'rowText': row_text[:400],
                        'sourceUrls': [source_url] if source_url else [],
                        'debug': {'matchedToken': safe_token, 'scannedLinks': scanned_links},
                    }
                    continue
                action_text = self._locator_text(action, timeout=1000) or '认领'
                result = {
                    'ok': True,
                    'matchedBy': 'source_url',
                    'rowIndex': index,
                    'title': self._source_match_title(row_text),
                    'rowText': row_text[:800],
                    'actionText': action_text[:120],
                    'actionRect': action_rect,
                    'sourceUrls': [source_url] if source_url else list(target_source_urls or []),
                    'debug': {
                        'matchedToken': safe_token,
                        'scannedLinks': scanned_links,
                        'strategy': 'bounded_locator',
                    },
                }
                break
            if result:
                break
        if result is None and matched_without_action:
            result = {'ok': False, **matched_without_action}
        if (
            result is None
            and str(product_query or '').strip()
            and (scanned_links == 0 or not self._data_acquisition_page_has_source_links(page))
        ):
            result = self._find_data_acquisition_claim_target_by_product_query_locator(
                page,
                str(product_query or '').strip(),
                target_source_urls=target_source_urls,
            )
        if result is None:
            result = {
                'ok': False,
                'reason': '未找到来源链接对应的可认领商品行；请确认该商品已存在于店小秘待认领列表，或换用准确来源链接。',
                'debug': {
                    'scannedLinks': scanned_links,
                    'tokenCount': len(tokens),
                    'strategy': 'bounded_locator',
                },
            }
        self._trace_workflow_event(
            'data_acquisition_claim:source_lookup_dom_scan_done',
            ok=isinstance(result, dict) and result.get('ok'),
            reason=result.get('reason') if isinstance(result, dict) else None,
            debug=result.get('debug') if isinstance(result, dict) else None,
        )
        if isinstance(result, dict) and result.get('ok'):
            return result
        return {
            'ok': False,
            'reason': (
                result.get('reason')
                if isinstance(result, dict) and result.get('reason')
                else '未找到来源链接对应的可认领商品行；请确认该商品已存在于店小秘待认领列表，或换用准确来源链接。'
            ),
            'target_source_urls': target_source_urls,
            'tokens': tokens,
            'debug': result.get('debug') if isinstance(result, dict) else None,
        }

    def _find_data_acquisition_claim_target_by_product_query_locator(
        self,
        page: Page,
        product_query: str,
        *,
        target_source_urls: list[str],
    ) -> dict[str, Any] | None:
        query_tokens = [
            token.lower()
            for token in ''.join(ch if ch.isalnum() else ' ' for ch in product_query).split()
            if len(token) >= 4
        ][:6]
        actions: list[Any] = []
        exact_text_predicate = (
            'normalize-space(.)="认领" or normalize-space(.)="领取" '
            'or normalize-space(.)="认领到采集箱" or normalize-space(.)="领取到采集箱"'
        )
        for selector in (
            f'xpath=//button[{exact_text_predicate}]',
            f'xpath=//a[{exact_text_predicate}]',
            f'xpath=//*[@role="button" and ({exact_text_predicate})]',
            f'xpath=//span[{exact_text_predicate}]',
        ):
            try:
                candidates = page.locator(selector)
            except Exception:
                continue
            for index in range(min(self._locator_count(candidates), 20 - len(actions))):
                actions.append(candidates.nth(index))
            if len(actions) >= 20:
                break
        count = min(len(actions), 20)
        samples: list[dict[str, Any]] = []
        self._trace_workflow_event(
            'data_acquisition_claim:product_query_locator_start',
            action_count=count,
            query_tokens=query_tokens,
            human_step='按标题匹配待认领结果',
        )
        for index in range(count):
            action = actions[index]
            action_text = self._locator_text(action, timeout=800)
            compact_action = ''.join(str(action_text or '').split())
            if compact_action not in {'认领', '领取', '认领到采集箱', '领取到采集箱'}:
                if len(samples) < 6:
                    samples.append({
                        'index': index,
                        'skip': 'action_text',
                        'actionText': str(action_text or '')[:120],
                    })
                continue
            row = self._source_match_container(action)
            row_text = self._locator_text(row, timeout=1000)
            if self._contains_data_acquisition_claim_forbidden_term(row_text):
                if len(samples) < 6:
                    samples.append({
                        'index': index,
                        'skip': 'forbidden_text',
                        'actionText': str(action_text or '')[:120],
                        'rowText': str(row_text or '')[:240],
                    })
                continue
            source_urls = self._source_urls_in_container(row)
            if target_source_urls and source_urls and not self._source_urls_match(source_urls, target_source_urls):
                if len(samples) < 6:
                    samples.append({
                        'index': index,
                        'skip': 'source_url_mismatch',
                        'actionText': str(action_text or '')[:120],
                        'rowText': str(row_text or '')[:240],
                        'sourceUrls': source_urls[:3],
                    })
                continue
            hay = row_text.lower()
            if query_tokens and not any(token in hay for token in query_tokens):
                if len(samples) < 6:
                    samples.append({
                        'index': index,
                        'skip': 'query_token_miss',
                        'actionText': str(action_text or '')[:120],
                        'rowText': str(row_text or '')[:240],
                        'sourceUrls': source_urls[:3],
                    })
                continue
            action_rect = self._locator_box(action, timeout=1000)
            if not self._rect_has_clickable_area(action_rect):
                if len(samples) < 6:
                    samples.append({
                        'index': index,
                        'skip': 'action_rect_missing',
                        'actionText': str(action_text or '')[:120],
                        'rowText': str(row_text or '')[:240],
                    })
                continue
            self._trace_workflow_event(
                'data_acquisition_claim:product_query_locator_matched',
                index=index,
                row_text=str(row_text or '')[:240],
                source_urls=source_urls[:3],
                human_step='按标题匹配待认领结果',
            )
            return {
                'ok': True,
                'matchedBy': 'product_query_after_collect',
                'rowIndex': index,
                'title': self._source_match_title(row_text) or product_query[:160],
                'rowText': row_text[:800],
                'actionText': action_text[:120] or '认领',
                'actionRect': action_rect,
                'sourceUrls': source_urls or list(target_source_urls or []),
                'debug': {
                    'strategy': 'product_query_locator_after_collect',
                    'queryTokens': query_tokens,
                },
            }
        self._trace_workflow_event(
            'data_acquisition_claim:product_query_locator_no_match',
            action_count=count,
            query_tokens=query_tokens,
            samples=samples,
            human_step='按标题匹配待认领结果',
        )
        return None

    def _source_urls_in_container(self, container: Any) -> list[str]:
        urls: list[str] = []
        try:
            anchors = container.locator('a[href]')
        except Exception:
            return urls
        for index in range(min(self._locator_count(anchors), 10)):
            url = self._locator_attribute(anchors.nth(index), 'href', timeout=500)
            if url and url not in urls:
                urls.append(url)
        return urls

    def _data_acquisition_page_has_source_links(self, page: Page) -> bool:
        try:
            anchors = page.locator('a[href]')
        except Exception:
            return True
        for index in range(min(self._locator_count(anchors), 30)):
            url = self._locator_attribute(anchors.nth(index), 'href', timeout=500)
            if url and ('http' in url or 'detail.1688.com' in url or 'aliexpress' in url or 'yangkeduo.com' in url):
                return True
        return False

    def _source_urls_match(self, actual_urls: list[str], target_urls: list[str]) -> bool:
        actual = [str(url or '').strip() for url in actual_urls if str(url or '').strip()]
        targets = [str(url or '').strip() for url in target_urls if str(url or '').strip()]
        return any(url == target or url in target or target in url for url in actual for target in targets)

    def _source_match_container(self, anchor: Any) -> Any:
        for selector in (
            'xpath=ancestor::tr[1]',
            'xpath=ancestor::*[contains(@class,"row") or contains(@class,"item") or contains(@class,"table")][1]',
            'xpath=ancestor::*[self::li or self::section or self::div][1]',
        ):
            try:
                candidate = anchor.locator(selector)
                if self._locator_count(candidate) > 0:
                    return candidate.first
            except Exception:
                continue
        return anchor

    def _claim_action_in_container(self, container: Any) -> Any | None:
        for selector in (
            'button',
            'a',
            '[role="button"]',
            'span',
            'div',
        ):
            try:
                candidates = container.locator(selector).filter(has_text='认领')
                for index in range(min(self._locator_count(candidates), 10)):
                    candidate = candidates.nth(index)
                    compact = ''.join(str(self._locator_text(candidate, timeout=500) or '').split())
                    if compact in {'认领', '认领到采集箱'}:
                        return candidate
            except Exception:
                continue
            try:
                candidates = container.locator(selector).filter(has_text='领取')
                for index in range(min(self._locator_count(candidates), 10)):
                    candidate = candidates.nth(index)
                    compact = ''.join(str(self._locator_text(candidate, timeout=500) or '').split())
                    if compact in {'领取', '领取到采集箱'}:
                        return candidate
            except Exception:
                continue
        return None

    def _source_match_title(self, row_text: str) -> str:
        for line in [part.strip() for part in str(row_text or '').replace('\r', '\n').split('\n') if part.strip()]:
            if not any(term in line for term in ('认领', '领取', '采集箱', '操作', '来源', '店铺')):
                return line[:160]
        return str(row_text or '店小秘待认领商品')[:160]

    def _locator_count(self, locator: Any) -> int:
        try:
            return int(locator.count())
        except Exception:
            return 0

    def _locator_text(self, locator: Any, *, timeout: int = 1000) -> str:
        try:
            return str(locator.inner_text(timeout=timeout) or '').strip()
        except TypeError:
            try:
                return str(locator.inner_text() or '').strip()
            except Exception:
                return ''
        except Exception:
            return ''

    def _locator_attribute(self, locator: Any, name: str, *, timeout: int = 1000) -> str:
        try:
            return str(locator.get_attribute(name, timeout=timeout) or '').strip()
        except TypeError:
            try:
                return str(locator.get_attribute(name) or '').strip()
            except Exception:
                return ''
        except Exception:
            return ''

    def _locator_box(self, locator: Any, *, timeout: int = 1000) -> dict[str, Any]:
        try:
            box = locator.bounding_box(timeout=timeout)
        except TypeError:
            try:
                box = locator.bounding_box()
            except Exception:
                box = None
        except Exception:
            box = None
        if not isinstance(box, dict):
            return {}
        return {
            'x': float(box.get('x') or 0),
            'y': float(box.get('y') or 0),
            'w': float(box.get('width') or box.get('w') or 0),
            'h': float(box.get('height') or box.get('h') or 0),
        }

    def _complete_data_acquisition_claim_dialog(
        self,
        page: Page,
        category_name: str | None = None,
        store_name: str | None = None,
    ) -> dict[str, Any]:
        if os.name == 'nt' and not self._is_headless() and self._is_data_acquisition_page_url(page):
            self._trace_workflow_event(
                'data_acquisition_claim_dialog:visible_scan_start',
                human_step='检查认领确认弹窗',
            )
            try:
                page.wait_for_timeout(1200)
            except Exception:
                pass
        category_json = json.dumps(category_name or '', ensure_ascii=False)
        store_json = json.dumps(store_name or '', ensure_ascii=False)
        script = r'''() => {
          const categoryName = __CATEGORY_NAME__;
          const storeName = __STORE_NAME__;
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
          const norm = (s) => String(s || '').replace(/\s+/g, '').trim();
          const forbidden = ['发布','立即发布','继续发布','保存并发布','保存并移入待发布','移入待发布','批量发布'];
          const containers = Array.from(document.querySelectorAll('.ant-modal, .ant-modal-wrap, .el-dialog, [role="dialog"], .modal, .layui-layer'))
            .filter(visible)
            .filter(el => {
              const text = textOf(el);
              return text.includes('认领') || text.includes('领取') || text.includes('采集箱');
            });
          const dialog = containers[containers.length - 1];
          if (!dialog) return {ok:true, skipped:true, reason:'未出现认领确认弹窗'};
          const dialogText = textOf(dialog);
          if (forbidden.some(term => norm(dialogText).includes(norm(term)))) {
            return {ok:false, reason:'认领弹窗中检测到发布相关动作，已停止'};
          }
          const dialogRect = rectOf(dialog);
          const optionRects = [];
          const optionTargetFor = (el) => {
            for (const selector of ['label', '.ant-checkbox-wrapper', '.el-checkbox', '.ant-radio-wrapper', 'li', '[role="treeitem"]']) {
              try {
                const target = el.closest(selector);
                if (!target || !dialog.contains(target) || !visible(target)) continue;
                const r = rectOf(target);
                if (r.width >= dialogRect.w * 0.92 && r.height >= dialogRect.h * 0.45) continue;
                return target;
              } catch (_) {}
            }
            return el;
          };
          for (const label of [storeName, categoryName].filter(Boolean)) {
            const labelNorm = norm(label);
            const option = Array.from(dialog.querySelectorAll('button,a,li,span,div,label'))
              .filter(visible)
              .map(el => {
                const text = textOf(el);
                const textNorm = norm(text);
                const target = optionTargetFor(el);
                const targetRect = rectOf(target);
                const elRect = rectOf(el);
                return {
                  el,
                  target,
                  text,
                  textNorm,
                  targetRect,
                  elRect,
                  exact: textNorm === labelNorm,
                  starts: textNorm.startsWith(labelNorm),
                  area: Math.max(1, targetRect.w * targetRect.h),
                };
              })
              .filter(item => item.textNorm === labelNorm || item.textNorm.includes(labelNorm))
              .filter(item => item.targetRect.w < dialogRect.w * 0.92 || item.exact || item.starts)
              .sort((a, b) => {
                if (a.exact !== b.exact) return a.exact ? -1 : 1;
                if (a.starts !== b.starts) return a.starts ? -1 : 1;
                if (a.textNorm.length !== b.textNorm.length) return a.textNorm.length - b.textNorm.length;
                return a.area - b.area;
              })[0];
            if (option) {
              optionRects.push({label, rect:option.targetRect, text:option.text.slice(0, 120)});
            }
          }
          const buttons = Array.from(dialog.querySelectorAll('button,a,[role="button"],span,div'))
            .filter(visible)
            .map(el => ({
              el,
              text: norm(textOf(el)),
              cls: String(el.className || ''),
              rect: rectOf(el),
              disabled: Boolean(el.disabled || el.getAttribute('aria-disabled') === 'true' || String(el.className || '').includes('disabled')),
            }))
            .filter(item => !item.disabled && !forbidden.some(term => norm(`${item.text} ${item.cls}`).includes(norm(term))));
          const submit = buttons.find(item => ['确定','确认','提交','开始认领','认领','领取'].includes(item.text))
            || buttons.find(item => item.text.includes('认领') || item.text.includes('领取'));
          if (!submit) {
            return {ok:false, reason:'认领弹窗已打开，但未找到安全确认按钮', dialog_text:dialogText.slice(0, 400), clicked_options: optionRects.map(item => item.label)};
          }
          return {
            ok:true,
            submitted:false,
            submit_text:submit.text,
            submit_rect:submit.rect,
            option_rects: optionRects,
            clicked_options: optionRects.map(item => item.label),
          };
        }'''.replace('__CATEGORY_NAME__', category_json).replace('__STORE_NAME__', store_json)
        try:
            result = self._evaluate_zero_arg_page_function_with_runtime_timeout(page, script, timeout=2000)
        except Exception as exc:  # noqa: BLE001 - DXM may navigate while the dialog is being inspected.
            return {'ok': False, 'reason': f'认领弹窗扫描失败：{str(exc)[:240]}'}
        if not isinstance(result, dict):
            return {'ok': False, 'reason': '认领弹窗扫描没有返回可用结果'}
        if not result.get('ok') or result.get('skipped'):
            return result
        clicked_options: list[str] = []
        for option in result.get('option_rects') or []:
            if not isinstance(option, dict) or not isinstance(option.get('rect'), dict):
                continue
            if not self._rect_has_clickable_area(option['rect']):
                continue
            self._click_data_acquisition_claim_rect_center(page, option['rect'], purpose='认领弹窗选项')
            clicked_options.append(str(option.get('label') or option.get('text') or ''))
            try:
                page.wait_for_timeout(250)
            except Exception:
                pass
        submit_rect = result.get('submit_rect')
        if not isinstance(submit_rect, dict) or not self._rect_has_clickable_area(submit_rect):
            return {'ok': False, 'reason': '认领弹窗确认按钮坐标不可用', 'dialog_state': result}
        self._click_data_acquisition_claim_rect_center(page, submit_rect, purpose='认领弹窗确认')
        try:
            page.wait_for_timeout(800)
        except Exception:
            pass
        updated = dict(result)
        updated['submitted'] = True
        updated['clicked_options'] = clicked_options or result.get('clicked_options') or []
        return updated

    def _verify_draft_box_claim(
        self,
        claim_mark: str,
        product_query: str | None = None,
        category_name: str | None = None,
        store_name: str | None = None,
        target_source_urls: list[str] | None = None,
    ) -> dict[str, Any]:
        self._trace_workflow_event(
            'draft_box_claim_verify:start',
            product_query=product_query,
            category_name=category_name,
            store_name=store_name,
            human_step='打开商品箱确认认领结果',
        )
        state = self.get_state()
        claimed = state.get('claimed_product') if isinstance(state.get('claimed_product'), dict) else {}
        product_query = product_query or claimed.get('title')
        category_name = category_name or claimed.get('category_name')
        resolved_target_source_urls = list(target_source_urls or [])
        if claimed.get('source_url'):
            resolved_target_source_urls.append(claimed.get('source_url'))
        page = self._ensure_page_with_cookies()
        visible_from_data_acquisition = os.name == 'nt' and not self._is_headless() and self._is_data_acquisition_page_url(page)
        if visible_from_data_acquisition:
            trace: list[dict[str, Any]] = []
            self._dismiss_data_acquisition_notice_with_native_click(page)
            self._click_data_acquisition_visible_dismiss_points(page, trace)
            self._press_native_escape_for_visible_dxm(page)
        draft_box_url = WORKFLOW_TARGETS['draft_box']['url']
        visible_browser = os.name == 'nt' and not self._is_headless()
        native_navigated = (
            visible_from_data_acquisition
            and self._navigate_visible_dxm_with_native_address_bar(page, draft_box_url)
        )
        if not native_navigated and visible_browser:
            self._trace_workflow_event(
                'draft_box_claim_verify:sterile_goto_start',
                url=draft_box_url,
                current_url=getattr(page, 'url', None),
                human_step='打开商品箱页面',
            )
            page.goto(
                draft_box_url,
                wait_until='commit' if visible_from_data_acquisition else 'domcontentloaded',
                timeout=15000 if visible_from_data_acquisition else 45000,
            )
            self._trace_workflow_event(
                'draft_box_claim_verify:sterile_goto_done',
                current_url=getattr(page, 'url', None),
                human_step='商品箱页面已打开',
            )
        elif not native_navigated:
            self._goto_with_live_hud(
                page,
                draft_box_url,
                wait_until='commit' if visible_from_data_acquisition else 'domcontentloaded',
                timeout=15000 if visible_from_data_acquisition else 45000,
            )
        self._trace_workflow_event(
            'draft_box_claim_verify:navigate_done',
            current_url=getattr(page, 'url', None),
            native_navigated=native_navigated,
            human_step='已打开商品箱',
        )
        visible_draft_box = visible_browser
        if visible_draft_box:
            self._trace_workflow_event(
                'draft_box_claim_verify:visible_settle_start',
                seconds=10,
                human_step='等待商品箱页面稳定',
            )
            page.wait_for_timeout(10000)
            wait_result = {
                'ready': True,
                'ready_term': 'visible_draft_box_settle',
                'loading': None,
                'rows': None,
                'text_excerpt': '',
                'url': getattr(page, 'url', ''),
                'title': '',
            }
        else:
            wait_result = self._wait_for_page_ready(
                page,
                WORKFLOW_READY_TERMS['draft_box'],
                label='商品箱',
                timeout=60000,
            )
        self._trace_workflow_event(
            'draft_box_claim_verify:ready',
            wait_result={
                'ready': wait_result.get('ready') if isinstance(wait_result, dict) else None,
                'ready_term': wait_result.get('ready_term') if isinstance(wait_result, dict) else None,
                'rows': wait_result.get('rows') if isinstance(wait_result, dict) else None,
                'loading': wait_result.get('loading') if isinstance(wait_result, dict) else None,
            },
            human_step='商品箱页面已加载',
        )
        dismissed = self._dismiss_blocking_modals_if_visible(page, context='draft_box_claim_verify:after_ready')
        self._trace_workflow_event(
            'draft_box_claim_verify:dismiss_done',
            dismissed=dismissed,
            human_step='检查商品箱弹窗',
        )
        row_info: dict[str, Any] | None = None
        try:
            self._trace_workflow_event(
                'draft_box_claim_verify:find_visible_start',
                product_query=product_query,
                store_name=store_name,
                target_source_urls=resolved_target_source_urls,
                human_step='先检查当前商品箱列表',
            )
            row_info = self._find_draft_box_row(
                page,
                product_query,
                store_name=store_name,
                claim_mark=claim_mark,
                target_source_urls=resolved_target_source_urls,
            )
            self._trace_workflow_event(
                'draft_box_claim_verify:find_visible_done',
                matched_by=row_info.get('matchedBy'),
                human_step='当前列表已找到商品',
            )
        except RuntimeError as exc:
            self._trace_workflow_event(
                'draft_box_claim_verify:find_visible_missed',
                reason=str(exc)[:240],
                human_step='当前列表未直接找到商品',
            )

        if row_info is None:
            self._search_draft_box(page, product_query=product_query, store_name=store_name)
            self._trace_workflow_event(
                'draft_box_claim_verify:search_done',
                product_query=product_query,
                store_name=store_name,
                human_step='搜索商品箱商品',
            )
            try:
                self._trace_workflow_event(
                    'draft_box_claim_verify:find_start',
                    product_query=product_query,
                    store_name=store_name,
                    target_source_urls=resolved_target_source_urls,
                    human_step='定位商品箱商品',
                )
                row_info = self._find_draft_box_row(
                    page,
                    product_query,
                    store_name=store_name,
                    claim_mark=claim_mark,
                    target_source_urls=resolved_target_source_urls,
                )
            except RuntimeError:
                self._trace_workflow_event(
                    'draft_box_claim_verify:find_retry_by_category',
                    category_name=category_name,
                    human_step='改用类目重新搜索商品箱商品',
                )
                self._search_draft_box(page, product_query=category_name, store_name=store_name)
                row_info = self._find_draft_box_row(
                    page,
                    category_name or product_query,
                    store_name=store_name,
                    target_source_urls=resolved_target_source_urls,
                )
        if row_info is None:
            raise RuntimeError('未找到商品箱商品')
        self._trace_workflow_event(
            'draft_box_claim_verify:find_done',
            matched_by=row_info.get('matchedBy'),
            source_urls=row_info.get('sourceUrls', []),
            human_step='已找到商品箱商品',
        )
        screenshot_path = ACQUISITION_ACTION_SCREENSHOT_MAP['verify']
        self._trace_workflow_event(
            'draft_box_claim_verify:screenshot_start',
            path=str(screenshot_path),
            human_step='保存商品箱证据',
        )
        page.screenshot(path=str(screenshot_path), full_page=True)
        self._trace_workflow_event(
            'draft_box_claim_verify:screenshot_done',
            path=str(screenshot_path),
            human_step='商品箱证据已保存',
        )
        claimed_product_title = self._draft_box_claimed_product_title(
            product_query=product_query,
            row_text=row_info.get('rowText'),
            category_name=category_name,
            claimed=claimed,
        )
        return {
            'page_title': page.title(),
            'page_url': page.url,
            'screenshot_url': self._artifact_url(screenshot_path),
            'product_query': product_query,
            'category_name': category_name,
            'store_name': store_name,
            'claim_mark': claim_mark,
            'target_row_text': row_info.get('rowText'),
            'target_source_urls': row_info.get('sourceUrls', []),
            'claimed_product': {
                'title': claimed_product_title,
                'category_name': category_name,
                'source_url': (row_info.get('sourceUrls') or resolved_target_source_urls or [None])[0],
                'row_text': row_info.get('rowText'),
            },
            'published': False,
        }

    def _draft_box_claimed_product_title(
        self,
        *,
        product_query: str | None,
        row_text: str | None,
        category_name: str | None,
        claimed: dict[str, Any] | None = None,
    ) -> str:
        row_title = self._product_title_from_draft_box_row(row_text)
        query = str(product_query or '').strip()
        claimed_title = str((claimed or {}).get('title') or '').strip()
        for candidate in (row_title, claimed_title, query, str(category_name or '').strip()):
            if candidate and not self._looks_like_external_url(candidate):
                return candidate
        return query or claimed_title or str(category_name or '').strip() or '店小秘待认领商品'

    @staticmethod
    def _looks_like_external_url(value: str) -> bool:
        text = str(value or '').strip()
        if not text:
            return False
        try:
            parsed = urlparse(text)
        except Exception:
            return False
        return bool(parsed.scheme in {'http', 'https'} and parsed.netloc)

    @staticmethod
    def _product_title_from_draft_box_row(row_text: str | None) -> str:
        text = re.sub(r'\s+', ' ', str(row_text or '')).strip()
        if not text:
            return ''
        text = re.split(r'\s+「[^」]+」|\s+创建：|\s+更新：|\s+移入待发布|\s+编辑|\s+发布|\s+更多', text, maxsplit=1)[0].strip()
        text = re.sub(r'^(1688|拼多多|淘宝|天猫|京东|Wish|AliExpress|Shopee|Lazada|eBay|Amazon)\s+', '', text, flags=re.IGNORECASE).strip()
        return text[:120].strip()

    def _perform_editor_action(
        self,
        action: str,
        defaults: dict[str, Any] | None = None,
        product_query: str | None = None,
        store_name: str | None = None,
        target_source_urls: list[str] | None = None,
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
            if not self._is_same_dxm_editor_page(getattr(page, 'url', ''), editor_url):
                self._goto_with_live_hud(page, editor_url, wait_until='domcontentloaded', timeout=45000)
                page.wait_for_timeout(2000)
            self._trace_workflow_event(
                'editor_action:wait_ready_start',
                action=action,
                current_url=getattr(page, 'url', None),
                human_step='等待编辑页内容加载',
            )
            visible_editor_page = self._is_visible_dxm_editor_page(page)
            ready = (
                self._wait_for_visible_editor_loaded(page, product_query=product_query, timeout=20000)
                if visible_editor_page
                else self._wait_for_body_text(page, ['基本信息', '半托管服务', '产品信息'])
            )
            self._trace_workflow_event(
                'editor_action:wait_ready_done',
                action=action,
                ready=ready,
                current_url=getattr(page, 'url', None),
                human_step='编辑页内容等待完成',
            )
            if visible_editor_page and not ready:
                return self._editor_page_not_ready_result(
                    action=action,
                    page=page,
                    editor_url=editor_url,
                    product_query=product_query,
                    store_name=store_name,
                )
            has_known_editor_url = self._is_dxm_editor_url(editor_url)
            if not ready and product_query and not has_known_editor_url:
                page = self._open_editor_page_for_product(page, product_query, store_name)
                reopened_ready = self._wait_for_body_text(page, ['基本信息', '半托管服务', '产品信息'])
                self._trace_workflow_event(
                    'editor_action:reopened_wait_ready_done',
                    action=action,
                    ready=reopened_ready,
                    current_url=getattr(page, 'url', None),
                    human_step='重新打开编辑页后等待完成',
                )
            self._trace_workflow_event(
                'editor_action:dismiss_start',
                action=action,
                current_url=getattr(page, 'url', None),
                human_step='检查编辑页提示弹窗',
            )
            if os.name == 'nt' and not self._is_headless():
                dismissed_modals = self._dismiss_blocking_modals_if_visible(page, context='editor_action:after_ready')
            else:
                dismissed_modals = self._dismiss_blocking_modals(page)
            self._trace_workflow_event(
                'editor_action:dismiss_done',
                action=action,
                dismissed=dismissed_modals,
                current_url=getattr(page, 'url', None),
                human_step='编辑页提示弹窗检查完成',
            )
            if action == 'verify_edit_ownership':
                return self._verify_edit_ownership_on_page(
                    page,
                    product_query,
                    store_name,
                    expected_source_urls=target_source_urls or state.get('target_source_urls') or [],
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

        state_page_url = state.get('page_url')
        if action in {'save_only', 'verify_not_published'} and self._is_dxm_editor_url(state_page_url):
            editor_url = str(state_page_url or '')
            if not self._is_same_dxm_editor_page(getattr(page, 'url', ''), editor_url):
                self._trace_workflow_event(
                    'editor_action:sterile_goto_start',
                    action=action,
                    url=editor_url,
                    current_url=getattr(page, 'url', None),
                    human_step='打开编辑页',
                )
                page.goto(editor_url, wait_until='domcontentloaded', timeout=45000)
                self._trace_workflow_event(
                    'editor_action:sterile_goto_done',
                    action=action,
                    current_url=getattr(page, 'url', None),
                    human_step='编辑页已打开',
                )
                page.wait_for_timeout(3000 if not self._is_headless() else 2000)
            visible_editor_page = self._is_visible_dxm_editor_page(page)
            ready = (
                self._wait_for_visible_editor_loaded(page, product_query=product_query, timeout=20000)
                if visible_editor_page
                else self._wait_for_body_text(page, ['基本信息', '产品信息', '保存'], timeout=15000)
            )
            if not ready:
                return self._editor_page_not_ready_result(
                    action=action,
                    page=page,
                    editor_url=editor_url,
                    product_query=product_query,
                    store_name=store_name,
                )
            self._reapply_live_hud_if_available(page)
            if action == 'verify_not_published':
                result = self._verify_not_published_on_page(
                    page,
                    product_query,
                    store_name,
                    prior_save_result=state.get('save_result'),
                )
            else:
                prefill = self._prepare_editor_page_for_save(page, defaults)
                if str(prefill.get('stage')).endswith('_failed'):
                    result = {
                        **prefill,
                        'stage': 'save_only_failed',
                        'label': '保存前编辑页配置未完成',
                        'message': prefill.get('message') or '保存前编辑页必填字段未补齐。',
                        'save_result': {
                            'ok': False,
                            'reason': 'editor_prefill_failed',
                            'published': False,
                            'preflight_results': prefill.get('preflight_results'),
                        },
                        'published': False,
                    }
                    if isinstance(result, dict) and not result.get('source_editor_url'):
                        result['source_editor_url'] = editor_url
                    return result
                result = self._save_only_on_page(page)
            if isinstance(result, dict) and not result.get('source_editor_url'):
                result['source_editor_url'] = editor_url
            return result

        semi_url = state.get('page_url')
        if not semi_url:
            raise RuntimeError('缺少上次半托管页地址')
        source_editor_url = state.get('source_editor_url') or state.get('editor_page_url')
        if action == 'fill_semi_managed_defaults' and self._is_visible_dxm_editor_page(page):
            result = self._fill_semi_managed_defaults_on_page(page, defaults)
            if source_editor_url and not result.get('source_editor_url'):
                result['source_editor_url'] = source_editor_url
            return result
        needs_source_reopen = bool(source_editor_url and 'editFromSmt' in str(semi_url) and '?' not in str(semi_url))
        if needs_source_reopen:
            self._goto_with_live_hud(page, source_editor_url, wait_until='domcontentloaded', timeout=45000)
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
            self._goto_with_live_hud(page, semi_url, wait_until='domcontentloaded', timeout=45000)
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

    def _is_dxm_editor_url(self, url: str | None) -> bool:
        try:
            parsed = urlparse(str(url or ''))
        except ValueError:
            return False
        if not parsed.netloc.endswith('dianxiaomi.com'):
            return False
        if parsed.path.rstrip('/') != '/web/smt/edit':
            return False
        editor_id = (parse_qs(parsed.query).get('id') or [''])[0]
        return bool(editor_id)

    def _is_visible_dxm_editor_page(self, page: Page) -> bool:
        return os.name == 'nt' and not self._is_headless() and self._is_dxm_editor_url(getattr(page, 'url', None))

    def _is_same_dxm_editor_page(self, current_url: str | None, expected_url: str | None) -> bool:
        try:
            current = urlparse(str(current_url or ''))
            expected = urlparse(str(expected_url or ''))
        except ValueError:
            return False
        if not current.netloc.endswith('dianxiaomi.com') or not expected.netloc.endswith('dianxiaomi.com'):
            return False
        if current.path.rstrip('/') != expected.path.rstrip('/'):
            return False
        if current.path.rstrip('/') != '/web/smt/edit':
            return False
        expected_id = (parse_qs(expected.query).get('id') or [''])[0]
        current_id = (parse_qs(current.query).get('id') or [''])[0]
        return bool(expected_id and current_id and expected_id == current_id)

    def _editor_page_not_ready_result(
        self,
        *,
        action: str,
        page: Page,
        editor_url: str | None,
        product_query: str | None = None,
        store_name: str | None = None,
    ) -> dict[str, Any]:
        page_url = str(getattr(page, 'url', '') or editor_url or '')
        fill_result = {
            'ok': False,
            'reason': 'editor_page_not_ready',
            'product_query': str(product_query or '').strip(),
            'store_name': str(store_name or '').strip(),
            'page_url': page_url,
            'verified_by': 'visible_editor_ready_gate',
        }
        result = {
            'stage': f'{action}_failed',
            'label': '编辑页未加载完成',
            'message': '编辑页仍在加载或关键商品信息为空，未继续执行。',
            'next_action': '等待店小秘编辑页加载完成，确认店铺、标题、分类出现后再重试。',
            'page_title': '店小秘编辑页' if self._is_dxm_editor_url(page_url) else None,
            'page_url': page_url,
            'fill_result': fill_result,
            'source_editor_url': editor_url,
            'published': False,
        }
        if action == 'save_only':
            result['save_result'] = {
                'ok': False,
                'reason': 'editor_page_not_ready',
                'published': False,
            }
        return result

    def _wait_for_visible_editor_loaded(
        self,
        page: Page,
        *,
        product_query: str | None = None,
        timeout: int = 20000,
    ) -> bool:
        deadline = time.monotonic() + max(float(timeout) / 1000.0, 1.0)
        last_state: dict[str, Any] | None = None
        attempt = 0
        while True:
            attempt += 1
            state = self._visible_editor_ready_state(page, product_query=product_query)
            last_state = state
            self._trace_workflow_event(
                'visible_editor_ready_check',
                attempt=attempt,
                ready=bool(state.get('ready')),
                loading=state.get('loading'),
                reason=state.get('reason'),
                source=state.get('source'),
                current_url=getattr(page, 'url', None),
                human_step='确认编辑页已加载',
            )
            if state.get('ready') is True:
                return True
            if time.monotonic() >= deadline:
                self._trace_workflow_event(
                    'visible_editor_ready_timeout',
                    last_state=last_state,
                    current_url=getattr(page, 'url', None),
                    human_step='编辑页加载等待超时',
                )
                return False
            time.sleep(1.0)

    def _visible_editor_ready_state(self, page: Page, *, product_query: str | None = None) -> dict[str, Any]:
        script = r'''({productQuery}) => {
          const norm = (s) => String(s || '').replace(/\s+/g, '').trim();
          const visible = (el) => {
            if (!el || !el.getBoundingClientRect) return false;
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const body = String(document.body ? (document.body.innerText || document.body.textContent || '') : '');
          const compact = norm(body);
          const visibleControls = Array.from(document.querySelectorAll('input,textarea,select,[class*="select"],[class*="Select"]')).filter(visible);
          const values = visibleControls.map(el => String(el.value || el.getAttribute('value') || el.innerText || el.textContent || '').trim()).filter(Boolean);
          const query = String(productQuery || '').trim();
          const queryCompact = norm(query);
          const titleValues = Array.from(document.querySelectorAll('input,textarea'))
            .filter(visible)
            .map(el => {
              const r = el.getBoundingClientRect();
              return {value: String(el.value || el.getAttribute('value') || '').trim(), width: r.width, top: r.top};
            })
            .filter(item => item.width >= 300 && item.top < 520 && item.value && !item.value.includes('请选择'));
          const loadingVisible = Array.from(document.querySelectorAll('[class*="loading"],[class*="Loading"],[class*="spin"],[class*="Spin"],[class*="loader"],[class*="Loader"]'))
            .some(el => visible(el) && norm(el.innerText || el.textContent || el.getAttribute('class') || '').match(/loading|加载|spin/i));
          const bodyLoading = compact.includes('LOADING') || compact.includes('加载中');
          const storeMissing = compact.includes('----请选择店铺----') || compact.includes('请选择店铺');
          const categoryMissing = compact.includes('----请选择分类----') || compact.includes('未选择分类');
          const titleMissing = titleValues.length === 0;
          const queryMatched = Boolean(queryCompact && (compact.includes(queryCompact) || values.some(value => norm(value).includes(queryCompact))));
          const hasEditorSignals = compact.includes('基本信息') && compact.includes('产品信息') && compact.includes('保存');
          const hasLoadedRequiredFields = !storeMissing && !categoryMissing && !titleMissing;
          const ready = Boolean(hasEditorSignals && !loadingVisible && !bodyLoading && (queryMatched || hasLoadedRequiredFields));
          return {
            ready,
            loading: Boolean(loadingVisible || bodyLoading),
            has_editor_signals: hasEditorSignals,
            query_matched: queryMatched,
            title_missing: titleMissing,
            store_missing: storeMissing,
            category_missing: categoryMissing,
            sample_values: values.slice(0, 5),
            reason: ready ? null : '编辑页仍在加载或关键字段为空',
            source: 'dom',
          };
        }'''
        try:
            result = self._evaluate_page_function_with_runtime_timeout(
                page,
                script,
                {'productQuery': product_query or ''},
                timeout=1800,
            )
            if isinstance(result, dict):
                return result
        except Exception as exc:  # noqa: BLE001 - fall back to native loading detector below.
            native_state = self._visible_editor_native_loading_state(page)
            native_loading = native_state.get('loading') is True
            reason = (
                native_state.get('reason')
                if native_loading
                else '无法确认编辑页关键字段已加载'
            )
            return {
                **native_state,
                'ready': False,
                'reason': reason or f'编辑页状态读取失败：{str(exc)[:160]}',
                'dom_error': str(exc)[:240],
                'verified_by': None,
            }
        return {'ready': False, 'reason': '编辑页状态结果不可读', 'source': 'dom'}

    def _visible_editor_native_loading_state(self, page: Page) -> dict[str, Any]:
        snapshot = self._capture_native_dxm_content_snapshot(page)
        if not snapshot:
            return {'loading': None, 'reason': '无法截取真实浏览器内容确认编辑页状态', 'source': 'native_snapshot'}
        loading = self._native_snapshot_has_loading_spinner(snapshot)
        return {
            'loading': loading,
            'reason': '真实浏览器仍显示加载中' if loading else '无法通过 DOM 确认编辑页关键字段',
            'source': 'native_snapshot',
        }

    @staticmethod
    def _native_snapshot_has_loading_spinner(snapshot: dict[str, Any]) -> bool:
        try:
            width = int(snapshot.get('width') or 0)
            height = int(snapshot.get('height') or 0)
            pixels = snapshot.get('pixels') or b''
        except (TypeError, ValueError):
            return False
        if width <= 0 or height <= 0 or len(pixels) < width * height * 4:
            return False
        x0 = max(int(width * 0.28), 0)
        x1 = min(int(width * 0.72), width)
        y0 = max(int(height * 0.18), 0)
        y1 = min(int(height * 0.82), height)
        blue_points: set[tuple[int, int]] = set()
        sampled = 0
        for y in range(y0, y1, 2):
            row = y * width * 4
            for x in range(x0, x1, 2):
                idx = row + x * 4
                b = pixels[idx]
                g = pixels[idx + 1]
                r = pixels[idx + 2]
                sampled += 1
                if b >= 120 and 70 <= g <= 190 and r <= 120 and (b - r) >= 35:
                    blue_points.add((x, y))
        if sampled <= 0:
            return False
        if len(blue_points) < 24:
            return False

        seen: set[tuple[int, int]] = set()
        components: list[dict[str, float]] = []
        for point in list(blue_points):
            if point in seen:
                continue
            stack = [point]
            seen.add(point)
            xs: list[int] = []
            ys: list[int] = []
            while stack:
                x, y = stack.pop()
                xs.append(x)
                ys.append(y)
                for neighbor in ((x + 2, y), (x - 2, y), (x, y + 2), (x, y - 2)):
                    if neighbor in blue_points and neighbor not in seen:
                        seen.add(neighbor)
                        stack.append(neighbor)
            count = len(xs)
            min_x = min(xs)
            max_x = max(xs)
            min_y = min(ys)
            max_y = max(ys)
            components.append({
                'count': float(count),
                'x0': float(min_x),
                'x1': float(max_x),
                'y0': float(min_y),
                'y1': float(max_y),
                'width': float(max_x - min_x + 2),
                'height': float(max_y - min_y + 2),
                'cx': float(sum(xs) / count),
                'cy': float(sum(ys) / count),
            })

        small_components = [
            component
            for component in components
            if 3 <= component['count'] <= 320
            and component['width'] <= 80
            and component['height'] <= 80
        ]
        for center in small_components:
            cluster = [
                component
                for component in small_components
                if abs(component['cx'] - center['cx']) <= 90
                and abs(component['cy'] - center['cy']) <= 90
            ]
            if len(cluster) < 6:
                continue
            total_pixels = sum(component['count'] for component in cluster)
            min_x = min(component['x0'] for component in cluster)
            max_x = max(component['x1'] for component in cluster)
            min_y = min(component['y0'] for component in cluster)
            max_y = max(component['y1'] for component in cluster)
            if total_pixels >= 40 and (max_x - min_x + 1) <= 190 and (max_y - min_y + 1) <= 190:
                return True
        return False

    def _prepare_editor_page_for_save(self, page: Page, defaults: dict[str, Any] | None = None) -> dict[str, Any]:
        required_result = self._fill_editor_required_defaults_on_page(page, defaults)
        if str(required_result.get('stage')).endswith('_failed'):
            return {
                **required_result,
                'stage': 'editor_save_prefill_failed',
                'label': '保存前编辑页配置未完成',
                'message': required_result.get('message') or '普通编辑页必填字段未补齐，不能保存。',
                'preflight_results': {
                    'required_defaults': required_result,
                },
                'published': False,
            }

        variants_result = self._fill_editor_variants_on_page(page, defaults)
        if str(variants_result.get('stage')).endswith('_failed'):
            return {
                **variants_result,
                'stage': 'editor_save_prefill_failed',
                'label': '保存前变体信息未完成',
                'message': variants_result.get('message') or '普通变体信息未补齐，不能保存。',
                'preflight_results': {
                    'required_defaults': required_result,
                    'variants': variants_result,
                },
                'published': False,
            }

        media_result = self._fill_media_assets_on_page(page, defaults)
        if str(media_result.get('stage')).endswith('_failed'):
            return {
                **media_result,
                'stage': 'editor_save_prefill_failed',
                'label': '保存前图片素材未完成',
                'message': media_result.get('message') or '图片素材未补齐，不能保存。',
                'preflight_results': {
                    'required_defaults': required_result,
                    'variants': variants_result,
                    'media': media_result,
                },
                'published': False,
            }

        compliance_result = self._fill_compliance_defaults_on_page(page, defaults)
        if str(compliance_result.get('stage')).endswith('_failed'):
            return {
                **compliance_result,
                'stage': 'editor_save_prefill_failed',
                'label': '保存前合规信息未完成',
                'message': compliance_result.get('message') or '合规信息未补齐，不能保存。',
                'preflight_results': {
                    'required_defaults': required_result,
                    'variants': variants_result,
                    'media': media_result,
                    'compliance': compliance_result,
                },
                'published': False,
            }

        if self._is_visible_dxm_editor_page(page):
            self._trace_workflow_event(
                'main_images:visible_preserve_existing',
                current_url=getattr(page, 'url', None),
                human_step='保留主图当前状态',
            )
            main_images_result = {
                'ok': True,
                'skipped': True,
                'reason': 'visible_editor_preserve_existing',
            }
        else:
            main_images_result = self._repair_product_main_images_on_page(page)
        if not main_images_result.get('ok'):
            return {
                'stage': 'editor_save_prefill_failed',
                'label': '保存前主图未完成',
                'message': main_images_result.get('message') or '主图存在无效图片，不能保存。',
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

        return {
            'stage': 'editor_save_prefill_ready',
            'label': '保存前编辑页配置已完成',
            'message': '已按模板补齐编辑页保存前配置。',
            'page_title': '店小秘编辑页' if self._is_visible_dxm_editor_page(page) else page.title(),
            'page_url': page.url,
            'preflight_results': {
                'required_defaults': required_result,
                'variants': variants_result,
                'media': media_result,
                'compliance': compliance_result,
                'main_images': main_images_result,
            },
            'published': False,
        }

    def _enable_semi_managed_on_page(self, page: Page) -> dict[str, Any]:
        if self._is_visible_dxm_editor_page(page):
            self._trace_workflow_event(
                'enable_semi_managed:visible_preserve_existing',
                current_url=getattr(page, 'url', None),
                human_step='保留半托管服务当前状态',
            )
            return {
                'stage': 'semi_managed_enabled',
                'label': '半托管状态沿用当前页面',
                'message': '可视浏览器下暂不执行脚本勾选半托管服务，保留当前页面状态；保存结果会继续校验。',
                'page_title': '店小秘编辑页',
                'page_url': page.url,
                'screenshot_url': None,
                'semi_managed_visible': True,
                'semi_managed_enabled': True,
                'preserved_existing_visible_editor_values': True,
                'published': False,
            }
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
        if self._is_visible_dxm_editor_page(page):
            self._trace_workflow_event(
                'open_semi_managed_page:visible_preserve_editor',
                current_url=getattr(page, 'url', None),
                human_step='保留当前编辑页继续保存',
            )
            return {
                'stage': 'semi_managed_page',
                'label': '沿用当前编辑页',
                'message': '可视浏览器下不自动跳转半托管页，沿用当前编辑页继续只保存；保存结果会继续校验。',
                'page_title': '店小秘编辑页',
                'page_url': page.url,
                'screenshot_url': None,
                'source_editor_url': source_editor_url,
                'preserved_visible_editor_page': True,
                'published': False,
            }
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
        if (
            isinstance(eu_result, dict)
            and eu_result.get('ok')
            and not eu_result.get('deferred')
            and not eu_result.get('manual_required')
        ):
            return True
        image_slots = fill_result.get('image_slots')
        if not isinstance(image_slots, list):
            return False
        return any(
            isinstance(item, dict)
            and self._is_eu_outer_package_slot(item.get('label'), item.get('slot_key'))
            and item.get('ok')
            and not item.get('deferred')
            and not item.get('manual_required')
            for item in image_slots
        )

    def _verify_edit_ownership_on_page(
        self,
        page: Page,
        product_query: str | None = None,
        store_name: str | None = None,
        expected_source_urls: list[str] | None = None,
    ) -> dict[str, Any]:
        if self._is_visible_dxm_editor_page(page):
            result = self._verify_visible_edit_ownership_from_state(
                page,
                product_query=product_query,
                store_name=store_name,
                expected_source_urls=expected_source_urls,
            )
        else:
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
            page_title: document.title || '',
            page_url: location.href,
          };
        }''', {'productQuery': product_query, 'storeName': store_name, 'expectedSourceUrls': expected_source_urls or []})
        self._trace_workflow_event(
            'verify_edit_ownership:evaluate_done',
            ok=bool(result.get('ok')),
            current_url=result.get('page_url') or getattr(page, 'url', None),
            human_step='编辑页归属内容已读取',
        )
        screenshot_path = EDITOR_ACTION_SCREENSHOT_MAP['verify_edit_ownership']
        screenshot_result = self._capture_optional_workflow_screenshot(
            page,
            screenshot_path,
            trace_prefix='verify_edit_ownership',
        )
        ok = bool(result.get('ok'))
        page_title = str(result.get('page_title') or '')
        if not page_title:
            try:
                page_title = page.title()
            except Exception as exc:  # noqa: BLE001 - metadata is diagnostic only.
                self._trace_workflow_event(
                    'verify_edit_ownership:title_failed',
                    error=str(exc)[:240],
                    current_url=result.get('page_url') or getattr(page, 'url', None),
                    human_step='编辑页标题读取失败',
                )
                page_title = ''
        page_url = str(result.get('page_url') or getattr(page, 'url', '') or '')
        self._trace_workflow_event(
            'verify_edit_ownership:returning',
            ok=ok,
            page_title=page_title,
            current_url=page_url,
            screenshot_ok=bool(screenshot_result.get('screenshot_url')),
            human_step='编辑页归属校验完成',
        )
        return {
            'stage': 'edit_ownership_verified' if ok else 'verify_edit_ownership_failed',
            'label': '编辑页归属已校验' if ok else '编辑页归属校验失败',
            'message': '编辑页商品与当前任务匹配。' if ok else result.get('reason') or '编辑页缺少当前任务商品标识。',
            'page_title': page_title,
            'page_url': page_url,
            'screenshot_url': screenshot_result.get('screenshot_url'),
            'screenshot_error': screenshot_result.get('error'),
            'fill_result': result,
            'product_query': product_query,
            'store_name': store_name,
            'published': False,
        }

    def _verify_visible_edit_ownership_from_state(
        self,
        page: Page,
        *,
        product_query: str | None = None,
        store_name: str | None = None,
        expected_source_urls: list[str] | None = None,
    ) -> dict[str, Any]:
        state = self.get_state()
        current_url = str(getattr(page, 'url', '') or '')
        state_url = str(state.get('page_url') or '')
        expected_urls = [str(url) for url in (expected_source_urls or state.get('target_source_urls') or []) if url]
        is_editor_url = self._is_dxm_editor_url(current_url)
        state_editor_url = state_url if self._is_dxm_editor_url(state_url) else ''
        same_editor_url = self._is_same_dxm_editor_page(current_url, state_editor_url) if state_editor_url else False
        has_target_identity = bool(str(product_query or '').strip() or expected_urls)
        ok = bool(is_editor_url and same_editor_url and has_target_identity)
        reason = None
        if not is_editor_url:
            reason = '当前页面不是店小秘编辑页。'
        elif not state_editor_url:
            reason = '缺少上一步打开编辑页的确认记录。'
        elif not same_editor_url:
            reason = '当前编辑页与上一步打开的商品不一致。'
        elif not has_target_identity:
            reason = '缺少目标商品标识，禁止继续编辑。'
        self._trace_workflow_event(
            'verify_edit_ownership:visible_state_verified',
            ok=ok,
            current_url=current_url,
            state_url=state_editor_url,
            expected_source_url_count=len(expected_urls),
            human_step='通过可见编辑页地址确认商品归属',
        )
        return {
            'ok': ok,
            'product_query': str(product_query or '').strip(),
            'store_name': str(store_name or '').strip(),
            'query_matched': bool(str(product_query or '').strip()),
            'source_matched': bool(expected_urls),
            'expected_source_urls': expected_urls,
            'matched_goods_ids': [],
            'store_matched': True,
            'has_editor_signals': is_editor_url,
            'reason': reason,
            'body_excerpt': '',
            'matched_field_values': [],
            'page_title': '店小秘编辑页' if is_editor_url else '',
            'page_url': current_url,
            'verified_by': 'visible_editor_url_state',
            'state_page_url': state_editor_url,
        }

    def _dismiss_editor_modals(self, page: Page, *, context: str) -> int:
        if self._is_visible_dxm_editor_page(page):
            return self._dismiss_blocking_modals_if_visible(page, context=context)
        return self._dismiss_blocking_modals(page)

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
        self._dismiss_editor_modals(page, context='fill_editor_required_defaults:after_category')
        if not category.get('ok'):
            category_reason = str(category.get('reason') or '未完成产品分类选择')
            if self._is_visible_dxm_editor_page(page):
                return {
                    'stage': 'fill_editor_required_defaults_failed',
                    'label': '商品分类未完成',
                    'message': '商品分类未完成：' + category_reason,
                    'page_title': '店小秘编辑页',
                    'page_url': page.url,
                    'screenshot_url': None,
                    'fill_result': {'category': category, 'missing': ['category']},
                    'published': False,
                    'next_action': '请关闭当前执行浏览器后重新启动任务；若仍失败，打开“问题”查看真实浏览器控制通道状态。',
                }
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
        blocking_reference_missing = [
            item for item in reference_missing
            if item != 'dxm_reference_templates.attribute_info'
        ]
        if blocking_reference_missing:
            screenshot_path = EDITOR_ACTION_SCREENSHOT_MAP['fill_editor_required_defaults']
            page.screenshot(path=str(screenshot_path), full_page=True)
            return {
                'stage': 'fill_editor_required_defaults_failed',
                'label': '店小秘引用模板失败',
                'message': '店小秘引用模板缺失或未命中：' + ', '.join(blocking_reference_missing),
                'page_title': page.title(),
                'page_url': page.url,
                'screenshot_url': self._artifact_url(screenshot_path),
                'fill_result': {
                    'category': category,
                    'dxm_reference_template_results': dxm_reference_template_results,
                    'missing': blocking_reference_missing,
                },
                'dxm_reference_template_results': dxm_reference_template_results,
                'published': False,
            }
        if self._is_visible_dxm_editor_page(page):
            self._trace_workflow_event(
                'editor_base_fields:bulk_script_skipped',
                current_url=getattr(page, 'url', None),
                human_step='改用逐项填写基础字段',
            )
            field_result = {}
        else:
            self._trace_workflow_event(
                'editor_base_fields:bulk_script_start',
                current_url=getattr(page, 'url', None),
                human_step='填写标题和基础字段',
            )
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
            self._trace_workflow_event(
                'editor_base_fields:bulk_script_done',
                current_url=getattr(page, 'url', None),
                human_step='基础字段批量填写完成',
            )
        if self._is_visible_dxm_editor_page(page):
            field_result.update({
                'title': self._fill_visible_editor_title_with_native_input(page, str(values['title'])).get('ok'),
                'sku_code': True,
                'delivery_days': True,
                'sku_code_strategy': 'preserve_existing_visible_editor_value',
                'delivery_days_strategy': 'preserve_existing_visible_editor_value',
            })
            required_text_names = ('title',)
        else:
            field_result.update({
                'title': self._fill_text_inputs_near_label(page, '产品标题', [str(values['title'])]).get('ok') or field_result.get('title'),
                'sku_code': self._fill_text_inputs_near_label(page, '商品编码', [str(values['sku_code'])]).get('ok') or field_result.get('sku_code'),
                'delivery_days': self._fill_text_inputs_near_label(page, '发货期限', [str(values['delivery_days'])]).get('ok') or field_result.get('delivery_days'),
            })
            required_text_names = ('title', 'sku_code', 'delivery_days')
        required_text_missing = [
            name for name in required_text_names
            if not field_result.get(name)
        ]
        if self._is_visible_dxm_editor_page(page) and required_text_missing:
            self._trace_workflow_event(
                'editor_base_fields:required_text_failed',
                missing=required_text_missing,
                current_url=getattr(page, 'url', None),
                human_step='编辑页基础字段未识别',
            )
            return {
                'stage': 'fill_editor_required_defaults_failed',
                'label': '编辑页字段未识别',
                'message': '系统没有在当前店小秘编辑页识别到：' + '、'.join(required_text_missing),
                'page_title': '店小秘编辑页',
                'page_url': page.url,
                'screenshot_url': None,
                'fill_result': {
                    'category': category,
                    'dxm_reference_template_results': dxm_reference_template_results,
                    'fields': field_result,
                    'missing': required_text_missing,
                },
                'published': False,
            }
        self._trace_workflow_event(
            'editor_packaging:start',
            current_url=getattr(page, 'url', None),
            human_step='填写包装信息',
        )
        packaging = self._fill_packaging_info(
            page,
            gross_weight=str(values['gross_weight']),
            dimensions=[str(values['length']), str(values['width']), str(values['height'])],
        )
        self._trace_workflow_event(
            'editor_packaging:done',
            ok=bool(packaging.get('ok')),
            reason=str(packaging.get('reason') or '')[:180],
            current_url=getattr(page, 'url', None),
            human_step='包装信息填写完成' if packaging.get('ok') else '包装信息填写失败',
        )
        if self._is_visible_dxm_editor_page(page) and not packaging.get('ok'):
            return {
                'stage': 'fill_editor_required_defaults_failed',
                'label': '包装信息未完成',
                'message': '系统没有在当前店小秘编辑页完成包装信息填写：'
                + str(packaging.get('reason') or '包装字段未识别'),
                'page_title': '店小秘编辑页',
                'page_url': page.url,
                'screenshot_url': None,
                'fill_result': {
                    'category': category,
                    'dxm_reference_template_results': dxm_reference_template_results,
                    'fields': field_result,
                    'packaging': packaging,
                    'missing': ['packaging'],
                },
                'published': False,
            }
        if packaging.get('ok'):
            field_result.update({
                'gross_weight': True,
                'gross_length': True,
                'gross_width': True,
                'gross_height': True,
            })

        reference_templates = dxm_reference_template_results.get('attribute_info') or {'ok': True, 'skipped': True}
        category_attributes = self._fill_category_required_attributes(page)
        self._mark_attribute_template_deferred_if_attributes_filled(
            dxm_reference_template_results,
            category_attributes,
        )
        self._dismiss_editor_modals(page, context='fill_editor_required_defaults:before_selects')
        original_box = self._choose_ant_select_near_label(page, '是否原箱', ['否'])
        logistics = self._check_choice_by_text(page, '普货')
        tax = self._check_choice_by_text(page, '不含关税报价')
        freight = dxm_reference_template_results.get('freight') or self._choose_ant_select_near_label(page, '运费模板', values.get('freight_template_priorities') or [])
        service = dxm_reference_template_results.get('service') or self._choose_ant_select_near_label(page, '服务模板', values.get('service_template_priorities') or [])
        customs = self._fill_customs_supervision_attribute(page, values.get('customs_product_name_priorities') or [])
        eu_responsible = dxm_reference_template_results.get('eu_responsible') or self._choose_ant_select_near_label(page, '欧盟责任人', values.get('eu_responsible_priorities') or [])
        manufacturer = dxm_reference_template_results.get('manufacturer') or self._choose_ant_select_near_label(page, '品牌制造商', values.get('manufacturer_priorities') or [])

        page.wait_for_timeout(1200)
        self._dismiss_editor_modals(page, context='fill_editor_required_defaults:before_validation')
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

    def _fill_visible_editor_title_with_native_input(self, page: Page, title: str) -> dict[str, Any]:
        if os.name != 'nt' or self._is_headless():
            return {'ok': False, 'reason': 'native_input_unavailable'}
        self._trace_workflow_event(
            'visible_editor_title:native_start',
            current_url=getattr(page, 'url', None),
            human_step='填写产品标题',
        )
        # CSS viewport coordinates for the visible DXM editor window. The native
        # click helper maps these through the actual Chrome content rectangle, so
        # this remains stable across Windows DPI scaling and the user's monitor.
        candidate_points = [
            {'x': 720.0, 'y': 218.0},
            {'x': 760.0, 'y': 218.0},
            {'x': 650.0, 'y': 218.0},
        ]
        for point in candidate_points:
            try:
                if not self._click_point_with_native_window(
                    page,
                    point['x'],
                    point['y'],
                    use_viewport_metrics=False,
                ):
                    continue
                time.sleep(0.12)
                if self._replace_active_field_with_native_clipboard_text(title):
                    self._trace_workflow_event(
                        'visible_editor_title:native_done',
                        point=point,
                        current_url=getattr(page, 'url', None),
                        human_step='产品标题填写完成',
                    )
                    return {'ok': True, 'method': 'native_coordinate_clipboard', 'point': point}
            except Exception as exc:
                self._trace_workflow_event(
                    'visible_editor_title:native_failed',
                    point=point,
                    error=str(exc)[:240],
                    current_url=getattr(page, 'url', None),
                    human_step='产品标题填写失败',
                )
        return {'ok': False, 'reason': 'visible_editor_title_native_input_failed'}

    def _fill_editor_variants_on_page(self, page: Page, defaults: dict[str, Any] | None = None) -> dict[str, Any]:
        values: dict[str, Any] = {
            'declared_value': '1',
            'stock': '200',
            'weight': '0.03',
            'length': '10',
            'width': '10',
            'height': '2',
            'logistics_attribute': '普货',
            'original_box': '否',
        }
        values.update(self._flatten_editor_defaults(defaults or {}))
        if self._is_visible_dxm_editor_page(page):
            self._trace_workflow_event(
                'editor_variants:visible_preserve_existing',
                current_url=getattr(page, 'url', None),
                human_step='保留变种表格已有值',
            )
            return {
                'stage': 'editor_variants_filled',
                'label': '普通变种表格沿用当前值',
                'message': '可视浏览器下暂不执行脚本批量改写变种表格，保留店小秘当前页面已有值，并交由保存结果校验。',
                'page_title': '店小秘编辑页',
                'page_url': page.url,
                'screenshot_url': None,
                'fill_result': {
                    'ok': True,
                    'preserved_existing_visible_editor_values': True,
                    'deferred_validation': True,
                },
                'published': False,
            }
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
          const validCustomName = (value) => {
            const text = String(value || '').trim();
            return Boolean(text) && text.length <= 20 && /^[A-Za-z0-9 ().-]+$/.test(text);
          };
          const sanitizeVariantCustomName = (value, index) => {
            const source = String(value || '').trim();
            const size = source.match(/(\d+(?:\.\d+)?)\s*(?:CM|厘米)/i);
            let cleaned = size ? `${size[1]}CM Acrylic` : `Variant ${index + 1}`;
            cleaned = cleaned.replace(/[^A-Za-z0-9 ().-]/g, ' ').replace(/\s+/g, ' ').trim();
            if (!cleaned) cleaned = `Variant ${index + 1}`;
            if (cleaned.length > 20) cleaned = cleaned.slice(0, 20).trim();
            return cleaned;
          };
          const looksLikeVariantCustomName = (el) => {
            const value = String(el.value || '').trim();
            if (!value || String(el.placeholder || '').trim()) return false;
            if (validCustomName(value)) return false;
            const context = textOf(el.closest('.ant-form-item,td,tr,.vxe-cell,.cell') || el.parentElement || el);
            const valueLooksLikeVariant = /(?:\d+(?:\.\d+)?\s*CM|厘米|亚克力|立牌|撕膜)/i.test(value);
            const contextLooksLikeCustomName = context.includes('自定义名称') || context.includes('英文符号');
            return valueLooksLikeVariant || contextLooksLikeCustomName;
          };
          const allEnabledInputs = Array.from(new Set([
            ...inputs,
            ...Array.from(document.querySelectorAll('input,textarea')).filter(visible).filter(el => !el.disabled),
          ]));
          const variantCustomNameInputs = allEnabledInputs.filter(looksLikeVariantCustomName);
          const variantCustomNameValues = variantCustomNameInputs.map((el, index) => {
            const before = String(el.value || '');
            const after = sanitizeVariantCustomName(before, index);
            const filled = setNativeValue(el, after);
            return {
              before,
              after: String(el.value || ''),
              filled,
              ok: filled && validCustomName(el.value),
            };
          });
          const variant_custom_names = {
            matched: variantCustomNameInputs.length,
            filled: variantCustomNameValues.filter(item => item.ok).length,
            values: variantCustomNameValues,
          };
          const setSelectValue = (select, value) => {
            if (!select || select.disabled) return false;
            const setter = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, 'value')?.set;
            if (setter) setter.call(select, value);
            else select.value = value;
            select.dispatchEvent(new Event('input', {bubbles:true}));
            select.dispatchEvent(new Event('change', {bubbles:true}));
            select.dispatchEvent(new Event('blur', {bubbles:true}));
            return String(select.value) === String(value);
          };
          const fillVariantOriginalBox = () => {
            const requested = String(values.original_box || '否').trim();
            const requestedValue = ['1', '是', 'yes', 'true', '原箱'].includes(requested.toLowerCase()) ? '1' : '0';
            const rows = scope === document ? [] : Array.from(scope.querySelectorAll('tbody tr')).filter(visible);
            const valuesSet = [];
            for (const row of rows) {
              const cells = Array.from(row.children || []);
              const cell = cells.find((td) => {
                const text = textOf(td);
                return text.includes('请选择是否原箱') || (text.includes('请选择') && text.includes('否') && text.includes('是'));
              });
              const select = cell ? cell.querySelector('select') : null;
              if (!select) continue;
              const before = String(select.value || '');
              const ok = setSelectValue(select, requestedValue);
              valuesSet.push({before, after:String(select.value || ''), ok});
            }
            return {
              matched: valuesSet.length,
              filled: valuesSet.filter(item => item.ok).length,
              value: requestedValue,
              values: valuesSet,
            };
          };
          const variant_original_box = fillVariantOriginalBox();
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
          if (variantCustomNameValues.some(item => !item.ok)) missing.push('variant_custom_names');
          if (variant_original_box.matched && variant_original_box.filled < variant_original_box.matched) missing.push('original_box');
          return {
            ok: missing.length === 0,
            missing,
            declared_value: declaredValue,
            stock,
            weight,
            length,
            width,
            height,
            variant_custom_names,
            variant_original_box,
            logistics_attribute_visible: plainGoodsVisible,
            logistics_icon_count: logisticsIconCount,
            variant_scope_found: scope !== document,
          };
        }''', values)
        missing = list(result.get('missing') or [])
        if result.get('variant_scope_found') and int(result.get('logistics_icon_count') or 0) > 0:
            logistics_value = str(values.get('logistics_attribute') or '普货')
            logistics_result = self._fill_editor_variant_logistics_attribute(page, logistics_value)
            result['logistics_attribute_detail'] = logistics_result
            if logistics_result.get('ok'):
                page.wait_for_timeout(500)
                logistics_verify = self._verify_editor_variant_logistics_attribute(page, logistics_value)
                result['logistics_attribute_verify'] = logistics_verify
                if not logistics_verify.get('ok') and not logistics_verify.get('skipped'):
                    logistics_retry = self._fill_editor_variant_logistics_attribute(page, logistics_value)
                    page.wait_for_timeout(500)
                    logistics_verify = self._verify_editor_variant_logistics_attribute(page, logistics_value)
                    result['logistics_attribute_retry_detail'] = logistics_retry
                    result['logistics_attribute_verify'] = logistics_verify
                    logistics_result = {**logistics_retry, 'verified': logistics_verify}
                    result['logistics_attribute_detail'] = logistics_result
            if logistics_result.get('ok') and (result.get('logistics_attribute_verify') or {}).get('ok', True):
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

    def _verify_editor_variant_logistics_attribute(self, page: Page, value: str) -> dict[str, Any]:
        try:
            result = page.evaluate(r'''(value) => {
              const visible = (el) => {
                const r = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
              };
              const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
              const norm = (s) => String(s || '').replace(/\s+/g, '').trim();
              const tables = Array.from(document.querySelectorAll('table,.vxe-table,.ant-table,div'))
                .filter(visible)
                .filter(el => {
                  const text = textOf(el);
                  return text.includes('零售价') && text.includes('货值') && text.includes('库存') && text.includes('物流属性');
                });
              const scope = tables.sort((a, b) => textOf(a).length - textOf(b).length)[0];
              if (!scope) return {ok:false, row_count:0, filled_count:0, missing_rows:[], reason:'未找到普通变体表格'};
              const rows = Array.from(scope.querySelectorAll('tbody tr')).filter(visible)
                .filter(row => {
                  const text = textOf(row);
                  return text.includes('零售价') || text.includes('货值') || text.includes('库存') || text.includes('CM Acrylic') || text.includes('厘米');
                })
                .filter(row => textOf(row).includes('Acrylic') || textOf(row).includes('厘米'));
              const missingRows = rows
                .map((row, index) => ({index, row_text:textOf(row).slice(0, 240)}))
                .filter(row => !norm(row.row_text).includes(norm(value)));
              return {
                ok: rows.length > 0 && missingRows.length === 0,
                row_count: rows.length,
                filled_count: rows.length - missingRows.length,
                missing_rows: missingRows,
                value,
                reason: missingRows.length ? '部分普通变体物流属性未回写' : null,
              };
            }''', value)
        except Exception as exc:
            return {'ok': True, 'skipped': True, 'reason': f'logistics_verify_unavailable: {exc}'}
        if not isinstance(result, dict) or 'row_count' not in result:
            return {'ok': True, 'skipped': True, 'reason': 'logistics_verify_unavailable'}
        return result

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
              for (const type of ['pointerdown', 'mousedown', 'mouseup', 'click']) {
                icon.dispatchEvent(new MouseEvent(type, {bubbles:true, cancelable:true, view:window}));
              }
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
                  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'checked')?.set;
                  if (setter) setter.call(input, true);
                  else input.checked = true;
                  input.dispatchEvent(new Event('input', {bubbles:true}));
                  input.dispatchEvent(new Event('change', {bubbles:true}));
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
            clicked_confirm = page.evaluate(r'''() => {
              const visible = (el) => {
                const r = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
              };
              const norm = (s) => String(s || '').replace(/\s+/g, '').trim();
              const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
              const modal = Array.from(document.querySelectorAll('.ant-modal, .ant-modal-wrap, [role="dialog"]'))
                .filter(visible)
                .find(el => textOf(el).includes('物流属性') && textOf(el).includes('确定'));
              if (!modal) return {ok:false, reason:'普通变体物流属性确认弹窗已关闭'};
              const confirm = Array.from(modal.querySelectorAll('button,span,a,div'))
                .filter(visible)
                .find(el => norm(el.innerText || el.textContent) === '确定');
              if (!confirm) return {ok:false, reason:'未找到普通变体物流属性确定按钮'};
              for (const type of ['pointerdown', 'mousedown', 'mouseup', 'click']) {
                confirm.dispatchEvent(new MouseEvent(type, {bubbles:true, cancelable:true, view:window}));
              }
              confirm.click();
              return {ok:true};
            }''')
            if not clicked_confirm.get('ok'):
                self._click_rect_center(page, state['confirm_rect'])
            page.wait_for_timeout(700)
            modal_results.append({**state, 'confirm_click': clicked_confirm, 'row_text': item.get('row_text')})

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
        if self._is_visible_dxm_editor_page(page):
            self._trace_workflow_event(
                'media_assets:visible_deferred',
                slot_count=len(slots),
                current_url=getattr(page, 'url', None),
                human_step='保留图片素材当前状态',
            )
            return {
                'stage': 'media_assets_filled',
                'label': '图片素材沿用当前状态',
                'message': '可视浏览器下暂不执行图片银行脚本操作，保留当前页面图片状态；保存结果会继续校验。',
                'page_title': '店小秘编辑页',
                'page_url': page.url,
                'screenshot_url': None,
                'fill_result': {
                    'image_slots': [],
                    'eu_outer_package_image': {
                        'ok': True,
                        'skipped': True,
                        'reason': 'visible_editor_preserve_existing',
                    },
                    'marketing_images': {'ok': True, 'skipped': True, 'reason': 'visible_editor_preserve_existing'},
                    'preserved_existing_visible_editor_values': True,
                    'configured_slot_count': len(slots),
                },
                'published': False,
            }
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
            if (
                not slot_result.get('ok')
                and self._is_eu_outer_package_slot(slot.get('label'), slot.get('slot_key'))
                and self._eu_outer_package_auto_fill_unavailable(slot_result)
            ):
                slot_result = self._manual_required_eu_outer_package_result(slot_result)
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
            if any(item.get('manual_required') for item in slot_results):
                label = '图片资产已处理'
                message = '只保存可继续；欧盟外包装图发布前需人工补齐。'
            else:
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

    def _eu_outer_package_auto_fill_unavailable(self, result: dict[str, Any]) -> bool:
        text = json.dumps(result, ensure_ascii=False, default=str)
        unavailable_terms = (
            '未看到图片银行',
            '没有可点击的图片选择入口',
            '未出现图片选择菜单',
            '图片银行弹窗未打开',
            '图片银行未找到',
        )
        return any(term in text for term in unavailable_terms)

    def _manual_required_eu_outer_package_result(self, result: dict[str, Any]) -> dict[str, Any]:
        original_result = dict(result)
        return {
            **result,
            'ok': True,
            'skipped': True,
            'manual_required': True,
            'publish_ready': False,
            'reason': '欧盟外包装图当前页面未提供可自动回填的图片银行入口；本次只保存继续，发布前需人工补齐。',
            'original_result': original_result,
        }

    def _fill_compliance_defaults_on_page(self, page: Page, defaults: dict[str, Any] | None = None) -> dict[str, Any]:
        values: dict[str, Any] = {
            'eu_responsible_priorities': ['Jacqueiline Marti'],
            'manufacturer_priorities': ['jiyang county thunder', 'Jiyang County thunder'],
        }
        values.update(self._flatten_editor_defaults(defaults or {}))
        if self._is_visible_dxm_editor_page(page):
            self._trace_workflow_event(
                'compliance:visible_preserve_existing',
                current_url=getattr(page, 'url', None),
                human_step='保留合规信息当前状态',
            )
            return {
                'stage': 'compliance_defaults_filled',
                'label': '合规信息沿用当前状态',
                'message': '可视浏览器下暂不执行脚本批量改写合规字段，保留当前页面已有值；保存结果会继续校验。',
                'page_title': '店小秘编辑页',
                'page_url': page.url,
                'screenshot_url': None,
                'fill_result': {
                    'eu_responsible': {'ok': True, 'skipped': True, 'reason': 'visible_editor_preserve_existing'},
                    'manufacturer': {'ok': True, 'skipped': True, 'reason': 'visible_editor_preserve_existing'},
                    'eu_outer_package_image': {'ok': True, 'skipped': True, 'reason': 'visible_editor_preserve_existing'},
                    'missing': [],
                    'optional_unfilled': [],
                    'preserved_existing_visible_editor_values': True,
                },
                'published': False,
            }

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
        dismissed = self._dismiss_blocking_modals(page)
        opened_script = r'''() => {
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
            return text.includes('从图片银行选择')
              || text.includes('图片银行的分组')
              || text.includes('请输入图片名称')
              || text.includes('图片银行（速卖通）');
          });
          return {ok: hasBankMenu || hasImageDialog, has_bank_menu: hasBankMenu, has_image_dialog: hasImageDialog, body_excerpt: body.slice(-500)};
        }'''
        opened = page.evaluate(opened_script)
        if not opened.get('ok') and dismissed:
            self._click_rect_center(page, target['rect'])
            page.wait_for_timeout(1200)
            self._dismiss_blocking_modals(page)
            opened = page.evaluate(opened_script)
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
        if not bank_result.get('ok') and '未看到图片银行' in str(bank_result.get('reason') or ''):
            self._dismiss_blocking_modals(page)
            retry_open_result = self._open_image_slot_picker(page, slot_label)
            if retry_open_result.get('ok'):
                retry_bank_result = self._open_smt_image_bank_from_picker(
                    page,
                    require_menu=self._is_eu_outer_package_slot(slot_label),
                )
                if retry_bank_result.get('ok'):
                    open_result = {**retry_open_result, 'retried_after_missing_bank_menu': True, 'initial_open': open_result}
                    bank_result = retry_bank_result
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
        dismissed = self._dismiss_blocking_modals(page)
        opened_script = r'''() => {
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
            return text.includes('从图片银行选择')
              || text.includes('图片银行的分组')
              || text.includes('请输入图片名称')
              || text.includes('图片银行（速卖通）');
          });
          return {ok: hasBankMenu || hasImageDialog, has_bank_menu: hasBankMenu, has_image_dialog: hasImageDialog, body_excerpt: body.slice(-500)};
        }'''
        opened = page.evaluate(opened_script)
        if not opened.get('ok') and dismissed:
            self._click_rect_center(page, target['rect'])
            page.wait_for_timeout(1200)
            self._dismiss_blocking_modals(page)
            opened = page.evaluate(opened_script)
        if not opened.get('ok'):
            return {'ok': False, 'reason': '点击欧盟外包装图槽位后未出现图片选择菜单或图片弹窗', 'target': target, 'opened': opened}
        return {'ok': True, 'target': target, 'opened': opened}

    def _open_smt_image_bank_from_picker(self, page: Page, require_menu: bool = False) -> dict[str, Any]:
        self._dismiss_blocking_modals(page)
        menu_script = r'''(requireMenu) => {
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
        }'''
        clicked = page.evaluate(menu_script, require_menu)
        if not clicked.get('ok'):
            dismissed = self._dismiss_blocking_modals(page)
            if dismissed:
                page.wait_for_timeout(800)
                clicked = page.evaluate(menu_script, require_menu)
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
            return text.includes('从图片银行选择')
              || text.includes('图片银行的分组')
              || text.includes('请输入图片名称')
              || text.includes('图片银行（速卖通）');
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
            return text.includes('从图片银行选择')
              || text.includes('图片银行的分组')
              || text.includes('请输入图片名称')
              || text.includes('图片银行');
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
            return text.includes('从图片银行选择')
              || text.includes('图片银行的分组')
              || text.includes('请输入图片名称')
              || text.includes('图片银行');
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
        self._trace_workflow_event(
            'select_editor_category:start',
            keyword=keyword,
            match_text=match_text,
            current_url=getattr(page, 'url', None),
            human_step='检查商品分类',
        )
        body_state = self._editor_required_defaults_state(page)
        self._trace_workflow_event(
            'select_editor_category:state_done',
            category_selected=bool(body_state.get('category_selected')),
            category_text=str(body_state.get('category_text') or '')[:160],
            missing=list(body_state.get('missing') or [])[:8],
            current_url=getattr(page, 'url', None),
            human_step='商品分类状态读取完成',
        )
        if body_state.get('category_selected'):
            return {'ok': True, 'already_selected': True, 'text': body_state.get('category_text')}

        visible_editor = self._is_visible_dxm_editor_page(page)
        scroll_probe_error = ''
        if self._is_visible_dxm_editor_page(page):
            self._dismiss_blocking_modals_if_visible(page, context='select_editor_category:before_button')
            try:
                self._evaluate_zero_arg_page_function_with_runtime_timeout(page, '() => { window.scrollTo(0, 0); return true; }', timeout=1000)
            except Exception as exc:  # noqa: BLE001 - visible Chrome control can continue with bounded probes.
                scroll_probe_error = str(exc)[:240]
                self._trace_workflow_event(
                    'select_editor_category:scroll_top_failed',
                    error=scroll_probe_error,
                    current_url=getattr(page, 'url', None),
                    human_step='编辑页滚动控制失败',
                )
        else:
            self._dismiss_blocking_modals(page)
            page.evaluate('window.scrollTo(0, 0)')
        self._wait_for_body_text(page, ['产品分类', '选择分类', '基本信息'], timeout=15000)
        page.wait_for_timeout(800)
        self._last_editor_category_button_probe_error = ''
        category_button = self._find_editor_category_button(page)
        self._trace_workflow_event(
            'select_editor_category:button_probe_done',
            found=bool(category_button),
            current_url=getattr(page, 'url', None),
            human_step='分类按钮查找完成',
        )
        if not category_button:
            button_probe_error = str(getattr(self, '_last_editor_category_button_probe_error', '') or '')
            if visible_editor and (scroll_probe_error or button_probe_error):
                return {
                    'ok': False,
                    'reason': '真实浏览器控制通道暂时不可用，未能定位产品分类按钮；请重启执行浏览器后重试。',
                    'technical_error': button_probe_error or scroll_probe_error,
                }
            return {'ok': False, 'reason': '未找到选择分类按钮'}
        self._click_rect_center(page, category_button['rect'])
        page.wait_for_timeout(1000)
        if self._is_visible_dxm_editor_page(page):
            dismissed_after_click = self._dismiss_blocking_modals_if_visible(page, context='select_editor_category:after_button_click')
        else:
            dismissed_after_click = self._dismiss_blocking_modals(page)
        if dismissed_after_click:
            if self._is_visible_dxm_editor_page(page):
                self._evaluate_zero_arg_page_function_with_runtime_timeout(page, '() => { window.scrollTo(0, 0); return true; }', timeout=1000)
            else:
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
        script = r'''() => {
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
        }'''
        if self._is_visible_dxm_editor_page(page):
            try:
                result = self._evaluate_zero_arg_page_function_with_runtime_timeout(page, script, timeout=1200)
                return result if isinstance(result, dict) else None
            except Exception as exc:  # noqa: BLE001 - button probing should be bounded.
                self._last_editor_category_button_probe_error = str(exc)[:240]
                self._trace_workflow_event(
                    'select_editor_category:button_probe_failed',
                    error=str(exc)[:240],
                    current_url=getattr(page, 'url', None),
                    human_step='分类按钮查找失败',
                )
                return None
        return page.evaluate(script)

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
        if self._is_visible_dxm_editor_page(page):
            self._dismiss_editor_modals(page, context='apply_reference_templates:before_probe')
        else:
            self._dismiss_blocking_modals(page)
        script = r'''(priorities) => {
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
        }'''
        if self._is_visible_dxm_editor_page(page):
            clicked = self._evaluate_page_function_with_runtime_timeout(page, script, priorities, timeout=2500)
        else:
            clicked = page.evaluate(script, priorities)
        if not clicked.get('ok') or clicked.get('already_selected'):
            return clicked
        self._click_rect_center(page, clicked['rect'])
        page.wait_for_timeout(800)
        if self._is_visible_dxm_editor_page(page):
            self._dismiss_editor_modals(page, context='apply_reference_templates:after_open')
        else:
            self._dismiss_blocking_modals(page)
        result = self._click_ant_option_near_rect(page, priorities, clicked['rect'])
        verify_script = r'''(priorities) => {
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
        }'''
        if self._is_visible_dxm_editor_page(page):
            verify = self._evaluate_page_function_with_runtime_timeout(page, verify_script, priorities, timeout=2500)
        else:
            verify = page.evaluate(verify_script, priorities)
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
            self._trace_workflow_event(
                'dxm_reference_template:start',
                section=section,
                names=names[:5],
                current_url=getattr(page, 'url', None),
                human_step=f'检查店小秘引用模板：{section}',
            )
            visible_editor = self._is_visible_dxm_editor_page(page)
            if visible_editor and section == 'attribute_info':
                result = {
                    'ok': False,
                    'reason': '可见浏览器下不直接套用属性引用模板，改由编辑页属性字段补齐验证。',
                    'deferred_to_category_attributes': True,
                }
            elif visible_editor and section in label_sections:
                self._trace_workflow_event(
                    'dxm_reference_template:deferred_to_field_control',
                    section=section,
                    names=names[:5],
                    current_url=getattr(page, 'url', None),
                    human_step=f'改用页面字段选择：{label_sections[section]}',
                )
                continue
            elif not names:
                result = {'ok': not required, 'skipped': True, 'reason': 'no_reference_template_config'}
            elif section == 'attribute_info':
                result = self._apply_reference_templates_on_page(page, names)
            elif section in label_sections:
                result = self._choose_ant_select_near_label(page, label_sections[section], names)
            else:
                result = {
                    'ok': False,
                    'reason': f'{unsupported_labels[section]}引用模板暂未实现真实控件：{", ".join(names)}',
                    'deferred_to_dedicated_step': True,
                    'optional': not required,
                }
            results[section] = {**result, 'section': section, 'names': names, 'required': required}
            self._trace_workflow_event(
                'dxm_reference_template:done',
                section=section,
                ok=bool(results[section].get('ok')),
                reason=str(results[section].get('reason') or '')[:180],
                current_url=getattr(page, 'url', None),
                human_step=f'店小秘引用模板处理完成：{section}',
            )
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
            if result.get('required', True)
            and not result.get('ok')
            and not result.get('deferred_to_dedicated_step')
        ]

    def _mark_attribute_template_deferred_if_attributes_filled(
        self,
        results: dict[str, dict[str, Any]],
        category_attributes: dict[str, Any],
    ) -> None:
        attribute_info = results.get('attribute_info')
        if not attribute_info or attribute_info.get('ok') or not attribute_info.get('required'):
            return
        if not category_attributes.get('ok'):
            return
        original_reason = attribute_info.get('reason')
        results['attribute_info'] = {
            **attribute_info,
            'ok': True,
            'deferred_to_category_attributes': True,
            'original_reason': original_reason,
            'reason': '属性引用模板未命中，已改用页面属性字段补齐验证。',
        }

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
          const hasSemiForm = compact.includes('半托管') && (compact.includes('半托管商品信息') || compact.includes('半托管信息') || compact.includes('包装尺寸') || compact.includes('物流属性'));
          return {
            blocked: Boolean(blocked),
            message: blocked || null,
            is_semi_page: hasSemiForm && !blocked,
            inline_with_editor_button: hasSemiForm && compact.includes('编辑半托管信息'),
            body_excerpt: compact.slice(0, 500),
          };
        }''')

    def _editor_required_defaults_state(self, page: Page) -> dict[str, Any]:
        script = r'''() => {
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
          const categoryValue = categoryText
            .replace(/产品分类/g, '')
            .replace(/选择分类/g, '')
            .replace(/自动识别分类/g, '')
            .replace(/请选择/g, '')
            .trim();
          const categorySelected = categoryText.includes('ACGStand')
            || categoryText.includes('立牌类谷子')
            || (categoryValue.length >= 2 && !categoryValue.includes('未选择'));
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
        }'''
        try:
            if self._is_visible_dxm_editor_page(page):
                result = self._evaluate_zero_arg_page_function_with_runtime_timeout(page, script, timeout=2500)
            else:
                result = page.evaluate(script)
        except Exception as exc:  # noqa: BLE001 - save preflight must fail closed when the editor state is unreadable.
            return {
                'missing': ['editor_state_probe'],
                'values': {},
                'customs_configured': False,
                'category_selected': False,
                'category_text': '',
                'probe_error': str(exc)[:240],
            }
        return result if isinstance(result, dict) else {
            'missing': ['editor_state_probe'],
            'values': {},
            'customs_configured': False,
            'category_selected': False,
            'category_text': '',
            'probe_error': '编辑页状态读取结果不可用',
        }

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
        rect = self._refresh_ant_select_rect_by_input_id(page, rect)
        existing_text = str(rect.get('text') or '').strip()
        if existing_text and not any(term in existing_text for term in ('请选择', '请选中', '----')):
            return {'ok': True, 'already_selected': True, 'text': existing_text}
        self._click_rect_center(page, rect['rect'])
        page.wait_for_timeout(800)
        self._open_ant_select_by_input_id(page, rect.get('input_id'))
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

    def _open_ant_select_by_input_id(self, page: Page, input_id: str | None) -> dict[str, Any]:
        input_id = str(input_id or '').strip()
        if not input_id:
            return {'opened': False, 'reason': 'missing_input_id'}
        result = page.evaluate(r'''({inputId}) => {
          const input = document.getElementById(inputId);
          const root = input?.closest('.ant-select');
          const selector = root?.querySelector('.ant-select-selector') || root;
          if (!input || !root || !selector) return {opened:false, reason:'select_not_found'};
          const expandedBefore = input.getAttribute('aria-expanded') === 'true' || root.className.includes('ant-select-open');
          if (!expandedBefore) {
            selector.scrollIntoView({block:'center', inline:'nearest'});
            const fire = (target, type) => target.dispatchEvent(new MouseEvent(type, {bubbles:true, cancelable:true, view:window}));
            fire(selector, 'mouseover');
            fire(selector, 'mousedown');
            fire(selector, 'mouseup');
            fire(selector, 'click');
            if (input.focus) input.focus();
          }
          const expandedAfter = input.getAttribute('aria-expanded') === 'true' || root.className.includes('ant-select-open');
          return {
            opened: expandedAfter,
            expanded_before: expandedBefore,
            expanded_after: expandedAfter,
          };
        }''', {'inputId': input_id}) or {}
        page.wait_for_timeout(300)
        return result

    def _refresh_ant_select_rect_by_input_id(self, page: Page, select_info: dict[str, Any]) -> dict[str, Any]:
        input_id = str(select_info.get('input_id') or '').strip()
        if not input_id:
            return select_info
        try:
            page.locator(f'#{input_id}').first.scroll_into_view_if_needed(timeout=3000)
            page.wait_for_timeout(300)
        except TimeoutError:
            return select_info
        refreshed = page.evaluate(r'''({inputId}) => {
          const input = document.getElementById(inputId);
          const root = input?.closest('.ant-select');
          if (!root) return null;
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          if (!visible(root)) return null;
          const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
          const r = root.getBoundingClientRect();
          return {
            rect: {x:r.x, y:r.y, w:r.width, h:r.height},
            text: textOf(root),
            input_id: inputId,
          };
        }''', {'inputId': input_id})
        if isinstance(refreshed, dict) and refreshed.get('rect'):
            return {**select_info, **refreshed}
        return select_info

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
        if self._is_visible_dxm_editor_page(page):
            return self._fill_text_inputs_after_label_locator(page, label_text, values)
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

    def _fill_text_inputs_after_label_locator(self, page: Page, label_text: str, values: list[str]) -> dict[str, Any]:
        if not values:
            return {'ok': True, 'filled': []}
        selector_result = self._fill_text_inputs_by_known_selector(page, label_text, values)
        if selector_result.get('ok'):
            return selector_result
        label_literal = self._xpath_literal(str(label_text))
        selector = (
            "xpath=(//*[self::label or self::span or self::div or self::td or self::th]"
            f"[contains(normalize-space(.), {label_literal})])[1]"
            "/following::*[self::input or self::textarea]"
            "[not(@disabled) and not(contains(@style, 'display: none'))]"
        )
        inputs = page.locator(selector)
        filled: list[str] = []
        self._trace_workflow_event(
            'editor_text_field:start',
            label=label_text,
            count=len(values),
            current_url=getattr(page, 'url', None),
            human_step=f'填写{label_text}',
        )
        for index, value in enumerate(values):
            try:
                target = inputs.nth(index)
                target.scroll_into_view_if_needed(timeout=3000)
                target.fill(str(value), timeout=3000, force=True)
                filled.append(str(value))
            except TimeoutError:
                self._trace_workflow_event(
                    'editor_text_field:failed',
                    label=label_text,
                    index=index,
                    current_url=getattr(page, 'url', None),
                    human_step=f'{label_text}填写失败',
                )
                return {'ok': False, 'reason': f'填写失败：{label_text}'}
        page.wait_for_timeout(300)
        self._trace_workflow_event(
            'editor_text_field:done',
            label=label_text,
            filled_count=len(filled),
            current_url=getattr(page, 'url', None),
            human_step=f'{label_text}填写完成',
        )
        return {'ok': True, 'filled': filled, 'method': 'visible_label_following_locator'}

    def _fill_text_inputs_by_known_selector(self, page: Page, label_text: str, values: list[str]) -> dict[str, Any]:
        selectors = self._known_visible_editor_text_selectors(label_text)
        if not selectors:
            return {'ok': False, 'reason': f'未配置稳定输入框：{label_text}'}
        last_reason = f'未找到输入框：{label_text}'
        for selector in self._prefer_visible_css_selectors(selectors):
            inputs = page.locator(selector)
            filled: list[str] = []
            try:
                candidate_count = inputs.count()
                self._trace_workflow_event(
                    'editor_text_field:selector_candidate',
                    label=label_text,
                    selector=selector,
                    count=candidate_count,
                    current_url=getattr(page, 'url', None),
                    human_step=f'查找{label_text}输入框',
                )
                if candidate_count < len(values):
                    last_reason = f'选择器未命中：{label_text} / {selector}'
                    continue
                for index, value in enumerate(values):
                    target = inputs.nth(index)
                    target.scroll_into_view_if_needed(timeout=1200)
                    target.fill(str(value), timeout=1800, force=True)
                    filled.append(str(value))
            except TimeoutError:
                last_reason = f'选择器未命中：{label_text} / {selector}'
                self._trace_workflow_event(
                    'editor_text_field:selector_timeout',
                    label=label_text,
                    selector=selector,
                    current_url=getattr(page, 'url', None),
                    human_step=f'{label_text}输入框不可填写',
                )
                continue
            except Exception as exc:
                last_reason = f'选择器填写失败：{label_text} / {selector} / {exc}'
                self._trace_workflow_event(
                    'editor_text_field:selector_error',
                    label=label_text,
                    selector=selector,
                    error=str(exc)[:240],
                    current_url=getattr(page, 'url', None),
                    human_step=f'{label_text}输入框填写异常',
                )
                continue
            page.wait_for_timeout(300)
            self._trace_workflow_event(
                'editor_text_field:done',
                label=label_text,
                filled_count=len(filled),
                selector=selector,
                current_url=getattr(page, 'url', None),
                human_step=f'{label_text}填写完成',
            )
            return {'ok': True, 'filled': filled, 'method': 'visible_known_selector', 'selector': selector}
        return {'ok': False, 'reason': last_reason}

    def _prefer_visible_css_selectors(self, selectors: list[str]) -> list[str]:
        preferred: list[str] = []
        for selector in selectors:
            clean = str(selector or '').strip()
            if not clean:
                continue
            if clean.startswith('xpath=') or ':visible' in clean:
                preferred.append(clean)
                continue
            preferred.append(f'{clean}:visible')
            preferred.append(clean)
        return preferred

    def _known_visible_editor_text_selectors(self, label_text: str) -> list[str]:
        compact = re.sub(r'\s+', '', str(label_text or ''))
        if compact == '产品标题':
            return [
                'input[name="subject"]',
                'textarea[name="subject"]',
                '.subject-editor input',
                '.subject-editor textarea',
                '#form_item_subject',
                '[placeholder="请输入产品标题"]',
                '[placeholder*="产品标题"]',
            ]
        if compact == '商品编码':
            return [
                '#form_item_productCode',
                '#form_item_product_code',
                '#form_item_skuCode',
                '#form_item_sku_code',
                'input[name="productCode"]',
                'input[name="product_code"]',
                'input[name="skuCode"]',
                'input[name="sku_code"]',
                'input[name*="sku"]',
                'input[id*="sku"]',
                '[placeholder*="商品编码"]',
                '[placeholder*="SKU"]',
            ]
        if compact == '发货期限':
            return [
                '#form_item_deliveryTime',
                '#form_item_delivery_time',
                '#form_item_deliveryPeriod',
                '#form_item_delivery_period',
                'input[name="deliveryTime"]',
                'input[name="delivery_time"]',
                'input[name="deliveryPeriod"]',
                'input[name="delivery_period"]',
                'input[name*="delivery"]',
                'input[id*="delivery"]',
                '[placeholder*="发货期限"]',
                '[placeholder*="备货期"]',
            ]
        return []

    def _xpath_literal(self, text: str) -> str:
        if "'" not in text:
            return f"'{text}'"
        if '"' not in text:
            return f'"{text}"'
        parts = text.split("'")
        return "concat(" + ", \"'\", ".join(f"'{part}'" for part in parts) + ")"

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
        option_script = r'''({priorities, anchor}) => {
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
          const priorityTerms = priorities.map(String).filter(Boolean);
          const pick = (items) => {
            const matched = priorityTerms.reduce((found, term) => found || items.find(x => x.text.includes(term)), null);
            return matched || (priorityTerms.length ? null : items[0]);
          };
          const pickedNear = pick(candidates);
          if (pickedNear) return {text:pickedNear.text, rect:pickedNear.rect, strategy:'near_anchor'};
          const pickedGlobal = pick(options);
          if (pickedGlobal) return {text:pickedGlobal.text, rect:pickedGlobal.rect, strategy:'global_visible_options'};
          return {
            no_match:true,
            options:(candidates.length ? candidates : options).map(x => x.text).slice(0, 20),
            candidate_count:candidates.length,
            option_count:options.length,
          };
        }'''
        option = page.evaluate(option_script, {'priorities': priorities, 'anchor': anchor_rect})
        if not option or not option.get('rect'):
            dismissed = self._dismiss_blocking_modals(page)
            if dismissed:
                self._click_rect_center(page, anchor_rect)
                page.wait_for_timeout(800)
                option = page.evaluate(option_script, {'priorities': priorities, 'anchor': anchor_rect})
        if not option or not option.get('rect'):
            reason = '未找到匹配选项' if option and option.get('no_match') else '未找到可见下拉选项'
            return {'ok': not required, 'reason': reason, 'optional': not required, 'options': (option or {}).get('options')}
        dispatched = page.evaluate(r'''({priorities, anchor, pickedText}) => {
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
          const priorityTerms = priorities.map(String).filter(Boolean);
          const pick = (items) => {
            const byPickedText = items.find(x => x.text === pickedText);
            if (byPickedText) return byPickedText;
            const matched = priorityTerms.reduce((found, term) => found || items.find(x => x.text.includes(term)), null);
            return matched || (priorityTerms.length ? null : items[0]);
          };
          const picked = pick(candidates) || pick(options);
          if (!picked) return {clicked:false, reason:'option_not_found'};
          picked.el.scrollIntoView({block:'nearest', inline:'nearest'});
          const fire = (target, type) => target.dispatchEvent(new MouseEvent(type, {bubbles:true, cancelable:true, view:window}));
          fire(picked.el, 'mouseover');
          fire(picked.el, 'mousemove');
          fire(picked.el, 'mousedown');
          fire(picked.el, 'mouseup');
          fire(picked.el, 'click');
          return {clicked:true, text:picked.text, rect:rectOf(picked.el)};
        }''', {'priorities': priorities, 'anchor': anchor_rect, 'pickedText': option.get('text')}) or {}
        if dispatched.get('clicked'):
            page.wait_for_timeout(800)
            return {
                'ok': True,
                'text': dispatched.get('text') or option.get('text'),
                'strategy': option.get('strategy'),
                'click_method': 'dom_dispatch',
            }
        self._click_rect_center(page, option['rect'])
        page.wait_for_timeout(800)
        return {'ok': True, 'text': option.get('text'), 'strategy': option.get('strategy'), 'click_method': 'coordinate'}

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
        script = r'''(payload) => {
          const text = payload.text;
          const doDispatch = Boolean(payload.doDispatch);
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
          const stateOf = (control) => {
            if (!control) return null;
            if (control.matches && control.matches('input[type="checkbox"],input[type="radio"]')) {
              return Boolean(control.checked);
            }
            const aria = String(control.getAttribute('aria-checked') || '').toLowerCase();
            if (aria === 'true') return true;
            if (aria === 'false') return false;
            const cls = String(control.className || '').toLowerCase();
            return cls.includes('checked') || cls.includes('selected') || cls.includes('active');
          };
          const findControl = (label, node) => {
            const scopes = [
              label,
              node.closest && node.closest('label'),
              node.closest && node.closest('.ant-radio-wrapper,.ant-checkbox-wrapper,[role="radio"],[role="checkbox"]'),
              node.parentElement,
              node.parentElement && node.parentElement.parentElement,
            ].filter(Boolean);
            for (const scope of scopes) {
              const control = scope.querySelector && scope.querySelector('input[type="checkbox"],input[type="radio"],[role="radio"],[role="checkbox"]');
              if (control) return {scope, control};
            }
            return {scope: label, control: null};
          };
          const dispatchMouse = (el) => {
            if (!el) return false;
            for (const type of ['mouseover', 'mouseenter', 'mousedown', 'mouseup', 'click']) {
              try {
                el.dispatchEvent(new MouseEvent(type, {bubbles:true, cancelable:true, view:window}));
              } catch (_) {}
            }
            return true;
          };
          const dispatchControl = (control, label) => {
            if (control && control.disabled) return false;
            if (control) {
              try { control.scrollIntoView({block:'center'}); } catch (_) {}
              try { control.focus({preventScroll:true}); } catch (_) {}
              try { control.click(); } catch (_) { dispatchMouse(control); }
              control.dispatchEvent(new Event('input', {bubbles:true}));
              control.dispatchEvent(new Event('change', {bubbles:true}));
            }
            if (label) {
              try { label.scrollIntoView({block:'center'}); } catch (_) {}
              try { label.click(); } catch (_) { dispatchMouse(label); }
            }
            return true;
          };
          const nodes = Array.from(document.querySelectorAll('label,span,div')).filter(visible).filter(el => norm(el.innerText || el.textContent) === norm(text));
          const node = nodes.find(el => el.closest('label')) || nodes[0];
          if (!node) return {ok:false, reason:`未找到选项：${text}`};
          const label = node.closest('label') || node;
          const {scope, control} = findControl(label, node);
          const target = scope || label;
          const beforeChecked = stateOf(control);
          if (beforeChecked === true) {
            return {
              ok:true,
              checked:true,
              already_checked:true,
              text:textOf(node),
              rect:rectOf(target),
              control_tag: control ? control.tagName : null,
              control_type: control ? control.getAttribute('type') : null,
            };
          }
          target.scrollIntoView({block:'center'});
          if (doDispatch) {
            dispatchControl(control, target);
          }
          const afterChecked = stateOf(control);
          return {
            ok: afterChecked === true,
            checked: afterChecked === true,
            text:textOf(node),
            rect:rectOf(target),
            control_found: Boolean(control),
            control_tag: control ? control.tagName : null,
            control_type: control ? control.getAttribute('type') : null,
            click_method: doDispatch ? 'dom_dispatch' : null,
            reason: afterChecked === true ? undefined : (control ? `选项未真正选中：${text}` : `未找到可校验选项控件：${text}`),
          };
        }'''
        result = page.evaluate(script, {'text': text, 'doDispatch': True})
        if result.get('ok') and result.get('checked') is True:
            return result
        if result.get('rect') and result.get('checked') is not True:
            self._click_rect_center(page, result['rect'])
            page.wait_for_timeout(500)
            verified = page.evaluate(script, {'text': text, 'doDispatch': False})
            if verified.get('ok') and verified.get('checked') is True:
                verified['click_method'] = result.get('click_method') or 'coordinate'
                return verified
            result.update({
                'ok': False,
                'checked': False,
                'verify_after_coordinate': verified,
                'reason': verified.get('reason') or result.get('reason') or f'选项未真正选中：{text}',
            })
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
        if os.name == 'nt' and not self._is_headless():
            self._trace_workflow_event(
                'semi_managed_defaults:visible_preserve_existing',
                current_url=getattr(page, 'url', None),
                human_step='保留包装物流当前状态',
            )
            return {
                'stage': 'semi_managed_defaults_filled',
                'label': '包装物流沿用当前状态',
                'message': '可视浏览器下暂不执行脚本批量改写包装物流字段，保留当前页面已有值；保存结果会继续校验。',
                'page_title': '店小秘半托管页',
                'page_url': page.url,
                'screenshot_url': None,
                'fill_result': {
                    'preserved_existing_visible_editor_values': True,
                    'deferred_validation': True,
                    'missing': [],
                },
                'published': False,
            }
        self._dismiss_blocking_modals(page)
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
          const locatedInputAny = (terms, placeholderTerms = terms) => {
            for (let i = 0; i < terms.length; i += 1) {
              const found = locatedInput(terms[i], placeholderTerms[i] || terms[i]);
              if (found) return found;
            }
            return null;
          };
          const productPrice = locatedInputAny(
            ['产品价格', '零售价', '供货价', '货值', '批发价', '报价'],
            ['价格', '零售价', '供货价', '货值', '批发价', '报价']
          );
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
            return page.evaluate(r'''(value) => {
              const visible = (el) => {
                const r = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
              };
              const norm = (s) => String(s || '').replace(/\s+/g, '').trim();
              const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
              const desiredText = norm(value).includes('是') && !norm(value).includes('否') ? '是' : '否';
              const setSelect = (select) => {
                const options = Array.from(select.options || []);
                const option = options.find(opt => norm(opt.textContent).includes(desiredText))
                  || options.find(opt => desiredText === '否' && String(opt.value) === '1')
                  || options.find(opt => desiredText === '是' && String(opt.value) === '2');
                if (!option) {
                  return {ok:false, reason:`未找到${desiredText}选项`, text:textOf(select), value:String(select.value || '')};
                }
                const before = String(select.value || '');
                const setter = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, 'value')?.set;
                if (setter) setter.call(select, option.value);
                else select.value = option.value;
                select.dispatchEvent(new Event('input', {bubbles:true}));
                select.dispatchEvent(new Event('change', {bubbles:true}));
                select.dispatchEvent(new Event('blur', {bubbles:true}));
                return {
                  ok: String(select.value || '') === String(option.value),
                  before,
                  after: String(select.value || ''),
                  selected_text: textOf(option),
                };
              };

              const rowSelects = [];
              const headerTerms = ['是否原箱', '是否原盒包装', 'OriginalPackage'];
              for (const table of Array.from(document.querySelectorAll('table')).filter(visible)) {
                const cells = Array.from(table.querySelectorAll('th,td')).filter(visible);
                const header = cells.find(cell => headerTerms.some(term => norm(textOf(cell)).includes(norm(term))));
                if (!header || typeof header.cellIndex !== 'number' || header.cellIndex < 0) continue;
                const rows = Array.from(table.querySelectorAll('tr'))
                  .filter(row => visible(row) && !row.contains(header));
                for (const row of rows) {
                  const rowCells = Array.from(row.children).filter(el => ['TD', 'TH'].includes(el.tagName));
                  const cell = rowCells[header.cellIndex];
                  if (!cell || !visible(cell)) continue;
                  const selects = Array.from(cell.querySelectorAll('select')).filter(visible);
                  rowSelects.push(...selects);
                }
              }
              if (!rowSelects.length) {
                return {ok:false, reason:'未找到半托管是否原箱选择框'};
              }
              const results = rowSelects.map(setSelect);
              const missing = results.filter(item => !item.ok);
              return {
                ok: missing.length === 0,
                strategy: 'table_select_by_header',
                count: rowSelects.length,
                results,
                reason: missing[0]?.reason || null,
              };
            }''', value)
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
        if self._is_visible_dxm_editor_page(page):
            save_state = self._visible_exact_save_button_state(page)
            save_state = save_state if isinstance(save_state, dict) else {'ok': False, 'reason': '保存按钮定位结果不可读'}
            if not save_state.get('ok') or not save_state.get('rect'):
                reason = save_state.get('reason') or 'visible_native_save_button_not_ready'
                self._trace_workflow_event(
                    'save_only:visible_exact_save_not_ready',
                    current_url=getattr(page, 'url', None),
                    reason=reason,
                    result=save_state,
                    human_step='等待安全保存按钮定位',
                )
                return {
                    'stage': 'save_only_failed',
                    'label': '保存按钮未安全定位',
                    'message': f'可视浏览器下未能安全定位精确“保存”按钮：{reason}。本次没有点击保存，也没有发布。',
                    'page_title': '店小秘编辑页',
                    'page_url': page.url,
                    'screenshot_url': None,
                    'save_result': {
                        **save_state,
                        'ok': False,
                        'reason': reason,
                        'published': False,
                        'clicked': False,
                    },
                    'published': False,
                }
            rect = save_state['rect']
            center_x = float(rect.get('x') or 0) + float(rect.get('w') or 0) / 2
            center_y = float(rect.get('y') or 0) + float(rect.get('h') or 0) / 2
            network_events = self._capture_save_network_events(page, rect)
            clicked = self._click_point_with_native_window(
                page,
                center_x,
                center_y,
                use_viewport_metrics=False,
                viewport_metrics_override=save_state.get('viewport') if isinstance(save_state.get('viewport'), dict) else None,
            )
            if not clicked:
                self._trace_workflow_event(
                    'save_only:visible_native_save_click_failed',
                    current_url=getattr(page, 'url', None),
                    result=save_state,
                    human_step='点击保存',
                )
                return {
                    'stage': 'save_only_failed',
                    'label': '保存按钮点击失败',
                    'message': '已定位精确“保存”按钮，但原生浏览器点击失败。本次没有点击保存，也没有发布。',
                    'page_title': '店小秘编辑页',
                    'page_url': page.url,
                    'screenshot_url': None,
                    'save_result': {
                        **save_state,
                        'ok': False,
                        'reason': 'native_exact_save_click_failed',
                        'published': False,
                        'clicked': False,
                        'network_events': network_events[:8],
                    },
                    'published': False,
                }
            self._trace_workflow_event(
                'save_only:visible_native_save_click_done',
                current_url=getattr(page, 'url', None),
                result={**save_state, 'clicked': True},
                human_step='点击保存',
            )
            try:
                page.wait_for_timeout(2500)
            except Exception:
                time.sleep(2.5)
            verify_result = self._visible_save_success_state(page)
            network_result = self._network_save_result(network_events)
            save_result = {
                **save_state,
                **(verify_result if isinstance(verify_result, dict) else {}),
                'clicked': True,
                'click_method': 'native_exact_save',
                'network_events': network_events[:8],
                'network_save_result': network_result,
                'published': False,
            }
            if network_result.get('ok') is True:
                save_result = {
                    **save_result,
                    'ok': True,
                    'success_text': save_result.get('success_text') or network_result.get('message') or '保存接口成功',
                }
            ok = bool(save_result.get('ok'))
            return {
                'stage': 'save_only' if ok else 'save_only_failed',
                'label': '已保存' if ok else '保存失败',
                'message': save_result.get('success_text') or save_result.get('message') or save_result.get('reason') or '保存后未拿到成功证明',
                'page_title': '店小秘编辑页',
                'page_url': page.url,
                'screenshot_url': None,
                'save_result': save_result,
                'published': False,
            }
        dismissed_modals = self._dismiss_blocking_modals(page)
        blocking_modal = self._visible_blocking_modal_state(page)
        if blocking_modal.get('visible'):
            screenshot_path = EDITOR_ACTION_SCREENSHOT_MAP['save_only']
            page.screenshot(path=str(screenshot_path), full_page=True)
            return {
                'stage': 'save_only_failed',
                'label': '保存失败',
                'message': '保存前弹窗未能关闭',
                'page_title': page.title(),
                'page_url': page.url,
                'screenshot_url': self._artifact_url(screenshot_path),
                'save_result': {
                    'ok': False,
                    'reason': '保存前弹窗未能关闭',
                    'dismissed_blocking_modals': dismissed_modals,
                    'dismiss_trace': self._last_dismiss_blocking_modals_trace[-8:],
                    'blocking_modal': blocking_modal,
                    'published': False,
                },
                'published': False,
            }
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
        if dismissed_modals:
            click_result = {
                **click_result,
                'dismissed_blocking_modals': dismissed_modals,
                'dismiss_trace': self._last_dismiss_blocking_modals_trace[-8:],
            }
        network_events = self._capture_save_network_events(page, click_result.get('rect'))
        if click_result.get('ok') and click_result.get('rect'):
            click_method = 'exact_save_locator'
            if not self._click_exact_save_button(page):
                self._click_rect_center(page, click_result['rect'])
                click_method = 'rect_center'
            click_result = {**click_result, 'clicked': True, 'click_method': click_method, 'message': '已点击保存'}
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

    def _visible_exact_save_button_state(self, page: Page) -> dict[str, Any]:
        self._trace_workflow_event(
            'save_only:visible_exact_save_locator_start',
            current_url=getattr(page, 'url', None),
            human_step='定位保存按钮',
        )
        script = r'''() => {
          const norm = (s) => String(s || '').replace(/\s+/g, '').trim();
          const textOf = (el) => norm(el.innerText || el.textContent || el.getAttribute('aria-label') || el.getAttribute('title') || '');
          const rectOf = (el) => {
            const r = el.getBoundingClientRect();
            return {x:r.x, y:r.y, w:r.width, h:r.height, top:r.top, bottom:r.bottom, left:r.left, right:r.right};
          };
          const visible = (el) => {
            if (!el || !el.getBoundingClientRect) return false;
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0
              && style.visibility !== 'hidden'
              && style.display !== 'none'
              && style.pointerEvents !== 'none'
              && !el.disabled
              && el.getAttribute('aria-disabled') !== 'true';
          };
          const dangerousTerms = ['发布','立即发布','继续发布','保存并发布','确认发布','提交发布','保存并移入待发布','移入待发布','批量发布','一键发布'];
          const actions = Array.from(document.querySelectorAll('button,a,[role="button"]'))
            .filter(visible)
            .map((el, index) => ({el, index, text:textOf(el), rect:rectOf(el), tag:String(el.tagName || '').toLowerCase()}));
          const forbiddenActions = actions
            .filter(item => dangerousTerms.includes(item.text))
            .map(item => ({text:item.text, rect:item.rect, tag:item.tag, index:item.index}));
          const dialogs = Array.from(document.querySelectorAll('.ant-modal,.ant-modal-wrap,.el-dialog,.el-dialog__wrapper,[role="dialog"],[class*="modal"],[class*="Modal"],[class*="popup"],[class*="Popup"],[class*="dialog"],[class*="Dialog"]'))
            .filter(visible);
          const exactSaves = actions.filter(item => item.text === '保存');
          if (!exactSaves.length) {
            const forbidden = forbiddenActions[0];
            return {
              ok:false,
              reason: forbidden ? `只看到发布类按钮：${forbidden.text}` : '未找到精确“保存”按钮',
              forbidden_actions: forbiddenActions,
              published:false,
              viewport:{innerWidth:window.innerWidth, innerHeight:window.innerHeight, visualViewportWidth:window.visualViewport && window.visualViewport.width, visualViewportHeight:window.visualViewport && window.visualViewport.height, devicePixelRatio:window.devicePixelRatio || 1}
            };
          }
          const targetItem = exactSaves.find(item => !dialogs.some(dialog => dialog.contains(item.el))) || exactSaves[0];
          const target = targetItem.el;
          if (dialogs.some(dialog => dialog.contains(target))) {
            return {
              ok:false,
              reason:'精确“保存”按钮位于弹窗内，不能确认是商品编辑页保存',
              rect:targetItem.rect,
              text:targetItem.text,
              forbidden_actions: forbiddenActions,
              published:false,
              viewport:{innerWidth:window.innerWidth, innerHeight:window.innerHeight, visualViewportWidth:window.visualViewport && window.visualViewport.width, visualViewportHeight:window.visualViewport && window.visualViewport.height, devicePixelRatio:window.devicePixelRatio || 1}
            };
          }
          target.scrollIntoView({block:'center', inline:'center'});
          const rect = rectOf(target);
          const x = rect.x + rect.w / 2;
          const y = rect.y + rect.h / 2;
          if (x < 0 || y < 0 || x > window.innerWidth || y > window.innerHeight) {
            return {
              ok:false,
              reason:'精确“保存”按钮不在当前可点击视口内',
              rect,
              text:targetItem.text,
              forbidden_actions: forbiddenActions,
              published:false,
              viewport:{innerWidth:window.innerWidth, innerHeight:window.innerHeight, visualViewportWidth:window.visualViewport && window.visualViewport.width, visualViewportHeight:window.visualViewport && window.visualViewport.height, devicePixelRatio:window.devicePixelRatio || 1}
            };
          }
          const atPoint = document.elementFromPoint(x, y);
          const actual = atPoint && atPoint.closest ? (atPoint.closest('button,a,[role="button"]') || target) : target;
          const actualText = textOf(actual);
          if (actualText !== '保存') {
            return {
              ok:false,
              reason:`保存按钮中心被其他元素遮挡：${actualText || '未知元素'}`,
              rect,
              text:targetItem.text,
              at_point_text:actualText,
              forbidden_actions: forbiddenActions,
              published:false,
              viewport:{innerWidth:window.innerWidth, innerHeight:window.innerHeight, visualViewportWidth:window.visualViewport && window.visualViewport.width, visualViewportHeight:window.visualViewport && window.visualViewport.height, devicePixelRatio:window.devicePixelRatio || 1}
            };
          }
          return {
            ok:true,
            text:'保存',
            rect,
            center:{x, y},
            at_point_text:actualText,
            exact_save_count: exactSaves.length,
            forbidden_actions: forbiddenActions,
            published:false,
            viewport:{innerWidth:window.innerWidth, innerHeight:window.innerHeight, visualViewportWidth:window.visualViewport && window.visualViewport.width, visualViewportHeight:window.visualViewport && window.visualViewport.height, devicePixelRatio:window.devicePixelRatio || 1}
          };
        }'''
        try:
            result = self._evaluate_visible_page_function_via_devtools(page, script, timeout=1800)
        except Exception as exc:
            devtools_reason = str(exc)[:160]
            native_result = self._visible_exact_save_button_state_from_native_snapshot(
                page,
                devtools_reason=devtools_reason,
            )
            if isinstance(native_result, dict) and native_result.get('ok'):
                result = native_result
            else:
                native_reason = native_result.get('reason') if isinstance(native_result, dict) else '原生窗口兜底不可用'
                result = {
                    'ok': False,
                    'reason': f'保存按钮定位通道不可用或失败：{devtools_reason}；原生窗口兜底失败：{native_reason}',
                    'published': False,
                    'native_fallback': native_result if isinstance(native_result, dict) else None,
                }
        self._trace_workflow_event(
            'save_only:visible_exact_save_locator_done',
            current_url=getattr(page, 'url', None),
            result=result,
            human_step='定位保存按钮',
        )
        return result if isinstance(result, dict) else {'ok': False, 'reason': '保存按钮定位结果不可读', 'published': False}

    def _visible_exact_save_button_state_from_native_snapshot(
        self,
        page: Page,
        *,
        devtools_reason: str | None = None,
    ) -> dict[str, Any]:
        try:
            snapshot = self._capture_native_dxm_content_snapshot(page)
        except Exception as exc:  # noqa: BLE001 - this is a best-effort fallback after DevTools failed.
            return {
                'ok': False,
                'reason': f'原生窗口截图失败：{str(exc)[:160]}',
                'published': False,
            }
        state = self._locate_save_button_from_native_toolbar_snapshot(snapshot)
        if not state.get('ok'):
            return state
        width = int((snapshot or {}).get('width') or 0)
        height = int((snapshot or {}).get('height') or 0)
        result = {
            **state,
            'locator': 'native_toolbar_snapshot',
            'devtools_error': devtools_reason,
            'published': False,
            'viewport': {
                'innerWidth': width,
                'innerHeight': height,
                'visualViewportWidth': width,
                'visualViewportHeight': height,
                'devicePixelRatio': 1,
                'source': 'native_content_bitmap',
            },
        }
        self._trace_workflow_event(
            'save_only:visible_exact_save_native_snapshot_done',
            current_url=getattr(page, 'url', None),
            result={key: result.get(key) for key in ('ok', 'rect', 'locator', 'devtools_error')},
            human_step='定位保存按钮',
        )
        return result

    @staticmethod
    def _locate_save_button_from_native_toolbar_snapshot(snapshot: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(snapshot, dict):
            return {'ok': False, 'reason': '原生窗口截图为空', 'published': False}
        try:
            width = int(snapshot.get('width') or 0)
            height = int(snapshot.get('height') or 0)
        except (TypeError, ValueError):
            return {'ok': False, 'reason': '原生窗口截图尺寸不可读', 'published': False}
        pixels = snapshot.get('pixels')
        if width <= 0 or height <= 0 or not isinstance(pixels, (bytes, bytearray)):
            return {'ok': False, 'reason': '原生窗口截图像素不可读', 'published': False}
        if len(pixels) < width * height * 4:
            return {'ok': False, 'reason': '原生窗口截图像素长度不足', 'published': False}

        top_limit = min(height, max(140, int(height * 0.24)))
        step = 1 if width <= 1000 else 2

        def pixel_rgb(x: int, y: int) -> tuple[int, int, int]:
            index = (y * width + x) * 4
            if str(snapshot.get('format') or 'bgra').lower() == 'rgba':
                return int(pixels[index]), int(pixels[index + 1]), int(pixels[index + 2])
            return int(pixels[index + 2]), int(pixels[index + 1]), int(pixels[index])

        def is_orange(r: int, g: int, b: int) -> bool:
            return r >= 220 and 70 <= g <= 175 and b <= 135 and (r - g) >= 45

        def is_green(r: int, g: int, b: int) -> bool:
            return 0 <= r <= 95 and g >= 120 and b <= 175 and (g - r) >= 45

        def components(predicate: Callable[[int, int, int], bool]) -> list[dict[str, Any]]:
            points: set[tuple[int, int]] = set()
            for y in range(0, top_limit, step):
                for x in range(0, width, step):
                    if predicate(*pixel_rgb(x, y)):
                        points.add((x, y))
            found: list[dict[str, Any]] = []
            while points:
                start = points.pop()
                stack = [start]
                min_x = max_x = start[0]
                min_y = max_y = start[1]
                count = 1
                while stack:
                    px, py = stack.pop()
                    for dx in (-step, 0, step):
                        for dy in (-step, 0, step):
                            if dx == 0 and dy == 0:
                                continue
                            nxt = (px + dx, py + dy)
                            if nxt not in points:
                                continue
                            points.remove(nxt)
                            stack.append(nxt)
                            nx, ny = nxt
                            min_x = min(min_x, nx)
                            max_x = max(max_x, nx)
                            min_y = min(min_y, ny)
                            max_y = max(max_y, ny)
                            count += 1
                box_w = max_x - min_x + step
                box_h = max_y - min_y + step
                found.append({
                    'x': min_x,
                    'y': min_y,
                    'w': box_w,
                    'h': box_h,
                    'left': min_x,
                    'top': min_y,
                    'right': min_x + box_w,
                    'bottom': min_y + box_h,
                    'center_x': min_x + box_w / 2,
                    'center_y': min_y + box_h / 2,
                    'count': count,
                })
            return found

        def buttonish(item: dict[str, Any], *, min_w: int, max_w: int) -> bool:
            box_w = int(item.get('w') or 0)
            box_h = int(item.get('h') or 0)
            count = int(item.get('count') or 0)
            if not min_w <= box_w <= max_w:
                return False
            if not 18 <= box_h <= 72:
                return False
            if int(item.get('y') or 0) > 220:
                return False
            area = max(1, box_w * box_h)
            return count >= max(30, int(area * 0.18 / max(1, step * step)))

        orange_buttons = [item for item in components(is_orange) if buttonish(item, min_w=34, max_w=190)]
        green_buttons = [item for item in components(is_green) if buttonish(item, min_w=34, max_w=180)]
        if not green_buttons:
            return {'ok': False, 'reason': '未在顶部工具栏识别到发布按钮参照物', 'published': False}

        for publish in sorted(green_buttons, key=lambda item: (float(item.get('x') or 0), int(item.get('count') or 0)), reverse=True):
            row_oranges = [
                item for item in orange_buttons
                if float(item.get('right') or 0) <= float(publish.get('left') or 0) - 4
                and abs(float(item.get('center_y') or 0) - float(publish.get('center_y') or 0)) <= 28
            ]
            exact_save_candidates = [item for item in row_oranges if 34 <= int(item.get('w') or 0) <= 112]
            if not exact_save_candidates:
                continue
            save = sorted(exact_save_candidates, key=lambda item: float(item.get('right') or 0), reverse=True)[0]
            rect = {
                'x': int(save['x']),
                'y': int(save['y']),
                'w': int(save['w']),
                'h': int(save['h']),
                'left': int(save['left']),
                'top': int(save['top']),
                'right': int(save['right']),
                'bottom': int(save['bottom']),
            }
            return {
                'ok': True,
                'text': '保存',
                'rect': rect,
                'center': {'x': rect['x'] + rect['w'] / 2, 'y': rect['y'] + rect['h'] / 2},
                'publish_reference_rect': {
                    'x': int(publish['x']),
                    'y': int(publish['y']),
                    'w': int(publish['w']),
                    'h': int(publish['h']),
                },
                'exact_save_count': 1,
                'published': False,
            }

        return {
            'ok': False,
            'reason': '已识别发布按钮，但未在其左侧安全识别到独立“保存”按钮',
            'published': False,
        }

    def _visible_save_success_state(self, page: Page) -> dict[str, Any]:
        script = r'''() => {
          const body = String(document.body ? document.body.innerText || document.body.textContent || '' : '');
          const compact = body.replace(/\s+/g, '');
          const successTerms = ['保存成功','编辑成功','产品编辑成功','您的产品编辑成功','已保存'];
          const successText = successTerms.find(term => compact.includes(term));
          if (successText) {
            return {ok:true, success_text:successText, published:false};
          }
          return {ok:false, reason:'保存后未检测到页面成功提示', published:false};
        }'''
        try:
            result = self._evaluate_visible_page_function_via_devtools(page, script, timeout=1800)
        except Exception as exc:
            result = {'ok': False, 'reason': f'保存成功提示读取通道不可用或失败：{str(exc)[:160]}', 'published': False}
        self._trace_workflow_event(
            'save_only:visible_success_check_done',
            current_url=getattr(page, 'url', None),
            result=result,
            human_step='确认保存结果',
        )
        return result if isinstance(result, dict) else {'ok': False, 'reason': '保存成功提示结果不可读', 'published': False}

    def _visible_blocking_modal_state(self, page: Page) -> dict[str, Any]:
        return page.evaluate(r'''() => {
          /* __DXM_BLOCKING_MODAL_STATE__ */
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
          const modal = Array.from(document.querySelectorAll('.notice-list-modal, .ant-modal-wrap, [role="dialog"], [class*="modal"], [class*="Modal"], [class*="popup"], [class*="Popup"], [class*="activity"], [class*="Activity"]'))
            .filter(isVisible)
            .reverse()
            .find(el => {
              const text = norm(el.innerText || el.textContent);
              if (!text) return false;
              if (text.includes('从图片银行选择') || text.includes('图片银行的分组')) return false;
              return text.includes('活动') || text.includes('公告') || text.includes('通知') || text.includes('我知道') || text.includes('知道了') || text.includes('关闭') || text.includes('忽略提示');
            });
          if (!modal) return {visible:false};
          const text = textOf(modal);
          return {visible:true, text:text.slice(0, 300), compact:norm(text).slice(0, 300), rect:rectOf(modal)};
        }''') or {'visible': False}

    def _dismiss_blocking_modals_if_visible(self, page: Page, *, context: str) -> int:
        self._trace_workflow_event(
            'blocking_modal_check:start',
            context=context,
            current_url=getattr(page, 'url', None),
            human_step='检查页面弹窗',
        )
        if os.name == 'nt' and os.getenv('DXM_LOGIN_HEADED') == '1' and not self._is_headless():
            self._trace_workflow_event(
                'blocking_modal_check:skipped_visible_browser',
                context=context,
                reason='avoid_cdp_or_dom_probe_hang_in_user_visible_chrome',
                human_step='可见浏览器跳过弹窗脚本探测',
            )
            return 0
        script = r'''() => {
          const norm = (s) => String(s || '').replace(/\s+/g, '').trim();
          const isVisible = (el) => {
            if (!el || !el.getBoundingClientRect) return false;
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const selectors = [
            '.notice-list-modal',
            '.ant-modal-wrap',
            '.ant-modal',
            '.el-dialog',
            '.el-dialog__wrapper',
            '[role="dialog"]',
            '[class*="modal"]',
            '[class*="Modal"]',
            '[class*="popup"]',
            '[class*="Popup"]',
            '[class*="activity"]',
            '[class*="Activity"]',
            '[class*="campaign"]',
            '[class*="Campaign"]',
            '[class*="guide"]',
            '[class*="Guide"]'
          ].join(',');
          const dangerousTerms = ['发布', '立即发布', '继续发布', '保存并发布', '确认发布', '提交发布', '保存并移入待发布', '移入待发布'];
          const candidates = Array.from(document.querySelectorAll(selectors)).filter(isVisible).map(el => {
            const text = String(el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
            const compact = norm(text);
            return {text, compact};
          }).filter(item => {
            if (!item.text && !item.compact) return false;
            if (item.compact.includes('从图片银行选择') || item.compact.includes('图片银行的分组')) return false;
            return item.compact.includes('跳过')
              || item.compact.includes('下一步')
              || item.compact.includes('我知道')
              || item.compact.includes('知道了')
              || item.compact.includes('关闭')
              || item.compact.includes('忽略提示')
              || item.compact.includes('活动')
              || item.compact.includes('公告')
              || item.compact.includes('通知');
          });
          const first = candidates[0] || null;
          if (!first) return {visible:false};
          const dangerous = dangerousTerms.find(term => first.compact.includes(norm(term))) || null;
          return {
            visible: true,
            dangerous,
            text: first.text.slice(0, 240),
          };
        }'''
        try:
            state = self._evaluate_zero_arg_page_function_with_runtime_timeout(page, script, timeout=2000)
        except Exception as exc:
            self._trace_workflow_event(
                'blocking_modal_check:failed',
                context=context,
                current_url=getattr(page, 'url', None),
                error=str(exc)[:240],
                human_step='页面弹窗检查失败',
            )
            return 0
        if not isinstance(state, dict) or not state.get('visible'):
            self._trace_workflow_event(
                'blocking_modal_check:none',
                context=context,
                human_step='未发现页面弹窗',
            )
            return 0
        self._trace_workflow_event(
            'blocking_modal_check:visible',
            context=context,
            dangerous=state.get('dangerous'),
            text=str(state.get('text') or '')[:160],
            human_step='发现页面弹窗',
        )
        if state.get('dangerous'):
            raise RuntimeError(f"检测到危险弹窗：{state.get('dangerous')}")
        dismissed = self._dismiss_blocking_modals(page)
        self._trace_workflow_event(
            'blocking_modal_check:dismissed',
            context=context,
            dismissed=dismissed,
            human_step='页面弹窗已处理',
        )
        return dismissed

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
        ambient_publish_risk_terms = {'已上架', '在线商品'}
        if (
            result
            and prior_save_ok
            and result.get('save_only_term')
            and result.get('publish_risk_term') in ambient_publish_risk_terms
        ):
            result['ignored_ambient_publish_risk_term'] = result.get('publish_risk_term')
            result['publish_risk_term'] = None
            result['published'] = False
            result['ok'] = True
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

    def _click_exact_save_button(self, page: Page) -> bool:
        locator = getattr(page, 'locator', None)
        if not callable(locator):
            return False
        selector = (
            "xpath=//button[normalize-space(.)='保存']"
            " | //a[normalize-space(.)='保存']"
            " | //*[@role='button' and normalize-space(.)='保存']"
        )
        try:
            exact_target = page.evaluate(r'''() => {
              const norm = (s) => String(s || '').replace(/\s+/g, '').trim();
              const visible = (el) => {
                const r = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none'
                  && !el.disabled && el.getAttribute('aria-disabled') !== 'true';
              };
              const rectOf = (el) => {
                const r = el.getBoundingClientRect();
                return {x:r.x, y:r.y, w:r.width, h:r.height};
              };
              const candidates = Array.from(document.querySelectorAll('button,a,[role="button"]'))
                .filter(visible)
                .filter(el => norm(el.innerText || el.textContent) === '保存');
              const target = candidates[0] || null;
              if (!target) return null;
              target.scrollIntoView({block:'center', inline:'center'});
              return {rect:rectOf(target), text:norm(target.innerText || target.textContent)};
            }''')
            if isinstance(exact_target, dict) and exact_target.get('rect'):
                page.wait_for_timeout(300)
                dispatched = page.evaluate(r'''() => {
                  const norm = (s) => String(s || '').replace(/\s+/g, '').trim();
                  const visible = (el) => {
                    const r = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < window.innerHeight
                      && style.visibility !== 'hidden' && style.display !== 'none'
                      && !el.disabled && el.getAttribute('aria-disabled') !== 'true';
                  };
                  const rectOf = (el) => {
                    const r = el.getBoundingClientRect();
                    return {x:r.x, y:r.y, w:r.width, h:r.height};
                  };
                  const dispatchMouse = (el, rect) => {
                    const x = rect.x + rect.w / 2;
                    const y = rect.y + rect.h / 2;
                    for (const type of ['mouseover', 'mousemove', 'mousedown', 'mouseup', 'click']) {
                      el.dispatchEvent(new MouseEvent(type, {bubbles:true, cancelable:true, view:window, clientX:x, clientY:y, button:0}));
                    }
                  };
                  const dangerousTerms = ['发布','立即发布','继续发布','保存并发布','保存并移入待发布','移入待发布','批量发布'];
                  const target = Array.from(document.querySelectorAll('button,a,[role="button"]'))
                    .filter(visible)
                    .find(el => norm(el.innerText || el.textContent) === '保存');
                  if (!target) return null;
                  const rect = rectOf(target);
                  const x = rect.x + rect.w / 2;
                  const y = rect.y + rect.h / 2;
                  const atPoint = document.elementFromPoint(x, y);
                  const actual = atPoint && atPoint.closest ? (atPoint.closest('button,a,[role="button"]') || target) : target;
                  const actualText = norm(actual.innerText || actual.textContent);
                  if (actualText !== '保存') {
                    return {ok:false, reason:'point_not_on_exact_save', rect, text:norm(target.innerText || target.textContent), at_point_text:actualText};
                  }
                  if (dangerousTerms.some(term => actualText.includes(norm(term)))) {
                    return {ok:false, reason:'dangerous_save_target', rect, text:actualText};
                  }
                  dispatchMouse(actual, rect);
                  if (typeof actual.click === 'function') actual.click();
                  return {ok:true, rect, text:actualText, method:'dom_exact_text'};
                }''')
                if isinstance(dispatched, dict) and dispatched.get('ok'):
                    self._trace_workflow_event(
                        'save_only:exact_save_click_done',
                        method='dom_exact_text',
                        result=dispatched,
                        human_step='点击保存',
                    )
                    return True
                if isinstance(dispatched, dict) and dispatched.get('rect'):
                    self._click_rect_center(page, dispatched['rect'])
                    self._trace_workflow_event(
                        'save_only:exact_save_click_done',
                        method='exact_text_scrolled_rect',
                        result=dispatched,
                        human_step='点击保存',
                    )
                    return True
        except Exception as exc:  # noqa: BLE001 - fall back to locator click.
            self._trace_workflow_event(
                'save_only:exact_save_dom_scroll_failed',
                error=str(exc)[:240],
                human_step='点击保存',
            )
        try:
            candidates = page.locator(selector)
            if self._locator_count(candidates) < 1:
                self._trace_workflow_event(
                    'save_only:exact_save_click_skipped',
                    reason='exact_save_button_not_found',
                    human_step='点击保存',
                )
                return False
            candidates.first.click(timeout=5000, force=True)
            self._trace_workflow_event(
                'save_only:exact_save_click_done',
                method='locator_exact_text',
                human_step='点击保存',
            )
            return True
        except Exception as exc:  # noqa: BLE001 - fall back to coordinate click.
            self._trace_workflow_event(
                'save_only:exact_save_click_failed',
                error=str(exc)[:240],
                human_step='点击保存',
            )
            return False

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
        json_events = [item for item in events if isinstance(item.get('json'), dict)]
        if json_events:
            exact_save_add_paths = {
                '/api/popchoiceproduct/add.json',
                '/api/smtproduct/add.json',
            }

            def event_path(item: dict[str, Any]) -> str:
                try:
                    return urlparse(str(item.get('url') or '')).path.lower()
                except ValueError:
                    return ''

            def priority(item: dict[str, Any]) -> int:
                path = event_path(item)
                if path in exact_save_add_paths:
                    return 0
                if path.endswith('/add.json') and 'history' not in path:
                    return 1
                return 2

            def status_ok(item: dict[str, Any]) -> bool:
                try:
                    return 200 <= int(item.get('status') or 0) < 300
                except (TypeError, ValueError):
                    return False

            def method_ok(item: dict[str, Any]) -> bool:
                return str(item.get('method') or '').upper() == 'POST'

            indexed = list(enumerate(json_events))
            _idx, item = sorted(indexed, key=lambda pair: (priority(pair[1]), -pair[0]))[0]
            payload = item.get('json') or {}
            data = payload.get('data')
            code = payload.get('code')
            msg = payload.get('msg') or payload.get('message')
            if isinstance(data, dict):
                code = data.get('code', code)
                msg = data.get('msg') or data.get('message') or msg
            code_ok = code in (0, '0') or payload.get('success') is True
            exact_add = event_path(item) in exact_save_add_paths
            if exact_add:
                success_text = str(msg or '')
                text_ok = any(term in success_text for term in ('保存成功', '编辑保存成功', '编辑成功'))
                ok = method_ok(item) and status_ok(item) and code_ok and text_ok
            else:
                ok = code_ok
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
        self._detach_cross_thread_browser_session()
        self._trace_workflow_event(
            'ensure_page:start',
            has_page=self._page is not None,
            has_context=self._context is not None,
            has_browser=self._browser is not None,
            headless=self._is_headless(),
        )
        if self._page is not None and not self._is_playwright_object_closed(self._page):
            self._trace_workflow_event('ensure_page:reuse_page', current_url=getattr(self._page, 'url', None))
            return self._page
        self._page = None
        if self._context is not None and not self._is_playwright_object_closed(self._context):
            self._page = self._context.new_page()
            self._reapply_live_hud_if_available(self._page)
            self._trace_workflow_event('ensure_page:new_page_existing_context', current_url=getattr(self._page, 'url', None))
            return self._page
        self._context = None
        if self._browser is not None and self._is_browser_connected(self._browser):
            self._context = self._new_browser_context(self._browser)
            self._page = self._context.new_page()
            self._reapply_live_hud_if_available(self._page)
            self._trace_workflow_event('ensure_page:new_context_existing_browser', current_url=getattr(self._page, 'url', None))
            return self._page
        self._playwright = sync_playwright().start()
        self._browser_session_thread_id = threading.get_ident()
        headless = self._is_headless()
        self._trace_workflow_event('ensure_page:playwright_started', headless=headless)
        options = chrome_launch_options(headless=headless)
        args = list(options.pop('args', []))
        if not headless:
            remote_debugging_port = self._ensure_visible_remote_debugging_port()
            args.extend([
                '--disable-notifications',
                '--disable-session-crashed-bubble',
                '--hide-crash-restore-bubble',
                '--no-first-run',
                '--no-default-browser-check',
                '--new-window',
                '--window-position=80,80',
                '--window-size=1600,950',
                f'--remote-debugging-port={remote_debugging_port}',
                '--remote-debugging-address=127.0.0.1',
                '--remote-allow-origins=*',
            ])
            self._trace_workflow_event(
                'ensure_page:visible_devtools_port_configured',
                port=remote_debugging_port,
                human_step='准备独立浏览器控制通道',
            )
        launch_kwargs = {**options}
        if args:
            launch_kwargs['args'] = args
        if not headless and self._use_persistent_visible_profile():
            profile_dir = self._workflow_browser_profile_dir()
            profile_dir.mkdir(parents=True, exist_ok=True)
            launch_kwargs.setdefault('viewport', {'width': 1440, 'height': 1024})
            launch_kwargs.setdefault('ignore_https_errors', True)
            self._trace_workflow_event(
                'ensure_page:persistent_context_start',
                profile_dir=str(profile_dir),
            )
            self._page = self._launch_visible_persistent_context_over_cdp(profile_dir, launch_kwargs)
            self._reapply_live_hud_if_available(self._page)
            self._trace_workflow_event('ensure_page:new_page_created', current_url=getattr(self._page, 'url', None))
            return self._page
        self._browser = self._playwright.chromium.launch(**launch_kwargs)
        self._trace_workflow_event('ensure_page:browser_launched', headless=headless, clean_context=True)
        self._context = self._new_browser_context(self._browser)
        self._trace_workflow_event('ensure_page:context_created')
        self._page = self._context.new_page()
        self._reapply_live_hud_if_available(self._page)
        self._trace_workflow_event('ensure_page:new_page_created', current_url=getattr(self._page, 'url', None))
        return self._page

    def _new_browser_context(self, browser: Browser) -> BrowserContext:
        context = browser.new_context(ignore_https_errors=True, viewport={'width': 1440, 'height': 1024})
        return context

    def _launch_visible_persistent_context_over_cdp(self, profile_dir: Path, launch_kwargs: dict[str, Any]) -> Page:
        executable_path = str(launch_kwargs.get('executable_path') or '').strip()
        if not executable_path:
            raise RuntimeError('未找到 Chrome/Edge 可执行文件，无法启动真实浏览器。')
        existing_port = self._existing_profile_devtools_port(profile_dir)
        if existing_port:
            port = existing_port
            self._remote_debugging_port = port
            self._trace_workflow_event(
                'ensure_page:external_cdp_existing_chrome_reuse',
                port=port,
                profile_dir=str(profile_dir),
                human_step='接入已打开的真实浏览器',
            )
            self._wait_for_visible_devtools_http(port)
            try:
                self._browser = self._connect_visible_browser_over_cdp(port)
                return self._page_from_connected_external_browser(profile_dir=profile_dir, port=port)
            except Exception as exc:  # noqa: BLE001 - stale Chrome DevTools can accept WS then never finish attaching.
                self._trace_workflow_event(
                    'ensure_page:external_cdp_existing_chrome_recycle',
                    port=port,
                    profile_dir=str(profile_dir),
                    error=str(exc)[:500],
                    human_step='旧执行浏览器已失去控制，正在重启真实浏览器',
                )
                self._terminate_existing_profile_chrome_processes(profile_dir)
                self._browser = None
                self._context = None
                self._page = None
                self._remote_debugging_port = None

        port = self._ensure_visible_remote_debugging_port()
        args = self._visible_external_chrome_args(profile_dir, launch_kwargs, port)
        command = [executable_path, *args, 'about:blank']
        popen_kwargs: dict[str, Any] = {
            'stdout': subprocess.DEVNULL,
            'stderr': subprocess.DEVNULL,
        }
        if os.name == 'nt' and hasattr(subprocess, 'CREATE_NO_WINDOW'):
            popen_kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
        self._trace_workflow_event(
            'ensure_page:external_cdp_chrome_start',
            port=port,
            profile_dir=str(profile_dir),
            executable_path=executable_path,
            has_no_sandbox_arg=any(str(arg).strip().lower() == '--no-sandbox' for arg in args),
            human_step='启动真实浏览器',
        )
        process = subprocess.Popen(command, **popen_kwargs)
        self._external_browser_process = process
        self._wait_for_visible_devtools_http(port)
        self._browser = self._connect_visible_browser_over_cdp(port)
        return self._page_from_connected_external_browser(profile_dir=profile_dir, port=port)

    def _connect_visible_browser_over_cdp(self, port: int) -> Browser:
        if self._playwright is None:
            raise RuntimeError('Playwright 未启动，无法接入真实浏览器。')
        endpoint = f'http://127.0.0.1:{port}'
        timeout_ms = self._visible_cdp_connect_timeout_ms()
        try:
            return self._playwright.chromium.connect_over_cdp(endpoint, timeout=timeout_ms)
        except TypeError as exc:
            if 'timeout' not in str(exc):
                raise
            return self._playwright.chromium.connect_over_cdp(endpoint)

    def _page_from_connected_external_browser(self, *, profile_dir: Path, port: int) -> Page:
        if self._browser is None:
            raise RuntimeError('真实浏览器接入失败，未获得可控浏览器会话。')
        contexts = list(getattr(self._browser, 'contexts', []) or [])
        self._context = contexts[0] if contexts else self._browser.new_context(ignore_https_errors=True, viewport={'width': 1440, 'height': 1024})
        self._trace_workflow_event(
            'ensure_page:external_cdp_connected',
            port=port,
            profile_dir=str(profile_dir),
            human_step='接入真实浏览器',
        )
        return self._context.pages[0] if self._context.pages else self._context.new_page()

    def _visible_cdp_connect_timeout_ms(self) -> int:
        configured = os.getenv('DXM_VISIBLE_CDP_CONNECT_TIMEOUT_MS') or os.getenv('DXM_WORKFLOW_CDP_CONNECT_TIMEOUT_MS')
        if configured:
            try:
                value = int(str(configured).strip())
            except ValueError:
                value = VISIBLE_CDP_CONNECT_TIMEOUT_MS
        else:
            value = VISIBLE_CDP_CONNECT_TIMEOUT_MS
        return min(max(value, 1000), 30000)

    def _terminate_existing_profile_chrome_processes(self, profile_dir: Path) -> list[int]:
        profile_text = str(profile_dir).strip().lower()
        if not profile_text or os.name != 'nt':
            return []
        profile_literal = profile_text.replace("'", "''")
        script = (
            f"$profile = '{profile_literal}'; "
            "$matched = Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
            "Where-Object { $_.CommandLine -and $_.CommandLine.ToLower().Contains($profile) }; "
            "foreach ($item in $matched) { "
            "$pidValue = [int]$item.ProcessId; "
            "try { Stop-Process -Id $pidValue -Force -ErrorAction Stop; Write-Output $pidValue } "
            "catch { Write-Output (\"failed:\" + $pidValue) } "
            "}"
        )
        try:
            completed = subprocess.run(
                ['powershell', '-NoProfile', '-Command', script],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
        except Exception as exc:  # noqa: BLE001 - cleanup is best effort; fresh launch will still report if it fails.
            self._trace_workflow_event(
                'ensure_page:external_cdp_existing_chrome_terminate_failed',
                profile_dir=str(profile_dir),
                error=str(exc)[:300],
                human_step='旧执行浏览器清理失败',
            )
            return []
        terminated: list[int] = []
        for line in (completed.stdout or '').splitlines():
            line = line.strip()
            if line.isdigit():
                terminated.append(int(line))
        self._trace_workflow_event(
            'ensure_page:external_cdp_existing_chrome_terminated',
            profile_dir=str(profile_dir),
            terminated_pids=terminated,
            human_step='旧执行浏览器已关闭',
        )
        return terminated

    def _existing_profile_devtools_port(self, profile_dir: Path) -> int | None:
        terminated_unhealthy = False
        for command_line in self._chrome_command_lines_for_profile(profile_dir):
            port = self._remote_debugging_port_from_command_line(command_line)
            if port and self._devtools_http_ready_on_port(port):
                if not self._devtools_page_runtime_healthy_on_port(port):
                    self._trace_workflow_event(
                        'ensure_page:external_cdp_existing_chrome_unhealthy',
                        port=port,
                        profile_dir=str(profile_dir),
                        human_step='旧执行浏览器页面已失去控制，准备重启',
                    )
                    if not terminated_unhealthy:
                        self._terminate_existing_profile_chrome_processes(profile_dir)
                        terminated_unhealthy = True
                    continue
                return port
        return None

    def _chrome_command_lines_for_profile(self, profile_dir: Path) -> list[str]:
        profile_text = str(profile_dir).strip().lower()
        if not profile_text or os.name != 'nt':
            return []
        script = (
            "$ErrorActionPreference='SilentlyContinue'; "
            "Get-CimInstance Win32_Process -Filter \"name='chrome.exe'\" | "
            "Select-Object -ExpandProperty CommandLine"
        )
        try:
            completed = subprocess.run(
                ['powershell', '-NoProfile', '-Command', script],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
        except Exception:
            return []
        command_lines = [line.strip() for line in (completed.stdout or '').splitlines() if line.strip()]
        return [line for line in command_lines if profile_text in line.lower()]

    def _remote_debugging_port_from_command_line(self, command_line: str) -> int | None:
        match = re.search(r'--remote-debugging-port=(\d+)', command_line or '')
        if not match:
            return None
        try:
            port = int(match.group(1))
        except ValueError:
            return None
        if port <= 0 or port > 65535:
            return None
        return port

    def _devtools_http_ready_on_port(self, port: int) -> bool:
        previous_port = self._remote_debugging_port
        try:
            self._remote_debugging_port = port
            version = self._devtools_json('/json/version', timeout_s=0.5)
            return isinstance(version, dict) and bool(version.get('webSocketDebuggerUrl'))
        except Exception:
            return False
        finally:
            self._remote_debugging_port = previous_port

    def _devtools_page_runtime_healthy_on_port(self, port: int) -> bool:
        previous_port = self._remote_debugging_port
        try:
            self._remote_debugging_port = port
            targets = self._devtools_json('/json/list', timeout_s=0.8)
        except Exception:
            return True
        finally:
            self._remote_debugging_port = previous_port
        if not isinstance(targets, list):
            return True
        page_targets = [
            item for item in targets
            if isinstance(item, dict)
            and item.get('type') == 'page'
            and item.get('webSocketDebuggerUrl')
        ]
        dxm_targets = [
            item for item in page_targets
            if 'dianxiaomi.com' in str(item.get('url') or '').lower()
        ]
        if not dxm_targets:
            return True
        expression = "(() => document.readyState || 'unknown')()"
        for target in dxm_targets:
            try:
                result = self._run_devtools_runtime_evaluate(
                    str(target.get('webSocketDebuggerUrl')),
                    expression,
                    timeout=800,
                )
                if result:
                    return True
            except Exception:
                continue
        return False

    def _visible_external_chrome_args(self, profile_dir: Path, launch_kwargs: dict[str, Any], port: int) -> list[str]:
        raw_args = [str(item) for item in (launch_kwargs.get('args') or []) if str(item).strip()]
        args: list[str] = []
        for arg in raw_args:
            if arg == '--remote-debugging-pipe':
                continue
            if arg.startswith('--user-data-dir='):
                continue
            if arg.startswith('--remote-debugging-port='):
                continue
            if arg.startswith('--remote-debugging-address='):
                continue
            args.append(arg)
        args.extend([
            f'--remote-debugging-port={port}',
            '--remote-debugging-address=127.0.0.1',
            '--remote-allow-origins=*',
            f'--user-data-dir={profile_dir}',
        ])
        return args

    def _wait_for_visible_devtools_http(self, port: int) -> dict[str, Any]:
        self._remote_debugging_port = port
        deadline = time.monotonic() + 8.0
        last_error = ''
        while time.monotonic() < deadline:
            try:
                version = self._devtools_json('/json/version', timeout_s=0.5)
                if isinstance(version, dict) and version.get('webSocketDebuggerUrl'):
                    return version
            except Exception as exc:  # noqa: BLE001 - retry until Chrome opens the port.
                last_error = str(exc)[:240]
            time.sleep(0.2)
        raise RuntimeError(f'真实浏览器 DevTools 端口未就绪: {last_error or port}')

    def _workflow_browser_profile_dir(self) -> Path:
        configured = os.getenv('DXM_WORKFLOW_PROFILE_DIR')
        if configured:
            return Path(configured).expanduser().resolve()
        return WORKFLOW_BROWSER_PROFILE_DIR

    def _use_persistent_visible_profile(self) -> bool:
        raw_value = os.getenv('DXM_WORKFLOW_PERSISTENT_PROFILE')
        value = str(raw_value or '').strip().lower()
        if value:
            return value in {'1', 'true', 'yes', 'on'}
        if os.getenv('DXM_DESKTOP', '').strip() == '1':
            return True
        if os.getenv('DXM_WORKFLOW_PROFILE_DIR', '').strip():
            return True
        return False

    def _install_data_acquisition_notice_auto_dismiss_for_context(self, context: BrowserContext) -> None:
        if not self._is_headless():
            try:
                context.add_init_script(DATA_ACQUISITION_NOTICE_AUTO_DISMISS_SCRIPT)
                self._data_acquisition_notice_bound_context_ids.add(id(context))
                self._trace_workflow_event(
                    'data_acquisition_notice_auto_dismiss:installed_on_context_create',
                    human_step='准备关闭店小秘通知弹窗',
                )
            except Exception as exc:
                self._trace_workflow_event(
                    'data_acquisition_notice_auto_dismiss:context_install_failed',
                    error=str(exc)[:240],
                    human_step='准备关闭店小秘通知弹窗',
                )

    def _is_playwright_object_closed(self, value: Any) -> bool:
        is_closed = getattr(value, 'is_closed', None)
        if callable(is_closed):
            try:
                return bool(is_closed())
            except Exception:
                return True
        return False

    def _is_browser_connected(self, browser: Browser) -> bool:
        is_connected = getattr(browser, 'is_connected', None)
        if callable(is_connected):
            try:
                return bool(is_connected())
            except Exception:
                return False
        return True

    def _ensure_page_with_cookies(self) -> Page:
        page = self._ensure_page()
        if self._context is not None and self.live_client.has_cookie_session():
            cookies = self.live_client.load_cookies()
            if cookies:
                self._context.add_cookies(cookies)
                self._trace_workflow_event(
                    'ensure_page:cookies_added',
                    cookie_count=len(cookies),
                    current_url=getattr(page, 'url', None),
                    human_step='已加载店小秘登录态',
                )
            else:
                self._trace_workflow_event(
                    'ensure_page:cookies_empty',
                    current_url=getattr(page, 'url', None),
                    human_step='未读取到店小秘登录态',
                )
        else:
            self._trace_workflow_event(
                'ensure_page:cookies_skipped',
                has_context=self._context is not None,
                has_cookie_session=self.live_client.has_cookie_session(),
                current_url=getattr(page, 'url', None),
                human_step='未加载店小秘登录态',
            )
        return page

    def _close_browser_session(self) -> None:
        if self._browser_session_thread_id is not None and self._browser_session_thread_id != threading.get_ident():
            self._trace_workflow_event(
                'browser_session:detached_cross_thread_close',
                owner_thread_id=self._browser_session_thread_id,
                current_thread_id=threading.get_ident(),
                human_step='丢弃跨线程浏览器引用',
            )
            self._page = None
            self._context = None
            self._browser = None
            self._playwright = None
            self._browser_session_thread_id = None
            self._remote_debugging_port = None
            self._external_browser_process = None
            return
        if self._context is not None:
            self._context.close()
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()
        self._close_external_browser_process()
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None
        self._browser_session_thread_id = None
        self._remote_debugging_port = None

    def _detach_cross_thread_browser_session(self) -> None:
        if self._browser_session_thread_id is None:
            return
        current_thread_id = threading.get_ident()
        if self._browser_session_thread_id == current_thread_id:
            return
        self._trace_workflow_event(
            'browser_session:detached_cross_thread_reuse',
            owner_thread_id=self._browser_session_thread_id,
            current_thread_id=current_thread_id,
            human_step='重新创建当前线程浏览器会话',
        )
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None
        self._browser_session_thread_id = None
        self._remote_debugging_port = None
        self._external_browser_process = None

    def _close_external_browser_process(self) -> None:
        process = self._external_browser_process
        self._external_browser_process = None
        if process is None:
            return
        poll = getattr(process, 'poll', None)
        try:
            running = callable(poll) and poll() is None
        except Exception:
            running = False
        if not running:
            return
        try:
            process.terminate()
            process.wait(timeout=3)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass

    def _ensure_visible_remote_debugging_port(self) -> int:
        if self._remote_debugging_port:
            return self._remote_debugging_port
        configured = os.getenv('DXM_WORKFLOW_DEVTOOLS_PORT') or os.getenv('DXM_VISIBLE_DEVTOOLS_PORT')
        if configured:
            try:
                port = int(str(configured).strip())
            except ValueError as exc:
                raise RuntimeError(f'DXM_WORKFLOW_DEVTOOLS_PORT 不是有效端口: {configured}') from exc
            if port <= 0 or port > 65535:
                raise RuntimeError(f'DXM_WORKFLOW_DEVTOOLS_PORT 超出端口范围: {configured}')
            self._remote_debugging_port = port
            return port
        self._remote_debugging_port = self._allocate_loopback_port()
        return self._remote_debugging_port

    def _allocate_loopback_port(self) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(('127.0.0.1', 0))
            return int(sock.getsockname()[1])

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

    def _evaluate_visible_page_function_via_devtools(
        self,
        page: Page,
        function_source: str,
        arg: Any | None = None,
        *,
        timeout: int = 2000,
    ) -> Any:
        port = self._remote_debugging_port
        if not port:
            raise RuntimeError('可视浏览器 DevTools 端口不可用，请重启真实浏览器。')
        timeout_s = max(float(timeout) / 1000.0, 0.5)
        targets = self._devtools_json('/json/list', timeout_s=min(timeout_s, 1.5))
        if not isinstance(targets, list):
            raise RuntimeError('可视浏览器 DevTools 目标列表不可读。')
        target = self._select_devtools_page_target(page, targets)
        if not target:
            raise RuntimeError('未找到当前店小秘页面的 DevTools 目标。')
        ws_url = target.get('webSocketDebuggerUrl')
        if not ws_url:
            raise RuntimeError('当前店小秘页面没有 DevTools WebSocket 地址。')
        if arg is None:
            expression = f'({function_source})()'
        else:
            arg_json = json.dumps(arg, ensure_ascii=False, default=str)
            expression = f'({function_source})({arg_json})'
        return self._run_devtools_runtime_evaluate(str(ws_url), expression, timeout=timeout)

    def _devtools_json(self, path: str, *, timeout_s: float = 1.5) -> Any:
        port = self._remote_debugging_port
        if not port:
            raise RuntimeError('可视浏览器 DevTools 端口不可用。')
        url = f'http://127.0.0.1:{port}{path}'
        try:
            with urllib.request.urlopen(url, timeout=timeout_s) as response:
                body = response.read().decode('utf-8', errors='replace')
        except urllib.error.URLError as exc:
            raise RuntimeError(f'可视浏览器 DevTools HTTP 不可用: {exc}') from exc
        return json.loads(body)

    def _select_devtools_page_target(self, page: Page, targets: list[Any]) -> dict[str, Any] | None:
        current_url = str(getattr(page, 'url', '') or '')
        current_url_no_hash = current_url.split('#', 1)[0]
        candidates = [
            item for item in targets
            if isinstance(item, dict)
            and item.get('type') == 'page'
            and item.get('webSocketDebuggerUrl')
        ]
        if not candidates:
            return None

        def score(item: dict[str, Any]) -> int:
            url = str(item.get('url') or '')
            url_no_hash = url.split('#', 1)[0]
            value = 0
            if current_url_no_hash and url_no_hash == current_url_no_hash:
                value += 100
            elif current_url_no_hash and (current_url_no_hash in url_no_hash or url_no_hash in current_url_no_hash):
                value += 80
            if '/web/smt/edit' in url:
                value += 60
            if 'dianxiaomi.com' in url:
                value += 40
            if url.startswith('about:') or not url:
                value -= 100
            return value

        selected = max(candidates, key=score)
        return selected if score(selected) > -50 else None

    def _run_devtools_runtime_evaluate(self, ws_url: str, expression: str, *, timeout: int = 2000) -> Any:
        timeout_s = max(float(timeout) / 1000.0, 0.5)

        async def run() -> Any:
            try:
                import websockets
            except Exception as exc:
                raise RuntimeError('缺少 websockets 依赖，无法使用独立 DevTools 通道。') from exc
            request_id = int(time.time() * 1000) % 1_000_000_000
            async with websockets.connect(
                ws_url,
                open_timeout=timeout_s,
                close_timeout=0.2,
                max_size=2_000_000,
            ) as websocket:
                await websocket.send(json.dumps(
                    {
                        'id': request_id,
                        'method': 'Runtime.evaluate',
                        'params': {
                            'expression': expression,
                            'returnByValue': True,
                            'awaitPromise': False,
                            'timeout': timeout,
                        },
                    },
                    ensure_ascii=False,
                ))
                deadline = time.monotonic() + timeout_s
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise RuntimeError('独立 DevTools Runtime.evaluate 超时。')
                    message = await asyncio.wait_for(websocket.recv(), timeout=remaining)
                    payload = json.loads(message)
                    if payload.get('id') != request_id:
                        continue
                    if payload.get('error'):
                        raise RuntimeError(str(payload.get('error'))[:240])
                    result = payload.get('result') or {}
                    if result.get('exceptionDetails'):
                        raise RuntimeError(str(result.get('exceptionDetails'))[:240])
                    runtime_result = result.get('result') or {}
                    if 'value' in runtime_result:
                        return runtime_result.get('value')
                    if runtime_result.get('type') == 'undefined':
                        return None
                    return runtime_result.get('description')

        return self._run_coroutine_from_sync(run, timeout_s=timeout_s + 0.5)

    def _run_coroutine_from_sync(self, coroutine_factory: Callable[[], Any], *, timeout_s: float) -> Any:
        def run_with_timeout() -> Any:
            return asyncio.run(asyncio.wait_for(coroutine_factory(), timeout=timeout_s))

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            try:
                return run_with_timeout()
            except asyncio.TimeoutError as exc:
                raise RuntimeError('独立 DevTools 调用超时。') from exc

        result_box: dict[str, Any] = {}

        def worker() -> None:
            try:
                result_box['value'] = run_with_timeout()
            except BaseException as exc:  # noqa: BLE001 - propagate from worker thread.
                result_box['error'] = exc

        thread = threading.Thread(target=worker, name='dxm-devtools-sync-bridge', daemon=True)
        thread.start()
        thread.join(timeout_s + 0.5)
        if thread.is_alive():
            raise RuntimeError('独立 DevTools 调用超时。')
        if 'error' in result_box:
            error = result_box['error']
            if isinstance(error, asyncio.TimeoutError):
                raise RuntimeError('独立 DevTools 调用超时。') from error
            if isinstance(error, BaseException):
                raise error
        return result_box.get('value')

    def _evaluate_zero_arg_page_function_with_runtime_timeout(
        self,
        page: Page,
        function_source: str,
        *,
        timeout: int = 2000,
    ) -> Any:
        if not self._is_headless() and self._remote_debugging_port:
            return self._evaluate_visible_page_function_via_devtools(page, function_source, timeout=timeout)
        try:
            cdp = page.context.new_cdp_session(page)
        except Exception:
            return page.evaluate(function_source)
        expression = f'({function_source})()'
        response = cdp.send(
            'Runtime.evaluate',
            {
                'expression': expression,
                'returnByValue': True,
                'timeout': timeout,
            },
        )
        if isinstance(response, dict) and response.get('exceptionDetails'):
            raise RuntimeError(str(response.get('exceptionDetails'))[:240])
        return ((response or {}).get('result') or {}).get('value')

    def _evaluate_page_function_with_runtime_timeout(
        self,
        page: Page,
        function_source: str,
        arg: Any,
        *,
        timeout: int = 3000,
    ) -> Any:
        if not self._is_headless() and self._remote_debugging_port:
            return self._evaluate_visible_page_function_via_devtools(page, function_source, arg, timeout=timeout)
        try:
            cdp = page.context.new_cdp_session(page)
        except Exception:
            return page.evaluate(function_source, arg)
        arg_json = json.dumps(arg, ensure_ascii=False, default=str)
        expression = f'({function_source})({arg_json})'
        response = cdp.send(
            'Runtime.evaluate',
            {
                'expression': expression,
                'returnByValue': True,
                'timeout': timeout,
            },
        )
        if isinstance(response, dict) and response.get('exceptionDetails'):
            raise RuntimeError(str(response.get('exceptionDetails'))[:240])
        return ((response or {}).get('result') or {}).get('value')

    def _dismiss_data_acquisition_blocking_modals(self, page: Page) -> int:
        dismissed = 0
        trace: list[dict[str, Any]] = []
        self._last_dismiss_blocking_modals_trace = trace
        visible_headed_data_acquisition = os.name == 'nt' and not self._is_headless() and self._is_data_acquisition_page_url(page)
        pressed_visible_escape = False
        if visible_headed_data_acquisition:
            if self._dismiss_data_acquisition_notice_with_native_click(page):
                trace.append({'clicked': 'native:notice-close'})
            self._click_data_acquisition_visible_dismiss_points(page, trace)
            if self._press_native_escape_for_visible_dxm(page):
                pressed_visible_escape = True
                trace.append({'clicked': 'native:escape'})
            plugin_guide_dismissed = self._dismiss_data_acquisition_plugin_guide_with_runtime(page, trace)
            if plugin_guide_dismissed:
                return plugin_guide_dismissed
            # Native fixed points are only a fast path. DXM can move the plugin guide,
            # so continue into the bounded DOM scan and click the actual dismiss control.
        for index in range(4):
            self._trace_workflow_event('dismiss_data_acquisition:start', iteration=index, current_url=page.url)
            if pressed_visible_escape:
                pressed_visible_escape = False
            elif self._press_native_escape_for_visible_dxm(page):
                self._trace_workflow_event(
                    'dismiss_data_acquisition:native_escape',
                    iteration=index,
                    reason='visible_browser_escape_before_bounded_overlay_scan',
                    human_step='检查页面弹窗',
                )
            script = r'''() => {
              const norm = (s) => String(s || '').replace(/\s+/g, '').trim();
              const rectOf = (el) => {
                const r = el.getBoundingClientRect();
                return {x:r.x, y:r.y, w:r.width, h:r.height};
              };
              const isVisible = (el) => {
                const r = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
              };
              const findTextTarget = (root, labels, limit = 300) => {
                for (const label of labels) {
                  const wanted = norm(label);
                  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
                  let seen = 0;
                  while (seen < limit) {
                    const node = walker.nextNode();
                    if (!node) break;
                    seen += 1;
                    const text = norm(node.nodeValue || '');
                    if (text !== wanted) continue;
                    let el = node.parentElement;
                    while (el && el !== root && !isVisible(el)) el = el.parentElement;
                    if (!el || !isVisible(el)) continue;
                    const clickable = el.closest('button,a,[role="button"],.ant-modal-close,[class*="close"]');
                    const target = clickable && root.contains(clickable) && isVisible(clickable) ? clickable : el;
                    return {el:target, text:text, rect:rectOf(target), tag:target.tagName};
                  }
                }
                return null;
              };
              const visibleInteractiveControls = (root) => Array.from(root.querySelectorAll('button,a,[role="button"],span,div,.ant-modal-close,[class*="close"]'))
                .filter(isVisible)
                .filter(el => norm(el.innerText || el.textContent || el.getAttribute('aria-label') || ''));
              const visibleGuides = Array.from(document.querySelectorAll('.guide-overlay, .guide-body, [class*="guide-overlay"], [class*="guide-body"]'))
                .filter(isVisible);
              if (visibleGuides.length) {
                const hasVisibleGuideControl = visibleGuides.some(el => visibleInteractiveControls(el).length > 0);
                const hasOnlyOverlayShells = visibleGuides.every(el => {
                  const compact = norm(el.innerText || el.textContent || '');
                  return visibleInteractiveControls(el).length === 0
                    && (
                      !compact
                      || Array.from(el.querySelectorAll('.guide-body, [class*="guide-body"]')).some(child => !isVisible(child))
                    );
                });
                if (!hasVisibleGuideControl && hasOnlyOverlayShells) {
                  visibleGuides.forEach(el => el.remove());
                  return {
                    visible: true,
                    removed: true,
                    removed_count: visibleGuides.length,
                    clicked: 'removed:blank-guide-overlay',
                    text: '店小秘采集引导遮罩'
                  };
                }
              }
              const selectors = [
                '.guide-overlay',
                '.guide-body',
                '.notice-list-modal',
                '.ant-modal-wrap',
                '.ant-modal',
                '.el-dialog',
                '.el-dialog__wrapper',
                '[role="dialog"]',
                '.ant-dropdown:not(.ant-dropdown-hidden)',
                '.ant-dropdown-menu',
                '[role="menu"]'
              ].join(',');
              const containers = Array.from(document.querySelectorAll(selectors))
                .filter(isVisible)
                .filter(el => !el.classList.contains('ant-modal-mask'));
              const modal = containers.find(el => {
                const text = norm(el.innerText || el.textContent);
                return text || el.querySelector('button,a,[role="button"],input,textarea,.ant-modal-close,[class*="close"]');
              });
              if (!modal) return {visible:false};
              const text = (modal.innerText || modal.textContent || '').replace(/\s+/g, ' ').trim();
              const compact = norm(text);
              const dangerousTerms = ['发布', '立即发布', '继续发布', '保存并发布', '确认发布', '提交发布', '保存并移入待发布', '移入待发布'];
              const dangerousTerm = dangerousTerms.find(term => compact.includes(norm(term)));
              if (dangerousTerm) {
                return {visible:true, dangerous:true, reason:`检测到危险弹窗：${dangerousTerm}`, text:text.slice(0,300)};
              }
              const labels = ['跳过','完成','我知道了','知道了','关闭','确定','忽略提示','下一步','取消'];
              const scoreControl = (item) => {
                const tag = String(item.tag || '').toLowerCase();
                const cls = String(item.cls || '').toLowerCase();
                const role = String(item.role || '').toLowerCase();
                const area = Math.max(0, Number(item.rect?.w || 0) * Number(item.rect?.h || 0));
                let score = Math.min(area, 20000) / 100;
                if (tag === 'button' || tag === 'a' || role === 'button') score -= 1000;
                if (cls.includes('close') || cls.includes('btn')) score -= 500;
                if (tag === 'div' || tag === 'span') score += 60;
                if (area > 20000) score += 1000;
                return score;
              };
              const controls = Array.from(modal.querySelectorAll('button,a,[role="button"],span,div,.ant-modal-close,[class*="close"]'))
                .filter(isVisible)
                .map(el => ({
                  el,
                  text:norm(el.innerText || el.textContent || el.getAttribute('aria-label') || ''),
                  rect:rectOf(el),
                  tag:el.tagName,
                  cls:String(el.className || ''),
                  role:String(el.getAttribute('role') || '')
                }))
                .sort((a, b) => scoreControl(a) - scoreControl(b));
              const match = labels.map(label => controls.find(item => item.text === norm(label))).find(Boolean)
                || findTextTarget(modal, labels)
                || controls.find(item => labels.includes(item.text))
                || controls.find(item => item.text.includes('关闭') || item.text.includes('知道'));
              if (!match) {
                const pageControls = Array.from(document.querySelectorAll('button,a,[role="button"],span,.ant-modal-close,[class*="close"]'))
                  .filter(isVisible)
                  .map(el => ({el, text:norm(el.innerText || el.textContent || el.getAttribute('aria-label') || ''), rect:rectOf(el), tag:el.tagName}));
                const pageMatch = labels.map(label => pageControls.find(item => item.text === norm(label))).find(Boolean)
                  || findTextTarget(document.body, labels, 1000);
                if (pageMatch) return {visible:true, clicked:`standalone:${pageMatch.text}`, rect:pageMatch.rect, text:text.slice(0,300)};
                return {visible:true, clicked:null, text:text.slice(0,300)};
              }
              return {visible:true, clicked:match.text || 'close', rect:match.rect, text:text.slice(0,300)};
            }'''
            try:
                result = self._evaluate_zero_arg_page_function_with_runtime_timeout(page, script, timeout=2000)
            except Exception as exc:
                self._trace_workflow_event(
                    'dismiss_data_acquisition:scan_failed',
                    iteration=index,
                    error=str(exc)[:240],
                    human_step='检查页面弹窗',
                )
                return dismissed
            self._trace_workflow_event('dismiss_data_acquisition:evaluated', iteration=index, result=result)
            if not result or not result.get('visible'):
                return dismissed
            trace.append({
                'clicked': result.get('clicked'),
                'rect': result.get('rect'),
                'text': str(result.get('text') or '')[:160],
                'dangerous': bool(result.get('dangerous')),
            })
            if result.get('dangerous'):
                raise RuntimeError(result.get('reason') or '检测到危险弹窗，已停止自动点击')
            if result.get('removed'):
                dismissed += 1
                try:
                    page.wait_for_timeout(300)
                except Exception:
                    pass
                continue
            if not result.get('clicked') or not result.get('rect'):
                return dismissed
            self._click_rect_center(page, result['rect'])
            dismissed += 1
            page.wait_for_timeout(500)
            if visible_headed_data_acquisition:
                return dismissed
        return dismissed

    def _dismiss_data_acquisition_plugin_guide_with_runtime(self, page: Page, trace: list[dict[str, Any]]) -> int:
        if os.name != 'nt' or self._is_headless() or not self._is_data_acquisition_page_url(page):
            return 0
        script = r'''() => {
          const norm = (s) => String(s || '').replace(/\s+/g, '').trim();
          const textOf = (el) => (el ? (el.innerText || el.textContent || '') : '').replace(/\s+/g, ' ').trim();
          const isVisible = (el) => {
            if (!el || !el.getBoundingClientRect) return false;
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const rectOf = (el) => {
            const r = el.getBoundingClientRect();
            return {x:r.x, y:r.y, w:r.width, h:r.height};
          };
          const guides = Array.from(document.querySelectorAll('.guide-overlay, .guide-body, [class*="guide-overlay"], [class*="guide-body"]'))
            .filter(isVisible)
            .filter(el => {
              const compact = norm(textOf(el));
              return compact.includes('安装店小秘采集插件') && compact.includes('跳过');
            });
          if (!guides.length) return {visible:false};
          const guide = guides.find(el => norm(textOf(el)).includes('下载采集插件')) || guides[0];
          const compact = norm(textOf(guide));
          const dangerousTerms = ['发布', '立即发布', '继续发布', '保存并发布', '确认发布', '提交发布', '保存并移入待发布', '移入待发布'];
          const dangerousTerm = dangerousTerms.find(term => compact.includes(norm(term)));
          if (dangerousTerm) {
            return {visible:true, dangerous:true, reason:`检测到危险引导层：${dangerousTerm}`, text:textOf(guide).slice(0, 300)};
          }
          const candidates = Array.from(guide.querySelectorAll('button,a,[role="button"],[onclick],span,div'))
            .filter(isVisible)
            .map(el => ({el, text:norm(textOf(el)), rect:rectOf(el), cls:String(el.className || ''), tag:String(el.tagName || '').toLowerCase()}))
            .filter(item => item.text === '跳过');
          const target = candidates.find(item => ['button', 'a'].includes(item.tag) || item.cls.includes('pointer'))
            || candidates[0];
          try {
            if (target && target.el && typeof target.el.click === 'function') target.el.click();
          } catch (_) {}
          const toRemove = new Set();
          for (const item of guides) {
            const overlay = item.closest('.guide-overlay, [class*="guide-overlay"]');
            toRemove.add(overlay || item);
          }
          let removed = 0;
          for (const item of toRemove) {
            if (item && item.parentElement) {
              item.remove();
              removed += 1;
            }
          }
          return {
            visible: true,
            removed: true,
            removed_count: removed,
            clicked: 'runtime:guide-skip',
            rect: target ? target.rect : null,
            text: textOf(guide).slice(0, 300),
          };
        }'''
        try:
            result = self._evaluate_zero_arg_page_function_with_runtime_timeout(page, script, timeout=2000)
        except Exception as exc:
            self._trace_workflow_event(
                'dismiss_data_acquisition:plugin_guide_runtime_failed',
                error=str(exc)[:240],
                human_step='关闭采集插件引导',
            )
            return 0
        self._trace_workflow_event(
            'dismiss_data_acquisition:plugin_guide_runtime_evaluated',
            result=result,
            human_step='关闭采集插件引导',
        )
        if not isinstance(result, dict) or not result.get('visible'):
            return 0
        trace.append({
            'clicked': result.get('clicked') or 'runtime:guide-skip',
            'rect': result.get('rect'),
            'text': str(result.get('text') or '')[:160],
            'removed': bool(result.get('removed')),
        })
        if result.get('dangerous'):
            raise RuntimeError(result.get('reason') or '检测到危险引导层，已停止自动点击')
        if result.get('removed') or result.get('clicked'):
            try:
                page.wait_for_timeout(300)
            except Exception:
                pass
            return 1
        return 0

    def _click_data_acquisition_visible_dismiss_points(self, page: Page, trace: list[dict[str, Any]]) -> int:
        if os.name != 'nt' or self._is_headless() or not self._is_data_acquisition_page_url(page):
            return 0
        # Visible DXM can block Playwright/CDP inspection while an activity or guide overlay is active.
        # These points target only known dismiss controls on the data-acquisition page and never submit, claim, save, or publish.
        points = [
            ('notice-header-close-1440', 1170.0, 91.0),
            ('notice-header-close-wide', 1650.0, 128.0),
            ('notice-footer-close-1440', 1147.0, 675.0),
            ('notice-footer-close-wide', 1618.0, 950.0),
            ('guide-skip', 542.0, 357.0),
        ]
        for label, x, y in points:
            self._trace_workflow_event(
                'dismiss_data_acquisition:native_point_start',
                label=label,
                point={'x': x, 'y': y},
                human_step='关闭页面遮罩',
            )
            if self._click_point_with_native_window(page, x, y):
                trace.append({'clicked': f'native:{label}', 'rect': {'x': x, 'y': y, 'w': 1, 'h': 1}})
                self._trace_workflow_event(
                    'dismiss_data_acquisition:native_point_done',
                    label=label,
                    point={'x': x, 'y': y},
                    human_step='关闭页面遮罩',
                )
                time.sleep(0.25)
            else:
                self._trace_workflow_event(
                    'dismiss_data_acquisition:native_point_skipped',
                    label=label,
                    point={'x': x, 'y': y},
                    human_step='关闭页面遮罩',
                )
        return 0

    def _press_native_escape_for_visible_dxm(self, page: Page) -> bool:
        if os.name != 'nt' or self._is_headless():
            return False
        page_url = str(getattr(page, 'url', '') or '')
        if 'dianxiaomi.com' not in page_url:
            return False
        try:
            import ctypes
            from ctypes import wintypes

            self._force_foreground_dxm_window()
            user32 = ctypes.windll.user32
            user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.POINTER(ctypes.c_ulong)]
            user32.keybd_event.restype = None
            vk_escape = 0x1B
            keyeventf_keyup = 0x0002
            user32.keybd_event(vk_escape, 0, 0, None)
            time.sleep(0.03)
            user32.keybd_event(vk_escape, 0, keyeventf_keyup, None)
            return True
        except Exception as exc:
            self._trace_workflow_event(
                'dismiss_data_acquisition:native_escape_failed',
                error=str(exc)[:240],
                human_step='检查页面弹窗',
            )
            return False

    def _dismiss_blocking_modals(self, page: Page) -> int:
        dismissed = 0
        trace: list[dict[str, Any]] = []
        repeated_clicks: dict[str, int] = {}
        self._last_dismiss_blocking_modals_trace = trace
        for _ in range(10):
            try:
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
              const dropdown = Array.from(document.querySelectorAll('.ant-dropdown:not(.ant-dropdown-hidden), .ant-dropdown-menu, [role="menu"], .dropdown-menu'))
                .filter(isVisible)
                .reverse()
                .find(el => {
                  const text = norm(el.innerText || el.textContent);
                  return text.includes('不提醒') || text.includes('不提示') || text.includes('关闭提示') || text.includes('忽略提示');
                });
              if (dropdown) {
                const dropdownText = textOf(dropdown);
                const dangerousTerms = ['发布', '立即发布', '继续发布', '保存并发布', '确认发布', '提交发布', '保存并移入待发布', '移入待发布'];
                const dangerousTerm = dangerousTerms.find(term => norm(dropdownText).includes(norm(term)));
                if (dangerousTerm) {
                  return {visible:true, dangerous:true, reason:`检测到危险下拉菜单：${dangerousTerm}`, text:dropdownText.slice(0,300)};
                }
                const options = Array.from(dropdown.querySelectorAll('button,a,li,span,div')).filter(isVisible);
                const target = options.find(el => norm(el.innerText || el.textContent).includes('不提示'))
                  || options.find(el => norm(el.innerText || el.textContent).includes('不提醒'))
                  || options.find(el => norm(el.innerText || el.textContent).includes('关闭提示'))
                  || options.find(el => norm(el.innerText || el.textContent).includes('忽略提示'));
                if (target) {
                  return {visible:true, clicked:`dropdown:${norm(target.innerText || target.textContent)}`, rect:rectOf(target), text:dropdownText.slice(0,300)};
                }
              }
              const standaloneNoticeLabels = ['忽略提示','我知道了','知道了','关闭','确定'];
              const standaloneNotice = Array.from(document.querySelectorAll('button,a,[role="button"],span,div'))
                .filter(isVisible)
                .map(el => ({el, text:norm(el.innerText || el.textContent), rect:rectOf(el), tag:el.tagName}))
                .filter(item => standaloneNoticeLabels.includes(item.text))
                .sort((a, b) => {
                  const area = (item) => Math.max(1, item.rect.w) * Math.max(1, item.rect.h);
                  const tagScore = (item) => ['BUTTON', 'A', 'SPAN'].includes(item.tag) ? 0 : 1;
                  return tagScore(a) - tagScore(b) || area(a) - area(b);
                })[0] || null;
               const modalSelectors = [
                 '.notice-list-modal',
                 '.ant-modal-wrap',
                 '.ant-modal',
                 '.el-dialog',
                 '.el-dialog__wrapper',
                 '[role="dialog"]',
                 '[class*="modal"]',
                 '[class*="Modal"]',
                 '[class*="popup"]',
                 '[class*="Popup"]',
                 '[class*="activity"]',
                 '[class*="Activity"]',
                 '[class*="campaign"]',
                 '[class*="Campaign"]',
                 '[class*="remind"]',
                 '[class*="Remind"]',
                 '[class*="dialog"]',
                 '[class*="Dialog"]'
               ].join(',');
               const hasModalContent = (el) => {
                 if (el.classList.contains('ant-modal-mask')) return false;
                 const text = norm(el.innerText || el.textContent);
                 const hasControl = Boolean(el.querySelector('button,a,[role="button"],input,textarea'));
                 return Boolean(text || hasControl);
               };
               const explicitModalCandidates = Array.from(document.querySelectorAll(modalSelectors))
                 .map((el, index) => ({el, index}))
                 .filter(item => isVisible(item.el) && hasModalContent(item.el));
               explicitModalCandidates.sort((a, b) => {
                 const styleA = window.getComputedStyle(a.el);
                 const styleB = window.getComputedStyle(b.el);
                 const zA = Number.parseInt(styleA.zIndex || '0', 10) || 0;
                 const zB = Number.parseInt(styleB.zIndex || '0', 10) || 0;
                 return zB - zA || b.index - a.index;
               });
               const explicitModal = explicitModalCandidates[0] ? explicitModalCandidates[0].el : null;
               const fixedNotice = Array.from(document.querySelectorAll('body *')).find(el => {
                 if (!isVisible(el)) return false;
                 const style = window.getComputedStyle(el);
                 const zIndex = Number.parseInt(style.zIndex || '0', 10) || 0;
                 if (!['fixed', 'sticky'].includes(style.position) && zIndex < 100) return false;
                 const r = el.getBoundingClientRect();
                 if (r.width < 240 || r.height < 80) return false;
                 const text = norm(el.innerText || el.textContent);
                 if (!(text.includes('重要提醒') || text.includes('最新特惠') || text.includes('活动') || text.includes('通知'))) return false;
                 return ['下一步','跳过','完成','我知道了','知道了','关闭','确定','忽略提示']
                   .some(label => text.includes(label));
               });
               const modal = explicitModal || fixedNotice;
               if (!modal) {
                 if (standaloneNotice) {
                   return {visible:true, clicked:`standalone:${standaloneNotice.text}`, rect:rectOf(standaloneNotice.el), text:standaloneNotice.text};
                }
                return {visible:false};
              }
              const modalText = textOf(modal);
              const compactModalText = norm(modalText);
              if (compactModalText.includes('从图片银行选择') || compactModalText.includes('图片银行的分组')) {
                return {visible:false, image_bank:true};
              }
              const dangerousActionLabels = ['发布', '立即发布', '继续发布', '保存并发布', '确认发布', '提交发布', '保存并移入待发布', '移入待发布', '批量发布'];
              const dangerousBodyTerms = ['立即发布', '继续发布', '保存并发布', '确认发布', '提交发布', '保存并移入待发布', '移入待发布', '批量发布'];
              const dangerousControls = Array.from(modal.querySelectorAll('button,a,[role="button"]'))
                .filter(isVisible)
                .map(el => norm(el.innerText || el.textContent))
                .filter(Boolean);
              const dangerousControlTerm = dangerousControls.find(text => dangerousActionLabels.includes(text));
              const dangerousBodyTerm = dangerousBodyTerms.find(term => compactModalText.includes(norm(term)));
              const dangerousTerm = dangerousControlTerm || dangerousBodyTerm;
              if (dangerousTerm) {
                return {visible:true, dangerous:true, reason:`检测到危险弹窗：${dangerousTerm}`, text:modalText.slice(0,300)};
              }
               const isNoticeModal = modal.classList.contains('notice-list-modal')
                 || compactModalText.includes('公告')
                 || compactModalText.includes('通知')
                 || compactModalText.includes('活动')
                 || compactModalText.includes('重要提醒')
                 || compactModalText.includes('最新特惠')
                 || compactModalText.includes('忽略提示')
                 || compactModalText.includes('我知道')
                 || compactModalText.includes('知道了');
              if (isNoticeModal) {
                const noticeButtons = Array.from(modal.querySelectorAll('button,a,span,div')).filter(isVisible);
                const noticeLabels = ['忽略提示','我知道了','知道了','关闭','确定'];
                const noticeMatches = noticeButtons
                  .map(el => ({el, text:norm(el.innerText || el.textContent), rect:rectOf(el), tag:el.tagName}))
                  .filter(item => noticeLabels.includes(item.text))
                  .sort((a, b) => {
                    const area = (item) => Math.max(1, item.rect.w) * Math.max(1, item.rect.h);
                    const tagScore = (item) => ['BUTTON', 'A', 'SPAN'].includes(item.tag) ? 0 : 1;
                    return tagScore(a) - tagScore(b) || area(a) - area(b);
                  });
                const noticeTarget = noticeMatches[0] || null;
                if (noticeTarget) {
                  return {visible:true, clicked:noticeTarget.text, rect:noticeTarget.rect, text:modalText.slice(0,300)};
                }
              }
              const modalDebug = () => ({
                tag: modal.tagName,
                cls: String(modal.className || ''),
                text: modalText.slice(0,300),
                controls: Array.from(modal.querySelectorAll('button,a,span,div'))
                  .filter(isVisible)
                  .map(el => norm(el.innerText || el.textContent))
                  .filter(Boolean)
                  .slice(0,20),
              });
              const closeButton = Array.from(modal.querySelectorAll('.ant-modal-close, .ant-modal-close-x, .close, .close-btn, .notice-close, [class*="close"], [aria-label*="Close"], [aria-label*="关闭"]'))
                .find(isVisible);
              if (closeButton) {
                return {visible:true, clicked:'modal-close', rect:rectOf(closeButton)};
              }
              if (standaloneNotice) {
                return {visible:true, clicked:`standalone:${standaloneNotice.text}`, rect:rectOf(standaloneNotice.el), text:standaloneNotice.text};
              }
              const guideDismissLabels = ['跳过','下一步','完成','我知道了','知道了','关闭','取消'];
              const noticeDismissLabels = ['跳过','下一步','完成','我知道了','知道了','关闭','确定','下一条'];
              const labels = [...(isNoticeModal ? noticeDismissLabels : guideDismissLabels), '忽略提示'];
              const buttons = Array.from(modal.querySelectorAll('button,a,span,div')).filter(isVisible);
              const textMatches = buttons.filter(el => labels.includes(norm(el.innerText || el.textContent)));
              const target = textMatches.find(el => ['BUTTON', 'A'].includes(el.tagName))
                || (textMatches[0] && (textMatches[0].closest('button,a') || textMatches[0]));
              if (!target) return {visible:true, clicked: isNoticeModal ? 'escape' : null, text: modalText.slice(0,300), modal_debug: modalDebug()};
              return {visible:true, clicked:norm(target.innerText || target.textContent), rect:rectOf(target)};
                }''')
            except Exception as exc:
                trace.append({
                    'clicked': None,
                    'rect': None,
                    'text': '',
                    'dangerous': False,
                    'modal_debug': {'error': str(exc)[:240]},
                    'fallback': 'page_unavailable',
                })
                self._trace_workflow_event(
                    'dismiss_blocking_modals:page_unavailable',
                    error=str(exc)[:240],
                    dismissed=dismissed,
                )
                return dismissed
            if not result or not result.get('visible'):
                return dismissed
            trace.append({
                'clicked': result.get('clicked'),
                'rect': result.get('rect'),
                'text': str(result.get('text') or '')[:160],
                'dangerous': bool(result.get('dangerous')),
                'modal_debug': result.get('modal_debug'),
            })
            if result.get('dangerous'):
                raise RuntimeError(result.get('reason') or '检测到危险弹窗，已停止自动点击')
            if not result.get('clicked'):
                return dismissed
            rect = result.get('rect')
            click_key = json.dumps({'clicked': result.get('clicked'), 'rect': rect}, ensure_ascii=False, sort_keys=True)
            repeated_clicks[click_key] = repeated_clicks.get(click_key, 0) + 1
            if repeated_clicks[click_key] >= 3:
                removed = self._remove_stuck_notice_modal(page)
                if removed.get('removed'):
                    trace[-1]['fallback'] = 'remove_stuck_notice_modal'
                    trace[-1]['removed_modal'] = removed
                    dismissed += 1
                    page.wait_for_timeout(800)
                    continue
                trace[-1]['fallback'] = 'escape_after_repeated_click'
                trace[-1]['remove_attempt'] = removed
                page.keyboard.press('Escape')
                dismissed += 1
                page.wait_for_timeout(800)
                continue
            if result.get('clicked') == 'escape':
                page.keyboard.press('Escape')
                dismissed += 1
                page.wait_for_timeout(800)
                continue
            if rect:
                self._click_rect_center(page, rect)
                dismissed += 1
            page.wait_for_timeout(800)
        return dismissed

    def _remove_stuck_notice_modal(self, page: Page) -> dict[str, Any]:
        try:
            return page.evaluate(r'''() => {
              const norm = (s) => String(s || '').replace(/\s+/g, '').trim();
              const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
              const isVisible = (el) => {
                const r = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
              };
              const modalSelectors = [
                '.notice-list-modal',
                '.ant-modal-wrap',
                '.ant-modal',
                '.el-dialog',
                '.el-dialog__wrapper',
                '[role="dialog"]',
                '[class*="modal"]',
                '[class*="Modal"]',
                '[class*="popup"]',
                '[class*="Popup"]',
                '[class*="activity"]',
                '[class*="Activity"]',
                '[class*="campaign"]',
                '[class*="Campaign"]',
                '[class*="remind"]',
                '[class*="Remind"]',
                '[class*="dialog"]',
                '[class*="Dialog"]'
              ].join(',');
              const dangerousTerms = ['发布', '立即发布', '继续发布', '保存并发布', '确认发布', '提交发布', '保存并移入待发布', '移入待发布'];
              const noticeTerms = ['公告', '通知', '活动', '重要提醒', '最新特惠', '忽略提示', '我知道', '知道了'];
              const classTerms = ['notice-list-modal', 'important-remind', 'comm-vip-tips-modal', 'activity', 'campaign'];
              const candidates = Array.from(document.querySelectorAll(modalSelectors))
                .map((el, index) => ({el, index}))
                .filter(item => {
                  const el = item.el;
                  if (!isVisible(el) || el.classList.contains('ant-modal-mask')) return false;
                  const text = norm(el.innerText || el.textContent);
                  const cls = String(el.className || '');
                  if (dangerousTerms.some(term => text.includes(norm(term)))) return false;
                  if (text.includes('从图片银行选择') || text.includes('图片银行的分组')) return false;
                  return noticeTerms.some(term => text.includes(norm(term)))
                    || classTerms.some(term => cls.includes(term));
                });
              candidates.sort((a, b) => {
                const styleA = window.getComputedStyle(a.el);
                const styleB = window.getComputedStyle(b.el);
                const zA = Number.parseInt(styleA.zIndex || '0', 10) || 0;
                const zB = Number.parseInt(styleB.zIndex || '0', 10) || 0;
                return zB - zA || b.index - a.index;
              });
              const removables = [];
              const seen = new Set();
              for (const item of candidates) {
                const removable = item.el.closest('.ant-modal-wrap, .el-dialog__wrapper, [role="dialog"]') || item.el;
                if (!removable || seen.has(removable)) continue;
                seen.add(removable);
                removables.push(removable);
              }
              if (!removables.length) return {removed:false, reason:'no_notice_modal'};
              const removedItems = removables.map(el => ({
                text: textOf(el).slice(0, 300),
                cls: String(el.className || ''),
              }));
              for (const removable of removables) {
                removable.remove();
              }
              Array.from(document.querySelectorAll('.ant-modal-mask, .modal-backdrop, [class*="modal-mask"]'))
                .filter(isVisible)
                .forEach(mask => {
                  try { mask.remove(); } catch (_) { mask.style.display = 'none'; }
                });
              return {
                removed:true,
                removed_count: removedItems.length,
                text: removedItems[0]?.text || '',
                cls: removedItems[0]?.cls || '',
                removed_items: removedItems,
              };
            }''') or {'removed': False, 'reason': 'empty_result'}
        except Exception as exc:  # noqa: BLE001 - best-effort modal cleanup fallback.
            return {'removed': False, 'reason': str(exc)[:240]}

    def _wait_for_body_text(self, page: Page, terms: list[str], timeout: int = 20000) -> bool:
        if self._is_visible_dxm_editor_page(page):
            settle_seconds = min(3.0, max(0.2, timeout / 1000))
            self._trace_workflow_event(
                'body_text_visible_editor_settle:start',
                terms=terms,
                timeout=timeout,
                settle_seconds=settle_seconds,
                current_url=getattr(page, 'url', None),
                human_step='等待可见编辑页自然加载',
            )
            time.sleep(settle_seconds)
            self._trace_workflow_event(
                'body_text_visible_editor_settle:done',
                current_url=getattr(page, 'url', None),
                human_step='可见编辑页静置完成',
            )
            return True
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

    def _wait_for_body_text_with_runtime(self, page: Page, terms: list[str], timeout: int = 20000) -> bool:
        deadline = time.monotonic() + max(0.5, timeout / 1000)
        last_result: dict[str, Any] | None = None
        last_error: str | None = None
        attempt = 0
        self._trace_workflow_event(
            'body_text_runtime_wait:start',
            terms=terms,
            timeout=timeout,
            current_url=getattr(page, 'url', None),
            human_step='等待编辑页正文出现',
        )
        script = r'''(terms) => {
          const text = document.body ? String(document.body.innerText || document.body.textContent || '') : '';
          const readyTerm = (terms || []).find((term) => text.includes(String(term || ''))) || null;
          const compact = text.replace(/\s+/g, '');
          const loading = compact.includes('LOADING') || compact.includes('加载中') || compact.includes('Loading');
          return {
            ready: Boolean(readyTerm),
            ready_term: readyTerm,
            loading,
            text_excerpt: text.replace(/\s+/g, ' ').trim().slice(0, 300),
            title: document.title || '',
            url: location.href,
          };
        }'''
        while True:
            attempt += 1
            remaining_ms = int(max(100, min(1200, (deadline - time.monotonic()) * 1000)))
            try:
                result = self._evaluate_page_function_with_runtime_timeout(
                    page,
                    script,
                    terms,
                    timeout=remaining_ms,
                )
                last_result = result if isinstance(result, dict) else {'value': result}
                if last_result.get('ready'):
                    self._trace_workflow_event(
                        'body_text_runtime_wait:ready',
                        attempt=attempt,
                        ready_term=last_result.get('ready_term'),
                        current_url=last_result.get('url') or getattr(page, 'url', None),
                        human_step='编辑页正文已出现',
                    )
                    return True
            except Exception as exc:  # noqa: BLE001 - runtime polling must stay bounded.
                last_error = str(exc)[:240]
                self._trace_workflow_event(
                    'body_text_runtime_wait:probe_error',
                    attempt=attempt,
                    error=last_error,
                    current_url=getattr(page, 'url', None),
                    human_step='编辑页正文探测重试',
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(0.35, max(0.05, remaining)))
        self._trace_workflow_event(
            'body_text_runtime_wait:timeout',
            attempts=attempt,
            last_error=last_error,
            last_result=last_result,
            current_url=getattr(page, 'url', None),
            human_step='编辑页正文等待超时',
        )
        return False

    def _inspect_data_acquisition_ready_state(self, page: Page, terms: list[str]) -> dict[str, Any]:
        if os.name == 'nt' and not self._is_headless() and self._is_data_acquisition_page_url(page):
            return self._inspect_data_acquisition_ready_state_with_runtime(page, terms)
        locator_result = self._inspect_data_acquisition_ready_state_with_locators(page, terms)
        if locator_result.get('ready') or locator_result.get('locator_probe_available'):
            return locator_result
        return self._inspect_data_acquisition_ready_state_with_runtime(page, terms)

    def _inspect_data_acquisition_ready_state_with_runtime(self, page: Page, terms: list[str]) -> dict[str, Any]:
        encoded_terms = json.dumps([str(term) for term in terms], ensure_ascii=False)
        script = r'''() => {
          const terms = __DXM_READY_TERMS__;
          const visible = (el) => {
            if (!el) return false;
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none' && style.opacity !== '0';
          };
          const textOf = (el) => String(el && el.textContent || '').replace(/\s+/g, ' ').trim();
          const limitedText = (selector, limit = 80) => Array.from(document.querySelectorAll(selector))
            .slice(0, limit)
            .map(textOf)
            .filter(Boolean)
            .join(' ')
            .slice(0, 1200);
          const pageText = [
            limitedText('nav, header, [role="navigation"], .breadcrumb, .page-title, .title, h1, h2, h3', 40),
            limitedText('input[placeholder], textarea[placeholder], button, a, [role="tab"], .ant-tabs-tab, .el-tabs__item', 80),
            limitedText('.vxe-toolbar, .vxe-table, .ant-table, table', 20),
          ].filter(Boolean).join(' ');
          const compact = pageText.replace(/\s+/g, '');
          const readyTerm = terms.find(term => pageText.includes(term) || compact.includes(String(term).replace(/\s+/g, '')));
          const url = String(location.href || '');
          const dataAcquisitionUrl = /dataAcquisition|productCrawl/i.test(url);
          const loadingNodes = Array.from(document.querySelectorAll(
            '.ant-spin-spinning, .vxe-loading, .vxe-loading--wrapper, .el-loading-mask'
          )).filter(visible).slice(0, 20);
          const loadingText = loadingNodes.map(textOf).join('');
          const loading = (
            loadingNodes.length > 0
            || compact.includes('LOADING')
            || compact.includes('加载中')
            || compact.includes('正在加载')
          ) && !readyTerm;
          const rows = document.querySelectorAll('tr.vxe-body--row, .vxe-body--row, .ant-table-row').length;
          const inputs = document.querySelectorAll('input, textarea').length;
          const firstInput = document.querySelector('input, textarea');
          const firstInputRect = firstInput ? (() => {
            const r = firstInput.getBoundingClientRect();
            return {x:r.x, y:r.y, w:r.width, h:r.height};
          })() : null;
          const startCollect = Array.from(document.querySelectorAll('button,a,[role="button"]')).find(el => {
            if (!el) return false;
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            if (!(r.width > 0 && r.height > 0) || style.visibility === 'hidden' || style.display === 'none') return false;
            const text = String(el.textContent || '').replace(/\s+/g, '').trim();
            return text === '开始采集';
          });
          const startCollectRect = startCollect ? (() => {
            const r = startCollect.getBoundingClientRect();
            return {x:r.x, y:r.y, w:r.width, h:r.height};
          })() : null;
          const claimActions = Array.from(document.querySelectorAll('button,a,[role="button"],span'))
            .filter(visible)
            .map(el => String(el.textContent || '').replace(/\s+/g, '').trim())
            .filter(text => ['认领','领取','认领到采集箱','领取到采集箱'].includes(text));
          const formReady = Boolean(firstInputRect);
          const interactive = formReady || (inputs > 0 && document.querySelectorAll('button, a').length > 0);
          const existingClaimReady = dataAcquisitionUrl && claimActions.length > 0 && !loading;
          const ready = dataAcquisitionUrl
            ? existingClaimReady
            : (Boolean(readyTerm) || interactive) && !loading;
          const resolvedReadyTerm = dataAcquisitionUrl
            ? (ready ? 'existing_claim_action_ready' : null)
            : (ready ? (readyTerm || 'interactive_ready') : null);
          return {
            ready,
            ready_term: resolvedReadyTerm,
            loading,
            loading_count: loadingNodes.length,
            rows,
            inputs,
            claim_count: claimActions.length,
            has_collect_form: Boolean(firstInputRect || startCollectRect),
            first_input_rect: dataAcquisitionUrl ? null : firstInputRect,
            start_collect_rect: null,
            text_excerpt: pageText.slice(0, 500),
            url,
            title: document.title,
            loading_text: loadingText.slice(0, 200),
          };
        }'''.replace('__DXM_READY_TERMS__', encoded_terms)
        self._trace_workflow_event(
            'data_acquisition_ready:runtime_probe_start',
            current_url=getattr(page, 'url', None),
        )
        try:
            result = self._evaluate_zero_arg_page_function_with_runtime_timeout(page, script, timeout=2000)
        except Exception as exc:
            self._trace_workflow_event(
                'data_acquisition_ready:runtime_probe_failed',
                current_url=getattr(page, 'url', None),
                error=str(exc)[:240],
            )
            result = None
        if isinstance(result, dict):
            self._trace_workflow_event(
                'data_acquisition_ready:runtime_probe_done',
                result={
                    'ready': result.get('ready'),
                    'loading': result.get('loading'),
                    'loading_count': result.get('loading_count'),
                    'rows': result.get('rows'),
                    'inputs': result.get('inputs'),
                    'claim_count': result.get('claim_count'),
                    'has_collect_form': bool(result.get('has_collect_form')),
                },
            )
            return result
        return {
            'ready': False,
            'ready_term': None,
            'loading': False,
            'loading_count': 0,
            'rows': 0,
            'inputs': 0,
            'text_excerpt': '',
            'url': getattr(page, 'url', ''),
            'title': '',
            'loading_text': '',
            'probe_error': 'data_acquisition_ready_probe_returned_non_object',
        }

    def _is_data_acquisition_page_url(self, page: Page) -> bool:
        page_url = str(getattr(page, 'url', '') or '')
        return 'dianxiaomi.com' in page_url and (
            'dataAcquisition' in page_url or 'productCrawl' in page_url
        )

    def _inspect_data_acquisition_ready_state_with_locators(self, page: Page, terms: list[str]) -> dict[str, Any]:
        try:
            source_input = page.locator(
                'textarea[placeholder*="产品的网址"], '
                'textarea[placeholder*="产品"], '
                'input[placeholder*="产品的网址"]'
            ).first
            start_collect = page.locator(
                'button:has-text("开始采集"), '
                'a:has-text("开始采集"), '
                '[role="button"]:has-text("开始采集")'
            ).first
        except Exception:
            return {'ready': False, 'locator_probe_available': False}

        input_rect = self._locator_bounding_box(source_input, timeout=1800)
        start_rect = self._locator_bounding_box(start_collect, timeout=1800)
        loading_state = self._data_acquisition_visible_loading_state(page)
        loading = bool(loading_state.get('loading'))
        claim_count = self._count_exact_data_acquisition_claim_actions(page)
        ready = bool(claim_count > 0 and not loading)
        page_url = str(getattr(page, 'url', '') or '')
        if os.name == 'nt' and not self._is_headless() and self._is_data_acquisition_page_url(page):
            page_title = ''
        else:
            try:
                page_title = page.title()
            except Exception:
                page_title = ''
        text_excerpt = ' '.join(str(term) for term in terms)
        if claim_count:
            text_excerpt = f'{text_excerpt} 已有认领按钮'
        elif input_rect or start_rect:
            text_excerpt = f'{text_excerpt} 店小秘采集输入区'
        return {
            'ready': ready,
            'ready_term': 'existing_claim_action_ready' if ready else None,
            'loading': loading,
            'loading_count': loading_state.get('loading_count', 0),
            'rows': claim_count,
            'inputs': 0,
            'claim_count': claim_count,
            'has_collect_form': bool(input_rect or start_rect),
            'first_input_rect': None,
            'start_collect_rect': None,
            'text_excerpt': text_excerpt.strip(),
            'url': page_url,
            'title': page_title,
            'loading_text': loading_state.get('loading_text', ''),
            'locator_probe_available': bool(claim_count or input_rect or start_rect),
        }

    def _locator_bounding_box(self, locator: Any, *, timeout: int = 1500) -> dict[str, float] | None:
        try:
            rect = locator.bounding_box(timeout=timeout)
        except Exception:
            return None
        if not rect:
            return None
        width = float(rect.get('width') or 0)
        height = float(rect.get('height') or 0)
        if width <= 0 or height <= 0:
            return None
        return {
            'x': float(rect.get('x') or 0),
            'y': float(rect.get('y') or 0),
            'w': width,
            'h': height,
        }

    def _wait_for_page_ready(
        self,
        page: Page,
        terms: list[str],
        *,
        label: str,
        timeout: int = 60000,
        dismiss_strategy: str = 'full',
    ) -> dict[str, Any]:
        self._trace_workflow_event('wait_ready:start', label=label, terms=terms, timeout=timeout, current_url=getattr(page, 'url', None), dismiss_strategy=dismiss_strategy)
        deadline = time.monotonic() + timeout / 1000
        last: dict[str, Any] = {}
        last_trace_at = 0.0
        data_acquisition_dismissed_once = False
        data_acquisition_scan = dismiss_strategy in {'data_acquisition', 'data_acquisition_no_dismiss'}
        if data_acquisition_scan:
            self._trace_workflow_event('wait_ready:settle', label=label, seconds=3.0)
            time.sleep(3.0)
            operable = self._inspect_data_acquisition_ready_state(page, terms)
            if operable.get('ready'):
                self._trace_workflow_event('wait_ready:ready', label=label, result=operable)
                return operable
        while time.monotonic() < deadline:
            data_acquisition_scan = dismiss_strategy in {'data_acquisition', 'data_acquisition_no_dismiss'}
            if dismiss_strategy in {'none', 'data_acquisition_no_dismiss'}:
                pass
            elif dismiss_strategy == 'data_acquisition':
                if not data_acquisition_dismissed_once:
                    data_acquisition_dismissed_once = True
                    self._dismiss_data_acquisition_blocking_modals(page)
            else:
                self._dismiss_blocking_modals(page)
            if data_acquisition_scan:
                last = self._inspect_data_acquisition_ready_state(page, terms)
            else:
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
                self._trace_workflow_event('wait_ready:ready', label=label, result=last)
                return last
            now = time.monotonic()
            if now - last_trace_at >= 5:
                last_trace_at = now
                self._trace_workflow_event('wait_ready:poll', label=label, result=last)
            if data_acquisition_scan:
                time.sleep(1.0)
            else:
                page.wait_for_timeout(1000)
        excerpt = (last.get('text_excerpt') or '').replace('\n', ' ')[:180]
        self._trace_workflow_event('wait_ready:timeout', label=label, result=last)
        raise RuntimeError(
            f'{label} {timeout // 1000} 秒内仍未加载完成；'
            f'请检查网络、店小秘接口或页面是否被遮罩阻塞。'
            f'最后状态 loading={last.get("loading")} rows={last.get("rows")} inputs={last.get("inputs")} text={excerpt}'
        )

    def _open_editor_page_for_product(self, page: Page, product_query: str, store_name: str | None = None) -> Page:
        draft_url = WORKFLOW_TARGETS['draft_box']['url']
        self._goto_with_live_hud(page, draft_url, wait_until='domcontentloaded', timeout=45000)
        self._wait_for_page_ready(
            page,
            WORKFLOW_READY_TERMS['draft_box'],
                label='速卖通商品箱',
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
        self._reapply_live_hud_if_available(editor_page)
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
        visible_draft_box = (
            os.name == 'nt'
            and not self._is_headless()
            and 'dianxiaomi.com' in str(getattr(page, 'url', '') or '')
            and 'smtProductList/draft' in str(getattr(page, 'url', '') or '')
        )
        self._trace_workflow_event(
            'draft_box_search:start',
            product_query=product_query,
            store_name=store_name,
            human_step='准备搜索商品箱',
        )
        if not product_query and not store_name:
            self._trace_workflow_event(
                'draft_box_search:skipped',
                reason='empty_query_and_store',
                human_step='跳过商品箱搜索',
            )
            return
        if store_name:
            self._trace_workflow_event(
                'draft_box_search:store_select_start',
                store_name=store_name,
                human_step='选择店铺',
            )
            if visible_draft_box:
                self._trace_workflow_event(
                    'draft_box_search:store_select_skipped_visible',
                    store_name=store_name,
                    reason='default_all_store_plus_source_url_row_match',
                    human_step='可见浏览器跳过店铺筛选',
                )
            else:
                page.evaluate(r'''(store) => {
          const norm = (s) => String(s || '').replace(/\s+/g, '').trim();
          const scoped = Array.from(document.querySelectorAll('.shop-con .d-tag-group-item, .shop-con .d-tag-group-item *'));
          const storeEl = scoped.find(el => norm(el.innerText || el.textContent) === norm(store));
          const storeTarget = storeEl && (storeEl.closest('.d-tag-group-item') || storeEl);
          if (storeTarget) storeTarget.dispatchEvent(new MouseEvent('click', {bubbles:true}));
        }''', store_name)
                page.wait_for_timeout(1200)
                dismissed = self._dismiss_blocking_modals_if_visible(page, context='draft_box_search:after_store_select')
                self._trace_workflow_event(
                    'draft_box_search:store_select_done',
                    store_name=store_name,
                    dismissed=dismissed,
                    human_step='店铺筛选已处理',
                )
        if product_query is not None or store_name:
            self._trace_workflow_event(
                'draft_box_search:submit_start',
                product_query=product_query,
                human_step='提交商品箱搜索',
            )
            if visible_draft_box:
                try:
                    visible_search = self._submit_visible_draft_box_search(page, product_query or '')
                    if not visible_search.get('ok'):
                        raise RuntimeError(visible_search.get('reason') or '未找到可编辑商品箱搜索框')
                    self._trace_workflow_event(
                        'draft_box_search:submit_visible_controls_done',
                        product_query=product_query,
                        strategy=visible_search.get('strategy'),
                        input=visible_search.get('input'),
                        clicked=visible_search.get('clicked'),
                        human_step='已点击商品箱搜索',
                    )
                except Exception as exc:
                    self._trace_workflow_event(
                        'draft_box_search:submit_visible_controls_failed',
                        product_query=product_query,
                        error=str(exc)[:240],
                        human_step='商品箱搜索失败',
                    )
                    raise RuntimeError(f'商品箱搜索控件操作失败：{exc}')
            else:
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
        if visible_draft_box:
            page.wait_for_timeout(2500)
            wait_result = {
                'ready': True,
                'ready_term': 'visible_draft_box_search_settle',
                'loading': None,
                'rows': None,
            }
        else:
            wait_result = self._wait_for_page_ready(
                page,
                ['标题/产品ID', '暂无数据', '移入待发布', '编辑'],
                label='商品箱搜索结果',
                timeout=30000,
            )
        self._trace_workflow_event(
            'draft_box_search:wait_done',
            wait_result={
                'ready': wait_result.get('ready') if isinstance(wait_result, dict) else None,
                'ready_term': wait_result.get('ready_term') if isinstance(wait_result, dict) else None,
                'rows': wait_result.get('rows') if isinstance(wait_result, dict) else None,
                'loading': wait_result.get('loading') if isinstance(wait_result, dict) else None,
            },
            human_step='商品箱搜索完成',
        )
        dismissed = self._dismiss_blocking_modals_if_visible(page, context='draft_box_search:after_search')
        self._trace_workflow_event(
            'draft_box_search:dismiss_done',
            dismissed=dismissed,
            human_step='检查搜索结果弹窗',
        )

    def _settle_visible_draft_box(self, page: Page) -> dict[str, Any]:
        self._trace_workflow_event(
            'visible_draft_box:settle_start',
            seconds=3,
            current_url=getattr(page, 'url', None),
            human_step='等待商品箱页面自行加载',
        )
        time.sleep(3)
        result = {
            'ready': True,
            'ready_term': 'visible_draft_box_opened_after_3s_settle',
            'loading': None,
            'rows': None,
            'inputs': None,
            'text_excerpt': '商品箱页面已打开并静置，后续定位商品时再读取页面内容。',
            'url': getattr(page, 'url', None),
            'title': '',
            'read_source': 'open_only_settle',
            'read_error': '',
        }
        self._trace_workflow_event(
            'visible_draft_box:settle_done',
            result={
                'ready': result['ready'],
                'ready_term': result['ready_term'],
                'loading': result['loading'],
                'rows': result['rows'],
                'inputs': result['inputs'],
                'read_source': result.get('read_source'),
                'read_error': result.get('read_error'),
                'text_excerpt': result['text_excerpt'][:300],
            },
            human_step='商品箱页面静置完成',
        )
        return result

    def _inspect_visible_draft_box_state(self, page: Page) -> dict[str, Any]:
        text = ''
        read_error = ''
        read_source = 'locator'
        try:
            text = page.locator('body').inner_text(timeout=2000)
        except Exception as exc:
            read_error = str(exc)[:240]
            try:
                text = str(self._evaluate_zero_arg_page_function_with_runtime_timeout(
                    page,
                    "() => document.body ? (document.body.innerText || document.body.textContent || '') : ''",
                    timeout=1500,
                ) or '')
                read_source = 'runtime_evaluate'
                read_error = ''
            except Exception as fallback_exc:
                read_source = 'unreadable'
                read_error = f'{read_error}; fallback={str(fallback_exc)[:160]}'
        ready_term = next((term for term in WORKFLOW_READY_TERMS['draft_box'] if term in text), None)
        compact = ''.join(str(text or '').split())
        loading = any(term in compact for term in ('LOADING', '加载中', '正在加载')) and not ready_term
        title = ''
        if text:
            try:
                title = page.title()
            except Exception:
                title = ''
        result = {
            'ready': bool(ready_term) and not loading,
            'ready_term': ready_term,
            'loading': loading,
            'rows': text.count('编辑'),
            'inputs': text.count('搜索内容'),
            'text_excerpt': text[:800],
            'url': getattr(page, 'url', None),
            'title': title,
            'read_source': read_source,
            'read_error': read_error,
        }
        return result

    def _submit_visible_draft_box_search(self, page: Page, product_query: str) -> dict[str, Any]:
        return page.evaluate(r'''(frag) => {
          const norm = (s) => String(s || '').replace(/\s+/g, '').trim();
          const visible = (el) => {
            if (!el || !el.getBoundingClientRect) return false;
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 20
              && r.height > 10
              && style.visibility !== 'hidden'
              && style.display !== 'none'
              && style.opacity !== '0';
          };
          const editable = (el) => visible(el) && !el.disabled && !el.readOnly && el.getAttribute('aria-disabled') !== 'true';
          const describe = (el) => {
            const r = el.getBoundingClientRect();
            return {
              tag: el.tagName,
              name: String(el.getAttribute('name') || ''),
              placeholder: String(el.getAttribute('placeholder') || ''),
              cls: String(el.className || ''),
              rect: {x:r.x, y:r.y, w:r.width, h:r.height},
            };
          };
          const inputs = Array.from(document.querySelectorAll('input, textarea')).filter(editable);
          const scoreInput = (input) => {
            const desc = `${input.getAttribute('name') || ''} ${input.getAttribute('placeholder') || ''} ${input.className || ''}`;
            const box = input.getBoundingClientRect();
            let score = 1000;
            if (String(input.getAttribute('name') || '').includes('tableSearchInput')) score -= 500;
            if (norm(desc).includes('搜索内容') || norm(desc).includes('标题') || norm(desc).includes('产品ID')) score -= 180;
            if (box.width >= 180) score -= 90;
            if (box.width >= 260) score -= 60;
            if (input.type === 'hidden') score += 1000;
            return score;
          };
          const input = inputs.sort((a, b) => scoreInput(a) - scoreInput(b))[0];
          if (!input) {
            return {ok:false, reason:'未找到可见可编辑的商品箱搜索框'};
          }
          input.focus();
          input.value = frag || '';
          input.dispatchEvent(new Event('input', {bubbles:true}));
          input.dispatchEvent(new Event('change', {bubbles:true}));
          const controls = Array.from(document.querySelectorAll('button,a,[role="button"],span,div'))
            .filter(visible)
            .map(el => {
              const text = norm(el.innerText || el.textContent);
              const target = el.closest('button,a,[role="button"]') || el;
              const tr = target.getBoundingClientRect();
              return {
                el,
                target,
                text,
                rect: {x:tr.x, y:tr.y, w:tr.width, h:tr.height},
                distance: Math.abs(tr.top - input.getBoundingClientRect().top) + Math.max(0, tr.left - input.getBoundingClientRect().right),
              };
            })
            .filter(item => item.text === '搜索' || item.text.endsWith('搜索'));
          const button = controls.sort((a, b) => a.distance - b.distance)[0];
          if (button) {
            button.target.dispatchEvent(new MouseEvent('click', {bubbles:true, cancelable:true, view:window}));
            return {ok:true, strategy:'dom_visible_input_click_button', input:describe(input), clicked:button.text};
          }
          input.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', code:'Enter', bubbles:true, cancelable:true}));
          input.dispatchEvent(new KeyboardEvent('keyup', {key:'Enter', code:'Enter', bubbles:true, cancelable:true}));
          return {ok:true, strategy:'dom_visible_input_enter', input:describe(input), clicked:null};
        }''', product_query)

    def _find_draft_box_row(
        self,
        page: Page,
        product_query: str | None = None,
        store_name: str | None = None,
        claim_mark: str | None = None,
        target_source_urls: list[str] | None = None,
    ) -> dict[str, Any]:
        payload = {
            'frag': product_query,
            'store': store_name,
            'claimMark': claim_mark,
            'targetSourceUrls': target_source_urls or [],
        }
        self._trace_workflow_event(
            'draft_box_row_find:start',
            product_query=product_query,
            store_name=store_name,
            has_claim_mark=bool(claim_mark),
            target_source_url_count=len(target_source_urls or []),
            human_step='定位商品箱商品行',
        )
        if os.name == 'nt' and os.getenv('DXM_LOGIN_HEADED') == '1' and not self._is_headless():
            runtime_row = self._find_draft_box_row_with_runtime_snapshot(
                page,
                product_query=product_query,
                store_name=store_name,
                claim_mark=claim_mark,
                target_source_urls=target_source_urls or [],
            )
            if runtime_row:
                self._trace_workflow_event(
                    'draft_box_row_find:runtime_done',
                    matched_by=runtime_row.get('matchedBy'),
                    human_step='商品箱商品行定位完成',
                )
                return runtime_row
            self._trace_workflow_event(
                'draft_box_row_find:runtime_missed',
                product_query=product_query,
                human_step='商品箱商品行未找到',
            )
            raise RuntimeError(f'未找到目标商品行：{product_query or "首个可操作商品"}')
        try:
            row_info = self._evaluate_page_function_with_runtime_timeout(page, r'''({frag, store, claimMark, targetSourceUrls}) => {
          const rows = Array.from(document.querySelectorAll('tr.vxe-body--row, tr, .ant-table-row, .el-table__row, [class*="vxe-body--row"], [class*="table"] [class*="row"], [class*="list"] [class*="item"]'));
          const normText = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
          const looksAggregate = (text) => (text.match(/创建：/g) || []).length > 1 || (text.match(/移入待发布/g) || []).length > 2;
          const sourceUrls = (row) => Array.from(row.querySelectorAll('a[href]'))
            .map(a => String(a.href || a.getAttribute('href') || ''))
            .filter(url => url.includes('goods_id=') || url.includes('detail.1688.com') || url.includes('yangkeduo.com') || url.includes('aliexpress.com'));
          const sourceKey = (url) => {
            const raw = String(url || '');
            try {
              const parsed = new URL(raw, location.href);
              const goodsId = parsed.searchParams.get('goods_id');
              if (goodsId) return `goods_id:${goodsId}`;
            } catch (_) {}
            const goodsMatch = raw.match(/[?&#]goods_id=(\d+)/);
            if (goodsMatch) return `goods_id:${goodsMatch[1]}`;
            const offerMatch = raw.match(/offer\/(\d+)\.html/);
            if (offerMatch) return `offer:${offerMatch[1]}`;
            const itemMatch = raw.match(/item\/(\d+)\.html/);
            if (itemMatch) return `item:${itemMatch[1]}`;
            return '';
          };
          const sourceUrlMatches = (url, target) => {
            if (url === target || url.includes(target) || target.includes(url)) return true;
            const urlKey = sourceKey(url);
            const targetKey = sourceKey(target);
            return Boolean(urlKey && targetKey && urlKey === targetKey);
          };
          const claim = claimMark;
          const targetUrls = Array.isArray(targetSourceUrls) ? targetSourceUrls.filter(Boolean).map(String) : [];
          const hasExplicitTarget = Boolean(claim) || Boolean(frag) || targetUrls.length > 0;
          const hasTargetSource = (row) => {
            if (!targetUrls.length) return false;
            const urls = sourceUrls(row);
            return urls.some(url => targetUrls.some(target => sourceUrlMatches(url, target)));
          };
          const candidates = rows.map((tr, idx) => ({idx, text:normText(tr)})).filter(x => {
            if (!x.text || looksAggregate(x.text)) return false;
            if (store && !x.text.includes(`「${store}」`) && !x.text.includes(store)) return false;
            if (claim && x.text.includes(claim)) return true;
            if (hasTargetSource(rows[x.idx])) return true;
            if (targetUrls.length) {
              const visibleSources = sourceUrls(rows[x.idx]);
              return Boolean(frag) && x.text.includes(frag) && visibleSources.length === 0;
            }
            if (frag) return x.text.includes(frag);
            if (hasExplicitTarget) return false;
            return ['移入待发布','编辑','发布','更多'].some(k => x.text.includes(k));
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
              return {txt, tag: el.tagName, cls: String(el.className || ''), href: String(el.href || el.getAttribute('href') || ''), rect: {x:r.x,y:r.y,w:r.width,h:r.height}};
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
              return {txt, tag: el.tagName, cls: String(el.className || ''), href: String(el.href || el.getAttribute('href') || ''), rect: {x:r.x,y:r.y,w:r.width,h:r.height}};
            }).filter(Boolean);
            return {ok:true, rowIndex:sourceMatches[0].idx, rowText:sourceMatches[0].text.slice(0,700), sourceUrls:sourceUrls(row), actions, matchedBy:'source_url'};
          }
          if (frag && candidates.length > 1) {
            return {ok:false, ambiguous:true, matches:candidates.map(x => ({rowIndex:x.idx, rowText:x.text.slice(0,300)}))};
          }
          const picked = candidates.find(x => !x.text.includes('备注:')) || candidates[0] || null;
          if (!picked) return {ok:false, matches:candidates};
          const row = rows[picked.idx];
          const pickedSourceUrls = sourceUrls(row);
          const actions = Array.from(row.querySelectorAll('*')).map(el => {
            const txt = normText(el);
            const r = el.getBoundingClientRect();
            if (!txt || r.width < 5 || r.height < 5) return null;
            if (!['移入待发布','编辑','发布','更多'].includes(txt)) return null;
            return {txt, tag: el.tagName, cls: String(el.className || ''), href: String(el.href || el.getAttribute('href') || ''), rect: {x:r.x,y:r.y,w:r.width,h:r.height}};
          }).filter(Boolean);
          const matchedBy = frag && picked.text.includes(frag)
            ? (targetUrls.length && pickedSourceUrls.length === 0 ? 'title_without_visible_source' : 'title')
            : 'first_operable';
          return {ok:true, rowIndex:picked.idx, rowText:picked.text.slice(0,700), sourceUrls:pickedSourceUrls, actions, matchedBy};
        }''', payload, timeout=3000)
        except Exception as exc:
            self._trace_workflow_event(
                'draft_box_row_find:failed',
                product_query=product_query,
                error=str(exc)[:240],
                human_step='商品箱商品行扫描失败',
            )
            raise RuntimeError(f'商品箱商品行扫描失败：{exc}') from exc
        self._trace_workflow_event(
            'draft_box_row_find:done',
            ok=bool(row_info and row_info.get('ok')),
            matched_by=(row_info or {}).get('matchedBy') if isinstance(row_info, dict) else None,
            match_count=len((row_info or {}).get('matches') or []) if isinstance(row_info, dict) else 0,
            human_step='商品箱商品行扫描完成',
        )
        if not row_info or not row_info.get('ok'):
            if row_info and row_info.get('ambiguous'):
                raise RuntimeError(f'目标商品行不唯一，请提供更精确的商品标题或唯一标识：{product_query}')
            raise RuntimeError(f'未找到目标商品行：{product_query or "首个可操作商品"}')
        return row_info

    def _find_draft_box_row_with_runtime_snapshot(
        self,
        page: Page,
        *,
        product_query: str | None,
        store_name: str | None,
        claim_mark: str | None,
        target_source_urls: list[str],
    ) -> dict[str, Any] | None:
        self._trace_workflow_event(
            'draft_box_row_find:runtime_start',
            human_step='读取当前商品箱列表',
        )
        self._force_foreground_dxm_window()
        payload = {
            'frag': product_query,
            'store': store_name,
            'claimMark': claim_mark,
            'targetSourceUrls': target_source_urls or [],
        }
        try:
            result = self._evaluate_page_function_with_runtime_timeout(page, r'''({frag, store, claimMark, targetSourceUrls}) => {
              const textOf = (el) => (el ? (el.innerText || el.textContent || '') : '').replace(/\s+/g, ' ').trim();
              const bodyText = textOf(document.body);
              const compactBody = bodyText.replace(/\s+/g, '');
              const visible = (el) => {
                if (!el || !el.getBoundingClientRect) return false;
                const r = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
              };
              const rows = Array.from(document.querySelectorAll('tr.vxe-body--row, tr, .ant-table-row, .el-table__row, [class*="vxe-body--row"], [class*="table"] [class*="row"], [class*="list"] [class*="item"]'))
                .filter(visible);
              const rowText = (row) => textOf(row);
              const looksAggregate = (text) => (text.match(/创建：/g) || []).length > 1 || (text.match(/移入待发布/g) || []).length > 2;
              const sourceUrls = (row) => Array.from(row.querySelectorAll('a[href]'))
                .map(a => String(a.href || a.getAttribute('href') || ''))
                .filter(url => url.includes('goods_id=') || url.includes('detail.1688.com') || url.includes('yangkeduo.com') || url.includes('aliexpress.com'));
              const sourceKey = (url) => {
                const raw = String(url || '');
                try {
                  const parsed = new URL(raw, location.href);
                  const goodsId = parsed.searchParams.get('goods_id');
                  if (goodsId) return `goods_id:${goodsId}`;
                } catch (_) {}
                const goodsMatch = raw.match(/[?&#]goods_id=(\d+)/);
                if (goodsMatch) return `goods_id:${goodsMatch[1]}`;
                const offerMatch = raw.match(/offer\/(\d+)\.html/);
                if (offerMatch) return `offer:${offerMatch[1]}`;
                const itemMatch = raw.match(/item\/(\d+)\.html/);
                if (itemMatch) return `item:${itemMatch[1]}`;
                return '';
              };
              const sourceUrlMatches = (url, target) => {
                if (url === target || url.includes(target) || target.includes(url)) return true;
                const urlKey = sourceKey(url);
                const targetKey = sourceKey(target);
                return Boolean(urlKey && targetKey && urlKey === targetKey);
              };
              const targetUrls = Array.isArray(targetSourceUrls) ? targetSourceUrls.filter(Boolean).map(String) : [];
              const hasTargetSource = (row) => {
                if (!targetUrls.length) return false;
                const urls = sourceUrls(row);
                return urls.some(url => targetUrls.some(target => sourceUrlMatches(url, target)));
              };
              const rectOf = (el) => {
                const r = el.getBoundingClientRect();
                return {x:r.x, y:r.y, w:r.width, h:r.height};
              };
              const actionCandidates = (row) => Array.from(row.querySelectorAll('a,button,[role="button"],span,div'))
                .filter(visible)
                .map(el => {
                  const text = textOf(el).replace(/\s+/g, '');
                  const target = el.closest('a,button,[role="button"]') || el;
                  return {txt:text, tag:target.tagName, cls:String(target.className || ''), href:String(target.href || target.getAttribute('href') || ''), rect:rectOf(target)};
                })
                .filter(item => ['移入待发布','编辑','发布','更多'].includes(item.txt));
              const loading = Boolean(
                compactBody.includes('LOADING') ||
                compactBody.includes('加载中') ||
                document.querySelector('.ant-spin-spinning,.el-loading-mask,.vxe-loading,.loading,[class*="loading"]')
              );
              const empty = compactBody.includes('暂无数据') || compactBody.includes('暂无记录') || compactBody.includes('没有数据');
              const candidates = rows.map((row, idx) => ({row, idx, text:rowText(row)})).filter(item => {
                if (!item.text || looksAggregate(item.text)) return false;
                if (!['移入待发布','编辑','发布','更多'].some(k => item.text.includes(k))) return false;
                if (store && !item.text.includes(`「${store}」`) && !item.text.includes(store)) return false;
                if (claimMark && item.text.includes(claimMark)) return true;
                if (hasTargetSource(item.row)) return true;
                if (frag) return item.text.includes(frag) || item.text.includes(String(frag).slice(0, 18));
                return true;
              });
              if (!candidates.length) {
                return {
                  ok:false,
                  reason: empty ? 'draft_box_empty' : (loading ? 'draft_box_loading' : 'draft_box_no_match'),
                  loading,
                  empty,
                  rowCount: rows.length,
                  textExcerpt: bodyText.slice(0, 500)
                };
              }
              const claimMatches = claimMark ? candidates.filter(item => item.text.includes(claimMark)) : [];
              const sourceMatches = targetUrls.length ? candidates.filter(item => hasTargetSource(item.row)) : [];
              const titleMatches = frag ? candidates.filter(item => item.text.includes(frag) || item.text.includes(String(frag).slice(0, 18))) : [];
              const pickedMatches = claimMatches.length ? claimMatches : (sourceMatches.length ? sourceMatches : titleMatches);
              if (pickedMatches.length > 1) {
                return {ok:false, ambiguous:true, matches:pickedMatches.map(item => ({rowIndex:item.idx, rowText:item.text.slice(0,300), sourceUrls:sourceUrls(item.row)}))};
              }
              const picked = pickedMatches[0] || candidates[0];
              const actions = actionCandidates(picked.row);
              const edit = actions.find(item => item.txt === '编辑');
              if (!edit) {
                return {ok:false, reason:'draft_box_edit_missing', rowText:picked.text.slice(0, 500), actions};
              }
              return {
                ok:true,
                rowIndex:picked.idx,
                rowText:picked.text.slice(0,700),
                sourceUrls:sourceUrls(picked.row),
                actions:[edit, ...actions.filter(item => item.txt !== '编辑')],
                matchedBy: claimMatches.length ? 'claim_mark' : (sourceMatches.length ? 'source_url' : 'title')
              };
            }''', payload, timeout=2500)
        except Exception as exc:
            self._trace_workflow_event(
                'draft_box_row_find:runtime_failed',
                error=str(exc)[:240],
                human_step='商品箱列表读取失败',
            )
            raise RuntimeError('读取商品箱列表超时或失败。请确认真实店小秘窗口已正常加载商品箱；系统不会继续保存或发布。') from exc

        self._trace_workflow_event(
            'draft_box_row_find:runtime_result',
            ok=bool(isinstance(result, dict) and result.get('ok')),
            reason=(result or {}).get('reason') if isinstance(result, dict) else None,
            row_count=(result or {}).get('rowCount') if isinstance(result, dict) else None,
            loading=(result or {}).get('loading') if isinstance(result, dict) else None,
            empty=(result or {}).get('empty') if isinstance(result, dict) else None,
            human_step='商品箱列表读取完成',
        )
        if isinstance(result, dict) and result.get('ok'):
            return result
        if isinstance(result, dict) and result.get('ambiguous'):
            raise RuntimeError(f'商品箱里匹配到多个目标商品，请先筛选到唯一商品：{product_query}')
        if isinstance(result, dict) and result.get('reason') in {'draft_box_empty', 'draft_box_loading'}:
            raise RuntimeError(
                '真实商品箱当前没有找到本次商品。页面显示暂无数据或仍在加载；请确认商品已经认领到商品箱，或刷新商品箱后重新创建只保存任务。'
            )
        if isinstance(result, dict) and result.get('reason') == 'draft_box_edit_missing':
            raise RuntimeError('已找到商品行，但没有找到“编辑”入口；请确认该商品仍在商品箱草稿列表。')
        return None

    def _find_draft_box_row_with_bounded_locators(
        self,
        page: Page,
        *,
        product_query: str | None,
        store_name: str | None,
        claim_mark: str | None,
        target_source_urls: list[str],
    ) -> dict[str, Any] | None:
        samples: list[dict[str, Any]] = []
        query = str(product_query or '').strip()
        selectors: list[str] = []
        if claim_mark:
            selectors.append(f'text="{claim_mark}"')
        if query:
            selectors.append(f'text="{query}"')
            if len(query) > 18:
                selectors.append(f'text="{query[:18]}"')
        self._trace_workflow_event(
            'draft_box_row_find:bounded_start',
            selector_count=len(selectors),
            human_step='按当前商品标题定位商品箱行',
        )
        for selector in selectors:
            try:
                candidates = page.locator(selector)
            except Exception as exc:
                samples.append({'selector': selector, 'error': str(exc)[:160]})
                continue
            count = min(self._locator_count(candidates), 8)
            samples.append({'selector': selector, 'count': count})
            for index in range(count):
                matched = candidates.nth(index)
                row = self._draft_box_match_container(matched)
                row_text = self._locator_text(row, timeout=800)
                if not row_text:
                    continue
                if store_name and store_name not in row_text and f'「{store_name}」' not in row_text:
                    continue
                if claim_mark and claim_mark not in row_text:
                    continue
                if query and query not in row_text and query[:18] not in row_text:
                    continue
                action = self._draft_box_edit_action_in_container(row)
                if action is None:
                    samples.append({'selector': selector, 'index': index, 'skip': 'edit_action_missing', 'rowText': row_text[:160]})
                    continue
                action_text = self._locator_text(action, timeout=800) or '编辑'
                action_href = self._locator_attribute(action, 'href', timeout=800)
                action_rect = self._locator_box(action, timeout=800)
                if not action_href and not self._rect_has_clickable_area(action_rect):
                    samples.append({'selector': selector, 'index': index, 'skip': 'edit_target_missing', 'rowText': row_text[:160]})
                    continue
                source_urls = self._source_urls_in_container(row)
                return {
                    'ok': True,
                    'rowIndex': index,
                    'rowText': row_text[:700],
                    'sourceUrls': source_urls or list(target_source_urls or []),
                    'actions': [
                        {
                            'txt': '编辑',
                            'tag': 'A' if action_href else 'BUTTON',
                            'cls': '',
                            'href': action_href,
                            'rect': action_rect,
                        }
                    ],
                    'matchedBy': 'bounded_title',
                    'debug': {'samples': samples[:8]},
                }
        self._trace_workflow_event(
            'draft_box_row_find:bounded_no_match',
            samples=samples[:8],
            human_step='当前商品箱列表未找到目标商品',
        )
        return None

    def _draft_box_match_container(self, locator: Any) -> Any:
        for selector in (
            'xpath=ancestor::tr[contains(@class,"vxe-body--row") or contains(@class,"ant-table-row") or contains(@class,"el-table__row")][1]',
            'xpath=ancestor::tr[1]',
            'xpath=ancestor::*[contains(@class,"vxe-body--row") or contains(@class,"ant-table-row") or contains(@class,"el-table__row")][1]',
            'xpath=ancestor::*[contains(@class,"row") or contains(@class,"item")][1]',
        ):
            try:
                candidate = locator.locator(selector)
                if self._locator_count(candidate) > 0:
                    return candidate.first
            except Exception:
                continue
        return locator

    def _draft_box_edit_action_in_container(self, container: Any) -> Any | None:
        for selector in (
            'a',
            'button',
            '[role="button"]',
            'span',
        ):
            try:
                candidates = container.locator(selector).filter(has_text='编辑')
            except Exception:
                continue
            for index in range(min(self._locator_count(candidates), 8)):
                candidate = candidates.nth(index)
                compact = ''.join(str(self._locator_text(candidate, timeout=500) or '').split())
                if compact == '编辑':
                    return candidate
        return None

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
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const norm = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, '').trim();
          const rectOf = (el) => {
            const r = el.getBoundingClientRect();
            return {x:r.x,y:r.y,w:r.width,h:r.height};
          };
          const dangerousTerms = ['发布', '立即发布', '继续发布', '保存并发布', '确认发布', '提交发布', '保存并移入待发布', '移入待发布', '删除'];
          const menus = Array.from(document.querySelectorAll('.ant-dropdown:not(.ant-dropdown-hidden), .ant-dropdown-menu, [role="menu"], .dropdown-menu, .vxe-table--context-menu-wrapper, .vxe-pulldown--panel'))
            .filter(visible);
          const scope = menus.length ? menus[menus.length - 1] : document;
          const candidates = Array.from(scope.querySelectorAll('li.ant-dropdown-menu-item, li, a, button, span, div, [role="menuitem"]'))
            .filter(visible)
            .map(el => {
              const clickable = el.closest('li.ant-dropdown-menu-item,[role="menuitem"],a,button') || el;
              return {
                el,
                clickable,
                text:norm(el),
                clickText:norm(clickable),
                tag:clickable.tagName,
                cls:String(clickable.className || ''),
                rect:rectOf(clickable),
              };
            })
            .filter(item => item.text);
          const safeRemark = candidates
            .filter(item => {
            const label = item.text || item.clickText;
            if (!label.includes('备注')) return false;
            if (dangerousTerms.some(term => item.text.includes(term))) return false;
            if (dangerousTerms.some(term => item.clickText.includes(term))) return false;
            return true;
          })
            .sort((a, b) => {
              const score = (item) => {
                const label = item.text || item.clickText;
                if (['备注','添加备注','修改备注'].includes(label)) return 0;
                if (label.includes('备注') && label.length <= 8) return 1;
                if (['A','BUTTON','LI'].includes(item.tag)) return 2;
                return 3;
              };
              return score(a) - score(b) || a.text.length - b.text.length;
            })[0];
          if (!safeRemark) {
            return {
              ok:false,
              reason:'未找到添加备注入口',
              menu_text: (menus.map(menu => norm(menu)).filter(Boolean).join(' | ') || '').slice(0, 500),
              samples: candidates.map(item => item.text).filter(Boolean).slice(0, 20),
            };
          }
          return {ok:true, text:safeRemark.text, click_text:safeRemark.clickText, tag:safeRemark.tag, rect:safeRemark.rect};
        }''')
        if not add_note or not add_note.get('ok'):
            samples = add_note.get('samples') if isinstance(add_note, dict) else None
            sample_text = f"；菜单项：{' / '.join(samples[:8])}" if isinstance(samples, list) and samples else ""
            reason = (add_note or {}).get('reason') or '未找到添加备注入口'
            raise RuntimeError(f'{reason}{sample_text}')
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
        x = float(rect['x']) + float(rect['w']) / 2
        y = float(rect['y']) + float(rect['h']) / 2
        self._trace_workflow_event('click_rect:start', x=x, y=y, human_step='点击页面按钮')
        self._bring_page_to_front_for_click(page)
        if self._click_point_with_cdp(page, x, y):
            self._trace_workflow_event('click_rect:done', method='cdp', human_step='点击页面按钮')
            return
        if self._click_point_with_native_window(page, x, y):
            self._trace_workflow_event('click_rect:done', method='native_window', human_step='点击页面按钮')
            return
        self._trace_workflow_event('click_rect:mouse_start', human_step='点击页面按钮')
        try:
            page.mouse.click(x, y)
            self._trace_workflow_event('click_rect:done', method='playwright_mouse', human_step='点击页面按钮')
            return
        except Exception as exc:
            self._trace_workflow_event('click_rect:mouse_failed', error=str(exc)[:240], human_step='点击页面按钮')
        raise RuntimeError('真实浏览器点击失败：浏览器输入事件不可用，已停止本次操作。')

    def _click_data_acquisition_claim_rect_center(self, page: Page, rect: dict[str, Any], *, purpose: str) -> None:
        if not isinstance(rect, dict) or not self._rect_has_clickable_area(rect):
            raise RuntimeError(f'{purpose}坐标不可用，已停止本次认领。')
        x = float(rect['x']) + float(rect['w']) / 2
        y = float(rect['y']) + float(rect['h']) / 2
        if os.name == 'nt' and not self._is_headless() and self._is_data_acquisition_page_url(page):
            self._trace_workflow_event(
                'data_acquisition_claim:page_mouse_click_start',
                x=x,
                y=y,
                purpose=purpose,
                human_step=purpose,
            )
            try:
                page.mouse.click(x, y, delay=50)
                self._trace_workflow_event(
                    'data_acquisition_claim:page_mouse_click_done',
                    x=x,
                    y=y,
                    purpose=purpose,
                    method='playwright_mouse',
                    human_step=purpose,
                )
                return
            except Exception as exc:
                self._trace_workflow_event(
                    'data_acquisition_claim:page_mouse_click_failed',
                    x=x,
                    y=y,
                    purpose=purpose,
                    error=str(exc)[:240],
                    human_step=purpose,
                )
        self._click_rect_center(page, rect)

    def _bring_page_to_front_for_click(self, page: Page) -> bool:
        native_front = self._force_foreground_dxm_window()
        if native_front:
            return True
        try:
            self._trace_workflow_event('click_rect:bring_to_front_start', human_step='切换到店小秘窗口')
            bring_to_front = getattr(page, 'bring_to_front', None)
            if callable(bring_to_front):
                bring_to_front()
            time.sleep(0.25)
            self._trace_workflow_event(
                'click_rect:bring_to_front_done',
                native_front=native_front,
                human_step='切换到店小秘窗口',
            )
            return True
        except Exception as exc:
            self._trace_workflow_event(
                'click_rect:bring_to_front_failed',
                error=str(exc)[:240],
                native_front=native_front,
                human_step='切换到店小秘窗口',
            )
            return native_front

    @staticmethod
    def _window_handle_to_int(value: Any) -> int:
        raw_value = getattr(value, 'value', value)
        if raw_value is None:
            return 0
        try:
            return int(raw_value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _native_click_screen_point(
        content_rect: dict[str, Any],
        x: float,
        y: float,
        viewport_metrics: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        viewport_metrics = viewport_metrics if isinstance(viewport_metrics, dict) else {}
        try:
            viewport_width = float(viewport_metrics.get('innerWidth') or viewport_metrics.get('visualViewportWidth') or 0)
        except (TypeError, ValueError):
            viewport_width = 0
        try:
            viewport_height = float(viewport_metrics.get('innerHeight') or viewport_metrics.get('visualViewportHeight') or 0)
        except (TypeError, ValueError):
            viewport_height = 0
        try:
            content_width = float(content_rect.get('width') or 0)
            content_height = float(content_rect.get('height') or 0)
        except (TypeError, ValueError):
            content_width = 0
            content_height = 0
        scale_x = content_width / viewport_width if viewport_width > 0 else 1.0
        scale_y = content_height / viewport_height if viewport_height > 0 else 1.0
        if not 0.5 <= scale_x <= 4.0:
            scale_x = 1.0
        if not 0.5 <= scale_y <= 4.0:
            scale_y = 1.0
        screen_x = int(round(float(content_rect.get('left') or 0) + float(x) * scale_x))
        screen_y = int(round(float(content_rect.get('top') or 0) + float(y) * scale_y))
        return {
            'screen': {'x': screen_x, 'y': screen_y},
            'scale': {'x': scale_x, 'y': scale_y},
            'viewport': viewport_metrics,
        }

    def _browser_viewport_metrics_for_native_click(self, page: Page) -> dict[str, Any]:
        expression = """() => ({
          innerWidth: window.innerWidth,
          innerHeight: window.innerHeight,
          visualViewportWidth: window.visualViewport ? window.visualViewport.width : null,
          visualViewportHeight: window.visualViewport ? window.visualViewport.height : null,
          devicePixelRatio: window.devicePixelRatio || 1,
          screenX: window.screenX,
          screenY: window.screenY,
          outerWidth: window.outerWidth,
          outerHeight: window.outerHeight,
        })"""
        if not self._is_headless() and self._remote_debugging_port:
            try:
                result = self._evaluate_visible_page_function_via_devtools(page, expression, timeout=900)
                if isinstance(result, dict):
                    return result
            except Exception as exc:  # noqa: BLE001 - native click can still fall back to Win32 rectangles.
                self._trace_workflow_event(
                    'click_rect:native_viewport_metrics_failed',
                    error=str(exc)[:240],
                    method='independent_devtools',
                    human_step='识别浏览器窗口位置',
                )
                return {}
        try:
            cdp = page.context.new_cdp_session(page)
        except Exception as exc:  # noqa: BLE001 - native click can still fall back to Win32 rectangles.
            self._trace_workflow_event(
                'click_rect:native_viewport_metrics_skipped',
                error=str(exc)[:240],
                human_step='识别浏览器窗口位置',
            )
            return {}
        try:
            response = cdp.send(
                'Runtime.evaluate',
                {
                    'expression': f'({expression})()',
                    'returnByValue': True,
                    'timeout': 700,
                },
            )
            if isinstance(response, dict) and response.get('exceptionDetails'):
                raise RuntimeError(str(response.get('exceptionDetails'))[:240])
            result = ((response or {}).get('result') or {}).get('value')
            return result if isinstance(result, dict) else {}
        except Exception as exc:  # noqa: BLE001 - best-effort diagnostic, click can fall back.
            self._trace_workflow_event(
                'click_rect:native_viewport_metrics_failed',
                error=str(exc)[:240],
                human_step='识别浏览器窗口位置',
            )
            return {}

    @staticmethod
    def _window_position_match_score(rect: dict[str, Any], viewport_metrics: dict[str, Any] | None) -> int:
        if not isinstance(rect, dict) or not isinstance(viewport_metrics, dict):
            return 0
        try:
            screen_x = float(viewport_metrics.get('screenX'))
            screen_y = float(viewport_metrics.get('screenY'))
        except (TypeError, ValueError):
            return 0
        try:
            outer_width = float(viewport_metrics.get('outerWidth') or 0)
            outer_height = float(viewport_metrics.get('outerHeight') or 0)
            rect_left = float(rect.get('left') or 0)
            rect_top = float(rect.get('top') or 0)
            rect_width = float(rect.get('width') or 0)
            rect_height = float(rect.get('height') or 0)
        except (TypeError, ValueError):
            return 0
        if outer_width <= 0 or outer_height <= 0 or rect_width <= 0 or rect_height <= 0:
            return 0

        # Chrome reports window position in CSS pixels while Win32 returns desktop pixels.
        # Try both unscaled and window-size-derived scale so secondary monitors and DPI
        # scaling do not make us choose another Chrome window.
        scale_candidates = [1.0]
        scale_x = rect_width / outer_width
        scale_y = rect_height / outer_height
        if 0.5 <= scale_x <= 4.0:
            scale_candidates.append(scale_x)
        if 0.5 <= scale_y <= 4.0:
            scale_candidates.append(scale_y)

        best = 0
        for scale in scale_candidates:
            dx = abs(rect_left - screen_x * scale)
            dy = abs(rect_top - screen_y * scale)
            dw = abs(rect_width - outer_width * scale)
            dh = abs(rect_height - outer_height * scale)
            score = 0
            if dx <= 80:
                score += 40
            elif dx <= 180:
                score += 20
            if dy <= 100:
                score += 40
            elif dy <= 220:
                score += 20
            if dw <= 180:
                score += 20
            if dh <= 180:
                score += 20
            best = max(best, score)
        return best

    def _native_dxm_content_window_info(self, page: Page) -> dict[str, Any] | None:
        if os.name != 'nt' or self._is_headless():
            return None
        page_url = str(getattr(page, 'url', '') or '')
        if 'dianxiaomi.com' not in page_url:
            return None
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            enum_windows_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            enum_child_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

            class Rect(ctypes.Structure):
                _fields_ = [
                    ('left', ctypes.c_long),
                    ('top', ctypes.c_long),
                    ('right', ctypes.c_long),
                    ('bottom', ctypes.c_long),
                ]

            user32.IsWindowVisible.argtypes = [wintypes.HWND]
            user32.IsWindowVisible.restype = wintypes.BOOL
            user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
            user32.GetWindowTextLengthW.restype = ctypes.c_int
            user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
            user32.GetWindowTextW.restype = ctypes.c_int
            user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(Rect)]
            user32.GetWindowRect.restype = wintypes.BOOL
            user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
            user32.GetClassNameW.restype = ctypes.c_int

            def window_text(hwnd: Any) -> str:
                length = user32.GetWindowTextLengthW(hwnd)
                if length <= 0:
                    return ''
                buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buffer, length + 1)
                return buffer.value or ''

            def window_rect(hwnd: Any) -> dict[str, int] | None:
                rect = Rect()
                if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                    return None
                return {
                    'left': int(rect.left),
                    'top': int(rect.top),
                    'right': int(rect.right),
                    'bottom': int(rect.bottom),
                    'width': int(rect.right - rect.left),
                    'height': int(rect.bottom - rect.top),
                }

            windows: list[dict[str, Any]] = []

            def collect_window(hwnd, _lparam):
                if not user32.IsWindowVisible(hwnd):
                    return True
                rect = window_rect(hwnd)
                if not rect or rect['width'] < 500 or rect['height'] < 400:
                    return True
                title = window_text(hwnd)
                class_buffer = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, class_buffer, 256)
                class_name = class_buffer.value or ''
                titled_dxm = '店小秘' in title
                visible_agent_shell = (
                    not title
                    and class_name.startswith('Chrome_WidgetWin_')
                    and 1000 <= int(rect.get('width') or 0) <= 2400
                    and 650 <= int(rect.get('height') or 0) <= 1500
                )
                if not titled_dxm and not visible_agent_shell:
                    return True
                hwnd_int = self._window_handle_to_int(hwnd)
                if hwnd_int:
                    windows.append({'hwnd': hwnd_int, 'title': title, 'class': class_name, 'rect': rect})
                return True

            user32.EnumWindows(enum_windows_proc(collect_window), 0)
            if not windows:
                return None

            def window_score(item: dict[str, Any]) -> tuple[int, int, int, int]:
                title = str(item.get('title') or '')
                rect = item.get('rect') or {}
                return (
                    30 if '编辑' in title else 0,
                    20 if '店小秘' in title else 0,
                    5 if str(item.get('class') or '').startswith('Chrome_WidgetWin_') else 0,
                    int(rect.get('width') or 0) * int(rect.get('height') or 0),
                )

            target = sorted(windows, key=window_score, reverse=True)[0]
            hwnd = wintypes.HWND(int(target['hwnd']))
            child_rects: list[dict[str, Any]] = []

            def collect_child(child_hwnd, _lparam):
                if not user32.IsWindowVisible(child_hwnd):
                    return True
                rect = window_rect(child_hwnd)
                if not rect or rect['width'] < 500 or rect['height'] < 300:
                    return True
                class_buffer = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(child_hwnd, class_buffer, 256)
                class_name = class_buffer.value or ''
                score = int(rect['width']) * int(rect['height'])
                if 'Chrome_RenderWidgetHostHWND' in class_name:
                    score += 10_000_000
                child_hwnd_int = self._window_handle_to_int(child_hwnd)
                if child_hwnd_int:
                    child_rects.append({'hwnd': child_hwnd_int, 'class': class_name, 'rect': rect, 'score': score})
                return True

            user32.EnumChildWindows(hwnd, enum_child_proc(collect_child), 0)
            if not child_rects:
                return None
            content = sorted(child_rects, key=lambda item: int(item.get('score') or 0), reverse=True)[0]
            return {
                'window_hwnd': int(target['hwnd']),
                'window_title': str(target.get('title') or ''),
                'content_hwnd': int(content['hwnd']),
                'content_rect': content['rect'],
                'child_class': str(content.get('class') or ''),
            }
        except Exception as exc:
            self._trace_workflow_event(
                'native_content_window_info_failed',
                error=str(exc)[:240],
                human_step='识别浏览器窗口位置',
            )
            return None

    def _capture_native_dxm_content_snapshot(self, page: Page) -> dict[str, Any] | None:
        if os.name != 'nt' or self._is_headless():
            return None
        self._bring_page_to_front_for_click(page)
        time.sleep(0.12)
        info = self._native_dxm_content_window_info(page)
        if not info:
            return None
        rect = info.get('content_rect') or {}
        try:
            left = int(rect.get('left') or 0)
            top = int(rect.get('top') or 0)
            width = int(rect.get('width') or 0)
            height = int(rect.get('height') or 0)
        except (TypeError, ValueError):
            return None
        if width < 500 or height < 300 or width > 5000 or height > 3000:
            return None
        try:
            capture_hwnd = int(info.get('content_hwnd') or info.get('window_hwnd') or 0)
        except (TypeError, ValueError):
            capture_hwnd = 0
        if not capture_hwnd:
            return None
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            gdi32 = ctypes.windll.gdi32

            class BitmapInfoHeader(ctypes.Structure):
                _fields_ = [
                    ('biSize', wintypes.DWORD),
                    ('biWidth', ctypes.c_long),
                    ('biHeight', ctypes.c_long),
                    ('biPlanes', wintypes.WORD),
                    ('biBitCount', wintypes.WORD),
                    ('biCompression', wintypes.DWORD),
                    ('biSizeImage', wintypes.DWORD),
                    ('biXPelsPerMeter', ctypes.c_long),
                    ('biYPelsPerMeter', ctypes.c_long),
                    ('biClrUsed', wintypes.DWORD),
                    ('biClrImportant', wintypes.DWORD),
                ]

            class BitmapInfo(ctypes.Structure):
                _fields_ = [
                    ('bmiHeader', BitmapInfoHeader),
                    ('bmiColors', wintypes.DWORD * 1),
                ]

            handle_t = ctypes.c_void_p
            user32.GetDC.argtypes = [handle_t]
            user32.GetDC.restype = handle_t
            user32.ReleaseDC.argtypes = [handle_t, handle_t]
            user32.PrintWindow.argtypes = [handle_t, handle_t, wintypes.UINT]
            user32.PrintWindow.restype = wintypes.BOOL
            gdi32.CreateCompatibleDC.argtypes = [handle_t]
            gdi32.CreateCompatibleDC.restype = handle_t
            gdi32.CreateCompatibleBitmap.argtypes = [handle_t, ctypes.c_int, ctypes.c_int]
            gdi32.CreateCompatibleBitmap.restype = handle_t
            gdi32.SelectObject.argtypes = [handle_t, handle_t]
            gdi32.SelectObject.restype = handle_t
            gdi32.BitBlt.argtypes = [handle_t, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, handle_t, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
            gdi32.BitBlt.restype = wintypes.BOOL
            gdi32.GetDIBits.argtypes = [handle_t, handle_t, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
            gdi32.GetDIBits.restype = ctypes.c_int
            gdi32.DeleteObject.argtypes = [handle_t]
            gdi32.DeleteDC.argtypes = [handle_t]

            screen_dc = user32.GetDC(None)
            mem_dc = gdi32.CreateCompatibleDC(screen_dc)
            bitmap = gdi32.CreateCompatibleBitmap(screen_dc, width, height)
            old_object = gdi32.SelectObject(mem_dc, bitmap)
            try:
                srccopy = 0x00CC0020
                print_ok = bool(user32.PrintWindow(handle_t(capture_hwnd), mem_dc, 2))
                if not print_ok and not gdi32.BitBlt(mem_dc, 0, 0, width, height, screen_dc, left, top, srccopy):
                    return None
                bmi = BitmapInfo()
                bmi.bmiHeader.biSize = ctypes.sizeof(BitmapInfoHeader)
                bmi.bmiHeader.biWidth = width
                bmi.bmiHeader.biHeight = -height
                bmi.bmiHeader.biPlanes = 1
                bmi.bmiHeader.biBitCount = 32
                bmi.bmiHeader.biCompression = 0
                buffer = (ctypes.c_ubyte * (width * height * 4))()
                rows = gdi32.GetDIBits(mem_dc, bitmap, 0, height, ctypes.cast(buffer, ctypes.c_void_p), ctypes.byref(bmi), 0)
                if rows <= 0:
                    return None
                snapshot = {
                    'width': width,
                    'height': height,
                    'pixels': bytes(buffer),
                    'format': 'bgra',
                    'content_rect': rect,
                    'window_title': info.get('window_title'),
                    'child_class': info.get('child_class'),
                    'capture_method': 'PrintWindow' if print_ok else 'BitBlt',
                }
                self._trace_workflow_event(
                    'native_content_snapshot_done',
                    width=width,
                    height=height,
                    content_rect=rect,
                    capture_method=snapshot.get('capture_method'),
                    window_title=str(info.get('window_title') or '')[:160],
                    child_class=str(info.get('child_class') or '')[:120],
                    human_step='识别浏览器窗口位置',
                )
                return snapshot
            finally:
                if old_object:
                    gdi32.SelectObject(mem_dc, old_object)
                if bitmap:
                    gdi32.DeleteObject(bitmap)
                if mem_dc:
                    gdi32.DeleteDC(mem_dc)
                if screen_dc:
                    user32.ReleaseDC(None, screen_dc)
        except Exception as exc:
            self._trace_workflow_event(
                'native_content_snapshot_failed',
                error=str(exc)[:240],
                content_rect=rect,
                human_step='识别浏览器窗口位置',
            )
            return None

    def _force_foreground_dxm_window(self) -> bool:
        if os.name != 'nt':
            return False
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            candidates: list[dict[str, Any]] = []

            class Rect(ctypes.Structure):
                _fields_ = [
                    ('left', ctypes.c_long),
                    ('top', ctypes.c_long),
                    ('right', ctypes.c_long),
                    ('bottom', ctypes.c_long),
                ]

            user32.IsWindowVisible.argtypes = [wintypes.HWND]
            user32.IsWindowVisible.restype = wintypes.BOOL
            user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
            user32.GetWindowTextLengthW.restype = ctypes.c_int
            user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
            user32.GetWindowTextW.restype = ctypes.c_int
            user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(Rect)]
            user32.GetWindowRect.restype = wintypes.BOOL
            user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
            user32.GetClassNameW.restype = ctypes.c_int
            viewport_metrics = {}
            page = getattr(self, '_page', None)
            if page is not None:
                viewport_metrics = self._browser_viewport_metrics_for_native_click(page)

            def collect(hwnd, _lparam):
                length = user32.GetWindowTextLengthW(hwnd)
                title = ''
                if length > 0:
                    buffer = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buffer, length + 1)
                    title = buffer.value or ''
                class_buffer = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, class_buffer, 256)
                class_name = class_buffer.value or ''
                rect = Rect()
                if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                    return True
                width = int(rect.right - rect.left)
                height = int(rect.bottom - rect.top)
                visible = bool(user32.IsWindowVisible(hwnd))
                titled_dxm = '店小秘' in title and ('Chrome' in title or 'Edge' in title or '店小秘--' in title)
                agent_chrome_shell = (
                    not title
                    and class_name.startswith('Chrome_WidgetWin_')
                    and 1000 <= width <= 2200
                    and 650 <= height <= 1400
                )
                if titled_dxm or agent_chrome_shell:
                    hwnd_int = self._window_handle_to_int(hwnd)
                    if not hwnd_int:
                        return True
                    candidates.append({
                        'hwnd': hwnd_int,
                        'title': title,
                        'class': class_name,
                        'visible': visible,
                        'width': width,
                        'height': height,
                        'rect': {'left': int(rect.left), 'top': int(rect.top), 'width': width, 'height': height},
                    })
                return True

            user32.EnumWindows(enum_proc(collect), 0)
            if not candidates:
                self._trace_workflow_event('click_rect:native_front_skipped', reason='dxm_window_not_found', human_step='切换到店小秘窗口')
                return False

            def score(item: dict[str, Any]) -> tuple[int, int, int, int, int]:
                title = str(item.get('title') or '')
                return (
                    self._window_position_match_score(item.get('rect') or {}, viewport_metrics),
                    20 if '店小秘--数据采集' in title else 0,
                    10 if '店小秘' in title else 0,
                    5 if item.get('visible') else 0,
                    int(item.get('width') or 0) * int(item.get('height') or 0),
                )

            candidate = sorted(candidates, key=score, reverse=True)[0]
            hwnd = self._window_handle_to_int(candidate.get('hwnd'))
            if not hwnd:
                self._trace_workflow_event('click_rect:native_front_skipped', reason='dxm_window_handle_missing', human_step='切换到店小秘窗口')
                return False
            title = str(candidate.get('title') or candidate.get('class') or '')
            hwnd_value = wintypes.HWND(hwnd)
            hwnd_topmost = wintypes.HWND(-1)
            hwnd_notopmost = wintypes.HWND(-2)
            try:
                user32.SwitchToThisWindow.argtypes = [wintypes.HWND, wintypes.BOOL]
                user32.SwitchToThisWindow.restype = None
            except Exception:
                pass
            user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
            user32.GetWindowThreadProcessId.restype = wintypes.DWORD
            user32.IsWindowVisible.argtypes = [wintypes.HWND]
            user32.IsWindowVisible.restype = wintypes.BOOL
            user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
            user32.GetWindowTextLengthW.restype = ctypes.c_int
            user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
            user32.GetWindowTextW.restype = ctypes.c_int
            user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(Rect)]
            user32.GetWindowRect.restype = wintypes.BOOL
            user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
            user32.ShowWindow.restype = wintypes.BOOL
            user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
            user32.SetWindowPos.restype = wintypes.BOOL
            user32.SetForegroundWindow.argtypes = [wintypes.HWND]
            user32.SetForegroundWindow.restype = wintypes.BOOL
            user32.BringWindowToTop.argtypes = [wintypes.HWND]
            user32.BringWindowToTop.restype = wintypes.BOOL
            user32.SetActiveWindow.argtypes = [wintypes.HWND]
            user32.SetActiveWindow.restype = wintypes.HWND
            user32.SetFocus.argtypes = [wintypes.HWND]
            user32.SetFocus.restype = wintypes.HWND
            user32.GetForegroundWindow.argtypes = []
            user32.GetForegroundWindow.restype = wintypes.HWND
            kernel32.GetCurrentThreadId.argtypes = []
            kernel32.GetCurrentThreadId.restype = wintypes.DWORD
            sw_restore = 9
            swp_nomove = 0x0002
            swp_nosize = 0x0001
            swp_showwindow = 0x0040
            flags = swp_nomove | swp_nosize | swp_showwindow
            rect = Rect()
            user32.GetWindowRect(hwnd_value, ctypes.byref(rect))
            width = int(rect.right - rect.left)
            height = int(rect.bottom - rect.top)
            offscreen_or_minimized = rect.left < -1000 or rect.top < -1000 or width < 400 or height < 300
            current_thread = kernel32.GetCurrentThreadId()
            foreground_before = user32.GetForegroundWindow()
            foreground_before_int = self._window_handle_to_int(foreground_before)
            foreground_thread = user32.GetWindowThreadProcessId(wintypes.HWND(foreground_before_int), None) if foreground_before_int else 0
            target_thread = user32.GetWindowThreadProcessId(hwnd_value, None)
            attached_foreground = bool(foreground_thread and user32.AttachThreadInput(current_thread, foreground_thread, True))
            attached_target = bool(target_thread and user32.AttachThreadInput(current_thread, target_thread, True))
            try:
                user32.ShowWindow(hwnd_value, sw_restore)
                if offscreen_or_minimized:
                    user32.SetWindowPos(hwnd_value, hwnd_topmost, 80, 80, 1600, 950, swp_showwindow)
                else:
                    user32.SetWindowPos(hwnd_value, hwnd_topmost, 0, 0, 0, 0, flags)
                time.sleep(0.05)
                try:
                    user32.SwitchToThisWindow(hwnd_value, True)
                except Exception:
                    pass
                user32.BringWindowToTop(hwnd_value)
                user32.SetForegroundWindow(hwnd_value)
                user32.SetActiveWindow(hwnd_value)
                user32.SetFocus(hwnd_value)
                time.sleep(0.05)
                user32.SetWindowPos(hwnd_value, hwnd_notopmost, 0, 0, 0, 0, flags)
            finally:
                if attached_target:
                    user32.AttachThreadInput(current_thread, target_thread, False)
                if attached_foreground:
                    user32.AttachThreadInput(current_thread, foreground_thread, False)
            foreground = self._window_handle_to_int(user32.GetForegroundWindow())
            ok = foreground == hwnd
            self._trace_workflow_event(
                'click_rect:native_front_done',
                ok=ok,
                title=title[:160],
                foreground=foreground,
                foreground_before=foreground_before_int,
                hwnd=hwnd,
                offscreen_or_minimized=bool(offscreen_or_minimized),
                window_rect={'left': int(rect.left), 'top': int(rect.top), 'width': width, 'height': height},
                viewport=viewport_metrics,
                attached_foreground=attached_foreground,
                attached_target=attached_target,
                human_step='切换到店小秘窗口',
            )
            return ok
        except Exception as exc:
            self._trace_workflow_event('click_rect:native_front_failed', error=str(exc)[:240], human_step='切换到店小秘窗口')
            return False

    def _click_point_with_native_window(
        self,
        page: Page,
        x: float,
        y: float,
        *,
        use_viewport_metrics: bool = True,
        viewport_metrics_override: dict[str, Any] | None = None,
    ) -> bool:
        if os.name != 'nt' or self._is_headless():
            return False
        page_url = str(getattr(page, 'url', '') or '')
        if 'dianxiaomi.com' not in page_url:
            return False
        try:
            foreground_ready = self._force_foreground_dxm_window()
            if not foreground_ready:
                self._trace_workflow_event(
                    'click_rect:native_click_foreground_unconfirmed',
                    human_step='切换到店小秘窗口',
                )
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            enum_windows_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            enum_child_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

            class Rect(ctypes.Structure):
                _fields_ = [
                    ('left', ctypes.c_long),
                    ('top', ctypes.c_long),
                    ('right', ctypes.c_long),
                    ('bottom', ctypes.c_long),
                ]

            user32.IsWindowVisible.argtypes = [wintypes.HWND]
            user32.IsWindowVisible.restype = wintypes.BOOL
            user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
            user32.GetWindowTextLengthW.restype = ctypes.c_int
            user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
            user32.GetWindowTextW.restype = ctypes.c_int
            user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(Rect)]
            user32.GetWindowRect.restype = wintypes.BOOL
            user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
            user32.GetClassNameW.restype = ctypes.c_int
            user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
            user32.SetCursorPos.restype = wintypes.BOOL
            user32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.c_ulong)]
            user32.mouse_event.restype = None
            if viewport_metrics_override is not None:
                viewport_metrics = viewport_metrics_override
                self._trace_workflow_event(
                    'click_rect:native_viewport_metrics_override',
                    viewport=viewport_metrics,
                    human_step='识别浏览器窗口位置',
                )
            elif use_viewport_metrics:
                viewport_metrics = self._browser_viewport_metrics_for_native_click(page)
            else:
                viewport_metrics = {}
                self._trace_workflow_event(
                    'click_rect:native_viewport_metrics_skipped',
                    reason='win32_only_click_path',
                    human_step='识别浏览器窗口位置',
                )

            windows: list[dict[str, Any]] = []

            def window_text(hwnd: Any) -> str:
                length = user32.GetWindowTextLengthW(hwnd)
                if length <= 0:
                    return ''
                buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buffer, length + 1)
                return buffer.value or ''

            def window_rect(hwnd: Any) -> dict[str, int] | None:
                rect = Rect()
                if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                    return None
                return {
                    'left': int(rect.left),
                    'top': int(rect.top),
                    'right': int(rect.right),
                    'bottom': int(rect.bottom),
                    'width': int(rect.right - rect.left),
                    'height': int(rect.bottom - rect.top),
                }

            def collect_window(hwnd, _lparam):
                if not user32.IsWindowVisible(hwnd):
                    return True
                title = window_text(hwnd)
                rect = window_rect(hwnd)
                if not rect or rect['width'] < 500 or rect['height'] < 400:
                    return True
                class_buffer = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, class_buffer, 256)
                class_name = class_buffer.value or ''
                titled_dxm = '店小秘' in title
                visible_agent_shell = (
                    not title
                    and class_name.startswith('Chrome_WidgetWin_')
                    and 1000 <= int(rect.get('width') or 0) <= 2200
                    and 650 <= int(rect.get('height') or 0) <= 1400
                )
                if not titled_dxm and not visible_agent_shell:
                    return True
                hwnd_int = self._window_handle_to_int(hwnd)
                if hwnd_int:
                    windows.append({'hwnd': hwnd_int, 'title': title, 'class': class_name, 'rect': rect})
                return True

            user32.EnumWindows(enum_windows_proc(collect_window), 0)
            if not windows:
                self._trace_workflow_event('click_rect:native_click_skipped', reason='dxm_window_not_found', human_step='点击页面按钮')
                return False

            def window_score(item: dict[str, Any]) -> tuple[int, int, int, int, int]:
                title = str(item.get('title') or '')
                rect = item.get('rect') or {}
                return (
                    self._window_position_match_score(rect, viewport_metrics),
                    20 if '数据采集' in title else 0,
                    10 if '店小秘' in title else 0,
                    5 if str(item.get('class') or '').startswith('Chrome_WidgetWin_') else 0,
                    int(rect.get('width') or 0) * int(rect.get('height') or 0),
                )

            target = sorted(windows, key=window_score, reverse=True)[0]
            hwnd = wintypes.HWND(int(target['hwnd']))
            child_rects: list[dict[str, Any]] = []

            def collect_child(child_hwnd, _lparam):
                if not user32.IsWindowVisible(child_hwnd):
                    return True
                rect = window_rect(child_hwnd)
                if not rect or rect['width'] < 500 or rect['height'] < 300:
                    return True
                class_buffer = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(child_hwnd, class_buffer, 256)
                class_name = class_buffer.value or ''
                score = int(rect['width']) * int(rect['height'])
                if 'Chrome_RenderWidgetHostHWND' in class_name:
                    score += 10_000_000
                child_hwnd_int = self._window_handle_to_int(child_hwnd)
                if child_hwnd_int:
                    child_rects.append({'hwnd': child_hwnd_int, 'class': class_name, 'rect': rect, 'score': score})
                return True

            user32.EnumChildWindows(hwnd, enum_child_proc(collect_child), 0)
            if not child_rects:
                self._trace_workflow_event(
                    'click_rect:native_click_skipped',
                    reason='render_widget_not_found',
                    title=str(target.get('title') or '')[:160],
                    human_step='点击页面按钮',
                )
                return False
            content = sorted(child_rects, key=lambda item: int(item.get('score') or 0), reverse=True)[0]
            content_rect = content['rect']
            viewport_width = float(viewport_metrics.get('innerWidth') or viewport_metrics.get('visualViewportWidth') or content_rect['width'])
            viewport_height = float(viewport_metrics.get('innerHeight') or viewport_metrics.get('visualViewportHeight') or content_rect['height'])
            if x < 0 or y < 0 or x > viewport_width or y > viewport_height:
                self._trace_workflow_event(
                    'click_rect:native_click_skipped',
                    reason='point_outside_content_rect',
                    point={'x': x, 'y': y},
                    content_rect=content_rect,
                    viewport=viewport_metrics,
                    human_step='点击页面按钮',
                )
                return False
            point = self._native_click_screen_point(content_rect, x, y, viewport_metrics)
            screen_x = int(point['screen']['x'])
            screen_y = int(point['screen']['y'])
            self._trace_workflow_event(
                'click_rect:native_click_start',
                screen={'x': screen_x, 'y': screen_y},
                content_rect=content_rect,
                viewport=viewport_metrics,
                scale=point.get('scale'),
                window_title=str(target.get('title') or '')[:160],
                child_class=str(content.get('class') or '')[:120],
                human_step='点击页面按钮',
            )
            user32.SetCursorPos(screen_x, screen_y)
            time.sleep(0.03)
            mouseeventf_leftdown = 0x0002
            mouseeventf_leftup = 0x0004
            user32.mouse_event(mouseeventf_leftdown, 0, 0, 0, None)
            time.sleep(0.04)
            user32.mouse_event(mouseeventf_leftup, 0, 0, 0, None)
            self._trace_workflow_event('click_rect:native_click_done', human_step='点击页面按钮')
            return True
        except Exception as exc:
            self._trace_workflow_event('click_rect:native_click_failed', error=str(exc)[:240], human_step='点击页面按钮')
            return False

    def _dismiss_data_acquisition_notice_with_native_click(self, page: Page) -> bool:
        if os.name != 'nt' or self._is_headless() or not self._is_data_acquisition_page_url(page):
            return False
        self._trace_workflow_event(
            'dismiss_data_acquisition_notice:native_start',
            human_step='关闭店小秘通知弹窗',
        )
        # DXM's offline notice uses a full-screen modal. A normal Escape does not close it.
        # The modal is responsive, so try the known close controls for both 1440px and maximized windows.
        self._bring_page_to_front_for_click(page)
        clicked_points: list[dict[str, float]] = []
        for x, y in (
            (1170.0, 91.0),
            (1650.0, 128.0),
            (1147.0, 675.0),
            (1618.0, 950.0),
        ):
            if self._click_point_with_native_window(page, x, y):
                clicked_points.append({'x': x, 'y': y})
                time.sleep(0.15)
        if clicked_points:
            time.sleep(0.35)
            self._trace_workflow_event(
                'dismiss_data_acquisition_notice:native_done',
                points=clicked_points,
                human_step='关闭店小秘通知弹窗',
            )
            return True
        self._trace_workflow_event(
            'dismiss_data_acquisition_notice:native_skipped',
            reason='native_click_unavailable',
            human_step='关闭店小秘通知弹窗',
        )
        return False

    def _replace_active_field_with_native_clipboard_text(self, text: str) -> bool:
        if os.name != 'nt' or self._is_headless():
            return False
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            previous = self._read_windows_clipboard_text()
            if not self._write_windows_clipboard_text(str(text or '')):
                return False
            user32.keybd_event.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, wintypes.DWORD, ctypes.c_ulonglong]
            user32.keybd_event.restype = None
            keyeventf_keyup = 0x0002
            vk_control = 0x11
            vk_a = 0x41
            vk_v = 0x56

            def ctrl_key(vk: int) -> None:
                user32.keybd_event(vk_control, 0, 0, 0)
                time.sleep(0.02)
                user32.keybd_event(vk, 0, 0, 0)
                time.sleep(0.02)
                user32.keybd_event(vk, 0, keyeventf_keyup, 0)
                time.sleep(0.02)
                user32.keybd_event(vk_control, 0, keyeventf_keyup, 0)

            ctrl_key(vk_a)
            time.sleep(0.04)
            ctrl_key(vk_v)
            time.sleep(0.18)
            if previous is not None:
                self._write_windows_clipboard_text(previous)
            return True
        except Exception as exc:
            self._trace_workflow_event('native_keyboard:paste_failed', error=str(exc)[:240])
            return False

    def _navigate_visible_dxm_with_native_address_bar(self, page: Page, url: str) -> bool:
        if os.name != 'nt' or self._is_headless():
            return False
        page_url = str(getattr(page, 'url', '') or '')
        if 'dianxiaomi.com' not in page_url:
            return False
        self._trace_workflow_event(
            'native_address_navigation:start',
            url=url,
            current_url=page_url,
            human_step='切换商品箱页面',
        )
        try:
            import ctypes
            from ctypes import wintypes

            if not self._bring_page_to_front_for_click(page):
                self._trace_workflow_event(
                    'native_address_navigation:skipped',
                    reason='window_not_foreground',
                    human_step='切换商品箱页面',
                )
                return False
            user32 = ctypes.windll.user32
            previous = self._read_windows_clipboard_text()
            if not self._write_windows_clipboard_text(str(url or '')):
                self._trace_workflow_event(
                    'native_address_navigation:skipped',
                    reason='clipboard_write_failed',
                    human_step='切换商品箱页面',
                )
                return False

            user32.keybd_event.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, wintypes.DWORD, ctypes.c_ulonglong]
            user32.keybd_event.restype = None
            keyeventf_keyup = 0x0002
            vk_control = 0x11
            vk_l = 0x4C
            vk_v = 0x56
            vk_enter = 0x0D

            def press(vk: int) -> None:
                user32.keybd_event(vk, 0, 0, 0)
                time.sleep(0.02)
                user32.keybd_event(vk, 0, keyeventf_keyup, 0)

            def ctrl_key(vk: int) -> None:
                user32.keybd_event(vk_control, 0, 0, 0)
                time.sleep(0.02)
                press(vk)
                time.sleep(0.02)
                user32.keybd_event(vk_control, 0, keyeventf_keyup, 0)

            ctrl_key(vk_l)
            time.sleep(0.08)
            ctrl_key(vk_v)
            time.sleep(0.08)
            press(vk_enter)
            navigated = False
            current_after = str(getattr(page, 'url', '') or '')
            for _ in range(12):
                time.sleep(0.25)
                current_after = str(getattr(page, 'url', '') or '')
                if self._is_current_page_url(page, url):
                    navigated = True
                    break
            if previous is not None:
                self._write_windows_clipboard_text(previous)
            if not navigated:
                self._trace_workflow_event(
                    'native_address_navigation:unchanged',
                    url=url,
                    current_url=current_after,
                    human_step='切换商品箱页面',
                )
                return False
            self._trace_workflow_event(
                'native_address_navigation:done',
                url=url,
                current_url=current_after,
                human_step='切换商品箱页面',
            )
            return True
        except Exception as exc:
            self._trace_workflow_event(
                'native_address_navigation:failed',
                error=str(exc)[:240],
                human_step='切换商品箱页面',
            )
            return False

    def _read_windows_clipboard_text(self) -> str | None:
        if os.name != 'nt':
            return None
        try:
            import ctypes

            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            cf_unicode_text = 13
            user32.IsClipboardFormatAvailable.argtypes = [ctypes.c_uint]
            user32.IsClipboardFormatAvailable.restype = ctypes.c_int
            user32.OpenClipboard.argtypes = [ctypes.c_void_p]
            user32.OpenClipboard.restype = ctypes.c_int
            user32.GetClipboardData.argtypes = [ctypes.c_uint]
            user32.GetClipboardData.restype = ctypes.c_void_p
            user32.CloseClipboard.argtypes = []
            user32.CloseClipboard.restype = ctypes.c_int
            kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
            kernel32.GlobalLock.restype = ctypes.c_void_p
            kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
            kernel32.GlobalUnlock.restype = ctypes.c_int
            if not user32.IsClipboardFormatAvailable(cf_unicode_text):
                return None
            if not user32.OpenClipboard(None):
                return None
            try:
                handle = user32.GetClipboardData(cf_unicode_text)
                if not handle:
                    return None
                kernel32.GlobalLock.restype = ctypes.c_void_p
                ptr = kernel32.GlobalLock(handle)
                if not ptr:
                    return None
                try:
                    return ctypes.wstring_at(ptr)
                finally:
                    kernel32.GlobalUnlock(handle)
            finally:
                user32.CloseClipboard()
        except Exception:
            return None

    def _write_windows_clipboard_text(self, text: str) -> bool:
        if os.name != 'nt':
            return False
        try:
            import ctypes

            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            cf_unicode_text = 13
            gmem_moveable = 0x0002
            user32.OpenClipboard.argtypes = [ctypes.c_void_p]
            user32.OpenClipboard.restype = ctypes.c_int
            user32.EmptyClipboard.argtypes = []
            user32.EmptyClipboard.restype = ctypes.c_int
            user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
            user32.SetClipboardData.restype = ctypes.c_void_p
            user32.CloseClipboard.argtypes = []
            user32.CloseClipboard.restype = ctypes.c_int
            kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
            kernel32.GlobalAlloc.restype = ctypes.c_void_p
            kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
            kernel32.GlobalLock.restype = ctypes.c_void_p
            kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
            kernel32.GlobalUnlock.restype = ctypes.c_int
            data = (str(text or '') + '\0').encode('utf-16le')
            for _attempt in range(6):
                if user32.OpenClipboard(None):
                    break
                time.sleep(0.03)
            else:
                return False
            try:
                user32.EmptyClipboard()
                handle = kernel32.GlobalAlloc(gmem_moveable, len(data))
                if not handle:
                    return False
                kernel32.GlobalLock.restype = ctypes.c_void_p
                ptr = kernel32.GlobalLock(handle)
                if not ptr:
                    return False
                try:
                    ctypes.memmove(ptr, data, len(data))
                finally:
                    kernel32.GlobalUnlock(handle)
                if not user32.SetClipboardData(cf_unicode_text, handle):
                    return False
                return True
            finally:
                user32.CloseClipboard()
        except Exception:
            return False

    def _click_point_with_dom(self, page: Page, x: float, y: float) -> bool:
        script_body = r'''
              const visible = (el) => {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
              };
              const norm = (s) => String(s || '').replace(/\s+/g, '').trim();
              const forbidden = ['发布','立即发布','继续发布','保存并发布','保存并移入待发布','移入待发布','批量发布'];
              const raw = document.elementFromPoint(x, y);
              if (!raw || !visible(raw)) return {ok:false, reason:'no_element_at_point'};
              const target = raw.closest('button,a,[role="button"],input,textarea,[onclick],span,div') || raw;
              if (!visible(target)) return {ok:false, reason:'target_not_visible'};
              const text = String(target.innerText || target.textContent || target.getAttribute('aria-label') || target.getAttribute('title') || '').trim();
              const hay = norm(text);
              if (forbidden.some(term => hay.includes(norm(term)))) {
                return {ok:false, reason:'forbidden_target', text:text.slice(0,120)};
              }
              target.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, cancelable:true, clientX:x, clientY:y, button:0}));
              target.dispatchEvent(new MouseEvent('mouseup', {bubbles:true, cancelable:true, clientX:x, clientY:y, button:0}));
              if (typeof target.click === 'function') {
                target.click();
              } else {
                target.dispatchEvent(new MouseEvent('click', {bubbles:true, cancelable:true, clientX:x, clientY:y, button:0}));
              }
              return {ok:true, tag:target.tagName, text:text.slice(0,120)};
        '''
        payload = {'x': x, 'y': y}
        try:
            self._trace_workflow_event('click_rect:dom_start', human_step='点击页面按钮')
            try:
                cdp = page.context.new_cdp_session(page)
            except Exception as exc:  # noqa: BLE001 - fake pages and non-CDP browsers fall back below.
                self._trace_workflow_event(
                    'click_rect:dom_runtime_unavailable',
                    error=str(exc)[:240],
                    human_step='点击页面按钮',
                )
            else:
                expression = (
                    '(() => {\n'
                    f'  const __dxmClick = {json.dumps(payload, ensure_ascii=False)};\n'
                    '  const x = Number(__dxmClick.x);\n'
                    '  const y = Number(__dxmClick.y);\n'
                    f'{script_body}\n'
                    '})()'
                )
                response = cdp.send(
                    'Runtime.evaluate',
                    {
                        'expression': expression,
                        'returnByValue': True,
                        'timeout': 2000,
                    },
                )
                if isinstance(response, dict) and response.get('exceptionDetails'):
                    self._trace_workflow_event(
                        'click_rect:dom_failed',
                        error=str(response.get('exceptionDetails'))[:240],
                        via='runtime',
                        human_step='点击页面按钮',
                    )
                    return False
                result = ((response or {}).get('result') or {}).get('value')
                self._trace_workflow_event(
                    'click_rect:dom_done',
                    result=result,
                    via='runtime',
                    human_step='点击页面按钮',
                )
                return isinstance(result, dict) and bool(result.get('ok'))
            result = page.evaluate(f'''({{x, y}}) => {{{script_body}}}''', payload)
            self._trace_workflow_event('click_rect:dom_done', result=result, human_step='点击页面按钮')
            return isinstance(result, dict) and bool(result.get('ok'))
        except Exception as exc:
            self._trace_workflow_event('click_rect:dom_failed', error=str(exc)[:240], human_step='点击页面按钮')
            return False

    def _click_point_with_cdp(self, page: Page, x: float, y: float) -> bool:
        try:
            self._trace_workflow_event('click_rect:cdp_session_start', human_step='点击页面按钮')
            cdp = page.context.new_cdp_session(page)
            self._trace_workflow_event('click_rect:cdp_session_done', human_step='点击页面按钮')
            for event in (
                {'type': 'mouseMoved', 'x': x, 'y': y, 'button': 'none'},
                {'type': 'mousePressed', 'x': x, 'y': y, 'button': 'left', 'clickCount': 1},
                {'type': 'mouseReleased', 'x': x, 'y': y, 'button': 'left', 'clickCount': 1},
            ):
                self._trace_workflow_event(
                    'click_rect:cdp_send_start',
                    mouse_event=event.get('type'),
                    human_step='点击页面按钮',
                )
                cdp.send('Input.dispatchMouseEvent', event)
                self._trace_workflow_event(
                    'click_rect:cdp_send_done',
                    mouse_event=event.get('type'),
                    human_step='点击页面按钮',
                )
            return True
        except Exception as exc:
            self._trace_workflow_event('click_rect:cdp_failed', error=str(exc)[:240], human_step='点击页面按钮')
            return False

    def _context_pages(self) -> list[Page]:
        if self._context is None or not hasattr(self._context, 'pages'):
            return []
        try:
            return list(self._context.pages)
        except Exception:
            return []

    def _new_context_pages(self, pages_before: list[Page]) -> list[Page]:
        before_ids = {id(page) for page in pages_before}
        return [page for page in self._context_pages() if id(page) not in before_ids]

    def _find_editor_page(self, pages: list[Page], wait_ms: int = 0) -> Page | None:
        seen: list[Page] = []
        deadline = time.monotonic() + max(wait_ms, 0) / 1000
        while True:
            for page in pages:
                if page is None or any(id(page) == id(item) for item in seen):
                    continue
                seen.append(page)
            for page in seen:
                if self._is_playwright_object_closed(page):
                    continue
                try:
                    if '/web/smt/edit' in str(page.url or ''):
                        return page
                except Exception:
                    continue
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.25)
            pages = [*pages, *self._context_pages()]

    def _open_editor_from_draft_box(self, page: Page, row_info: dict[str, Any] | None = None) -> Page:
        if self._context is None:
            raise RuntimeError('浏览器上下文不存在，无法从商品箱进入编辑页')

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
            edit_href = str(edit_action.get('href') or '').strip()
            if edit_href and not edit_href.lower().startswith('javascript') and edit_href != '#':
                edit_url = urljoin(str(page.url or ''), edit_href)
                if '/web/smt/edit' in edit_url:
                    self._goto_with_live_hud(page, edit_url, wait_until='domcontentloaded', timeout=45000)
                    page.wait_for_url('**/web/smt/edit**', timeout=15000)
                    page.wait_for_timeout(1500)
                    self._reapply_live_hud_if_available(page)
                    return page
            pages_before_dom = self._context_pages()
            dom_click = self._dispatch_draft_row_edit_event(page, row_info or {}) or {}
            if dom_click.get('ok'):
                page.wait_for_timeout(1500)
                editor_page = self._find_editor_page(
                    [page, *self._new_context_pages(pages_before_dom)],
                    wait_ms=8000,
                )
                if editor_page is not None:
                    self._reapply_live_hud_if_available(editor_page)
                    return editor_page
            if hasattr(self._context, 'expect_page'):
                pages_before = self._context_pages()
                try:
                    with self._context.expect_page(timeout=8000) as new_page_info:
                        self._click_rect_center(page, edit_action['rect'])
                    new_page = new_page_info.value
                    new_page.wait_for_load_state('domcontentloaded', timeout=10000)
                    editor_page = self._find_editor_page(
                        [new_page, page, *self._new_context_pages(pages_before)],
                        wait_ms=12000,
                    )
                    if editor_page is not None:
                        self._reapply_live_hud_if_available(editor_page)
                        return editor_page
                    page = new_page
                except TimeoutError:
                    page.wait_for_timeout(1500)
                    editor_page = self._find_editor_page(
                        [page, *self._new_context_pages(pages_before)],
                        wait_ms=1500,
                    )
                    if editor_page is not None:
                        self._reapply_live_hud_if_available(editor_page)
                        return editor_page
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
                raise RuntimeError('未找到商品箱编辑入口')

        if '/web/smt/edit' in page.url:
            return page

        for selector in skip_selectors:
            locator = page.locator(selector).first
            try:
                if locator.count() == 0:
                    continue
                pages_before = self._context_pages()
                with self._context.expect_page(timeout=5000) as new_page_info:
                    locator.click(timeout=3000)
                new_page = new_page_info.value
                new_page.wait_for_load_state('domcontentloaded', timeout=10000)
                editor_page = self._find_editor_page(
                    [new_page, page, *self._new_context_pages(pages_before)],
                    wait_ms=5000,
                )
                final_page = editor_page or new_page
                self._reapply_live_hud_if_available(final_page)
                return final_page
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

    def _dispatch_draft_row_edit_event(self, page: Page, row_info: dict[str, Any]) -> dict[str, Any]:
        return page.evaluate(r'''(rowInfo) => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
          const rows = Array.from(document.querySelectorAll('tr,.ant-table-row,.vxe-body--row,li,div')).filter(visible);
          const rowTextFull = String(rowInfo?.rowText || '').replace(/\s+/g, ' ').trim();
          const rowText = rowTextFull.slice(0, 260);
          const compactRowText = rowTextFull.replace(/\s+/g, '');
          const claimMark = rowTextFull.match(/AI认领-\d+-\d+/)?.[0] || '';
          const sourceTitle = rowTextFull.split(/备注[:：]/)[0].trim();
          const meaningfulPrefix = sourceTitle.length >= 24 ? sourceTitle.slice(0, 48) : rowTextFull.slice(0, 48);
          const rowMatches = (text) => {
            const normalized = String(text || '').replace(/\s+/g, ' ').trim();
            if (!normalized || normalized.length < 20) return false;
            if (!normalized.includes('编辑')) return false;
            if (!rowTextFull) return true;
            const compact = normalized.replace(/\s+/g, '');
            if (claimMark && normalized.includes(claimMark)) return true;
            if (meaningfulPrefix.length >= 20 && normalized.includes(meaningfulPrefix)) return true;
            if (normalized.includes(rowText) || rowText.includes(normalized)) return true;
            if (compactRowText.length >= 40 && compact.includes(compactRowText.slice(0, 80))) return true;
            return false;
          };
          const rowIndex = Number(rowInfo?.rowIndex);
          let row = Number.isInteger(rowIndex) && rowIndex >= 0 && rowIndex < rows.length ? rows[rowIndex] : null;
          if (row && !rowMatches(textOf(row))) row = null;
          if (!row && rowText) {
            row = rows
              .map(el => ({el, text:textOf(el)}))
              .filter(item => rowMatches(item.text))
              .sort((a, b) => a.text.length - b.text.length)[0]?.el || null;
          }
          if (!row) return {ok:false, reason:'未找到目标草稿行'};
          const edit = Array.from(row.querySelectorAll('a,button,span,[role="button"]'))
            .filter(visible)
            .find(el => textOf(el) === '编辑');
          if (!edit) return {ok:false, reason:'未找到目标行编辑入口', row_text:textOf(row).slice(0, 260)};
          edit.scrollIntoView({block:'center', inline:'nearest'});
          for (const type of ['mouseover', 'mousemove', 'mousedown', 'mouseup', 'click']) {
            edit.dispatchEvent(new MouseEvent(type, {bubbles:true, cancelable:true, view:window}));
          }
          return {
            ok:true,
            strategy:'dom_mouse_event',
            target_text:textOf(edit),
            row_text:textOf(row).slice(0, 260),
          };
        }''', row_info)

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

    def _capture_optional_workflow_screenshot(
        self,
        page: Page,
        path: Path,
        *,
        trace_prefix: str,
    ) -> dict[str, Any]:
        if os.name == 'nt' and not self._is_headless() and self._is_dxm_editor_url(getattr(page, 'url', None)):
            self._trace_workflow_event(
                f'{trace_prefix}:screenshot_skipped',
                path=str(path),
                reason='visible_editor_screenshot_skipped',
                human_step='可见编辑页跳过整页截图',
            )
            return {'ok': False, 'screenshot_url': None, 'error': 'visible_editor_screenshot_skipped'}
        full_page = not (os.name == 'nt' and not self._is_headless() and self._is_data_acquisition_page_url(page))
        timeout = 5000 if not full_page else 15000
        try:
            page.screenshot(path=str(path), full_page=full_page, timeout=timeout)
        except TypeError:
            try:
                page.screenshot(path=str(path), full_page=full_page)
            except Exception as exc:
                self._trace_workflow_event(
                    f'{trace_prefix}:screenshot_failed',
                    path=str(path),
                    full_page=full_page,
                    error=str(exc),
                )
                return {'ok': False, 'screenshot_url': None, 'error': str(exc)}
        except Exception as exc:
            self._trace_workflow_event(
                f'{trace_prefix}:screenshot_failed',
                path=str(path),
                full_page=full_page,
                error=str(exc),
            )
            return {'ok': False, 'screenshot_url': None, 'error': str(exc)}

        self._trace_workflow_event(
            f'{trace_prefix}:screenshot_done',
            path=str(path),
            full_page=full_page,
        )
        return {'ok': True, 'screenshot_url': self._artifact_url(path), 'error': None}

    def _draft_box_action_message(self, action: str, note_text: str | None = None) -> str:
        if action == 'remark':
            return f'已进入商品箱备注动作，目标备注：{note_text or "AI认领"}。'
        if action == 'edit':
            return '已进入商品箱编辑动作，下一步应处理分类引导并打开真实编辑页。'
        return f'已触发商品箱动作：{action}'

    def _is_headless(self) -> bool:
        if os.getenv('DXM_LOGIN_HEADLESS') == '1':
            return True
        if os.getenv('DXM_LOGIN_HEADED') == '1':
            return False
        if os.name == 'nt':
            return False
        return not bool(os.getenv('DISPLAY'))

    def _mask_secret(self, raw: str) -> str:
        if len(raw) <= 2:
            return '*' * len(raw)
        return raw[0] + '*' * (len(raw) - 2) + raw[-1]
