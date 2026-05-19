import json
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path('/root/.Hermes/workspace/dxm-auto-uikit')
COOKIE_FILE=ROOT/'data'/'sessions'/'dianxiaomi_cookies.json'
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
    page.goto('https://www.dianxiaomi.com/web/productCrawl/dataAcquisition', wait_until='domcontentloaded', timeout=45000)
    page.wait_for_timeout(3500)
    page.locator('.ant-modal-close').first.click(force=True)
    page.wait_for_timeout(1000)
    try:
        page.get_by_text('跳过', exact=True).click(force=True, timeout=1500)
        page.wait_for_timeout(1000)
    except Exception:
        pass
    page.evaluate(r'''() => {
      const a = Array.from(document.querySelectorAll('a')).find(el => (el.innerText||el.textContent||'').trim()==='认领');
      if (a) a.dispatchEvent(new MouseEvent('click', {bubbles:true}));
    }''')
    page.wait_for_timeout(1500)
    # click JOYEE label in modal via DOM click dispatch
    res=page.evaluate(r'''() => {
      const label = Array.from(document.querySelectorAll('label.ant-checkbox-wrapper')).find(el => (el.innerText||el.textContent||'').includes('JOYEE'));
      if (!label) return {found:false};
      label.dispatchEvent(new MouseEvent('click', {bubbles:true}));
      return {found:true, text:(label.innerText||label.textContent||'').trim(), html:label.outerHTML.slice(0,200)};
    }''')
    page.wait_for_timeout(1000)
    state=page.evaluate(r'''() => {
      const modal = Array.from(document.querySelectorAll('[role="dialog"], .ant-modal-wrap')).find(el => (el.innerText||el.textContent||'').includes('选择店铺-认领到采集箱'));
      return {
        clicked: true,
        modalText: modal ? (modal.innerText||modal.textContent||'').replace(/\s+/g,' ').trim() : null,
        checkedLabels: Array.from(document.querySelectorAll('label.ant-checkbox-wrapper')).filter(el => el.className.includes('ant-checkbox-wrapper-checked') || el.querySelector('.ant-checkbox-checked')).map(el => (el.innerText||el.textContent||'').replace(/\s+/g,' ').trim()),
      }
    }''')
    print('dispatch', res)
    print(json.dumps(state, ensure_ascii=False, indent=2))
    browser.close()
