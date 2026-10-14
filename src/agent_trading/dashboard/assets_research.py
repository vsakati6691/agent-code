"""CSS and JavaScript for the comparison page and the scenario calculator (spec 2026-10-14.5).

No external scripts. COMPARE_JS mirrors compare.comparability() and compare.rebase_common(); LAB_JS mirrors
lab.run(). Both only read data embedded in the page and never send or store anything.
"""

CSS = r"""
:root { --s1: #2a78d6; --s2: #c55a11; --s3: #2f8f5b; --s4: #8e44ad; }
@media (prefers-color-scheme: dark) { :root:where(:not([data-theme="light"])) { --s1: #3987e5; --s2: #e8853f; --s3: #4cc27a; --s4: #b98ce0; } }
:root[data-theme="dark"] { --s1: #3987e5; --s2: #e8853f; --s3: #4cc27a; --s4: #b98ce0; }
.pill.ok, .pill.q-high { border-color: var(--good); color: var(--good); }
.pill.warn, .pill.q-medium { border-color: var(--warn-border); }
.pill.bad, .pill.q-low { border-color: var(--bad-border); color: var(--bad-border); }
.pill.muted, .pill.q-none { border-style: dashed; }
button:focus-visible, select:focus-visible, input:focus-visible { outline: 2px solid var(--series-1); outline-offset: 2px; }
.lab-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 10px 16px; margin: 8px 0; }
.lab-field { display: flex; flex-direction: column; gap: 2px; font-size: 14px; }
.lab-input { display: flex; align-items: center; gap: 6px; }
.lab-input input, .cmp-row select { font: inherit; padding: 5px 8px; border: 1px solid var(--border); border-radius: 6px;
  background: var(--surface-1); color: var(--text-primary); }
.lab-input input { width: 120px; }
.lab-input input[aria-invalid="true"] { border-color: var(--bad-border); }
.lab button, .cmp-controls button { font: inherit; padding: 6px 12px; border: 1px solid var(--border); border-radius: 6px;
  background: var(--surface-1); color: var(--text-primary); cursor: pointer; }
.lab tr.mine td { font-weight: 650; background: var(--info-bg); }
.cmp-controls { display: flex; flex-direction: column; flex-wrap: nowrap; align-items: stretch; gap: 6px; min-width: 0; }
.cmp-row { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.cmp-row select { min-width: 0; flex: 1 1 220px; max-width: 100%; }
.cmp-chips { list-style: none; padding: 0; margin: 2px 0; display: flex; flex-wrap: wrap; gap: 6px; }
.cmp-chips li { display: inline-flex; align-items: center; gap: 2px; border: 1px solid var(--border); border-radius: 14px;
  padding: 1px 2px 1px 10px; background: var(--surface-2); }
.cmp-chips li i { display: inline-block; width: 14px; margin-right: 4px; border-top: 3px solid; vertical-align: middle; }
.cmp-chips button { border: 0; background: none; color: var(--link); padding: 2px 8px; }
.cmp-wrap td.metric { position: sticky; left: 0; background: var(--surface-1); min-width: 140px; max-width: 200px;
  white-space: normal; z-index: 1; box-shadow: 1px 0 0 var(--border); }
.cmp-wrap th:first-child { position: sticky; left: 0; z-index: 2; }
.cmp-wrap tr.group td { background: var(--surface-2); font-weight: 650; }
.cmp-wrap td.cell { min-width: 108px; white-space: normal; }
.cmp-wrap .pad { padding: 10px 12px; margin: 0; }
td .na { color: var(--text-muted); font-style: italic; }
.tabs button[aria-pressed="true"] { background: var(--series-1); color: #fff; font-weight: 650; border-color: var(--series-1); }
.cmp-legend { display: flex; flex-wrap: wrap; gap: 4px 14px; font-size: 13px; margin: 4px 0; }
.cmp-legend i { display: inline-block; width: 22px; border-top: 3px solid; vertical-align: middle; margin-right: 6px; }
@media (max-width: 700px) { .cmp-wrap td.metric { min-width: 110px; max-width: 130px; } .cmp-wrap td.cell { min-width: 92px; } }
@media print { .cmp-controls, .lab-grid, .lab button { display: none !important; } }
"""

