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
    page.wait_for_timeout(2000)
    data=page.evaluate(r'''() => {
      const modal = Array.from(document.querySelectorAll('[role="dialog"], .ant-modal-wrap')).find(el => (el.innerText||el.textContent||'').includes('选择店铺-认领到采集箱'));
      if (!modal) return {found:false};
      const nodes = Array.from(modal.querySelectorAll('input, button, a, label, span, div')).map(el => {
        const st=getComputedStyle(el), r=el.getBoundingClientRect();
        if (st.display==='none' || st.visibility==='hidden' || parseFloat(st.opacity||'1')===0 || r.width<5 || r.height<5) return null;
        const txt=(el.innerText||el.textContent||el.getAttribute('value')||'').replace(/\s+/g,' ').trim();
        const checked = el.getAttribute('aria-checked') || el.checked || el.getAttribute('checked') || null;
        return {tag:el.tagName, type:el.getAttribute('type'), txt:txt.slice(0,120), cls:el.className||'', checked, rect:{x:r.x,y:r.y,w:r.width,h:r.height}};
      }).filter(Boolean);
      return {found:true, text:(modal.innerText||modal.textContent||'').replace(/\s+/g,' ').trim(), nodes:nodes.slice(0,250)};
    }''')
    print(json.dumps(data, ensure_ascii=False, indent=2))
    browser.close()
