import json
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path('/root/.Hermes/workspace/dxm-auto-uikit')
COOKIE_FILE=ROOT/'data'/'sessions'/'dianxiaomi_cookies.json'
OUT_JSON=ROOT/'data'/'sessions'/'dianxiaomi_claim_flow_probe.json'
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
    page.goto('https://www.dianxiaomi.com/web/productCrawl/dataAcquisition', wait_until='domcontentloaded', timeout=45000)
    page.wait_for_timeout(3500)
    # close product modal
    try:
        page.locator('.ant-modal-close').first.click(force=True)
        page.wait_for_timeout(1000)
    except Exception:
        pass
    # skip guide overlay
    try:
        page.get_by_text('跳过', exact=True).click(force=True, timeout=1500)
        page.wait_for_timeout(1000)
    except Exception:
        pass
    page.screenshot(path=str(OUT_DIR/'dxm_claim_probe_cleaned.png'), full_page=True)
    result={'after_cleanup': page.evaluate(r'''() => ({
        dialog: document.querySelector('[role="dialog"]')?.innerText || null,
        guideDisplay: getComputedStyle(document.querySelector('.guide-overlay')||document.body).display,
        guideText: document.querySelector('.guide-body')?.innerText || null,
        body: document.body.innerText.slice(0,2000)
    })''')}
    # click first visible claim
    claim=page.locator('a').filter(has_text='认领').first
    result['claim_before']={'visible': claim.is_visible(timeout=1000), 'box': claim.bounding_box()}
    claim.click(force=True, timeout=2000)
    page.wait_for_timeout(2500)
    page.screenshot(path=str(OUT_DIR/'dxm_claim_probe_after_claim_click.png'), full_page=True)
    result['after_claim']=page.evaluate(r'''() => ({
        url: location.href,
        title: document.title,
        dialogText: Array.from(document.querySelectorAll('[role="dialog"], .ant-modal-wrap, .ant-select-dropdown, .ant-dropdown')).map(el => ({cls: el.className||'', txt:(el.innerText||el.textContent||'').replace(/\s+/g,' ').trim().slice(0,400)})).slice(0,20),
        text: document.body.innerText.slice(0,4000),
        controls: Array.from(document.querySelectorAll('input, textarea, button, a, [contenteditable="true"], .ant-select-selector')).map(el => {
            const st=getComputedStyle(el), r=el.getBoundingClientRect();
            if (st.display==='none'||st.visibility==='hidden'||parseFloat(st.opacity||'1')===0||r.width<5||r.height<5) return null;
            return {tag:el.tagName, text:(el.innerText||el.textContent||el.getAttribute('value')||'').replace(/\s+/g,' ').trim().slice(0,120), ph:el.getAttribute('placeholder'), cls:el.className||'', rect:{x:r.x,y:r.y,w:r.width,h:r.height}};
        }).filter(Boolean).slice(0,200)
    })''')
    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    browser.close()
