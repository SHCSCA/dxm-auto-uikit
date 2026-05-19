import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path('/root/.Hermes/workspace/dxm-auto-uikit')
COOKIE_FILE = ROOT / 'data' / 'sessions' / 'dianxiaomi_cookies.json'
OUT_DIR = ROOT / 'data' / 'screenshots'
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_JSON = ROOT / 'data' / 'sessions' / 'dianxiaomi_claim_action_v2.json'


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


def visible_dialogs(page):
    return page.evaluate(r'''() => {
      const out = [];
      for (const el of document.querySelectorAll('[role="dialog"], .ant-modal-wrap, .ant-modal, .ant-drawer, .ant-popover, .ant-select-dropdown, .ant-dropdown')) {
        const st = getComputedStyle(el); const r = el.getBoundingClientRect();
        if (st.display === 'none' || st.visibility === 'hidden' || parseFloat(st.opacity || '1') === 0 || r.width < 30 || r.height < 30) continue;
        out.push({cls: el.className || '', id: el.id || '', text: (el.innerText || el.textContent || '').replace(/\s+/g,' ').trim().slice(0,300), rect:{x:r.x,y:r.y,w:r.width,h:r.height}})
      }
      return out.slice(0,20)
    }''')


def close_blockers(page, log):
    for round_idx in range(8):
        dialogs = visible_dialogs(page)
        if not dialogs:
            log.append({'round': round_idx, 'dialogs': []})
            return
        item = {'round': round_idx, 'dialogs': dialogs}
        closed = False
        for sel in [
            '[role="dialog"] .ant-modal-close',
            '.ant-modal-wrap .ant-modal-close',
            '.ant-modal-wrap .ant-modal-close-x',
            '.comm-modal .ant-modal-close',
            '.comm-modal .ant-modal-close-x',
            '.ant-modal-footer button',
        ]:
            try:
                loc = page.locator(sel)
                for i in range(min(loc.count(), 5)):
                    el = loc.nth(i)
                    if el.is_visible(timeout=500):
                        el.click(timeout=1500, force=True)
                        page.wait_for_timeout(1200)
                        item['clicked'] = f'{sel}[{i}]'
                        closed = True
                        break
                if closed:
                    break
            except Exception as e:
                item.setdefault('errors', []).append(f'{sel}: {e}')
        if not closed:
            for txt in ['关闭', '×', '我知道了', '知道了']:
                try:
                    loc = page.get_by_text(txt, exact=True)
                    for i in range(min(loc.count(), 8)):
                        el = loc.nth(i)
                        if el.is_visible(timeout=500):
                            el.click(timeout=1500, force=True)
                            page.wait_for_timeout(1200)
                            item['clicked'] = f'{txt}[{i}]'
                            closed = True
                            break
                    if closed:
                        break
                except Exception as e:
                    item.setdefault('errors', []).append(f'{txt}: {e}')
        if not closed:
            try:
                page.keyboard.press('Escape')
                page.wait_for_timeout(800)
                item['clicked'] = 'Escape'
                closed = True
            except Exception:
                pass
        log.append(item)
        if not closed:
            return


