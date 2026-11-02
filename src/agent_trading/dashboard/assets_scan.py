"""Presentation and device-local pins for the daily research scan."""

CSS = r"""
/* A restrained desk layout: clear hierarchy, legible figures, no remote assets. */
header.site .inner, main { max-width: 1400px; padding-left: 28px; padding-right: 28px; }
header.site .inner { gap: 14px 20px; padding-top: 18px; padding-bottom: 14px; }
header.site .brand { display: inline-flex; align-items: center; gap: 10px; letter-spacing: -.4px; }
header.site .brand::before { content: "T / S"; background: var(--text-primary); color: var(--surface-1);
  padding: 7px; border-radius: 5px; font: 700 11px/1.2 ui-monospace, monospace; letter-spacing: -1px; }
header.site nav { order: 3; flex-basis: 100%; font-size: 13px; }
nav a { display: inline-block; padding: 4px 0; color: var(--text-secondary); }
nav a[aria-current="page"] { color: var(--link); text-underline-offset: 8px; text-decoration-thickness: 2px; }
main { padding-top: 16px; }
#freshness { font-size: 12px; border: 1px solid var(--border); background: var(--surface-1); padding: 9px 12px; }
#freshness strong { display: inline; font-weight: 600; margin-right: 4px; }
#freshness { display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 12px; }
#freshness details { margin: 0; }
#freshness details[open] { flex-basis: 100%; order: 3; }
.empty-data { margin: 12px 0; font-size: 13px; }
.filter-details { margin: 8px 0; }
.filter-details > summary { font-size: 13px; font-weight: 600; }
.compact-heading { margin: 18px 0 12px; }
.compact-heading h1 { margin: 0 0 6px; }
.compact-heading p { margin: 0; }
@media (max-width: 600px) {
  .scan-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .controls { gap: 8px; }
}
.eyebrow { font-size: 11px; font-weight: 700; letter-spacing: 1.6px; color: var(--text-secondary); margin: 0 0 12px; }
.scan-hero { display: flex; justify-content: space-between; gap: 32px; align-items: center; padding: 28px 0 30px; }
.scan-hero h1 { font-size: clamp(28px, 3.2vw, 44px); line-height: 1.16; letter-spacing: -1.6px; margin: 0 0 16px; }
.scan-hero h1 span { color: var(--text-secondary); font-weight: 450; }
.scan-hero .lede { max-width: 610px; font-size: 14px; }
.hero-actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 22px; }
.action { display: inline-flex; align-items: center; justify-content: center; padding: 9px 13px; font: 600 12px/1.4 system-ui, sans-serif;
  border: 1px solid var(--border); border-radius: 6px; background: var(--surface-1); color: var(--text-primary); cursor: pointer; text-decoration: none; }
.action.primary { background: var(--text-primary); color: var(--surface-1); border-color: var(--text-primary); }
.action:hover { border-color: var(--link); }
.snapshot-note { display: flex; flex-direction: column; align-items: flex-start; gap: 7px; flex: 0 0 270px;
  padding: 20px 0 20px 24px; border-left: 2px solid var(--border); font-size: 12px; color: var(--text-secondary); }
.snapshot-note .eyebrow { margin: 0; } .snapshot-note strong { font: 600 25px/1.4 ui-monospace, monospace; color: var(--text-primary); }
.snapshot-note a { margin-top: 8px; }
.scan-stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); background: var(--surface-1);
  border: 1px solid var(--border); border-radius: 8px; margin: 0 0 28px; }
.scan-stat { display: flex; flex-direction: column; gap: 4px; padding: 18px 22px; }
.scan-stat + .scan-stat { border-left: 1px solid var(--border); }
.scan-stat > span { font-size: 12px; color: var(--text-secondary); }
.scan-stat strong { font-size: 28px; line-height: 1.3; letter-spacing: -.8px; font-variant-numeric: tabular-nums; }
.scan-stat small { color: var(--text-muted); font-size: 11px; }
.section-heading { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; margin: 26px 0 12px; }
.section-heading h2 { margin: 0; font-size: 20px; letter-spacing: -.5px; }
.section-heading .eyebrow { margin-bottom: 6px; font-size: 10px; }
.market-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.market-tile { background: var(--surface-1); border: 1px solid var(--border); border-radius: 8px; padding: 16px 20px; }
.market-label, .market-foot { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
.market-label { font-size: 13px; } .market-label span { color: var(--text-muted); font-size: 12px; }
.market-value { font-size: 27px; font-weight: 550; letter-spacing: -.7px; margin: 8px 0; font-variant-numeric: tabular-nums; }
.market-foot { flex-wrap: wrap; font-size: 11px; color: var(--text-muted); }
.research-paths { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; margin: 24px 0; }
.research-path { display: flex; flex-direction: column; gap: 9px; padding: 22px; border: 1px solid var(--border);
  border-radius: 8px; background: var(--surface-1); color: var(--text-secondary); text-decoration: none; font-size: 13px; }
.research-path:hover { border-color: var(--link); text-decoration: none; }
.research-path .eyebrow { margin: 0; font-size: 10px; }
.research-path strong { display: flex; justify-content: space-between; font-size: 21px; color: var(--text-primary); }
.research-path strong span { color: var(--link); } .research-path small { color: var(--text-muted); }
#research-briefing { scroll-margin-top: 20px; }
.positive { color: var(--good); } .negative { color: var(--bad-border); }
#candidate-scan { scroll-margin-top: 20px; margin-top: 36px; }
.scan-toolbar { background: var(--surface-1); padding: 14px; border: 1px solid var(--border); border-radius: 8px; align-items: end; gap: 10px; }
.scan-toolbar label { display: flex; flex-direction: column; gap: 5px; font-size: 11px; font-weight: 600; color: var(--text-secondary); min-width: 0; }
.scan-toolbar input, .scan-toolbar select { font-size: 12px; height: 36px; max-width: 100%; }
.scan-search { flex: 1 1 220px; } .scan-toolbar .action { height: 36px; }
.scan-meta { display: flex; justify-content: space-between; flex-wrap: wrap; gap: 8px; margin: 12px 0; }
.scan-meta .small { font-size: 11px; }
#t-scan { font-size: 13px; } #t-scan th { padding: 12px 10px; font-size: 11px; color: var(--text-secondary); }
#t-scan td { padding: 13px 10px; } #t-scan tr:hover td { background: var(--surface-2); }
#t-scan td.tk { min-width: 190px; max-width: 230px; }
.scan-company { display: block; font-size: 11px; color: var(--text-muted); margin-top: 4px; white-space: normal; }
.scan-risk { min-width: 240px; max-width: 320px; }
.pinbtn { background: none; border: 0; padding: 3px 7px 3px 0; font-size: 20px; line-height: 1; color: var(--text-muted); cursor: pointer; }
.pinbtn[aria-pressed="true"] { color: var(--link); }
.scan-empty { padding: 22px; text-align: center; background: var(--surface-1); border: 1px dashed var(--border); border-radius: 8px; }
.context-details { border: 1px solid var(--border); border-radius: 8px; padding: 16px; background: var(--surface-1); margin: 18px 0; }
.context-details > summary { font-size: 14px; font-weight: 600; color: var(--text-primary); }
.watch-heading { margin: 28px 0 22px; } .watch-heading h1 { font-size: 30px; letter-spacing: -1px; }
.watch-heading .lede { font-size: 14px; margin-bottom: 0; }
button:focus-visible, a:focus-visible, input:focus-visible, select:focus-visible, summary:focus-visible { outline: 2px solid var(--link); outline-offset: 3px; }
[hidden] { display: none !important; }
@media (max-width: 900px) {
  .scan-hero { gap: 18px; } .snapshot-note { flex-basis: 215px; }
  .scan-stat { padding: 16px 14px; } .market-tile { padding: 14px; }
}
@media (max-width: 700px) {
  header.site .inner, main { padding-left: 16px; padding-right: 16px; }
  header.site .inner { display: flex; flex-direction: row; gap: 12px; }
  header.site .inner .symsearch { margin-left: auto; flex: 1 1 120px; }
  .themebtn { font-size: 11px; } header.site nav { order: 4; }
  .scan-hero { display: block; padding: 22px 0; } .scan-hero h1 { letter-spacing: -1px; }
  .snapshot-note { padding: 12px 0 0; margin-top: 20px; border-left: 0; border-top: 1px solid var(--border); gap: 3px; }
  .snapshot-note strong { font-size: 18px; } .snapshot-note .eyebrow { font-size: 9px; }
  .scan-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); margin-bottom: 20px; }
  .scan-stat:nth-child(3) { border-left: 0; } .scan-stat:nth-child(n+3) { border-top: 1px solid var(--border); }
  .scan-stat strong { font-size: 24px; }
  .market-grid { grid-template-columns: 1fr; gap: 8px; }
  .research-paths { grid-template-columns: 1fr; gap: 10px; } .research-path { padding: 18px; }
  .market-tile { display: grid; grid-template-columns: 1fr auto; gap: 4px 12px; }
  .market-label { justify-content: flex-start; flex-wrap: wrap; } .market-value { font-size: 22px; margin: 0; }
  .market-foot { grid-column: 1 / -1; }
  .scan-toolbar label { flex: 1 1 130px; } .scan-toolbar .scan-search { flex-basis: 100%; }
  .scan-toolbar input, .scan-toolbar select { font-size: 16px; } .scan-toolbar .action { width: 100%; }
  #t-scan td.tk { min-width: 140px; max-width: 170px; } .scan-risk { min-width: 200px; }
  .section-heading h2 { font-size: 18px; } .watch-heading h1 { font-size: 24px; }
}
@media print {
  .hero-actions, .pinbtn, .scan-toolbar, .scan-meta, .snapshot-note a { display: none !important; }
  .scan-hero { padding: 12px 0; } .scan-hero h1 { font-size: 25px; }
  .context-details { border: 0; padding: 0; } .market-grid { grid-template-columns: repeat(3, 1fr); }
}
"""

