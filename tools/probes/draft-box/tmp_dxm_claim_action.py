import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path('/root/.Hermes/workspace/dxm-auto-uikit')
COOKIE_FILE = ROOT / 'data' / 'sessions' / 'dianxiaomi_cookies.json'
OUT_DIR = ROOT / 'data' / 'screenshots'
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_JSON = ROOT / 'data' / 'sessions' / 'dianxiaomi_claim_action.json'


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


def text_dump(page, limit=5000):
    try:
        return page.locator('body').inner_text(timeout=5000)[:limit]
    except Exception as e:
        return f'<text_error:{e}>'


def visible_dialogs(page):
    return page.evaluate(r'''() => {
      const out = [];
      for (const el of document.querySelectorAll('[role="dialog"], .ant-modal, .ant-drawer, .ant-popover, .ant-select-dropdown, .ant-dropdown')) {
        const st = getComputedStyle(el);
        const r = el.getBoundingClientRect();
        if (st.display === 'none' || st.visibility === 'hidden' || parseFloat(st.opacity || '1') === 0 || r.width < 20 || r.height < 20) continue;
        out.push({tag: el.tagName, cls: el.className || '', id: el.id || '', text: (el.innerText || el.textContent || '').replace(/\s+/g,' ').trim().slice(0,500), rect:{x:r.x,y:r.y,w:r.width,h:r.height}})
      }
      return out.slice(0,30)
    }''')