LAB_JS = r"""
(function () {
  // Scenario calculator: the published EV/Sales scenario formula applied to the visitor's own inputs.
  // Mirrors dashboard/lab.py run(); nothing is stored, sent anywhere or ranked.
  var box = document.querySelector('.lab[data-lab]');
  if (!box) return;
  var inp = JSON.parse(box.getAttribute('data-lab'));
  var fields = Array.prototype.slice.call(box.querySelectorAll('input[data-key]'));
  var out = box.querySelector('.lab-out'), status = box.querySelector('.lab-status');
  function ok(x) { return typeof x === 'number' && isFinite(x); }
  function clamp(k, v) { var b = inp.bounds[k]; return Math.min(b[1], Math.max(b[0], v)); }
  function run(ch) {
    var g = clamp('starting_revenue_growth', ch.starting_revenue_growth), exitM = clamp('exit_ev_to_sales', ch.exit_ev_to_sales);
    var d = clamp('annual_dilution', ch.annual_dilution), margin = ok(ch.fcf_margin) ? clamp('fcf_margin', ch.fcf_margin) : null;
    var m0 = inp.fcf_margin_today, horizon = Math.max.apply(null, inp.years), rev = inp.revenue_ttm, res = {};
    for (var y = 1; y <= horizon; y++) {
      rev *= 1 + g;
      g += inp.fade * (inp.terminal - g);
      if (inp.years.indexOf(y) < 0) continue;
      var frac = y / horizon, mult = inp.ev_to_sales + (exitM - inp.ev_to_sales) * frac;
      var sh = inp.shares * Math.pow(1 + d, y), value = Math.max(0, (rev * mult + inp.net_cash) / sh);
      var mg = margin === null ? null : (ok(m0) ? m0 + (margin - m0) * frac : margin), fcf = mg === null ? null : rev * mg;
      res[y] = {value: value, multiple: value / inp.price, evfcf: fcf && fcf > 0 ? rev * mult / fcf : null};
    }
    return res;
  }
  function money(v) { return '$' + v.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2}); }
  function read() {
    var ch = {}, clamped = [];
    fields.forEach(function (f) {
      var k = f.getAttribute('data-key'), sc = parseFloat(f.getAttribute('data-scale')), v = parseFloat(f.value);
      if (!isFinite(v)) {
        ch[k] = k === 'fcf_margin' ? null : inp.published[k];
        f.setAttribute('aria-invalid', f.value === '' ? 'false' : 'true');
        return;
      }
      // an untouched field shows the published value rounded for display; use the exact published value then
      var raw = f.value === f.getAttribute('data-shown') && ok(inp.published[k]) ? inp.published[k] : v / sc, c = clamp(k, raw);
      f.setAttribute('aria-invalid', c !== raw ? 'true' : 'false');
      if (c !== raw) clamped.push(f.closest('label').querySelector('span').textContent);
      ch[k] = c;
    });
    return {choice: ch, clamped: clamped};
  }
  function same(ch) {
    return Object.keys(inp.published).every(function (k) {
      var a = ch[k], b = inp.published[k];
      if (!ok(b)) return a === null || a === undefined;
      return ok(a) && Math.abs(a - b) < 5e-5 * Math.max(1, Math.abs(b));
    });
  }
  function row(label, cls, values) {
    var tr = document.createElement('tr');
    if (cls) tr.className = cls;
    var th = document.createElement('td');
    th.textContent = label;
    tr.appendChild(th);
    values.forEach(function (v) { var td = document.createElement('td'); td.className = 'num'; td.textContent = v; tr.appendChild(td); });
    return tr;
  }
  function render(msg) {
    var r = read(), res = run(r.choice);
    out.textContent = '';
    out.appendChild(row('Your experiment', 'mine', inp.years.map(function (y) {
      return money(res[y].value) + ' (' + res[y].multiple.toFixed(2) + 'x)';
    })));
    out.appendChild(row('Implied EV / FCF in your experiment', '', inp.years.map(function (y) {
      return res[y].evfcf === null ? 'n/a' : res[y].evfcf.toFixed(1) + 'x';
    })));
    ['bear', 'base', 'bull'].forEach(function (k) {
      out.appendChild(row('Published ' + k + ' case', '', inp.years.map(function (y) { return money(inp.cases[k][String(y)]); })));
    });
    var text = msg || (same(r.choice) ? 'Your inputs equal the published base case, so the first row matches it.'
                                      : 'Showing your experiment. It is not saved and does not change any published figure.');
    if (r.clamped.length) text += ' Kept within the allowed range: ' + r.clamped.join(', ') + '.';
    status.textContent = text;
  }
  function reset() {
    fields.forEach(function (f) {
      var v = inp.published[f.getAttribute('data-key')];
      f.value = ok(v) ? (v * parseFloat(f.getAttribute('data-scale'))).toFixed(2) : '';
    });
    render('Reset to the published base-case assumptions.');
  }
  fields.forEach(function (f) { f.addEventListener('input', function () { render(); }); });
  box.querySelector('.lab-reset').addEventListener('click', reset);
  render();
})();
"""