def body_head(page, limit=5000):
    return page.locator('body').inner_text()[:limit]

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
    context = browser.new_context(ignore_https_errors=True, viewport={'width': 1600, 'height': 1400})
    context.add_cookies(load_cookies())
    page = context.new_page()
    result = {}

    page.goto('https://www.dianxiaomi.com/web/productCrawl/dataAcquisition', wait_until='domcontentloaded', timeout=45000)
    page.wait_for_timeout(3500)
    close_log = []
    close_blockers(page, close_log)
    result['close_log'] = close_log
    result['dialogs_after_close'] = visible_dialogs(page)
    result['landing_url'] = page.url
    result['landing_title'] = page.title()
    page.screenshot(path=str(OUT_DIR / 'dxm_claim_v2_step0_clean.png'), full_page=True)

    # ensure unclaimed tab active
    unclaimed_info = {}
    try:
        tab = page.get_by_text('未认领(51)', exact=False).first
        unclaimed_info['visible'] = tab.is_visible(timeout=1000)
        if unclaimed_info['visible']:
            tab.click(timeout=2000)
            page.wait_for_timeout(1200)
            unclaimed_info['clicked'] = True
    except Exception as e:
        unclaimed_info['error'] = str(e)
    result['unclaimed_tab'] = unclaimed_info

    # click first visible claim link
    claim_meta = {}
    claim_loc = page.locator('a').filter(has_text='认领')
    claim_meta['count'] = claim_loc.count()
    clicked = False
    for i in range(min(claim_loc.count(), 12)):
        el = claim_loc.nth(i)
        try:
            if not el.is_visible(timeout=700):
                continue
            claim_meta['candidate'] = i
            claim_meta['box'] = el.bounding_box()
            el.click(timeout=2000)
            page.wait_for_timeout(2500)
            clicked = True
            claim_meta['clicked'] = True
            break
        except Exception as e:
            claim_meta.setdefault('errors', []).append({i: str(e)})
    result['claim_click'] = claim_meta
    page.screenshot(path=str(OUT_DIR / 'dxm_claim_v2_step1_clicked_claim.png'), full_page=True)

    # inspect claim dialog/form
    result['post_claim_dialogs'] = visible_dialogs(page)
    result['post_claim_text_head'] = body_head(page, 7000)
    result['post_claim_controls'] = page.evaluate(r'''() => {
      const out = [];
      for (const el of document.querySelectorAll('input, textarea, button, a, select, [contenteditable="true"], .ql-editor, .ant-select-selector')) {
        const st = getComputedStyle(el); const r = el.getBoundingClientRect();
        if (st.display === 'none' || st.visibility === 'hidden' || parseFloat(st.opacity || '1') === 0 || r.width < 5 || r.height < 5) continue;
        out.push({tag: el.tagName, text: (el.innerText || el.textContent || el.getAttribute('value') || '').replace(/\s+/g,' ').trim().slice(0,120), placeholder: el.getAttribute('placeholder'), cls: el.className || '', id: el.id || '', rect:{x:r.x,y:r.y,w:r.width,h:r.height}})
      }
      return out.slice(0,200)
    }''')

    # choose shop if a select/dropdown appears
    shop_choice = {'attempted': False}
    try:
        selectors = page.locator('.ant-select-selector')
        if selectors.count() > 0:
            for i in range(min(selectors.count(), 5)):
                sel = selectors.nth(i)
                if sel.is_visible(timeout=500):
                    shop_choice['attempted'] = True
                    sel.click(timeout=1500)
                    page.wait_for_timeout(1200)
                    options = page.locator('.ant-select-item-option-content')
                    opt_count = options.count()
                    shop_choice['option_count'] = opt_count
                    names = []
                    for j in range(min(opt_count, 10)):
                        o = options.nth(j)
                        if o.is_visible(timeout=300):
                            names.append(o.inner_text(timeout=500))
                    shop_choice['options_preview'] = names
                    # prefer JOYEE, else first non-empty non-全部
                    chosen = None
                    for name in names:
                        if 'JOYEE' in name:
                            chosen = name
                            break
                    if not chosen:
                        for name in names:
                            if name.strip() and '全部' not in name:
                                chosen = name
                                break
                    if chosen:
                        page.get_by_text(chosen, exact=True).click(timeout=1500)
                        page.wait_for_timeout(1200)
                        shop_choice['chosen'] = chosen
                    break
    except Exception as e:
        shop_choice['error'] = str(e)
    result['shop_choice'] = shop_choice

    # write remark/note if field exists
    remark = {'written': False}
    try:
        # plain remark fields
        for selector in ['textarea[placeholder*="备注"]', 'input[placeholder*="备注"]', 'textarea', 'input']:
            loc = page.locator(selector)
            for i in range(min(loc.count(), 10)):
                el = loc.nth(i)
                if not el.is_visible(timeout=400):
                    continue
                ph = (el.get_attribute('placeholder') or '')
                cls = (el.get_attribute('class') or '')
                if '备注' in ph or selector == 'textarea':
                    el.fill('AI认领', timeout=2000)
                    remark = {'written': True, 'mode': 'plain', 'selector': selector, 'placeholder': ph, 'class': cls}
                    raise SystemExit
        # rich editor fallback
    except SystemExit:
        pass
    except Exception as e:
        remark['error_plain'] = str(e)
    if not remark['written']:
        try:
            for selector in ['[contenteditable="true"]', '.ql-editor']:
                loc = page.locator(selector)
                for i in range(min(loc.count(), 5)):
                    el = loc.nth(i)
                    if not el.is_visible(timeout=400):
                        continue
                    page.evaluate(r'''(el) => {
                        el.focus();
                        el.innerHTML = '<span style="color:#ff0000;">AI认领</span>';
                        el.dispatchEvent(new Event('input', {bubbles:true}));
                        el.dispatchEvent(new Event('change', {bubbles:true}));
                    }''', el)
                    remark = {'written': True, 'mode': 'rich-red', 'selector': selector}
                    raise SystemExit
        except SystemExit:
            pass
        except Exception as e:
            remark['error_rich'] = str(e)
    result['remark'] = remark

    page.screenshot(path=str(OUT_DIR / 'dxm_claim_v2_step2_filled.png'), full_page=True)

    # submit if possible
    submit = {'submitted': False}
    for label in ['认领', '确定', '提交', '确认', '保存并认领']:
        try:
            loc = page.get_by_text(label, exact=True)
            for i in range(min(loc.count(), 8)):
                el = loc.nth(i)
                if el.is_visible(timeout=500):
                    submit['label'] = label
                    submit['index'] = i
                    submit['box'] = el.bounding_box()
                    el.click(timeout=2000)
                    page.wait_for_timeout(3500)
                    submit['submitted'] = True
                    raise SystemExit
        except SystemExit:
            break
        except Exception as e:
            submit.setdefault('errors', []).append({label: str(e)})
    result['submit'] = submit
    result['final_url'] = page.url
    result['final_title'] = page.title()
    result['final_dialogs'] = visible_dialogs(page)
    result['final_text_head'] = body_head(page, 9000)
    page.screenshot(path=str(OUT_DIR / 'dxm_claim_v2_step3_after_submit.png'), full_page=True)

    browser.close()

OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(result, ensure_ascii=False, indent=2))
