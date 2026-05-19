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
    page.wait_for_timeout(800)
    try:
        page.get_by_text('跳过', exact=True).click(force=True, timeout=1500)
        page.wait_for_timeout(800)
    except Exception:
        pass
    data=page.evaluate(r'''() => {
      const anchors = Array.from(document.querySelectorAll('a')).filter(el => (el.innerText||el.textContent||'').trim()==='认领');
      return anchors.slice(0,20).map((el,i) => {
        const r=el.getBoundingClientRect();
        let p=el.parentElement;
        let chain=[];
        for(let j=0;j<5 && p;j++,p=p.parentElement){ chain.push({tag:p.tagName, cls:p.className||'', txt:(p.innerText||p.textContent||'').replace(/\s+/g,' ').trim().slice(0,200)}); }
        return {i, rect:{x:r.x,y:r.y,w:r.width,h:r.height}, href:el.getAttribute('href'), onclick:el.getAttribute('onclick'), outer:el.outerHTML, chain};
      })
    }''')
    print(json.dumps(data, ensure_ascii=False, indent=2))
    browser.close()
