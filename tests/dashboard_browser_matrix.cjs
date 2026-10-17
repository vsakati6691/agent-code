/* Complete public-dashboard interaction matrix; requires an already-built local site. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const names = ['index','growth','multibaggers','ai','desk','options','bets','watchlist','leaders',
  'goal','evidence','compare','history','methodology','audit'];

async function reveal(page, locator) {
  const panels = await locator.evaluate(e => {
    const result=[];
    for(let p=e.parentElement;p;p=p.parentElement) if(p.matches('[role=tabpanel]'))
      result.unshift({id:p.id,hz:p.dataset.hz,type:p.dataset.type,panel:p.dataset.panel});
    return result;
  });
  const parents=locator.locator('xpath=ancestor::details');
  for(const d of await parents.all()) if(!await d.evaluate(e=>e.open) && await d.locator(':scope > summary').isVisible()) await d.locator(':scope > summary').click();
  for(const p of panels) {
    if(p.panel) await page.locator(`[data-tab="${p.panel}"]`).click();
    if(p.hz) {
      await page.locator(`[data-dim="type"][data-val="${p.type}"]`).click();
      await page.locator(`[data-dim="hz"][data-val="${p.hz}"]`).click();
    }
  }
  for(const d of await parents.all()) if(!await d.evaluate(e=>e.open)) await d.locator(':scope > summary').click();
}

async function rowState(table) {
  return table.evaluate(t => {
    const items=t.hasAttribute('data-grouped') ? [...t.tBodies].filter(b=>b.classList.contains('item')) : [...t.tBodies[0].rows];
    return items.map(item=>({hidden:item.hidden,data:{...item.dataset},text:item.textContent,
      cells:[...(item.rows?item.rows[0]:item).cells].map(c=>c.dataset.v??c.textContent)}));
  });
}

async function resetFor(page, id) {
  const own=page.locator(`[data-reset="${id}"]`);
  if(await own.count()) return own;
  const count=page.locator(`[data-count="${id}"]`);
  return await count.count() ? count.locator('..').locator('.linkbtn', {hasText:'Reset view'}) : null;
}

async function tables(page) {
  const result={tables:0,searches:0,filterOptions:0,sorts:0,pins:0,resets:0};
  for(const table of await page.locator('table[data-table]').all()) {
    await reveal(page, table);
    const id=await table.getAttribute('id');
    const reset=await resetFor(page,id);
    if(reset && await reset.isVisible()) await reset.click();
    const original=await rowState(table);
    if(!original.length) continue;
    result.tables++;
    const search=page.locator(`[data-search="${id}"]`);
    if(await search.count()) {
      await reveal(page,search);
      await search.fill('no-such-ticker-zzzz');
      assert.equal((await rowState(table)).filter(r=>!r.hidden).length,0,`${id}: empty search`);
      await reset.click(); result.resets++;
      assert.equal((await rowState(table)).filter(r=>!r.hidden).length,original.length);
      result.searches++;
    }
    for(const filter of await page.locator(`[data-filter="${id}"], [data-sector="${id}"]`).all()) {
      await reveal(page,filter);
      const field=await filter.getAttribute('data-field') || 'sector';
      for(const value of await filter.locator('option').evaluateAll(es=>es.map(e=>e.value).filter(Boolean))) {
        await filter.selectOption(value);
        const shown=(await rowState(table)).filter(r=>!r.hidden);
        const expected=original.filter(r=>r.data[field]===value);
        assert.equal(shown.length,expected.length,`${id} filter ${field}=${value}`);
        assert.ok(shown.every(r=>r.data[field]===value));
        await reset.click(); result.resets++; result.filterOptions++;
        assert.equal(await filter.inputValue(),'');
        assert.equal((await rowState(table)).filter(r=>!r.hidden).length,original.length);
      }
    }
    for(const th of await table.locator('th[data-sort]').all()) {
      if(!await th.isVisible()) continue; // responsive hidden columns expose no control
      const index=await th.evaluate(e=>e.cellIndex), numeric=await th.getAttribute('data-sort')==='num';
      for(const dir of [1,-1]) {
        await th.locator('button').click();
        assert.equal(await th.getAttribute('aria-sort'),dir===1?'ascending':'descending');
        const raw=(await rowState(table)).map(r=>r.cells[index]);
        const values=numeric?raw.map(parseFloat).filter(Number.isFinite):raw;
        for(let i=1;i<values.length;i++) assert.ok(
          (numeric?values[i]-values[i-1]:String(values[i]).localeCompare(String(values[i-1])))*dir >= 0,
          `${id}: ${await th.innerText()} order`);
        if(numeric) {
          const missing=raw.findIndex(v=>!Number.isFinite(parseFloat(v)));
          if(missing>=0) assert.ok(raw.slice(missing).every(v=>!Number.isFinite(parseFloat(v))));
        }
        result.sorts++;
      }
      if(reset && await reset.isVisible()) {
        await reset.click(); result.resets++;
        assert.deepEqual((await rowState(table)).map(r=>r.text),original.map(r=>r.text));
      }
    }
  }
  for(const pin of await page.locator('[data-pin]').all()) {
    await reveal(page,pin);
    if(!await pin.isVisible()) continue;
    const before=await pin.getAttribute('aria-pressed');
    await pin.click(); assert.notEqual(await pin.getAttribute('aria-pressed'),before);
    await pin.click(); assert.equal(await pin.getAttribute('aria-pressed'),before);
    result.pins++;
  }
  for(const filter of await page.locator('[data-filter][data-field="pinned"]').all()) {
    const table=page.locator('#'+await filter.getAttribute('data-filter'));
    const pin=table.locator('[data-pin]').first();
    if(!await pin.count())continue;
    await reveal(page,pin);await pin.click();
    await reveal(page,filter);await filter.selectOption('yes');
    const shown=(await rowState(table)).filter(r=>!r.hidden);
    assert.ok(shown.length>0 && shown.every(r=>r.data.pinned==='yes'));
    await filter.selectOption('');await pin.click();
    assert.equal(await pin.getAttribute('aria-pressed'),'false');
    result.filterOptions++;
  }
  return result;
}

async function details(page) {
  let count=0;
  // Include disclosures inside hidden tab panels and nested disclosures.
  for(const detail of await page.locator('details').all()) {
    await reveal(page,detail);
    const summary=detail.locator(':scope > summary');
    if(!await summary.isVisible()) continue;
    const original=await detail.evaluate(e=>e.open);
    if(original) await summary.click();
    await summary.click(); assert.equal(await detail.evaluate(e=>e.open),true);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>document.documentElement.clientWidth),false,'Expanded disclosure overflows the page');
    await summary.click(); assert.equal(await detail.evaluate(e=>e.open),false);
    if(original) await summary.click();
    count++;
  }
  return count;
}

async function rowDetails(page) {
  let rows=0,disclosures=0;
  for(const toggle of await page.locator('.rowtoggle').all()) {
    await reveal(page,toggle);
    if(!await toggle.isVisible())continue;
    const row=page.locator('#'+await toggle.getAttribute('aria-controls'));
    await toggle.click();assert.equal(await toggle.getAttribute('aria-expanded'),'true');
    for(const lazy of await row.locator('.lazy').all()) {
      await lazy.locator('p,table,dl,div').first().waitFor();
      await page.waitForFunction(id=>document.getElementById(id)?.querySelector('.lazy')?.dataset.state==='loaded',await row.getAttribute('id'));
      assert.ok((await lazy.innerText()).trim().length>30);
    }
    for(const d of await row.locator('details').all()) {
      await reveal(page,d);const summary=d.locator(':scope > summary');
      if(!await summary.isVisible())continue;
      const old=await d.evaluate(e=>e.open);await summary.click();assert.equal(await d.evaluate(e=>e.open),!old);
      await summary.click();disclosures++;
    }
    await toggle.click();assert.equal(await row.isVisible(),false);rows++;
  }
  return {rows,disclosures};
}

async function plan(page) {
  const data=await page.locator('#goal-data').evaluate(e=>JSON.parse(e.textContent));
  const table=page.locator('#t-goal');
  assert.equal(await table.locator('th').count(),8);
  for(const label of ['Current price (date)','2030 Bear','2030 Base','2030 Bull','Base %/yr','Required %/yr'])
    assert.ok((await table.innerText()).includes(label));
  const end=new Date(data.start_date+'T00:00:00Z'); end.setUTCDate(end.getUTCDate()+1461);
  await page.locator('#goal-capital').fill('10000');
  await page.locator('#goal-target').fill('20000');
  await page.locator('#goal-date').fill(end.toISOString().slice(0,10));
  await page.locator('#goal-monthly').fill('100');
  assert.equal(await page.locator('#goal-required').innerText(),'9.28%/yr');
  assert.equal(await page.locator('#goal-no-contributions').innerText(),'18.92%/yr');
  const cash=data.assets.findIndex(a=>a.ticker==='Cash');
  await reveal(page,page.locator(`#goal-weight-${cash}`));
  await page.locator(`#goal-weight-${cash}`).fill('100');
  for(const k of ['bear','base','bull']) assert.equal(await page.locator(`#goal-ending-${k}`).innerText(),'$14,800');
  await page.reload(); await page.waitForLoadState('networkidle');
  assert.equal(await page.locator(`#goal-weight-${cash}`).inputValue(),'100');
  assert.equal(await page.locator('#goal-required').innerText(),'9.28%/yr');
  await page.locator('#goal-reset').click();
  assert.equal(await page.locator(`#goal-weight-${cash}`).inputValue(),'0');
  assert.equal(await page.locator('#goal-monthly').inputValue(),'0');
  return 'Fixed 4-year target/contribution regression; 100% Cash $14,800 in all cases; saved weights and reset';
}

async function extras(page,name) {
  const checks=[];
  if(name==='goal') checks.push(await plan(page));
  if(name==='leaders') {
    const rows=await rowState(page.locator('#t-leaders'));
    assert.equal(await page.locator('#t-leaders th').count(),11);
    assert.equal(await page.locator('#t-leaders th').filter({hasText:'Implied %/yr'}).count(),3);
    checks.push(`${rows.length} Leaders rows, 3 implied-growth columns`);
  }
  if(name==='compare' && await page.locator('#cmp-pick').count()) {
    const values=await page.locator('#cmp-pick option').evaluateAll(es=>es.map(e=>e.value).filter(Boolean));
    for(const v of values.slice(0,4)) {await page.locator('#cmp-pick').selectOption(v);await page.locator('#cmp-add').click();}
    assert.equal(await page.locator('#cmp-chips li').count(),Math.min(4,values.length));
    assert.ok(await page.locator('#cmp-table-wrap table').isVisible());
    for(const button of await page.locator('[data-win]').all()) {await button.click();assert.equal(await button.getAttribute('aria-pressed'),'true');}
    while(await page.locator('#cmp-chips button').count()) await page.locator('#cmp-chips button').first().click();
    assert.equal(await page.locator('#cmp-chips li').count(),0);
    checks.push('Add/remove 2–4 companies and all price windows');
  }
  if(await page.locator('#research-field').count()) {
    const field=page.locator('#research-field');await reveal(page,field);
    let ranges=false;
    for(const value of await field.locator('option').evaluateAll(es=>es.map(e=>e.value))) {
      await field.selectOption(value);
      assert.equal(await page.locator('[data-research-heading]').innerText(),await field.locator('option:checked').innerText());
      const cells=page.locator('[data-research-value]'), n=await cells.count();
      const ready=await cells.evaluateAll(es=>es.filter(e=>e.dataset.v!=='').length);
      await page.locator('#research-coverage').selectOption('available');
      assert.equal((await rowState(page.locator('#t-scan'))).filter(r=>!r.hidden).length,ready);
      await page.locator('#research-coverage').selectOption('missing');
      assert.equal((await rowState(page.locator('#t-scan'))).filter(r=>!r.hidden).length,n-ready);
      await page.locator('[data-reset="t-scan"]').click();
      if(!ranges && !await page.locator('#research-min').isDisabled() && ready) {
        await page.locator('#research-min').fill('1e100');
        assert.equal((await rowState(page.locator('#t-scan'))).filter(r=>!r.hidden).length,0);
        await page.locator('[data-reset="t-scan"]').click();
        await page.locator('#research-max').fill('-1e100');
        assert.equal((await rowState(page.locator('#t-scan'))).filter(r=>!r.hidden).length,0);
        await page.locator('[data-reset="t-scan"]').click();ranges=true;
      }
    }
    await page.locator('#research-text').fill('no field value zzzzz');
    assert.equal((await rowState(page.locator('#t-scan'))).filter(r=>!r.hidden).length,0);
    await page.locator('[data-reset="t-scan"]').click();
    checks.push('Every research field and available/missing coverage; text and reset');
  }
  if(await page.locator('#spec-pin-filter').count()) {
    const filter=page.locator('#spec-pin-filter');await reveal(page,filter);
    await filter.selectOption('pinned');
    assert.equal(await page.locator('.speculative-ticker:visible').count(),0);
    await filter.selectOption('all');
    const size=page.locator('#spec-size');await reveal(page,size);await size.fill('10000');
    await page.locator('#spec-cap').fill('10');await page.locator('#spec-trade').fill('2');
    assert.match(await page.locator('#spec-budget-summary').innerText(),/1,000/);
    assert.match(await page.locator('#spec-budget-summary').innerText(),/200/);
    checks.push('Speculative pin filter and both hypothetical budget limits');
  }
  if(name==='bets' && await page.locator('#bets-table').count()) {
    const budget=page.locator('#bet-budget');await reveal(page,budget);await budget.fill('0.01');
    assert.equal((await rowState(page.locator('#bets-table'))).filter(r=>!r.hidden).length,0);
    await budget.fill('1000');await page.locator('#bet-contract').selectOption('0');
    assert.match(await page.locator('#bet-sizing').innerText(),/whole contract/);
    await page.locator('#bet-save').click();assert.equal(await page.locator('#bet-slip li').count(),1);
    await page.locator('#bet-clear').click();assert.equal(await page.locator('#bet-slip li').count(),0);
    await budget.fill('');checks.push('Budget filter, sizing, local-only save/clear');
  }
  if(name==='company' && await page.locator('.lab input').count()) {
    const input=page.locator('.lab input').first(), old=await input.inputValue();
    await input.fill('0');assert.match(await page.locator('.lab-out').innerText(),/Your experiment/);
    await page.locator('.lab-reset').click();assert.equal(await input.inputValue(),old);
    checks.push('Company scenario experiment and reset');
  }
  return checks;
}

function layout() {
  const overflow=Math.max(0,document.documentElement.scrollWidth-document.documentElement.clientWidth);
  const overlaps=[], nodes=[], walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
  let node;
  while(node=walker.nextNode()) {
    const el=node.parentElement;
    if(!node.textContent.trim()||el.closest('script,style,noscript,.sr-only,svg,select')||getComputedStyle(el).visibility==='hidden') continue;
    if(el.closest('[hidden]') || [...document.querySelectorAll('details:not([open])')].some(d=>d.contains(el)&&!d.querySelector(':scope > summary')?.contains(el))) continue;
    const range=document.createRange();range.selectNodeContents(node);
    for(const raw of range.getClientRects()) {
      let r={left:Math.max(0,raw.left),right:Math.min(innerWidth,raw.right),top:Math.max(0,raw.top),bottom:Math.min(innerHeight,raw.bottom)};
      for(let p=el;p;p=p.parentElement) {
        const s=getComputedStyle(p), b=p.getBoundingClientRect();
        if(s.overflowX!=='visible') {r.left=Math.max(r.left,b.left);r.right=Math.min(r.right,b.right);}
        if(s.overflowY!=='visible') {r.top=Math.max(r.top,b.top);r.bottom=Math.min(r.bottom,b.bottom);}
      }
      if(r.right-r.left>2&&r.bottom-r.top>2) nodes.push({r,el,text:node.textContent.trim().slice(0,60)});
    }
  }
  for(let i=0;i<nodes.length;i++) for(let j=i+1;j<nodes.length;j++) {
    const a=nodes[i],b=nodes[j];if(a.el===b.el||a.text===b.text)continue;
    const w=Math.min(a.r.right,b.r.right)-Math.max(a.r.left,b.r.left),h=Math.min(a.r.bottom,b.r.bottom)-Math.max(a.r.top,b.r.top);
    if(w>2&&h>2) overlaps.push([a.text,b.text]);
  }
  const contrast=[];
  const rgb=s=>(s.match(/[\d.]+/g)||[]).map(Number);
  const lum=c=>c.slice(0,3).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;}).reduce((s,v,i)=>s+v*[.2126,.7152,.0722][i],0);
  for(const {el,text} of nodes) {
    if(contrast.some(c=>c.text===text))continue;
    const chain=[];for(let p=el;p;p=p.parentElement)chain.unshift(p);
    let bg=[255,255,255];
    for(const p of chain){const c=rgb(getComputedStyle(p).backgroundColor);if(c.length>=3){const a=c[3]??1;bg=bg.map((v,i)=>v*(1-a)+c[i]*a);}}
    const style=getComputedStyle(el),fg=rgb(style.color);if(fg.length<3)continue;
    const a=fg[3]??1,front=lum(fg.map((v,i)=>v*a+(bg[i]||0)*(1-a))),back=lum(bg);
    const ratio=(Math.max(front,back)+.05)/(Math.min(front,back)+.05);
    const large=parseFloat(style.fontSize)>=24 || (parseFloat(style.fontSize)>=18.66&&parseInt(style.fontWeight)>=700);
    if(ratio+.01<(large?3:4.5)) contrast.push({text,ratio,foreground:style.color,background:bg});
  }
  return {overflow,overlaps,contrast,numeric:getComputedStyle(document.body).fontVariantNumeric};
}

exports.checkMatrix=async function(browser,base,profile,out) {
  const results=[];
  for(const [width,height] of [[1440,900],[390,844]]) for(const theme of ['light','dark']) {
    const context=await browser.newContext({viewport:{width,height},colorScheme:theme,reducedMotion:'reduce'});
    await context.route('**/*',r=>r.request().url().startsWith(base+'/')?r.continue():r.abort());
    const page=await context.newPage();page.setDefaultTimeout(10000);
    let errors=[],failed=[];
    page.on('pageerror',e=>errors.push(e.message));
    page.on('console',m=>{if(m.type()==='error') errors.push(m.text());});
    page.on('requestfailed',r=>failed.push(r.url()));
    page.on('response',r=>{if(r.status()>=400)failed.push(r.url()+': '+r.status());});
    try {
      for(const name of [...names,'company'].filter(n=>!process.env.DASHBOARD_MATRIX_PAGES||process.env.DASHBOARD_MATRIX_PAGES.split(',').includes(n))) {
        errors=[];failed=[];
        const file=name==='company'?profile.firstAiHref:name+'.html';
        if(page.url().startsWith(base)) await page.evaluate(()=>localStorage.clear());
        await page.goto(`${base}/${file}`);await page.waitForLoadState('networkidle');
        const initial=await page.evaluate(layout);
        assert.equal(initial.overflow,0,`${name} ${width} ${theme} overflow`);
        assert.deepEqual(initial.overlaps,[],`${name} ${width} ${theme} text overlaps`);
        assert.deepEqual(initial.contrast,[],`${name} ${width} ${theme} AA contrast`);
        assert.ok(initial.numeric.includes('tabular-nums'));
        await page.screenshot({path:path.join(out,`${name}-${width}-${theme}.png`)});
        const nav=page.locator('nav[aria-label="Research sections"]');
        assert.equal(await nav.locator('a').count(),15);
        assert.equal(await nav.locator('[aria-current=page]').count(),1);
        assert.equal(await nav.locator('[aria-current=page]').getAttribute('href'),name==='company'?'../ai.html':name+'.html');
        assert.ok((await nav.locator('[aria-current=page]').evaluate(e=>getComputedStyle(e).textDecorationLine)).includes('underline'));
        const links=await nav.locator('a').evaluateAll(es=>es.map(e=>e.href));
        for(const url of links) {const response=await context.request.get(url);assert.equal(response.status(),200);}
        const next=names[(names.indexOf(name)+1)%names.length]+'.html';
        await nav.locator(`a[href$="${next}"]`).click();await page.waitForURL(`**/${next}`);
        assert.equal(await page.locator('nav[aria-label="Research sections"] [aria-current=page]').getAttribute('href'),next);
        await page.goto(`${base}/${file}`);await page.waitForLoadState('networkidle');
        const csv=[...new Set(await page.locator('a[href*=".csv"]').evaluateAll(es=>es.map(e=>e.href)))];
        for(const url of csv) {const response=await context.request.get(url);assert.equal(response.status(),200);assert.ok((await response.body()).length>0);}
        const toggles=await details(page);
        const controls=await tables(page);
        const evidence=await rowDetails(page);
        const extra=await extras(page,name);
        if(name==='leaders'&&profile.minimumLeaders) assert.ok(await page.locator('#t-leaders tbody tr').count()>=profile.minimumLeaders);
        await page.locator('.command-trigger').click();await page.locator('#command-query').fill(profile.ticker);
        await page.keyboard.press('Enter');await page.waitForURL(`**/symbol/${profile.ticker}.html`);
        await page.waitForLoadState('networkidle');assert.ok((await page.locator('main').innerText()).includes(profile.ticker));
        assert.deepEqual(errors,[],`${name} console`);assert.deepEqual(failed,[],`${name} requests`);
        results.push({name,file,width,height,theme,...initial,navLinks:links.length,csv:csv.length,details:toggles,
          ...controls,evidence,extra,consoleErrors:errors,failedRequests:failed,brokenLinks:0});
        fs.writeFileSync(path.join(out,'matrix-results.json'),JSON.stringify(results,null,2));
        console.log(`Matrix ${width} ${theme}: ${name}`);
      }
    } finally {await context.close();}
  }
  return results;
};

