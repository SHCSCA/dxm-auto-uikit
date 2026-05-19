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
    page.goto('https://www.dianxiaomi.com/web/smt/smtProductList/draft', wait_until='domcontentloaded', timeout=45000)
    page.wait_for_timeout(3500)
    page.evaluate(r'''({target, frag}) => { const stores=[...document.querySelectorAll("*")]; const s=stores.find(el=>(el.innerText||el.textContent||"").replace(/\s+/g,"").trim()===target.replace(/\s+/g,"")); if(s) s.dispatchEvent(new MouseEvent("click",{bubbles:true})); const input=[...document.querySelectorAll("input.ant-input,input")].find(el=>{const r=el.getBoundingClientRect(); return r.width>220 && r.height>20 && !el.disabled}); if(input){input.value=frag; input.dispatchEvent(new Event("input",{bubbles:true})); input.dispatchEvent(new Event("change",{bubbles:true}));} const btn=[...document.querySelectorAll("button,span,a,div")].find(el=>(el.innerText||el.textContent||"").replace(/\s+/g,"").trim()==="搜索"); if(btn) btn.dispatchEvent(new MouseEvent("click",{bubbles:true})); }''', {'target':'Dang Kang','frag':'崩坏3钥匙扣爱莉希雅'})
    page.wait_for_timeout(2200)
    print(json.dumps(page.evaluate(r'''() => {
      const rows=[...document.querySelectorAll('tr.vxe-body--row, tr')];
      const idx=rows.findIndex(tr=>(tr.innerText||tr.textContent||'').includes('崩坏3钥匙扣爱莉希雅') && !(tr.innerText||tr.textContent||'').includes('备注:'));
      if(idx<0) return {ok:false};
      const row=rows[idx];
      const els=[...row.querySelectorAll('*')].map(el=>{
        const txt=(el.innerText||el.textContent||'').replace(/\s+/g,' ').trim();
        const r=el.getBoundingClientRect();
        if(!txt || r.width<5 || r.height<5) return null;
        return {tag:el.tagName, txt, cls:String(el.className||''), rect:{x:r.x,y:r.y,w:r.width,h:r.height}};
      }).filter(Boolean);
      return {ok:true, idx, els:els.slice(-80)};
    }'''), ensure_ascii=False, indent=2))
    browser.close()
