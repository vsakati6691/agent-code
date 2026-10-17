/* Reproduce Task 0/3/4 visible-word and first-screen metrics from a local site.
 * node tests/dashboard_ux_capture.cjs <site> <output> [company-page-relative-path]
 * Screenshots cover both sizes; metrics cover both sizes and both themes.
 */
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(process.argv[2]);
const out = path.resolve(process.argv[3]);
fs.mkdirSync(out, {recursive:true});
const names=['index','growth','multibaggers','ai','options','bets','watchlist','leaders','goal','evidence','compare','history','methodology','audit'];
const company=process.argv[4] || 'stock/ai_large-AIL1.html';
const pages=[...names.map(name=>({name,file:name+'.html'})),{name:'company',file:company}].filter(p=>!process.env.CAPTURE_NAMES||process.env.CAPTURE_NAMES.split(',').includes(p.name));
const server=http.createServer((req,res)=>{
  let file;
  try {file=path.resolve(root,'.'+decodeURIComponent(req.url.split('?')[0]));}catch {res.writeHead(400).end();return;}
  if(!file.startsWith(root+path.sep)||!fs.existsSync(file)||!fs.statSync(file).isFile()){res.writeHead(404).end();return;}
  res.setHeader('Content-Type',({'.html':'text/html','.css':'text/css','.js':'application/javascript','.json':'application/json','.svg':'image/svg+xml'})[path.extname(file)]||'application/octet-stream');
  res.end(fs.readFileSync(file));
});
(async()=>{
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const base=`http://127.0.0.1:${server.address().port}`;
  const browser=await chromium.launch({headless:true,...(process.env.DASHBOARD_BROWSER?{executablePath:process.env.DASHBOARD_BROWSER}:{})});
  const results=[];
  try {
    for(const [device,width,height] of [['desktop',1440,900],['mobile',390,844]]){
      for(const theme of ['light','dark']){
        const ctx=await browser.newContext({viewport:{width,height},colorScheme:theme,reducedMotion:'reduce'});
        await ctx.route('**/*',r=>r.request().url().startsWith(base+'/')?r.continue():r.abort());
        const page=await ctx.newPage();
        let errors=[],failed=[];
        page.on('pageerror',e=>errors.push(e.message));
        page.on('requestfailed',r=>failed.push(r.url().replace(base,'')));
        page.on('response',r=>{if(r.status()>=400)failed.push(r.url().replace(base,'')+': '+r.status());});
        for(const item of pages){
          errors=[];failed=[];
          await page.goto(`${base}/${item.file}`);
          await page.waitForLoadState('networkidle');
          const metrics=await page.evaluate(()=>{
            const main=document.querySelector('main');
            const rects=node=>{const range=document.createRange();range.selectNodeContents(node);return [...range.getClientRects()].filter(r=>r.width&&r.height);};
            const visible=e=>{
              if(e.closest('[hidden]')||getComputedStyle(e).visibility==='hidden'||!rects(e).length)return false;
              for(let p=e;p;p=p.parentElement)if(p.tagName==='DETAILS'&&!p.open&&!p.querySelector(':scope > summary')?.contains(e))return false;
              return true;
            };
            const blocks=[...main.querySelectorAll('table,.grid:has(>.card),.scan-stats,.market-grid,.mb-list,.ow-grid,.contract-grid,.volatility-grid,#required-rate')].filter(visible);
            const first=blocks[0];
            const top=first?.getBoundingClientRect().top ?? null;
            const walker=document.createTreeWalker(main,NodeFilter.SHOW_TEXT);
            let words=0,points=0,node;
            while(node=walker.nextNode()){
              const el=node.parentElement,text=node.textContent.trim();
              if(!text||el.closest('script,style,noscript,footer')||!visible(el))continue;
              const boxes=rects(node);if(!boxes.length)continue;
              if(top!==null&&boxes.every(r=>r.bottom<=top+1))words+=text.split(/\s+/).length;
              const data=el.closest('td,.card.stat .value,.scan-stat strong,.market-grid strong,.mb-list strong,.ow-grid strong,.contract-grid strong,.volatility-grid strong,#required-rate strong');
              if(data&&/\d/.test(text)&&boxes.some(r=>r.top>=0&&r.bottom<=innerHeight&&r.left<innerWidth&&r.right>0))points++;
            }
            return {wordsAboveData:top===null?null:words,dataPointsFirstScreen:points,firstDataTop:top,firstData:first?(first.id||first.className||first.tagName):null,overflow:Math.max(0,document.documentElement.scrollWidth-document.documentElement.clientWidth)};
          });
          results.push({...item,device,theme,width,height,bytes:fs.statSync(path.join(root,item.file)).size,...metrics,errors:[...errors],failedRequests:[...failed]});
          if(theme==='light')await page.screenshot({path:path.join(out,`${item.name}-${device}.png`)});
        }
        await ctx.close();
        console.log(`Captured ${device} ${theme}`);
      }
    }
    fs.writeFileSync(path.join(out,'metrics.json'),JSON.stringify(results,null,2));
  } finally {await browser.close();server.close();}
})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
