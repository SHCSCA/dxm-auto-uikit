import json
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path('/root/.Hermes/workspace/dxm-auto-uikit')
COOKIE_FILE=ROOT/'data'/'sessions'/'dianxiaomi_cookies.json'
OUT_JSON=ROOT/'data'/'sessions'/'dianxiaomi_edit_direct_probe.json'
OUT_DIR=ROOT/'data'/'screenshots'
OUT_DIR.mkdir(parents=True, exist_ok=True)
URL='https://www.dianxiaomi.com/web/smt/edit?id=130658341226453206'

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
    page.goto(URL, wait_until='domcontentloaded', timeout=45000)
    page.wait_for_timeout(4000)
    page.screenshot(path=str(OUT_DIR/'dxm_edit_direct_probe.png'), full_page=True)
    body=page.locator('body').inner_text()[:12000]
    data=page.evaluate(r'''() => {
      const body=document.body.innerText||'';
      const keys=['店小秘信息','产品信息','保存','发布','半托管','托管','物流','运费模板','类目','分类','变种'];
      const matches=Array.from(document.querySelectorAll('*')).map(el=>{
        const txt=(el.innerText||el.textContent||'').replace(/\s+/g,' ').trim();
        if(!txt) return null;
        if(!keys.some(k=>txt.includes(k))) return null;
        const r=el.getBoundingClientRect();
        const st=getComputedStyle(el);
        if(st.display==='none'||st.visibility==='hidden'||parseFloat(st.opacity||'1')===0||r.width<5||r.height<5) return null;
        return {tag:el.tagName, txt:txt.slice(0,180), cls:String(el.className||''), rect:{x:r.x,y:r.y,w:r.width,h:r.height}};
      }).filter(Boolean).slice(0,150);
      return {
        flags:{has_dxm_info:body.includes('店小秘信息'),has_product_info:body.includes('产品信息'),has_save:body.includes('保存'),has_publish:body.includes('发布'),has_half_manage:body.includes('半托管'),has_consignment:body.includes('托管')},
        matches
      };
    }''')
    out={'url':page.url,'title':page.title(),'body':body,'data':data}
    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(out, ensure_ascii=False, indent=2))
    browser.close()
