/* Optional browser regression pass over an already-built, offline dashboard.
 * Usage: node tests/dashboard_ui_browser.cjs <site-directory> <report-directory>
 * Requires Playwright in the development environment; no production dependency.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(process.argv[2]);
const out = path.resolve(process.argv[3] || 'reports/dashboard-ui');
fs.mkdirSync(out, {recursive: true});
const pages = ['index', 'growth', 'multibaggers', 'ai', 'options', 'bets', 'watchlist', 'leaders',
  'goal', 'evidence', 'compare', 'history', 'methodology', 'audit'];
const server = http.createServer((req, res) => {
  let file;
  try { file = path.resolve(root, '.' + decodeURIComponent(req.url.split('?')[0])); }
  catch { res.writeHead(400).end(); return; }
  if (!file.startsWith(root + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
    res.writeHead(404).end(); return;
  }
  const types = {'.html': 'text/html', '.css': 'text/css', '.js': 'application/javascript',
    '.json': 'application/json', '.svg': 'image/svg+xml'};
  res.setHeader('Content-Type', types[path.extname(file)] || 'application/octet-stream');
  res.end(fs.readFileSync(file));
});

(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  const browser = await chromium.launch({headless: true,
    ...(process.env.DASHBOARD_BROWSER ? {executablePath: process.env.DASHBOARD_BROWSER} : {})});
  const checks = [], errors = [];
  try {
    const context = await browser.newContext();
    await context.route('**/*', route => route.request().url().startsWith(base + '/') ? route.continue() : route.abort());
    await context.addInitScript(() => {
      window.__layoutShift = 0;
      window.__shiftSources = [];
      new PerformanceObserver(list => {
        for (const entry of list.getEntries()) if (!entry.hadRecentInput) {
          window.__layoutShift += entry.value;
          window.__shiftSources.push({value: entry.value, sources: entry.sources.map(s => s.node?.outerHTML?.slice(0, 180))});
        }
      }).observe({type: 'layout-shift', buffered: true});
    });
    const page = await context.newPage();
    page.on('pageerror', error => errors.push(error.message));
    for (const width of [390, 768, 1440]) {
      for (const theme of ['light', 'dark']) {
        await page.setViewportSize({width, height: 1000});
        await page.emulateMedia({colorScheme: theme, reducedMotion: 'reduce'});
        for (const name of pages) {
          await page.goto(`${base}/${name}.html`);
          await page.waitForLoadState('networkidle');
          const dimensions = await page.evaluate(() => ({
            overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
            cls: window.__layoutShift,
            shifts: window.__shiftSources,
            numeric: getComputedStyle(document.body).fontVariantNumeric
          }));
          checks.push({name, width, theme, ...dimensions});
          assert.ok(dimensions.overflow <= 1, `${name} ${width} ${theme}: page overflow ${dimensions.overflow}px`);
          assert.ok(dimensions.numeric.includes('tabular-nums'));
          if ((name === 'index' && width === 1440) || (name === 'watchlist' && width === 390) ||
              (name === 'ai' && [390, 1440].includes(width))) {
            await page.screenshot({path: path.join(out, `${name}-${width}-${theme}.png`)});
          }
        }
        console.log(`Checked ${width}px ${theme}`);
      }
    }
    fs.writeFileSync(path.join(out, 'layout-results.json'), JSON.stringify(checks, null, 2));
    await page.setViewportSize({width: 1440, height: 1000});
    await page.goto(`${base}/growth.html`);
    await page.locator('.command-trigger').click();
    const query = page.locator('#command-query');
    await page.keyboard.press('ArrowDown');
    assert.equal(await query.getAttribute('aria-activedescendant'), 'command-option-1');
    await page.keyboard.press('ArrowUp');
    assert.equal(await query.getAttribute('aria-activedescendant'), 'command-option-0');
    await page.keyboard.press('Tab');
    assert.equal(await page.locator('#ticker-command').evaluate(e => e.contains(document.activeElement)), true);
    await query.focus();
    await query.fill('nvidia');
    assert.equal(await page.locator('#command-results li').count(), 1);
    assert.match(await page.locator('#command-results').innerText(), /NVDA/);
    await page.screenshot({path: path.join(out, 'command-palette.png')});
    await page.keyboard.press('Escape');
    await page.waitForFunction(() => document.activeElement === document.querySelector('.command-trigger'));
    await page.keyboard.press('Control+k');
    await query.fill('no matching ticker <script>');
    assert.match(await page.locator('#command-hint').innerText(), /No matching ticker/);
    await page.keyboard.press('Enter');
    assert.equal(page.url(), `${base}/growth.html`);
    await query.fill('NVDA');
    await page.keyboard.press('Enter');
    await page.waitForURL('**/symbol/NVDA.html');
    await page.keyboard.press('Meta+k');
    assert.equal(await page.locator('#ticker-command').isVisible(), true);
    await query.fill('NVDA');
    await page.keyboard.press('Enter');
    await page.waitForLoadState('networkidle');
    assert.equal(page.url(), `${base}/symbol/NVDA.html`); // nested-page base is preserved

    await page.goto(`${base}/growth.html`);
    const table = page.locator('#t-scan'), wrap = table.locator('..');
    await wrap.scrollIntoViewIfNeeded();
    await wrap.evaluate(e => {e.scrollTop = 220; e.scrollLeft = 240;});
    const sticky = await table.evaluate(t => {
      const box = t.parentElement.getBoundingClientRect();
      const header = t.querySelector('th').getBoundingClientRect();
      const ticker = t.querySelector('tbody td.tk').getBoundingClientRect();
      return {headerOffset: header.top - box.top, tickerOffset: ticker.left - box.left};
    });
    assert.ok(Math.abs(sticky.headerOffset) <= 2, JSON.stringify(sticky));
    assert.ok(Math.abs(sticky.tickerOffset) <= 2, JSON.stringify(sticky));
    const numericHeader = table.locator('th[data-sort="num"]').first();
    await numericHeader.locator('button').click();
    assert.equal(await numericHeader.getAttribute('aria-sort'), 'ascending');
    await numericHeader.locator('button').click();
    assert.equal(await numericHeader.getAttribute('aria-sort'), 'descending');

    await page.route('**/fragments/*.json', route => route.fulfill({status: 503, body: 'Temporarily unavailable'}));
    await page.locator('#growth-details > summary').click();
    const toggle = page.locator('#t-large .rowtoggle').first();
    await toggle.click();
    const evidence = page.locator('#t-large tr.detail:not([hidden]) .lazy');
    await evidence.locator('button', {hasText: 'Retry loading evidence'}).waitFor();
    const before = await evidence.boundingBox();
    assert.ok(await evidence.locator('a', {hasText: 'Open the full research page'}).getAttribute('href'));
    await page.unroute('**/fragments/*.json');
    await page.route('**/fragments/*.json', route => route.fulfill({contentType: 'application/json', body: '{}'}));
    await evidence.locator('button').click();
    await evidence.locator('button', {hasText: 'Retry loading evidence'}).waitFor();
    assert.equal((await evidence.innerText()).includes('undefined'), false);
    await page.unroute('**/fragments/*.json');
    await evidence.locator('button').click();
    await page.waitForFunction(() => document.querySelector('#t-large tr.detail:not([hidden]) .lazy')?.dataset.state === 'loaded');
    const after = await evidence.boundingBox();
    assert.ok(Math.abs(before.height - after.height) <= 1, 'Evidence loading changes its reserved height');
    await page.setViewportSize({width: 390, height: 850});
    assert.equal(await table.locator('thead').evaluate(e => getComputedStyle(e).display), 'table-header-group');
    await page.setViewportSize({width: 1440, height: 1000});

    await page.goto(`${base}/compare.html#%ZZ`);
    await page.waitForLoadState('networkidle');
    await page.goto(`${base}/options.html#%ZZ`);
    await page.locator('.themebtn').click();
    const chosen = await page.locator('html').getAttribute('data-theme');
    await page.reload();
    assert.equal(await page.locator('html').getAttribute('data-theme'), chosen);
    await page.goto(`${base}/index.html`);
    assert.equal(await page.locator('.daily-status.warn').count(), 1);
    assert.equal(await page.locator('.refresh-missing').getAttribute('open'), null);
    await page.locator('.refresh-missing summary').click();
    assert.match(await page.locator('.refresh-missing').innerText(), /COCO.*stale chain/);
    assert.equal(await page.locator('.data-notice', {hasText: 'Macro inputs unavailable'}).count(), 1);
    await page.emulateMedia({reducedMotion: 'reduce'});
    await page.keyboard.press('Control+k');
    assert.equal(await page.locator('#ticker-command').evaluate(e => getComputedStyle(e).animationName), 'none');
    await page.keyboard.press('Escape');
    await page.goto(`${base}/growth.html`);
    await page.emulateMedia({media: 'print'});
    assert.equal(await page.locator('.table-wrap th').first().evaluate(e => getComputedStyle(e).position), 'static');

    const nojs = await browser.newContext({javaScriptEnabled: false, viewport: {width: 390, height: 850}});
    const fallback = await nojs.newPage();
    await fallback.goto(`${base}/growth.html`);
    assert.equal(await fallback.locator('#symq').isVisible(), true);
    assert.equal(await fallback.locator('.command-trigger').isVisible(), false);
    assert.equal(await fallback.locator('#ticker-command').isVisible(), false);
    assert.equal(await fallback.locator('#t-scan').locator('..').getAttribute('tabindex'), '0');
    await nojs.close();
    const ai = await require('./dashboard_ai_browser.cjs').checkAiPage(page, base);
    assert.deepEqual(errors, []);
    const result = {checks, errors, sticky, ai, maxLayoutShift: Math.max(...checks.map(c => c.cls)),
      interactions: 'palette, nested navigation, empty search, Escape/focus, sticky axes, sorting, 503 retry, partial data, theme, reduced motion, print, no JavaScript'};
    fs.writeFileSync(path.join(out, 'browser-results.json'), JSON.stringify(result, null, 2));
    console.log(JSON.stringify({pagesChecked: checks.length, maxLayoutShift: result.maxLayoutShift, errors, sticky}));
  } finally {
    await browser.close();
    server.close();
  }
})().catch(error => {console.error(error); server.close(); process.exitCode = 1;});