COMPARE_JS = r"""
(function () {
  // Comparison page: mirrors dashboard/compare.py comparability() and rebase_common().
  var el = document.getElementById('cmp-data');
  if (!el || !document.getElementById('cmp-pick')) return;
  var data = JSON.parse(el.textContent), rules = data.rules, byT = {};
  data.entries.forEach(function (e) { e.chart.dates = data.date_sets[e.chart.dset] || []; byT[e.ticker] = e; });
  var COLORS = ['var(--s1)', 'var(--s2)', 'var(--s3)', 'var(--s4)'], DASH = ['', '6 4', '2 3', '8 3 2 3'];
  var sel = [], win = 1;
  var pick = document.getElementById('cmp-pick'), chips = document.getElementById('cmp-chips'),
      hint = document.getElementById('cmp-hint'), flags = document.getElementById('cmp-flags'),
      wrap = document.getElementById('cmp-table-wrap'), chart = document.getElementById('cmp-chart'),
      note = document.getElementById('cmp-chart-note');
  function ok(x) { return typeof x === 'number' && isFinite(x); }
  function text(tag, t, cls) {
    var n = document.createElement(tag);
    if (t !== undefined) n.textContent = t;
    if (cls) n.className = cls;
    return n;
  }
  function fmt(kind, v) {
    if (!ok(v)) return null;
    if (kind === 'pct') return (v * 100).toFixed(1) + '%';
    if (kind === 'x') return v.toFixed(1) + 'x';
    if (kind === 'money') {
      var a = Math.abs(v), s = v < 0 ? '-$' : '$';
      return a >= 1e12 ? s + (a / 1e12).toFixed(2) + 'T' : a >= 1e9 ? s + (a / 1e9).toFixed(1) + 'B' : s + (a / 1e6).toFixed(0) + 'M';
    }
    return v.toFixed(2);
  }
  function keysOf(o) { return Object.keys(o).sort(); }
  function comparability(es) {
    var out = [];
    if (es.length < rules.min_names || es.length > rules.max_names) {
      return ['Choose ' + rules.min_names + ' to ' + rules.max_names + ' different companies.'];
    }
    var dates = {};
    es.forEach(function (e) { dates[e.price_date] = 1; });
    if (keysOf(dates).length > 1) {
      out.push('Prices are from different sessions: ' + es.map(function (e) { return e.ticker + ' ' + e.price_date; }).join(', ') + '.');
    }
    var qs = es.filter(function (e) { return e.period.latest_quarter; });
    if (qs.length >= 2) {
      var ds = qs.map(function (e) { return Date.parse(e.period.latest_quarter); });
      if ((Math.max.apply(null, ds) - Math.min.apply(null, ds)) / 86400000 > rules.max_quarter_end_gap_days) {
        out.push('Trailing figures cover different periods (latest quarter ends: ' +
                 qs.map(function (e) { return e.ticker + ' ' + e.period.latest_quarter; }).join(', ') + ').');
      }
    }
    if (es.some(function (e) { return !e.period.latest_quarter; })) {
      out.push('Watchlist names have no stored quarter dates; their trailing figures cannot be period-matched.');
    }
    var prof = {};
    es.forEach(function (e) { if (e.profile) prof[e.profile] = 1; });
    if (keysOf(prof).length > 1) {
      out.push('Score components come from different scoring profiles (' + keysOf(prof).join(', ') +
               '), so the composite scores are not comparable.');
    }
    if (es.some(function (e) { return e.kind === 'watchlist'; })) out.push('Watchlist names are not scored: no components or composite.');
    var b = {};
    es.forEach(function (e) { if (e.benchmark) b[e.benchmark] = 1; });
    if (keysOf(b).length > 1) out.push('Names are measured against different benchmarks (' + keysOf(b).join(', ') + ').');
    return out;
  }
  function rebase(es, start) {
    var s = es.filter(function (e) { return e.chart.dates.length; });
    if (s.length < 2) return {found: false, reason: 'At least two of the selected names need stored price paths (watchlist names have none).'};
    var common = s[0].chart.dates.filter(function (d) {
      return d >= start && s.every(function (e) { return e.chart.dates.indexOf(d) >= 0; });
    });
    if (common.length < 2) return {found: false, reason: 'Fewer than two common dates in this window.'};
    return {found: true, start: common[0], end: common[common.length - 1], days: common, series: s.map(function (e) {
      var obs = {};
      e.chart.dates.forEach(function (d, i) { obs[d] = e.chart.values[i]; });
      var base = obs[common[0]];
      return {ticker: e.ticker, points: common.map(function (d) { return obs[d] / base * 100; }),
              omitted: e.chart.dates.length - common.length};
    })};
  }
  function missingText(e, key) { return e.not_stored.indexOf(key) >= 0 ? 'not stored for watchlist names' : 'missing in the filings used'; }
  function na(reason) { return text('span', reason, 'na'); }
  function addRow(tbody, label, cells, cls) {
    var tr = document.createElement('tr');
    if (cls) tr.className = cls;
    var td = text('td', label, 'metric');
    if (cls === 'group') td.colSpan = 1;
    tr.appendChild(td);
    cells.forEach(function (c) {
      var t = document.createElement('td');
      t.className = 'cell';
      if (c && c.nodeType) t.appendChild(c);
      else if (c === null) t.appendChild(na('n/a'));
      else t.textContent = c;
      tr.appendChild(t);
    });
    if (cls === 'group') for (var i = 0; i < cells.length || i < sel.length; i++) tr.appendChild(document.createElement('td'));
    tbody.appendChild(tr);
  }
  function table(es) {
    wrap.textContent = '';
    if (es.length < 2) { wrap.appendChild(text('p', 'Choose at least two companies to see them side by side.', 'small muted pad')); return; }
    var t = document.createElement('table');
    t.setAttribute('aria-label', 'Side-by-side comparison');
    var th = document.createElement('thead'), hr = document.createElement('tr');
    var first = text('th', 'Measure'); first.scope = 'col'; hr.appendChild(first);
    es.forEach(function (e, i) {
      var h = document.createElement('th'), a = text('a', e.ticker);
      h.scope = 'col';
      a.href = e.url;
      h.appendChild(a);
      h.appendChild(text('div', e.name || '', 'small muted'));
      h.style.borderTop = '3px solid ' + COLORS[i];
      h.style.whiteSpace = 'normal';
      hr.appendChild(h);
    });
    th.appendChild(hr);
    t.appendChild(th);
    var tb = document.createElement('tbody');
    addRow(tb, 'Basis', [], 'group');
    addRow(tb, 'Price (close)', es.map(function (e) { return ok(e.price) ? '$' + e.price.toFixed(2) + ' on ' + e.price_date : null; }));
    addRow(tb, 'Latest fiscal quarter in TTM', es.map(function (e) { return e.period.latest_quarter || na('not stored'); }));
    addRow(tb, 'Currency and basis', es.map(function (e) { return e.period.currency + ', ' + e.period.basis; }));
    addRow(tb, 'Lists', es.map(function (e) { return e.lists.join(', '); }));
    data.groups.forEach(function (g) {
      addRow(tb, g.title, [], 'group');
      g.rows.forEach(function (r) {
        addRow(tb, r.label, es.map(function (e) { var v = fmt(r.kind, e.metrics[r.key]); return v === null ? na(missingText(e, r.key)) : v; }));
      });
    });
    addRow(tb, 'Returns and drawdowns (price only, to each close)', [], 'group');
    data.returns.forEach(function (k) {
      addRow(tb, k + ' return', es.map(function (e) {
        var r = e.returns[k];
        if (!r || !ok(r.value)) return na('not enough history');
        var d = document.createElement('span');
        d.textContent = fmt('pct', r.value);
        d.appendChild(text('div', r.start ? r.start + ' to ' + r.end : (r.sessions ? r.sessions + ' sessions' : 'window') + ' to ' + r.end, 'small muted'));
        return d;
      }));
    });
    addRow(tb, 'Max drawdown, 5 years', es.map(function (e) {
      return fmt('pct', e.drawdowns.max_5y) || na(e.kind === 'watchlist' ? 'not stored for watchlist names' : 'not enough history');
    }));
    addRow(tb, 'From 52-week high', es.map(function (e) {
      return fmt('pct', e.drawdowns.from_52w_high) || na(e.kind === 'watchlist' ? 'not stored for watchlist names' : 'n/a');
    }));
    addRow(tb, 'Score components (0-100)', [], 'group');
    var keys = [];
    es.forEach(function (e) { Object.keys(e.components).forEach(function (k) { if (keys.indexOf(k) < 0) keys.push(k); }); });
    keys.forEach(function (k) {
      addRow(tb, k, es.map(function (e) {
        if (e.kind === 'watchlist') return na('not scored');
        if (!(k in e.components)) return na('not in the ' + e.profile + ' profile');
        return ok(e.components[k]) ? String(Math.round(e.components[k] * 100)) : na('missing, scored 0');
      }));
    });
    addRow(tb, 'Composite score', es.map(function (e) { return ok(e.composite) ? e.composite.toFixed(1) + ' (' + e.profile + ')' : na('not scored'); }));
    addRow(tb, 'Evidence', [], 'group');
    addRow(tb, 'Evidence quality', es.map(function (e) { return text('span', 'evidence: ' + (e.quality.label || e.quality.level), 'pill q-' + e.quality.level); }));
    addRow(tb, 'Missing inputs', es.map(function (e) {
      return e.quality.missing.length ? e.quality.missing.length + ': ' + e.quality.missing.join('; ').replace(/_/g, ' ') : '0';
    }));
    addRow(tb, 'Data flags', es.map(function (e) { return e.quality.flags.length ? e.quality.flags.join('; ') : 'none'; }));
    addRow(tb, 'Sources', es.map(function (e) {
      var d = document.createElement('span');
      e.sources.forEach(function (s, i) {
        if (i) d.appendChild(document.createTextNode(' · '));
        if (s.url) { var a = text('a', s.label); a.href = s.url; a.rel = 'noopener'; d.appendChild(a); }
        else d.appendChild(document.createTextNode(s.label));
        d.appendChild(text('span', ' (' + s.date + ')', 'muted'));
      });
      return d;
    }));
    t.appendChild(tb);
    wrap.appendChild(t);
  }
  function svgEl(name, attrs) {
    var n = document.createElementNS('http://www.w3.org/2000/svg', name);
    Object.keys(attrs).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    return n;
  }
  function drawChart(es) {
    chart.textContent = '';
    note.textContent = '';
    if (es.length < 2) return;
    // the return table's own start session when every selected name stores it, else the same calendar date
    var key = {1: '1y', 3: '3y', 5: '5y'}[win], starts = {};
    es.forEach(function (e) { var r = e.returns[key]; starts[r && r.start ? r.start : ''] = 1; });
    var shared = Object.keys(starts);
    var start = shared.length === 1 && shared[0] ? shared[0] : (parseInt(data.as_of.slice(0, 4), 10) - win) + data.as_of.slice(4);
    var r = rebase(es, start);
    if (!r.found) { note.textContent = r.reason; return; }
    var W = 720, H = 260, L = 44, R = 640, T = 12, B = 228, all = [];
    r.series.forEach(function (s) { all = all.concat(s.points); });
    var lo = Math.min.apply(null, all), hi = Math.max.apply(null, all);
    if (hi === lo) hi = lo + 1;
    var n = r.days.length;
    function X(i) { return L + (R - L) * i / Math.max(1, n - 1); }
    function Y(v) { return B - (B - T) * (v - lo) / (hi - lo); }
    var svg = svgEl('svg', {viewBox: '0 0 ' + W + ' ' + H, role: 'img', 'aria-label': 'Price paths rebased to 100 on ' + r.start + ': ' +
      r.series.map(function (s) { return s.ticker + ' ' + s.points[n - 1].toFixed(0); }).join(', ')});
    [lo, (lo + hi) / 2, hi].forEach(function (v) {
      svg.appendChild(svgEl('line', {x1: L, x2: R, y1: Y(v), y2: Y(v), stroke: 'var(--border)'}));
      var tx = svgEl('text', {x: L - 6, y: Y(v) + 4, 'text-anchor': 'end', 'font-size': '11', fill: 'var(--text-muted)'});
      tx.textContent = v.toFixed(0);
      svg.appendChild(tx);
    });
    [0, n - 1].forEach(function (i) {
      var tx = svgEl('text', {x: X(i), y: B + 18, 'text-anchor': i ? 'end' : 'start', 'font-size': '11', fill: 'var(--text-muted)'});
      tx.textContent = r.days[i];
      svg.appendChild(tx);
    });
    var used = [];
    r.series.forEach(function (s) {
      var i0 = sel.indexOf(s.ticker);
      var p = svgEl('path', {d: s.points.map(function (v, i) { return (i ? 'L' : 'M') + X(i).toFixed(1) + ',' + Y(v).toFixed(1); }).join(' '),
                             fill: 'none', stroke: COLORS[i0], 'stroke-width': '2'});
      if (DASH[i0]) p.setAttribute('stroke-dasharray', DASH[i0]);
      svg.appendChild(p);
      var y = Y(s.points[n - 1]) + 4;
      used.forEach(function (u) { if (Math.abs(u - y) < 13) y = u + 13; });
      used.push(y);
      var lb = svgEl('text', {x: R + 6, y: y, 'font-size': '12', fill: 'var(--text-primary)'});
      lb.textContent = s.ticker + ' ' + s.points[n - 1].toFixed(0);
      svg.appendChild(lb);
    });
    var legend = text('div', undefined, 'cmp-legend');
    r.series.forEach(function (s) {
      var i0 = sel.indexOf(s.ticker), sp = document.createElement('span'), ic = document.createElement('i');
      ic.style.borderTopColor = COLORS[i0];
      ic.style.borderTopStyle = i0 ? 'dashed' : 'solid';
      sp.appendChild(ic);
      sp.appendChild(document.createTextNode(s.ticker));
      legend.appendChild(sp);
    });
    chart.appendChild(legend);
    chart.appendChild(svg);
    var skipped = es.filter(function (e) { return !e.chart.dates.length; }).map(function (e) { return e.ticker; });
    note.textContent = 'Rebased to 100 on ' + r.start + ' (the first date every name has), ' + n + ' common weekly points to ' + r.end +
      '; no dates are interpolated. Price return, dividends excluded.' + (skipped.length ? ' Not charted (no stored path): ' + skipped.join(', ') + '.' : '');
  }
  function update(msg) {
    chips.textContent = '';
    sel.forEach(function (t, i) {
      var li = document.createElement('li'), ic = document.createElement('i');
      ic.style.borderTopColor = COLORS[i];
      li.appendChild(ic);
      li.appendChild(document.createTextNode(t));
      var b = text('button', '×');
      b.type = 'button';
      b.setAttribute('aria-label', 'Remove ' + t);
      b.addEventListener('click', function () { sel.splice(sel.indexOf(t), 1); update('Removed ' + t + '.'); pick.focus(); });
      li.appendChild(b);
      chips.appendChild(li);
    });
    var es = sel.map(function (t) { return byT[t]; });
    hint.textContent = msg || (sel.length < 2 ? 'Choose at least ' + (2 - sel.length) + ' more.' : sel.length + ' of ' + rules.max_names + ' selected.');
    flags.textContent = '';
    var f = sel.length >= 2 ? comparability(es) : [];
    if (f.length) {
      var bx = text('div', undefined, 'banner warn'), ul = text('ul', undefined, 'tight small');
      bx.appendChild(text('strong', 'Check before comparing'));
      f.forEach(function (x) { ul.appendChild(text('li', x)); });
      bx.appendChild(ul);
      flags.appendChild(bx);
    }
    table(es);
    drawChart(es);
    try { history.replaceState(null, '', sel.length ? '#' + sel.join(',') : location.pathname); } catch (e) {}
  }
  function add(t) {
    if (!t || !byT[t]) return;
    if (sel.indexOf(t) >= 0) { update(t + ' is already selected.'); return; }
    if (sel.length >= rules.max_names) { update('Up to ' + rules.max_names + ' companies; remove one first.'); return; }
    sel.push(t);
    pick.value = '';
    update('Added ' + t + '.');
  }
  document.getElementById('cmp-add').addEventListener('click', function () { add(pick.value); });
  pick.addEventListener('keydown', function (ev) { if (ev.key === 'Enter') { ev.preventDefault(); add(pick.value); } });
  document.querySelectorAll('[data-cmp-window] button').forEach(function (b) {
    b.addEventListener('click', function () {
      win = parseInt(b.getAttribute('data-win'), 10);
      document.querySelectorAll('[data-cmp-window] button').forEach(function (x) { x.setAttribute('aria-pressed', x === b ? 'true' : 'false'); });
      drawChart(sel.map(function (t) { return byT[t]; }));
    });
  });
  decodeURIComponent(location.hash.slice(1)).split(',').forEach(function (t) {
    t = t.trim().toUpperCase();
    if (byT[t] && sel.indexOf(t) < 0 && sel.length < rules.max_names) sel.push(t);
  });
  update();
})();
"""