def visible_controls(page):
    return page.evaluate(r'''() => {
      const targets = [];
      for (const el of document.querySelectorAll('input, textarea, button, a, [contenteditable="true"], .ql-editor, .w-e-text-container, .tox-edit-area')) {
        const st = getComputedStyle(el);
        const r = el.getBoundingClientRect();
        if (st.display === 'none' || st.visibility === 'hidden' || parseFloat(st.opacity || '1') === 0 || r.width < 5 || r.height < 5) continue;
        const txt = (el.innerText || el.textContent || el.getAttribute('value') || el.getAttribute('placeholder') || '').replace(/\s+/g,' ').trim();
        targets.push({tag: el.tagName, type: el.getAttribute('type'), text: txt.slice(0,150), placeholder: el.getAttribute('placeholder'), cls: el.className || '', id: el.id || '', href: el.getAttribute('href'), rect:{x:r.x,y:r.y,w:r.width,h:r.height}})
      }
      return targets.slice(0,300)
    }''')

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
    context = browser.new_context(ignore_https_errors=True, viewport={'width': 1600, 'height': 1400})
    context.add_cookies(load_cookies())
    page = context.new_page()
    data = {'steps': []}

    page.goto('https://www.dianxiaomi.com/web/productCrawl/dataAcquisition', wait_until='domcontentloaded', timeout=45000)
    page.wait_for_timeout(3500)
    page.screenshot(path=str(OUT_DIR / 'dxm_claim_step0_data_acq.png'), full_page=True)
    data['steps'].append({'step': 'landing', 'url': page.url, 'title': page.title(), 'text': text_dump(page)})

    # Ensure we're on 未认领 tab if visible
    for label in ['未认领(51)', '未认领']:
        try:
            loc = page.get_by_text(label, exact=False)
            if loc.count() > 0 and loc.first.is_visible(timeout=800):
                loc.first.click(timeout=2000)
                page.wait_for_timeout(1500)
                data['steps'].append({'step': 'clicked_unclaimed_tab', 'label': label})
                break
        except Exception as e:
            data['steps'].append({'step': 'clicked_unclaimed_tab_error', 'label': label, 'error': str(e)})

    # Click first visible 认领
    claim_clicked = False
    claim_href_info = None
    claim_loc = page.locator('a').filter(has_text='认领')
    count = claim_loc.count()
    data['steps'].append({'step': 'claim_locator_count', 'count': count})
    for i in range(min(count, 10)):
        el = claim_loc.nth(i)
        try:
            if not el.is_visible(timeout=800):
                continue
            box = el.bounding_box()
            txt = el.inner_text(timeout=1000)
            claim_href_info = {'i': i, 'box': box, 'text': txt}
            el.click(timeout=2500)
            page.wait_for_timeout(2500)
            claim_clicked = True
            data['steps'].append({'step': 'clicked_claim', **claim_href_info, 'url_after': page.url, 'title_after': page.title()})
            break
        except Exception as e:
            data['steps'].append({'step': 'clicked_claim_error', 'i': i, 'error': str(e)})

    page.screenshot(path=str(OUT_DIR / 'dxm_claim_step1_after_click_claim.png'), full_page=True)
    dialogs1 = visible_dialogs(page)
    controls1 = visible_controls(page)
    data['steps'].append({'step': 'after_click_claim_state', 'dialogs': dialogs1, 'controls_sample': controls1[:120], 'url': page.url, 'title': page.title(), 'text': text_dump(page, 7000)})

    # Try to find remark/notes/textarea/editor and set AI认领 in red if possible
    remark_written = False
    remark_mode = None
    # textarea/input candidates
    for selector in ['textarea', 'input[placeholder*="备注"]', 'textarea[placeholder*="备注"]', 'input', '[contenteditable="true"]', '.ql-editor']:
        try:
            loc = page.locator(selector)
            for i in range(min(loc.count(), 20)):
                el = loc.nth(i)
                if not el.is_visible(timeout=500):
                    continue
                ph = el.get_attribute('placeholder') or ''
                cls = el.get_attribute('class') or ''
                if selector in ['textarea', 'input', 'input[placeholder*="备注"]', 'textarea[placeholder*="备注"]'] and ('备注' in ph or selector == 'textarea'):
                    el.fill('AI认领', timeout=2000)
                    remark_written = True
                    remark_mode = f'plain:{selector}'
                    break
                if selector in ['[contenteditable="true"]', '.ql-editor']:
                    # rich text with red color
                    page.evaluate(r'''(el) => {
                      el.focus();
                      const sel = window.getSelection();
                      const range = document.createRange();
                      range.selectNodeContents(el);
                      range.collapse(false);
                      sel.removeAllRanges();
                      sel.addRange(range);
                      document.execCommand('insertText', false, 'AI认领');
                      const range2 = document.createRange();
                      if (el.firstChild) {
                        range2.setStart(el.firstChild, 0);
                        range2.setEnd(el.firstChild, el.firstChild.textContent.length);
                        sel.removeAllRanges();
                        sel.addRange(range2);
                        document.execCommand('foreColor', false, '#ff0000');
                      }
                    }''', el)
                    remark_written = True
                    remark_mode = f'rich:{selector}'
                    break
            if remark_written:
                break
        except Exception as e:
            data['steps'].append({'step': 'remark_write_error', 'selector': selector, 'error': str(e)})

    # Also inspect dropdowns for shop selection
    dialogs2 = visible_dialogs(page)
    controls2 = visible_controls(page)
    page.screenshot(path=str(OUT_DIR / 'dxm_claim_step2_before_submit.png'), full_page=True)
    data['steps'].append({'step': 'before_submit_state', 'remark_written': remark_written, 'remark_mode': remark_mode, 'dialogs': dialogs2, 'controls_sample': controls2[:160], 'url': page.url, 'title': page.title(), 'text': text_dump(page, 9000)})

    # Try submit/confirm if visible, prioritizing 保存并认领 / 认领 / 确定 / 提交
    submitted = False
    for label in ['保存并认领', '认领', '确定', '提交', '确认']:
        try:
            loc = page.get_by_text(label, exact=True)
            for i in range(min(loc.count(), 8)):
                el = loc.nth(i)
                if el.is_visible(timeout=700):
                    box = el.bounding_box()
                    el.click(timeout=2500)
                    page.wait_for_timeout(3000)
                    data['steps'].append({'step': 'clicked_submit', 'label': label, 'i': i, 'box': box, 'url_after': page.url, 'title_after': page.title()})
                    submitted = True
                    raise SystemExit
        except SystemExit:
            break
        except Exception as e:
            data['steps'].append({'step': 'submit_click_error', 'label': label, 'error': str(e)})

    page.screenshot(path=str(OUT_DIR / 'dxm_claim_step3_after_submit.png'), full_page=True)
    data['steps'].append({'step': 'after_submit_state', 'submitted': submitted, 'url': page.url, 'title': page.title(), 'dialogs': visible_dialogs(page), 'controls_sample': visible_controls(page)[:160], 'text': text_dump(page, 10000)})

    browser.close()

OUT_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(data, ensure_ascii=False, indent=2))
