import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path('/root/.Hermes/workspace/dxm-auto-uikit')
COOKIE_FILE = ROOT / 'data' / 'sessions' / 'dianxiaomi_cookies.json'
OUT_JSON = ROOT / 'data' / 'sessions' / 'dianxiaomi_test_note_flow.json'
OUT_DIR = ROOT / 'data' / 'screenshots'
OUT_DIR.mkdir(parents=True, exist_ok=True)


def load_cookies():
    raw = json.loads(COOKIE_FILE.read_text(encoding='utf-8'))
    out = []
    for c in raw:
        item = {
            'name': c['name'], 'value': c['value'], 'domain': c['domain'], 'path': c.get('path', '/'),
            'httpOnly': c.get('httpOnly', False), 'secure': c.get('secure', False)
        }
        ss = c.get('sameSite')
        if ss in ('lax', 'strict', 'none', 'Lax', 'Strict', 'None'):
            item['sameSite'] = ss.capitalize() if ss.lower() != 'none' else 'None'
        if 'expirationDate' in c:
            item['expires'] = int(c['expirationDate'])
        out.append(item)
    return out


def q(page, js):
    return page.evaluate(js)


def close_blockers(page, log):
    # close product modal
    try:
        btn = page.locator('.ant-modal-close').first
        if btn.is_visible(timeout=800):
            btn.click(force=True, timeout=1500)
            page.wait_for_timeout(1000)
            log.append('closed .ant-modal-close')
    except Exception as e:
        log.append(f'no modal close: {e}')
    # skip guide
    try:
        skip = page.get_by_text('跳过', exact=True)
        if skip.count() > 0 and skip.first.is_visible(timeout=800):
            skip.first.click(force=True, timeout=1500)
            page.wait_for_timeout(1000)
            log.append('clicked 跳过')
    except Exception as e:
        log.append(f'no 跳过: {e}')