exports.checkNoJs=async function(browser,base,profile,out) {
  const result=[];
  for(const [width,height] of [[1440,900],[390,844]]) for(const theme of ['light','dark']) {
    const context=await browser.newContext({javaScriptEnabled:false,viewport:{width,height},colorScheme:theme});
    const page=await context.newPage();
    try {
      for(const name of [...names,'company']) {
        const file=name==='company'?profile.firstAiHref:name+'.html';
        await page.goto(`${base}/${file}`);
        assert.equal(await page.locator('main h1').count(),1);
        assert.equal(await page.locator('.command-trigger').isVisible(),false);
        assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>document.documentElement.clientWidth),false);
        const browse=page.locator('header details').filter({hasText:'Browse tickers'});
        await browse.locator('summary').click();
        const link=browse.locator('a').filter({hasText:new RegExp('^'+profile.ticker+'$')});
        assert.equal(await link.count(),1);
        if(name==='options') assert.ok(await page.locator('section[role=tabpanel]').first().isVisible());
        if(name==='goal') assert.match(await page.locator('#t-goal').innerText(),/\$[\d,]/);
        if(name==='leaders'&&profile.minimumLeaders) assert.ok(await page.locator('#t-leaders tbody tr').count()>=profile.minimumLeaders);
        if(name==='bets'&&await page.locator('#bets-table').count()) assert.ok(await page.locator('#bets-table tbody tr').count()>0);
        await link.click();assert.ok((await page.locator('main').innerText()).includes(profile.ticker));
        result.push({name,width,height,theme,readable:true,tickerLink:true});
      }
    } finally {await context.close();}
  }
  fs.writeFileSync(path.join(out,'nojs-results.json'),JSON.stringify(result,null,2));
  return result;
};
