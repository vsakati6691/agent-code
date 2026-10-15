"""Static CSS and JavaScript for the dashboard site (no external scripts, fonts or trackers)."""

from .assets_scan import CSS as SCAN_CSS, JS as SCAN_JS

CSS = r"""
:root {
  color-scheme: light;
  --bg: #f7f7f5; --surface-1: #fcfcfb; --surface-2: #f0efec; --border: #dddcd7;
  --text-primary: #0b0b0b; --text-secondary: #52514e; --text-muted: #6d6c67;
  --series-1: #2a78d6; --reference: #6d6c67; --link: #1c5cab;
  --good: #0f7a3d; --warn-bg: #fff4d6; --warn-border: #c98500; --bad-bg: #fde8e8; --bad-border: #c23b3a;
  --info-bg: #e8f1fc; --info-border: #2a78d6;
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) {
    color-scheme: dark;
    --bg: #121211; --surface-1: #1a1a19; --surface-2: #242422; --border: #383835;
    --text-primary: #ffffff; --text-secondary: #c3c2b7; --text-muted: #a3a29b;
    --series-1: #3987e5; --reference: #a3a29b; --link: #86b6ef;
    --good: #4cc27a; --warn-bg: #3a2f10; --warn-border: #c98500; --bad-bg: #3d1a1a; --bad-border: #e66767;
    --info-bg: #14263d; --info-border: #3987e5;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --bg: #121211; --surface-1: #1a1a19; --surface-2: #242422; --border: #383835;
  --text-primary: #ffffff; --text-secondary: #c3c2b7; --text-muted: #a3a29b;
  --series-1: #3987e5; --reference: #a3a29b; --link: #86b6ef;
  --good: #4cc27a; --warn-bg: #3a2f10; --warn-border: #c98500; --bad-bg: #3d1a1a; --bad-border: #e66767;
  --info-bg: #14263d; --info-border: #3987e5;
}
* { box-sizing: border-box; }
html, body { margin: 0; background: var(--bg); color: var(--text-primary);
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
a { color: var(--link); }
header.site { background: var(--surface-1); border-bottom: 1px solid var(--border); }
header.site .inner, main { max-width: 1180px; margin: 0 auto; padding: 0 16px; }
header.site .inner { display: flex; flex-wrap: wrap; gap: 8px 20px; align-items: center; padding-top: 12px; padding-bottom: 12px; }
header.site .brand { font-weight: 650; font-size: 17px; color: var(--text-primary); text-decoration: none; }
nav a { margin-right: 14px; text-decoration: none; }
nav a[aria-current="page"] { font-weight: 650; text-decoration: underline; }
main { padding-top: 18px; padding-bottom: 48px; }
h1 { font-size: 24px; margin: 6px 0 4px; } h2 { font-size: 19px; margin: 28px 0 8px; } h3 { font-size: 16px; margin: 18px 0 6px; }
p.lede { color: var(--text-secondary); margin-top: 0; }
.banner { border: 1px solid; border-left-width: 5px; border-radius: 6px; padding: 10px 14px; margin: 10px 0; }
.banner.info { background: var(--info-bg); border-color: var(--info-border); }
.banner.warn { background: var(--warn-bg); border-color: var(--warn-border); }
.banner.bad { background: var(--bad-bg); border-color: var(--bad-border); }
.banner strong { display: block; }
.card { background: var(--surface-1); border: 1px solid var(--border); border-radius: 8px; padding: 14px 16px; margin: 12px 0; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }
.stat .label { color: var(--text-secondary); font-size: 13px; } .stat .value { font-size: 20px; font-weight: 650; }
.muted { color: var(--text-muted); } .small { font-size: 13px; }
.tabs { display: flex; flex-wrap: wrap; gap: 6px; margin: 12px 0; }
.tabs button { font: inherit; padding: 6px 12px; border: 1px solid var(--border); background: var(--surface-1);
  color: var(--text-primary); border-radius: 6px; cursor: pointer; }
.tabs button[aria-selected="true"] { background: var(--series-1); color: #fff; font-weight: 650; border-color: var(--series-1);
  box-shadow: inset 0 -3px 0 var(--text-primary); text-decoration: underline; text-underline-offset: 3px; }
.controls { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin: 8px 0; }
.controls input, .controls select { font: inherit; padding: 5px 8px; border: 1px solid var(--border); border-radius: 6px;
  background: var(--surface-1); color: var(--text-primary); }
.table-wrap { overflow-x: auto; border: 1px solid var(--border); border-radius: 8px; background: var(--surface-1); }
table { border-collapse: collapse; width: 100%; font-size: 14px; }
th, td { padding: 6px 7px; border-bottom: 1px solid var(--border); text-align: left; vertical-align: top; }
td.val { white-space: normal; min-width: 92px; }
td.dist { white-space: normal; min-width: 120px; }
th { background: var(--surface-2); font-weight: 600; white-space: nowrap; }
/* sortable headers hold a real button; the arrow shows the current order */
th[data-sort] .sortbtn { font: inherit; font-weight: inherit; color: inherit; background: none; border: 0; padding: 0; margin: 0;
  cursor: pointer; text-align: inherit; }
th[data-sort] .sortbtn::after { content: " \2195"; color: var(--text-muted); }
th[aria-sort="ascending"] .sortbtn::after { content: " \25B2"; color: var(--text-primary); }
th[aria-sort="descending"] .sortbtn::after { content: " \25BC"; color: var(--text-primary); }
.sortbtn:focus-visible { outline: 2px solid var(--series-1); outline-offset: 2px; }
.linkbtn { font: inherit; font-size: 13px; background: none; border: 0; padding: 0 0 0 8px; color: var(--link);
  text-decoration: underline; cursor: pointer; }
.lazy[aria-busy="true"] { opacity: 0.7; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
tr:last-child td { border-bottom: 0; }
.pill { display: inline-block; padding: 1px 7px; border-radius: 10px; font-size: 12px; border: 1px solid var(--border);
  background: var(--surface-2); color: var(--text-secondary); margin: 1px 2px 1px 0; }
.pill.high { border-color: var(--good); color: var(--good); }
.pill.low { border-color: var(--bad-border); }
.bar { height: 8px; background: var(--surface-2); border-radius: 4px; min-width: 60px; }
.bar > span { display: block; height: 8px; background: var(--series-1); border-radius: 4px; }
details { margin: 6px 0; } summary { cursor: pointer; color: var(--link); }
.chart { position: relative; } .chart svg { width: 100%; height: auto; display: block; }
.chart .tip { position: absolute; pointer-events: none; background: var(--surface-1); border: 1px solid var(--border);
  border-radius: 6px; padding: 6px 9px; font-size: 13px; display: none; white-space: nowrap; box-shadow: 0 2px 8px rgba(0,0,0,.12); }
.legend { display: flex; gap: 16px; font-size: 13px; color: var(--text-secondary); margin: 4px 0; }
.legend i { display: inline-block; width: 18px; height: 0; border-top: 2px solid var(--series-1); vertical-align: middle; margin-right: 6px; }
.legend i.ref { border-top: 2px dashed var(--reference); }
ul.tight { margin: 4px 0; padding-left: 20px; }
footer { color: var(--text-muted); font-size: 13px; border-top: 1px solid var(--border); margin-top: 32px; padding-top: 12px; }
.themebtn { font: inherit; font-size: 13px; padding: 3px 9px; border: 1px solid var(--border); border-radius: 6px;
  background: var(--surface-1); color: var(--text-secondary); cursor: pointer; }
@media print {
  header.site, .symsearch, .themebtn, .tabs, .controls, footer, #stale-client { display: none !important; }
  :root, body { background: #fff !important; color: #000 !important; }
  .card, .banner, .table-wrap, th, tr.detail td { background: #fff !important; box-shadow: none !important; }
  .table-wrap { overflow: visible !important; border: 0; }
  .table-wrap td.tk, .table-wrap th.tk { position: static; }
  a { color: #000; text-decoration: underline; }
  h1, h2, h3 { page-break-after: avoid; } tr, .card { page-break-inside: avoid; }
  .chart svg { max-width: 100%; }
}
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
/* keyboard users: the first Tab press reveals a link straight to the page content */
.skip { position: absolute; left: -999px; top: 8px; z-index: 10; padding: 6px 10px; background: var(--surface-1);
  border: 2px solid var(--series-1); border-radius: 6px; color: var(--text-primary); }
.skip:focus { left: 16px; }
main:focus { outline: none; }
.rowtoggle { font: inherit; background: none; border: 0; padding: 0; color: var(--link); cursor: pointer; text-align: left; }
.rowtoggle::after { content: " \25B8"; color: var(--text-muted); }
.rowtoggle[aria-expanded="true"]::after { content: " \25BE"; }
.rowtoggle:focus-visible, .tabs button:focus-visible { outline: 2px solid var(--series-1); outline-offset: 2px; }
/* options: maximum loss and critical warnings stay visible at every width */
.crit, td.crit { color: var(--bad-border); font-weight: 650; } th.crit { color: var(--text-primary); }
tr.detail p.crit { margin: 4px 0 8px; }
.facts { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 8px 18px; }
.facts h4 { margin: 6px 0 4px; font-size: 14px; } .facts ul { margin: 0; }
.ow-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 12px; margin: 8px 0 16px; }
.ow-grid .card { margin: 0; } .ow-grid h3 { margin-top: 0; font-size: 15px; } .ow-grid ol { padding-left: 20px; margin: 4px 0; }
.ow-grid li { margin: 3px 0; }
.tabs button .small { font-weight: 400; }
td.ev-unknown, td.ev-scheduled { color: var(--warn-border); }
.flags ul { margin: 2px 0; }
tbody.item + tbody.item tr:first-child td { border-top: 1px solid var(--border); }
tbody.item tr:first-child td { border-bottom: 0; }
tr.detail td { background: var(--surface-2); }
td.risk { min-width: 170px; max-width: 260px; }
.evidence { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 12px 18px;
  position: sticky; left: 0; width: min(1120px, calc(100vw - 72px)); }
tr.detail > td { white-space: normal; }
.pin { position: sticky; left: 0; width: min(1120px, calc(100vw - 72px)); }
.evidence h4, .card h4 { margin: 6px 0 4px; font-size: 14px; }
.ev-row { display: grid; grid-template-columns: 80px 1fr 32px; gap: 6px; align-items: center; font-size: 13px; margin: 2px 0; }
.panels { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 12px; margin: 12px 0; }
.panels .card { margin: 0; } .panels h3 { margin-top: 0; font-size: 15px; }
/* phones: the ranked lists come first; the context panels follow them */
.overview { display: flex; flex-direction: column; } .ov-panels, .ov-lists { min-width: 0; }
.mb-list { display: grid; gap: 12px; }
.card.mb header { display: flex; flex-wrap: wrap; gap: 6px 10px; align-items: baseline; margin-bottom: 4px; }
.mb-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 0 18px; }
.rank { font-weight: 700; color: var(--text-secondary); }
/* the ticker column stays visible while a wide table scrolls sideways */
.table-wrap td.tk, .table-wrap th.tk { position: sticky; left: 0; z-index: 2; background: var(--surface-1);
  box-shadow: 1px 0 0 var(--border); min-width: 84px; }
.table-wrap th.tk { background: var(--surface-2); }
.spark { vertical-align: middle; }
.strip { display: flex; flex-wrap: wrap; gap: 4px 12px; align-items: center; font-size: 13px; margin: 4px 0; }
.chip { display: inline-flex; align-items: center; gap: 5px; }
.chipbar { display: inline-block; height: 8px; background: var(--series-1); border-radius: 4px; }
.summary { margin: 4px 0; } details.more { display: inline; } details.more > summary { display: inline; font-size: 13px; }
details.more[open] > p { margin: 6px 0 0; }
.chart.range { overflow-x: auto; } .chart.range svg { min-width: 560px; }
caption { text-align: left; }
.symsearch input { font: inherit; padding: 4px 8px; border: 1px solid var(--border); border-radius: 6px; width: 150px;
  background: var(--surface-1); color: var(--text-primary); }
header.site .inner .symsearch { margin-left: auto; }
@media (max-width: 700px) {
  header.site .inner .symsearch { margin-left: 0; } .symsearch input { width: 100%; }
  header.site .inner { flex-direction: column; align-items: stretch; gap: 4px; padding-top: 8px; padding-bottom: 6px; }
  nav { display: flex; flex-wrap: nowrap; overflow-x: auto; white-space: nowrap; gap: 14px; padding-bottom: 4px; min-width: 0; max-width: 100%;
        scrollbar-width: thin; -webkit-overflow-scrolling: touch; }
  nav a { flex: none; margin-right: 0; padding: 4px 0; }
  h1 { font-size: 20px; } h2 { font-size: 17px; } th, td { padding: 6px 5px; } .hide-sm { display: none; }
  table { font-size: 13px; } td.risk { min-width: 140px; } .tabs button { padding: 6px 9px; }
  .ov-panels { order: 2; } .ov-lists { order: 1; }
}
"""