def body_head(page, limit=4000):
    try:
        return page.locator('body').inner_text()[:limit]
    except Exception as e:
        return f'<body_error:{e}>'


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
    ctx = browser.new_context(ignore_https_errors=True, viewport={'width': 1600, 'height': 1400})
    ctx.add_cookies(load_cookies())
    page = ctx.new_page()
    result = {'steps': []}

    page.goto('https://www.dianxiaomi.com/web/productCrawl/dataAcquisition', wait_until='domcontentloaded', timeout=45000)
    page.wait_for_timeout(3500)
    close_log = []
    close_blockers(page, close_log)
    result['steps'].append({'step': 'landing', 'url': page.url, 'title': page.title(), 'close_log': close_log})
    page.screenshot(path=str(OUT_DIR / 'dxm_test_note_flow_01_landing.png'), full_page=True)

    # capture counts and first row title before claim
    pre = q(page, r'''() => {
      const text = document.body.innerText;
      const firstClaim = Array.from(document.querySelectorAll('a')).find(el => (el.innerText||el.textContent||'').trim()==='认领');
      const tr = firstClaim?.closest('tr');
      const rowText = tr ? (tr.innerText||tr.textContent||'').replace(/\s+/g,' ').trim() : null;
      const tabs = Array.from(document.querySelectorAll('*')).map(el => (el.innerText||el.textContent||'').replace(/\s+/g,'').trim()).filter(Boolean);
      return {
        counts: tabs.filter(t => /^全部\(\d+\)$|^未认领\(\d+\)$|^已认领\(\d+\)$/.test(t)).slice(0,5),
        rowText,
      };
    }''')
    result['steps'].append({'step': 'pre_claim_state', **pre})
    target_title = (pre.get('rowText') or '').split(' 0.')[0][:60]

    # open claim modal by DOM dispatch
    open_claim = q(page, r'''() => {
      const a = Array.from(document.querySelectorAll('a')).find(el => (el.innerText||el.textContent||'').trim()==='认领');
      if (!a) return {ok:false, reason:'no_claim_anchor'};
      a.dispatchEvent(new MouseEvent('click', {bubbles:true}));
      return {ok:true};
    }''')
    page.wait_for_timeout(1800)
    result['steps'].append({'step': 'open_claim', **open_claim})
    page.screenshot(path=str(OUT_DIR / 'dxm_test_note_flow_02_claim_modal.png'), full_page=True)

    # choose Dang Kang
    choose = q(page, r'''() => {
      const label = Array.from(document.querySelectorAll('label.ant-checkbox-wrapper')).find(el => (el.innerText||el.textContent||'').includes('Dang Kang'));
      if (!label) return {ok:false, reason:'no_dang_kang'};
      label.dispatchEvent(new MouseEvent('click', {bubbles:true}));
      const modal = Array.from(document.querySelectorAll('[role="dialog"], .ant-modal-wrap')).find(el => (el.innerText||el.textContent||'').includes('选择店铺-认领到采集箱'));
      return {
        ok:true,
        modalText: modal ? (modal.innerText||modal.textContent||'').replace(/\s+/g,' ').trim().slice(0,500) : null,
        checked: Array.from(document.querySelectorAll('label.ant-checkbox-wrapper')).filter(el => el.className.includes('ant-checkbox-wrapper-checked') || el.querySelector('.ant-checkbox-checked')).map(el => (el.innerText||el.textContent||'').replace(/\s+/g,' ').trim())
      };
    }''')
    page.wait_for_timeout(800)
    result['steps'].append({'step': 'choose_store', **choose})

    # confirm claim
    confirm = q(page, r'''() => {
      const btn = Array.from(document.querySelectorAll('button, span, a, div')).find(el => (el.innerText||el.textContent||'').replace(/\s+/g,'').trim()==='确定');
      if (!btn) return {ok:false, reason:'no_confirm'};
      btn.dispatchEvent(new MouseEvent('click', {bubbles:true}));
      return {ok:true, tag: btn.tagName, cls: btn.className || ''};
    }''')
    page.wait_for_timeout(5000)
    page.screenshot(path=str(OUT_DIR / 'dxm_test_note_flow_03_claim_result.png'), full_page=True)
    post_claim = q(page, r'''() => ({
      dialogs: Array.from(document.querySelectorAll('[role="dialog"], .ant-modal-wrap')).map(el => ({cls: el.className || '', txt: (el.innerText||el.textContent||'').replace(/\s+/g,' ').trim().slice(0,300)})).slice(0,20),
      counts: Array.from(document.querySelectorAll('*')).map(el => (el.innerText||el.textContent||'').replace(/\s+/g,'').trim()).filter(t => /^全部\(\d+\)$|^未认领\(\d+\)$|^已认领\(\d+\)$/.test(t)).slice(0,5)
    })''')
    result['steps'].append({'step': 'claim_result', 'confirm': confirm, **post_claim})

    # close success / claim dialogs if any close buttons
    close_log2 = []
    for _ in range(3):
        try:
            btn = page.locator('.ant-modal-close').first
            if btn.is_visible(timeout=800):
                btn.click(force=True, timeout=1200)
                page.wait_for_timeout(800)
                close_log2.append('closed .ant-modal-close')
            else:
                break
        except Exception:
            break
    result['steps'].append({'step': 'post_claim_close', 'log': close_log2})

    # switch to claimed tab
    switch_claimed = q(page, r'''() => {
      const tab = Array.from(document.querySelectorAll('*')).find(el => {
        const t = (el.innerText||el.textContent||'').replace(/\s+/g,'').trim();
        return /^已认领\(\d+\)$/.test(t);
      });
      if (!tab) return {ok:false, reason:'no_claimed_tab'};
      const text = (tab.innerText||tab.textContent||'').replace(/\s+/g,'').trim();
      tab.dispatchEvent(new MouseEvent('click', {bubbles:true}));
      return {ok:true, text};
    }''')
    page.wait_for_timeout(1200)
    result['steps'].append({'step': 'switch_claimed', **switch_claimed})

    # search by title fragment
    title_fragment = ''.join(ch for ch in target_title if ch not in ' \t')[:12] or '地狱客栈'
    search_fill = q(page, json.dumps(title_fragment))
    # fill the main search input using DOM
    fill_res = page.evaluate(r'''(frag) => {
      const inputs = Array.from(document.querySelectorAll('input.ant-input, input'));
      const target = inputs.find(el => {
        const r = el.getBoundingClientRect();
        return r.width > 120 && r.height > 20 && !el.disabled;
      });
      if (!target) return {ok:false, reason:'no_search_input'};
      target.focus();
      target.value = frag;
      target.dispatchEvent(new Event('input', {bubbles:true}));
      target.dispatchEvent(new Event('change', {bubbles:true}));
      return {ok:true, value: target.value, placeholder: target.getAttribute('placeholder')};
    }''', title_fragment)
    page.wait_for_timeout(500)
    search_click = q(page, r'''() => {
      const btn = Array.from(document.querySelectorAll('button, span, a, div')).find(el => (el.innerText||el.textContent||'').replace(/\s+/g,'').trim()==='搜索');
      if (!btn) return {ok:false, reason:'no_search_btn'};
      btn.dispatchEvent(new MouseEvent('click', {bubbles:true}));
      return {ok:true};
    }''')
    page.wait_for_timeout(2000)
    page.screenshot(path=str(OUT_DIR / 'dxm_test_note_flow_04_claimed_search.png'), full_page=True)
    result['steps'].append({'step': 'search_claimed_row', 'fragment': title_fragment, 'fill': fill_res, 'search_click': search_click, 'body': body_head(page, 3500)})

    # open more for matching row or first row
    open_more = page.evaluate(r'''(frag) => {
      const rows = Array.from(document.querySelectorAll('tr.vxe-body--row, tr'));
      let row = rows.find(tr => (tr.innerText||tr.textContent||'').replace(/\s+/g,'').includes(frag.replace(/\s+/g,'')));
      if (!row) row = rows.find(tr => (tr.innerText||tr.textContent||'').includes('查看记录'));
      if (!row) return {ok:false, reason:'no_row_found'};
      const rowText = (row.innerText||row.textContent||'').replace(/\s+/g,' ').trim().slice(0,400);
      let more = Array.from(row.querySelectorAll('a,div,span,button')).find(el => (el.innerText||el.textContent||'').replace(/\s+/g,'').trim()==='更多');
      if (!more) return {ok:false, reason:'no_more_in_row', rowText};
      more.dispatchEvent(new MouseEvent('click', {bubbles:true}));
      return {ok:true, rowText};
    }''', title_fragment)
    page.wait_for_timeout(1200)
    page.screenshot(path=str(OUT_DIR / 'dxm_test_note_flow_05_more_menu.png'), full_page=True)
    result['steps'].append({'step': 'open_more_menu', **open_more})

    # click add note
    click_add_note = page.evaluate(r'''() => {
      const node = Array.from(document.querySelectorAll('li,div,a,span,button')).find(el => (el.innerText||el.textContent||'').replace(/\s+/g,'').trim()==='添加备注');
      if (!node) return {ok:false, reason:'no_add_note'};
      node.dispatchEvent(new MouseEvent('click', {bubbles:true}));
      return {ok:true, tag: node.tagName, cls: node.className || ''};
    }''')
    page.wait_for_timeout(1500)
    page.screenshot(path=str(OUT_DIR / 'dxm_test_note_flow_06_note_dialog.png'), full_page=True)

    modal = page.evaluate(r'''() => {
      const dialog = Array.from(document.querySelectorAll('[role="dialog"], .ant-modal-wrap, .ant-drawer, .tox-tinymce')).find(el => {
        const t=(el.innerText||el.textContent||'').replace(/\s+/g,' ').trim();
        return t.includes('备注') || t.includes('添加备注');
      });
      const controls = Array.from(document.querySelectorAll('input, textarea, button, a, span, div, [contenteditable="true"], .tox-tinymce, .tox-toolbar, .tox-edit-area, .ql-editor')).map(el => {
        const st=getComputedStyle(el), r=el.getBoundingClientRect();
        if (st.display==='none'||st.visibility==='hidden'||parseFloat(st.opacity||'1')===0||r.width<5||r.height<5) return null;
        return {tag:el.tagName, text:(el.innerText||el.textContent||el.getAttribute('value')||'').replace(/\s+/g,' ').trim().slice(0,100), placeholder:el.getAttribute('placeholder'), cls:el.className||'', rect:{x:r.x,y:r.y,w:r.width,h:r.height}};
      }).filter(Boolean).slice(0,250);
      return {dialogText: dialog ? (dialog.innerText||dialog.textContent||'').replace(/\s+/g,' ').trim().slice(0,2000) : null, controls};
    }''')
    result['steps'].append({'step': 'note_modal', 'click_add_note': click_add_note, **modal})

    # write note AI认领 in red if possible
    note_write = {'ok': False}
    try:
        # rich text first
        res = page.evaluate(r'''() => {
          const rich = document.querySelector('[contenteditable="true"], .ql-editor');
          if (rich) {
            rich.focus();
            rich.innerHTML = '<span style="color:#ff0000;">AI认领</span>';
            rich.dispatchEvent(new Event('input', {bubbles:true}));
            rich.dispatchEvent(new Event('change', {bubbles:true}));
            return {ok:true, mode:'rich-red'};
          }
          return {ok:false};
        }''')
        note_write = res
    except Exception:
        pass
    if not note_write.get('ok'):
        try:
            res = page.evaluate(r'''() => {
              const ta = Array.from(document.querySelectorAll('textarea, input')).find(el => {
                const r = el.getBoundingClientRect();
                return r.width > 100 && r.height > 20 && !el.disabled;
              });
              if (!ta) return {ok:false, reason:'no_text_input'};
              ta.value = 'AI认领';
              ta.style.color = 'red';
              ta.dispatchEvent(new Event('input', {bubbles:true}));
              ta.dispatchEvent(new Event('change', {bubbles:true}));
              return {ok:true, mode:'plain-input-red-style', placeholder: ta.getAttribute('placeholder'), className: ta.className || ''};
            }''')
            note_write = res
        except Exception as e:
            note_write = {'ok': False, 'error': str(e)}
    page.wait_for_timeout(500)
    page.screenshot(path=str(OUT_DIR / 'dxm_test_note_flow_07_note_filled.png'), full_page=True)
    result['steps'].append({'step': 'note_write', **note_write})

    # save note
    save = page.evaluate(r'''() => {
      const btn = Array.from(document.querySelectorAll('button, span, a, div')).find(el => {
        const t=(el.innerText||el.textContent||'').replace(/\s+/g,'').trim();
        return t==='保存' || t==='确定';
      });
      if (!btn) return {ok:false, reason:'no_save_btn'};
      btn.dispatchEvent(new MouseEvent('click', {bubbles:true}));
      return {ok:true, text:(btn.innerText||btn.textContent||'').replace(/\s+/g,'').trim(), tag: btn.tagName, cls: btn.className || ''};
    }''')
    page.wait_for_timeout(3000)
    page.screenshot(path=str(OUT_DIR / 'dxm_test_note_flow_08_after_save.png'), full_page=True)
    after_save = page.evaluate(r'''() => ({
      dialogs: Array.from(document.querySelectorAll('[role="dialog"], .ant-modal-wrap')).map(el => ({cls: el.className || '', txt: (el.innerText||el.textContent||'').replace(/\s+/g,' ').trim().slice(0,300)})).slice(0,10),
      body: document.body.innerText.slice(0,5000)
    })''')
    result['steps'].append({'step': 'after_save', 'save': save, **after_save})

    browser.close()

OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(result, ensure_ascii=False, indent=2))
