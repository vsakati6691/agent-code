"""Static CSS and JavaScript for the dashboard site (no external scripts, fonts or trackers)."""

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
.tabs button[aria-selected="true"] { background: var(--surface-2); font-weight: 650; border-color: var(--text-secondary); }
.controls { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin: 8px 0; }
.controls input, .controls select { font: inherit; padding: 5px 8px; border: 1px solid var(--border); border-radius: 6px;
  background: var(--surface-1); color: var(--text-primary); }
.table-wrap { overflow-x: auto; border: 1px solid var(--border); border-radius: 8px; background: var(--surface-1); }
table { border-collapse: collapse; width: 100%; font-size: 14px; }
th, td { padding: 7px 9px; border-bottom: 1px solid var(--border); text-align: left; vertical-align: top; }
th { background: var(--surface-2); font-weight: 600; white-space: nowrap; }
th[data-sort] { cursor: pointer; } th[data-sort]::after { content: " \2195"; color: var(--text-muted); }
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
@media (max-width: 640px) { h1 { font-size: 20px; } th, td { padding: 6px; } .hide-sm { display: none; } }
"""

JS = r"""
(function () {
  // freshness: warn in the browser even if a failed update never redeployed the site
  var fresh = document.getElementById('freshness');
  if (fresh) {
    var asOf = new Date(fresh.dataset.asof + 'T21:00:00Z');
    var days = Math.floor((Date.now() - asOf.getTime()) / 86400000);
    var age = document.getElementById('age');
    if (age) age.textContent = days <= 0 ? 'today' : days + (days === 1 ? ' day ago' : ' days ago');
    if (days > 9) {
      var b = document.getElementById('stale-client');
      if (b) b.hidden = false;
    }
  }
  // tabs
  document.querySelectorAll('[data-tabs]').forEach(function (group) {
    var buttons = group.querySelectorAll('button[data-tab]');
    function show(key) {
      buttons.forEach(function (b) { b.setAttribute('aria-selected', b.dataset.tab === key ? 'true' : 'false'); });
      document.querySelectorAll('[data-panel-of="' + group.id + '"]').forEach(function (p) { p.hidden = p.dataset.panel !== key; });
      try { localStorage.setItem('tab:' + group.id, key); } catch (e) {}
    }
    buttons.forEach(function (b) { b.addEventListener('click', function () { show(b.dataset.tab); }); });
    var saved = null; try { saved = localStorage.getItem('tab:' + group.id); } catch (e) {}
    var hash = location.hash.replace('#', '');
    var first = buttons[0] && buttons[0].dataset.tab;
    var want = [hash, saved, first].filter(function (k) { return k && group.querySelector('button[data-tab="' + k + '"]'); })[0];
    if (want) show(want);
  });
  // sortable + searchable + sector-filtered tables
  document.querySelectorAll('table[data-table]').forEach(function (table) {
    var tbody = table.tBodies[0];
    var search = document.querySelector('[data-search="' + table.id + '"]');
    var sector = document.querySelector('[data-sector="' + table.id + '"]');
    var count = document.querySelector('[data-count="' + table.id + '"]');
    function filter() {
      var q = search ? search.value.trim().toLowerCase() : '';
      var s = sector ? sector.value : '';
      var shown = 0;
      Array.prototype.forEach.call(tbody.rows, function (r) {
        var ok = (!q || r.textContent.toLowerCase().indexOf(q) >= 0) && (!s || r.dataset.sector === s);
        r.hidden = !ok; if (ok) shown++;
      });
      if (count) count.textContent = shown + ' of ' + tbody.rows.length + ' shown';
    }
    if (search) search.addEventListener('input', filter);
    if (sector) sector.addEventListener('change', filter);
    table.querySelectorAll('th[data-sort]').forEach(function (th, i) {
      var dir = 1;
      th.addEventListener('click', function () {
        var col = Array.prototype.indexOf.call(th.parentNode.children, th);
        var rows = Array.prototype.slice.call(tbody.rows);
        var numeric = th.dataset.sort === 'num';
        rows.sort(function (a, b) {
          var x = a.cells[col].dataset.v !== undefined ? a.cells[col].dataset.v : a.cells[col].textContent;
          var y = b.cells[col].dataset.v !== undefined ? b.cells[col].dataset.v : b.cells[col].textContent;
          if (numeric) { x = parseFloat(x); y = parseFloat(y); if (isNaN(x)) x = -Infinity; if (isNaN(y)) y = -Infinity; return (x - y) * dir; }
          return String(x).localeCompare(String(y)) * dir;
        });
        dir = -dir;
        rows.forEach(function (r) { tbody.appendChild(r); });
      });
    });
    filter();
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
