import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path('/root/.Hermes/workspace/dxm-auto-uikit')
COOKIE_FILE = ROOT / 'data' / 'sessions' / 'dianxiaomi_cookies.json'
OUT_JSON = ROOT / 'data' / 'sessions' / 'dianxiaomi_edit_newpage_probe.json'
OUT_DIR = ROOT / 'data' / 'screenshots'
OUT_DIR.mkdir(parents=True, exist_ok=True)
TARGET_TEXT='崩坏3钥匙扣爱莉希雅'

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
    page.goto('https://www.dianxiaomi.com/web/smt/smtProductList/draft', wait_until='domcontentloaded', timeout=45000)
    page.wait_for_timeout(3500)
    page.evaluate(r'''({target, frag}) => {
      const all = Array.from(document.querySelectorAll('*'));
      const store = all.find(el => (el.innerText||el.textContent||'').replace(/\s+/g,'').trim() === target.replace(/\s+/g,''));
      if (store) store.dispatchEvent(new MouseEvent('click', {bubbles:true}));
      const input = Array.from(document.querySelectorAll('input.ant-input,input')).find(el => { const r=el.getBoundingClientRect(); return r.width>220 && r.height>20 && !el.disabled;});
      if (input) { input.value=frag; input.dispatchEvent(new Event('input',{bubbles:true})); input.dispatchEvent(new Event('change',{bubbles:true})); }
      const btn = all.find(el => (el.innerText||el.textContent||'').replace(/\s+/g,'').trim()==='搜索');
      if (btn) btn.dispatchEvent(new MouseEvent('click',{bubbles:true}));
    }''', {'target':'Dang Kang','frag':TARGET_TEXT})
    page.wait_for_timeout(2200)
    edits=page.locator('a').filter(has_text='编辑')
    edits.first.click(timeout=3000)
    page.wait_for_timeout(1500)
    skip=page.get_by_text('跳过，去编辑产品', exact=True)
    if skip.count()>0:
        skip.first.click(timeout=3000)
    page.wait_for_timeout(4500)
    result['pages']=[{'url':pg.url,'title':pg.title()} for pg in ctx.pages]
    if len(ctx.pages)>1:
        newp=ctx.pages[-1]
        newp.wait_for_timeout(1500)
        newp.screenshot(path=str(OUT_DIR/'dxm_edit_newpage.png'), full_page=True)
        result['new_page']={
            'url':newp.url,
            'title':newp.title(),
            'body':newp.locator('body').inner_text()[:8000]
        }
    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    browser.close()