JS = r"""
(function () {
  // colour theme: auto (follows the system) -> light -> dark; the choice is remembered on this device only
  var tb = document.querySelector('.themebtn');
  if (tb) {
    var order = ['auto', 'light', 'dark'];
    var cur = 'auto';
    try { cur = localStorage.getItem('theme') || 'auto'; } catch (e) {}
    function apply(t) {
      if (t === 'auto') { delete document.documentElement.dataset.theme; } else { document.documentElement.dataset.theme = t; }
      tb.textContent = 'Theme: ' + t;
      tb.setAttribute('aria-label', 'Colour theme: ' + (t === 'auto' ? 'automatic' : t) + '. Select to change.');
      try { if (t === 'auto') localStorage.removeItem('theme'); else localStorage.setItem('theme', t); } catch (e) {}
    }
    apply(order.indexOf(cur) >= 0 ? cur : 'auto');
    tb.addEventListener('click', function () {
      var now = document.documentElement.dataset.theme || 'auto';
      apply(order[(order.indexOf(now) + 1) % order.length]);
    });
  }
  // printing: expand every collapsed section so the printout is complete
  window.addEventListener('beforeprint', function () {
    document.querySelectorAll('details').forEach(function (d) { d.setAttribute('open', ''); });
  });
  // header search: open the symbol page when the input matches a ticker in the inline datalist
  var sf = document.querySelector('.symsearch');
  if (sf) {
    var q = sf.querySelector('input');
    var known = {};
    sf.querySelectorAll('datalist option').forEach(function (o) { known[o.value.toUpperCase()] = o.value; });
    function go() {
      var t = known[q.value.trim().toUpperCase()];
      if (t) location.href = sf.dataset.base + encodeURIComponent(t) + '.html';
    }
    q.addEventListener('change', go);
    q.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); go(); } });
  }
  // phone header: keep the current page's link in view inside the scrolling nav
  var cur = document.querySelector('nav a[aria-current]');
  if (cur && cur.parentNode.scrollWidth > cur.parentNode.clientWidth) {
    cur.parentNode.scrollLeft = cur.offsetLeft - 16;
  }
  // freshness: warn in the browser even if a failed update never redeployed the site
  // age in completed NYSE sessions, New York time (spec FRESHNESS_RULE); the session list comes from the build
  var fresh = document.getElementById('freshness');
  if (fresh) {
    var sessions = (fresh.dataset.sessions || '').split(',').filter(Boolean);
    var parts = new Intl.DateTimeFormat('en-CA', {timeZone: 'America/New_York', year: 'numeric', month: '2-digit',
      day: '2-digit', hour: '2-digit', hour12: false}).formatToParts(new Date());
    var part = function (t) { var x = parts.filter(function (p) { return p.type === t; })[0]; return x ? x.value : ''; };
    var today = part('year') + '-' + part('month') + '-' + part('day'), hour = parseInt(part('hour'), 10) % 24;
    var done = sessions.filter(function (s) { return s < today || (s === today && hour >= 16); }).length;
    var beyond = sessions.length > 0 && today > sessions[sessions.length - 1];
    var age = document.getElementById('age');
    if (age) age.textContent = beyond ? 'more than ' + sessions.length + ' trading sessions old'
      : done === 0 ? 'the latest completed session' : done + (done === 1 ? ' trading session' : ' trading sessions') + ' old';
    if (beyond || done > parseInt(fresh.dataset.staleAfter || '6', 10)) {
      var b = document.getElementById('stale-client');
      if (b) b.hidden = false;
    }
  }
  // keyboard support for every tab list: Left/Right (or Up/Down) move between tabs and select them, Home/End jump,
  // and only the selected tab sits in the Tab order (roving tabindex)
  function roving(list) {
    list.querySelectorAll('button[role="tab"]').forEach(function (b) {
      b.setAttribute('tabindex', b.getAttribute('aria-selected') === 'true' ? '0' : '-1');
    });
  }
  function tablistKeys(list, select) {
    var tabs = Array.prototype.slice.call(list.querySelectorAll('button[role="tab"]'));
    function go(i) { var b = tabs[(i + tabs.length) % tabs.length]; select(b); b.focus(); }
    tabs.forEach(function (b, i) {
      b.addEventListener('keydown', function (e) {
        if (e.key === 'ArrowRight' || e.key === 'ArrowDown') { e.preventDefault(); go(i + 1); }
        else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') { e.preventDefault(); go(i - 1); }
        else if (e.key === 'Home') { e.preventDefault(); go(0); }
        else if (e.key === 'End') { e.preventDefault(); go(tabs.length - 1); }
      });
    });
  }
  // tabs
  document.querySelectorAll('[data-tabs]').forEach(function (group) {
    var buttons = group.querySelectorAll('button[data-tab]');
    // default to the first tab on every load; only an explicit URL hash selects another (no silent restore)
    function show(key, push) {
      buttons.forEach(function (b) { b.setAttribute('aria-selected', b.dataset.tab === key ? 'true' : 'false'); });
      document.querySelectorAll('[data-panel-of="' + group.id + '"]').forEach(function (p) { p.hidden = p.dataset.panel !== key; });
      roving(group);
      if (push) history.replaceState(null, '', '#' + key);
    }
    buttons.forEach(function (b) { b.addEventListener('click', function () { show(b.dataset.tab, true); }); });
    tablistKeys(group, function (b) { show(b.dataset.tab, true); });
    var hash = location.hash.replace('#', '');
    var first = buttons[0] && buttons[0].dataset.tab;
    var want = [hash, first].filter(function (k) { return k && group.querySelector('button[data-tab="' + k + '"]'); })[0];
    if (want) show(want, false);
  });
  // evidence blocks on the list pages are separate small files, fetched the first time their row opens
  function lazyLoad(box) {
    if (!box || box.dataset.state === 'loading' || box.dataset.state === 'loaded') return;
    box.dataset.state = 'loading';
    box.setAttribute('aria-busy', 'true');
    fetch(box.dataset.src, {credentials: 'same-origin'}).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    }).then(function (j) {
      box.innerHTML = j.html;
      box.dataset.state = 'loaded';
    }).catch(function () {
      box.dataset.state = '';
      box.textContent = 'The evidence could not be loaded. ';
      var a = document.createElement('a');
      a.href = box.dataset.page;
      a.textContent = 'Open the full research page';
      box.appendChild(a);
      box.appendChild(document.createTextNode(', or select the ticker again to retry.'));
    }).then(function () { box.removeAttribute('aria-busy'); });
  }
  // expandable rows (evidence, assumptions, payoffs)
  document.querySelectorAll('.rowtoggle').forEach(function (b) {
    b.addEventListener('click', function () {
      var row = document.getElementById(b.getAttribute('aria-controls'));
      var open = b.getAttribute('aria-expanded') === 'true';
      b.setAttribute('aria-expanded', open ? 'false' : 'true');
      if (row) {
        row.hidden = open;
        if (!open) row.querySelectorAll('.lazy[data-src]').forEach(lazyLoad);
      }
    });
  });
  // two-dimensional tabs (option type x expiry horizon)
  // Calls / 3 months on every load unless the URL hash names a tab (#put-6m); the hash follows each click
  document.querySelectorAll('[data-matrix]').forEach(function (box) {
    var state = {};
    function valid(d, v) { return v && box.querySelector('button[data-dim="' + d + '"][data-val="' + v + '"]'); }
    function render(push) {
      box.querySelectorAll('button[data-dim]').forEach(function (b) {
        b.setAttribute('aria-selected', state[b.dataset.dim] === b.dataset.val ? 'true' : 'false');
      });
      box.querySelectorAll('section[data-type]').forEach(function (p) {
        p.hidden = !(p.dataset.type === state.type && p.dataset.hz === state.hz);
      });
      box.querySelectorAll('[role="tablist"]').forEach(roving);
      if (push) history.replaceState(null, '', '#' + state.type + '-' + state.hz);
    }
    function fromHash() {
      var parts = location.hash.replace('#', '').split('-');
      var changed = false;
      ['type', 'hz'].forEach(function (d, i) {
        var first = box.querySelector('button[data-dim="' + d + '"]');
        var want = valid(d, parts[i]) ? parts[i] : (state[d] || (first && first.dataset.val));
        if (want !== state[d]) { state[d] = want; changed = true; }
      });
      return changed;
    }
    fromHash();
    box.querySelectorAll('button[data-dim]').forEach(function (b) {
      b.addEventListener('click', function () { state[b.dataset.dim] = b.dataset.val; render(true); });
    });
    box.querySelectorAll('[role="tablist"]').forEach(function (tl) {
      tablistKeys(tl, function (b) { state[b.dataset.dim] = b.dataset.val; render(true); });
    });
    // in-page links such as #put-6m (the summary strip) switch the view without a reload
    window.addEventListener('hashchange', function () { if (fromHash()) render(false); });
    render(false);
  });
  // sortable + searchable + filtered tables; grouped tables move each <tbody class="item"> as a unit.
  // Each header is a real button, and sort changes are announced politely. The last search, filters and sort of a
  // table are remembered on this device only (localStorage, per page and table); a restored view is always shown
  // as such, with a reset control, and is never applied silently.
  var announce = document.createElement('div');
  announce.className = 'sr-only';
  announce.setAttribute('role', 'status');
  announce.setAttribute('aria-live', 'polite');
  document.body.appendChild(announce);
  function remember(key, value) {
    try { if (value === null) localStorage.removeItem(key); else localStorage.setItem(key, JSON.stringify(value)); } catch (e) {}
  }
  function recall(key) {
    try { var raw = localStorage.getItem(key); return raw ? JSON.parse(raw) : null; } catch (e) { return null; }
  }
  document.querySelectorAll('table[data-table]').forEach(function (table) {
    var grouped = table.hasAttribute('data-grouped');
    var holder = grouped ? table : table.tBodies[0];
    function items() {
      return grouped ? Array.prototype.filter.call(table.tBodies, function (b) { return b.classList.contains('item'); })
                     : Array.prototype.slice.call(table.tBodies[0].rows);
    }
    function head(it) { return grouped ? it.rows[0] : it; }
    var original = items().slice();
    var search = document.querySelector('[data-search="' + table.id + '"]');
    var sector = document.querySelector('[data-sector="' + table.id + '"]');
    var count = document.querySelector('[data-count="' + table.id + '"]');
    var filters = Array.from(document.querySelectorAll('[data-filter="' + table.id + '"]'));
    var empty = document.querySelector('[data-empty="' + table.id + '"]');
    var ths = Array.prototype.slice.call(table.querySelectorAll('th[data-sort]'));
    var key = 'view:' + location.pathname + ':' + table.id;
    var view = {q: '', s: '', f: {}, col: null, label: '', dir: 1};    // dir: 1 ascending, -1 descending
    // a table with its own "Reset filters" button uses it; any other table gets a "Reset view" link next to the count
    var ownReset = document.querySelector('[data-reset="' + table.id + '"]');
    var reset = ownReset;
    if (!reset) {
      reset = document.createElement('button');
      reset.type = 'button';
      reset.className = 'linkbtn';
      reset.textContent = 'Reset view';
      reset.hidden = true;
      if (count && count.parentNode) count.parentNode.insertBefore(reset, count.nextSibling);
    }
    function isDefault() { return !view.q && !view.s && !Object.keys(view.f).length && view.col === null; }
    function filter() {
      view.q = search ? search.value.trim() : '';
      view.s = sector ? sector.value : '';
      view.f = {};
      filters.forEach(function (f) { if (f.value) view.f[f.dataset.field] = f.value; });
      var q = view.q.toLowerCase(), s = view.s;
      var all = items(), shown = 0;
      all.forEach(function (it) {
        var ok = (!q || it.textContent.toLowerCase().indexOf(q) >= 0) && (!s || it.dataset.sector === s) &&
          filters.every(function (f) { return !f.value || it.dataset[f.dataset.field] === f.value; }) &&
          (typeof table.acceptRow !== 'function' || table.acceptRow(it));
        it.hidden = !ok; if (ok) shown++;
      });
      if (count) count.textContent = shown + ' of ' + all.length + ' shown';
      if (empty) empty.hidden = shown > 0;
      if (!ownReset) reset.hidden = isDefault();
      remember(key, isDefault() ? null : view);
    }
    function applySort(th, dir) {
      var col = Array.prototype.indexOf.call(th.parentNode.children, th);
      var numeric = th.dataset.sort === 'num';
      var all = items();
      all.sort(function (a, b) {
        var ca = head(a).cells[col], cb = head(b).cells[col];
        var x = ca.dataset.v !== undefined ? ca.dataset.v : ca.textContent;
        var y = cb.dataset.v !== undefined ? cb.dataset.v : cb.textContent;
        if (numeric) {
          x = parseFloat(x); y = parseFloat(y);
          if (isNaN(x)) return isNaN(y) ? 0 : 1;      // missing numbers sort last in either direction
          if (isNaN(y)) return -1;
          return (x - y) * dir;
        }
        return String(x).localeCompare(String(y)) * dir;
      });
      ths.forEach(function (o) { o.setAttribute('aria-sort', 'none'); });
      th.setAttribute('aria-sort', dir > 0 ? 'ascending' : 'descending');
      all.forEach(function (it) { holder.appendChild(it); });
      return col;
    }
    ths.forEach(function (th) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'sortbtn';
      while (th.firstChild) btn.appendChild(th.firstChild);
      th.appendChild(btn);
      th.setAttribute('aria-sort', 'none');
      btn.addEventListener('click', function () {
        var dir = th.getAttribute('aria-sort') === 'ascending' ? -1 : 1;
        view.col = applySort(th, dir);
        view.label = btn.textContent.trim();
        view.dir = dir;
        announce.textContent = 'Sorted by ' + view.label + ', ' + (dir > 0 ? 'ascending' : 'descending') + '.';
        filter();
      });
    });
    if (search) search.addEventListener('input', filter);
    // Optional local calculator predicates and compact-data tables reuse the same sorting/filter controls.
    table.addEventListener('tablefilterchange', filter);
    table.addEventListener('tabledatachange', function () {
      original = items().slice();
      var selected = ths.find(function (th) {
        return Array.prototype.indexOf.call(th.parentNode.children, th) === view.col;
      });
      if (selected) applySort(selected, view.dir);
      filter();
    });
    if (sector) sector.addEventListener('change', filter);
    filters.forEach(function (f) { f.addEventListener('change', filter); });
    document.addEventListener('pinschange', filter);
    reset.addEventListener('click', function () {
      if (search) search.value = '';
      if (sector) sector.value = '';
      filters.forEach(function (f) { f.value = ''; });
      view.col = null; view.label = ''; view.dir = 1;
      ths.forEach(function (o) { o.setAttribute('aria-sort', 'none'); });
      original.forEach(function (it) { holder.appendChild(it); });
      filter();
      announce.textContent = 'View reset to the default order and filters.';
    });
    var saved = recall(key);
    if (saved && typeof saved === 'object') {
      if (search && typeof saved.q === 'string') search.value = saved.q;
      if (sector && typeof saved.s === 'string' &&
          Array.prototype.some.call(sector.options, function (o) { return o.value === saved.s; })) sector.value = saved.s;
      if (saved.f && typeof saved.f === 'object') filters.forEach(function (f) {
        var v = saved.f[f.dataset.field];
        if (typeof v === 'string' && Array.prototype.some.call(f.options, function (o) { return o.value === v; })) f.value = v;
      });
      var th = ths.filter(function (t) {
        return Array.prototype.indexOf.call(t.parentNode.children, t) === saved.col &&
               t.querySelector('.sortbtn').textContent.trim() === saved.label;
      })[0];
      if (th && (saved.dir === 1 || saved.dir === -1)) {
        view.col = applySort(th, saved.dir); view.label = saved.label; view.dir = saved.dir;
      }
    }
    filter();
    if (!isDefault()) announce.textContent = 'Saved view restored for this table. Use the reset control to clear it.';
  });
  // line chart crosshair + tooltip
  document.querySelectorAll('.chart[data-series]').forEach(function (box) {
    var data = JSON.parse(box.dataset.series);
    var svg = box.querySelector('svg'); var tip = box.querySelector('.tip'); var hair = svg.querySelector('.hair');
    var vb = svg.viewBox.baseVal; var L = +box.dataset.left, R = +box.dataset.right;
    function at(evt) {
      var rect = svg.getBoundingClientRect();
      var x = (evt.clientX - rect.left) / rect.width * vb.width;
      var i = Math.round((x - L) / (R - L) * (data.dates.length - 1));
      return Math.max(0, Math.min(data.dates.length - 1, i));
    }
    function move(evt) {
      var i = at(evt); var x = L + (R - L) * i / Math.max(1, data.dates.length - 1);
      hair.setAttribute('x1', x); hair.setAttribute('x2', x); hair.style.display = '';
      tip.textContent = '';
      var d = document.createElement('div'); d.textContent = data.dates[i]; d.className = 'muted'; tip.appendChild(d);
      [['stock', data.label || 'Stock'], ['benchmark', data.benchLabel || 'Benchmark']].forEach(function (k) {
        if (!data[k[0]]) return;
        var row = document.createElement('div'); var s = document.createElement('strong');
        s.textContent = data[k[0]][i].toFixed(1); row.appendChild(s);
        row.appendChild(document.createTextNode(' ' + k[1])); tip.appendChild(row);
      });
      var rect = svg.getBoundingClientRect();
      tip.style.display = 'block';
      var px = (x / vb.width) * rect.width;
      tip.style.left = Math.min(rect.width - tip.offsetWidth, Math.max(0, px + 10)) + 'px';
      tip.style.top = '8px';
    }
    svg.addEventListener('pointermove', move);
    svg.addEventListener('pointerleave', function () { tip.style.display = 'none'; hair.style.display = 'none'; });
  });
})();
"""

CSS += SCAN_CSS
JS += SCAN_JS

from .assets_decisions import CSS as DECISION_CSS, JS as DECISION_JS
CSS += DECISION_CSS
JS += DECISION_JS
