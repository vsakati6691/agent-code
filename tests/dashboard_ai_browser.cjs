/* Browser checks against the offline fixture or the original October 15 snapshot. */
const assert = require('node:assert/strict');

exports.checkAiPage = async function (page, base, profile = {unavailableTicker:'ARM', unavailableReason:'not common stock', firstAiHref:'stock/ai_large-MU.html'}) {
  await page.emulateMedia({media:'screen'});
  await page.setViewportSize({width:390, height:1000});
  await page.goto(`${base}/ai.html`);
  const firstTableTop = await page.locator('#t-ai_large').evaluate(e=>e.getBoundingClientRect().top);
  const guide = page.locator('.ai-guide details');
  assert.equal(await guide.getAttribute('open'), null);
  await guide.locator('summary').click();
  assert.match(await guide.innerText(), /momentum 10%/);
  await guide.locator('summary').click();
  for (const target of ['ai_large','ai_mid','top20','universe','private']) {
    await page.locator(`.section-nav a[href="#${target}"]`).click();
    assert.equal(new URL(page.url()).hash, '#' + target);
    assert.equal(await page.locator('#' + target).isVisible(), true);
  }
  const unavailable = page.locator('.ai-unavailable').filter({hasText:profile.unavailableTicker});
  await unavailable.locator('summary').focus();
  await page.keyboard.press('Enter');
  assert.ok((await unavailable.locator('p').innerText()).includes(profile.unavailableReason));
  assert.equal(await unavailable.locator('p').isVisible(), true);
  assert.equal(await page.locator('.ai-page a.pill').first().getAttribute('href'), profile.firstAiHref);
  const privateTable = page.locator('table[aria-label="Private AI companies with a reported valuation"]');
  assert.equal(await privateTable.locator('th').last().isVisible(), true);
  await page.setViewportSize({width:1440,height:1000});
  const table = page.locator('#t-ai-scenarios');
  const tickers = () => table.locator('tbody tr td:first-child strong').allTextContents();
  const original = await tickers();
  const header = table.locator('th').nth(2);
  await header.locator('button').click();
  const values = await table.locator('tbody tr td:nth-child(3)').evaluateAll(es=>es.map(e=>Number(e.dataset.v)));
  assert.deepEqual(values, [...values].sort((a,b)=>a-b));
  await header.locator('button').click();
  await page.reload();
  assert.equal(await header.getAttribute('aria-sort'), 'descending');
  await page.locator('[data-reset="t-ai-scenarios"]').click();
  assert.deepEqual(await tickers(), original);
  const search = page.locator('[data-search="t-ai_large"]');
  await search.fill('no such company');
  assert.equal(await page.locator('[data-empty="t-ai_large"]').isVisible(), true);
  await search.locator('..').getByText('Reset view', {exact:true}).click();
  assert.equal(await page.locator('[data-empty="t-ai_large"]').isVisible(), false);
  assert.equal(await page.locator('#t-ai_large tbody.item:visible').count(), 5);
  const nojs = await page.context().browser().newContext({javaScriptEnabled:false, viewport:{width:390,height:1000}});
  try {
    const fallback = await nojs.newPage();
    await fallback.goto(`${base}/ai.html`);
    await fallback.locator('.section-nav a[href="#universe"]').click();
    assert.equal(new URL(fallback.url()).hash, '#universe');
    const reason = fallback.locator('.ai-unavailable').filter({hasText:profile.unavailableTicker});
    await reason.locator('summary').click();
    assert.equal(await reason.locator('p').isVisible(), true);
  } finally {await nojs.close();}
  return {firstTableTop, jumpLinks:5, unavailableReason:'keyboard/touch disclosure',
    scenarioSorting:'numeric, persisted and reset', searchEmptyState:'passed', mobilePrivateColumns:'visible'};
};

// Also runnable on its own with the same <site-directory> <report-directory> arguments.
if(require.main===module) {
  process.env.DASHBOARD_AI_ONLY='1';
  require('./dashboard_ui_browser.cjs');
}
