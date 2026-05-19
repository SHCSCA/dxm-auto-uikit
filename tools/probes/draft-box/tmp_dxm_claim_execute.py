import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path('/root/.Hermes/workspace/dxm-auto-uikit')
COOKIE_FILE=ROOT/'data'/'sessions'/'dianxiaomi_cookies.json'
OUT_JSON=ROOT/'data'/'sessions'/'dianxiaomi_claim_execute.json'
OUT_DIR=ROOT/'data'/'screenshots'
OUT_DIR.mkdir(parents=True, exist_ok=True)

def load_cookies():
    raw=json.loads(COOKIE_FILE.read_text(encoding='utf-8'))
    out=[]
    for c in raw:
        item={'name':c['name'],'value':c['value'],'domain':c['domain'],'path':c.get('path','/'),'httpOnly':c.get('httpOnly',False),'secure':c.get('secure',False)}
        ss=c.get('sameSite')
        if ss in ('lax','strict','none','Lax','Strict','None'): item['sameSite']=ss.capitalize() if ss.lower()!='none' else 'None'
        if 'expirationDate' in c: item['expires']=int(c['expirationDate'])
        out.append(item)
    return out

with sync_playwright() as p:
    browser=p.chromium.launch(headless=True, executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
    ctx=browser.new_context(ignore_https_errors=True, viewport={'width':1600,'height':1400})
    ctx.add_cookies(load_cookies())
    page=ctx.new_page()
    result={}

    page.goto('https://www.dianxiaomi.com/web/productCrawl/dataAcquisition', wait_until='domcontentloaded', timeout=45000)
    page.wait_for_timeout(3500)
    # close blockers
    try:
        page.locator('.ant-modal-close').first.click(force=True)
        page.wait_for_timeout(1000)
    except Exception:
        pass
    try:
        page.get_by_text('跳过', exact=True).click(force=True, timeout=1500)
        page.wait_for_timeout(1000)
    except Exception:
        pass
    result['before_text'] = page.locator('body').inner_text()[:4000]
    page.screenshot(path=str(OUT_DIR/'dxm_claim_execute_before.png'), full_page=True)

    # record first row title for traceability
    first_row = page.evaluate(r'''() => {
      const a = Array.from(document.querySelectorAll('a')).find(el => (el.innerText||el.textContent||'').trim()==='认领');
      if (!a) return null;
      const tr = a.closest('tr');
      return tr ? (tr.innerText||tr.textContent||'').replace(/\s+/g,' ').trim().slice(0,400) : null;
    }''')
    result['target_row'] = first_row

    # open claim modal via browser event dispatch because UI overlay interferes with locator clicks
    result['open_claim'] = page.evaluate(r'''() => {
      const a = Array.from(document.querySelectorAll('a')).find(el => (el.innerText||el.textContent||'').trim()==='认领');
      if (!a) return {ok:false, reason:'no_claim_anchor'};
      a.dispatchEvent(new MouseEvent('click', {bubbles:true}));
      return {ok:true};
    }''')
    page.wait_for_timeout(1800)

    # choose JOYEE store
    result['choose_store'] = page.evaluate(r'''() => {
      const label = Array.from(document.querySelectorAll('label.ant-checkbox-wrapper')).find(el => (el.innerText||el.textContent||'').includes('JOYEE'));
      if (!label) return {ok:false, reason:'no_joyee'};
      label.dispatchEvent(new MouseEvent('click', {bubbles:true}));
      const modal = Array.from(document.querySelectorAll('[role="dialog"], .ant-modal-wrap')).find(el => (el.innerText||el.textContent||'').includes('选择店铺-认领到采集箱'));
      return {ok:true, modalText: modal ? (modal.innerText||modal.textContent||'').replace(/\s+/g,' ').trim().slice(0,500) : null};
    }''')
    page.wait_for_timeout(800)

    # inspect whether any note/remark field exists in claim modal
    result['remark_fields'] = page.evaluate(r'''() => {
      const modal = Array.from(document.querySelectorAll('[role="dialog"], .ant-modal-wrap')).find(el => (el.innerText||el.textContent||'').includes('选择店铺-认领到采集箱'));
      if (!modal) return [];
      return Array.from(modal.querySelectorAll('input, textarea, [contenteditable="true"], .ql-editor')).map(el => ({
        tag: el.tagName,
        placeholder: el.getAttribute('placeholder'),
        cls: el.className || '',
        text: (el.innerText||el.textContent||el.getAttribute('value')||'').replace(/\s+/g,' ').trim().slice(0,120)
      }));
    }''')

    # confirm claim
    result['confirm_click'] = page.evaluate(r'''() => {
      const btn = Array.from(document.querySelectorAll('button, span, a, div')).find(el => (el.innerText||el.textContent||'').replace(/\s+/g,'').trim()==='确定');
      if (!btn) return {ok:false, reason:'no_confirm'};
      btn.dispatchEvent(new MouseEvent('click', {bubbles:true}));
      return {ok:true, tag: btn.tagName, cls: btn.className || ''};
    }''')
    page.wait_for_timeout(5000)
    page.screenshot(path=str(OUT_DIR/'dxm_claim_execute_after.png'), full_page=True)

    result['after_url'] = page.url
    result['after_title'] = page.title()
    result['after_text'] = page.locator('body').inner_text()[:6000]
    result['dialogs_after'] = page.evaluate(r'''() => Array.from(document.querySelectorAll('[role="dialog"], .ant-modal-wrap')).map(el => ({cls: el.className || '', txt: (el.innerText||el.textContent||'').replace(/\s+/g,' ').trim().slice(0,300)})).slice(0,20)''')

    # verify by opening draft page
    page.goto('https://www.dianxiaomi.com/web/smt/smtProductList/draft', wait_until='domcontentloaded', timeout=45000)
    page.wait_for_timeout(3500)
    page.screenshot(path=str(OUT_DIR/'dxm_claim_execute_draft_verify.png'), full_page=True)
    result['draft_verify'] = {
        'url': page.url,
        'title': page.title(),
        'text': page.locator('body').inner_text()[:5000]
    }

    browser.close()

OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(result, ensure_ascii=False, indent=2))