JS = r"""
(function () {
  var key = 'research-pins-v1', pins = new Set(), persistent = true;
  try {
    var stored = JSON.parse(localStorage.getItem(key) || '[]');
    if (Array.isArray(stored)) stored.slice(0, 1000).forEach(function (s) {
      if (typeof s === 'string' && /^[A-Z0-9.\-]{1,20}$/.test(s)) pins.add(s);
    });
  } catch (e) { persistent = false; }
  function render() {
    document.querySelectorAll('[data-pin]').forEach(function (b) {
      var active = pins.has(b.dataset.pin);
      b.textContent = active ? '★' : '☆';
      b.setAttribute('aria-pressed', active ? 'true' : 'false');
      b.setAttribute('aria-label', (active ? 'Unpin ' : 'Pin ') + b.dataset.pin);
    });
    document.querySelectorAll('[data-ticker]').forEach(function (r) { r.dataset.pinned = pins.has(r.dataset.ticker) ? 'yes' : 'no'; });
    if (!persistent) document.querySelectorAll('[data-pin-status]').forEach(function (n) {
      n.textContent = 'Device storage is unavailable. Pins last for this page only.';
    });
    document.dispatchEvent(new Event('pinschange'));
  }
  document.querySelectorAll('[data-pin]').forEach(function (b) {
    b.addEventListener('click', function () {
      var ticker = b.dataset.pin;
      if (pins.has(ticker)) pins.delete(ticker); else pins.add(ticker);
      try { localStorage.setItem(key, JSON.stringify(Array.from(pins))); } catch (e) { persistent = false; }
      render();
    });
  });
  document.addEventListener('keydown', function (e) {
    var target = e.target;
    if (e.key !== '/' || e.ctrlKey || e.metaKey || e.altKey || target.isContentEditable ||
        /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;
    var search = document.querySelector('[data-search="t-scan"], [data-search="t-watch"]');
    if (search) { e.preventDefault(); search.focus(); }
  });
  // Old overview bookmarks follow the lists to their dedicated pages.
  function revealHash() {
    var id;
    try { id = decodeURIComponent(location.hash.slice(1)); } catch (e) { return; }
    if (document.querySelector('[data-overview]')) {
      var destination = id === 'multibagger' ? 'multibaggers.html' :
        ['large', 'mid', 'small', 'spec', 'growth', 'candidate-scan'].includes(id) ? 'growth.html' : '';
      if (destination) { location.replace(destination + '#' + encodeURIComponent(id)); return; }
    }
    var target = document.getElementById(id) || Array.from(document.querySelectorAll('[data-panel]')).find(function (p) {
      return p.dataset.panel === id;
    });
    if (!target) return;
    if (target.dataset.panel) {
      var tab = Array.from(document.querySelectorAll('[data-tab]')).find(function (b) { return b.dataset.tab === target.dataset.panel; });
      if (tab) tab.click();
    }
    var parent = target;
    while (parent) {
      if (parent.tagName === 'DETAILS') parent.open = true;
      parent = parent.parentElement;
    }
    target.scrollIntoView({block: 'start'});
  }
  window.addEventListener('hashchange', revealHash);
  revealHash();
  render();
})();
"""
